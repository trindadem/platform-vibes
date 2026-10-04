"""svc-plans · orquestração durável. Fonte da verdade: specs/plans.md §3

As activities já existem: cada método público de PlansService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Cleaned, Empty, Encerramentos, Exportacao, ExportacaoRef, Fechamento, FechamentoIn
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


@workflow.defn
class FechamentoWorkflow:
    """No dia 1: cada cliente pagante inicia o Faturamento e cobrança na organização da Cogniventure."""

    @workflow.run
    async def run(self, data: FechamentoIn) -> Fechamento:
        return await workflow.execute_activity_method(
            PlansService.fechar_mes,
            data,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn
class EncerramentosWorkflow:
    """Todo dia, logo depois da meia-noite de Brasília: encerra as contas cujo mês pago acabou e apaga as encerradas há
    30 dias."""

    @workflow.run
    async def run(self, data: Empty) -> Encerramentos:
        return await workflow.execute_activity_method(
            PlansService.encerramentos,
            data,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn
class ExportarWorkflow:
    """O pacote dos dados que o dono pediu (pode levar minutos: muitos arquivos)."""

    @workflow.run
    async def run(self, data: ExportacaoRef) -> Exportacao:
        return await workflow.execute_activity_method(
            PlansService.exportar,
            data,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


WORKFLOWS = [PlansCleanupWorkflow, FechamentoWorkflow, EncerramentosWorkflow, ExportarWorkflow]

# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES = [
    Schedule("limpeza", "30 4 * * *", PlansCleanupWorkflow.run, Empty()),  # todo dia às 4h30 (UTC)
    Schedule("encerramentos", "15 3 * * *", EncerramentosWorkflow.run, Empty()),  # todo dia às 0h15 de Brasília
    Schedule("fechamento", "0 9 1 * *", FechamentoWorkflow.run, FechamentoIn()),  # dia 1, às 6h de Brasília
]
