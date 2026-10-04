"""svc-agentes · lógica de negócio pura. Fonte da verdade: specs/agentes.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py, e vira a activity "agentes.<método>".

Os agentes da organização (briefing.md §7.1): instrução, modelo (do svc-ai), ferramentas do catálogo (as da
plataforma e as dos servidores MCP conectados em Integrações), a política de cada ferramenta (permitir ou perguntar) e a
suíte de avaliação. Nasce rascunho; vira verificado quando a suíte passa; confiável, só por decisão do staff. Mudar o
que ele faz volta a rascunho. O agente roda no laço do AgentExo (llm.run_agent); ferramenta MCP é chamada pelo
svc-integracoes, que guarda a credencial; ação de pacote, pelo próprio pacote (rpc.<pacote>.acao, core/processes.py).
Ferramenta irreversível só entra pedindo aprovação. Um passo de processo usa um agente verificado por rpc.agentes.executar.
"""
import inspect
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from nats.errors import Error as NatsError
from pydantic import BaseModel, Field, create_model

from core.envelope import ServiceError
from core.llm import SchemaTool, llm
from core.nats_bus import bus
from core.processes import ActionCall, ActionResult, action_subject
from core.security import acting_as, current, current_tenant, system
from core.surreal import Migration, db
from core.temporal_runner import activities, runner

from schemas import (
    ACOES_SUBJECT,
    AGENTES,
    BUSCA_SUBJECT,
    DOCUMENTO_SUBJECT,
    FERRAMENTAS_SUBJECT,
    INSTRUCOES_PLATAFORMA,
    LIVE_AGENTES,
    MCP_SUBJECT,
    SERVICE,
    STAFF,
    TASK_QUEUE,
    WRITERS,
    Achados,
    AcoesDisponiveis,
    Agente,
    AgenteMudou,
    AgenteRef,
    Agentes,
    Avaliacao,
    BuscaQuery,
    Caso,
    CatalogoFerramentas,
    ChamadaMcp,
    Consulta,
    DocumentoRef,
    DocumentoTexto,
    EdicaoAgente,
    Empty,
    Execucao,
    ExecutarAgente,
    FerramentaCatalogo,
    FerramentasDisponiveis,
    LeituraDocumento,
    ListaAgentes,
    NovoAgente,
    PedidoAjuda,
    ResultadoCaso,
    ResultadoMcp,
    ResumoAgente,
    SuiteRef,
    Teste,
    Tipo,
)

MIGRATIONS: list[Migration] = []
PLATAFORMA = [
    FerramentaCatalogo(ref="documento", nome="Ler o documento", origem="plataforma", risco="leitura",
                       descricao="Lê o texto de um documento recebido pela caixa de entrada (o do gatilho do processo)."),
    FerramentaCatalogo(ref="conhecimento", nome="Buscar no conhecimento", origem="plataforma", risco="leitura",
                       descricao="Busca no conhecimento da empresa (briefing, site e documentos), com a fonte."),
]
_FUNCIONAIS = ("instrucao", "modelo", "ferramentas", "casos")  # o que muda o que o agente faz: volta a rascunho


@activities("agentes")
class AgentesService:
    # ── Os agentes da organização ────────────────────────────────────────────

    async def agentes(self, data: Empty) -> Agentes:
        rows = await db.query(f"SELECT * FROM {AGENTES} WHERE tenant = $tenant ORDER BY nome")
        return Agentes(itens=[Agente.model_validate(r) for r in rows])

    async def agente(self, data: AgenteRef) -> Agente:
        return Agente.model_validate(await _row(data.id))

    async def catalogo(self, data: Empty) -> CatalogoFerramentas:
        """As ferramentas que um agente pode usar: as da plataforma, as ações dos pacotes ligados no plano e as dos
        servidores MCP da organização. Quem não respondeu fica de fora, com o aviso (processos, integracoes)."""
        try:
            acoes = await bus.request(ACOES_SUBJECT, Empty(), AcoesDisponiveis, timeout=10)
        except (NatsError, TimeoutError, ServiceError):
            acoes = None
        pacotes = [FerramentaCatalogo(ref=f"acao:{a.name}", nome=a.title, descricao=a.description, origem="pacote", pacote=a.pacote,
                                      risco=a.risk, parametros=a.input_schema) for a in (acoes.itens if acoes else [])]
        try:
            disponiveis = await bus.request(FERRAMENTAS_SUBJECT, Empty(), FerramentasDisponiveis, timeout=10)
        except (NatsError, TimeoutError, ServiceError):
            return CatalogoFerramentas(itens=[*PLATAFORMA, *pacotes], integracoes=False, processos=acoes is not None)
        mcp = [FerramentaCatalogo(ref=f"mcp:{f.servidor}:{f.nome}", nome=f.nome, descricao=f.descricao, origem="mcp",
                                  servidor_nome=f.servidor_nome, risco=f.risco, parametros=f.parametros) for f in disponiveis.itens]
        return CatalogoFerramentas(itens=[*PLATAFORMA, *pacotes, *mcp], processos=acoes is not None)

    async def criar(self, data: NovoAgente) -> Agente:
        _escritor()
        await _conferir_ferramentas(self, data.ferramentas)
        _conferir_casos(data.casos)
        try:
            row = await db.create(AGENTES, {**data.model_dump(), "status": "rascunho", "versao": 1, "avaliando": False,
                                            "avaliacao": None, "confiavel_por": None})
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_AGENTES_NOME", "Já existe um agente com este nome.", 409) from None
            raise
        agente = Agente.model_validate(row)
        await bus.live(LIVE_AGENTES, AgenteMudou(id=agente.id, action="criado"))
        return agente

    async def editar(self, data: EdicaoAgente) -> Agente:
        """Mudar instrução, modelo, ferramentas ou casos sobe a versão e volta a rascunho: a suíte roda de novo."""
        _escritor()
        atual = Agente.model_validate(await _row(data.id))
        mudancas = data.model_dump(exclude={"id"}, exclude_none=True)
        if "ferramentas" in mudancas:
            await _conferir_ferramentas(self, data.ferramentas or [])
        if "casos" in mudancas:
            _conferir_casos(data.casos or [])
        funcional = any(k in mudancas and mudancas[k] != _jsonavel(getattr(atual, k)) for k in _FUNCIONAIS)
        if funcional:
            mudancas |= {"versao": atual.versao + 1, "status": "rascunho", "confiavel_por": None}
        try:
            row = await db.merge(f"{AGENTES}:{data.id}", mudancas)
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_AGENTES_NOME", "Já existe um agente com este nome.", 409) from None
            raise
        await bus.live(LIVE_AGENTES, AgenteMudou(id=data.id, action="alterado"))
        return Agente.model_validate(row)

    async def remover(self, data: AgenteRef) -> Agente:
        _escritor()
        agente = Agente.model_validate(await _row(data.id))
        await db.delete(f"{AGENTES}:{data.id}")
        await bus.live(LIVE_AGENTES, AgenteMudou(id=data.id, action="removido"))
        return agente

    # ── Suíte e confiança ────────────────────────────────────────────────────

    async def avaliar(self, data: AgenteRef) -> Agente:
        """Roda a suíte em segundo plano (workflow durável); passando inteira, a versão avaliada fica verificada."""
        _escritor()
        agente = Agente.model_validate(await _row(data.id))
        if not agente.casos:
            raise ServiceError("ERRO_AGENTES_SEM_CASOS", "Escreva pelo menos um caso na suíte antes de avaliar.", 409)
        row = await db.merge(f"{AGENTES}:{data.id}", {"avaliando": True})
        from workflows import AvaliarSuiteWorkflow  # o workflow importa este arquivo: a referência é resolvida na hora

        await runner.start_workflow(AvaliarSuiteWorkflow.run, SuiteRef(id=agente.id, versao=agente.versao), task_queue=TASK_QUEUE,
                                    id=f"suite-{agente.id}-v{agente.versao}-{int(datetime.now(UTC).timestamp())}")
        await bus.live(LIVE_AGENTES, AgenteMudou(id=data.id, action="avaliando"))
        return Agente.model_validate(row)

    async def rodar_suite(self, data: SuiteRef) -> Agente:
        """Activity: cada caso roda o agente de verdade (modelo e ferramentas) e compara com o esperado."""
        agente = Agente.model_validate(await _row(data.id))
        resultados = []
        for caso in agente.casos:
            execucao = await _executar(agente, caso.tarefa, _contexto(caso.dados), {c: _tipo(v) for c, v in caso.esperado.items()})
            resultados.append(_julgar(caso, execucao))
        avaliacao = Avaliacao(versao=data.versao, ok=all(r.ok for r in resultados), resultados=resultados, em=datetime.now(UTC))
        atual = Agente.model_validate(await _row(data.id))
        mudancas: dict[str, Any] = {"avaliando": False, "avaliacao": avaliacao.model_dump(mode="json")}
        if atual.versao == data.versao:  # mudou enquanto a suíte rodava: o resultado não verifica a versão nova
            mudancas["status"] = ("confiavel" if atual.status == "confiavel" else "verificado") if avaliacao.ok else "rascunho"
        row = await db.merge(f"{AGENTES}:{data.id}", mudancas)
        await bus.live(LIVE_AGENTES, AgenteMudou(id=data.id, action="avaliado"))
        return Agente.model_validate(row)

    async def encerrar_suite(self, data: SuiteRef) -> Agente:
        """Activity: a suíte não terminou (provedor fora, tempo esgotado); o agente não fica preso em avaliação."""
        avaliacao = Avaliacao(versao=data.versao, ok=False, em=datetime.now(UTC), resultados=[
            ResultadoCaso(caso="-", ok=False, detalhes=["A suíte não terminou (modelo ou ferramenta fora do ar). Rode de novo."])])
        row = await db.merge(f"{AGENTES}:{data.id}", {"avaliando": False, "avaliacao": avaliacao.model_dump(mode="json")})
        await bus.live(LIVE_AGENTES, AgenteMudou(id=data.id, action="avaliado"))
        return Agente.model_validate(row)

    async def confiar(self, data: AgenteRef) -> Agente:
        """Confiável é decisão do staff da Cogniventure, sobre um agente que já passou na suíte."""
        who = current()
        if who is None or not (STAFF & who.roles):
            raise ServiceError("ERRO_AGENTES_FORBIDDEN", "Só o staff da Cogniventure marca um agente como confiável.", 403)
        agente = Agente.model_validate(await _row(data.id))
        if agente.status != "verificado":
            raise ServiceError("ERRO_AGENTES_NAO_VERIFICADO", "O agente precisa passar na suíte antes.", 409)
        row = await db.merge(f"{AGENTES}:{data.id}", {"status": "confiavel", "confiavel_por": who.sub})
        await bus.live(LIVE_AGENTES, AgenteMudou(id=data.id, action="confiavel"))
        return Agente.model_validate(row)

    async def testar(self, data: Teste) -> Execucao:
        """Experimenta o agente com uma tarefa e dados quaisquer (não muda o status)."""
        _escritor()
        return await _executar(Agente.model_validate(await _row(data.id)), data.tarefa, _contexto(data.dados), data.saidas)

    # ── Para o svc-processos ─────────────────────────────────────────────────

    async def lista(self, data: Empty) -> ListaAgentes:
        """rpc.agentes.lista: os agentes e o status (o desenho oferece os verificados; a validação confere)."""
        return ListaAgentes(itens=[ResumoAgente(id=a.id, nome=a.nome, descricao=a.descricao, status=a.status,
                                                ferramentas=[f.ref for f in a.ferramentas]) for a in (await self.agentes(Empty())).itens])

    async def executar(self, data: ExecutarAgente) -> Execucao:
        """rpc.agentes.executar: um passo de processo com um agente que passou na suíte."""
        agente = Agente.model_validate(await _row(data.agente))
        if agente.status not in ("verificado", "confiavel"):
            raise ServiceError("ERRO_AGENTES_NAO_VERIFICADO", f"O agente {agente.nome} ainda não passou na suíte.", 409)
        contexto = data.contexto
        if data.regras:
            contexto += "\n\nRegras que o staff da Cogniventure ensinou para este passo (siga-as):\n" + "\n".join(f"- {r}" for r in data.regras)
        return await _executar(agente, data.tarefa, contexto, data.saidas, leitura=data.leitura, obrigatorias=data.obrigatorias)


# ── O agente rodando ─────────────────────────────────────────────────────────

async def _executar(agente: Agente, tarefa: str, contexto: str, saidas: dict[str, Tipo], *, leitura: bool = False,
                    obrigatorias: list[str] | None = None) -> Execucao:
    """Monta as ferramentas (as da plataforma e as MCP, com a política de cada uma) e roda no laço do AgentExo."""
    feito = Execucao()
    tipos = {"texto": str, "numero": float, "sim_nao": bool}
    campos: dict[str, Any] = {campo: (tipos[tipo] | None, None) for campo, tipo in saidas.items()}
    if leitura:
        campos["fontes"] = (dict[str, str], Field(default_factory=dict, description=(
            "Para cada saída, o trecho copiado igual de onde ela saiu (documento ou resposta de ferramenta); "
            "para a que veio de uma regra do staff, escreva regra")))
    modelo = create_model("saidas", **campos)

    async def concluir(dados: BaseModel) -> str:
        valores = dados.model_dump(mode="json")
        feito.fontes = valores.pop("fontes", None) or {}
        feito.saidas = valores
        return "Passo concluído."

    exigidas = [c for c in (obrigatorias or saidas) if c in saidas]
    concluir.__doc__ = f"Conclui com as saídas: {', '.join(saidas)}" + (
        f" (obrigatórias: {', '.join(exigidas)}; as outras, se souber)." if len(exigidas) < len(saidas) else ".") + (
        " Em fontes, o trecho de onde saiu cada uma: o que não está escrito não se conclui (peça ajuda)." if leitura else "")
    concluir.__signature__ = _assinatura(modelo)  # type: ignore[attr-defined]

    async def pedir_ajuda(dados: PedidoAjuda) -> str:
        """Não dá para concluir com segurança: uma pessoa resolve, com o motivo."""
        feito.ajuda = feito.ajuda or dados.motivo
        return "Pedido de ajuda registrado."

    ferramentas: list[Any] = [concluir, pedir_ajuda]
    refs = {f.ref: f.modo for f in agente.ferramentas}
    if "documento" in refs:
        async def ler_documento(dados: LeituraDocumento) -> str:
            """Lê o texto de um documento recebido (o id vem do gatilho: gatilho.documento_id)."""
            try:
                doc = await bus.request(DOCUMENTO_SUBJECT, DocumentoRef(id=dados.documento_id), DocumentoTexto, timeout=10)
            except (NatsError, TimeoutError):
                return "O serviço de documentos não respondeu agora."
            feito.ferramentas.append("ler_documento")
            if not doc.texto.strip():
                return f"{doc.nome} ({doc.tipo}) não tem texto legível (imagem ou PDF escaneado)."
            feito.lidos.append(f"{doc.nome} {doc.assunto or ''} {doc.texto}")
            return f"{doc.nome} — assunto: {doc.assunto or '-'}\n\n{doc.texto[:12000]}"

        ferramentas.append(ler_documento)
    if "conhecimento" in refs:
        async def buscar_conhecimento(dados: Consulta) -> str:
            """Busca no conhecimento da empresa (site, documentos e briefing) e devolve os trechos com a fonte."""
            try:
                achados = await bus.request(BUSCA_SUBJECT, BuscaQuery(q=dados.consulta), Achados, timeout=10)
            except (NatsError, TimeoutError):
                return "O conhecimento não respondeu agora."
            feito.ferramentas.append("buscar_conhecimento")
            texto = json.dumps([{k: a.get(k) for k in ("titulo", "trecho", "fonte")} for a in achados.itens], ensure_ascii=False)
            feito.lidos.append(texto)
            return texto if achados.itens else "Nada encontrado no conhecimento."

        ferramentas.append(buscar_conhecimento)
    externas = [r for r in refs if r.startswith(("acao:", "mcp:"))]
    if externas:
        catalogo = {f.ref: f for f in (await AgentesService().catalogo(Empty())).itens}
        nomes: set[str] = set()
        for ref in externas:
            item = catalogo.get(ref)  # fora do catálogo (pacote desligado, servidor removido, quarentena): o agente não a vê
            if item is None:
                continue
            modo = "perguntar" if item.risco == "irreversivel" else refs[ref]  # irreversível nunca roda sozinho
            ferramentas.append((_ferramenta_acao if item.origem == "pacote" else _ferramenta_mcp)(item, modo, feito, nomes))
    instrucoes = f"{agente.instrucao}\n\n{INSTRUCOES_PLATAFORMA}"
    resultado = await llm.run_agent(agente.modelo, tarefa, instructions=instrucoes, tools=ferramentas, context=contexto, max_turns=8)
    textos = [resultado.text]
    if not (feito.saidas or feito.ajuda or feito.aprovacao):
        # Achado com o modelo real: às vezes ele escreve a resposta ("concluir(divergente=false)") em vez de chamar a
        # ferramenta. Uma segunda chance, com o que ele já consultou e o que faltou; se ainda faltar, não concluiu.
        lembrete = "\n\n".join(p for p in (
            contexto, "O que você já consultou nesta tarefa:\n" + "\n".join(feito.lidos[-5:])[:6000] if feito.lidos else "",
            f"Sua resposta anterior, sem chamar concluir: {resultado.text[:1500]}") if p)
        resultado = await llm.run_agent(agente.modelo, f"{tarefa}\n\nChame a ferramenta concluir com as saídas (ou pedir_ajuda); não responda só em texto.",
                                        instructions=instrucoes, tools=ferramentas, context=lembrete, max_turns=4)
        textos.append(resultado.text)
    if not (feito.saidas or feito.ajuda or feito.aprovacao):  # a resposta veio como JSON no texto: vale se tiver todas as saídas
        valores = next((v for t in textos if (v := _saidas_do_texto(t, modelo, exigidas))), {})
        feito.fontes, feito.saidas = valores.pop("fontes", None) or {}, valores
    feito.texto = resultado.text
    return feito


def _saidas_do_texto(texto: str, modelo: type[BaseModel], saidas: list[str]) -> dict[str, Any]:
    """Um objeto JSON no texto com todas as saídas pedidas, validado pelo mesmo modelo de concluir; senão, nada."""
    for trecho in re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", texto):
        try:
            bruto = json.loads(trecho)
        except json.JSONDecodeError:
            continue
        if isinstance(bruto, dict) and set(saidas) <= set(bruto):
            try:
                return modelo.model_validate({k: v for k, v in bruto.items() if k in modelo.model_fields}).model_dump(mode="json")
            except ValueError:
                continue
    return {}


def _ferramenta_acao(item: FerramentaCatalogo, modo: str, feito: Execucao, nomes: set[str]) -> SchemaTool:
    """A ação do pacote como o modelo a vê; a chamada vai ao próprio pacote (rpc.<pacote>.acao), que a roda na organização
    de quem roda o agente, com a mesma conferência de um passo do processo."""
    pacote, acao = item.ref.removeprefix("acao:").split(".", 1)
    nome = _nome_unico(f"acao_{pacote}_{acao}", nomes)

    async def chamar(argumentos: dict[str, Any]) -> str:
        if modo == "perguntar":  # política (ou irreversível): não executa; o passo vai para uma pessoa aprovar
            feito.aprovacao = feito.aprovacao or f"{item.nome} ({item.pacote}) com {json.dumps(argumentos, ensure_ascii=False)[:300]}"
            return "Esta ferramenta precisa da aprovação de uma pessoa e não foi executada. Chame pedir_ajuda dizendo o que ia fazer."
        feito.ferramentas.append(f"{pacote}.{acao}")
        with acting_as(system(SERVICE, current_tenant())):  # o pacote só atende o svc-agentes, na organização do agente
            try:
                resposta = await bus.request(action_subject(pacote), ActionCall(acao=acao, entrada=argumentos), ActionResult, timeout=60)
            except (NatsError, TimeoutError):
                return f"O pacote {item.pacote} não respondeu agora."
        if not resposta.ok:
            return f"A ação não seguiu: {resposta.motivo}"
        texto = json.dumps(resposta.resultado, ensure_ascii=False)
        feito.lidos.append(texto)
        return texto

    descricao = f"[{item.pacote}] {item.descricao}" + (" (pede aprovação de uma pessoa antes de rodar)" if modo == "perguntar" else "")
    return SchemaTool(nome, descricao, item.parametros or {"type": "object", "properties": {}}, chamar)


def _ferramenta_mcp(item: FerramentaCatalogo, modo: str, feito: Execucao, nomes: set[str]) -> SchemaTool:
    """A ferramenta MCP como o modelo a vê; a chamada vai ao svc-integracoes (a credencial não passa por aqui)."""
    servidor = item.ref.split(":")[1]
    nome = _nome_unico(f"mcp_{_normal_nome(item.servidor_nome or 'servidor')}_{_normal_nome(item.nome)}", nomes)

    async def chamar(argumentos: dict[str, Any]) -> str:
        if modo == "perguntar":  # política: não executa; o passo vai para uma pessoa aprovar (Ask do AgentExo)
            feito.aprovacao = feito.aprovacao or f"{item.nome} ({item.servidor_nome}) com {json.dumps(argumentos, ensure_ascii=False)[:300]}"
            return "Esta ferramenta precisa da aprovação de uma pessoa e não foi executada. Chame pedir_ajuda dizendo o que ia fazer."
        feito.ferramentas.append(item.nome)
        resposta = await bus.request(MCP_SUBJECT, ChamadaMcp(servidor=servidor, ferramenta=item.nome, argumentos=argumentos),
                                     ResultadoMcp, timeout=60)
        feito.lidos.append(resposta.texto)
        return resposta.texto if resposta.ok else f"A ferramenta respondeu com erro: {resposta.texto}"

    descricao = f"[{item.servidor_nome}] {item.descricao}" + (" (pede aprovação de uma pessoa antes de rodar)" if modo == "perguntar" else "")
    return SchemaTool(nome, descricao, item.parametros or {"type": "object", "properties": {}}, chamar)


# ── Ajudantes ────────────────────────────────────────────────────────────────

def _nome_unico(nome: str, nomes: set[str]) -> str:
    """O nome da ferramenta para o modelo: snake_case, até 60, sem repetir entre as do agente."""
    base = re.sub(r"[^a-z0-9_]", "_", nome)[:60]
    nome = base
    while nome in nomes:
        nome = f"{base[:57]}_{len(nomes)}"
    nomes.add(nome)
    return nome


def _escritor() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_AGENTES_FORBIDDEN", "Só donos, administradores e o staff mexem nos agentes.", 403)


async def _row(agente_id: str) -> dict[str, Any]:
    row = await db.select(f"{AGENTES}:{agente_id}")
    if row is None:
        raise ServiceError("ERRO_AGENTES_NAO_ENCONTRADO", "Agente não encontrado.", 404)
    return row


async def _conferir_ferramentas(svc: AgentesService, ferramentas: list[Any]) -> None:
    """Só o que está no catálogo agora (pacote ligado, servidor conectado, ferramenta fora de quarentena), sem repetir;
    irreversível só pedindo aprovação (perguntar)."""
    refs = [f.ref for f in ferramentas]
    if len(set(refs)) != len(refs):
        raise ServiceError("ERRO_AGENTES_FERRAMENTA", "Ferramenta repetida no agente.", 422)
    disponiveis = {f.ref: f for f in (await svc.catalogo(Empty())).itens}
    if fora := [r for r in refs if r not in disponiveis]:
        raise ServiceError("ERRO_AGENTES_FERRAMENTA",
                           f"Fora do catálogo (pacote desligado, servidor desconectado ou em quarentena?): {', '.join(fora)}", 422)
    if sozinhas := [disponiveis[f.ref].nome for f in ferramentas if disponiveis[f.ref].risco == "irreversivel" and f.modo != "perguntar"]:
        raise ServiceError("ERRO_AGENTES_FERRAMENTA",
                           f"Irreversível só com a aprovação de uma pessoa (perguntar): {', '.join(sozinhas)}", 422)


def _conferir_casos(casos: list[Caso]) -> None:
    ids = [c.id for c in casos]
    if len(set(ids)) != len(ids):
        raise ServiceError("ERRO_AGENTES_CASO", "Dois casos da suíte com o mesmo id.", 422)


def _contexto(dados: dict[str, Any]) -> str:
    return "Dados que o passo tem à mão: " + json.dumps(dados, ensure_ascii=False)[:6000] if dados else ""


def _tipo(valor: Any) -> Tipo:
    return "sim_nao" if isinstance(valor, bool) else "numero" if isinstance(valor, int | float) else "texto"


def _julgar(caso: Caso, execucao: Execucao) -> ResultadoCaso:
    """Chegou no esperado? Número igual (centavos); sim/não igual; texto igual sem acento e pontuação, ou um contém o outro."""
    detalhes = []
    if execucao.ajuda:
        detalhes.append(f"pediu ajuda: {execucao.ajuda}")
    if execucao.aprovacao:
        detalhes.append(f"pediu aprovação para usar {execucao.aprovacao}")
    for campo, certo in caso.esperado.items():
        obtido = execucao.saidas.get(campo)
        if isinstance(certo, bool):
            igual = obtido is certo
        elif isinstance(certo, int | float):
            try:
                igual = obtido is not None and not isinstance(obtido, bool) and abs(float(obtido) - float(certo)) < 0.01
            except (TypeError, ValueError):
                igual = False
        else:
            a, b = _normal(certo), _normal(obtido if obtido is not None else "")
            igual = bool(b) and (a == b or a in b or b in a)
        if not igual:
            detalhes.append(f"{campo}: esperado {certo!r}, o agente deu {obtido!r}")
    return ResultadoCaso(caso=caso.id, ok=not detalhes, saida=execucao.saidas, detalhes=detalhes, ferramentas=execucao.ferramentas)


def _normal(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", texto)


def _normal_nome(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")[:24] or "x"


def _jsonavel(valor: Any) -> Any:
    if isinstance(valor, list):
        return [v.model_dump() if isinstance(v, BaseModel) else v for v in valor]
    return valor


def _assinatura(modelo: type[BaseModel]) -> Any:
    return inspect.Signature([inspect.Parameter("dados", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=modelo)])
