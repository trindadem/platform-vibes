"""svc-integracoes · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/integracoes.md

HTTP /conexoes...        → conexões da organização (caixa de entrada, banco simulado).
HTTP /documentos...      → documentos recebidos e o link para abrir cada um.
HTTP /pagamentos...      → pagamentos no banco simulado; confirmar à mão.
HTTP POST /entrada/mailpit → só na rede interna, no ambiente local: o Mailpit avisa que chegou um e-mail (spec §2).
NATS rpc.integracoes.documento e rpc.integracoes.banco_agendar → texto do documento (agentes) e agendamento (ações).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-integracoes main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.security import install_security
from core.storage import storage
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    AGENDAR_SUBJECT,
    DOCUMENTO_SUBJECT,
    MODULE,
    SEARCH,
    SERVICE,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    AgendarPagamento,
    AvisoEmail,
    ConexaoRef,
    DocumentoQuery,
    DocumentoRef,
    Empty,
    NovaConexao,
    PagamentoQuery,
    PagamentoRef,
)
from service import MIGRATIONS, IntegracoesService
from workflows import SCHEDULES, PagamentoSimuladoWorkflow

svc = IntegracoesService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, search=SEARCH, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[PagamentoSimuladoWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await storage.connected(SERVICE)  # os documentos recebidos (README §5.14)
        await bus.respond(DOCUMENTO_SUBJECT, svc.documento_texto, model=DocumentoRef)  # agentes dos processos
        await bus.respond(AGENDAR_SUBJECT, svc.agendar_pagamento, model=AgendarPagamento)  # ação do svc-financeiro
        await plans.declare(MODULE)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE, public=("/entrada/mailpit",))  # spec §2: aviso do Mailpit, só na rede interna
install_telemetry(app, service=SERVICE)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/conexoes", response_model=ResponseEnvelope)
async def conexoes() -> ResponseEnvelope:
    return _ok(await svc.conexoes(Empty()))


@app.post("/conexoes", response_model=ResponseEnvelope)
async def conectar(data: NovaConexao) -> ResponseEnvelope:
    return _ok(await svc.conectar(data))


@app.post("/conexoes/remover", response_model=ResponseEnvelope)
async def desconectar(data: ConexaoRef) -> ResponseEnvelope:
    return _ok(await svc.desconectar(data))


@app.get("/resumo", response_model=ResponseEnvelope)
async def resumo() -> ResponseEnvelope:
    return _ok(await svc.resumo(Empty()))


@app.get("/documentos", response_model=ResponseEnvelope)
async def documentos(data: Annotated[DocumentoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.documentos(data))


@app.get("/documentos/arquivo", response_model=ResponseEnvelope)
async def arquivo(data: Annotated[DocumentoRef, Query()]) -> ResponseEnvelope:
    return _ok(await svc.arquivo(data))


@app.get("/pagamentos", response_model=ResponseEnvelope)
async def pagamentos(data: Annotated[PagamentoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.pagamentos(data))


@app.post("/pagamentos/confirmar", response_model=ResponseEnvelope)
async def confirmar(data: PagamentoRef) -> ResponseEnvelope:
    return _ok(await svc.confirmar_pagamento(data))


@app.post("/entrada/mailpit", response_model=ResponseEnvelope)
async def mailpit(data: AvisoEmail) -> ResponseEnvelope:
    return _ok(await svc.receber_email(data))
