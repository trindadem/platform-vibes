"""svc-plans · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/plans.md

HTTP: plano e consumo da organização ativa, comparação de planos e, para quem administra a plataforma, os planos e a
atribuição (todas exigem token).
NATS: CATALOG_SUBJECT grava os limites declarados; USAGE_SUBJECT soma consumo; COUNT_SUBJECT guarda totais;
rpc.plans.limits responde ao core/plans.py; rpc.plans.assign troca o plano (tarefa da plataforma).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-plans main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.security import install_security
from core.surreal import db
from core.temporal_runner import runner

from schemas import (
    ASSIGN_SUBJECT,
    CATALOG_SUBJECT,
    COUNT_SUBJECT,
    LIMITS_SUBJECT,
    SERVICE,
    SHARED_TABLES,
    TASK_QUEUE,
    TENANT_TABLES,
    UNIQUE,
    USAGE_SUBJECT,
    AssignInput,
    AssignRequest,
    CountReport,
    Empty,
    LimitCatalog,
    LimitsRequest,
    PlanInput,
    PlanRef,
    PlanUpdate,
    UsageReport,
)
from service import MIGRATIONS, PlansService, settings
from workflows import SCHEDULES, PlansCleanupWorkflow

svc = PlansService()


async def on_catalog(data: LimitCatalog) -> None:
    await svc.record_catalog(data)


async def on_usage(data: UsageReport) -> None:
    await svc.record_usage(data)


async def on_count(data: CountReport) -> None:
    await svc.record_count(data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings()
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[PlansCleanupWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await bus.subscribe(CATALOG_SUBJECT, on_catalog, model=LimitCatalog)
        await bus.subscribe(USAGE_SUBJECT, on_usage, model=UsageReport)
        await bus.subscribe(COUNT_SUBJECT, on_count, model=CountReport)
        await bus.respond(LIMITS_SUBJECT, svc.resolve, model=LimitsRequest)
        await bus.respond(ASSIGN_SUBJECT, svc.assign, model=AssignRequest)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)  # nenhuma rota pública (specs/plans.md §2)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/current", response_model=ResponseEnvelope)
async def current() -> ResponseEnvelope:
    return _ok(await svc.current(Empty()))


@app.get("/plans", response_model=ResponseEnvelope)
async def plans() -> ResponseEnvelope:
    return _ok(await svc.list_plans(Empty()))


@app.get("/limits", response_model=ResponseEnvelope)
async def limits() -> ResponseEnvelope:
    return _ok(await svc.list_limits(Empty()))


@app.post("/plans", response_model=ResponseEnvelope)
async def create_plan(data: PlanInput) -> ResponseEnvelope:
    return _ok(await svc.create_plan(data))


@app.post("/plans/update", response_model=ResponseEnvelope)
async def update_plan(data: PlanUpdate) -> ResponseEnvelope:
    return _ok(await svc.update_plan(data))


@app.post("/plans/remove", response_model=ResponseEnvelope)
async def remove_plan(data: PlanRef) -> ResponseEnvelope:
    return _ok(await svc.remove_plan(data))


@app.post("/assign", response_model=ResponseEnvelope)
async def assign(data: AssignInput) -> ResponseEnvelope:
    return _ok(await svc.assign_plan(data))
