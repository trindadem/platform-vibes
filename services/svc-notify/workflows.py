"""svc-notify · orquestração durável. Fonte da verdade: specs/notify.md §3

As activities já existem: cada método público de NotifyService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import EMAIL_ATTEMPTS, Cleaned, EmailRef, EmailResult, Empty, Outgoing, Prepared
    from service import NotifyService

_EMAIL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=EMAIL_ATTEMPTS,
)


@workflow.defn
class NotifyWorkflow:
    """Um aviso: grava e avisa ao vivo, depois envia cada e-mail com retentativas. Disparada por events.notify.send."""

    @workflow.run
    async def run(self, data: Outgoing) -> Prepared:
        prepared = await workflow.execute_activity_method(
            NotifyService.deliver,
            data,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        await asyncio.gather(*(self._send(email) for email in prepared.emails))
        return prepared

    async def _send(self, email: str) -> EmailResult:
        ref = EmailRef(id=email)
        try:
            return await workflow.execute_activity_method(
                NotifyService.send_email, ref, start_to_close_timeout=timedelta(minutes=1), retry_policy=_EMAIL_RETRY
            )
        except ActivityError:  # tentativas esgotadas: fica registrado como falha
            return await workflow.execute_activity_method(
                NotifyService.give_up, ref, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=5)
            )


@workflow.defn
class NotifyCleanupWorkflow:
    """Apaga avisos lidos antigos e registros de e-mail antigos. Todo dia (SCHEDULES)."""

    @workflow.run
    async def run(self, data: Empty) -> Cleaned:
        return await workflow.execute_activity_method(
            NotifyService.cleanup,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES = [Schedule("limpeza", "30 4 * * *", NotifyCleanupWorkflow.run, Empty())]  # todo dia às 4h30 (UTC)
