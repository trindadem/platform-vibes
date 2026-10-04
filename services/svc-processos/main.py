"""svc-processos · ingress HTTP + worker Temporal no mesmo loop. Fonte da verdade: specs/processos.md

HTTP /biblioteca, /processos...  → biblioteca da Cogniventure e processos da organização (aceitar e recusar).
HTTP POST /descoberta            → o agente de descoberta sugere processos (em pedaços: os passos e o resultado).
HTTP POST /descrever             → o agente organiza um processo descrito pelo cliente.
HTTP /desenho...                 → desenho do processo aceito: abrir, conversar com o agente (em pedaços), simular,
                                   desfazer, publicar no Camunda, ajustar a publicada e descartar o rascunho.
HTTP /execucoes..., /tarefas..., /acompanhamento → execuções no motor, tarefas de pessoas e autonomia.
HTTP /desenho/revisao, /aprovar, /devolver, /ajuda... e /regras... → o staff no setup (revisão, ajuda) e o que ele ensina.
NATS rpc.processos.acompanhamento → a saúde da organização para a carteira do staff (svc-staff).
NATS rpc.processos.fila_*        → o staff vê e resolve exceções e revisões pela fila, sem trocar de organização.
NATS events.processos.catalogo   → os pacotes declaram as ações e os modelos (core/processes.py); o catálogo fica aqui.
NATS events.integracoes.evento   → inicia os processos daquele gatilho e entrega mensagens às execuções que esperam.
NATS events.processos.evento     → o mesmo, para os acontecimentos dos pacotes (vendas.pedido_proposta...).
HTTP /projetos                   → as cadeias de processos (um termina e inicia outros), cada uma como um projeto.
NATS events.processos.passo      → o que o worker de cada pacote fez num passo (a linha do tempo da execução).
Motor (core/processes.py)        → os jobs dos passos de agente e os ouvintes de começo, tarefa, espera e fim.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-processos main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope, stream_response
from core.nats_bus import bus
from core.plans import plans
from core.processes import JOB_AGENT, JOB_END, JOB_START, JOB_TASK, JOB_WAIT, ActionCatalog, camunda, processes
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    ACOMPANHAMENTO_SUBJECT,
    INICIAR_MODELO_SUBJECT,
    RESULTADOS_SUBJECT,
    FILA_DECIDIR_SUBJECT,
    FILA_RESOLVER_SUBJECT,
    FILA_REVISAO_SUBJECT,
    FILA_TAREFA_SUBJECT,
    CATALOG_SUBJECT,
    EVENT_SUBJECT,
    PACOTE_SUBJECT,
    STEP_SUBJECT,
    MODULE,
    SEARCH,
    SERVICE,
    SHARED,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    AdicionarModelo,
    Descoberta,
    Descricao,
    Desenho,
    DesenhoRef,
    AjudaIn,
    CancelarExecucao,
    Devolucao,
    DecisaoStaff,
    Empty,
    EventoExterno,
    ExecucaoQuery,
    ExecucaoRef,
    Iniciar,
    IniciarModelo,
    MensagemDesenhoIn,
    PassoFeito,
    RegraQuery,
    RegraRef,
    ResolucaoStaff,
    Resposta,
    RevisaoRef,
    RevisaoIn,
    TarefaQuery,
    TarefaRef,
    ProcessoQuery,
    ProcessoRef,
    ProjetoQuery,
    ResultadosPedido,
    ResultadosQuery,
    SimulacaoIn,
    VoltarVersao,
)
from service import MIGRATIONS, ProcessosService
from workflows import SCHEDULES, AvaliarRegraWorkflow, ResumoMensalWorkflow

svc = ProcessosService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, shared=SHARED, unique=UNIQUE, search=SEARCH, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[AvaliarRegraWorkflow, ResumoMensalWorkflow], service=svc, schedules=SCHEDULES),
        processes.worker(SERVICE, jobs={JOB_AGENT: svc._job_agente, JOB_START: svc._job_inicio, JOB_TASK: svc._job_tarefa,
                                        JOB_WAIT: svc._job_espera, JOB_END: svc._job_fim}, lock_seconds=600),
    ):
        await bus.subscribe(CATALOG_SUBJECT, svc.registrar_catalogo, model=ActionCatalog)
        await bus.subscribe(EVENT_SUBJECT, svc.receber_evento, model=EventoExterno)
        await bus.subscribe(PACOTE_SUBJECT, svc.receber_evento, model=EventoExterno)  # o mesmo formato (core/processes.py)
        await bus.subscribe(STEP_SUBJECT, svc.registrar_passo, model=PassoFeito)
        await bus.respond(ACOMPANHAMENTO_SUBJECT, svc.acompanhamento, model=Empty)  # svc-staff: a saúde da carteira
        await bus.respond(FILA_TAREFA_SUBJECT, svc.fila_tarefa, model=TarefaRef)  # svc-staff: resolver pela fila
        await bus.respond(FILA_RESOLVER_SUBJECT, svc.fila_resolver, model=ResolucaoStaff)
        await bus.respond(FILA_REVISAO_SUBJECT, svc.fila_revisao, model=RevisaoRef)
        await bus.respond(FILA_DECIDIR_SUBJECT, svc.fila_decidir, model=DecisaoStaff)
        await bus.respond(INICIAR_MODELO_SUBJECT, svc.iniciar_modelo, model=IniciarModelo)  # svc-plans: o fechamento do mês
        await bus.respond(RESULTADOS_SUBJECT, svc.resultados_staff, model=ResultadosPedido)  # svc-staff: a carteira
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        yield
    await camunda.close()


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/biblioteca", response_model=ResponseEnvelope)
async def biblioteca() -> ResponseEnvelope:
    return _ok(await svc.biblioteca(Empty()))


@app.get("/processos", response_model=ResponseEnvelope)
async def listar(data: Annotated[ProcessoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.listar(data))


@app.get("/resumo", response_model=ResponseEnvelope)
async def resumo() -> ResponseEnvelope:
    return _ok(await svc.resumo(Empty()))


@app.post("/descoberta")
async def descoberta(data: Empty):
    return stream_response(svc.descobrir(data), SERVICE, final=Descoberta)


@app.post("/descrever", response_model=ResponseEnvelope)
async def descrever(data: Descricao) -> ResponseEnvelope:
    return _ok(await svc.descrever(data))


@app.post("/processos/aceitar", response_model=ResponseEnvelope)
async def aceitar(data: ProcessoRef) -> ResponseEnvelope:
    return _ok(await svc.aceitar(data))


@app.post("/processos/recusar", response_model=ResponseEnvelope)
async def recusar(data: ProcessoRef) -> ResponseEnvelope:
    return _ok(await svc.recusar(data))


@app.post("/processos/pausar", response_model=ResponseEnvelope)
async def pausar(data: ProcessoRef) -> ResponseEnvelope:
    return _ok(await svc.pausar(data))


@app.post("/processos/retomar", response_model=ResponseEnvelope)
async def retomar(data: ProcessoRef) -> ResponseEnvelope:
    return _ok(await svc.retomar(data))


@app.post("/processos/adicionar", response_model=ResponseEnvelope)
async def adicionar(data: AdicionarModelo) -> ResponseEnvelope:
    return _ok(await svc.adicionar(data))


@app.get("/catalogo", response_model=ResponseEnvelope)
async def catalogo() -> ResponseEnvelope:
    return _ok(await svc.catalogo(Empty()))


@app.post("/desenho/abrir", response_model=ResponseEnvelope)
async def abrir(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.abrir(data))


@app.post("/desenho/mensagem")
async def mensagem(data: MensagemDesenhoIn):
    return stream_response(svc.conversar(data), SERVICE, final=Desenho)


@app.post("/desenho/simular", response_model=ResponseEnvelope)
async def simular(data: SimulacaoIn) -> ResponseEnvelope:
    return _ok(await svc.simular(data))


@app.post("/desenho/desfazer", response_model=ResponseEnvelope)
async def desfazer(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.desfazer(data))


@app.post("/desenho/publicar", response_model=ResponseEnvelope)
async def publicar(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.publicar(data))


@app.post("/desenho/ajustar", response_model=ResponseEnvelope)
async def ajustar(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.ajustar(data))


@app.post("/desenho/descartar", response_model=ResponseEnvelope)
async def descartar(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.descartar(data))


@app.post("/desenho/voltar", response_model=ResponseEnvelope)
async def voltar(data: VoltarVersao) -> ResponseEnvelope:
    return _ok(await svc.voltar(data))


@app.get("/resultados", response_model=ResponseEnvelope)
async def resultados(data: Annotated[ResultadosQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.resultados(data))


@app.get("/execucoes", response_model=ResponseEnvelope)
async def execucoes(data: Annotated[ExecucaoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.execucoes(data))


@app.get("/execucoes/item", response_model=ResponseEnvelope)
async def execucao(data: Annotated[ExecucaoRef, Query()]) -> ResponseEnvelope:
    return _ok(await svc.execucao(data))


@app.post("/execucoes/iniciar", response_model=ResponseEnvelope)
async def iniciar(data: Iniciar) -> ResponseEnvelope:
    return _ok(await svc.iniciar(data))


@app.post("/execucoes/cancelar", response_model=ResponseEnvelope)
async def cancelar_execucao(data: CancelarExecucao) -> ResponseEnvelope:
    return _ok(await svc.cancelar_execucao(data))


@app.get("/tarefas", response_model=ResponseEnvelope)
async def tarefas(data: Annotated[TarefaQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.tarefas(data))


@app.post("/tarefas/responder", response_model=ResponseEnvelope)
async def responder(data: Resposta) -> ResponseEnvelope:
    return _ok(await svc.responder(data))


@app.get("/acompanhamento", response_model=ResponseEnvelope)
async def acompanhamento() -> ResponseEnvelope:
    return _ok(await svc.acompanhamento(Empty()))


@app.get("/projetos", response_model=ResponseEnvelope)
async def projetos(data: Annotated[ProjetoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.projetos(data))


@app.post("/desenho/revisao", response_model=ResponseEnvelope)
async def pedir_revisao(data: RevisaoIn) -> ResponseEnvelope:
    return _ok(await svc.pedir_revisao(data))


@app.post("/desenho/aprovar", response_model=ResponseEnvelope)
async def aprovar_revisao(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.aprovar_revisao(data))


@app.post("/desenho/devolver", response_model=ResponseEnvelope)
async def devolver(data: Devolucao) -> ResponseEnvelope:
    return _ok(await svc.devolver(data))


@app.post("/desenho/ajuda", response_model=ResponseEnvelope)
async def pedir_ajuda(data: AjudaIn) -> ResponseEnvelope:
    return _ok(await svc.pedir_ajuda(data))


@app.post("/desenho/ajuda/concluir", response_model=ResponseEnvelope)
async def concluir_ajuda(data: DesenhoRef) -> ResponseEnvelope:
    return _ok(await svc.concluir_ajuda(data))


@app.get("/regras", response_model=ResponseEnvelope)
async def regras(data: Annotated[RegraQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.regras(data))


@app.post("/regras/desativar", response_model=ResponseEnvelope)
async def desativar_regra(data: RegraRef) -> ResponseEnvelope:
    return _ok(await svc.desativar_regra(data))
