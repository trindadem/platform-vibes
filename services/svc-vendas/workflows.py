"""svc-vendas · orquestração durável. Fonte da verdade: specs/vendas.md §3

As ações rodam como passos de processo (Camunda, core/processes.py). Aqui fica o que é deste pacote e roda sozinho:
os follow-ups das propostas enviadas que ainda não tiveram resposta.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Empty, FollowUps
    from service import VendasService


@workflow.defn
class FollowUpWorkflow:
    """Todo dia: proposta enviada e sem resposta há 3 e há 7 dias recebe um follow-up (cada um uma vez)."""

    @workflow.run
    async def run(self, data: Empty) -> FollowUps:
        return await workflow.execute_activity_method(
            VendasService.follow_up,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES: list[Schedule] = [Schedule("follow-up-propostas", "0 13 * * *", FollowUpWorkflow.run, Empty())]  # 10h em Brasília
