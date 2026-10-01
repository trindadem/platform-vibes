"""svc-plans · contratos (DTOs, enums, constantes). Fonte da verdade: specs/plans.md §2"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic_settings import BaseSettings

from core.notify import CONTACTS_SUBJECT, Contacts, ContactsRequest  # o nome da organização vem do svc-identity
from core.plans import (  # contrato com core/plans.py
    ASSIGN_SUBJECT,
    CATALOG_SUBJECT,
    COUNT_SUBJECT,
    LIMITS_SUBJECT,
    USAGE_SUBJECT,
    Assigned,
    AssignRequest,
    CatalogLimit,
    CountReport,
    LimitCatalog,
    LimitsRequest,
    LimitState,
    PlanLimits,
    PlanSlug,
    UsageReport,
)

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-plans"
TASK_QUEUE = "plans-queue"
USAGE_LIVE = "plans.uso"  # ao vivo para a organização quando um consumo ou um total muda (README §5.10)

# Catálogo, planos e o plano de cada organização (org = id dela) valem para a plataforma: quem a administra precisa
# saber se um plano está em uso. Consumo e totais são de cada organização.
LIMITS = "plan_limits"
TIERS = "plan_tiers"
ACCOUNTS = "plan_accounts"
USAGE = "plan_usage"
USAGE_LOG = "plan_usage_log"
COUNTS = "plan_counts"
SHARED_TABLES = [LIMITS, TIERS, ACCOUNTS]
TENANT_TABLES = [USAGE, USAGE_LOG, COUNTS]
UNIQUE = {TIERS: ["slug"], ACCOUNTS: ["org"], USAGE: ["name", "month"], USAGE_LOG: ["message"], COUNTS: ["name"]}

MANAGERS = frozenset({"owner", "admin"})
ALERTS = (100, 80)  # patamares de aviso dos limites mensais, em % (do maior para o menor)
KEEP_LOG_DAYS = 45
KEEP_MONTHS = 13
NO_PLAN = "Sem plano"

LimitName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$", max_length=81)]
LimitValue = Annotated[float, Field(ge=0)]
Currency = Literal["BRL", "USD", "EUR"]  # as moedas que a tela formata (Money)
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class PlansSettings(BaseSettings):
    platform_tenant: str | None = Field(None, description="Organização que administra a plataforma (gerencia os planos)")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


class Plan(BaseModel):
    slug: str
    name: str
    description: str = ""
    price: float = Field(..., description="Preço por mês, informativo (a cobrança é do produto)")
    currency: Currency = Field(..., description="Moeda do preço")
    public: bool = Field(..., description="Aparece para as organizações na comparação de planos")
    default: bool = Field(..., description="Plano de quem ainda não tem um atribuído")
    limits: dict[str, float | None] = Field(..., description="Limite → valor (null: sem limite); o que falta vale o default")


class PlanInput(_Input):
    slug: PlanSlug = Field(..., description="Identificador curto e permanente (ex.: gratis, pro)")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    price: float = Field(0, ge=0, description="Preço por mês, informativo")
    currency: Currency = "BRL"
    public: bool = True
    default: bool = False
    limits: dict[LimitName, LimitValue | None] = Field(default_factory=dict, description="Limite → valor (null: sem limite)")


class PlanUpdate(_Input):
    slug: PlanSlug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    price: float | None = Field(None, ge=0)
    currency: Currency | None = None
    public: bool | None = None
    default: bool | None = None
    limits: dict[LimitName, LimitValue | None] | None = Field(None, description="Substitui a lista inteira")


class PlanRef(_Input):
    slug: PlanSlug


class PlanList(BaseModel):
    items: list[Plan]
    current: str | None = Field(..., description="Slug do plano da organização ativa (null: sem plano)")
    manages_platform: bool = Field(..., description="Quem pede administra os planos da plataforma")


class LimitList(BaseModel):
    items: list[CatalogLimit]


class Current(BaseModel):
    tenant: str = Field(..., description="Id da organização: quem administra a plataforma atribui o plano por ele")
    plan: Plan | None = Field(..., description="Plano em vigor (atribuído ou o padrão); null: sem plano")
    month: str = Field(..., description="AAAA-MM, em UTC: o mês dos consumos")
    limits: list[LimitState]
    manages_platform: bool


class AssignInput(_Input):
    tenant: Id = Field(..., description="Id da organização (aparece para ela na tela Plano)")
    plan: PlanSlug


class Account(BaseModel):
    tenant: str
    tenant_name: str
    plan: str
    plan_name: str


class UsageChanged(BaseModel):
    """Consumo ou total que mudou (também vai ao vivo para a tela da organização)."""

    name: str
    used: float


class Cleaned(BaseModel):
    usage_log: int
    usage: int
