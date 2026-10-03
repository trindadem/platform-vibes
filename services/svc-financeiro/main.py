"""svc-financeiro · boot do pacote. Fonte da verdade: specs/financeiro.md

Declara o módulo (plano) e as ações do pacote (catálogo do desenho de processos) e roda o worker delas no motor.
HTTP /fornecedores... → cadastro declarado (core/resources.py). HTTP /titulos → contas a pagar agendadas.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-financeiro main:app --port 8100 --env-file .env
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

from schemas import ACTIONS, MODULE, RESOURCES, SERVICE, TABLES, TASK_QUEUE, UNIQUE, TituloQuery
from service import MIGRATIONS, FinanceiroService
from workflows import SCHEDULES

svc = FinanceiroService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[], service=svc, schedules=SCHEDULES),
        processes.worker(SERVICE, ACTIONS, svc),  # os jobs financeiro.<ação> do motor (core/processes.py)
    ):
        await plans.declare(MODULE)
        await processes.declare(ACTIONS)  # o catálogo de ações vai para o svc-processos
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)
resources.mount(app, RESOURCES)  # as rotas dos fornecedores (README §5.19)


@app.get("/titulos", response_model=ResponseEnvelope)
async def titulos(data: Annotated[TituloQuery, Query()]) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=await svc.titulos(data), service=SERVICE)
