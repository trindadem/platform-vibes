"""svc-administrativo · orquestração durável. Fonte da verdade: specs/administrativo.md §3

As ações rodam como passos de processo (Camunda, core/processes.py): este pacote não tem workflow próprio.
"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule

# Tarefas recorrentes (README §5.13): nenhuma (os vencimentos são um processo com gatilho de agenda).
SCHEDULES: list[Schedule] = []
