"""svc-integracoes · orquestração durável. Fonte da verdade: specs/integracoes.md §3

As activities já existem: cada método público de IntegracoesService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Pagamento, PagamentoRef, PagamentoSimulado
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


SCHEDULES: list[Schedule] = []
