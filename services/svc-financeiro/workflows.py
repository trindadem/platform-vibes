"""svc-financeiro · orquestração durável. Fonte da verdade: specs/financeiro.md §3

As ações rodam como passos de processo (Camunda, core/processes.py). Aqui fica o que é deste pacote e roda sozinho:
a régua de cobrança, que lembra o cliente das faturas cobradas e ainda não pagas (D-3, D+1, D+7).
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Empty, Regua
    from service import FinanceiroService


@workflow.defn
class ReguaWorkflow:
    """Todo dia: os lembretes da régua de cobrança (cada um uma vez por fatura)."""

    @workflow.run
    async def run(self, data: Empty) -> Regua:
        return await workflow.execute_activity_method(
            FinanceiroService.regua,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES: list[Schedule] = [Schedule("regua-cobranca", "0 12 * * *", ReguaWorkflow.run, Empty())]  # 9h em Brasília
