"""svc-staff · orquestração durável. Fonte da verdade: specs/staff.md §3

As activities já existem: cada método público de StaffService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Empty, Escalados
    from service import StaffService


@workflow.defn
class EscalarWorkflow:
    """Exceção que passou do prazo sem ninguém assumir sobe para o gestor da carteira (briefing.md §5.7)."""

    @workflow.run
    async def run(self, data: Empty) -> Escalados:
        return await workflow.execute_activity_method(
            StaffService.escalar,
            data,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES: list[Schedule] = [Schedule("escalar-excecoes", "* * * * *", EscalarWorkflow.run, Empty())]
