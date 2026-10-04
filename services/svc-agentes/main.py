"""svc-agentes · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/agentes.md

HTTP /agentes...     → os agentes da organização: lista, item, criar, editar, remover, avaliar (suíte), confiar, testar.
HTTP /ferramentas    → o catálogo do que um agente pode usar (plataforma e servidores MCP de Integrações).
NATS rpc.agentes.lista e rpc.agentes.executar → o svc-processos oferece, confere e roda os agentes nos passos.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-agentes main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    EXECUTAR_SUBJECT,
    LISTA_SUBJECT,
    MODULE,
    SERVICE,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    AgenteRef,
    EdicaoAgente,
    Empty,
    ExecutarAgente,
    NovoAgente,
    Teste,
)
from service import MIGRATIONS, AgentesService
from workflows import SCHEDULES, AvaliarSuiteWorkflow

svc = AgentesService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[AvaliarSuiteWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await bus.respond(LISTA_SUBJECT, svc.lista, model=Empty)  # svc-processos: desenho e validação
        await bus.respond(EXECUTAR_SUBJECT, svc.executar, model=ExecutarAgente)  # svc-processos: passo com agente
        await plans.declare(MODULE)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/agentes", response_model=ResponseEnvelope)
async def agentes() -> ResponseEnvelope:
    return _ok(await svc.agentes(Empty()))


@app.get("/agentes/item", response_model=ResponseEnvelope)
async def agente(data: Annotated[AgenteRef, Query()]) -> ResponseEnvelope:
    return _ok(await svc.agente(data))


@app.post("/agentes", response_model=ResponseEnvelope)
async def criar(data: NovoAgente) -> ResponseEnvelope:
    return _ok(await svc.criar(data))


@app.post("/agentes/editar", response_model=ResponseEnvelope)
async def editar(data: EdicaoAgente) -> ResponseEnvelope:
    return _ok(await svc.editar(data))


@app.post("/agentes/remover", response_model=ResponseEnvelope)
async def remover(data: AgenteRef) -> ResponseEnvelope:
    return _ok(await svc.remover(data))


@app.post("/agentes/avaliar", response_model=ResponseEnvelope)
async def avaliar(data: AgenteRef) -> ResponseEnvelope:
    return _ok(await svc.avaliar(data))


@app.post("/agentes/confiar", response_model=ResponseEnvelope)
async def confiar(data: AgenteRef) -> ResponseEnvelope:
    return _ok(await svc.confiar(data))


@app.post("/agentes/testar", response_model=ResponseEnvelope)
async def testar(data: Teste) -> ResponseEnvelope:
    return _ok(await svc.testar(data))


@app.get("/ferramentas", response_model=ResponseEnvelope)
async def ferramentas() -> ResponseEnvelope:
    return _ok(await svc.catalogo(Empty()))
