"""svc-processos · lógica de negócio pura. Fonte da verdade: specs/processos.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py (ou é um gerador de pedaços, que não vira activity), e vira a activity "processos.<método>".
O perfil e o conhecimento da empresa vêm do svc-conhecimento por RPC (rpc.conhecimento.*), na organização de quem age.
"""
import asyncio
import hashlib
import inspect
import json
import logging
import re
import unicodedata
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from nats.errors import Error as NatsError
from pydantic import BaseModel, Field, create_model

from core.envelope import ServiceError
from core.llm import AgentStep, llm
from core.nats_bus import bus
from core.plans import plans
from core.notify import notify
from core.processes import (
    END,
    START,
    CatalogIndicator,
    IndicatorRequest,
    IndicatorValues,
    indicators_subject,
    ActionCatalog,
    CatalogAction,
    Condition,
    Flow,
    Fluxo,
    Handoff,
    Job,
    Step,
    Trigger,
    camunda,
    exception_merge,
    process_id,
    step_outputs,
    to_bpmn,
)
from core.security import SYSTEM_PREFIX, Principal, acting_as, current, current_tenant, system
from core.surreal import Migration, db
from core.temporal_runner import activities, runner

from schemas import (
    BLOQUEIOS,
    FUSO,
    FimAlcancado,
    MarcaVersao,
    MesAutonomia,
    ResultadoProcesso,
    Resultados,
    ResultadosPedido,
    ResultadosQuery,
    ResumoMensal,
    ResumoMensalIn,
    ValorIndicador,
    PLANS_SERVICE,
    CancelarExecucao,
    IniciarModelo,
    VoltarVersao,
    STAFF_SERVICE,
    AGENTES_EXECUTAR_SUBJECT,
    AGENTES_LISTA_SUBJECT,
    AgenteDaEmpresa,
    AgentesDaEmpresa,
    ExecucaoDeAgente,
    ExecutarAgente,
    UsoDeAgente,
    ACOES,
    BIBLIOTECA,
    CADEIA,
    MODELOS,
    BUSCA_SUBJECT,
    CONTEXTO_SUBJECT,
    DESCOBERTA_INSTRUCOES,
    DESCRICAO_INSTRUCOES,
    DESENHO_INSTRUCOES,
    DESIGNERS,
    DOCUMENTO_SUBJECT,
    EXECUCAO_INSTRUCOES,
    EXECUCOES,
    HISTORY,
    LIVE_DESENHO,
    LIVE_EXECUCOES,
    LIVE_PROCESSOS,
    LIVE_REGRAS,
    LIVE_TAREFAS,
    MENSAGENS,
    OPERADORES,
    PASSOS,
    PROCESSOS,
    REGRAS,
    SERVICE,
    STAFF_SUBJECT,
    STARTERS,
    TAREFAS,
    TASK_QUEUE,
    UNDO,
    VERSOES,
    WRITERS,
    Achados,
    AdicionarModelo,
    EtapaProjeto,
    ModeloDeclarado,
    Projeto,
    ProjetoPage,
    ProjetoQuery,
    ProcessoLigado,
    Acompanhamento,
    AcompanhamentoProcesso,
    AcaoPacote,
    AcoesPacotes,
    AjudaIn,
    AlteracaoPasso,
    Autonomia,
    Avaliacao,
    Biblioteca,
    BuscaQuery,
    Campo,
    CatalogoAcoes,
    Cenario,
    ContextoEmpresa,
    Descoberta,
    Descricao,
    Desenho,
    DesenhoMudou,
    DecisaoStaff,
    DesenhoRef,
    Desligamento,
    Devolucao,
    DocumentoRef,
    DocumentoTexto,
    Empty,
    EventoExterno,
    Execucao,
    ExecucaoDetalhe,
    ExecucaoMudou,
    ExecucaoPage,
    ExecucaoQuery,
    ExecucaoRef,
    Iniciar,
    Item,
    ItemStaff,
    LeituraDocumento,
    Ligacao,
    Marco,
    MensagemDesenho,
    MensagemDesenhoIn,
    Motor,
    NovoPasso,
    Parametro,
    PassoAgente,
    PassoFeito,
    PassoSimulado,
    Problema,
    Processo,
    ProcessoDescrito,
    ProcessoMudou,
    ProcessoPage,
    ProcessoQuery,
    ProcessoRef,
    ProcessosSettings,
    Regra,
    RegraMudou,
    RegraQuery,
    RegraRef,
    Regras,
    RemocaoPasso,
    ResolucaoStaff,
    Resposta,
    RevisaoRef,
    RevisaoResumo,
    Resumo,
    RevisaoIn,
    SaidaAgente,
    Simulacao,
    SimulacaoIn,
    Sugestao,
    Tarefa,
    TarefaMudou,
    TarefaPage,
    TarefaQuery,
    TarefaRef,
    Versao,
    VersaoResumo,
)

MIGRATIONS: list[Migration] = []
settings = ProcessosSettings()
log = logging.getLogger(SERVICE)
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
        who = current()
        return Resumo(sugeridos=total.get("sugerido", 0), aceitos=total.get("aceito", 0), recusados=total.get("recusado", 0),
                      publicados=await _publicados(), staff=who is not None and _e_staff(who))

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

    async def adicionar(self, data: AdicionarModelo) -> Processo:
        """A empresa escolhe um modelo direto da biblioteca: o processo nasce aceito (o que já existia desse modelo,
        sugerido ou recusado, passa a aceito)."""
        _writer()
        modelo = _MODELOS[data.modelo]
        rows = await db.query(f"SELECT * FROM {PROCESSOS} WHERE tenant = $tenant AND modelo = $modelo LIMIT 1", modelo=modelo.id)
        if rows:
            if rows[0]["status"] == "aceito":
                return _processo(rows[0])
            return await _mudar(_short(rows[0]["id"]), "aceito")
        row = await db.create(PROCESSOS, {"modelo": modelo.id, "area": modelo.area, "titulo": modelo.titulo, "descricao": modelo.resumo,
                                          "motivo": None, "origem": "biblioteca", "status": "aceito", "prioridade": "media"})
        processo = _processo(row)
        await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=processo.id, action="aceito"))
        return processo

    async def recusar(self, data: ProcessoRef) -> Processo:
        return await _mudar(data.id, "recusado")

    # ── Catálogo de ações dos pacotes ────────────────────────────────────────

    async def pausar(self, data: ProcessoRef) -> Processo:
        """Pausa um processo publicado: o gatilho não inicia execução nova (as em andamento terminam). Dono, admin ou
        operador."""
        return await _pausar(data.id, True)

    async def retomar(self, data: ProcessoRef) -> Processo:
        """Retoma o processo pausado: o próximo gatilho volta a iniciar."""
        return await _pausar(data.id, False)

    async def registrar_catalogo(self, data: ActionCatalog) -> Empty:
        """events.processos.catalogo: o pacote declarou as ações e os fluxos de partida dos modelos no boot; troca os
        dele no catálogo. Modelo que não está na biblioteca fica de fora (a biblioteca é o que a Cogniventure vende)."""
        await db.query_shared(f"DELETE FROM {ACOES} WHERE service = $service", service=data.service)
        for acao in data.actions:
            await db.query_shared(f"CREATE {ACOES} CONTENT $acao", acao=acao.model_dump(mode="json"))
        await db.query_shared(f"DELETE FROM {MODELOS} WHERE service = $service", service=data.service)
        for modelo in data.models:
            if modelo.id in _MODELOS:
                await db.query_shared(f"DELETE FROM {MODELOS} WHERE modelo = $modelo", modelo=modelo.id)  # mudou de pacote
                await db.query_shared(f"CREATE {MODELOS} CONTENT $m", m={"modelo": modelo.id, "service": data.service,
                                                                        "fluxo": modelo.fluxo.model_dump(mode="json"),
                                                                        "indicadores": [i.model_dump(mode="json") for i in modelo.indicadores]})
        return Empty()

    async def catalogo(self, data: Empty) -> CatalogoAcoes:
        return CatalogoAcoes(itens=list((await _catalogo()).values()))

    async def acoes(self, data: Empty) -> AcoesPacotes:
        """rpc.processos.acoes (svc-agentes): as ações dos pacotes ligados no plano da organização, com o título do
        pacote, para um agente da empresa usar como ferramenta (o pacote roda por rpc.<pacote>.acao). Sem resposta do
        svc-plans, todas, com o nome do pacote no lugar do título."""
        modulos = {m.name: m for m in (await plans.limits()).modules}
        itens = []
        for acao in (await _catalogo()).values():
            modulo = modulos.get(acao.service.removeprefix("svc-"))
            if modulo is None or modulo.enabled:
                itens.append(AcaoPacote(**acao.model_dump(), pacote=modulo.title if modulo else acao.service.removeprefix("svc-")))
        return AcoesPacotes(itens=itens)

    # ── Desenho: versões, conversa, simulação e publicação ───────────────────

    async def abrir(self, data: DesenhoRef) -> Desenho:
        """Abre o desenho do processo aceito; na primeira vez nasce o rascunho 1 a partir do fluxo de partida."""
        processo = await _processo_por_id(data.processo)
        if processo.status != "aceito":
            raise ServiceError("ERRO_PROCESSOS_NAO_ACEITO", "Aceite o processo antes de desenhá-lo.", 409)
        if not await _versoes(processo.id):
            _desenhista()
            try:
                await db.create(VERSOES, {"processo": processo.id, "numero": 1, "status": "rascunho",
                                          "fluxo": (await _partida(processo)).model_dump(mode="json"), "anteriores": [], "alteracoes": 0})
            except ServiceError as exc:  # duas abas abrindo ao mesmo tempo: a outra criou o rascunho 1
                if exc.code != "ERRO_RECORD_DUPLICATE":
                    raise
        return await _desenho(processo.id)

    async def conversar(self, data: MensagemDesenhoIn) -> AsyncIterator[PassoAgente | Desenho]:
        """Uma mensagem no desenho (da empresa ou do staff, no setup): o agente edita o rascunho pelas operações;
        cada uma é um passo."""
        who = _desenhista()
        processo = await _processo_por_id(data.processo)
        rascunho = await _rascunho(processo.id)
        historico = await _mensagens(processo.id)
        try:
            empresa = await _contexto_da_empresa()
        except ServiceError:
            empresa = None
        await db.create(MENSAGENS, {"processo": processo.id, "papel": _papel(who), "autor": who.sub, "texto": data.texto, "passos": []})
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="mensagem"))
        catalogo = await _catalogo()
        agentes = await _agentes()
        fila: asyncio.Queue[AgentStep | None] = asyncio.Queue()
        feitos: list[str] = []

        def passo(step: AgentStep) -> None:
            if step.status == "done" and (rotulo := PASSOS.get(step.tool, step.tool)) not in feitos:
                feitos.append(rotulo)
            fila.put_nowait(step)

        async def rodar(tarefa: str) -> str:
            rascunho_agora = await _rascunho(processo.id)
            contexto = _contexto_desenho(processo, Fluxo.model_validate(rascunho_agora["fluxo"]), catalogo, empresa, historico, agentes)
            argumentos = dict(instructions=DESENHO_INSTRUCOES, tools=_ferramentas(processo.id, catalogo, agentes), context=contexto,
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
            pedido = f"Mensagem {'do staff da Cogniventure' if _papel(who) == 'staff' else 'do cliente'}:\n{data.texto}\n\n"
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
        _desenhista()
        rascunho = await _rascunho(data.processo)
        anteriores = list(rascunho.get("anteriores") or [])
        if not anteriores:
            raise ServiceError("ERRO_PROCESSOS_NADA_A_DESFAZER", "Não há alteração para desfazer.", 409)
        await db.merge(_ref(VERSOES, rascunho), {"fluxo": anteriores.pop(), "anteriores": anteriores,
                                                 "alteracoes": max(0, int(rascunho.get("alteracoes") or 0) - 1)})
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=data.processo, action="alterado"))
        return await _desenho(data.processo)

    async def publicar(self, data: DesenhoRef) -> Desenho:
        """Publica o rascunho: implanta no Camunda (a versão seguinte do processo no motor) e arquiva a anterior. Com
        ação irreversível ou conexão que a publicada não tinha, só o staff publica (a empresa pede a revisão)."""
        who = _desenhista()
        processo = await _processo_por_id(data.processo)
        rascunho = await _rascunho(processo.id)
        if not _e_staff(who) and await _precisa_revisao(processo.id, rascunho):
            raise ServiceError("ERRO_PROCESSOS_REVISAO", "Esta versão traz ação irreversível ou conexão nova: peça a revisão do staff da Cogniventure.", 409)
        return await _publicar(processo, rascunho)

    async def pedir_revisao(self, data: RevisaoIn) -> Desenho:
        """A empresa pede a revisão do staff: o rascunho fica em revisão (ninguém edita) até o staff publicar ou devolver."""
        who = _desenhista()
        processo = await _processo_por_id(data.processo)
        rascunho = await _rascunho(processo.id)
        erros = [p for p in _problemas(Fluxo.model_validate(rascunho["fluxo"]), await _catalogo()) if p.nivel == "erro"]
        if erros:
            raise ServiceError("ERRO_PROCESSOS_FLUXO_INVALIDO", "O fluxo tem problemas: " + "; ".join(e.texto for e in erros[:3]), 409)
        await db.merge(_ref(VERSOES, rascunho), {"status": "revisao"})
        texto = "Pedi a revisão do staff" + (f": {data.mensagem}" if data.mensagem else ".")
        await db.create(MENSAGENS, {"processo": processo.id, "papel": _papel(who), "autor": who.sub, "texto": texto, "passos": []})
        await _ao_staff(ItemStaff(tipo="revisao", ref=processo.id, titulo=f"{processo.titulo}: revisão da versão {rascunho['numero']}",
                                  detalhe=data.mensagem, status="aberta", link=f"/processos/{processo.id}", em=datetime.now(UTC)))
        await notify.roles("operador", title=f"Revisão pedida: {processo.titulo}", body=data.mensagem or "", link=f"/processos/{processo.id}",
                           key=f"revisao-{processo.id}-{rascunho['numero']}")
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="alterado"))
        return await _desenho(processo.id)

    async def aprovar_revisao(self, data: DesenhoRef) -> Desenho:
        """O staff revisou: publica a versão em revisão."""
        who = _operador()
        processo = await _processo_por_id(data.processo)
        revisao = await _em_revisao(processo.id)
        await _publicar(processo, revisao)
        await db.create(MENSAGENS, {"processo": processo.id, "papel": "staff", "autor": who.sub,
                                    "texto": f"Revisei e publiquei a versão {revisao['numero']}.", "passos": []})
        return await _desenho(processo.id)

    async def devolver(self, data: Devolucao) -> Desenho:
        """O staff devolve a versão em revisão para a empresa, com o que precisa mudar."""
        who = _operador()
        processo = await _processo_por_id(data.processo)
        revisao = await _em_revisao(processo.id)
        await db.merge(_ref(VERSOES, revisao), {"status": "rascunho"})
        await db.create(MENSAGENS, {"processo": processo.id, "papel": "staff", "autor": who.sub,
                                    "texto": f"Devolvi para ajuste: {data.motivo}", "passos": []})
        await _ao_staff(ItemStaff(tipo="revisao", ref=processo.id, titulo=f"{processo.titulo}: revisão da versão {revisao['numero']}",
                                  status="concluida", link=f"/processos/{processo.id}", em=datetime.now(UTC)))
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="alterado"))
        return await _desenho(processo.id)

    async def pedir_ajuda(self, data: AjudaIn) -> Desenho:
        """A empresa pede ajuda ao staff no setup: o pedido vai para a fila da carteira; o staff entra na conversa."""
        who = _desenhista()
        processo = await _processo_por_id(data.processo)
        if not await _versoes(processo.id):
            raise ServiceError("ERRO_PROCESSOS_SEM_DESENHO", "Abra o desenho do processo primeiro.", status=409)
        agora = datetime.now(UTC)
        await db.merge(f"{PROCESSOS}:{processo.id}", {"ajuda": {"texto": data.texto, "por": who.sub, "em": agora}})
        await db.create(MENSAGENS, {"processo": processo.id, "papel": _papel(who), "autor": who.sub,
                                    "texto": f"Pedi ajuda ao staff: {data.texto}", "passos": []})
        await _ao_staff(ItemStaff(tipo="ajuda", ref=processo.id, titulo=f"{processo.titulo}: ajuda no desenho", detalhe=data.texto,
                                  status="aberta", link=f"/processos/{processo.id}", em=agora))
        await notify.roles("operador", title=f"Pedido de ajuda: {processo.titulo}", body=data.texto, link=f"/processos/{processo.id}",
                           key=f"ajuda-{processo.id}-{int(agora.timestamp())}")
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="mensagem"))
        return await _desenho(processo.id)

    async def concluir_ajuda(self, data: DesenhoRef) -> Desenho:
        _desenhista()
        processo = await _processo_por_id(data.processo)
        await _fechar_ajuda(processo)
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="alterado"))
        return await _desenho(processo.id)

    async def ajustar(self, data: DesenhoRef) -> Desenho:
        """Abre um rascunho novo a partir da versão publicada (as execuções em andamento seguem na versão delas)."""
        _desenhista()
        versoes = await _versoes(data.processo)
        if any(v["status"] in ("rascunho", "revisao") for v in versoes):
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
        _desenhista()
        rascunho = await _rascunho(data.processo)
        if not any(v["status"] == "publicada" for v in await _versoes(data.processo)):
            raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", "O primeiro rascunho não se descarta: ajuste-o ou recuse o processo.", 409)
        await db.delete(_ref(VERSOES, rascunho))
        await bus.live(LIVE_DESENHO, DesenhoMudou(processo=data.processo, action="descartado"))
        return await _desenho(data.processo)


    async def voltar(self, data: VoltarVersao) -> Desenho:
        """Voltar a uma versão do histórico: o fluxo dela vira a próxima versão e é publicado; se a regra pede a revisão
        do staff (ação irreversível, conexão ou agente que a publicada não tem), vai para a revisão. Dono, admin ou
        operador; com rascunho aberto, descarte antes."""
        who = _desenhista()
        processo = await _processo_por_id(data.processo)
        versoes = await _versoes(processo.id)
        if any(v["status"] in ("rascunho", "revisao") for v in versoes):
            raise ServiceError("ERRO_PROCESSOS_RASCUNHO_ABERTO", "Há um rascunho aberto: descarte-o (ou publique) antes de voltar a uma versão.", 409)
        alvo = next((v for v in versoes if int(v["numero"]) == data.numero), None)
        if alvo is None or alvo["status"] != "arquivada":
            raise ServiceError("ERRO_PROCESSOS_VERSAO", "Escolha uma versão anterior do histórico (a publicada já é a que roda).", 409)
        numero = max(int(v["numero"]) for v in versoes) + 1
        rascunho = await db.create(VERSOES, {"processo": processo.id, "numero": numero, "status": "rascunho", "fluxo": alvo["fluxo"],
                                             "anteriores": [], "alteracoes": 0, "volta_de": data.numero})
        try:
            if not _e_staff(who) and await _precisa_revisao(processo.id, rascunho):
                desenho = await self.pedir_revisao(RevisaoIn(processo=processo.id, mensagem=f"Voltar à versão {data.numero}"))
            else:
                desenho = await _publicar(processo, rascunho)
        except ServiceError:
            await db.delete(_ref(VERSOES, rascunho))  # não publicou nem foi à revisão: nada muda
            raise
        texto = f"Voltei à versão {data.numero}: ela vira a versão {numero}" + (", em revisão do staff." if desenho.versao.status == "revisao" else ".")
        await db.create(MENSAGENS, {"processo": processo.id, "papel": _papel(who), "autor": who.sub, "texto": texto, "passos": []})
        return await _desenho(processo.id)

    # ── Execução: gatilhos, acompanhamento e tarefas de pessoas ───────────────

    async def receber_evento(self, data: EventoExterno) -> Empty:
        """events.integracoes.evento: inicia os processos publicados cujo gatilho é este evento e, com chave, entrega a
        mensagem à execução que espera por ela (ex.: banco.pago com o id do pagamento)."""
        origem = bus.message_id()
        resumo = data.dados.get("resumo") or data.dados.get("nome") or data.dados.get("assunto")
        for processo, versao in await _publicados_por_evento(data.nome):
            try:
                await _iniciar(processo, versao, origem="evento", gatilho=data.dados, resumo=str(resumo) if resumo else data.nome,
                               chave=f"{origem}:{processo.id}" if origem else None)
            except ServiceError as exc:
                if exc.code not in BLOQUEIOS:
                    raise
                log.info("evento %s não iniciou %s: %s", data.nome, processo.id, exc.code)  # pausado ou conta suspensa
        if data.chave:
            await camunda.message(f"{current_tenant()}.{data.nome}", data.chave, {"mensagem": data.dados}, message_id=origem)
        return Empty()

    async def iniciar(self, data: Iniciar) -> Execucao:
        """Inicia à mão uma execução do processo publicado (dono, admin ou operador); dados = o que o gatilho traria."""
        who = current()
        if who is None or not (who.is_system or STARTERS & who.roles):
            raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só donos, administradores e operadores iniciam execuções.", 403)
        processo = await _processo_por_id(data.processo)
        publicada = next((v for v in await _versoes(processo.id) if v["status"] == "publicada"), None)
        if publicada is None:
            raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", "Publique o processo antes de iniciar uma execução.", 409)
        return await _iniciar(processo, publicada, origem="manual", gatilho={**data.dados, "origem": "manual"}, resumo="Iniciada à mão")

    async def iniciar_modelo(self, data: IniciarModelo) -> Execucao:
        """rpc.processos.iniciar_modelo (só o svc-plans): inicia o processo publicado deste modelo na organização de quem
        pede, com os dados no gatilho (o fechamento do mês inicia o Faturamento e cobrança na Cogniventure)."""
        who = current()
        if who is None or who.sub != f"{SYSTEM_PREFIX}{PLANS_SERVICE}" or not who.tenant:
            raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só o svc-plans inicia por modelo.", 403)
        for processo in await _todos():
            if processo.modelo != data.modelo or processo.publicada is None:
                continue
            publicada = next((v for v in await _versoes(processo.id) if v["status"] == "publicada"), None)
            if publicada is not None:
                return await _iniciar(processo, publicada, origem="agenda", gatilho={**data.dados, "origem": "agenda"},
                                      resumo=data.resumo, chave=data.chave)
        modelo = _MODELOS.get(data.modelo)
        nome = modelo.titulo if modelo else data.modelo
        raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", f"Publique o {nome} para iniciar por aqui.", 409)

    async def cancelar_execucao(self, data: CancelarExecucao) -> Execucao:
        """Cancela uma execução em andamento (dono, admin ou operador), com o motivo na linha do tempo. Não desfaz o que
        já aconteceu fora da plataforma (a tela avisa antes: ExecucaoDetalhe.efeitos). As tarefas abertas dela fecham."""
        who = current()
        if who is None or not (who.is_system or STARTERS & who.roles):
            raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só donos, administradores e operadores cancelam execuções.", 403)
        row = await db.select(f"{EXECUCOES}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Execução não encontrada.", 404)
        execucao = Execucao.model_validate(row)
        if execucao.status not in ("andamento", "incidente"):
            raise ServiceError("ERRO_PROCESSOS_EXECUCAO_FECHADA", "Esta execução já terminou.", 409)
        await camunda.cancel(execucao.instancia)
        agora = datetime.now(UTC)
        abertas = await db.query(f"SELECT * FROM {TAREFAS} WHERE tenant = $tenant AND instancia = $i AND status = 'aberta'", i=execucao.instancia)
        for tarefa in (Tarefa.model_validate(t) for t in abertas):
            await db.merge(f"{TAREFAS}:{tarefa.id}", {"status": "concluida", "resposta": {"cancelada": data.motivo},
                                                       "concluida_por": who.sub, "concluida_em": agora})
            await bus.live(LIVE_TAREFAS, TarefaMudou(id=tarefa.id, action="concluida"))
            if tarefa.responsavel == "staff":
                await _ao_staff(ItemStaff(tipo="excecao", ref=tarefa.id, titulo=f"{tarefa.titulo}: {tarefa.nome}", status="concluida",
                                          link="/processos/tarefas", em=agora))
        await _marcar(execucao.instancia, Marco(passo=execucao.passo_atual or START, nome="Cancelada", status="cancelada", em=agora,
                                                motivo=data.motivo, por=who.sub),
                      aguardando=None, atual=(None, None), final={"status": "cancelada", "concluida_em": agora})
        await bus.live(LIVE_EXECUCOES, ExecucaoMudou(id=execucao.id, action="cancelada"))
        return Execucao.model_validate(await db.select(f"{EXECUCOES}:{execucao.id}"))

    async def execucoes(self, data: ExecucaoQuery) -> ExecucaoPage:
        return await db.page(EXECUCOES, data, ExecucaoPage)

    async def execucao(self, data: ExecucaoRef) -> ExecucaoDetalhe:
        """A execução com o BPMN da versão dela e o caminho percorrido (o motor diz por onde passou)."""
        row = await db.select(f"{EXECUCOES}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Execução não encontrada.", 404)
        execucao = Execucao.model_validate(row)
        versao = await _versao_do_motor(execucao.processo, execucao.motor_versao)
        fluxo = Fluxo.model_validate(versao["fluxo"]) if versao else Fluxo()
        bpmn = to_bpmn(fluxo, process_id=_motor_id(execucao.processo), name=execucao.titulo, actions=await _catalogo())
        elementos = await camunda.path(execucao.instancia)
        visitados = [e["id"] for e in elementos]
        concluidos = {e["id"] for e in elementos if e["estado"] == "COMPLETED"}  # interrompido (exceção) não segue em frente
        ligacoes = re.findall(r'<bpmn:sequenceFlow id="([^"]+)" sourceRef="([^"]+)" targetRef="([^"]+)"', bpmn)
        caminho = [*dict.fromkeys(visitados), *(fid for fid, de, para in ligacoes if de in concluidos and para in visitados)]
        atuais = [e["id"] for e in elementos if e["estado"] == "ACTIVE"]
        cadeia = await _etapas(execucao.projeto) if execucao.projeto else []
        catalogo = await _catalogo()
        feitos = {m.passo for m in execucao.marcos if m.status == "concluido"}
        efeitos = [s.nome for s in fluxo.passos if s.id in feitos and s.tipo == "acao" and s.acao in catalogo
                   and catalogo[s.acao].risk in ("externa", "irreversivel")]
        return ExecucaoDetalhe(execucao=execucao, bpmn=bpmn, caminho=caminho, atuais=atuais, cadeia=cadeia, efeitos=efeitos)

    async def projetos(self, data: ProjetoQuery) -> ProjetoPage:
        """As cadeias de processos (um que terminou e iniciou outros), cada uma como um projeto com as execuções dela."""
        raizes = await db.page(EXECUCOES, data, ExecucaoPage, where="raiz = true")
        etapas = await _etapas_de([e.id for e in raizes.items])
        itens = []
        for raiz in raizes.items:
            delas = etapas.get(raiz.id) or [EtapaProjeto.model_validate(raiz.model_dump())]
            status = "atencao" if any(e.status == "incidente" for e in delas) else (
                "andamento" if any(e.status == "andamento" for e in delas) else "concluido")
            itens.append(Projeto(id=raiz.id, titulo=raiz.titulo, resumo=raiz.resumo, status=status, etapas=delas, created_at=raiz.created_at))
        return ProjetoPage(items=itens, total=raizes.total, page=raizes.page, size=raizes.size, pages=raizes.pages)

    # ── A fila do staff resolve sem trocar de organização (só o svc-staff) ──

    async def fila_tarefa(self, data: TarefaRef) -> Tarefa:
        """rpc.processos.fila_tarefa: a exceção inteira (campos, contexto, motivo), para o cartão da fila."""
        _da_fila()
        row = await db.select(f"{TAREFAS}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Tarefa não encontrada.", 404)
        return Tarefa.model_validate(row)

    async def fila_resolver(self, data: ResolucaoStaff) -> Tarefa:
        """rpc.processos.fila_resolver: o staff resolve a exceção pela fila, como se estivesse na tela do cliente."""
        _da_fila()
        with acting_as(_como_operador(data.por)):
            return await self.responder(Resposta(id=data.id, dados=data.dados, comentario=data.comentario, regra=data.regra))

    async def fila_revisao(self, data: RevisaoRef) -> RevisaoResumo:
        """rpc.processos.fila_revisao: a versão em revisão e o que ela muda na publicada, para o cartão da fila."""
        _da_fila()
        desenho = await _desenho(data.processo)
        return RevisaoResumo(processo=desenho.processo.id, titulo=desenho.processo.titulo, numero=desenho.versao.numero,
                             status=desenho.versao.status, mudancas=desenho.mudancas)

    async def fila_decidir(self, data: DecisaoStaff) -> RevisaoResumo:
        """rpc.processos.fila_decidir: o staff aprova (publica) ou devolve a versão em revisão pela fila."""
        _da_fila()
        with acting_as(_como_operador(data.por)):
            if data.aprovar:
                await self.aprovar_revisao(DesenhoRef(processo=data.processo))
            else:
                if not data.motivo:
                    raise ServiceError("ERRO_PROCESSOS_RESPOSTA", "Diga o que precisa mudar.", 422)
                await self.devolver(Devolucao(processo=data.processo, motivo=data.motivo))
        return await self.fila_revisao(RevisaoRef(processo=data.processo))

    async def tarefas(self, data: TarefaQuery) -> TarefaPage:
        return await db.page(TAREFAS, data, TarefaPage)

    async def responder(self, data: Resposta) -> Tarefa:
        """Resolve uma tarefa: aprovação (dono ou admin) ou exceção (operador, com a saída do passo que parou)."""
        row = await db.select(f"{TAREFAS}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Tarefa não encontrada.", 404)
        tarefa = Tarefa.model_validate(row)
        who = current()
        pode = WRITERS if tarefa.responsavel == "cliente" else OPERADORES
        if who is None or not (who.is_system or pode & who.roles or (tarefa.responsavel == "staff" and _e_staff(who))):
            quem = "donos e administradores" if tarefa.responsavel == "cliente" else "operadores do staff"
            raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", f"Esta tarefa é para {quem}.", 403)
        if tarefa.status != "aberta":
            raise ServiceError("ERRO_PROCESSOS_TAREFA_FECHADA", "Esta tarefa já foi resolvida.", 409)
        if data.regra and not tarefa.aprende:
            raise ServiceError("ERRO_PROCESSOS_REGRA", "Só a exceção de um passo de agente vira regra.", 422)
        if tarefa.tipo == "aprovacao":
            if data.aprovado is None:
                raise ServiceError("ERRO_PROCESSOS_RESPOSTA", "Diga se aprova ou não.", 422)
            resposta: dict[str, Any] = {"aprovado": data.aprovado, "comentario": data.comentario or ""}
        else:
            resposta = _valores_da_excecao(tarefa, data)
        await camunda.complete_task(tarefa.chave, {tarefa.passo: resposta})
        agora = datetime.now(UTC)
        row = await db.merge(f"{TAREFAS}:{tarefa.id}", {"status": "concluida", "resposta": resposta,
                                                         "concluida_por": who.sub if who else None, "concluida_em": agora})
        await _marcar(tarefa.instancia, Marco(passo=tarefa.passo, nome=tarefa.nome, status="resolvido", em=agora, por=who.sub if who else None,
                                              motivo=None if tarefa.tipo == "excecao" else ("aprovado" if data.aprovado else "recusado")),
                      saida=(tarefa.passo, resposta), aguardando=None)
        await bus.live(LIVE_TAREFAS, TarefaMudou(id=tarefa.id, action="concluida"))
        if tarefa.responsavel == "staff":
            await _ao_staff(ItemStaff(tipo="excecao", ref=tarefa.id, titulo=f"{tarefa.titulo}: {tarefa.nome}", status="concluida",
                                      link="/processos/tarefas", em=agora))
        if data.regra:
            await _nova_regra(tarefa, row, data.regra, resposta, who.sub if who else None)
        return Tarefa.model_validate(row)

    async def acompanhamento(self, data: Empty) -> Acompanhamento:
        """O passo de acompanhamento da jornada: execuções, tarefas, atrasos e autonomia por processo e por versão."""
        execucoes = await db.query(f"SELECT processo, titulo, versao, status, handoffs FROM {EXECUCOES} WHERE tenant = $tenant")
        abertas = await db.query(f"SELECT responsavel, prazo FROM {TAREFAS} WHERE tenant = $tenant AND status = 'aberta'")
        aceitos = await db.query(f"SELECT publicada FROM {PROCESSOS} WHERE tenant = $tenant AND status = 'aceito'")
        agora = datetime.now(UTC)
        processos: dict[str, AcompanhamentoProcesso] = {}
        for pid in dict.fromkeys(e["processo"] for e in execucoes):
            delas = [e for e in execucoes if e["processo"] == pid]
            versoes = sorted({e.get("versao") for e in delas if e.get("versao") is not None})
            processos[pid] = AcompanhamentoProcesso(
                processo=pid, titulo=delas[0]["titulo"], andamento=sum(1 for e in delas if e["status"] == "andamento"),
                geral=_autonomia(delas), por_versao=[_autonomia([e for e in delas if e.get("versao") == v], v) for v in versoes])
        return Acompanhamento(
            andamento=sum(1 for e in execucoes if e["status"] == "andamento"),
            concluidas=sum(1 for e in execucoes if e["status"] == "concluida"),
            incidentes=sum(1 for e in execucoes if e["status"] == "incidente"),
            tarefas_cliente=sum(1 for t in abertas if t["responsavel"] == "cliente"),
            tarefas_staff=sum(1 for t in abertas if t["responsavel"] == "staff"),
            atrasadas=sum(1 for t in abertas if t.get("prazo") and _quando(t["prazo"]) < agora),
            autonomia=_autonomia(execucoes).autonomia, processos=list(processos.values()),
            aceitos=len(aceitos), publicados=sum(1 for p in aceitos if p.get("publicada")))

    # ── Resultados (alinhamento pós-N7, item 7) ──────────────────────────────

    async def resultados(self, data: ResultadosQuery) -> Resultados:
        """A tela Resultados: para cada processo publicado, a autonomia mês a mês com as versões marcadas, as execuções do
        mês por fim alcançado e os indicadores de negócio que o modelo declara. Todo membro."""
        return await _resultados(data.mes or _mes_atual(), data.meses)

    async def resultados_staff(self, data: ResultadosPedido) -> Resultados:
        """rpc.processos.resultados (só o svc-staff): os mesmos números, para a carteira do staff."""
        _da_fila()
        return await _resultados(data.mes or _mes_atual(), data.meses)

    async def resumo_mensal(self, data: ResumoMensalIn) -> ResumoMensal:
        """Agendado no dia 1 (ou com o mês): o resumo do mês que acabou ao dono de cada organização com processo publicado
        (tela e e-mail): execuções, autonomia e os indicadores de cada processo. Conta encerrada não recebe."""
        mes = data.mes or _mes_anterior(_mes_atual())
        organizacoes = enviados = 0
        for org in await db.tenants(PROCESSOS):
            with acting_as(system(SERVICE, org)):
                resultados = await _resultados(mes, 1)
                if not resultados.processos:
                    continue
                organizacoes += 1
                if await plans.situacao() == "encerrada":
                    continue
                await notify.roles("owner", title=f"Resultados de {_mes_extenso(mes)}", body=_texto_resumo(resultados),
                                   link=f"/processos/resultados?mes={mes}", action="Ver resultados", key=f"resumo-{mes}")
                enviados += 1
        return ResumoMensal(mes=mes, organizacoes=organizacoes, enviados=enviados)

    async def registrar_passo(self, data: PassoFeito) -> Empty:
        """events.processos.passo: o worker de um pacote concluiu um passo, mandou ao staff ou abriu incidente."""
        nome = await _nome_do_passo(data.processo, data.motor_versao, data.passo)
        marco = Marco(passo=data.passo, nome=nome, status=data.status, em=data.em or datetime.now(UTC), motivo=data.motivo)
        await _marcar(data.instancia, marco, saida=(data.passo, data.saida) if data.status == "concluido" else None,
                      handoff=data.status == "handoff", incidente=data.status == "incidente")
        return Empty()

    # ── Regras aprendidas com o handoff (briefing.md §5.7) ──────────────────

    async def regras(self, data: RegraQuery) -> Regras:
        return Regras(itens=await _regras(data.processo))

    async def desativar_regra(self, data: RegraRef) -> Regra:
        _desenhista()
        row = await db.select(f"{REGRAS}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Regra não encontrada.", 404)
        regra = Regra.model_validate(await db.merge(f"{REGRAS}:{data.id}", {"status": "desativada"}))
        await bus.live(LIVE_REGRAS, RegraMudou(id=regra.id, action="desativada"))
        return regra

    async def avaliar_regra(self, data: RegraRef) -> Regra:
        """A regra só entra no agente se, com ela, o agente refaz o caso que a gerou e chega no que o staff fez."""
        row = await db.select(f"{REGRAS}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Regra não encontrada.", 404)
        regra = Regra.model_validate(row)
        if regra.status != "avaliando":
            return regra
        processo = await _processo_por_id(regra.processo)
        versao = await _versao_do_motor(regra.processo, int(row.get("versao") or 0)) or next(
            (v for v in await _versoes(regra.processo) if v["status"] == "publicada"), None)
        step = Fluxo.model_validate(versao["fluxo"]).step(regra.passo) if versao else None
        if step is None or step.tipo != "agente":
            avaliacao = Avaliacao(ok=False, detalhes=["O passo não existe mais ou não é de agente."])
        else:
            ativas = [r for r in await _regras(regra.processo) if r.passo == regra.passo and r.status == "ativa"]
            try:
                saida = await _executar_agente(processo, step, row.get("caso") or {}, [*ativas, regra])
                avaliacao = _comparar(regra.esperado, saida)
            except Handoff as exc:
                avaliacao = Avaliacao(ok=False, detalhes=[f"Com a regra, o agente ainda pediu ajuda: {exc.motivo}"])
        regra = Regra.model_validate(await db.merge(f"{REGRAS}:{regra.id}", {
            "status": "ativa" if avaliacao.ok else "reprovada", "avaliacao": avaliacao.model_dump()}))
        await bus.live(LIVE_REGRAS, RegraMudou(id=regra.id, action="avaliada"))
        if regra.autor:
            texto = "entrou no agente" if avaliacao.ok else "não passou na avaliação: " + "; ".join(avaliacao.detalhes)[:300]
            await notify.user(regra.autor, title=f"Regra de {processo.titulo} {texto.split(':')[0]}", body=f"{regra.texto} — {texto}",
                              link=f"/processos/{processo.id}", send_email=False, key=f"regra-{regra.id}")
        return regra

    # ── Jobs do motor para este serviço (core/processes.py: o BPMN os gera) ──

    async def _job_inicio(self, job: Job) -> None:
        """A execução começou (qualquer gatilho): garante o registro dela (a de agenda só se sabe aqui). A de agenda com
        o processo pausado ou a conta suspensa é cancelada no motor na hora, e fica registrada como não iniciada."""
        if await _execucao_por_instancia(job.instance) is None:
            processo = await _processo_por_id(job.processo)
            gatilho = job.variables.get("gatilho") or {}
            origem = gatilho.get("origem") if gatilho.get("origem") in ("manual", "processo", "agenda") else ("evento" if gatilho else "agenda")
            bloqueio = await _bloqueio(processo) if origem == "agenda" and not gatilho else None
            await _registrar_execucao(processo, job.instance, job.version, origem=origem, resumo=bloqueio, gatilho=gatilho)
            if bloqueio:
                await camunda.cancel(job.instance)
                agora = datetime.now(UTC)
                await _marcar(job.instance, Marco(passo=START, nome="Não iniciou", status="cancelada", em=agora, motivo=bloqueio),
                              aguardando=None, atual=(None, None), final={"status": "cancelada", "concluida_em": agora})
        return None

    async def _job_tarefa(self, job: Job) -> None:
        """Uma tarefa de pessoa foi criada: aprovação do cliente ou exceção do staff, com o contexto para decidir."""
        tarefa_motor = job.user_task or {}
        chave = str(tarefa_motor.get("userTaskKey") or job.headers.get("io.camunda.zeebe:userTaskKey") or "")
        if not chave or await db.query(f"SELECT id FROM {TAREFAS} WHERE tenant = $tenant AND chave = $c LIMIT 1", c=chave):
            return None  # reentrega do mesmo job
        processo = await _processo_por_id(job.processo)
        versao = await _versao_do_motor(job.processo, job.version)
        fluxo = Fluxo.model_validate(versao["fluxo"]) if versao else Fluxo()
        catalogo = await _catalogo()
        execucao = await _execucao_por_instancia(job.instance) or await _registrar_execucao(processo, job.instance, job.version, origem="evento", resumo=None)
        excecao = job.element.endswith("__excecao")
        passo_id = job.element.removesuffix("__excecao")
        step = fluxo.step(passo_id)
        nome = step.nome if step else passo_id
        saidas = {k: v for k, v in job.variables.items() if isinstance(v, dict) and k not in ("parametros", "entrada", "mensagem")}
        motivo = None
        if excecao:
            ultimo = next((m for m in reversed(execucao.marcos) if m.passo == passo_id and m.status == "handoff"), None)
            motivo = ultimo.motivo if ultimo else (f"O prazo de {nome.lower()} passou." if step and step.tipo == "espera" else None)
        dados = {**(saidas.get("gatilho") or {}), **{k: v for s in saidas.values() for k, v in s.items()}}
        if excecao and not saidas.get(passo_id):  # o que o agente leu antes de ir para a exceção
            rows = await db.query(f"SELECT parciais FROM {EXECUCOES} WHERE tenant = $tenant AND instancia = $i LIMIT 1", i=job.instance)
            parcial = ((rows[0].get("parciais") if rows else None) or {}).get(passo_id)
            if parcial:
                saidas[passo_id] = parcial
        tarefa = {
            "chave": chave, "execucao": execucao.id, "instancia": job.instance, "processo": processo.id, "titulo": processo.titulo,
            "passo": passo_id, "nome": f"Exceção: {nome}" if excecao else nome, "tipo": "excecao" if excecao else "aprovacao",
            "responsavel": "staff" if excecao else (step.responsavel if step and step.responsavel else "cliente"),
            "pergunta": (f"Resolva {nome.lower()} e preencha o que o passo devolveria." if excecao else (step.pergunta if step and step.pergunta else nome)),
            "motivo": motivo, "contexto": [i.model_dump() for i in _contexto_tarefa(dados)],
            "campos": [c.model_dump() for c in _campos(step, catalogo, saidas.get(passo_id) or dados)] if excecao and step else [],
            "documento_id": (saidas.get("gatilho") or {}).get("documento_id"), "prazo": _quando(tarefa_motor.get("dueDate")),
            "aprende": bool(excecao and step and step.tipo == "agente"), "status": "aberta", "resposta": {},
            # O caso da exceção (o que o passo tinha à mão): se o staff ensinar uma regra, a avaliação refaz este caso.
            "caso": {k: v for k, v in job.variables.items() if k != "entrada"} if excecao else None,
            "versao": job.version,
        }
        try:
            criada = Tarefa.model_validate(await db.create(TAREFAS, tarefa))
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                return None
            raise
        aguardando = "staff" if tarefa["responsavel"] == "staff" else "cliente"
        await _marcar(job.instance, Marco(passo=passo_id, nome=tarefa["nome"], status="tarefa", em=datetime.now(UTC), motivo=motivo),
                      aguardando=aguardando, atual=(passo_id, tarefa["nome"]))
        await bus.live(LIVE_TAREFAS, TarefaMudou(id=criada.id, action="criada"))
        titulo = f"{processo.titulo}: {tarefa['nome']}"
        if aguardando == "staff":
            await _ao_staff(ItemStaff(tipo="excecao", ref=criada.id, titulo=titulo, detalhe=motivo, prazo=criada.prazo, status="aberta",
                                      link="/processos/tarefas", em=datetime.now(UTC)))
        if aguardando == "cliente":
            await notify.roles("owner", "admin", title=titulo, body=tarefa["pergunta"], link="/processos/tarefas", key=f"tarefa-{chave}")
        else:
            await notify.roles("operador", title=titulo, body=motivo or tarefa["pergunta"], link="/processos/tarefas", key=f"tarefa-{chave}")
        return None

    async def _job_espera(self, job: Job) -> None:
        """A execução entrou numa espera (mensagem do banco, tempo)."""
        nome = await _nome_do_passo(job.processo, job.version, job.element)
        await _marcar(job.instance, Marco(passo=job.element, nome=nome, status="aguardando", em=datetime.now(UTC)),
                      aguardando="evento", atual=(job.element, nome))
        return None

    async def _job_fim(self, job: Job) -> None:
        """A execução chegou a um fim: concluída, com o resultado desse fim. Os processos da empresa que começam quando
        este termina (gatilho por outro processo) são iniciados com as saídas dele: a cadeia vira um projeto."""
        versao = await _versao_do_motor(job.processo, job.version)
        step = Fluxo.model_validate(versao["fluxo"]).step(job.element) if versao else None
        resultado = (step.resultado or step.nome) if step else job.element
        agora = datetime.now(UTC)
        antes = await _execucao_por_instancia(job.instance)
        if antes is None or antes.status != "concluida":  # o ouvinte entregue de novo não repete o marco
            await _marcar(job.instance, Marco(passo=job.element, nome=step.nome if step else job.element, status="fim", em=agora),
                          aguardando=None, atual=(None, None), final={"status": "concluida", "resultado": resultado, "concluida_em": agora})
        execucao = await _execucao_por_instancia(job.instance)
        if execucao is not None:
            await _disparar(execucao, resultado, job.variables)
        return None

    async def _job_agente(self, job: Job) -> dict[str, Any]:
        """Passo de agente: o objetivo do passo, as saídas declaradas, as regras que o staff ensinou e as ferramentas de
        leitura. Sem segurança, o agente pede ajuda e o passo vai para a exceção do staff (Handoff)."""
        versao = await _versao_do_motor(job.processo, job.version)
        step = Fluxo.model_validate(versao["fluxo"]).step(job.element) if versao else None
        if step is None or step.tipo != "agente":
            raise Handoff("Passo de agente não encontrado na versão publicada.")
        processo = await _processo_por_id(job.processo)
        regras = [r for r in await _regras(processo.id) if r.passo == step.id and r.status == "ativa"]
        try:
            return {"resultado": await _executar_agente(processo, step, job.variables, regras)}
        except Handoff as handoff:
            if handoff.parcial:  # a tarefa de exceção (criada pelo motor logo depois) já vem com o que o agente leu
                await db.query(f"UPDATE {EXECUCOES} SET parciais.{step.id} = $parcial WHERE tenant = $tenant AND instancia = $i",
                               parcial=handoff.parcial, i=job.instance)
            raise


# ── Ajudantes ────────────────────────────────────────────────────────────────

async def _executar_agente(processo: Processo, step: Step, variaveis: dict[str, Any], regras: list[Regra]) -> dict[str, Any]:
    """Roda o agente de um passo com os dados da execução e as regras ativas; devolve as saídas ou levanta Handoff. Com
    agente da empresa (step.agente_id), quem roda é o svc-agentes; a conferência do resultado é a mesma."""
    lidos = [json.dumps({k: v for k, v in variaveis.items() if k != "entrada"}, ensure_ascii=False)]  # onde as saídas podem estar
    contexto = "\n".join([
        f"Processo: {processo.titulo}. Passo: {step.nome}.", f"Objetivo: {step.objetivo or step.nome}",
        f"Saídas: {', '.join(f'{c} (ex.: {step.exemplo.get(c)!r})' for c in step.saidas)}",
        "Dados da execução: " + json.dumps({k: v for k, v in variaveis.items() if k != "entrada"}, ensure_ascii=False)[:4000],
    ])
    ensinadas = [f"{r.texto} (no caso que gerou a regra, a saída certa foi: {json.dumps(r.esperado, ensure_ascii=False)})" for r in regras]
    tarefa = f"Execute o passo \"{step.nome}\" e conclua com as saídas."
    obrigatorias, padroes = _contrato(step, await _catalogo())
    if step.agente_id:
        resultado, ajuda = await _agente_da_empresa(step, tarefa, contexto, ensinadas, lidos, obrigatorias)
    else:
        resultado, ajuda = await _agente_da_plataforma(step, tarefa, contexto, ensinadas, lidos)
    if ajuda:
        raise Handoff(ajuda[0])
    if not resultado:
        raise Handoff(f"O agente não concluiu {step.nome.lower()}.")
    fontes = resultado.pop("fontes", None) or {}
    if step.leitura:  # não chuta: cada saída lida aponta o trecho de onde saiu, e o trecho está no que ele leu e diz o mesmo
        sem_fonte = [c for c, v in resultado.items() if v not in (None, "") and not _tem_fonte(v, str(fontes.get(c) or ""), lidos, bool(regras))]
        if sem_fonte:
            parcial = {c: v for c, v in resultado.items() if c not in sem_fonte and v not in (None, "")}
            raise Handoff(f"O agente não mostrou no documento de onde tirou: {', '.join(sem_fonte)}.", parcial=parcial)
    for campo, padrao in padroes.items():  # o que a ação substituída tem por padrão: as condições adiante nunca veem vazio
        if resultado.get(campo) is None:
            resultado[campo] = padrao
    faltam = [c for c in obrigatorias if resultado.get(c) in (None, "")]
    if faltam:
        raise Handoff(f"O agente não encontrou: {', '.join(faltam)}.", parcial={c: v for c, v in resultado.items() if v not in (None, "")})
    return resultado


def _contrato(step: Step, catalogo: dict[str, CatalogAction]) -> tuple[list[str], dict[str, Any]]:
    """O que o passo precisa devolver. No lugar de uma ação (usar_agente), o contrato da ação: as saídas obrigatórias
    dela e os padrões das outras. Senão, as saídas que têm exemplo."""
    acao = catalogo.get(step.acao or "")
    if acao is None:
        return [c for c in step.exemplo if c in step.saidas], {}
    propriedades = acao.output_schema.get("properties", {})
    obrigatorias = [c for c in acao.output_schema.get("required", []) if c in step.saidas]
    return obrigatorias, {c: p["default"] for c, p in propriedades.items() if c in step.saidas and "default" in p}


async def _agente_da_empresa(step: Step, tarefa: str, contexto: str, regras: list[str], lidos: list[str],
                             obrigatorias: list[str]) -> tuple[dict[str, Any], list[str]]:
    """O agente da organização roda no svc-agentes (instrução, ferramentas MCP e política dele); a política que pede
    aprovação vira a exceção do staff, como o pedido de ajuda."""
    pedido = ExecutarAgente(agente=step.agente_id or "", tarefa=tarefa, contexto=contexto, leitura=step.leitura, regras=regras,
                            saidas={c: _tipo_do_valor(step.exemplo.get(c, "")) for c in step.saidas}, obrigatorias=obrigatorias)
    try:
        feito = await bus.request(AGENTES_EXECUTAR_SUBJECT, pedido, ExecucaoDeAgente, timeout=300)
    except (NatsError, TimeoutError):
        raise Handoff(f"O agente da empresa do passo {step.nome} não respondeu agora.") from None
    except ServiceError as exc:
        raise Handoff(f"O agente da empresa do passo {step.nome} não pôde rodar: {exc.message}") from None
    lidos += feito.lidos
    if feito.aprovacao:
        return {}, [f"A política do agente pede aprovação de uma pessoa para usar {feito.aprovacao}."]
    return ({**feito.saidas, "fontes": feito.fontes} if feito.saidas else {}), [feito.ajuda] if feito.ajuda else []


async def _agente_da_plataforma(step: Step, tarefa: str, contexto: str, regras: list[str], lidos: list[str]) -> tuple[dict[str, Any], list[str]]:
    """O agente da Cogniventure: ler o documento do gatilho, consultar o conhecimento, concluir ou pedir ajuda."""
    resultado: dict[str, Any] = {}
    ajuda: list[str] = []
    campos: dict[str, Any] = {campo: (_tipo_do_exemplo(step.exemplo.get(campo)) | None, None) for campo in step.saidas}
    if step.leitura:
        campos["fontes"] = (dict[str, str], Field(default_factory=dict, description=(
            "Para cada saída, o trecho do documento copiado igual, de onde ela saiu (ex.: \"Vencimento: 15/10/2026\"); "
            "para a que veio de uma regra do staff, escreva regra")))
    modelo = create_model(f"saidas_{step.id}", **campos)

    async def ler_documento(dados: LeituraDocumento) -> str:
        """Lê o texto de um documento recebido (o id vem do gatilho: gatilho.documento_id)."""
        try:
            doc = await bus.request(DOCUMENTO_SUBJECT, DocumentoRef(id=dados.documento_id), DocumentoTexto, timeout=10)
        except (NatsError, TimeoutError):
            return "O serviço de documentos não respondeu agora."
        if not doc.texto.strip():
            return f"{doc.nome} ({doc.tipo}) não tem texto legível (foto ou PDF escaneado que o modelo não conseguiu ler)."
        lidos.append(f"{doc.nome} {doc.assunto or ''} {doc.texto}")
        origem = " (foto ou PDF escaneado: o texto abaixo é a leitura do modelo de visão)" if doc.leitura == "modelo" else ""
        return f"{doc.nome}{origem} — assunto: {doc.assunto or '-'}\n\n{doc.texto[:12000]}"

    async def concluir(dados: BaseModel) -> str:
        resultado.clear()
        resultado.update(dados.model_dump(mode="json"))
        return "Passo concluído."

    concluir.__doc__ = f"Conclui o passo com as saídas: {', '.join(step.saidas)}. Valores em reais como número; datas AAAA-MM-DD." + (
        " Em fontes, o trecho do documento de onde saiu cada uma: o que não está escrito no documento não se conclui (peça ajuda)."
        if step.leitura else "")
    concluir.__signature__ = inspect.Signature([inspect.Parameter("dados", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=modelo)])

    async def pedir_ajuda(dados: SaidaAgente) -> str:
        """Não dá para concluir com segurança: o passo vai para uma pessoa do staff, com o motivo."""
        ajuda.append(dados.motivo)
        return "Pedido de ajuda registrado."

    if regras:
        contexto += "\n\nRegras que o staff da Cogniventure ensinou para este passo (siga-as):\n" + "\n".join(f"- {r}" for r in regras)
    await llm.run_agent(settings.model, tarefa, instructions=EXECUCAO_INSTRUCOES,
                        tools=[ler_documento, _buscar_conhecimento, concluir, pedir_ajuda], context=contexto, max_turns=6)
    return resultado, ajuda


def _tem_fonte(valor: Any, trecho: str, lidos: list[str], tem_regra: bool) -> bool:
    """A saída se sustenta: veio de uma regra do staff, ou o trecho citado está no que o agente leu e traz o valor."""
    if trecho.strip().lower() == "regra":
        return tem_regra
    alvo = _normal(trecho)
    if len(alvo) < 3 or not any(alvo in _normal(texto) for texto in lidos):
        return False
    if isinstance(valor, bool):
        return True
    if isinstance(valor, int | float):
        return any(abs(n - float(valor)) < 0.01 for n in _numeros(trecho))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(valor)):
        return str(valor) in _datas(trecho)
    return _normal(valor) in alvo


def _numeros(texto: str) -> set[float]:
    """Números escritos no trecho, em pt-BR (1.850,00) ou não (1850.5)."""
    achados: set[float] = set()
    for bruto in re.findall(r"\d[\d.,]*\d|\d", texto):
        for candidato in (bruto.replace(".", "").replace(",", "."), bruto.replace(",", "")):
            try:
                achados.add(float(candidato))
            except ValueError:
                pass
    return achados


def _datas(texto: str) -> set[str]:
    """Datas escritas no trecho (15/10/2026, 15-10-26, 2026-10-15), como AAAA-MM-DD."""
    datas = {f"{a}-{m}-{d}" for a, m, d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", texto)}
    for d, m, a in re.findall(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?!\d)", texto):
        datas.add(f"{a if len(a) == 4 else '20' + a}-{int(m):02d}-{int(d):02d}")
    return datas


async def _publicar(processo: Processo, rascunho: dict[str, Any]) -> Desenho:
    """Implanta a versão no Camunda (a versão seguinte do processo no motor), arquiva a anterior e fecha o que o staff
    tinha aberto para este desenho (revisão, ajuda)."""
    fluxo = Fluxo.model_validate(rascunho["fluxo"])
    catalogo = await _catalogo()
    erros = [p for p in [*_problemas(fluxo, catalogo, await _agentes(obrigatorio=any(s.agente_id for s in fluxo.passos))),
                         *await _problemas_da_cadeia(fluxo, processo, await _todos())] if p.nivel == "erro"]
    if erros:
        raise ServiceError("ERRO_PROCESSOS_FLUXO_INVALIDO", "O fluxo tem problemas: " + "; ".join(e.texto for e in erros[:3]), 409)
    motor_id = _motor_id(processo.id)
    xml = to_bpmn(fluxo, process_id=motor_id, name=processo.titulo, actions=catalogo)
    digest = hashlib.sha256(xml.encode()).hexdigest()[:24]
    publicada = next((v for v in await _versoes(processo.id) if v["status"] == "publicada"), None)
    if publicada is not None:
        hash_publicado = (publicada.get("motor") or {}).get("hash")
        # O mesmo BPMN de novo daria a mesma versão no motor. Mudou só o compilador (ou o catálogo)? Aí publica.
        if hash_publicado == digest or (hash_publicado is None and Fluxo.model_validate(publicada["fluxo"]) == fluxo):
            raise ServiceError("ERRO_PROCESSOS_SEM_MUDANCA", "O rascunho está igual à versão publicada: mude o fluxo ou descarte o rascunho.", 409)
    if processo.publicada is None:
        ativos = await db.query(f"SELECT count() AS total FROM (SELECT id FROM {PROCESSOS} WHERE tenant = $tenant "
                                "AND publicada != NONE AND publicada != NULL) GROUP ALL")
        await plans.check("ativos", used=ativos[0]["total"] if ativos else 0)
    implantado = await camunda.deploy(xml, motor_id)
    for versao in await _versoes(processo.id):
        if versao["status"] == "publicada":
            await db.merge(_ref(VERSOES, versao), {"status": "arquivada"})
    await db.merge(_ref(VERSOES, rascunho), {
        "status": "publicada", "publicada_em": datetime.now(UTC), "anteriores": [],
        "motor": Motor(processo=motor_id, chave=implantado.key, versao=implantado.version, hash=digest).model_dump()})
    await db.merge(f"{PROCESSOS}:{processo.id}", {"publicada": int(rascunho["numero"])})
    await plans.count("ativos", await _publicados())
    if rascunho["status"] == "revisao":
        await _ao_staff(ItemStaff(tipo="revisao", ref=processo.id, titulo=f"{processo.titulo}: revisão da versão {rascunho['numero']}",
                                  status="concluida", link=f"/processos/{processo.id}", em=datetime.now(UTC)))
    await _fechar_ajuda(processo)
    await bus.live(LIVE_DESENHO, DesenhoMudou(processo=processo.id, action="publicado"))
    return await _desenho(processo.id)


def _desenhista() -> Any:
    """Quem desenha: dono e admin da empresa, e o staff da Cogniventure (operador) no setup."""
    who = current()
    if who is None or not (who.is_system or DESIGNERS & who.roles):
        raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só donos, administradores e o staff mexem no desenho.", 403)
    return who


def _da_fila() -> None:
    who = current()
    if who is None or who.sub != f"{SYSTEM_PREFIX}{STAFF_SERVICE}" or not who.tenant:
        raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só o serviço do staff faz isso.", 403)


def _como_operador(pessoa: str) -> Principal:
    """A pessoa do staff na organização do cliente (o svc-staff conferiu a carteira, que dá o papel operador)."""
    return Principal(sub=pessoa, tenant=current_tenant(), roles=frozenset({"operador"}))


def _e_staff(who: Principal) -> bool:
    """Quem faz o papel do staff: o operador que a carteira põe no cliente; na organização da própria Cogniventure
    (o faturamento dos clientes roda lá), o dono e o admin dela, que ninguém põe numa carteira."""
    platform = settings.platform_tenant
    return bool(who.is_system or OPERADORES & who.roles or (platform and who.tenant == platform and WRITERS & who.roles))


def _operador() -> Any:
    who = current()
    if who is None or not _e_staff(who):
        raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só o staff da Cogniventure faz isso.", 403)
    return who


def _papel(who: Any) -> str:
    return "staff" if OPERADORES & who.roles and not WRITERS & who.roles else "cliente"


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
    """Id do processo no motor: a organização entra no nome (core/processes.py: o worker tira dele quem age)."""
    return process_id(current_tenant(), processo_id)


async def _processo_por_id(processo_id: str) -> Processo:
    row = await db.select(f"{PROCESSOS}:{processo_id}")
    if row is None:
        raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Processo não encontrado.", status=404)
    return _processo(row)


async def _versoes(processo_id: str) -> list[dict[str, Any]]:
    return await db.query(f"SELECT * FROM {VERSOES} WHERE tenant = $tenant AND processo = $p ORDER BY numero", p=processo_id)


async def _rascunho(processo_id: str) -> dict[str, Any]:
    versoes = await _versoes(processo_id)
    rascunho = next((v for v in versoes if v["status"] == "rascunho"), None)
    if rascunho is None and any(v["status"] == "revisao" for v in versoes):
        raise ServiceError("ERRO_PROCESSOS_EM_REVISAO", "A versão está em revisão pelo staff: espere a publicação ou a devolução.", 409)
    if rascunho is None:
        raise ServiceError("ERRO_PROCESSOS_SEM_RASCUNHO", "Não há rascunho aberto: clique em Ajustar para abrir um.", 409)
    return rascunho


async def _em_revisao(processo_id: str) -> dict[str, Any]:
    revisao = next((v for v in await _versoes(processo_id) if v["status"] == "revisao"), None)
    if revisao is None:
        raise ServiceError("ERRO_PROCESSOS_SEM_REVISAO", "Não há versão em revisão.", 409)
    return revisao


async def _precisa_revisao(processo_id: str, versao: dict[str, Any]) -> bool:
    publicada = next((v for v in await _versoes(processo_id) if v["status"] == "publicada"), None)
    return _exige_revisao(Fluxo.model_validate(versao["fluxo"]), await _catalogo(),
                          Fluxo.model_validate(publicada["fluxo"]) if publicada else None)


async def _regras(processo_id: str | None) -> list[Regra]:
    if processo_id:
        rows = await db.query(f"SELECT * FROM {REGRAS} WHERE tenant = $tenant AND processo = $p ORDER BY created_at", p=processo_id)
    else:
        rows = await db.query(f"SELECT * FROM {REGRAS} WHERE tenant = $tenant ORDER BY created_at")
    return [Regra.model_validate(r) for r in rows]


async def _nova_regra(tarefa: Tarefa, row: dict[str, Any], texto: str, resposta: dict[str, Any], autor: str | None) -> None:
    """O staff resolveu a exceção de um agente e ensinou o que fazer: a regra nasce em avaliação (workflow)."""
    processo = await _processo_por_id(tarefa.processo)
    versao = await _versao_do_motor(tarefa.processo, int(row.get("versao") or 0))
    step = Fluxo.model_validate(versao["fluxo"]).step(tarefa.passo) if versao else None
    if step is None or step.tipo != "agente":
        raise ServiceError("ERRO_PROCESSOS_REGRA", "Só a exceção de um passo de agente vira regra.", 422)
    esperado = {k: v for k, v in resposta.items() if k in step.saidas and v not in (None, "")}
    criada = await db.create(REGRAS, {"processo": processo.id, "passo": step.id, "passo_nome": step.nome, "texto": texto,
                                      "esperado": esperado, "caso": row.get("caso") or {}, "versao": row.get("versao"),
                                      "status": "avaliando", "avaliacao": None, "autor": autor, "tarefa": tarefa.id})
    regra = Regra.model_validate(criada)
    await bus.live(LIVE_REGRAS, RegraMudou(id=regra.id, action="criada"))
    await runner.start_workflow(_workflow_regra(), RegraRef(id=regra.id), task_queue=TASK_QUEUE, id=f"regra-{current_tenant()}-{regra.id}")


def _workflow_regra() -> Any:
    from workflows import AvaliarRegraWorkflow  # o workflow importa este arquivo: a referência é resolvida na hora

    return AvaliarRegraWorkflow.run


def _normal(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", texto)


def _comparar(esperado: dict[str, Any], saida: dict[str, Any]) -> Avaliacao:
    """O agente chegou no que o staff fez? Número igual (centavos), texto igual sem acento e pontuação (ou um contém o outro)."""
    detalhes = []
    for campo, certo in esperado.items():
        obtido = saida.get(campo)
        if isinstance(certo, (int, float)) and not isinstance(certo, bool):
            try:
                igual = obtido is not None and abs(float(obtido) - float(certo)) < 0.01
            except (TypeError, ValueError):
                igual = False
        else:
            a, b = _normal(certo), _normal(obtido if obtido is not None else "")
            igual = bool(b) and (a == b or a in b or b in a)
        if not igual:
            detalhes.append(f"{campo}: esperado {certo!r}, o agente deu {obtido!r}")
    return Avaliacao(ok=not detalhes, detalhes=detalhes)


async def _ao_staff(item: ItemStaff) -> None:
    """Publica para a fila da carteira (svc-staff) como a plataforma: o módulo do staff não é da organização. O item
    concluído leva quem resolveu (os números do gestor)."""
    who = current()
    if item.status == "concluida" and item.por is None and who is not None and not who.is_system:
        item = item.model_copy(update={"por": who.sub})
    with acting_as(system(SERVICE, current_tenant())):
        await bus.publish(STAFF_SUBJECT, item, msg_id=f"staff-{current_tenant()}-{item.tipo}-{item.ref}-{item.status}-{int(item.em.timestamp())}")


async def _fechar_ajuda(processo: Processo) -> None:
    row = await db.select(f"{PROCESSOS}:{processo.id}")
    if row and row.get("ajuda"):
        await db.merge(f"{PROCESSOS}:{processo.id}", {"ajuda": None})
        await _ao_staff(ItemStaff(tipo="ajuda", ref=processo.id, titulo=f"{processo.titulo}: ajuda no desenho", status="concluida",
                                  link=f"/processos/{processo.id}", em=datetime.now(UTC)))


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
    publicada = next((Fluxo.model_validate(v["fluxo"]) for v in versoes if v["status"] == "publicada"), None)
    outros = [p for p in await _todos() if p.id != processo.id and p.status == "aceito"]
    return Desenho(
        processo=processo,
        versao=versao,
        versoes=[VersaoResumo(numero=v["numero"], status=v["status"], publicada_em=v.get("publicada_em"),
                              motor_versao=(v.get("motor") or {}).get("versao")) for v in versoes],
        bpmn=to_bpmn(fluxo, process_id=_motor_id(processo_id), name=processo.titulo, actions=catalogo),
        problemas=[*_problemas(fluxo, catalogo, await _agentes()), *await _problemas_da_cadeia(fluxo, processo, outros)],
        mensagens=[MensagemDesenho(id=_short(m["id"]), papel=m["papel"], autor=m.get("autor"), texto=m["texto"],
                                   passos=m.get("passos") or [], created_at=m.get("created_at")) for m in await _mensagens(processo_id)],
        exige_revisao=aberta["status"] != "publicada" and _exige_revisao(fluxo, catalogo, publicada),
        mudancas=_mudancas(publicada or await _partida(processo), fluxo) if aberta["status"] != "publicada" else [],
        regras=await _regras(processo_id),
        inicia=await _seguintes(processo, outros),
    )


async def _agentes(*, obrigatorio: bool = False) -> dict[str, AgenteDaEmpresa] | None:
    """Os agentes da organização (svc-agentes). Fora do ar: None (o desenho segue sem conferir); para publicar um passo
    com agente da empresa, é obrigatório conferir."""
    try:
        return {a.id: a for a in (await bus.request(AGENTES_LISTA_SUBJECT, Empty(), AgentesDaEmpresa, timeout=5)).itens}
    except (NatsError, TimeoutError, ServiceError):
        if obrigatorio:
            raise ServiceError("ERRO_PROCESSOS_AGENTES", "O serviço de agentes não respondeu: tente publicar de novo em instantes.", 503) from None
        return None


async def _partida(processo: Processo) -> Fluxo:
    """O fluxo de partida: o do modelo da biblioteca, como o pacote da área declarou (processos_modelos); sem ele (o
    pacote não subiu, ou o processo é só da empresa), um agente faz o processo."""
    if processo.modelo:
        rows = await db.query_shared(f"SELECT * FROM {MODELOS} WHERE modelo = $modelo LIMIT 1", modelo=processo.modelo)
        if rows:
            return ModeloDeclarado.model_validate(rows[0]).fluxo
    modelo = next((m for m in BIBLIOTECA if m.id == processo.modelo), None)
    gatilho = Trigger(tipo="manual", descricao=(modelo.gatilho if modelo else "Pedido do cliente")[:200])
    if modelo and modelo.gatilho.lower().startswith("todo dia"):
        gatilho = Trigger(tipo="agenda", agenda="0 11 * * *", descricao=modelo.gatilho)  # 8h em Brasília
    elif modelo and (modelo.gatilho.lower().startswith("todo mês") or modelo.gatilho.lower() == "dia 1"):
        gatilho = Trigger(tipo="agenda", agenda="0 11 1 * *", descricao=modelo.gatilho)
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


def _problemas(fluxo: Fluxo, catalogo: dict[str, CatalogAction], agentes: dict[str, AgenteDaEmpresa] | None = None) -> list[Problema]:
    """O que impede publicar (erro) e o que merece atenção (aviso). agentes: os da organização (svc-agentes), quando
    quem chama os tem à mão (desenho, publicação); sem eles, o agente da empresa de um passo não é conferido."""
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
    elif t.tipo == "agenda" and len(t.agenda.split()) != 5:
        erro("A agenda é um cron de 5 campos em UTC: minuto hora dia mês dia-da-semana (ex.: 0 11 * * * = 8h em Brasília).")
    if t.tipo == "processo" and not t.processo:
        erro("Gatilho por outro processo sem dizer qual (o modelo da biblioteca ou o id do processo).")
    for f in fluxo.ligacoes:
        if f.para not in ids or (f.de != START and f.de not in ids):
            erro(f"Ligação {f.de} → {f.para} aponta para passo que não existe.", f.de)
    if not any(s.tipo == "fim" for s in fluxo.passos):
        erro("O fluxo precisa de pelo menos um fim.")
    juncoes = _juncoes(fluxo)
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
        if s.tipo == "paralelo":
            entrando = [f for f in fluxo.ligacoes if f.para == s.id]
            if any(f.condicao for f in saindo):
                erro(f"{s.nome} é paralelo: os caminhos dele não têm condição (condições só saem de decisões).", s.id)
            if len(saindo) > 1 and len(entrando) > 1:
                erro(f"{s.nome} abre e junta ramos ao mesmo tempo: use um paralelo para abrir e outro para juntar.", s.id)
            elif len(saindo) > 1:
                juncao = juncoes.get(s.id)
                if juncao is None:
                    erro(f"Os ramos de {s.nome} não se juntam num mesmo paralelo (cada ramo precisa chegar nele, sem passar por um fim).", s.id)
                else:
                    chegando = sum(1 for f in fluxo.ligacoes if f.para == juncao)
                    if chegando != len(saindo):
                        erro(f"{fluxo.step(juncao).nome} espera {chegando} caminhos, mas {s.nome} abre {len(saindo)}: a execução pararia ali.", s.id)
            elif len(entrando) <= 1:
                aviso(f"{s.nome} é paralelo mas não abre nem junta ramos.", s.id)
        elif s.tipo == "decisao":
            padroes = [f for f in saindo if f.condicao is None]
            if len(saindo) < 2:
                erro(f"A decisão {s.nome} precisa de pelo menos dois caminhos.", s.id)
            if len(padroes) != 1:
                erro(f"A decisão {s.nome} precisa de exatamente um caminho padrão (sem condição).", s.id)
            condicoes = [_condicao(f) for f in saindo if f.condicao is not None]
            for repetida in sorted({c for c in condicoes if condicoes.count(c) > 1}):  # o motor seguiria só o primeiro
                erro(f"A decisão {s.nome} tem dois caminhos com a mesma condição ({repetida.removeprefix(' se ')}).", s.id)
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
            if s.agente_id and agentes is not None:
                agente = agentes.get(s.agente_id)
                if agente is None:
                    erro(f"O agente da empresa do passo {s.nome} não existe mais.", s.id)
                elif agente.status == "rascunho":
                    erro(f"O agente {agente.nome} (passo {s.nome}) ainda não passou na suíte de avaliação.", s.id)
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
        for alt in f.condicao.alternatives():  # o motor recusa comparar tipos diferentes: viraria incidente na execução
            tipo = _tipo_do_campo(fluxo, catalogo, alt.campo)
            if alt.operador in ("verdadeiro", "falso") and tipo not in (None, "sim_nao"):
                erro(f"A condição de {f.de} → {f.para} pergunta se {alt.campo} é {alt.operador}, mas ele é {tipo}, não sim/não.", f.de)
            elif alt.operador in (">", ">=", "<", "<=") and tipo not in (None, "numero"):
                erro(f"A condição de {f.de} → {f.para} compara {alt.campo} com {alt.operador}, mas ele é {tipo}, não número.", f.de)
            elif alt.operador not in ("verdadeiro", "falso") and alt.valor is not None:
                referencia = isinstance(alt.valor, str) and alt.valor.startswith("parametros.")
                outro = _tipo_do_campo(fluxo, catalogo, alt.valor) if referencia else _tipo_do_valor(alt.valor)
                if tipo and outro and tipo != outro:
                    erro(f"A condição de {f.de} → {f.para} compara {alt.campo} ({tipo}) com {alt.valor!r} ({outro}).", f.de)
    return out


def _juncoes(fluxo: Fluxo) -> dict[str, str]:
    """Para cada paralelo que abre ramos, o paralelo onde todos eles se juntam: o primeiro que cada ramo alcança sem
    passar por um fim (um paralelo aninhado num ramo é atravessado até a junção dele). Sem um comum, fica de fora."""
    entram: dict[str, int] = {}
    for f in fluxo.ligacoes:
        entram[f.para] = entram.get(f.para, 0) + 1
    memo: dict[str, str | None] = {}

    def juncao(abre: str, pilha: frozenset[str]) -> str | None:
        if abre in memo or abre in pilha:
            return memo.get(abre)
        comuns: list[str] | None = None
        for f in fluxo.outgoing(abre):
            achadas = ramo(f.para, pilha | {abre})
            comuns = achadas if comuns is None else [j for j in comuns if j in achadas]
        memo[abre] = comuns[0] if comuns else None
        return memo[abre]

    def ramo(inicio: str, pilha: frozenset[str]) -> list[str]:
        achadas, vistos, fila = [], set(), [inicio]
        while fila:
            no = fila.pop(0)
            step = fluxo.step(no)
            if no in vistos or step is None:
                continue
            vistos.add(no)
            if step.tipo == "fim":
                return []  # um ramo que termina antes de se juntar: a junção esperaria para sempre
            if step.tipo == "paralelo" and entram.get(no, 0) > 1:
                achadas.append(no)
                continue
            if step.tipo == "paralelo" and len(fluxo.outgoing(no)) > 1:
                interna = juncao(no, pilha)
                fila += [g.para for g in fluxo.outgoing(interna)] if interna else []
                continue
            fila += [g.para for g in fluxo.outgoing(no)]
        return achadas

    return {s.id: j for s in fluxo.passos if s.tipo == "paralelo" and len(fluxo.outgoing(s.id)) > 1 and (j := juncao(s.id, frozenset()))}


async def _fluxo_vigente(processo: Processo) -> Fluxo:
    """O fluxo que vale para a cadeia: o publicado; sem ele, o rascunho (ou o fluxo de partida, antes de desenhar)."""
    versoes = await _versoes(processo.id)
    for status in ("publicada", "revisao", "rascunho"):
        if found := next((v for v in versoes if v["status"] == status), None):
            return Fluxo.model_validate(found["fluxo"])
    return await _partida(processo)


def _fins(fluxo: Fluxo) -> list[str]:
    return [s.resultado or s.nome for s in fluxo.passos if s.tipo == "fim"]


async def _problemas_da_cadeia(fluxo: Fluxo, processo: Processo, processos: list[Processo]) -> list[Problema]:
    """O gatilho por outro processo aponta para um processo da empresa que existe, não é ele mesmo e termina com o
    resultado pedido (senão este nunca começa)."""
    t = fluxo.gatilho
    if t.tipo != "processo" or not t.processo:
        return []
    if t.processo in (processo.id, processo.modelo):
        return [Problema(nivel="erro", texto="O processo não pode começar quando ele mesmo termina.")]
    origem = next((p for p in processos if p.id != processo.id and t.processo in (p.id, p.modelo) and p.status == "aceito"), None)
    nome = origem.titulo if origem else (_MODELOS[t.processo].titulo if t.processo in _MODELOS else t.processo)
    if origem is None:
        return [Problema(nivel="aviso", texto=f"{nome} não está entre os processos aceitos da empresa: este só começa quando ele terminar.")]
    out = []
    if origem.publicada is None:
        out.append(Problema(nivel="aviso", texto=f"{nome} ainda não está publicado: este processo só começa quando ele terminar."))
    fins = _fins(await _fluxo_vigente(origem))
    if t.resultado and _normal(t.resultado) not in {_normal(f) for f in fins}:
        out.append(Problema(nivel="aviso", texto=f"{nome} nunca termina como {t.resultado} (os fins dele: {', '.join(fins) or 'nenhum'})."))
    return out


async def _seguintes(processo: Processo, processos: list[Processo]) -> list[ProcessoLigado]:
    """Os processos aceitos da empresa que começam quando este termina: a cadeia que o desenho mostra."""
    out = []
    for outro in processos:
        if outro.id == processo.id or outro.status != "aceito":
            continue
        gatilho = (await _fluxo_vigente(outro)).gatilho
        if gatilho.tipo == "processo" and gatilho.processo in (processo.id, processo.modelo):
            out.append(ProcessoLigado(id=outro.id, titulo=outro.titulo, resultado=gatilho.resultado, publicada=outro.publicada))
    return out


def _tipo_do_valor(valor: Any) -> str:
    return "sim_nao" if isinstance(valor, bool) else "numero" if isinstance(valor, int | float) else "texto"


def _tipo_do_campo(fluxo: Fluxo, catalogo: dict[str, CatalogAction], campo: str) -> str | None:
    """numero, texto ou sim_nao; None quando não dá para saber (o campo não existe ou o agente não deu exemplo)."""
    passo, _, nome = campo.partition(".")
    if passo == "parametros":
        exemplo: Any = fluxo.parametros.get(nome)
    else:
        step = fluxo.step(passo)
        if step is None:
            return None
        if step.tipo == "tarefa":
            exemplo = {"aprovado": True, "comentario": ""}.get(nome)
        elif step.tipo == "acao" and step.acao in catalogo:
            propriedades = catalogo[step.acao].output_schema.get("properties", {})
            exemplo = ({"number": 0.0, "integer": 0.0, "boolean": False}.get(_tipo_json(propriedades[nome]), "") if nome in propriedades
                       else catalogo[step.acao].example.get(nome))
        else:
            exemplo = step.exemplo.get(nome)
    return None if exemplo is None else _tipo_do_valor(exemplo)


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


def _sensiveis(fluxo: Fluxo, catalogo: dict[str, CatalogAction]) -> set[str]:
    """O que pede revisão: ações irreversíveis ou com conexão a sistemas de fora, e agentes da empresa (ferramentas de
    sistemas do cliente, servidores MCP) entrando num passo."""
    acoes = {s.acao for s in fluxo.passos if s.tipo == "acao" and (a := catalogo.get(s.acao or "")) and (a.risk == "irreversivel" or a.connections)}
    return {*(a for a in acoes if a), *(f"agente:{s.agente_id}" for s in fluxo.passos if s.tipo == "agente" and s.agente_id)}


def _exige_revisao(fluxo: Fluxo, catalogo: dict[str, CatalogAction], publicada: Fluxo | None = None) -> bool:
    """Revisão do staff obrigatória (briefing.md §5.5): ação irreversível ou conexão que a publicada não tinha."""
    return bool(_sensiveis(fluxo, catalogo) - (_sensiveis(publicada, catalogo) if publicada else set()))


def _resumo_fluxo(fluxo: Fluxo) -> str:
    t = fluxo.gatilho
    origem = t.evento or t.agenda or (f"{t.processo} termina{' como ' + t.resultado if t.resultado else ''}" if t.processo else None)
    linhas = [f"Gatilho: {t.tipo}" + (f" ({origem})" if origem else "") + (f" — {t.descricao}" if t.descricao else "")]
    if fluxo.parametros:
        linhas.append("Parâmetros: " + ", ".join(f"{k} = {v}" for k, v in fluxo.parametros.items()))
    linhas.append("Passos:")
    for s in fluxo.passos:
        extra = {"acao": s.acao, "agente": f"objetivo: {s.objetivo}; saidas: {', '.join(s.saidas)}" + (f"; agente da empresa: {s.agente_id}" if s.agente_id else ""),
                 "tarefa": f"{s.responsavel}: {s.pergunta}",
                 "espera": f"{s.espera} {s.mensagem or ''} {s.chave or ''} {s.horas or ''}".strip(), "fim": s.resultado}.get(s.tipo)
        linhas.append(f"- {s.id} [{s.tipo}] {s.nome}" + (f" ({extra})" if extra else "") + (" [exceção]" if s.excecao else ""))
    linhas.append("Ligações:")
    for f in fluxo.ligacoes:
        linhas.append(f"- {f.de} → {f.para}{_condicao(f)}")
    return "\n".join(linhas)


def _condicao(f: Flow) -> str:
    """" se ler_documento.valor > parametros.limite" (vazio sem condição)."""
    return (" se " + " ou ".join(f"{a.campo} {a.operador} {a.valor if a.valor is not None else ''}".rstrip()
                                 for a in f.condicao.alternatives())) if f.condicao else ""


def _mudancas(antes: Fluxo, depois: Fluxo) -> list[str]:
    """O que mudou entre dois fluxos, em frases curtas: o que o staff confere na revisão e o cliente antes de pedi-la."""
    out: list[str] = []
    if antes.gatilho != depois.gatilho:
        out.append(f"Gatilho: {depois.gatilho.descricao or depois.gatilho.tipo}")
    for nome in sorted(antes.parametros.keys() | depois.parametros.keys()):
        de, para = antes.parametros.get(nome), depois.parametros.get(nome)
        if de != para:
            mostra = lambda v: int(v) if isinstance(v, float) and v.is_integer() else v  # noqa: E731 - 5000.0 → 5000
            out.append(f"Parâmetro {nome.replace('_', ' ')}: {'—' if de is None else mostra(de)} → {'removido' if para is None else mostra(para)}")
    passos_antes = {p.id: p for p in antes.passos}
    passos_depois = {p.id: p for p in depois.passos}
    out += [f"Passo novo: {p.nome}" for i, p in passos_depois.items() if i not in passos_antes]
    out += [f"Passo removido: {p.nome}" for i, p in passos_antes.items() if i not in passos_depois]
    out += [f"Passo alterado: {p.nome}" for i, p in passos_depois.items() if i in passos_antes and passos_antes[i] != p]
    ligacoes_antes = {(f.de, f.para, _condicao(f)) for f in antes.ligacoes}
    ligacoes_depois = {(f.de, f.para, _condicao(f)) for f in depois.ligacoes}
    nome = lambda i: passos_depois.get(i, passos_antes.get(i)).nome if i in passos_depois or i in passos_antes else "início"  # noqa: E731
    out += [f"Caminho novo: {nome(de)} → {nome(para)}{cond}" for de, para, cond in sorted(ligacoes_depois - ligacoes_antes)]
    out += [f"Caminho removido: {nome(de)} → {nome(para)}{cond}" for de, para, cond in sorted(ligacoes_antes - ligacoes_depois)]
    return out


def _contexto_desenho(processo: Processo, fluxo: Fluxo, catalogo: dict[str, CatalogAction], empresa: ContextoEmpresa | None,
                      historico: list[dict[str, Any]], agentes: dict[str, AgenteDaEmpresa] | None = None) -> str:
    linhas = [f"Processo: {processo.titulo} ({processo.area}). {processo.descricao}"]
    if processo.motivo:
        linhas.append(f"Por que foi sugerido: {processo.motivo}")
    if empresa:
        linhas.append("Perfil da empresa: " + "; ".join(f"{k}: {v}" for k, v in empresa.perfil.items() if v not in (None, "")))
    linhas += ["", "Catálogo de ações (nome — o que faz; risco; saídas; conexões):"]
    linhas += [f"- {a.name} — {a.title}: {a.description}; {a.risk}; saídas: {', '.join(a.output_fields)}"
               + (f"; conexões: {', '.join(a.connections)}" if a.connections else "") for a in catalogo.values()] or ["- (vazio)"]
    if agentes:
        linhas += ["", "Agentes da empresa (usar_agente com o id; só verificado ou confiável entra num processo):"]
        linhas += [f"- {a.id} — {a.nome}: {a.descricao or 'sem descrição'}; {a.status}" for a in agentes.values()]
    linhas += ["", "Fluxo atual:", _resumo_fluxo(fluxo), "", "Problemas agora:"]
    linhas += [f"- {p.nivel}: {p.texto}" for p in _problemas(fluxo, catalogo, agentes)] or ["- nenhum"]
    quem = {"cliente": "Cliente", "staff": "Staff da Cogniventure", "agente": "Agente"}
    linhas += ["", "Conversa até aqui:"] + [f"{quem.get(m['papel'], 'Agente')}: {m['texto']}" for m in historico]
    return "\n".join(linhas)


def _ferramentas(processo_id: str, catalogo: dict[str, CatalogAction], agentes: dict[str, AgenteDaEmpresa] | None = None) -> list[Any]:
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
        problemas = _problemas(fluxo, catalogo, agentes)
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
                if anterior is not None and anterior.tipo == "paralelo" and len(fluxo.outgoing(anterior.id)) > 1:
                    raise ValueError("depois de um paralelo que abre ramos, use ligar para pôr o passo num ramo")
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
                outro = next((f.para for f in fluxo.outgoing(dados.de) if f.para != dados.para), None)
                if outro and not (origem is not None and origem.tipo == "paralelo"):
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

    async def usar_agente(dados: UsoDeAgente) -> str:
        """Põe um agente da empresa (verificado ou confiável) para fazer um passo de ação ou de agente, com as mesmas
        saídas; sem agente, o passo volta ao agente da Cogniventure."""
        def mudar(fluxo: Fluxo) -> str:
            step = fluxo.step(dados.passo)
            if step is None or step.tipo not in ("acao", "agente"):
                raise ValueError(f"o passo {dados.passo} precisa existir e ser de ação ou de agente")
            if dados.agente is None:
                if step.tipo != "agente":
                    raise ValueError("só um passo de agente deixa de usar o agente da empresa")
                if step.acao in catalogo:  # era uma ação: volta a ser a ação do pacote
                    fluxo.passos[fluxo.passos.index(step)] = Step(id=step.id, tipo="acao", nome=step.nome, acao=step.acao, excecao=step.excecao)
                    return f"Passo {step.nome} volta a ser a ação {step.acao}"
                fluxo.passos[fluxo.passos.index(step)] = step.model_copy(update={"agente_id": None})
                return f"Passo {step.nome} volta ao agente da Cogniventure"
            agente = (agentes or {}).get(dados.agente)
            if agente is None:
                raise ValueError(f"não há agente da empresa com id {dados.agente}")
            if agente.status == "rascunho":
                raise ValueError(f"o agente {agente.nome} ainda não passou na suíte (está em rascunho)")
            if step.tipo == "acao":  # vira passo de agente com as mesmas saídas: as condições adiante continuam valendo
                acao = catalogo.get(step.acao or "")
                saidas = list(acao.output_fields) if acao else []
                exemplo = {k: v for k, v in (acao.example if acao else {}).items() if isinstance(v, str | int | float | bool)}
                novo = Step(id=step.id, tipo="agente", nome=step.nome, objetivo=(acao.description if acao else step.nome)[:600],
                            acao=step.acao, saidas=saidas, exemplo=exemplo, excecao=True, agente_id=agente.id)  # acao: o contrato que ele cumpre
            else:
                novo = step.model_copy(update={"agente_id": agente.id, "excecao": True})
            fluxo.passos[fluxo.passos.index(step)] = novo
            return f"Passo {step.nome} agora é feito pelo agente {agente.nome}"
        return await aplicar(mudar)

    return [adicionar_passo, alterar_passo, remover_passo, ligar, desligar, definir_gatilho, definir_parametro, simular, usar_agente]


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
    """Percorre o fluxo como o motor faria, com as saídas de exemplo; devolve o caminho para pintar no diagrama. Um
    paralelo percorre os ramos um depois do outro até a junção e segue dali."""
    variaveis: dict[str, Any] = {"parametros": dict(fluxo.parametros)}
    caminho: list[str] = [START]
    passos: list[PassoSimulado] = []
    problemas = [p.texto for p in _problemas(fluxo, catalogo) if p.nivel == "erro"]
    juncoes = _juncoes(fluxo)
    voltas = [0]
    sobrepor = lambda passo, saida: {**saida, **{k.partition(".")[2]: v for k, v in cenario.valores.items() if k.partition(".")[0] == passo}}  # noqa: E731

    def andar(proximo: str | None, parar: str | None = None) -> tuple[str, str | None]:
        """Anda até parar (a junção de um paralelo) ou até um fim: ("parou" | "fim" | "erro", resultado ou problema)."""
        while True:
            voltas[0] += 1
            if voltas[0] > 200:
                return "erro", "O fluxo voltou muitas vezes (laço sem saída)."
            if parar is not None and proximo == parar:
                return "parou", None
            step = fluxo.step(proximo) if proximo else None
            if step is None:
                return "erro", "O caminho parou num passo que não existe."
            caminho.append(step.id)
            saindo = fluxo.outgoing(step.id)
            nota, seguinte = "", next((f.para for f in saindo), None)
            if step.tipo == "paralelo" and len(saindo) > 1:
                passos.append(PassoSimulado(id=step.id, nome=step.nome, tipo=step.tipo, nota=f"abriu {len(saindo)} ramos ao mesmo tempo"))
                juncao = juncoes.get(step.id)
                if juncao is None:
                    return "erro", f"Os ramos de {step.nome} não se juntam."
                for f in saindo:
                    caminho.append(f"f_{step.id}_{f.para}")
                    como, texto = andar(f.para, parar=juncao)
                    if como != "parou":
                        return como, texto
                proximo = juncao
                continue
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
                escolhido = next((f for f in saindo if f.condicao and _avaliar(f.condicao, variaveis)), None)
                escolhido = escolhido or next((f for f in saindo if f.condicao is None), None)
                seguinte = escolhido.para if escolhido else None
                nota = f"seguiu para {fluxo.step(seguinte).nome if seguinte and fluxo.step(seguinte) else '?'}"
            elif step.tipo == "espera":
                nota = f"chegou {step.mensagem}" if step.espera == "mensagem" else f"esperou {step.horas or 0:g} h"
            elif step.tipo == "paralelo":
                nota = "todos os ramos chegaram"
            retoma = exception_merge(fluxo, step) if seguinte else None  # passo e exceção se juntam antes do paralelo
            if step.tipo in ("acao", "agente") and step.id in cenario.excecoes and step.excecao:
                caminho.extend([f"{step.id}__erro", f"f_{step.id}__erro", f"{step.id}__excecao"])
                nota = "caiu na exceção: o staff resolveu"
                if seguinte:
                    caminho.append(f"f_{step.id}__excecao_{seguinte}")
                    if retoma:
                        caminho.extend([retoma, f"f_{retoma}_{seguinte}"])
                    passos.append(PassoSimulado(id=step.id, nome=step.nome, tipo=step.tipo, nota=nota))
                    proximo = seguinte
                    continue
            passos.append(PassoSimulado(id=step.id, nome=step.nome, tipo=step.tipo, nota=nota))
            if step.tipo == "fim":
                return "fim", step.resultado or step.nome
            if not seguinte:
                return "erro", f"{step.nome} não tem caminho depois."
            caminho.append(f"f_{step.id}_{seguinte}")
            if retoma:
                caminho.extend([retoma, f"f_{retoma}_{seguinte}"])
            proximo = seguinte

    primeiro = next((f.para for f in fluxo.outgoing(START)), None)
    if primeiro:
        caminho.append(f"f_{START}_{primeiro}")
    como, texto = andar(primeiro)
    if como == "fim":
        return Simulacao(caminho=caminho, passos=passos, fim=texto, problemas=problemas)
    return Simulacao(caminho=caminho, passos=passos, fim=None, problemas=problemas or [texto or "O caminho parou."])


async def _publicados_por_evento(evento: str) -> list[tuple[Processo, dict[str, Any]]]:
    """Os processos publicados da organização cujo gatilho é este evento, com a versão publicada."""
    out = []
    for processo in await _todos():
        if processo.publicada is None:
            continue
        publicada = next((v for v in await _versoes(processo.id) if v["status"] == "publicada"), None)
        if publicada is None:
            continue
        gatilho = Fluxo.model_validate(publicada["fluxo"]).gatilho
        if gatilho.tipo == "evento" and gatilho.evento == evento:
            out.append((processo, publicada))
    return out


async def _pausar(processo_id: str, pausar: bool) -> Processo:
    who = current()
    if who is None or not (who.is_system or STARTERS & who.roles):
        raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só donos, administradores e operadores pausam e retomam processos.", 403)
    processo = await _processo_por_id(processo_id)
    if processo.publicada is None:
        raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", "Só um processo publicado se pausa.", 409)
    mudancas = {"pausado": True, "pausado_em": datetime.now(UTC), "pausado_por": who.sub} if pausar else \
        {"pausado": False, "pausado_em": None, "pausado_por": None}
    processo = _processo(await db.merge(f"{PROCESSOS}:{processo.id}", mudancas))
    await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=processo.id, action="pausado" if pausar else "retomado"))
    return processo


async def _bloqueio(processo: Processo) -> str | None:
    """Por que nada novo começa agora (None: pode): o processo pausado, ou a conta da organização suspensa ou encerrada
    (o svc-plans, perguntado na hora)."""
    if processo.pausado:
        return "O processo está pausado: retome para iniciar execuções."
    situacao = await plans.situacao()
    if situacao == "suspensa":
        return "A conta está suspensa: nenhuma execução nova começa até a regularização. Fale com a Cogniventure."
    if situacao == "encerrada":
        return "A conta está encerrada: nenhuma execução nova começa."
    return None


async def _iniciar(processo: Processo, versao: dict[str, Any], *, origem: str, gatilho: dict[str, Any], resumo: str | None,
                   chave: str | None = None, pai: Execucao | None = None) -> Execucao:
    """Inicia no motor (com o limite do plano conferido antes) e registra a execução; pai: a execução do processo que
    terminou e iniciou esta (a cadeia)."""
    if chave:
        existente = await db.query(f"SELECT * FROM {EXECUCOES} WHERE tenant = $tenant AND gatilho_id = $g LIMIT 1", g=chave)
        if existente:
            return Execucao.model_validate(existente[0])  # o mesmo evento entregue de novo
    if motivo := await _bloqueio(processo):
        situacao = "PAUSADO" if processo.pausado else ("CONTA_ENCERRADA" if "encerrada" in motivo else "CONTA_SUSPENSA")
        raise ServiceError(f"ERRO_PROCESSOS_{situacao}", motivo, 409)
    await plans.check("execucoes")
    iniciada = await camunda.start(_motor_id(processo.id), {"gatilho": gatilho})
    execucao = await _registrar_execucao(processo, iniciada.instance, iniciada.version, origem=origem, resumo=resumo, gatilho_id=chave,
                                         pai=pai, gatilho=gatilho)
    await plans.use("execucoes", 1, key=f"execucao-{iniciada.instance}")
    return execucao


async def _registrar_execucao(processo: Processo, instancia: str, motor_versao: int, *, origem: str, resumo: str | None,
                              gatilho_id: str | None = None, pai: Execucao | None = None,
                              gatilho: dict[str, Any] | None = None) -> Execucao:
    versao = await _versao_do_motor(processo.id, motor_versao)
    dados = {"instancia": instancia, "processo": processo.id, "titulo": processo.titulo, "versao": versao["numero"] if versao else None,
             "motor_versao": motor_versao, "status": "andamento", "origem": origem, "resumo": resumo, "handoffs": 0, "saidas": {},
             "marcos": [Marco(passo=START, nome="Início", status="iniciada", em=datetime.now(UTC), motivo=resumo).model_dump(mode="json")]}
    if gatilho_id:
        dados["gatilho_id"] = gatilho_id
    if gatilho:  # os dados com que começou (os indicadores podem usar gatilho.<campo>)
        dados["gatilho"] = {k: v for k, v in gatilho.items() if isinstance(v, str | int | float | bool) or v is None}
    if pai is not None:  # a cadeia: a primeira execução dela é o projeto
        dados |= {"pai": pai.id, "projeto": pai.projeto or pai.id, "nivel": pai.nivel + 1}
        if pai.projeto is None:
            await db.merge(f"{EXECUCOES}:{pai.id}", {"projeto": pai.id, "raiz": True})
    try:
        row = await db.create(EXECUCOES, dados)
    except ServiceError as exc:  # o ouvinte do começo registrou antes: completa o que ele não sabia
        if exc.code != "ERRO_RECORD_DUPLICATE":
            raise
        rows = await db.query(f"UPDATE {EXECUCOES} MERGE $m WHERE tenant = $tenant AND instancia = $i RETURN AFTER", i=instancia,
                              m={k: v for k, v in dados.items() if k in ("origem", "resumo", "gatilho_id", "pai", "projeto", "nivel", "gatilho")
                                 and v is not None})
        row = rows[0]
    execucao = Execucao.model_validate(row)
    await bus.live(LIVE_EXECUCOES, ExecucaoMudou(id=execucao.id, action="iniciada"))
    return execucao


async def _execucao_por_instancia(instancia: str) -> Execucao | None:
    rows = await db.query(f"SELECT * FROM {EXECUCOES} WHERE tenant = $tenant AND instancia = $i LIMIT 1", i=instancia)
    return Execucao.model_validate(rows[0]) if rows else None


async def _disparar(execucao: Execucao, resultado: str, variaveis: dict[str, Any]) -> None:
    """A execução terminou: inicia cada processo publicado da organização cujo gatilho é este processo (pelo modelo ou
    pelo id) com este resultado, com as saídas dela no gatilho. Uma vez por processo (o ouvinte pode vir de novo); a
    cadeia para em CADEIA processos (um laço entre processos não roda para sempre)."""
    origem = await _processo_por_id(execucao.processo)
    if execucao.nivel + 1 >= CADEIA:
        return
    dados = dict(variaveis.get("gatilho") or {})
    for nome, valor in variaveis.items():
        if isinstance(valor, dict) and nome not in ("gatilho", "parametros", "entrada", "mensagem"):
            dados |= {k: v for k, v in valor.items() if isinstance(v, str | int | float | bool)}
    dados |= {"origem": "processo", "execucao_origem": execucao.id, "processo_origem": origem.titulo, "resultado_origem": resultado}
    for processo in await _todos():
        if processo.publicada is None or processo.id == origem.id:
            continue
        publicada = next((v for v in await _versoes(processo.id) if v["status"] == "publicada"), None)
        gatilho = Fluxo.model_validate(publicada["fluxo"]).gatilho if publicada else None
        if gatilho is None or gatilho.tipo != "processo" or gatilho.processo not in (origem.id, origem.modelo):
            continue
        if gatilho.resultado and _normal(gatilho.resultado) != _normal(resultado):
            continue
        resumo = f"{origem.titulo}: {resultado}" + (f" ({execucao.resumo})" if execucao.resumo else "")
        try:
            await _iniciar(processo, publicada, origem="processo", gatilho=dados, resumo=resumo[:300],
                           chave=f"{execucao.instancia}:{processo.id}", pai=execucao)
        except ServiceError as exc:
            if exc.status >= 500:
                raise  # o motor fora do ar: o ouvinte volta e tenta de novo (a chave impede iniciar duas vezes)
            await _marcar(execucao.instancia, Marco(passo=START, nome=f"Não iniciou {processo.titulo}", status="incidente",
                                                    em=datetime.now(UTC), motivo=exc.message))


async def _etapas_de(projetos: list[str]) -> dict[str, list[EtapaProjeto]]:
    """As execuções de cada projeto, na ordem em que começaram."""
    if not projetos:
        return {}
    rows = await db.query(f"SELECT * FROM {EXECUCOES} WHERE tenant = $tenant AND projeto IN $p ORDER BY created_at", p=projetos)
    out: dict[str, list[EtapaProjeto]] = {}
    for row in rows:
        out.setdefault(row["projeto"], []).append(EtapaProjeto.model_validate(row))
    return out


async def _etapas(projeto: str) -> list[EtapaProjeto]:
    return (await _etapas_de([projeto])).get(projeto, [])


async def _marcar(instancia: str, marco: Marco, *, saida: tuple[str, dict[str, Any]] | None = None, aguardando: Any = ...,
                  atual: tuple[str | None, str | None] | None = None, handoff: bool = False, incidente: bool = False,
                  final: dict[str, Any] | None = None) -> None:
    """Acrescenta um marco à linha do tempo (atômico no banco) e atualiza onde a execução está."""
    sets = ["marcos += $marco", "updated_at = time::now()"]
    params: dict[str, Any] = {"marco": marco.model_dump(mode="json"), "i": instancia}
    if saida is not None:
        sets.append(f"saidas.{saida[0]} = $saida")
        params["saida"] = saida[1]
    if aguardando is not ...:
        sets.append("aguardando = $aguardando")
        params["aguardando"] = aguardando
    if atual is not None:
        sets += ["passo_atual = $atual", "passo_nome = $atual_nome"]
        params |= {"atual": atual[0], "atual_nome": atual[1]}
    if handoff:
        sets.append("handoffs += 1")
    if incidente:
        sets.append("status = 'incidente'")
    for campo, valor in (final or {}).items():
        sets.append(f"{campo} = ${campo}")
        params[campo] = valor
    rows = await db.query(f"UPDATE {EXECUCOES} SET {', '.join(sets)} WHERE tenant = $tenant AND instancia = $i RETURN AFTER", **params)
    if rows:
        execucao = Execucao.model_validate(rows[0])
        await bus.live(LIVE_EXECUCOES, ExecucaoMudou(id=execucao.id, action="concluida" if final else "mudou"))


async def _versao_do_motor(processo_id: str, motor_versao: int) -> dict[str, Any] | None:
    """A nossa versão que foi implantada como esta versão do motor (a execução roda nela até o fim)."""
    return next((v for v in await _versoes(processo_id) if (v.get("motor") or {}).get("versao") == motor_versao), None)


async def _nome_do_passo(processo_id: str, motor_versao: int, passo: str) -> str:
    versao = await _versao_do_motor(processo_id, motor_versao)
    step = Fluxo.model_validate(versao["fluxo"]).step(passo) if versao else None
    return step.nome if step else passo


def _autonomia(execucoes: list[dict[str, Any]], versao: int | None = None) -> Autonomia:
    concluidas = [e for e in execucoes if e["status"] == "concluida"]
    sem = sum(1 for e in concluidas if not e.get("handoffs"))
    return Autonomia(versao=versao, concluidas=len(concluidas), sem_handoff=sem,
                     autonomia=round(sem / len(concluidas), 3) if concluidas else None)


def _quando(valor: Any) -> datetime | None:
    """Data do motor ("2026-10-04T15:17:21.164Z[GMT]") ou do banco → datetime com fuso."""
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    texto = re.sub(r"\[.*\]$", "", str(valor)).replace("Z", "+00:00")
    try:
        data = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=UTC)


_ROTULOS = {"fornecedor": "Fornecedor", "cnpj": "CNPJ", "valor": "Valor", "vencimento": "Vencimento", "linha_digitavel": "Linha digitável",
            "nome": "Documento", "de": "De", "assunto": "Assunto", "nota_documento": "PDF da nota fiscal", "divergente": "Diverge do pedido", "diferenca": "Diferença",
            "fornecedor_novo": "Fornecedor novo", "pedido": "Pedido ou contrato", "conta": "Conta", "pagamento_id": "Pagamento", "data": "Data",
            # N7: os pacotes de área
            "processo_origem": "Iniciado por", "cliente": "Cliente", "email": "E-mail", "descricao": "Descrição", "desconto": "Desconto (%)",
            "validade": "Validade", "parte": "Parte", "objeto": "Objeto", "pontos": "Pontos de atenção", "risco_alto": "Risco alto",
            "inicio": "Início", "fim": "Fim", "cargo": "Cargo", "colaborador": "Colaborador", "item": "Item", "quantidade": "Quantidade",
            "melhor_fornecedor": "Melhor cotação", "melhor_valor": "Valor da melhor cotação", "recebidas": "Cotações recebidas",
            "prazo_dias": "Prazo de entrega (dias)", "referencia": "Mês", "pendencias": "Pendências", "resumo": "Resumo",
            "novas": "Intimações novas", "prazo_final": "Prazo final", "positivas": "Certidões positivas", "proximos": "Vencimentos próximos",
            "exige_presenca": "Exigem presença ou vistoria", "qualificado": "Qualificado", "quer_humano": "Pediu atendimento humano",
            "interesse": "Interesse", "telefone": "Telefone", "nota_numero": "Nota fiscal", "valor_sem_par": "Valor sem par", "sem_par": "Lançamentos sem par"}
_DINHEIRO = ("valor", "diferenca", "melhor_valor", "valor_sem_par")


def _contexto_tarefa(dados: dict[str, Any]) -> list[Item]:
    """O que a pessoa precisa ver para decidir: os dados do documento e o que os passos anteriores acharam."""
    itens = []
    for campo, valor in dados.items():
        if campo in _ROTULOS and valor not in (None, "", {}):
            texto = ("Sim" if valor else "Não") if isinstance(valor, bool) else (
                f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if campo in _DINHEIRO and isinstance(valor, (int, float)) else str(valor))
            itens.append(Item(rotulo=_ROTULOS[campo], valor=texto[:200]))
    return itens


def _campos(step: Step, catalogo: dict[str, CatalogAction], visto: dict[str, Any]) -> list[Campo]:
    """Os campos que o staff preenche ao resolver a exceção: a saída que o passo devolveria."""
    if step.tipo == "agente":
        tipos = {c: step.exemplo.get(c) for c in step.saidas}
    elif step.tipo == "acao" and step.acao in catalogo:
        propriedades = catalogo[step.acao].output_schema.get("properties", {})
        tipos = {c: _DOCUMENTO if propriedades.get(c, {}).get("format") == "documento"  # a ação pede um arquivo (ex.: o PDF da nota)
                 else {"number": 0.0, "integer": 0.0, "boolean": False}.get(_tipo_json(propriedades.get(c, {})), "")
                 for c in step_outputs(step, catalogo)}
    else:
        return []
    return [Campo(nome=c, rotulo=_ROTULOS.get(c, c.replace("_", " ").capitalize()),
                  tipo="documento" if t is _DOCUMENTO else "sim_nao" if isinstance(t, bool) else "numero" if isinstance(t, (int, float)) else "texto",
                  valor=visto.get(c) if isinstance(visto.get(c), (str, int, float, bool)) else None) for c, t in tipos.items()]


_DOCUMENTO = object()  # marca de campo que é arquivo anexado (format "documento" no schema de saída da ação)


def _tipo_json(schema: dict[str, Any]) -> str:
    if "type" in schema:
        return schema["type"]
    return next((o.get("type") for o in schema.get("anyOf", []) if o.get("type") not in (None, "null")), "string")


def _tipo_do_exemplo(valor: Any) -> type:
    return bool if isinstance(valor, bool) else float if isinstance(valor, (int, float)) else str


def _valores_da_excecao(tarefa: Tarefa, data: Resposta) -> dict[str, Any]:
    """A saída que o staff preencheu, conferida contra os campos (número é número; obrigatório o que tinha valor)."""
    valores: dict[str, Any] = {}
    for campo in tarefa.campos:
        bruto = data.dados.get(campo.nome, campo.valor)
        if bruto in (None, ""):
            valores[campo.nome] = None
            continue
        if campo.tipo == "numero":
            try:
                valores[campo.nome] = float(str(bruto).replace(",", ".")) if isinstance(bruto, str) else float(bruto)
            except ValueError:
                raise ServiceError("ERRO_PROCESSOS_RESPOSTA", f"{campo.rotulo}: informe um número.", 422) from None
        elif campo.tipo == "sim_nao":
            valores[campo.nome] = bruto if isinstance(bruto, bool) else str(bruto).lower() in ("sim", "true", "1")
        elif campo.tipo == "documento":  # o id do documento que a tela enviou ao svc-integracoes
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(bruto)):
                raise ServiceError("ERRO_PROCESSOS_RESPOSTA", f"{campo.rotulo}: anexe o arquivo de novo.", 422)
            valores[campo.nome] = str(bruto)
        else:
            valores[campo.nome] = str(bruto)[:300]
    if data.comentario:
        valores["comentario"] = data.comentario
    return valores


# ── Resultados: autonomia por mês, fins alcançados e indicadores ────────────

async def _resultados(mes: str, meses: int) -> Resultados:
    """Os números de um mês (e a autonomia dos meses antes dele) dos processos publicados da organização atual."""
    lista = _meses_ate(mes, meses)
    inicio, fim = _limites(lista[0])[0], _limites(mes)[1]
    processos = [p for p in await _todos() if p.publicada is not None]
    execucoes = await db.query(
        f"SELECT processo, status, resultado, handoffs, created_at, concluida_em, marcos, saidas, gatilho FROM {EXECUCOES} "
        "WHERE tenant = $tenant AND ((created_at >= $inicio AND created_at < $fim) OR (concluida_em >= $inicio AND concluida_em < $fim) "
        "OR status = 'andamento')", inicio=inicio, fim=fim)
    versoes = await db.query(
        f"SELECT processo, numero, publicada_em FROM {VERSOES} WHERE tenant = $tenant AND publicada_em != NONE "
        "AND publicada_em >= $inicio AND publicada_em < $fim ORDER BY publicada_em", inicio=inicio, fim=fim)
    modelos = {row["modelo"]: row for row in await db.query_shared(
        f"SELECT modelo, service, indicadores FROM {MODELOS} WHERE modelo IN $m", m=[p.modelo for p in processos if p.modelo])}
    itens = []
    for processo in processos:
        delas = [e for e in execucoes if e["processo"] == processo.id]
        itens.append(await _resultado_processo(processo, delas, [v for v in versoes if v["processo"] == processo.id], mes, lista,
                                               modelos.get(processo.modelo or "")))
    concluidas_mes = [e for e in execucoes if any(e["processo"] == p.id for p in processos) and _no_mes(e, "concluida_em", mes)
                      and e["status"] == "concluida"]
    autonomia = _autonomia(concluidas_mes)
    return Resultados(mes=mes, meses=lista, concluidas=autonomia.concluidas, sem_handoff=autonomia.sem_handoff,
                      autonomia=autonomia.autonomia, processos=itens)


async def _resultado_processo(processo: Processo, execucoes: list[dict[str, Any]], versoes: list[dict[str, Any]], mes: str,
                              lista: list[str], modelo: dict[str, Any] | None) -> ResultadoProcesso:
    concluidas = [e for e in execucoes if e["status"] == "concluida" and _no_mes(e, "concluida_em", mes)]
    por_mes = []
    for m in lista:
        a = _autonomia([e for e in execucoes if e["status"] == "concluida" and _no_mes(e, "concluida_em", m)])
        por_mes.append(MesAutonomia(mes=m, concluidas=a.concluidas, sem_handoff=a.sem_handoff, autonomia=a.autonomia))
    fins: dict[str, int] = {}
    for e in concluidas:
        fins[e.get("resultado") or "concluída"] = fins.get(e.get("resultado") or "concluída", 0) + 1
    declarados = [CatalogIndicator.model_validate(i) for i in (modelo or {}).get("indicadores") or []]
    valores = {i.nome: _calcular(i, execucoes, mes) for i in declarados if i.calculo != "pacote"}
    if do_pacote := [i.nome for i in declarados if i.calculo == "pacote"]:
        valores |= await _do_pacote(modelo["service"], processo.modelo or "", mes, do_pacote)
    return ResultadoProcesso(
        processo=processo.id, titulo=processo.titulo, modelo=processo.modelo, area=processo.area, publicada=processo.publicada,
        pausado=processo.pausado, meses=por_mes,
        versoes=[MarcaVersao(numero=v["numero"], mes=_mes_de(_quando(v["publicada_em"])), publicada_em=_quando(v["publicada_em"]))
                 for v in versoes],
        iniciadas=sum(1 for e in execucoes if _no_mes(e, "created_at", mes)), concluidas=len(concluidas),
        canceladas=sum(1 for e in execucoes if e["status"] == "cancelada" and _no_mes(e, "concluida_em", mes)),
        em_andamento=sum(1 for e in execucoes if e["status"] == "andamento"),
        fins=[FimAlcancado(resultado=r, quantidade=n) for r, n in sorted(fins.items(), key=lambda x: -x[1])],
        indicadores=[ValorIndicador(nome=i.nome, titulo=i.titulo, unidade=i.unidade, valor=valores.get(i.nome), descricao=i.descricao)
                     for i in declarados])


def _calcular(indicador: CatalogIndicator, execucoes: list[dict[str, Any]], mes: str) -> float | None:
    """Um indicador declarado, das execuções do mês (core/processes.py: Indicator)."""
    if indicador.base == "iniciadas":
        base = [e for e in execucoes if _no_mes(e, "created_at", mes)]
    else:
        base = [e for e in execucoes if e["status"] == "concluida" and _no_mes(e, "concluida_em", mes)]
    filtradas = [e for e in base if _passa(indicador, e)]
    calculo = indicador.calculo
    if calculo == "contagem":
        return float(len(filtradas))
    if calculo == "percentual":
        return round(100 * len(filtradas) / len(base), 1) if base else None
    if calculo in ("soma", "media", "razao"):
        valores = [v for e in filtradas if (v := _numero(_campo(e, indicador.campo or ""))) is not None]
        if calculo == "soma":
            return round(sum(valores), 2) if valores or not filtradas else None
        if calculo == "media":
            return round(sum(valores) / len(valores), 2) if valores else None
        total = sum(v for e in filtradas if (v := _numero(_campo(e, indicador.sobre or ""))) is not None)
        return round(100 * sum(valores) / total, 1) if total else None
    if calculo == "tempo":
        duracoes = [d for e in filtradas if (d := _duracao(e, indicador.de or START, indicador.ate or END)) is not None]
        if not duracoes:
            return None
        media = sum(duracoes) / len(duracoes)
        return round(media / 86_400 if indicador.unidade == "dias" else media / 3_600, 1)
    return None


def _passa(indicador: CatalogIndicator, execucao: dict[str, Any]) -> bool:
    if indicador.resultado is not None and _normal(execucao.get("resultado") or "") != _normal(indicador.resultado):
        return False
    if indicador.condicao is not None:
        return _avaliar(indicador.condicao, _variaveis(execucao))
    return True


def _variaveis(execucao: dict[str, Any]) -> dict[str, Any]:
    return {**(execucao.get("saidas") or {}), "gatilho": execucao.get("gatilho") or {}}


def _campo(execucao: dict[str, Any], campo: str) -> Any:
    passo, _, nome = campo.partition(".")
    return (_variaveis(execucao).get(passo) or {}).get(nome)


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    try:
        return float(str(valor).replace(".", "").replace(",", ".")) if "," in str(valor) else float(str(valor))
    except ValueError:
        return None


def _duracao(execucao: dict[str, Any], de: str, ate: str) -> float | None:
    """Segundos entre dois pontos da execução: inicio (a criação), fim (concluida_em) ou o passo concluído."""
    def quando(ponto: str) -> datetime | None:
        if ponto == START:
            return _quando(execucao.get("created_at"))
        if ponto == END:
            return _quando(execucao.get("concluida_em"))
        return next((_quando(m.get("em")) for m in execucao.get("marcos") or []
                     if m.get("passo") == ponto and m.get("status") in ("concluido", "resolvido")), None)

    a, b = quando(de), quando(ate)
    return (b - a).total_seconds() if a and b and b >= a else None


async def _do_pacote(service: str, modelo: str, mes: str, nomes: list[str]) -> dict[str, float | None]:
    """Os indicadores que o pacote calcula com os dados dele (rpc.<pacote>.indicadores); fora do ar: sem dado."""
    try:
        with acting_as(system(SERVICE, current_tenant())):
            resposta = await bus.request(indicators_subject(service), IndicatorRequest(modelo=modelo, mes=mes, nomes=nomes),
                                         IndicatorValues, timeout=5)
    except (NatsError, TimeoutError, ServiceError) as exc:
        log.warning("indicadores de %s (%s) sem resposta: %s", modelo, service, type(exc).__name__)
        return {}
    return {nome: resposta.valores.get(nome) for nome in nomes}


def _texto_resumo(resultados: Resultados) -> str:
    """O resumo do mês em texto (o e-mail e o aviso na tela)."""
    autonomia = f"{round(resultados.autonomia * 100)}%" if resultados.autonomia is not None else "sem execuções concluídas"
    linhas = [f"No mês, {resultados.concluidas} execução(ões) concluída(s); rodaram sozinhas: {autonomia}.", ""]
    for p in resultados.processos:
        m = p.meses[-1]
        sozinha = f", {round(m.autonomia * 100)}% sozinhas" if m.autonomia is not None else ""
        linhas.append(f"{p.titulo}: {p.concluidas} concluída(s){sozinha}" + (" (pausado)" if p.pausado else ""))
        for i in p.indicadores:
            if i.valor is not None:
                linhas.append(f"  · {i.titulo}: {_formatar(i.valor, i.unidade)}")
    return "\n".join(linhas)[:3900]


def _formatar(valor: float, unidade: str) -> str:
    numero = f"{valor:,.2f}" if unidade == "moeda" else (f"{valor:,.1f}" if not float(valor).is_integer() else f"{valor:,.0f}")
    numero = numero.replace(",", "_").replace(".", ",").replace("_", ".")
    return {"moeda": f"R$ {numero}", "percentual": f"{numero}%", "dias": f"{numero} dia(s)", "horas": f"{numero} h"}.get(unidade, numero)


def _mes_atual() -> str:
    return datetime.now(ZoneInfo(FUSO)).strftime("%Y-%m")


def _mes_anterior(mes: str) -> str:
    ano, numero = (int(x) for x in mes.split("-"))
    return f"{ano - 1}-12" if numero == 1 else f"{ano}-{numero - 1:02d}"


def _meses_ate(mes: str, quantos: int) -> list[str]:
    lista = [mes]
    while len(lista) < quantos:
        lista.insert(0, _mes_anterior(lista[0]))
    return lista


def _limites(mes: str) -> tuple[datetime, datetime]:
    """Começo e fim (exclusivo) do mês em Brasília, em UTC."""
    ano, numero = (int(x) for x in mes.split("-"))
    seguinte = (ano + 1, 1) if numero == 12 else (ano, numero + 1)
    fuso = ZoneInfo(FUSO)
    return datetime(ano, numero, 1, tzinfo=fuso).astimezone(UTC), datetime(*seguinte, 1, tzinfo=fuso).astimezone(UTC)


def _mes_de(quando: datetime | None) -> str:
    return quando.astimezone(ZoneInfo(FUSO)).strftime("%Y-%m") if quando else ""


def _no_mes(execucao: dict[str, Any], campo: str, mes: str) -> bool:
    return _mes_de(_quando(execucao.get(campo))) == mes


_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _mes_extenso(mes: str) -> str:
    ano, numero = mes.split("-")
    return f"{_MESES[int(numero) - 1]} de {ano}"
