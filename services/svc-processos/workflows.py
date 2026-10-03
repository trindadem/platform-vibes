"""svc-processos · orquestração durável. Fonte da verdade: specs/processos.md §3

O processo do cliente roda no Camunda (core/processes.py); aqui fica só o que é deste serviço e precisa sobreviver a
reinícios: a avaliação de uma regra que o staff ensinou (o agente refaz o caso com ela, o que leva alguns segundos).
As activities já existem: cada método público de ProcessosService é registrado.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Regra, RegraRef
    from service import ProcessosService


@workflow.defn
class AvaliarRegraWorkflow:
    """A regra nova entra no agente do passo só se passar: com ela, o agente refaz o caso que a gerou."""

    @workflow.run
    async def run(self, data: RegraRef) -> Regra:
        return await workflow.execute_activity_method(
            ProcessosService.avaliar_regra,
            data,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): nenhuma por enquanto.
SCHEDULES: list[Schedule] = []
