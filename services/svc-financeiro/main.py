"""svc-financeiro · boot do pacote. Fonte da verdade: specs/financeiro.md

Declara o módulo (plano) e as ações do pacote (catálogo do desenho de processos). Sem rotas públicas neste bloco.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-financeiro main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.envelope import install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.processes import processes
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import ACTIONS, MODULE, SERVICE, TASK_QUEUE
from service import MIGRATIONS, FinanceiroService
from workflows import SCHEDULES

svc = FinanceiroService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[], service=svc, schedules=SCHEDULES),
    ):
        await plans.declare(MODULE)
        await processes.declare(ACTIONS)  # o catálogo de ações vai para o svc-processos (core/processes.py)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)
