"""svc-webhooks · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/webhooks.md

HTTP: endereços, entregas e catálogo da organização ativa (todas exigem token de owner/admin).
NATS: EMIT_SUBJECT → WebhooksWorkflow; RETRY_SUBJECT → RedeliverWorkflow; CATALOG_SUBJECT grava o catálogo.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-webhooks main:app --port 8100 --env-file .env
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
from core.webhooks import webhooks

from schemas import (
    CATALOG_SUBJECT,
    EMIT_SUBJECT,
    LIMITS,
    RETRY_SUBJECT,
    SERVICE,
    SHARED_TABLES,
    TASK_QUEUE,
    TENANT_TABLES,
    UNIQUE,
    WEBHOOKS,
    Catalog,
    DeliveryQuery,
    DeliveryRef,
    Emitted,
    Empty,
    EndpointInput,
    EndpointRef,
    EndpointUpdate,
    Outgoing,
)
from service import MIGRATIONS, WebhooksService, settings
from workflows import SCHEDULES, RedeliverWorkflow, WebhooksCleanupWorkflow, WebhooksWorkflow

svc = WebhooksService()


async def on_emit(data: Emitted) -> None:
    # id = id estável da mensagem: reentrega do NATS nunca inicia um segundo workflow nem duplica entregas.
    message = bus.message_id()
    await runner.start_workflow(WebhooksWorkflow.run, Outgoing(message=message, emitted=data), task_queue=TASK_QUEUE, id=message)


async def on_retry(data: DeliveryRef) -> None:
    await runner.start_workflow(RedeliverWorkflow.run, data, task_queue=TASK_QUEUE, id=bus.message_id())


async def on_catalog(data: Catalog) -> None:
    await svc.record_catalog(data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings()  # sem WEBHOOKS_SECRETS_KEY válida o serviço não sobe
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(
            TASK_QUEUE, workflows=[WebhooksWorkflow, RedeliverWorkflow, WebhooksCleanupWorkflow], service=svc, schedules=SCHEDULES
        ),
    ):
        await bus.subscribe(CATALOG_SUBJECT, on_catalog, model=Catalog)
        await bus.subscribe(EMIT_SUBJECT, on_emit, model=Emitted)
        await bus.subscribe(RETRY_SUBJECT, on_retry, model=DeliveryRef)
        await webhooks.declare(WEBHOOKS)  # o próprio webhooks.teste entra no catálogo
        await plans.declare(LIMITS)  # endereços por organização no catálogo de limites dos planos (README §5.17)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)  # nenhuma rota pública (specs/webhooks.md §2)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/endpoints", response_model=ResponseEnvelope)
async def endpoints() -> ResponseEnvelope:
    return _ok(await svc.list_endpoints(Empty()))


@app.post("/endpoints", response_model=ResponseEnvelope)
async def create_endpoint(data: EndpointInput) -> ResponseEnvelope:
    return _ok(await svc.create_endpoint(data))


@app.post("/endpoints/update", response_model=ResponseEnvelope)
async def update_endpoint(data: EndpointUpdate) -> ResponseEnvelope:
    return _ok(await svc.update_endpoint(data))


@app.post("/endpoints/remove", response_model=ResponseEnvelope)
async def remove_endpoint(data: EndpointRef) -> ResponseEnvelope:
    return _ok(await svc.remove_endpoint(data))


@app.post("/endpoints/rotate", response_model=ResponseEnvelope)
async def rotate_secret(data: EndpointRef) -> ResponseEnvelope:
    return _ok(await svc.rotate_secret(data))


@app.post("/endpoints/test", response_model=ResponseEnvelope)
async def test_endpoint(data: EndpointRef) -> ResponseEnvelope:
    return _ok(await svc.test_endpoint(data))


@app.get("/deliveries", response_model=ResponseEnvelope)
async def deliveries(data: Annotated[DeliveryQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.list_deliveries(data))


@app.post("/deliveries/retry", response_model=ResponseEnvelope)
async def retry_delivery(data: DeliveryRef) -> ResponseEnvelope:
    return _ok(await svc.retry_delivery(data))


@app.get("/events", response_model=ResponseEnvelope)
async def events() -> ResponseEnvelope:
    return _ok(await svc.list_events(Empty()))
