"""svc-financeiro · contratos (DTOs, enums, constantes). Fonte da verdade: specs/financeiro.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from core.plans import Module
from core.processes import Action
from core.resources import Fields, Money, Resource
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-financeiro"
TASK_QUEUE = "financeiro-queue"
AGENDAR_SUBJECT = "rpc.integracoes.banco_agendar"  # o banco da organização (svc-integracoes)
TITULOS = "financeiro_titulos"
TABLES = [TITULOS]
UNIQUE = {TITULOS: ["pagamento_id"]}
CONTA_PADRAO = "2.1.01 Fornecedores"
LIVE_TITULOS = "financeiro.titulos"

MODULE = Module("Financeiro", "Pacote de ações financeiras do BPO: contas a pagar, conciliação, cobrança e fechamento",
                category="Pacotes")


# Cadastro (README §5.19): os fornecedores que a empresa paga. A conferência usa o valor do contrato e a
# classificação usa a conta; fornecedor que não está aqui é "novo" (e entra aqui ao ser classificado).
class Fornecedor(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="Nome")
    cnpj: str | None = Field(None, max_length=20, title="CNPJ")
    conta: str = Field(CONTA_PADRAO, min_length=2, max_length=80, title="Conta do plano de contas")
    centro_custo: str | None = Field(None, max_length=80, title="Centro de custo")
    valor_contrato: Money | None = Field(None, title="Valor do contrato", description="Mensal; documento com outro valor diverge")


FORNECEDORES = Resource(SERVICE, "fornecedores", Fornecedor, "Fornecedores", search=("nome", "cnpj"), sort=("nome",),
                        unique=("nome",), write=("owner", "admin", "operador"))
RESOURCES = [FORNECEDORES]


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
    fornecedor: str | None = None
    linha_digitavel: str | None = None


class Agendamento(BaseModel):
    pagamento_id: str = Field(..., description="Identificador do pagamento no banco (chave do comprovante)")
    data: str = Field(..., description="Data agendada (AAAA-MM-DD)")


class Comprovante(BaseModel):
    pagamento_id: str


class Conciliacao(BaseModel):
    conciliado: bool
    diferenca: float = 0


# Do svc-integracoes (rpc.integracoes.banco_agendar): o contrato repetido aqui, de quem consome.
class AgendarPagamento(BaseModel):
    valor: float
    vencimento: str | None = None
    fornecedor: str | None = None
    linha_digitavel: str | None = None


class PagamentoAgendado(BaseModel):
    pagamento_id: str
    data: str


class Titulo(BaseModel):
    """Uma conta a pagar que o processo agendou: do agendamento à conciliação."""

    id: str
    fornecedor: str | None = None
    valor: float
    vencimento: str | None = None
    data: str = Field(..., description="Data agendada no banco")
    pagamento_id: str
    status: Literal["agendado", "pago"]
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class TituloQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "data", "valor")
    default_sort: ClassVar[str | None] = "-created_at"
    status: Literal["agendado", "pago"] | None = None


class TituloPage(Page[Titulo]):
    pass


class TituloMudou(BaseModel):
    id: str
    action: Literal["agendado", "pago"]


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
