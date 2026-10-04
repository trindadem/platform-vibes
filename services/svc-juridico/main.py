"""svc-juridico · boot do pacote. Fonte da verdade: specs/juridico.md

Declara o módulo (plano), as ações do pacote e os modelos que ele executa (gestão de contratos, publicações e
certidões: o catálogo do desenho de processos) e roda o worker das ações no motor.
HTTP /contratos..., /certidoes... → cadastros declarados (core/resources.py).
Temporal: os avisos antes de vencer, todo dia.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-juridico main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.envelope import install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.processes import processes
from core.resources import resources
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import ACTIONS, MODELS, MODULE, RESOURCES, SERVICE, TASK_QUEUE
from service import MIGRATIONS, JuridicoService
from workflows import SCHEDULES, AvisosWorkflow

svc = JuridicoService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[AvisosWorkflow], service=svc, schedules=SCHEDULES),
        processes.worker(SERVICE, ACTIONS, svc),  # os jobs juridico.<ação> do motor (core/processes.py)
    ):
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        await processes.declare(ACTIONS, MODELS)  # o catálogo de ações e os modelos vão para o svc-processos
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)
resources.mount(app, RESOURCES)  # as rotas dos cadastros (README §5.19)
