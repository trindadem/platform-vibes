"""svc-conhecimento · orquestração durável. Fonte da verdade: specs/conhecimento.md §3

As activities já existem: cada método público de ConhecimentoService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import LeituraFalha, LeituraPedido, LeituraRef
    from service import ConhecimentoService


@workflow.defn
class LeituraWorkflow:
    """Lê o site ou o documento e grava os itens; tentativas esgotadas deixam a leitura como falhou, com o motivo."""

    @workflow.run
    async def run(self, data: LeituraPedido) -> None:
        ler = ConhecimentoService.ler_site if data.tipo == "site" else ConhecimentoService.ler_documento
        try:
            await workflow.execute_activity_method(
                ler,
                LeituraRef(id=data.id),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
            )
        except ActivityError as exc:
            cause = exc.cause
            motivo = cause.message if isinstance(cause, ApplicationError) and cause.non_retryable else (
                "Não foi possível ler agora. Tente de novo em alguns minutos."
            )
            await workflow.execute_activity_method(
                ConhecimentoService.falhou,
                LeituraFalha(id=data.id, erro=motivo[:300]),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )


# Tarefas recorrentes (README §5.13): nenhuma por enquanto.
SCHEDULES: list[Schedule] = []
