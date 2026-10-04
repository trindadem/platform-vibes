"""svc-vendas · boot do pacote. Fonte da verdade: specs/vendas.md

Declara o módulo (plano), as ações do pacote e os modelos que ele executa (qualificação de leads, proposta comercial e
reativação da carteira: o catálogo do desenho de processos) e roda o worker das ações no motor.
HTTP /leads..., /clientes... → cadastros declarados (core/resources.py); POST /leads/receber inicia a qualificação.
HTTP /propostas → as propostas; POST /propostas (o pedido) inicia o processo de proposta (events.processos.evento).
Temporal: os follow-ups das propostas sem resposta, todo dia.
NATS rpc.vendas.indicadores → os indicadores "pacote" dos modelos (propostas enviadas, aceite, voltaram a comprar).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-vendas main:app --port 8100 --env-file .env
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

from schemas import ACTIONS, MODELS, MODULE, RESOURCES, SEARCH, SERVICE, TABLES, TASK_QUEUE, PedidoProposta, PropostaQuery, ReceberLead
from service import MIGRATIONS, VendasService
from workflows import SCHEDULES, FollowUpWorkflow

svc = VendasService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, search=SEARCH, resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[FollowUpWorkflow], service=svc, schedules=SCHEDULES),
        processes.worker(SERVICE, ACTIONS, svc),  # os jobs vendas.<ação> do motor (core/processes.py)
    ):
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        # o catálogo de ações e os modelos (com os indicadores) vão para o svc-processos; os "pacote" saem de svc.indicadores
        await processes.declare(ACTIONS, MODELS, indicators=svc.indicadores)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)
resources.mount(app, RESOURCES)  # as rotas dos cadastros (README §5.19)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.post("/leads/receber", response_model=ResponseEnvelope)
async def receber_lead(data: ReceberLead) -> ResponseEnvelope:
    return _ok(await svc.receber_lead(data))


@app.get("/propostas", response_model=ResponseEnvelope)
async def propostas(data: Annotated[PropostaQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.propostas(data))


@app.post("/propostas", response_model=ResponseEnvelope)
async def pedir_proposta(data: PedidoProposta) -> ResponseEnvelope:
    return _ok(await svc.pedir_proposta(data))
