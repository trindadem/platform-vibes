"""svc-notify · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/notify.md

HTTP: os avisos e a preferência de quem chama (todas exigem token).
NATS: SEND_SUBJECT (publicado pelo core/notify.py) → NotifyWorkflow (durável e idempotente).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-notify main:app --port 8100 --env-file .env
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
    SEND_SUBJECT,
    SERVICE,
    SHARED_TABLES,
    TASK_QUEUE,
    TENANT_TABLES,
    UNIQUE,
    Empty,
    NotificationQuery,
    NotifyRequest,
    Outgoing,
    Preferences,
    ReadRequest,
)
from service import MIGRATIONS, NotifyService, settings
from workflows import SCHEDULES, NotifyCleanupWorkflow, NotifyWorkflow

svc = NotifyService()


async def on_send(data: NotifyRequest) -> None:
    # id = id estável da mensagem: reentrega do NATS nunca inicia um segundo workflow nem duplica avisos.
    message = bus.message_id()
    await runner.start_workflow(NotifyWorkflow.run, Outgoing(message=message, request=data), task_queue=TASK_QUEUE, id=message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings()  # SMTP_URL, MAIL_FROM e APP_URL conferidos: configuração inválida não sobe
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[NotifyWorkflow, NotifyCleanupWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await bus.subscribe(SEND_SUBJECT, on_send, model=NotifyRequest)
        await plans.declare(MODULE)  # o módulo, da plataforma, no catálogo dos planos (README §5.17)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)  # nenhuma rota pública (specs/notify.md §2)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/items", response_model=ResponseEnvelope)
async def items(data: Annotated[NotificationQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.list_items(data))


@app.get("/unread", response_model=ResponseEnvelope)
async def unread() -> ResponseEnvelope:
    return _ok(await svc.unread(Empty()))


@app.post("/read", response_model=ResponseEnvelope)
async def read(data: ReadRequest) -> ResponseEnvelope:
    return _ok(await svc.mark_read(data))


@app.post("/read-all", response_model=ResponseEnvelope)
async def read_all() -> ResponseEnvelope:
    return _ok(await svc.mark_all_read(Empty()))


@app.get("/preferences", response_model=ResponseEnvelope)
async def preferences() -> ResponseEnvelope:
    return _ok(await svc.preferences(Empty()))


@app.post("/preferences", response_model=ResponseEnvelope)
async def set_preferences(data: Preferences) -> ResponseEnvelope:
    return _ok(await svc.set_preferences(data))
