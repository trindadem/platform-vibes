"""svc-financeiro · contratos (DTOs, enums, constantes). Fonte da verdade: specs/financeiro.md §2"""
from pydantic import BaseModel, Field

from core.plans import Module
from core.processes import Action

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-financeiro"
TASK_QUEUE = "financeiro-queue"

MODULE = Module("Financeiro", "Pacote de ações financeiras do BPO: contas a pagar, conciliação, cobrança e fechamento",
                category="Pacotes")


class Documento(BaseModel):
    fornecedor: str | None = Field(None, description="Razão social ou nome do fornecedor")
    cnpj: str | None = None
    valor: float | None = Field(None, description="Valor do documento, em reais")
    vencimento: str | None = Field(None, description="Data de vencimento (AAAA-MM-DD)")
    linha_digitavel: str | None = None


class Conferencia(BaseModel):
    divergente: bool = Field(..., description="O valor ou o fornecedor não batem com o pedido ou o contrato")
    diferenca: float = Field(0, description="Diferença entre o documento e o pedido, em reais")
    pedido: str | None = Field(None, description="Pedido ou contrato encontrado")
    fornecedor_novo: bool = Field(False, description="Fornecedor que a empresa nunca pagou")


class Classificacao(BaseModel):
    conta: str = Field(..., description="Conta do plano de contas")
    centro_custo: str | None = None


class Pagamento(BaseModel):
    valor: float
    vencimento: str
    linha_digitavel: str | None = None


class Agendamento(BaseModel):
    pagamento_id: str = Field(..., description="Identificador do pagamento no banco (chave do comprovante)")
    data: str = Field(..., description="Data agendada (AAAA-MM-DD)")


class Comprovante(BaseModel):
    pagamento_id: str


class Conciliacao(BaseModel):
    conciliado: bool
    diferenca: float = 0


ACTIONS = [
    Action("conferir_pedido", "Conferir com o pedido", "Compara o documento com o pedido ou o contrato e diz se diverge",
           Documento, Conferencia, risk="leitura",
           example=Conferencia(divergente=False, diferenca=0, pedido="PC-1042", fornecedor_novo=False)),
    Action("classificar", "Classificar no plano de contas", "Escolhe a conta e o centro de custo pelas regras aprendidas",
           Documento, Classificacao, risk="escrita", example=Classificacao(conta="2.1.01 Fornecedores", centro_custo="Produção")),
    Action("agendar_pagamento", "Agendar pagamento", "Agenda o pagamento no banco da empresa para o vencimento",
           Pagamento, Agendamento, risk="irreversivel", connections=("Banco",),
           example=Agendamento(pagamento_id="PG-88231", data="2026-10-15")),
    Action("conciliar", "Conciliar o comprovante", "Casa o comprovante do banco com o lançamento do pagamento",
           Comprovante, Conciliacao, risk="escrita", connections=("Banco",), example=Conciliacao(conciliado=True)),
]
