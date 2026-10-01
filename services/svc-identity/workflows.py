"""svc-identity · orquestração durável. Fonte da verdade: specs/identity.md §3

As activities já existem: cada método público de IdentityService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from schemas import Cleaned, Empty
    from service import IdentityService


@workflow.defn
class IdentityWorkflow:
    """Limpeza: apaga sessões e convites vencidos. Disparada por events.identity.trigger."""

    @workflow.run
    async def run(self, data: Empty) -> Cleaned:
        return await workflow.execute_activity_method(
            IdentityService.cleanup,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
