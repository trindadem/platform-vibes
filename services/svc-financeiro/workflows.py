"""svc-financeiro · orquestração durável. Fonte da verdade: specs/financeiro.md §3

Sem workflows neste bloco: as ações rodam como passos de processo (Camunda), a partir do N4.
"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule

SCHEDULES: list[Schedule] = []
