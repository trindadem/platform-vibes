"""svc-financeiro · boot do pacote. Fonte da verdade: specs/financeiro.md

Declara o módulo (plano), as ações do pacote e os modelos que ele executa (contas a pagar, conciliação, faturamento e
fechamento: o catálogo do desenho de processos) e roda o worker das ações no motor.
HTTP /fornecedores... → cadastro declarado (core/resources.py). HTTP /titulos → contas a pagar agendadas.
HTTP /faturas → contas a receber (faturamento e cobrança). Temporal: a régua de cobrança, todo dia.
NATS rpc.financeiro.indicadores → os indicadores "pacote" dos modelos (pagos em atraso, valor em atraso).

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

from schemas import ACTIONS, MODELS, MODULE, RESOURCES, SERVICE, TABLES, TASK_QUEUE, UNIQUE, FaturaQuery, TituloQuery
from service import MIGRATIONS, FinanceiroService
from workflows import SCHEDULES, ReguaWorkflow

svc = FinanceiroService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[ReguaWorkflow], service=svc, schedules=SCHEDULES),
        processes.worker(SERVICE, ACTIONS, svc),  # os jobs financeiro.<ação> do motor (core/processes.py)
    ):
        await plans.declare(MODULE)
        # o catálogo de ações e os modelos (com os indicadores) vão para o svc-processos; os indicadores "pacote"
        # saem de svc.indicadores (rpc.financeiro.indicadores)
        await processes.declare(ACTIONS, MODELS, indicators=svc.indicadores)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)
resources.mount(app, RESOURCES)  # as rotas dos fornecedores (README §5.19)


@app.get("/titulos", response_model=ResponseEnvelope)
async def titulos(data: Annotated[TituloQuery, Query()]) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=await svc.titulos(data), service=SERVICE)


@app.get("/faturas", response_model=ResponseEnvelope)
async def faturas(data: Annotated[FaturaQuery, Query()]) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=await svc.faturas(data), service=SERVICE)
