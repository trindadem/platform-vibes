"""svc-staff · ingress HTTP + worker Temporal no mesmo loop. Fonte da verdade: specs/staff.md

HTTP /clientes... → o gestor abre os clientes (organização, convite do dono, plano e carteira) e acompanha a jornada.
HTTP /carteiras..., /organizacoes → o gestor monta as carteiras (dá e tira o papel operador nos clientes).
HTTP /carteira, /fila..., /resumo → a área de cada pessoa do staff: clientes, saúde e o que espera por ela; a fila
                                   resolve exceção, revisão e pedido de ajuda sem trocar de organização.
HTTP /numeros                    → o gestor vê tempo de resolução e prazo cumprido por pessoa e por cliente.
NATS events.processos.staff e events.atendimento.staff → o que espera o staff em cada organização (exceção, revisão,
ajuda no desenho, pedido de ajuda): a fila.
NATS events.identity.member-left → quem sai da Cogniventure sai das carteiras e perde o papel operador nos clientes.
Agenda (Temporal) a cada minuto → exceção vencida sem dono sobe para o gestor.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-staff main:app --port 8100 --env-file .env
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
    ATENDIMENTO_SUBJECT,
    ENCERRADA_SUBJECT,
    MEMBER_LEFT_SUBJECT,
    MODULE,
    SERVICE,
    STAFF_SUBJECT,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    Atribuicao,
    CarteiraRef,
    ClienteRef,
    CobrancaCliente,
    ContaEncerrada,
    DecidirRevisao,
    Empty,
    FilaQuery,
    ItemRef,
    ItemStaff,
    MemberLeft,
    NovaCarteira,
    NovoCliente,
    NumerosQuery,
    ResultadosQuery,
    SituacaoCliente,
    ResolverExcecao,
    ResponderPedido,
)
from service import MIGRATIONS, StaffService, apagar_cliente
from workflows import SCHEDULES, EscalarWorkflow

svc = StaffService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, migrations=MIGRATIONS, service=SERVICE, on_purge=apagar_cliente),
        runner.worker(TASK_QUEUE, workflows=[EscalarWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await bus.subscribe(STAFF_SUBJECT, svc.receber, model=ItemStaff)
        await bus.subscribe(ATENDIMENTO_SUBJECT, svc.receber, model=ItemStaff)  # os pedidos de ajuda dos clientes
        await bus.subscribe(MEMBER_LEFT_SUBJECT, svc.saiu, model=MemberLeft)
        await bus.subscribe(ENCERRADA_SUBJECT, svc.encerrada, model=ContaEncerrada)  # svc-plans: a conta do cliente encerrou
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


@app.get("/clientes", response_model=ResponseEnvelope)
async def clientes() -> ResponseEnvelope:
    return _ok(await svc.clientes(Empty()))


@app.post("/clientes", response_model=ResponseEnvelope)
async def novo_cliente(data: NovoCliente) -> ResponseEnvelope:
    return _ok(await svc.novo_cliente(data))


@app.post("/clientes/convite", response_model=ResponseEnvelope)
async def convidar_dono(data: ClienteRef) -> ResponseEnvelope:
    return _ok(await svc.convidar_dono(data))


@app.get("/carteira/resultados", response_model=ResponseEnvelope)
async def resultados(data: Annotated[ResultadosQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.resultados(data))


@app.post("/clientes/cobranca", response_model=ResponseEnvelope)
async def cobranca(data: CobrancaCliente) -> ResponseEnvelope:
    return _ok(await svc.cobranca(data))


@app.post("/clientes/situacao", response_model=ResponseEnvelope)
async def situacao(data: SituacaoCliente) -> ResponseEnvelope:
    return _ok(await svc.situacao(data))


@app.get("/organizacoes", response_model=ResponseEnvelope)
async def organizacoes() -> ResponseEnvelope:
    return _ok(await svc.organizacoes(Empty()))


@app.get("/carteiras", response_model=ResponseEnvelope)
async def carteiras() -> ResponseEnvelope:
    return _ok(await svc.carteiras(Empty()))


@app.post("/carteiras", response_model=ResponseEnvelope)
async def atribuir_carteira(data: NovaCarteira) -> ResponseEnvelope:
    return _ok(await svc.atribuir_carteira(data))


@app.post("/carteiras/remover", response_model=ResponseEnvelope)
async def remover_carteira(data: CarteiraRef) -> ResponseEnvelope:
    return _ok(await svc.remover_carteira(data))


@app.get("/carteira", response_model=ResponseEnvelope)
async def carteira() -> ResponseEnvelope:
    return _ok(await svc.carteira(Empty()))


@app.get("/fila", response_model=ResponseEnvelope)
async def fila(data: Annotated[FilaQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.fila(data))


@app.post("/fila/assumir", response_model=ResponseEnvelope)
async def assumir(data: ItemRef) -> ResponseEnvelope:
    return _ok(await svc.assumir(data))


@app.post("/fila/atribuir", response_model=ResponseEnvelope)
async def atribuir(data: Atribuicao) -> ResponseEnvelope:
    return _ok(await svc.atribuir(data))


@app.get("/fila/detalhe", response_model=ResponseEnvelope)
async def detalhe(data: Annotated[ItemRef, Query()]) -> ResponseEnvelope:
    return _ok(await svc.detalhe(data))


@app.post("/fila/resolver", response_model=ResponseEnvelope)
async def resolver(data: ResolverExcecao) -> ResponseEnvelope:
    return _ok(await svc.resolver(data))


@app.post("/fila/revisao", response_model=ResponseEnvelope)
async def decidir(data: DecidirRevisao) -> ResponseEnvelope:
    return _ok(await svc.decidir(data))


@app.post("/fila/responder", response_model=ResponseEnvelope)
async def responder(data: ResponderPedido) -> ResponseEnvelope:
    return _ok(await svc.responder(data))


@app.get("/numeros", response_model=ResponseEnvelope)
async def numeros(data: Annotated[NumerosQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.numeros(data))
