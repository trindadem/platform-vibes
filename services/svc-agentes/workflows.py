"""svc-agentes · orquestração durável. Fonte da verdade: specs/agentes.md §3

As activities já existem: cada método público de AgentesService é registrado sozinho (core/temporal_runner.py). Aqui
só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Agente, SuiteRef
    from service import AgentesService


@workflow.defn
class AvaliarSuiteWorkflow:
    """A suíte de um agente: cada caso roda o agente de verdade (leva de segundos a minutos). Sem terminar, o agente
    sai da avaliação com o motivo, para não ficar preso."""

    @workflow.run
    async def run(self, data: SuiteRef) -> Agente:
        try:
            return await workflow.execute_activity_method(
                AgentesService.rodar_suite,
                data,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except ActivityError:
            return await workflow.execute_activity_method(
                AgentesService.encerrar_suite,
                data,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )


# Tarefas recorrentes (README §5.13): nenhuma por enquanto.
SCHEDULES: list[Schedule] = []
