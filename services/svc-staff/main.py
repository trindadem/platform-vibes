"""svc-staff · ingress HTTP + worker Temporal no mesmo loop. Fonte da verdade: specs/staff.md

HTTP /carteiras..., /organizacoes → o gestor monta as carteiras (dá e tira o papel operador nos clientes).
HTTP /carteira, /fila..., /resumo → a área de cada pessoa do staff: clientes, saúde e o que espera por ela.
NATS events.processos.staff → o que espera o staff em cada organização (exceção, revisão, ajuda): a fila.
Agenda (Temporal) a cada minuto → exceção vencida sem dono sobe para o gestor.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-staff main:app --port 8100 --env-file .env
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
    MODULE,
    SERVICE,
    STAFF_SUBJECT,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    Atribuicao,
    CarteiraRef,
    Empty,
    FilaQuery,
    ItemRef,
    ItemStaff,
    NovaCarteira,
)
from service import MIGRATIONS, StaffService
from workflows import SCHEDULES, EscalarWorkflow

svc = StaffService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[EscalarWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await bus.subscribe(STAFF_SUBJECT, svc.receber, model=ItemStaff)
        await plans.declare(MODULE)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/resumo", response_model=ResponseEnvelope)
async def resumo() -> ResponseEnvelope:
    return _ok(await svc.resumo(Empty()))


@app.get("/organizacoes", response_model=ResponseEnvelope)
async def organizacoes() -> ResponseEnvelope:
    return _ok(await svc.organizacoes(Empty()))


@app.get("/carteiras", response_model=ResponseEnvelope)
async def carteiras() -> ResponseEnvelope:
    return _ok(await svc.carteiras(Empty()))


@app.post("/carteiras", response_model=ResponseEnvelope)
async def atribuir_carteira(data: NovaCarteira) -> ResponseEnvelope:
    return _ok(await svc.atribuir_carteira(data))


@app.post("/carteiras/remover", response_model=ResponseEnvelope)
async def remover_carteira(data: CarteiraRef) -> ResponseEnvelope:
    return _ok(await svc.remover_carteira(data))


@app.get("/carteira", response_model=ResponseEnvelope)
async def carteira() -> ResponseEnvelope:
    return _ok(await svc.carteira(Empty()))


@app.get("/fila", response_model=ResponseEnvelope)
async def fila(data: Annotated[FilaQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.fila(data))


@app.post("/fila/assumir", response_model=ResponseEnvelope)
async def assumir(data: ItemRef) -> ResponseEnvelope:
    return _ok(await svc.assumir(data))


@app.post("/fila/atribuir", response_model=ResponseEnvelope)
async def atribuir(data: Atribuicao) -> ResponseEnvelope:
    return _ok(await svc.atribuir(data))
