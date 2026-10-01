"""svc-webhooks · orquestração durável. Fonte da verdade: specs/webhooks.md §3

As activities já existem: cada método público de WebhooksService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import ATTEMPTS, TIMEOUT_SECONDS, Cleaned, DeliveryChanged, DeliveryRef, Empty, Outgoing, Planned
    from service import WebhooksService

# 5 s, 20 s, 80 s, 5 min, 21 min, 85 min e depois 5 h entre tentativas (cerca de 15 h ao todo).
_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=4.0,
    maximum_interval=timedelta(hours=5),
    maximum_attempts=ATTEMPTS,
)


async def _deliver(delivery: str) -> DeliveryChanged:
    ref = DeliveryRef(id=delivery)
    try:
        return await workflow.execute_activity_method(
            WebhooksService.deliver, ref, start_to_close_timeout=timedelta(seconds=TIMEOUT_SECONDS + 30), retry_policy=_RETRY
        )
    except ActivityError:  # tentativas esgotadas
        return await workflow.execute_activity_method(
            WebhooksService.give_up, ref, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=5)
        )


@workflow.defn
class WebhooksWorkflow:
    """Um evento: uma entrega por endereço inscrito, cada uma com suas tentativas. Disparada por events.webhooks.emit."""

    @workflow.run
    async def run(self, data: Outgoing) -> Planned:
        planned = await workflow.execute_activity_method(
            WebhooksService.fan_out, data, start_to_close_timeout=timedelta(minutes=1), retry_policy=RetryPolicy(maximum_attempts=5)
        )
        await asyncio.gather(*(_deliver(delivery) for delivery in planned.deliveries))
        return planned


@workflow.defn
class RedeliverWorkflow:
    """Reenviar pela tela: a mesma entrega, de novo com todas as tentativas. Disparada por events.webhooks.retry."""

    @workflow.run
    async def run(self, data: DeliveryRef) -> DeliveryChanged:
        return await _deliver(data.id)


@workflow.defn
class WebhooksCleanupWorkflow:
    """Apaga entregas concluídas com mais de 30 dias. Todo dia (SCHEDULES)."""

    @workflow.run
    async def run(self, data: Empty) -> Cleaned:
        return await workflow.execute_activity_method(
            WebhooksService.cleanup, data, start_to_close_timeout=timedelta(minutes=5), retry_policy=RetryPolicy(maximum_attempts=3)
        )


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES = [Schedule("limpeza", "45 4 * * *", WebhooksCleanupWorkflow.run, Empty())]  # todo dia às 4h45 (UTC)
