"""svc-atendimento · orquestração durável. Fonte da verdade: specs/atendimento.md §3

Nada durável aqui ainda: o pedido vive no banco e o prazo de 4 h é escalonado pelo svc-staff (EscalarWorkflow).
"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot.
SCHEDULES: list[Schedule] = []
