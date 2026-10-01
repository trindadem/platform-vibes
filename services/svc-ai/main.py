"""svc-ai · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/ai.md

HTTP: provedores, catálogo de modelos e uso (todas exigem token; gerenciar exige owner/admin).
NATS: rpc.ai.resolve (o core/llm.py pergunta como chamar um modelo), events.ai.usage (uso de cada chamada)
e TRIGGER_SUBJECT → AiWorkflow (busca de modelos em segundo plano).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-ai main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.security import install_security
from core.surreal import db
from core.temporal_runner import runner

from schemas import (
    RESOLVE_SUBJECT,
    SERVICE,
    SHARED_TABLES,
    TASK_QUEUE,
    TENANT_TABLES,
    LIMITS,
    SEARCH,
    TRIGGER_SUBJECT,
    UNIQUE,
    USAGE_SUBJECT,
    Empty,
    ModelInput,
    ModelQuery,
    ModelUpdate,
    ProviderInput,
    ProviderRef,
    ResolveRequest,
    UsageEvent,
)
from service import AiService, settings
from workflows import AiWorkflow

svc = AiService()


async def on_trigger(data: ProviderRef) -> None:
    # id = id estável da mensagem: reentrega do NATS nunca inicia um segundo workflow.
    await runner.start_workflow(AiWorkflow.run, data, task_queue=TASK_QUEUE, id=bus.message_id())


async def on_usage(data: UsageEvent) -> None:
    await svc.record_usage(data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings()  # sem AI_SECRETS_KEY válida o serviço não sobe
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE, search=SEARCH),
        runner.worker(TASK_QUEUE, workflows=[AiWorkflow], service=svc),
    ):
        await bus.subscribe(TRIGGER_SUBJECT, on_trigger, model=ProviderRef)
        await bus.subscribe(USAGE_SUBJECT, on_usage, model=UsageEvent)
        await bus.respond(RESOLVE_SUBJECT, svc.resolve, model=ResolveRequest)
        await plans.declare(LIMITS)  # custo e tokens do mês entram no catálogo de limites dos planos
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)  # nenhuma rota pública (specs/ai.md §2)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/providers", response_model=ResponseEnvelope)
async def providers() -> ResponseEnvelope:
    return _ok(await svc.list_providers(Empty()))


@app.post("/providers", response_model=ResponseEnvelope)
async def create_provider(data: ProviderInput) -> ResponseEnvelope:
    return _ok(await svc.create_provider(data))


@app.post("/providers/remove", response_model=ResponseEnvelope)
async def remove_provider(data: ProviderRef) -> ResponseEnvelope:
    return _ok(await svc.remove_provider(data))


@app.post("/providers/discover", response_model=ResponseEnvelope)
async def discover_models(data: ProviderRef) -> ResponseEnvelope:
    return _ok(await svc.discover_models(data))


@app.get("/models", response_model=ResponseEnvelope)
async def models(data: Annotated[ModelQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.list_models(data))


@app.post("/models", response_model=ResponseEnvelope)
async def add_model(data: ModelInput) -> ResponseEnvelope:
    return _ok(await svc.add_model(data))


@app.post("/models/update", response_model=ResponseEnvelope)
async def update_model(data: ModelUpdate) -> ResponseEnvelope:
    return _ok(await svc.update_model(data))


@app.get("/usage", response_model=ResponseEnvelope)
async def usage() -> ResponseEnvelope:
    return _ok(await svc.usage_summary(Empty()))
