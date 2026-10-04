"""svc-integracoes · orquestração durável. Fonte da verdade: specs/integracoes.md §3

As activities já existem: cada método público de IntegracoesService é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule
    from schemas import Cobranca, CobrancaRef, CobrancaSimulada, Documento, LeituraDocumento, Pagamento, PagamentoRef, PagamentoSimulado
    from service import IntegracoesService


@workflow.defn
class PagamentoSimuladoWorkflow:
    """O banco simulado: depois de alguns segundos, confirma o pagamento agendado (o timer sobrevive a reinícios)."""

    @workflow.run
    async def run(self, data: PagamentoSimulado) -> Pagamento:
        await workflow.sleep(timedelta(seconds=data.segundos))
        return await workflow.execute_activity_method(
            IntegracoesService.confirmar_pagamento,
            PagamentoRef(id=data.id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )


@workflow.defn
class CobrancaSimuladaWorkflow:
    """O banco simulado: depois de alguns segundos, o cliente paga a cobrança emitida (o timer sobrevive a reinícios)."""

    @workflow.run
    async def run(self, data: CobrancaSimulada) -> Cobranca:
        await workflow.sleep(timedelta(seconds=data.segundos))
        return await workflow.execute_activity_method(
            IntegracoesService.confirmar_cobranca,
            CobrancaRef(id=data.id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )


@workflow.defn
class LeituraDocumentoWorkflow:
    """Foto ou PDF escaneado: o modelo de visão escreve o texto do documento e então os processos são avisados. A leitura
    não derruba o recebimento: falha do modelo vira documento sem texto (o agente pede ajuda ao staff)."""

    @workflow.run
    async def run(self, data: LeituraDocumento) -> Documento:
        try:
            return await workflow.execute_activity_method(
                IntegracoesService.ler_documento,
                data,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5)),
            )
        except ActivityError:  # não deu para ler: segue sem texto, e os processos são avisados mesmo assim
            return await workflow.execute_activity_method(
                IntegracoesService.desistir_leitura,
                data,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )


SCHEDULES: list[Schedule] = []
