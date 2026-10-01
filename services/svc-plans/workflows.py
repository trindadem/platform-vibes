"""svc-plans · orquestração durável. Fonte da verdade: specs/plans.md §3

As activities já existem: cada método público de PlansService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Cleaned, Empty
    from service import PlansService


@workflow.defn
class PlansCleanupWorkflow:
    """Apaga linhas de consumo com mais de 45 dias e somas com mais de 13 meses. Todo dia (SCHEDULES)."""

    @workflow.run
    async def run(self, data: Empty) -> Cleaned:
        return await workflow.execute_activity_method(
            PlansService.cleanup,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES = [Schedule("limpeza", "30 4 * * *", PlansCleanupWorkflow.run, Empty())]  # todo dia às 4h30 (UTC)
