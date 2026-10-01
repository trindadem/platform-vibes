"""svc-financeiro · lógica de negócio pura. Fonte da verdade: specs/financeiro.md §3

Neste bloco o pacote só declara as ações (schemas.ACTIONS); a execução delas pelo motor de processos entra no N4,
como métodos públicos aqui (cada um vira activity e, então, worker do Camunda).
"""
from core.surreal import Migration
from core.temporal_runner import activities

MIGRATIONS: list[Migration] = []


@activities("financeiro")
class FinanceiroService:
    pass
