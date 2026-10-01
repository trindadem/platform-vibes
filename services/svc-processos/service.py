"""svc-processos · lógica de negócio pura. Fonte da verdade: specs/processos.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py (ou é um gerador de pedaços, que não vira activity), e vira a activity "processos.<método>".
O perfil e o conhecimento da empresa vêm do svc-conhecimento por RPC (rpc.conhecimento.*), na organização de quem age.
"""
import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.llm import AgentStep, llm
from core.nats_bus import bus
from core.plans import plans
from core.processes import START, ActionCatalog, CatalogAction, Condition, Flow, Fluxo, Step, Trigger, camunda, to_bpmn
from core.security import current, current_tenant
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    ACOES,
    BIBLIOTECA,
    BUSCA_SUBJECT,
    CONTEXTO_SUBJECT,
    DESCOBERTA_INSTRUCOES,
    DESCRICAO_INSTRUCOES,
    DESENHO_INSTRUCOES,
    FLUXOS,
    HISTORY,
    LIVE_DESENHO,
    LIVE_PROCESSOS,
    MENSAGENS,
    PASSOS,
    PROCESSOS,
    UNDO,
    VERSOES,
    WRITERS,
    Achados,
    AlteracaoPasso,
    Biblioteca,
    BuscaQuery,
    CatalogoAcoes,
    Cenario,
    ContextoEmpresa,
    Desenho,
    DesenhoMudou,
    DesenhoRef,
    Desligamento,
    Descoberta,
    Descricao,
    Empty,
    Ligacao,
    MensagemDesenho,
    MensagemDesenhoIn,
    Motor,
    NovoPasso,
    Parametro,
    PassoAgente,
    PassoSimulado,
    Problema,
    Processo,
    ProcessoDescrito,
    ProcessoMudou,
    ProcessoPage,
    ProcessoQuery,
    ProcessoRef,
    ProcessosSettings,
    RemocaoPasso,
    Resumo,
    Simulacao,
    SimulacaoIn,
    Sugestao,
    Versao,
    VersaoResumo,
)

MIGRATIONS: list[Migration] = []
settings = ProcessosSettings()
_MODELOS = {m.id: m for m in BIBLIOTECA}
# Verbos de quem diz que mudou o fluxo: sem nenhuma operação aplicada, o agente é chamado de novo (o modelo às vezes
# responde a mudança em vez de fazê-la).
_AFIRMA_MUDANCA = re.compile(r"\b(adicionei|alterei|mudei|atualizei|inclu[ií]|removi|liguei|desliguei|troquei|ajustei|"
                             r"defini|coloquei|criei|subi|baixei|reduzi|aumentei|configurei|tirei)\b", re.IGNORECASE)


@activities("processos")
class ProcessosService:
    async def biblioteca(self, data: Empty) -> Biblioteca:
        """Os modelos de processo que a Cogniventure executa (os mesmos para toda organização)."""
        return Biblioteca(itens=BIBLIOTECA)

    async def listar(self, data: ProcessoQuery) -> ProcessoPage:
        return await db.page(PROCESSOS, data, ProcessoPage)

    async def resumo(self, data: Empty) -> Resumo:
        """O passo de descoberta da jornada, para o workspace."""
        rows = await db.query(f"SELECT status, count() AS total FROM {PROCESSOS} WHERE tenant = $tenant GROUP BY status")
        total = {r["status"]: r["total"] for r in rows}
        return Resumo(sugeridos=total.get("sugerido", 0), aceitos=total.get("aceito", 0), recusados=total.get("recusado", 0),
                      publicados=await _publicados())

    async def descobrir(self, data: Empty) -> AsyncIterator[PassoAgente | Descoberta]:
        """O agente de descoberta lê o perfil e sugere processos da biblioteca, com o porquê; cada ferramenta é um passo."""
        _writer()
        contexto = await _contexto_da_empresa()
        if not any(t.get("status") == "feito" for t in contexto.topicos):
            raise ServiceError("ERRO_PROCESSOS_SEM_BRIEFING", "Faça o briefing antes: ainda não há nada sobre a empresa.", 409)
        existentes = await _todos()
        sugeridos: list[str] = []
        fila: asyncio.Queue[AgentStep | None] = asyncio.Queue()
        ferramentas = [_buscar_conhecimento, _sugerir(sugeridos)]
        tarefa = asyncio.create_task(llm.run_agent(
            settings.model,
            "Sugira os processos da biblioteca que fazem sentido para esta empresa, chamando sugerir_processo para cada um, "
            "e escreva no fim o resumo para o cliente.",
            instructions=DESCOBERTA_INSTRUCOES, tools=ferramentas, context=_contexto(contexto, existentes),
            on_step=fila.put_nowait, max_turns=10,
        ))
        tarefa.add_done_callback(lambda _: fila.put_nowait(None))
        while (passo := await fila.get()) is not None:
            yield PassoAgente(ferramenta=passo.tool, texto=PASSOS.get(passo.tool, passo.tool), status=passo.status)
        resultado = await tarefa
        processos = [p for p in await _todos() if p.id in sugeridos]
        texto = resultado.text.strip() or (f"Sugeri {len(processos)} processos." if processos else "Não encontrei processos da biblioteca para sugerir agora.")
        yield Descoberta(texto=texto, processos=processos)

    async def descrever(self, data: Descricao) -> Processo:
        """O cliente descreve um processo próprio: o agente organiza e o processo nasce aceito."""
        _writer()
        registrados: list[Processo] = []

        async def registrar_processo(dados: ProcessoDescrito) -> str:
            """Registra o processo descrito pelo cliente, organizado (chame uma única vez)."""
            if registrados:
                return "Já registrado."
            row = await db.create(PROCESSOS, {"modelo": dados.modelo, "area": dados.area, "titulo": dados.titulo,
                                              "descricao": dados.descricao, "motivo": None, "origem": "cliente",
                                              "status": "aceito", "prioridade": "media"})
            registrados.append(_processo(row))
            return f"Registrado: {dados.titulo}."

        catalogo = "\n".join(f"- {m.id} ({m.area}): {m.titulo}. {m.resumo}" for m in BIBLIOTECA)
        await llm.run_agent(settings.model, f"Processo descrito pelo cliente:\n{data.texto}", instructions=DESCRICAO_INSTRUCOES,
                            tools=[registrar_processo], context=f"Biblioteca:\n{catalogo}", max_turns=3)
        if not registrados:
            raise ServiceError("ERRO_PROCESSOS_DESCRICAO", "Não consegui organizar a descrição. Conte o gatilho, o que acontece e quem participa.", 422)
        await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=registrados[0].id, action="descrito"))
        return registrados[0]

    async def aceitar(self, data: ProcessoRef) -> Processo:
        return await _mudar(data.id, "aceito")

    async def recusar(self, data: ProcessoRef) -> Processo:
        return await _mudar(data.id, "recusado")

    # ── Catálogo de ações dos pacotes ────────────────────────────────────────

    async def registrar_catalogo(self, data: ActionCatalog) -> Empty:
        """events.processos.catalogo: o pacote declarou as ações no boot; troca as dele no catálogo."""
        await db.query_shared(f"DELETE FROM {ACOES} WHERE service = $service", service=data.service)
        for acao in data.actions:
            await db.query_shared(f"CREATE {ACOES} CONTENT $acao", acao=acao.model_dump(mode="json"))
        return Empty()

    async def catalogo(self, data: Empty) -> CatalogoAcoes:
        return CatalogoAcoes(itens=list((await _catalogo()).values()))

    # ── Desenho: versões, conversa, simulação e publicação ───────────────────

    async def abrir(self, data: DesenhoRef) -> Desenho:
        """Abre o desenho do processo aceito; na primeira vez nasce o rascunho 1 a partir do fluxo de partida."""
        processo = await _processo_por_id(data.processo)
        if processo.status != "aceito":
            raise ServiceError("ERRO_PROCESSOS_NAO_ACEITO", "Aceite o processo antes de desenhá-lo.", 409)
        if not await _versoes(processo.id):
            _writer()
            try:
                await db.create(VERSOES, {"processo": processo.id, "numero": 1, "status": "rascunho",
                                          "fluxo": _partida(processo).model_dump(mode="json"), "anteriores": [], "alteracoes": 0})
            except ServiceError as exc:  # duas abas abrindo ao mesmo tempo: a outra criou o rascunho 1
                if exc.code != "ERRO_RECORD_DUPLICATE":
                    raise
        return await _desenho(processo.id)

    async def conversar(self, data: MensagemDesenhoIn) -> AsyncIterator[PassoAgente | Desenho]:
        """Uma mensagem do cliente no desenho: o agente edita o rascunho pelas operações; cada uma é um passo."""
        _writer()
        processo = await _processo_por_id(data.processo)
        rascunho = await _rascunho(processo.id)
        historico = await _mensagens(processo.id)
        try:
            empresa = await _contexto_da_empresa()
        except ServiceError:
            empresa = None
        await db.create(MENSAGENS, {"processo": processo.id, "papel": "cliente", "texto": data.texto, "passos": []})
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="mensagem"))
        catalogo = await _catalogo()
        fila: asyncio.Queue[AgentStep | None] = asyncio.Queue()
        feitos: list[str] = []

        def passo(step: AgentStep) -> None:
            if step.status == "done" and (rotulo := PASSOS.get(step.tool, step.tool)) not in feitos:
                feitos.append(rotulo)
            fila.put_nowait(step)

        async def rodar(tarefa: str) -> str:
            rascunho_agora = await _rascunho(processo.id)
            contexto = _contexto_desenho(processo, Fluxo.model_validate(rascunho_agora["fluxo"]), catalogo, empresa, historico)
            argumentos = dict(instructions=DESENHO_INSTRUCOES, tools=_ferramentas(processo.id, catalogo), context=contexto,
                              on_step=passo, max_turns=16)
            try:
                return (await llm.run_agent(settings.desenho_model, tarefa, **argumentos)).text.strip()
            except ServiceError as exc:  # o modelo de desenho não está cadastrado: vale o dos outros agentes
                if exc.code != "ERRO_AI_MODEL_UNAVAILABLE" or settings.desenho_model == settings.model:
                    raise
                return (await llm.run_agent(settings.model, tarefa, **argumentos)).text.strip()

        def erros(fluxo: dict[str, Any]) -> set[str]:
            return {p.texto for p in _problemas(Fluxo.model_validate(fluxo), catalogo) if p.nivel == "erro"}

        antes, erros_antes = int(rascunho.get("alteracoes") or 0), erros(rascunho["fluxo"])

        async def pendencia(texto: str) -> tuple[str | None, bool, list[str]]:
            """O que o agente deixou por fazer (disse que mudou sem chamar operação, ou deixou erros novos), se mudou e os erros novos."""
            agora = await _rascunho(processo.id)
            mudou, novos = int(agora.get("alteracoes") or 0) != antes, sorted(erros(agora["fluxo"]) - erros_antes)
            if not mudou and _AFIRMA_MUDANCA.search(texto):
                return (f"Você respondeu \"{texto}\", mas não chamou nenhuma ferramenta: o fluxo continua igual. Faça agora as "
                        "mudanças pelas ferramentas e só depois responda ao cliente.", mudou, novos)
            if novos:
                return ("Suas mudanças deixaram estes erros no fluxo: " + "; ".join(novos)
                        + ". Corrija pelas ferramentas (o fluxo atual está no contexto) e responda ao cliente.", mudou, novos)
            return None, mudou, novos

        async def responder() -> None:
            pedido = f"Mensagem do cliente:\n{data.texto}\n\n"
            texto = await rodar(pedido + "Faça as mudanças no fluxo e responda ao cliente.")
            aviso, mudou, novos = await pendencia(texto)
            if aviso:  # uma segunda chance, com o que faltou dito; se ainda faltar, a resposta diz a verdade
                texto = await rodar(pedido + aviso)
                aviso, mudou, novos = await pendencia(texto)
            if aviso or not texto:
                if not mudou:
                    texto = "Não consegui aplicar essa mudança no fluxo. Pode me dizer de outro jeito o que quer mudar?"
                elif novos:
                    texto = "Mudei o fluxo, mas ficou algo para resolver: " + "; ".join(novos)
                else:
                    texto = texto or "Pronto, ajustei o fluxo."
            await db.create(MENSAGENS, {"processo": processo.id, "papel": "agente", "texto": texto, "passos": feitos})
            await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="mensagem"))

        tarefa = asyncio.create_task(responder())
        tarefa.add_done_callback(lambda _: fila.put_nowait(None))
        while (step := await fila.get()) is not None:
            yield PassoAgente(ferramenta=step.tool, texto=PASSOS.get(step.tool, step.tool), status=step.status)
        await tarefa
        yield await _desenho(processo.id)

    async def simular(self, data: SimulacaoIn) -> Simulacao:
        """Percorre o fluxo da versão aberta com os exemplos das ações e dos agentes (e o cenário, se vier)."""
        processo = await _processo_por_id(data.processo)
        versao = await _aberta(processo.id)
        return _simular(Fluxo.model_validate(versao["fluxo"]), await _catalogo(), data)

    async def desfazer(self, data: DesenhoRef) -> Desenho:
        _writer()
        rascunho = await _rascunho(data.processo)
        anteriores = list(rascunho.get("anteriores") or [])
        if not anteriores:
            raise ServiceError("ERRO_PROCESSOS_NADA_A_DESFAZER", "Não há alteração para desfazer.", 409)
        await db.merge(_ref(VERSOES, rascunho), {"fluxo": anteriores.pop(), "anteriores": anteriores,
                                                 "alteracoes": max(0, int(rascunho.get("alteracoes") or 0) - 1)})
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=data.processo, action="alterado"))
        return await _desenho(data.processo)

    async def publicar(self, data: DesenhoRef) -> Desenho:
        """Publica o rascunho: implanta no Camunda (a versão seguinte do processo no motor) e arquiva a anterior."""
        _writer()
        processo = await _processo_por_id(data.processo)
        rascunho = await _rascunho(processo.id)
        fluxo = Fluxo.model_validate(rascunho["fluxo"])
        erros = [p for p in _problemas(fluxo, await _catalogo()) if p.nivel == "erro"]
        if erros:
            raise ServiceError("ERRO_PROCESSOS_FLUXO_INVALIDO", "O fluxo tem problemas: " + "; ".join(e.texto for e in erros[:3]), 409)
        publicada = next((v for v in await _versoes(processo.id) if v["status"] == "publicada"), None)
        if publicada is not None and Fluxo.model_validate(publicada["fluxo"]) == fluxo:
            raise ServiceError("ERRO_PROCESSOS_SEM_MUDANCA", "O rascunho está igual à versão publicada: mude o fluxo ou descarte o rascunho.", 409)
        if processo.publicada is None:
            ativos = await db.query(f"SELECT count() AS total FROM (SELECT id FROM {PROCESSOS} WHERE tenant = $tenant "
                                    "AND publicada != NONE AND publicada != NULL) GROUP ALL")
            await plans.check("ativos", used=ativos[0]["total"] if ativos else 0)
        motor_id = _motor_id(processo.id)
        implantado = await camunda.deploy(to_bpmn(fluxo, process_id=motor_id, name=processo.titulo), motor_id)
        for versao in await _versoes(processo.id):
            if versao["status"] == "publicada":
                await db.merge(_ref(VERSOES, versao), {"status": "arquivada"})
        await db.merge(_ref(VERSOES, rascunho), {
            "status": "publicada", "publicada_em": datetime.now(UTC), "anteriores": [],
            "motor": Motor(processo=motor_id, chave=implantado.key, versao=implantado.version).model_dump()})
        await db.merge(f"{PROCESSOS}:{processo.id}", {"publicada": int(rascunho["numero"])})
        await plans.count("ativos", await _publicados())
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="publicado"))
        return await _desenho(processo.id)

    async def ajustar(self, data: DesenhoRef) -> Desenho:
        """Abre um rascunho novo a partir da versão publicada (as execuções em andamento seguem na versão delas)."""
        _writer()
        versoes = await _versoes(data.processo)
        if any(v["status"] == "rascunho" for v in versoes):
            return await _desenho(data.processo)
        publicada = next((v for v in versoes if v["status"] == "publicada"), None)
        if publicada is None:
            raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", "Ainda não há versão publicada para ajustar.", 409)
        await db.create(VERSOES, {"processo": data.processo, "numero": max(int(v["numero"]) for v in versoes) + 1,
                                  "status": "rascunho", "fluxo": publicada["fluxo"], "anteriores": [], "alteracoes": 0})
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=data.processo, action="ajustado"))
        return await _desenho(data.processo)

    async def descartar(self, data: DesenhoRef) -> Desenho:
        """Descarta o rascunho de um processo que já tem versão publicada (volta para ela)."""
        _writer()
        rascunho = await _rascunho(data.processo)
        if not any(v["status"] == "publicada" for v in await _versoes(data.processo)):
            raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", "O primeiro rascunho não se descarta: ajuste-o ou recuse o processo.", 409)
        await db.delete(_ref(VERSOES, rascunho))
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=data.processo, action="descartado"))
        return await _desenho(data.processo)


# ── Ajudantes ────────────────────────────────────────────────────────────────

def _writer() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só donos e administradores mexem nos processos.", 403)


def _short(record_id: Any) -> str:
    """"processos_processos:⟨abc⟩" → "abc": na API, o id é só a chave."""
    return str(record_id).partition(":")[2].strip("⟨⟩`") if ":" in str(record_id) else str(record_id)


def _processo(row: dict[str, Any]) -> Processo:
    return Processo.model_validate({**row, "id": _short(row["id"])})


async def _todos() -> list[Processo]:
    rows = await db.query(f"SELECT * FROM {PROCESSOS} WHERE tenant = $tenant ORDER BY created_at")
    return [_processo(r) for r in rows]


async def _mudar(processo_id: str, status: str) -> Processo:
    _writer()
    if await db.select(f"{PROCESSOS}:{processo_id}") is None:
        raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Processo não encontrado.", status=404)
    processo = _processo(await db.merge(f"{PROCESSOS}:{processo_id}", {"status": status}))
    await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=processo.id, action=status))
    return processo


async def _contexto_da_empresa() -> ContextoEmpresa:
    try:
        return await bus.request(CONTEXTO_SUBJECT, Empty(), ContextoEmpresa, timeout=10)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_PROCESSOS_SEM_CONHECIMENTO", "O conhecimento da empresa não respondeu. Tente de novo em instantes.", 503) from None


async def _buscar_conhecimento(consulta: str) -> str:
    """Busca no conhecimento da empresa (site, documentos e briefing) e devolve os trechos mais relevantes."""
    try:
        achados = await bus.request(BUSCA_SUBJECT, BuscaQuery(q=consulta), Achados, timeout=10)
    except (NatsError, TimeoutError):
        return "O conhecimento não respondeu agora; siga com o perfil."
    if not achados.itens:
        return "Nada encontrado no conhecimento."
    return json.dumps([{k: a.get(k) for k in ("titulo", "trecho", "fonte")} for a in achados.itens], ensure_ascii=False)


def _sugerir(sugeridos: list[str]) -> Any:
    async def sugerir_processo(dados: Sugestao) -> str:
        """Sugere à empresa um processo da biblioteca, com o motivo (o que no briefing mostra que serve)."""
        modelo = _MODELOS[dados.modelo]
        rows = await db.query(f"SELECT * FROM {PROCESSOS} WHERE tenant = $tenant AND modelo = $modelo LIMIT 1", modelo=dados.modelo)
        if rows and rows[0]["status"] != "sugerido":
            return f"{modelo.titulo} já foi {rows[0]['status']} pela empresa; não sugira de novo."
        campos = {"motivo": dados.motivo, "prioridade": dados.prioridade}
        if rows:
            row = await db.merge(f"{PROCESSOS}:{_short(rows[0]['id'])}", campos)
        else:
            row = await db.create(PROCESSOS, {"modelo": modelo.id, "area": modelo.area, "titulo": modelo.titulo,
                                              "descricao": modelo.resumo, "origem": "sugestao", "status": "sugerido", **campos})
        processo = _processo(row)
        if processo.id not in sugeridos:
            sugeridos.append(processo.id)
        await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=processo.id, action="sugerido"))
        return f"Sugerido: {modelo.titulo}."

    return sugerir_processo


def _contexto(empresa: ContextoEmpresa, existentes: list[Processo]) -> str:
    perfil = [f"- {k}: {v}" for k, v in empresa.perfil.items() if v not in (None, "")]
    linhas = ["Perfil da empresa:", *(perfil or ["- (vazio)"]), "", "Biblioteca (id, área, título — o que faz; sinais):"]
    linhas += [f"- {m.id} ({m.area}): {m.titulo} — {m.resumo} Gatilho: {m.gatilho}. Sinais: {'; '.join(m.sinais)}."
               for m in BIBLIOTECA]
    linhas += ["", "Processos da empresa:"]
    linhas += [f"- {p.modelo or p.titulo}: {p.status}" for p in existentes] or ["- (nenhum ainda)"]
    return "\n".join(linhas)


# ── Desenho: ajudantes ───────────────────────────────────────────────────────

def _ref(table: str, row: dict[str, Any]) -> str:
    return f"{table}:{_short(row['id'])}"


def _motor_id(processo_id: str) -> str:
    """Id do processo no motor: a organização entra no nome (cada organização tem os seus processos no Camunda)."""
    return f"p_{current_tenant()}_{processo_id}"


async def _processo_por_id(processo_id: str) -> Processo:
    row = await db.select(f"{PROCESSOS}:{processo_id}")
    if row is None:
        raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Processo não encontrado.", status=404)
    return _processo(row)


async def _versoes(processo_id: str) -> list[dict[str, Any]]:
    return await db.query(f"SELECT * FROM {VERSOES} WHERE tenant = $tenant AND processo = $p ORDER BY numero", p=processo_id)


async def _rascunho(processo_id: str) -> dict[str, Any]:
    rascunho = next((v for v in await _versoes(processo_id) if v["status"] == "rascunho"), None)
    if rascunho is None:
        raise ServiceError("ERRO_PROCESSOS_SEM_RASCUNHO", "Não há rascunho aberto: clique em Ajustar para abrir um.", 409)
    return rascunho


async def _aberta(processo_id: str) -> dict[str, Any]:
    """A versão que a tela mostra: o rascunho; sem ele, a publicada; sem ela, a mais nova."""
    versoes = await _versoes(processo_id)
    if not versoes:
        raise ServiceError("ERRO_PROCESSOS_SEM_DESENHO", "Abra o desenho do processo primeiro.", status=409)
    for status in ("rascunho", "revisao", "publicada"):
        if found := next((v for v in versoes if v["status"] == status), None):
            return found
    return versoes[-1]


async def _mensagens(processo_id: str) -> list[dict[str, Any]]:
    rows = await db.query(f"SELECT * FROM {MENSAGENS} WHERE tenant = $tenant AND processo = $p "
                          "ORDER BY created_at DESC, id DESC LIMIT $n", p=processo_id, n=HISTORY)
    return list(reversed(rows))


async def _publicados() -> int:
    rows = await db.query(f"SELECT count() AS total FROM (SELECT id FROM {PROCESSOS} WHERE tenant = $tenant "
                          "AND publicada != NONE AND publicada != NULL) GROUP ALL")
    return rows[0]["total"] if rows else 0


async def _catalogo() -> dict[str, CatalogAction]:
    rows = await db.query_shared(f"SELECT * FROM {ACOES} ORDER BY name")
    return {r["name"]: CatalogAction.model_validate(r) for r in rows}


async def _desenho(processo_id: str) -> Desenho:
    processo = await _processo_por_id(processo_id)
    versoes = await _versoes(processo_id)
    aberta = await _aberta(processo_id)
    fluxo = Fluxo.model_validate(aberta["fluxo"])
    catalogo = await _catalogo()
    versao = Versao.model_validate({**aberta, "pode_desfazer": bool(aberta.get("anteriores"))})
    return Desenho(
        processo=processo,
        versao=versao,
        versoes=[VersaoResumo(numero=v["numero"], status=v["status"], publicada_em=v.get("publicada_em"),
                              motor_versao=(v.get("motor") or {}).get("versao")) for v in versoes],
        bpmn=to_bpmn(fluxo, process_id=_motor_id(processo_id), name=processo.titulo),
        problemas=_problemas(fluxo, catalogo),
        mensagens=[MensagemDesenho(id=_short(m["id"]), papel=m["papel"], texto=m["texto"], passos=m.get("passos") or [],
                                   created_at=m.get("created_at")) for m in await _mensagens(processo_id)],
        exige_revisao=_exige_revisao(fluxo, catalogo),
    )


def _partida(processo: Processo) -> Fluxo:
    """O fluxo de partida: o modelo da biblioteca, quando há um desenhado; senão, um agente faz o processo."""
    if processo.modelo in FLUXOS:
        return FLUXOS[processo.modelo].model_copy(deep=True)
    modelo = next((m for m in BIBLIOTECA if m.id == processo.modelo), None)
    gatilho = Trigger(tipo="manual", descricao=(modelo.gatilho if modelo else "Pedido do cliente")[:200])
    if modelo and modelo.gatilho.lower().startswith("todo dia"):
        gatilho = Trigger(tipo="agenda", agenda="0 8 * * *", descricao=modelo.gatilho)
    elif modelo and (modelo.gatilho.lower().startswith("todo mês") or modelo.gatilho.lower() == "dia 1"):
        gatilho = Trigger(tipo="agenda", agenda="0 8 1 * *", descricao=modelo.gatilho)
    objetivo = (modelo.roda_sozinho if modelo else processo.descricao)[:600]
    return Fluxo(gatilho=gatilho,
                 passos=[Step(id="executar", tipo="agente", nome=processo.titulo[:80], objetivo=objetivo, excecao=True),
                         Step(id="concluido", tipo="fim", nome="Concluído", resultado="concluido")],
                 ligacoes=[Flow(de=START, para="executar"), Flow(de="executar", para="concluido")])


# Saídas de cada tipo de passo (o que as condições podem usar).
def _saidas(step: Step, catalogo: dict[str, CatalogAction]) -> list[str]:
    if step.tipo == "acao":
        return catalogo[step.acao].output_fields if step.acao in catalogo else []
    if step.tipo == "agente":
        return list(step.saidas)
    if step.tipo == "tarefa":
        return ["aprovado", "comentario"]
    return []


def _problemas(fluxo: Fluxo, catalogo: dict[str, CatalogAction]) -> list[Problema]:
    """O que impede publicar (erro) e o que merece atenção (aviso)."""
    out: list[Problema] = []
    erro = lambda texto, passo=None: out.append(Problema(nivel="erro", passo=passo, texto=texto))  # noqa: E731
    aviso = lambda texto, passo=None: out.append(Problema(nivel="aviso", passo=passo, texto=texto))  # noqa: E731
    ids = {s.id for s in fluxo.passos}
    if len(ids) != len(fluxo.passos):
        erro("Há passos com o mesmo id.")
    inicio = fluxo.outgoing(START)
    if len(inicio) != 1:
        erro("O início precisa de exatamente uma ligação para o primeiro passo.")
    t = fluxo.gatilho
    if t.tipo == "evento" and not t.evento:
        erro("Gatilho por evento sem o nome do evento.")
    if t.tipo == "agenda" and not t.agenda:
        erro("Gatilho por agenda sem a agenda (cron).")
    for f in fluxo.ligacoes:
        if f.para not in ids or (f.de != START and f.de not in ids):
            erro(f"Ligação {f.de} → {f.para} aponta para passo que não existe.", f.de)
    if not any(s.tipo == "fim" for s in fluxo.passos):
        erro("O fluxo precisa de pelo menos um fim.")
    alcancados, fila = set(), [f.para for f in inicio]
    while fila:
        atual = fila.pop()
        if atual in alcancados or atual not in ids:
            continue
        alcancados.add(atual)
        fila += [f.para for f in fluxo.outgoing(atual)]
    for s in fluxo.passos:
        saindo = fluxo.outgoing(s.id)
        if s.id not in alcancados:
            erro(f"{s.nome} não é alcançado a partir do início.", s.id)
        if s.tipo == "fim":
            if saindo:
                erro(f"{s.nome} é fim e não pode ter caminho depois.", s.id)
            continue
        if not saindo:
            erro(f"{s.nome} não tem caminho depois.", s.id)
        if s.tipo == "decisao":
            padroes = [f for f in saindo if f.condicao is None]
            if len(saindo) < 2:
                erro(f"A decisão {s.nome} precisa de pelo menos dois caminhos.", s.id)
            if len(padroes) != 1:
                erro(f"A decisão {s.nome} precisa de exatamente um caminho padrão (sem condição).", s.id)
        elif len(saindo) > 1 or any(f.condicao for f in saindo):
            erro(f"{s.nome} tem mais de um caminho ou condição; condições só saem de decisões.", s.id)
        if s.tipo == "acao":
            if not s.acao or s.acao not in catalogo:
                erro(f"{s.nome}: a ação {s.acao or '(vazia)'} não está no catálogo.", s.id)
            else:
                acao = catalogo[s.acao]
                if acao.connections:
                    aviso(f"{s.nome} precisa da conexão {', '.join(acao.connections)}.", s.id)
                if acao.risk == "irreversivel" and not _aprovado_antes(fluxo, s.id):
                    aviso(f"{s.nome} é irreversível e não tem aprovação do cliente antes em todos os caminhos.", s.id)
        if s.tipo == "agente":
            if not s.objetivo:
                erro(f"O agente {s.nome} precisa de um objetivo.", s.id)
            if not s.excecao:
                erro(f"O agente {s.nome} precisa de caminho de exceção (excecao).", s.id)
        if s.tipo == "tarefa" and not s.responsavel:
            erro(f"A tarefa {s.nome} precisa de um responsável (cliente ou staff).", s.id)
        if s.tipo == "espera":
            if s.espera == "mensagem" and not (s.mensagem and s.chave):
                erro(f"A espera {s.nome} precisa da mensagem e da chave.", s.id)
            if s.espera == "tempo" and not s.horas:
                erro(f"A espera {s.nome} precisa de horas.", s.id)
            if s.espera is None:
                erro(f"A espera {s.nome} precisa dizer se é por mensagem ou por tempo.", s.id)
    for f in fluxo.ligacoes:
        if f.condicao is None:
            continue
        campos = []
        for alt in f.condicao.alternatives():
            campos.append(alt.campo)
            if isinstance(alt.valor, str) and alt.valor.startswith("parametros."):
                campos.append(alt.valor)
        for campo in campos:
            if not _campo_existe(fluxo, catalogo, campo):
                erro(f"A condição de {f.de} → {f.para} usa {campo}, que não existe.", f.de)
    return out


def _campo_existe(fluxo: Fluxo, catalogo: dict[str, CatalogAction], campo: str) -> bool:
    passo, _, nome = campo.partition(".")
    if passo == "parametros":
        return nome in fluxo.parametros
    step = fluxo.step(passo)
    return step is not None and nome in _saidas(step, catalogo)


def _aprovado_antes(fluxo: Fluxo, alvo: str) -> bool:
    """Todo caminho do início até o passo passa por uma tarefa do cliente?"""
    def sem_aprovacao(no: str, vistos: frozenset[str]) -> bool:
        if no == alvo:
            return True
        step = fluxo.step(no)
        if no in vistos or (step is not None and step.tipo == "tarefa" and step.responsavel == "cliente"):
            return False
        return any(sem_aprovacao(f.para, vistos | {no}) for f in fluxo.outgoing(no))

    return not sem_aprovacao(START, frozenset())


def _exige_revisao(fluxo: Fluxo, catalogo: dict[str, CatalogAction]) -> bool:
    acoes = [catalogo.get(s.acao or "") for s in fluxo.passos if s.tipo == "acao"]
    return any(a is not None and (a.risk == "irreversivel" or a.connections) for a in acoes)


def _resumo_fluxo(fluxo: Fluxo) -> str:
    t = fluxo.gatilho
    linhas = [f"Gatilho: {t.tipo}" + (f" ({t.evento or t.agenda})" if t.evento or t.agenda else "") + (f" — {t.descricao}" if t.descricao else "")]
    if fluxo.parametros:
        linhas.append("Parâmetros: " + ", ".join(f"{k} = {v}" for k, v in fluxo.parametros.items()))
    linhas.append("Passos:")
    for s in fluxo.passos:
        extra = {"acao": s.acao, "agente": f"objetivo: {s.objetivo}; saidas: {', '.join(s.saidas)}", "tarefa": f"{s.responsavel}: {s.pergunta}",
                 "espera": f"{s.espera} {s.mensagem or ''} {s.chave or ''} {s.horas or ''}".strip(), "fim": s.resultado}.get(s.tipo)
        linhas.append(f"- {s.id} [{s.tipo}] {s.nome}" + (f" ({extra})" if extra else "") + (" [exceção]" if s.excecao else ""))
    linhas.append("Ligações:")
    for f in fluxo.ligacoes:
        cond = (" se " + " ou ".join(f"{a.campo} {a.operador} {a.valor if a.valor is not None else ''}".rstrip()
                                    for a in f.condicao.alternatives())) if f.condicao else ""
        linhas.append(f"- {f.de} → {f.para}{cond}")
    return "\n".join(linhas)


def _contexto_desenho(processo: Processo, fluxo: Fluxo, catalogo: dict[str, CatalogAction], empresa: ContextoEmpresa | None,
                      historico: list[dict[str, Any]]) -> str:
    linhas = [f"Processo: {processo.titulo} ({processo.area}). {processo.descricao}"]
    if processo.motivo:
        linhas.append(f"Por que foi sugerido: {processo.motivo}")
    if empresa:
        linhas.append("Perfil da empresa: " + "; ".join(f"{k}: {v}" for k, v in empresa.perfil.items() if v not in (None, "")))
    linhas += ["", "Catálogo de ações (nome — o que faz; risco; saídas; conexões):"]
    linhas += [f"- {a.name} — {a.title}: {a.description}; {a.risk}; saídas: {', '.join(a.output_fields)}"
               + (f"; conexões: {', '.join(a.connections)}" if a.connections else "") for a in catalogo.values()] or ["- (vazio)"]
    linhas += ["", "Fluxo atual:", _resumo_fluxo(fluxo), "", "Problemas agora:"]
    linhas += [f"- {p.nivel}: {p.texto}" for p in _problemas(fluxo, catalogo)] or ["- nenhum"]
    linhas += ["", "Conversa até aqui:"] + [f"{'Cliente' if m['papel'] == 'cliente' else 'Agente'}: {m['texto']}" for m in historico]
    return "\n".join(linhas)


def _ferramentas(processo_id: str, catalogo: dict[str, CatalogAction]) -> list[Any]:
    """As operações tipadas do agente de desenho: cada uma muda o rascunho e devolve os problemas."""

    async def aplicar(mudar: Callable[[Fluxo], str]) -> str:
        rascunho = await _rascunho(processo_id)
        fluxo = Fluxo.model_validate(rascunho["fluxo"])
        try:
            resumo = mudar(fluxo)
        except ValueError as exc:
            return f"Não aplicado: {exc}"
        anteriores = [*(rascunho.get("anteriores") or []), rascunho["fluxo"]][-UNDO:]
        await db.merge(_ref(VERSOES, rascunho), {"fluxo": fluxo.model_dump(mode="json"), "anteriores": anteriores,
                                                 "alteracoes": int(rascunho.get("alteracoes") or 0) + 1})
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo_id, action="alterado"))
        problemas = _problemas(fluxo, catalogo)
        return resumo + ". Problemas: " + ("; ".join(f"{p.nivel}: {p.texto}" for p in problemas) or "nenhum") + "."

    async def adicionar_passo(dados: NovoPasso) -> str:
        """Adiciona um passo ao fluxo; com depois_de, ele entra entre esse passo e o que vinha depois."""
        def mudar(fluxo: Fluxo) -> str:
            if fluxo.step(dados.id) or dados.id == START:
                raise ValueError(f"já existe um passo {dados.id}")
            fluxo.passos.append(Step.model_validate(dados.model_dump(exclude={"depois_de"})))
            if dados.depois_de:
                anterior = fluxo.step(dados.depois_de)
                if dados.depois_de != START and anterior is None:
                    raise ValueError(f"não existe o passo {dados.depois_de}")
                if anterior is not None and anterior.tipo == "decisao":
                    raise ValueError("depois de uma decisão, use ligar com a condição do caminho")
                saindo = fluxo.outgoing(dados.depois_de)
                for f in saindo:
                    fluxo.ligacoes.remove(f)
                    fluxo.ligacoes.append(Flow(de=dados.id, para=f.para))
                fluxo.ligacoes.append(Flow(de=dados.depois_de, para=dados.id))
            return f"Passo {dados.id} adicionado"
        return await aplicar(mudar)

    async def alterar_passo(dados: AlteracaoPasso) -> str:
        """Altera campos de um passo (só os enviados)."""
        def mudar(fluxo: Fluxo) -> str:
            step = fluxo.step(dados.id)
            if step is None:
                raise ValueError(f"não existe o passo {dados.id}")
            novo = Step.model_validate({**step.model_dump(), **dados.model_dump(exclude={"id"}, exclude_none=True)})
            fluxo.passos[fluxo.passos.index(step)] = novo
            return f"Passo {dados.id} alterado"
        return await aplicar(mudar)

    async def remover_passo(dados: RemocaoPasso) -> str:
        """Remove um passo; se ele tinha um caminho antes e um depois, os dois se ligam."""
        def mudar(fluxo: Fluxo) -> str:
            step = fluxo.step(dados.id)
            if step is None:
                raise ValueError(f"não existe o passo {dados.id}")
            entrando = [f for f in fluxo.ligacoes if f.para == dados.id]
            saindo = fluxo.outgoing(dados.id)
            fluxo.passos.remove(step)
            fluxo.ligacoes = [f for f in fluxo.ligacoes if dados.id not in (f.de, f.para)]
            if len(saindo) == 1:
                for f in entrando:
                    fluxo.ligacoes.append(Flow(de=f.de, para=saindo[0].para, condicao=f.condicao))
            return f"Passo {dados.id} removido"
        return await aplicar(mudar)

    async def ligar(dados: Ligacao) -> str:
        """Liga dois passos (de → para); saindo de decisão, com a condição do caminho ou sem ela no caminho padrão."""
        def mudar(fluxo: Fluxo) -> str:
            for no in (dados.de, dados.para):
                if no != START and fluxo.step(no) is None:
                    raise ValueError(f"não existe o passo {no}")
            origem = fluxo.step(dados.de)
            if origem is None or origem.tipo != "decisao":  # recusa na hora o que viraria erro: o agente acerta mais rápido
                if dados.condicao is not None:
                    raise ValueError(f"condições só saem de decisões: ponha uma decisão depois de {dados.de} "
                                     "(adicionar_passo tipo decisao com depois_de) e a condição nos caminhos dela")
                if outro := next((f.para for f in fluxo.outgoing(dados.de) if f.para != dados.para), None):
                    raise ValueError(f"{dados.de} já segue para {outro} e só tem um caminho; para trocar, desligue antes; "
                                     "para escolher entre caminhos, use uma decisão")
            fluxo.ligacoes = [f for f in fluxo.ligacoes if not (f.de == dados.de and f.para == dados.para)]
            fluxo.ligacoes.append(Flow(de=dados.de, para=dados.para, condicao=dados.condicao))
            return f"Ligação {dados.de} → {dados.para} feita"
        return await aplicar(mudar)

    async def desligar(dados: Desligamento) -> str:
        """Remove a ligação de → para."""
        def mudar(fluxo: Fluxo) -> str:
            antes = len(fluxo.ligacoes)
            fluxo.ligacoes = [f for f in fluxo.ligacoes if not (f.de == dados.de and f.para == dados.para)]
            if len(fluxo.ligacoes) == antes:
                raise ValueError(f"não existe a ligação {dados.de} → {dados.para}")
            return f"Ligação {dados.de} → {dados.para} removida"
        return await aplicar(mudar)

    async def definir_gatilho(dados: Trigger) -> str:
        """Define como o processo começa: evento (mensagem), agenda (cron) ou manual."""
        def mudar(fluxo: Fluxo) -> str:
            fluxo.gatilho = dados
            return "Gatilho definido"
        return await aplicar(mudar)

    async def definir_parametro(dados: Parametro) -> str:
        """Define um parâmetro do processo (regra do cliente, como limite_aprovacao = 5000)."""
        def mudar(fluxo: Fluxo) -> str:
            fluxo.parametros[dados.nome] = dados.valor
            return f"Parâmetro {dados.nome} = {dados.valor}"
        return await aplicar(mudar)

    async def simular(dados: Cenario) -> str:
        """Simula o rascunho com os exemplos (e o cenário, se vier) e devolve o caminho percorrido."""
        rascunho = await _rascunho(processo_id)
        resultado = _simular(Fluxo.model_validate(rascunho["fluxo"]), catalogo, dados)
        return json.dumps({"caminho": [f"{p.nome}: {p.nota}" for p in resultado.passos], "fim": resultado.fim,
                           "problemas": resultado.problemas}, ensure_ascii=False)

    return [adicionar_passo, alterar_passo, remover_passo, ligar, desligar, definir_gatilho, definir_parametro, simular]


def _valor(variaveis: dict[str, Any], campo: str) -> Any:
    passo, _, nome = campo.partition(".")
    return (variaveis.get(passo) or {}).get(nome)


def _avaliar(condicao: Condition, variaveis: dict[str, Any]) -> bool:
    return any(_avaliar_uma(alt, variaveis) for alt in condicao.alternatives())


def _avaliar_uma(condicao: Any, variaveis: dict[str, Any]) -> bool:
    atual = _valor(variaveis, condicao.campo)
    if condicao.operador == "verdadeiro":
        return atual is True
    if condicao.operador == "falso":
        return atual is False
    alvo = condicao.valor
    if isinstance(alvo, str) and alvo.startswith("parametros."):
        alvo = _valor(variaveis, alvo)
    try:
        a, b = float(atual), float(alvo)  # números (inclusive "1250") comparam como números
    except (TypeError, ValueError):
        a, b = atual, alvo
    try:
        return {"=": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[condicao.operador]
    except TypeError:
        return False


def _simular(fluxo: Fluxo, catalogo: dict[str, CatalogAction], cenario: Cenario) -> Simulacao:
    """Percorre o fluxo como o motor faria, com as saídas de exemplo; devolve o caminho para pintar no diagrama."""
    variaveis: dict[str, Any] = {"parametros": dict(fluxo.parametros)}
    caminho: list[str] = [START]
    passos: list[PassoSimulado] = []
    problemas = [p.texto for p in _problemas(fluxo, catalogo) if p.nivel == "erro"]
    proximo = next((f.para for f in fluxo.outgoing(START)), None)
    if proximo:
        caminho.append(f"f_{START}_{proximo}")
    sobrepor = lambda passo, saida: {**saida, **{k.partition(".")[2]: v for k, v in cenario.valores.items() if k.partition(".")[0] == passo}}  # noqa: E731
    for _ in range(200):
        step = fluxo.step(proximo) if proximo else None
        if step is None:
            return Simulacao(caminho=caminho, passos=passos, fim=None, problemas=problemas or ["O caminho parou num passo que não existe."])
        caminho.append(step.id)
        nota, seguinte = "", next((f.para for f in fluxo.outgoing(step.id)), None)
        if step.tipo == "acao":
            saida = sobrepor(step.id, dict(catalogo[step.acao].example) if step.acao in catalogo else {})
            variaveis[step.id], nota = saida, ", ".join(f"{k} = {v}" for k, v in saida.items())
        elif step.tipo == "agente":
            saida = sobrepor(step.id, {k: step.exemplo.get(k) for k in step.saidas})
            variaveis[step.id], nota = saida, ", ".join(f"{k} = {v}" for k, v in saida.items() if v is not None)
        elif step.tipo == "tarefa":
            aprovado = step.id not in cenario.recusas
            variaveis[step.id], nota = {"aprovado": aprovado}, f"{step.responsavel or 'pessoa'} respondeu {'sim' if aprovado else 'não'}"
        elif step.tipo == "decisao":
            escolhido = next((f for f in fluxo.outgoing(step.id) if f.condicao and _avaliar(f.condicao, variaveis)), None)
            escolhido = escolhido or next((f for f in fluxo.outgoing(step.id) if f.condicao is None), None)
            seguinte = escolhido.para if escolhido else None
            nota = f"seguiu para {fluxo.step(seguinte).nome if seguinte and fluxo.step(seguinte) else '?'}"
        elif step.tipo == "espera":
            nota = f"chegou {step.mensagem}" if step.espera == "mensagem" else f"esperou {step.horas or 0:g} h"
        if step.tipo in ("acao", "agente") and step.id in cenario.excecoes and step.excecao:
            caminho += [f"{step.id}__erro", f"f_{step.id}__erro", f"{step.id}__excecao"]
            nota = "caiu na exceção: o staff resolveu"
            if seguinte:
                caminho.append(f"f_{step.id}__excecao_{seguinte}")
                passos.append(PassoSimulado(id=step.id, nome=step.nome, tipo=step.tipo, nota=nota))
                proximo = seguinte
                continue
        passos.append(PassoSimulado(id=step.id, nome=step.nome, tipo=step.tipo, nota=nota))
        if step.tipo == "fim":
            return Simulacao(caminho=caminho, passos=passos, fim=step.resultado or step.nome, problemas=problemas)
        if not seguinte:
            return Simulacao(caminho=caminho, passos=passos, fim=None, problemas=problemas or [f"{step.nome} não tem caminho depois."])
        caminho.append(f"f_{step.id}_{seguinte}")
        proximo = seguinte
    return Simulacao(caminho=caminho, passos=passos, fim=None, problemas=["O fluxo voltou muitas vezes (laço sem saída)."])
