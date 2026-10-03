"""svc-staff · contratos (DTOs, enums, constantes). Fonte da verdade: specs/staff.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings

from core.plans import Module
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-staff"
TASK_QUEUE = "staff-queue"
STAFF_SUBJECT = "events.processos.staff"  # do svc-processos: o que espera o staff numa organização
OPERADOR_SUBJECT = "rpc.identity.operador"  # svc-identity: a carteira dá ou tira o papel operador
ORGANIZACOES_SUBJECT = "rpc.identity.organizacoes"  # svc-identity: as organizações clientes
ACOMPANHAMENTO_SUBJECT = "rpc.processos.acompanhamento"  # svc-processos: a saúde de uma organização
LIVE_FILA = "staff.fila"
LIVE_CARTEIRAS = "staff.carteiras"

CARTEIRAS = "staff_carteiras"
FILA = "staff_fila"
TABLES = [CARTEIRAS, FILA]
UNIQUE = {CARTEIRAS: ["pessoa", "organizacao"], FILA: ["chave"]}
GESTORES = frozenset({"owner", "admin"})  # gestor da carteira: dono ou admin da organização da Cogniventure

# Área da equipe da Cogniventure: desligada para os clientes; o plano da organização da plataforma a liga.
MODULE = Module("Staff", "Área da equipe da Cogniventure: carteira de clientes, exceções, revisões e pedidos de ajuda",
                category="Cogniventure", default=False)


class StaffSettings(BaseSettings):
    platform_tenant: str | None = Field(None, description="A organização da Cogniventure: quem é dela é staff")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _key(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


# ── Carteira: quem do staff cuida de qual organização ────────────────────────

class Carteira(BaseModel):
    id: str
    pessoa: str = Field(..., description="Id da pessoa do staff")
    organizacao: str
    organizacao_nome: str
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class Carteiras(BaseModel):
    itens: list[Carteira]


class NovaCarteira(_Input):
    pessoa: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    organizacao: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class CarteiraRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class CarteiraMudou(BaseModel):
    id: str
    action: Literal["atribuida", "removida"]


class Organizacao(BaseModel):
    id: str
    name: str
    created_at: datetime | None = None


class Organizacoes(BaseModel):
    items: list[Organizacao]


class OperadorAcesso(BaseModel):
    user: str
    tenant: str
    ativo: bool


class OperadorResultado(BaseModel):
    user: str
    tenant: str
    roles: list[str]


# ── Fila: o que espera o staff nas organizações da carteira ─────────────────

TipoItem = Literal["excecao", "revisao", "ajuda"]


class ItemStaff(BaseModel):
    """events.processos.staff (contrato do svc-processos, repetido aqui por quem consome)."""

    tipo: TipoItem
    ref: str
    titulo: str
    detalhe: str | None = None
    prazo: datetime | None = None
    status: Literal["aberta", "concluida"]
    link: str
    em: datetime


class ItemFila(BaseModel):
    id: str
    organizacao: str
    organizacao_nome: str
    tipo: TipoItem
    ref: str
    titulo: str
    detalhe: str | None = None
    prazo: datetime | None = None
    status: Literal["aberta", "concluida"]
    link: str = Field(..., description="Onde resolver, na tela da organização (entre nela antes)")
    assumida_por: str | None = None
    atribuida_a: str | None = None
    escalada: bool = Field(False, description="Passou do prazo sem ninguém assumir: subiu para o gestor da carteira")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class FilaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("prazo", "created_at")
    default_sort: ClassVar[str | None] = "prazo"
    tipo: TipoItem | None = None
    status: Literal["aberta", "concluida"] | None = None
    escalada: bool | None = None
    todas: bool | None = Field(None, description="Gestor: a fila de todas as carteiras (não é filtro do banco)")
    organizacao: list[str] | None = None


class FilaPage(Page[ItemFila]):
    pass


class ItemRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Atribuicao(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    pessoa: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class FilaMudou(BaseModel):
    id: str
    action: Literal["chegou", "mudou", "escalada"]


class Escalados(BaseModel):
    itens: int


# ── Saúde dos clientes da carteira ───────────────────────────────────────────

class Acompanhamento(BaseModel):
    """rpc.processos.acompanhamento (contrato do svc-processos, só o que a carteira usa)."""

    model_config = ConfigDict(extra="ignore")

    andamento: int
    concluidas: int
    incidentes: int
    tarefas_cliente: int
    tarefas_staff: int
    atrasadas: int
    autonomia: float | None = None


class Saude(BaseModel):
    organizacao: str
    nome: str
    andamento: int | None = None
    concluidas: int | None = None
    incidentes: int | None = None
    autonomia: float | None = None
    excecoes: int = Field(0, description="Exceções abertas na fila")
    revisoes: int = 0
    ajudas: int = 0
    disponivel: bool = Field(True, description="Falso quando a organização não respondeu agora")


class MinhaCarteira(BaseModel):
    gestor: bool
    itens: list[Saude]


class Resumo(BaseModel):
    staff: bool = Field(..., description="Quem pergunta é da equipe da Cogniventure")
    gestor: bool
    excecoes: int = 0
    atrasadas: int = 0
    escaladas: int = 0
    revisoes: int = 0
    ajudas: int = 0
    organizacoes: int = 0
