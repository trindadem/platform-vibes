"""svc-integracoes · orquestração durável. Fonte da verdade: specs/integracoes.md §3

As activities já existem: cada método público de IntegracoesService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Cobranca, CobrancaRef, CobrancaSimulada, Pagamento, PagamentoRef, PagamentoSimulado
    from service import IntegracoesService


@workflow.defn
class PagamentoSimuladoWorkflow:
    """O banco simulado: depois de alguns segundos, confirma o pagamento agendado (o timer sobrevive a reinícios)."""

    @workflow.run
    async def run(self, data: PagamentoSimulado) -> Pagamento:
        await workflow.sleep(timedelta(seconds=data.segundos))
        return await workflow.execute_activity_method(
            IntegracoesService.confirmar_pagamento,
            PagamentoRef(id=data.id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )


@workflow.defn
class CobrancaSimuladaWorkflow:
    """O banco simulado: depois de alguns segundos, o cliente paga a cobrança emitida (o timer sobrevive a reinícios)."""

    @workflow.run
    async def run(self, data: CobrancaSimulada) -> Cobranca:
        await workflow.sleep(timedelta(seconds=data.segundos))
        return await workflow.execute_activity_method(
            IntegracoesService.confirmar_cobranca,
            CobrancaRef(id=data.id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )


SCHEDULES: list[Schedule] = []
