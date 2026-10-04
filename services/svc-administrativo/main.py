"""svc-administrativo · boot do pacote. Fonte da verdade: specs/administrativo.md

Declara o módulo (plano), as ações do pacote e os modelos que ele executa (admissão, compras e cotação, vencimentos: o
catálogo do desenho de processos) e roda o worker das ações no motor.
HTTP /colaboradores..., /fornecedores..., /vencimentos... → cadastros declarados (core/resources.py).
HTTP POST /admissoes, /requisicoes → registram e iniciam o processo (events.processos.evento); /requisicoes/cotacao.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-administrativo main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.processes import processes
from core.resources import resources
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    ACTIONS,
    MODELS,
    MODULE,
    RESOURCES,
    SEARCH,
    SERVICE,
    TABLES,
    TASK_QUEUE,
    NovaAdmissao,
    NovaCotacao,
    NovaRequisicao,
    RequisicaoQuery,
)
from service import MIGRATIONS, AdministrativoService
from workflows import SCHEDULES

svc = AdministrativoService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, search=SEARCH, resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[], service=svc, schedules=SCHEDULES),
        processes.worker(SERVICE, ACTIONS, svc),  # os jobs administrativo.<ação> do motor (core/processes.py)
    ):
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        await processes.declare(ACTIONS, MODELS)  # o catálogo de ações e os modelos vão para o svc-processos
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)
resources.mount(app, RESOURCES)  # as rotas dos cadastros (README §5.19)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.post("/admissoes", response_model=ResponseEnvelope)
async def admitir(data: NovaAdmissao) -> ResponseEnvelope:
    return _ok(await svc.admitir(data))


@app.get("/requisicoes", response_model=ResponseEnvelope)
async def requisicoes(data: Annotated[RequisicaoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.requisicoes(data))


@app.post("/requisicoes", response_model=ResponseEnvelope)
async def requisitar(data: NovaRequisicao) -> ResponseEnvelope:
    return _ok(await svc.requisitar(data))


@app.post("/requisicoes/cotacao", response_model=ResponseEnvelope)
async def registrar_cotacao(data: NovaCotacao) -> ResponseEnvelope:
    return _ok(await svc.registrar_cotacao(data))
