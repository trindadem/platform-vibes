"""svc-integracoes · lógica de negócio pura. Fonte da verdade: specs/integracoes.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py, e vira a activity "integracoes.<método>".

As conexões da organização com o mundo de fora. Neste bloco: a caixa de entrada (e-mail encaminhado ao endereço da
organização; no ambiente local o Mailpit avisa e entrega a mensagem) e o banco simulado (agenda e confirma depois de
alguns segundos, ou à mão). O que chega sai em events.integracoes.evento: o svc-processos inicia as execuções e entrega
as mensagens que elas esperam.
"""
import asyncio
import base64
import email
import io
import os
import re
import secrets
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any, TypeVar

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from exovision.harness.mcp import MCPClient, MCPError, MCPTool, StreamableHTTPTransport
from exovision.harness.mcp.toolset import blocks_to_result
from pypdf import PdfReader

from core.envelope import ServiceError
from core.http_client import http
from core.nats_bus import bus
from core.security import acting_as, assert_public_url, current, current_tenant, system
from core.storage import storage
from core.surreal import Migration, db
from core.temporal_runner import activities, runner

from schemas import (
    ACCEPTED,
    BANK_OPERATORS,
    CONEXOES,
    DOCUMENT_MAX_BYTES,
    DOCUMENTOS,
    EVENT_SUBJECT,
    LIVE_CONEXOES,
    LIVE_DOCUMENTOS,
    LIVE_PAGAMENTOS,
    LIVE_SERVIDORES,
    MCP_MAX_BYTES,
    MCP_TIMEOUT,
    PAGAMENTOS,
    SERVICE,
    SERVIDORES,
    TASK_QUEUE,
    TEXT_MAX_CHARS,
    WRITERS,
    CATALOGO,
    AgendarPagamento,
    AvisoEmail,
    Catalogo,
    ChamadaMcp,
    Conexao,
    ConexaoMudou,
    ConexaoRef,
    Conexoes,
    Documento,
    DocumentoMudou,
    DocumentoPage,
    DocumentoQuery,
    DocumentoRef,
    DocumentoTexto,
    Empty,
    EventoExterno,
    FerramentaDisponivel,
    FerramentaMcp,
    FerramentasDisponiveis,
    IntegracoesSettings,
    Link,
    NovaConexao,
    NovoServidorMcp,
    Pagamento,
    PagamentoAgendado,
    PagamentoMudou,
    PagamentoPage,
    PagamentoQuery,
    PagamentoRef,
    PagamentoSimulado,
    Recebidos,
    ResultadoMcp,
    Resumo,
    ServidorMcp,
    ServidorMudou,
    ServidoresMcp,
    ServidorRef,
)

MIGRATIONS: list[Migration] = []
settings = IntegracoesSettings()
_NOMES = {"caixa_entrada": "Caixa de entrada", "banco_simulado": "Banco (simulado)"}


@activities("integracoes")
class IntegracoesService:
    # ── Conexões ─────────────────────────────────────────────────────────────

    async def conexoes(self, data: Empty) -> Conexoes:
        rows = await db.query(f"SELECT * FROM {CONEXOES} WHERE tenant = $tenant ORDER BY created_at")
        return Conexoes(itens=[Conexao.model_validate(r) for r in rows])

    async def conectar(self, data: NovaConexao) -> Conexao:
        """Uma conexão de cada tipo por organização. Caixa de entrada ganha um endereço próprio."""
        _writer()
        dados: dict[str, Any] = {"tipo": data.tipo, "nome": data.nome or _NOMES[data.tipo]}
        if data.tipo == "caixa_entrada":
            codigo = secrets.token_hex(4)
            dados |= {"codigo": codigo, "endereco": f"{current_tenant()}.{codigo}@{settings.dominio}"}
        else:
            dados["confirmar_apos"] = data.confirmar_apos
        try:
            row = await db.create(CONEXOES, dados)
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_INTEGRACOES_JA_CONECTADA", "Esta conexão já existe na organização.", 409) from None
            raise
        conexao = Conexao.model_validate(row)
        await bus.live(LIVE_CONEXOES, ConexaoMudou(id=conexao.id, action="conectada"))
        return conexao

    async def desconectar(self, data: ConexaoRef) -> Conexao:
        _writer()
        row = await db.select(f"{CONEXOES}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_INTEGRACOES_NAO_ENCONTRADA", "Conexão não encontrada.", 404)
        await db.delete(f"{CONEXOES}:{data.id}")
        await bus.live(LIVE_CONEXOES, ConexaoMudou(id=data.id, action="removida"))
        return Conexao.model_validate(row)

    async def resumo(self, data: Empty) -> Resumo:
        conexoes = {c.tipo: c for c in (await self.conexoes(Empty())).itens}
        documentos = await db.query(f"SELECT count() AS n FROM {DOCUMENTOS} WHERE tenant = $tenant GROUP ALL")
        agendados = await db.query(f"SELECT count() AS n FROM {PAGAMENTOS} WHERE tenant = $tenant AND status = 'agendado' GROUP ALL")
        caixa = conexoes.get("caixa_entrada")
        return Resumo(caixa_entrada=caixa.endereco if caixa else None, banco="banco_simulado" in conexoes,
                      documentos=documentos[0]["n"] if documentos else 0, agendados=agendados[0]["n"] if agendados else 0)

    # ── Caixa de entrada ─────────────────────────────────────────────────────

    async def documentos(self, data: DocumentoQuery) -> DocumentoPage:
        return await db.page(DOCUMENTOS, data, DocumentoPage)

    async def arquivo(self, data: DocumentoRef) -> Link:
        """Link (5 min) para abrir o documento recebido."""
        row = await _documento(data.id)
        return Link(url=storage.url(row["chave"], filename=row["nome"], content_type=row["tipo"]), nome=row["nome"], tipo=row["tipo"])

    async def documento_texto(self, data: DocumentoRef) -> DocumentoTexto:
        """rpc.integracoes.documento: o texto para o agente que lê o documento num passo de processo."""
        row = await _documento(data.id)
        return DocumentoTexto(id=data.id, nome=row["nome"], tipo=row["tipo"], de=row.get("de"), assunto=row.get("assunto"),
                              texto=row.get("texto") or "")

    async def receber_email(self, data: AvisoEmail) -> Recebidos:
        """Ambiente local: o Mailpit avisou que chegou um e-mail. A mensagem (RFC 822) vem dele; cada destinatário
        <organização>.<código>@<domínio> com caixa de entrada conectada recebe os anexos como documentos."""
        if not settings.mailpit_url:
            raise ServiceError("ERRO_INTEGRACOES_SEM_PROVEDOR", "Nenhum provedor de e-mail configurado.", 404)
        resposta = await http.get(f"{settings.mailpit_url.rstrip('/')}/api/v1/message/{data.ID}/raw",
                                  allow_http=True, allow_private=True, max_bytes=DOCUMENT_MAX_BYTES * 3)
        if resposta.status_code != 200:
            raise ServiceError("ERRO_INTEGRACOES_EMAIL", "O e-mail avisado não foi encontrado.", 404)
        return await self._ingerir(resposta.content, origem=f"mailpit-{data.ID}")

    async def _ingerir(self, bruto: bytes, *, origem: str) -> Recebidos:
        mensagem = email.message_from_bytes(bruto, policy=policy.default)
        assert isinstance(mensagem, EmailMessage)
        destinos = [addr.lower() for _, addr in getaddresses(mensagem.get_all("To", []) + mensagem.get_all("Cc", []))]
        total = 0
        for endereco in dict.fromkeys(destinos):
            match = re.fullmatch(rf"([a-z0-9]{{1,40}})\.([a-f0-9]{{8}})@{re.escape(settings.dominio.lower())}", endereco)
            if not match:
                continue
            with acting_as(system(SERVICE, match.group(1))):
                conexao = await db.query(f"SELECT * FROM {CONEXOES} WHERE tenant = $tenant AND tipo = 'caixa_entrada' "
                                         "AND codigo = $codigo LIMIT 1", codigo=match.group(2))
                if conexao:
                    total += await _guardar_anexos(mensagem, Conexao.model_validate(conexao[0]), origem)
        return Recebidos(documentos=total)

    # ── Banco simulado ───────────────────────────────────────────────────────

    async def agendar_pagamento(self, data: AgendarPagamento) -> PagamentoAgendado:
        """rpc.integracoes.banco_agendar: agenda no banco conectado. O simulado confirma depois de confirmar_apos s."""
        banco = await db.query(f"SELECT * FROM {CONEXOES} WHERE tenant = $tenant AND tipo = 'banco_simulado' LIMIT 1")
        if not banco:
            raise ServiceError("ERRO_INTEGRACOES_SEM_BANCO", "Conecte o banco da empresa em Integrações para agendar pagamentos.", 409)
        hoje = date.today().isoformat()
        data_agendada = data.vencimento if data.vencimento and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.vencimento) and data.vencimento > hoje else hoje
        pagamento_id = "PG-" + secrets.token_hex(4).upper()
        row = await db.create(PAGAMENTOS, {"pagamento_id": pagamento_id, "valor": data.valor, "data": data_agendada,
                                           "fornecedor": data.fornecedor, "linha_digitavel": data.linha_digitavel, "status": "agendado"})
        pagamento = Pagamento.model_validate(row)
        await runner.start_workflow(_workflow_pagamento(), PagamentoSimulado(id=pagamento.id, segundos=int(banco[0].get("confirmar_apos") or 30)),
                                    task_queue=TASK_QUEUE, id=f"pagamento-{current_tenant()}-{pagamento.id}")
        await bus.live(LIVE_PAGAMENTOS, PagamentoMudou(id=pagamento.id, action="agendado"))
        return PagamentoAgendado(pagamento_id=pagamento_id, data=data_agendada)

    async def pagamentos(self, data: PagamentoQuery) -> PagamentoPage:
        return await db.page(PAGAMENTOS, data, PagamentoPage)

    async def confirmar_pagamento(self, data: PagamentoRef) -> Pagamento:
        """O banco pagou (o simulado, sozinho, ou alguém à mão): avisa a execução que espera pelo comprovante."""
        who = current()
        if who is None or not (who.is_system or BANK_OPERATORS & who.roles):
            raise ServiceError("ERRO_INTEGRACOES_FORBIDDEN", "Só donos, administradores e operadores confirmam pagamentos.", 403)
        row = await db.select(f"{PAGAMENTOS}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_INTEGRACOES_NAO_ENCONTRADO", "Pagamento não encontrado.", 404)
        if row["status"] == "pago":
            return Pagamento.model_validate(row)
        row = await db.merge(f"{PAGAMENTOS}:{data.id}", {"status": "pago", "pago_em": datetime.now(UTC)})
        pagamento = Pagamento.model_validate(row)
        await bus.publish(EVENT_SUBJECT, EventoExterno(
            nome="banco.pago", chave=pagamento.pagamento_id,
            dados={"pagamento_id": pagamento.pagamento_id, "valor": pagamento.valor, "pago_em": pagamento.pago_em.isoformat() if pagamento.pago_em else None},
        ), msg_id=f"banco-pago-{current_tenant()}-{pagamento.pagamento_id}")
        await bus.live(LIVE_PAGAMENTOS, PagamentoMudou(id=pagamento.id, action="pago"))
        return pagamento

    # ── Servidores MCP: ferramentas dos sistemas da empresa para os agentes ──

    async def catalogo(self, data: Empty) -> Catalogo:
        """O que dá para conectar: o que já existe e o que vem com o fornecedor escolhido (briefing.md §14)."""
        return CATALOGO

    async def servidores(self, data: Empty) -> ServidoresMcp:
        rows = await db.query(f"SELECT * FROM {SERVIDORES} WHERE tenant = $tenant ORDER BY nome")
        return ServidoresMcp(itens=[_servidor(r) for r in rows])

    async def conectar_mcp(self, data: NovoServidorMcp) -> ServidorMcp:
        """Conecta com a credencial, lista as ferramentas e guarda cada uma pinada; a credencial fica cifrada aqui."""
        _writer()
        ferramentas, servidor = await _mcp(data.url, data.cabecalho, data.segredo, _descobrir)
        try:
            row = await db.create(SERVIDORES, {
                "nome": data.nome, "url": data.url, "cabecalho": data.cabecalho if data.segredo else None,
                "segredo": _cifrar(data.nome, data.segredo) if data.segredo else None, "servidor": servidor,
                "ferramentas": [f.model_dump() for f in ferramentas], "atualizado_em": datetime.now(UTC),
            })
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_INTEGRACOES_JA_CONECTADA", "Já existe um servidor MCP com este nome.", 409) from None
            raise
        conectado = _servidor(row)
        await bus.live(LIVE_SERVIDORES, ServidorMudou(id=conectado.id, action="conectado"))
        return conectado

    async def atualizar_mcp(self, data: ServidorRef) -> ServidorMcp:
        """Lista de novo e aceita as definições atuais (inclusive as que mudaram): é a confirmação de quem administra."""
        _writer()
        row = await _servidor_row(data.id)
        ferramentas, servidor = await _mcp(row["url"], row.get("cabecalho"), _segredo(row), _descobrir)
        atualizado = _servidor(await db.merge(f"{SERVIDORES}:{data.id}", {
            "ferramentas": [f.model_dump() for f in ferramentas], "servidor": servidor, "atualizado_em": datetime.now(UTC)}))
        await bus.live(LIVE_SERVIDORES, ServidorMudou(id=data.id, action="atualizado"))
        return atualizado

    async def remover_mcp(self, data: ServidorRef) -> ServidorMcp:
        _writer()
        row = await _servidor_row(data.id)
        await db.delete(f"{SERVIDORES}:{data.id}")
        await bus.live(LIVE_SERVIDORES, ServidorMudou(id=data.id, action="removido"))
        return _servidor(row)

    async def ferramentas(self, data: Empty) -> FerramentasDisponiveis:
        """rpc.integracoes.ferramentas: as ferramentas que os agentes da organização podem usar (fora de quarentena)."""
        itens = [FerramentaDisponivel(servidor=s.id, servidor_nome=s.nome, nome=f.nome, descricao=f.descricao,
                                      parametros=f.parametros, risco=f.risco)
                 for s in (await self.servidores(Empty())).itens for f in s.ferramentas if not f.quarentena]
        return FerramentasDisponiveis(itens=itens)

    async def chamar_mcp(self, data: ChamadaMcp) -> ResultadoMcp:
        """rpc.integracoes.mcp_chamar: confere que a ferramenta é a mesma que foi pinada e chama com a credencial."""
        row = await _servidor_row(data.servidor)
        pinada = next((FerramentaMcp.model_validate(f) for f in row.get("ferramentas") or [] if f["nome"] == data.ferramenta), None)
        if pinada is None:
            raise ServiceError("ERRO_INTEGRACOES_FERRAMENTA", f"O servidor {row['nome']} não tem a ferramenta {data.ferramenta}.", 404)
        if pinada.quarentena:
            raise ServiceError("ERRO_INTEGRACOES_QUARENTENA", f"{data.ferramenta} está em quarentena: {pinada.quarentena}", 409)

        def chamar(cliente: MCPClient) -> tuple[str | None, dict[str, Any] | None]:
            atual = next((t for t in cliente.list_tools() if t.name == data.ferramenta), None)
            if atual is None or atual.digest != pinada.digest:
                return "sumiu do servidor" if atual is None else "a definição mudou desde que foi conectada", None
            return None, cliente.call_tool(data.ferramenta, data.argumentos)

        mudou, bruto = await _mcp(row["url"], row.get("cabecalho"), _segredo(row), chamar)
        if mudou:  # possível troca maliciosa da ferramenta: quarentena até alguém atualizar o servidor em Integrações
            motivo = f"A ferramenta {mudou}: confira e atualize o servidor em Integrações."
            ferramentas = [{**f, "quarentena": motivo} if f["nome"] == data.ferramenta else f for f in row.get("ferramentas") or []]
            await db.merge(f"{SERVIDORES}:{data.servidor}", {"ferramentas": ferramentas})
            await bus.live(LIVE_SERVIDORES, ServidorMudou(id=data.servidor, action="quarentena"))
            raise ServiceError("ERRO_INTEGRACOES_QUARENTENA", motivo, 409)
        resultado = blocks_to_result(bruto or {}, tool=data.ferramenta)
        return ResultadoMcp(ok=resultado.ok, texto=resultado.text, dados=resultado.metadata.get("structured"))


# ── Ajudantes ────────────────────────────────────────────────────────────────

def _writer() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_INTEGRACOES_FORBIDDEN", "Só donos e administradores mexem nas conexões.", 403)


def _workflow_pagamento() -> Any:
    from workflows import PagamentoSimuladoWorkflow  # o workflow importa este arquivo: a referência é resolvida na hora

    return PagamentoSimuladoWorkflow.run


async def _documento(doc_id: str) -> dict[str, Any]:
    row = await db.select(f"{DOCUMENTOS}:{doc_id}")
    if row is None:
        raise ServiceError("ERRO_INTEGRACOES_NAO_ENCONTRADO", "Documento não encontrado.", 404)
    return row


async def _guardar_anexos(mensagem: EmailMessage, conexao: Conexao, origem: str) -> int:
    """Cada anexo aceito vira um documento (sem anexo, o corpo do e-mail); cada documento novo, um evento."""
    de = str(mensagem.get("From", ""))[:200] or None
    assunto = str(mensagem.get("Subject", ""))[:300] or None
    partes: list[tuple[str, str, bytes]] = []
    for i, anexo in enumerate(mensagem.iter_attachments()):
        tipo = anexo.get_content_type().lower()
        conteudo = anexo.get_payload(decode=True) or b""
        if tipo in ACCEPTED and 0 < len(conteudo) <= DOCUMENT_MAX_BYTES:
            partes.append((anexo.get_filename() or f"anexo-{i + 1}", tipo, conteudo))
    if not partes:
        corpo = mensagem.get_body(preferencelist=("plain",))
        texto = corpo.get_content() if corpo is not None else ""
        if texto.strip():
            partes.append(("mensagem.txt", "text/plain", texto.encode()[:DOCUMENT_MAX_BYTES]))
    novos = 0
    for i, (nome, tipo, conteudo) in enumerate(partes):
        chave_origem = f"{origem}-{i}"
        if await db.query(f"SELECT id FROM {DOCUMENTOS} WHERE tenant = $tenant AND origem_id = $o LIMIT 1", o=chave_origem):
            continue  # o mesmo aviso de novo: não duplica
        guardado = await storage.save(conteudo, filename=nome, content_type=tipo, max_bytes=DOCUMENT_MAX_BYTES, folder="entrada")
        texto = _texto(conteudo, tipo)
        try:
            row = await db.create(DOCUMENTOS, {"origem": "email", "origem_id": chave_origem, "conexao": conexao.id, "de": de,
                                               "assunto": assunto, "nome": guardado.filename, "tipo": tipo, "tamanho": guardado.size,
                                               "chave": guardado.key, "texto": texto, "tem_texto": bool(texto.strip())})
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":  # outro aviso do mesmo e-mail chegou junto
                await storage.delete(guardado.key)
                continue
            raise
        documento = Documento.model_validate(row)
        await bus.publish(EVENT_SUBJECT, EventoExterno(
            nome="documento.recebido",
            dados={"documento_id": documento.id, "origem": "email", "de": de, "assunto": assunto, "nome": documento.nome},
        ), msg_id=f"documento-{current_tenant()}-{documento.id}")
        await bus.live(LIVE_DOCUMENTOS, DocumentoMudou(id=documento.id, action="recebido"))
        novos += 1
    return novos


def _texto(conteudo: bytes, tipo: str) -> str:
    """Texto de PDF (com camada de texto), XML ou texto puro; imagem e PDF escaneado: vazio (sem OCR)."""
    try:
        if tipo == "application/pdf":
            leitor = PdfReader(io.BytesIO(conteudo))
            texto = "\n\n".join((pagina.extract_text() or "") for pagina in leitor.pages[:20])
        elif tipo.startswith("text/") or tipo.endswith("/xml"):
            texto = conteudo.decode("utf-8", errors="replace")
        else:
            texto = ""
    except Exception:  # noqa: BLE001 - arquivo corrompido: o agente vê que não há texto e pede ajuda
        texto = ""
    return texto[:TEXT_MAX_CHARS]


# ── Servidores MCP ───────────────────────────────────────────────────────────

T = TypeVar("T")


class _Resposta:
    """O que o transporte do AgentExo espera do opener (urllib): status, headers e read()."""

    def __init__(self, resposta: httpx.Response) -> None:
        self.status, self.headers, self._corpo = resposta.status_code, resposta.headers, resposta.content

    def read(self) -> bytes:
        return self._corpo

    def close(self) -> None:
        return None

    def __enter__(self) -> "_Resposta":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


async def _mcp(url: str, cabecalho: str | None, segredo: str | None, uso: Callable[[MCPClient], T]) -> T:
    """Uma sessão MCP com o cliente do AgentExo (síncrono, numa thread); cada requisição sai pelo http do core: SSRF
    conferido a cada uma (rede interna só no ambiente local), sem redirect, com teto de tamanho."""
    local = settings.environment == "development"
    try:
        await assert_public_url(url, allow_http=local, allow_private=local)
    except ServiceError:
        raise ServiceError("ERRO_INTEGRACOES_URL", "O endereço do servidor MCP precisa ser https e público.", 422) from None
    loop = asyncio.get_running_loop()

    def abrir(pedido: urllib.request.Request, timeout: float) -> _Resposta:
        coro = http.request(pedido.get_method(), pedido.full_url, content=pedido.data, headers=dict(pedido.header_items()),
                            timeout=min(timeout, MCP_TIMEOUT), allow_http=local, allow_private=local, max_bytes=MCP_MAX_BYTES)
        resposta = asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=MCP_TIMEOUT + 5)
        if resposta.status_code >= 400:
            raise urllib.error.HTTPError(pedido.full_url, resposta.status_code, resposta.reason_phrase, resposta.headers,  # type: ignore[arg-type]
                                         io.BytesIO(resposta.content))
        return _Resposta(resposta)

    def sessao() -> T:
        transporte = StreamableHTTPTransport(url, headers={cabecalho: segredo} if cabecalho and segredo else {}, opener=abrir)
        cliente = MCPClient(transporte, timeout=MCP_TIMEOUT, client_name="cogniventure")
        try:
            return uso(cliente)
        finally:
            cliente.close()

    try:
        return await asyncio.to_thread(sessao)
    except MCPError as exc:  # sem ecoar o corpo da resposta (pode trazer pedaços da credencial)
        status = re.search(r"HTTP (\d{3})", str(exc))
        if status and status.group(1) in ("401", "403"):
            raise ServiceError("ERRO_INTEGRACOES_CREDENCIAL", "O servidor MCP recusou a credencial.", 422) from None
        detalhe = f" (HTTP {status.group(1)})" if status else ""
        raise ServiceError("ERRO_INTEGRACOES_MCP", f"O servidor MCP não respondeu como esperado{detalhe}.", 502) from None


def _descobrir(cliente: MCPClient) -> tuple[list[FerramentaMcp], str]:
    ferramentas = [_ferramenta(t) for t in cliente.list_tools()]
    info = cliente.server_info
    return ferramentas, " ".join(str(info.get(k) or "") for k in ("name", "version")).strip()[:120]


def _ferramenta(t: MCPTool) -> FerramentaMcp:
    """Piso de risco externa (código de terceiro falando com o mundo); a anotação só sobe. Texto oculto é quarentena."""
    quarentena = None
    if t.concealed:
        quarentena = "a descrição tem caractere invisível (o que a tela mostra e o que o agente lê divergiriam)"
    elif t.task_support == "required":
        quarentena = "a ferramenta exige execução como tarefa, que a plataforma ainda não usa"
    return FerramentaMcp(nome=t.name, titulo=t.title or None, descricao=t.description[:2000] or f"Ferramenta {t.name}",
                         parametros=t.input_schema, risco="irreversivel" if t.annotations.get("destructiveHint") is True else "externa",
                         digest=t.digest, quarentena=quarentena)


async def _servidor_row(servidor_id: str) -> dict[str, Any]:
    row = await db.select(f"{SERVIDORES}:{servidor_id}")
    if row is None:
        raise ServiceError("ERRO_INTEGRACOES_NAO_ENCONTRADA", "Servidor MCP não encontrado.", 404)
    return row


def _servidor(row: dict[str, Any]) -> ServidorMcp:
    return ServidorMcp.model_validate({**{k: v for k, v in row.items() if k != "segredo"}, "tem_segredo": bool(row.get("segredo"))})


def _aead() -> AESGCM:
    """Conferida no boot (main.py): sem INTEGRACOES_SECRETS_KEY de 32 bytes o serviço não sobe."""
    raw = settings.secrets_key.get_secret_value() if settings.secrets_key else ""
    chave = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    if len(chave) != 32:
        raise RuntimeError("INTEGRACOES_SECRETS_KEY precisa de 32 bytes (base64url): rode uv run python -m core.security keygen")
    return AESGCM(chave)


def _cifrar(nome: str, segredo: str) -> str:
    """AES-256-GCM preso à organização e ao nome do servidor: copiado para outro registro, não abre."""
    nonce = os.urandom(12)
    return base64.urlsafe_b64encode(nonce + _aead().encrypt(nonce, segredo.encode(), f"{current_tenant()}:{nome}".encode())).decode()


def _segredo(row: dict[str, Any]) -> str | None:
    if not row.get("segredo"):
        return None
    bruto = base64.urlsafe_b64decode(row["segredo"])
    return _aead().decrypt(bruto[:12], bruto[12:], f"{current_tenant()}:{row['nome']}".encode()).decode()
