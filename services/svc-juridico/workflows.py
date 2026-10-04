"""svc-juridico · orquestração durável. Fonte da verdade: specs/juridico.md §3

As ações rodam como passos de processo (Camunda, core/processes.py). Aqui fica o que é deste pacote e roda sozinho:
os avisos antes de um contrato vencer (ou reajustar) e antes de uma certidão perder a validade.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Avisos, Empty
    from service import JuridicoService


@workflow.defn
class AvisosWorkflow:
    """Todo dia: contratos a 60 e a 30 dias do fim ou do reajuste, certidões a 15 dias da validade."""

    @workflow.run
    async def run(self, data: Empty) -> Avisos:
        return await workflow.execute_activity_method(
            JuridicoService.avisar,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES: list[Schedule] = [Schedule("avisos-juridicos", "0 11 * * *", AvisosWorkflow.run, Empty())]  # 8h em Brasília
