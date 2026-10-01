"""svc-ai · orquestração durável. Fonte da verdade: specs/ai.md §3

As activities já existem: cada método público de AiService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from schemas import Discovered, ProviderRef
    from service import AiService


@workflow.defn
class AiWorkflow:
    """Busca os modelos de um provedor em segundo plano. Disparada por events.ai.trigger."""

    @workflow.run
    async def run(self, data: ProviderRef) -> Discovered:
        return await workflow.execute_activity_method(
            AiService.discover_models,
            data,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
