"""svc-atendimento · ingress HTTP + worker Temporal no mesmo loop. Fonte da verdade: specs/atendimento.md

HTTP /resumo, /pedidos... → o "Falar com a Cogniventure": pedir ajuda, conversar, encerrar e o histórico.
NATS rpc.atendimento.pedido e rpc.atendimento.responder → o staff vê e responde pela fila (só o svc-staff).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-atendimento main:app --port 8100 --env-file .env
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
    PEDIDO_SUBJECT,
    RESPONDER_SUBJECT,
    SEARCH,
    SERVICE,
    TABLES,
    TASK_QUEUE,
    Empty,
    MensagemNova,
    NovoPedido,
    PedidoQuery,
    PedidoRef,
    Resposta,
)
from service import MIGRATIONS, AtendimentoService
from workflows import SCHEDULES

svc = AtendimentoService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, search=SEARCH, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[], service=svc, schedules=SCHEDULES),
    ):
        await bus.respond(PEDIDO_SUBJECT, svc.pedido, model=PedidoRef)  # svc-staff: o cartão da fila
        await bus.respond(RESPONDER_SUBJECT, svc.responder, model=Resposta)  # svc-staff: responder pela fila
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


@app.get("/pedidos", response_model=ResponseEnvelope)
async def pedidos(data: Annotated[PedidoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.pedidos(data))


@app.get("/pedidos/item", response_model=ResponseEnvelope)
async def item(data: Annotated[PedidoRef, Query()]) -> ResponseEnvelope:
    return _ok(await svc.item(data))


@app.post("/pedidos", response_model=ResponseEnvelope)
async def abrir(data: NovoPedido) -> ResponseEnvelope:
    return _ok(await svc.abrir(data))


@app.post("/pedidos/mensagem", response_model=ResponseEnvelope)
async def mensagem(data: MensagemNova) -> ResponseEnvelope:
    return _ok(await svc.mensagem(data))


@app.post("/pedidos/encerrar", response_model=ResponseEnvelope)
async def encerrar(data: PedidoRef) -> ResponseEnvelope:
    return _ok(await svc.encerrar(data))
