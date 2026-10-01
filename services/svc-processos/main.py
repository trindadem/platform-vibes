"""svc-processos · ingress HTTP + worker Temporal no mesmo loop. Fonte da verdade: specs/processos.md

HTTP /biblioteca, /processos...  → biblioteca da Cogniventure e processos da organização (aceitar e recusar).
HTTP POST /descoberta            → o agente de descoberta sugere processos (em pedaços: os passos e o resultado).
HTTP POST /descrever             → o agente organiza um processo descrito pelo cliente.
HTTP /desenho...                 → desenho do processo aceito: abrir, conversar com o agente (em pedaços), simular,
                                   desfazer, publicar no Camunda, ajustar a publicada e descartar o rascunho.
NATS events.processos.catalogo   → os pacotes declaram as ações (core/processes.py); o catálogo fica aqui.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-processos main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope, stream_response
from core.nats_bus import bus
from core.plans import plans
from core.processes import ActionCatalog, camunda
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    CATALOG_SUBJECT,
    MODULE,
    SEARCH,
    SERVICE,
    SHARED,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    Descoberta,
    Descricao,
    Desenho,
    DesenhoRef,
    Empty,
    MensagemDesenhoIn,
    ProcessoQuery,
    ProcessoRef,
    SimulacaoIn,
)
from service import MIGRATIONS, ProcessosService
from workflows import SCHEDULES

svc = ProcessosService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, shared=SHARED, unique=UNIQUE, search=SEARCH, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[], service=svc, schedules=SCHEDULES),
    ):
        await bus.subscribe(CATALOG_SUBJECT, svc.registrar_catalogo, model=ActionCatalog)
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
