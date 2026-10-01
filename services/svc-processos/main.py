"""svc-processos · ingress HTTP + worker Temporal no mesmo loop. Fonte da verdade: specs/processos.md

HTTP /biblioteca, /processos...  → biblioteca da Cogniventure e processos da organização (aceitar e recusar).
HTTP POST /descoberta            → o agente de descoberta sugere processos (em pedaços: os passos e o resultado).
HTTP POST /descrever             → o agente organiza um processo descrito pelo cliente.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-processos main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope, stream_response
from core.nats_bus import bus
from core.plans import plans
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import MODULE, SEARCH, SERVICE, TABLES, TASK_QUEUE, Descoberta, Descricao, Empty, ProcessoQuery, ProcessoRef
from service import MIGRATIONS, ProcessosService
from workflows import SCHEDULES

svc = ProcessosService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, search=SEARCH, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[], service=svc, schedules=SCHEDULES),
    ):
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        yield


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
