"""svc-conhecimento · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/conhecimento.md

HTTP /briefing...   → briefing com o agente (a mensagem responde em pedaços: os passos do agente e o briefing final).
HTTP /itens...      → cadastro declarado em schemas.RESOURCES (core/resources.py): lista, item, cria, edita, remove.
HTTP /site, /documentos, /leituras → leituras de site e documentos, em segundo plano.
NATS TRIGGER_SUBJECT → inicia LeituraWorkflow (assíncrona, durável e idempotente).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-conhecimento main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope, stream_response
from core.nats_bus import bus
from core.plans import plans
from core.resources import resources
from core.security import install_security
from core.storage import storage
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    MODULE,
    RESOURCES,
    SEARCH,
    SERVICE,
    TABLES,
    TASK_QUEUE,
    TRIGGER_SUBJECT,
    UNIQUE,
    Briefing,
    BuscaQuery,
    Empty,
    KeepRequest,
    LeituraPedido,
    LeituraQuery,
    LeituraRef,
    MensagemIn,
    Perfil,
    SiteIn,
    UploadRequest,
)
from service import MIGRATIONS, ConhecimentoService
from workflows import SCHEDULES, LeituraWorkflow

svc = ConhecimentoService()


async def on_trigger(data: LeituraPedido) -> None:
    # id = id estável da mensagem: reentrega do NATS nunca inicia um segundo workflow.
    await runner.start_workflow(LeituraWorkflow.run, data, task_queue=TASK_QUEUE, id=bus.message_id())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, search=SEARCH, resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[LeituraWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await storage.connected(SERVICE)  # documentos enviados (README §5.14)
        await bus.subscribe(TRIGGER_SUBJECT, on_trigger, model=LeituraPedido)
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)
resources.mount(app, RESOURCES)  # as rotas dos itens (README §5.19)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/briefing", response_model=ResponseEnvelope)
async def briefing() -> ResponseEnvelope:
    return _ok(await svc.briefing(Empty()))


@app.post("/briefing/mensagem")
async def mensagem(data: MensagemIn):
    return stream_response(svc.conversar(data), SERVICE, final=Briefing)


@app.post("/briefing/perfil", response_model=ResponseEnvelope)
async def perfil(data: Perfil) -> ResponseEnvelope:
    return _ok(await svc.salvar_perfil(data))


@app.post("/briefing/concluir", response_model=ResponseEnvelope)
async def concluir(data: Empty) -> ResponseEnvelope:
    return _ok(await svc.concluir(data))


@app.post("/briefing/reabrir", response_model=ResponseEnvelope)
async def reabrir(data: Empty) -> ResponseEnvelope:
    return _ok(await svc.reabrir(data))


@app.get("/busca", response_model=ResponseEnvelope)
async def busca(data: Annotated[BuscaQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.buscar(data))


@app.get("/resumo", response_model=ResponseEnvelope)
async def resumo() -> ResponseEnvelope:
    return _ok(await svc.resumo(Empty()))


@app.post("/site", response_model=ResponseEnvelope)
async def site(data: SiteIn) -> ResponseEnvelope:
    return _ok(await svc.pedir_site(data))


@app.post("/documentos/upload", response_model=ResponseEnvelope)
async def documento_upload(data: UploadRequest) -> ResponseEnvelope:
    return _ok(await svc.documento_upload(data))


@app.post("/documentos", response_model=ResponseEnvelope)
async def documento(data: KeepRequest) -> ResponseEnvelope:
    return _ok(await svc.documento(data))


@app.get("/leituras", response_model=ResponseEnvelope)
async def leituras(data: Annotated[LeituraQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.leituras(data))


@app.post("/leituras/remove", response_model=ResponseEnvelope)
async def remover_leitura(data: LeituraRef) -> ResponseEnvelope:
    return _ok(await svc.remover_leitura(data))
