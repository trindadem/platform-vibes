"""svc-processos · orquestração durável. Fonte da verdade: specs/processos.md §3

Neste bloco tudo é síncrono (descoberta e descrição respondem na hora); os processos aceitos ganham fluxo e execução
no desenho (bloco N3, com o Camunda). As activities já existem: cada método público de ProcessosService é registrado.
"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from core.temporal_runner import Schedule

# Tarefas recorrentes (README §5.13): nenhuma por enquanto.
SCHEDULES: list[Schedule] = []
