"""svc-plans · contratos (DTOs, enums, constantes). Fonte da verdade: specs/plans.md §2"""
from datetime import datetime
from typing import Annotated, Any, Literal

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
    CatalogModule,
    CountReport,
    LimitsRequest,
    LimitState,
    Module,
    ModuleCatalog,
    ModuleName,
    ModuleState,
    PlanLimits,
    PlanSlug,
    Situacao,
    UsageReport,
)
from core.surreal import PURGE_SUBJECT, PurgeRequest  # a organização que sai: cada serviço apaga o que é dela

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-plans"
TASK_QUEUE = "plans-queue"
USAGE_LIVE = "plans.uso"  # ao vivo para a organização quando um consumo ou um total muda (README §5.10)

# Catálogo (módulos e limites), planos e o plano de cada organização (org = id dela) valem para a plataforma: quem a
# administra precisa saber se um plano está em uso. Consumo e totais são de cada organização.
LIMIT_CATALOG = "plan_limits"
MODULE_CATALOG = "plan_modules"
TIERS = "plan_tiers"
ACCOUNTS = "plan_accounts"
USAGE = "plan_usage"
USAGE_LOG = "plan_usage_log"
COUNTS = "plan_counts"
EXPORTS = "plan_exports"  # por organização: o pacote dos dados que o dono baixa
SHARED_TABLES = [LIMIT_CATALOG, MODULE_CATALOG, TIERS, ACCOUNTS]
TENANT_TABLES = [USAGE, USAGE_LOG, COUNTS, EXPORTS]
UNIQUE = {TIERS: ["slug"], ACCOUNTS: ["org"], USAGE: ["name", "month"], USAGE_LOG: ["message"], COUNTS: ["name"]}

# Ciclo de vida da conta (alinhamento pós-N7, itens 2 e 13)
CONTA_SUBJECT = "rpc.plans.conta"  # svc-staff, agindo no cliente: mensalidade, vencimento, suspensão e encerramento
ENCERRADA_SUBJECT = "events.plans.encerrada"  # a conta encerrou: cada serviço desliga o que é da organização
INICIAR_MODELO_SUBJECT = "rpc.processos.iniciar_modelo"  # o fechamento inicia o faturamento na Cogniventure
FATURAMENTO_MODELO = "faturamento-cobranca"
STAFF_SERVICE = "svc-staff"
VENCIMENTO_PADRAO = 10  # dia do mês em que a mensalidade vence, se ninguém disse outro
DIAS_ATE_EXCLUIR = 30  # depois do encerramento, os dados ficam este tempo (o dono baixa e pode reativar)
FUSO = "America/Sao_Paulo"  # o mês pago acaba à meia-noite de Brasília
EXPORT_FILE_BYTES = 100_000_000  # arquivo maior que isso vai listado no LEIA-ME, sem o conteúdo

MANAGERS = frozenset({"owner", "admin"})
ALERTS = (100, 80)  # patamares de aviso dos limites mensais, em % (do maior para o menor)
KEEP_LOG_DAYS = 45
KEEP_MONTHS = 13
NO_PLAN = "Sem plano"

LimitName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$", max_length=81)]
LimitValue = Annotated[float, Field(ge=0)]
Currency = Literal["BRL", "USD", "EUR"]  # as moedas que a tela formata (Money)
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


# O próprio módulo (README §5.17): da plataforma, sempre ligado.
MODULE = Module("Plano", "Plano, módulos e consumo da organização", category="Organização", core=True)


class PlansSettings(BaseSettings):
    platform_tenant: str | None = Field(None, description="Organização que administra a plataforma (gerencia os planos)")
    modules: str = Field("", description="Módulos de negócio instalados, separados por vírgula (vazio: todos do catálogo)")

    def installed(self) -> frozenset[str] | None:
        """None: todos os módulos do catálogo valem (instalação compartilhada)."""
        chosen = frozenset(m.strip() for m in self.modules.split(",") if m.strip())
        return chosen or None


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
    modules: dict[str, bool] = Field(..., description="Módulo → incluído; o que falta vale o default do módulo")


class PlanInput(_Input):
    slug: PlanSlug = Field(..., description="Identificador curto e permanente (ex.: gratis, pro)")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    price: float = Field(0, ge=0, description="Preço por mês, informativo")
    currency: Currency = "BRL"
    public: bool = True
    default: bool = False
    limits: dict[LimitName, LimitValue | None] = Field(default_factory=dict, description="Limite → valor (null: sem limite)")
    modules: dict[ModuleName, bool] = Field(default_factory=dict, description="Módulo → incluído (o que falta vale o default)")


class PlanUpdate(_Input):
    slug: PlanSlug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    price: float | None = Field(None, ge=0)
    currency: Currency | None = None
    public: bool | None = None
    default: bool | None = None
    limits: dict[LimitName, LimitValue | None] | None = Field(None, description="Substitui a lista inteira")
    modules: dict[ModuleName, bool] | None = Field(None, description="Substitui a lista inteira")


class PlanRef(_Input):
    slug: PlanSlug


class PlanList(BaseModel):
    items: list[Plan]
    current: str | None = Field(..., description="Slug do plano da organização ativa (null: sem plano)")
    manages_platform: bool = Field(..., description="Quem pede administra os planos da plataforma")


class Catalog(BaseModel):
    """O que os serviços declararam: os módulos (por categoria) e os limites."""

    modules: list[CatalogModule]
    limits: list[CatalogLimit]


class ModuleList(BaseModel):
    """Os módulos da plataforma e se cada um está ligado para a organização ativa (o menu esconde os desligados)."""

    items: list[ModuleState]


class Current(BaseModel):
    tenant: str = Field(..., description="Id da organização: quem administra a plataforma atribui o plano por ele")
    plan: Plan | None = Field(..., description="Plano em vigor (atribuído ou o padrão); null: sem plano")
    month: str = Field(..., description="AAAA-MM, em UTC: o mês dos consumos")
    limits: list[LimitState]
    modules: list[ModuleState]
    manages_platform: bool
    conta: "Conta" = Field(..., description="Mensalidade, situação e cancelamento da organização")


class AssignInput(_Input):
    tenant: Id = Field(..., description="Id da organização (aparece para ela na tela Plano)")
    plan: PlanSlug
    modules: dict[ModuleName, bool] | None = Field(
        None, description="Ajuste da organização: módulo → ligado, além do plano. null: mantém o ajuste; {}: só o plano"
    )


class AccountRef(_Input):
    tenant: Id


class Account(BaseModel):
    tenant: str
    tenant_name: str
    plan: str | None = Field(..., description="Plano em vigor (atribuído ou o padrão); null: sem plano")
    plan_name: str
    assigned: bool = Field(..., description="O plano foi atribuído (false: vale o padrão)")
    modules: dict[str, bool] = Field(..., description="Ajuste da organização além do plano: módulo → ligado")


class UsageChanged(BaseModel):
    """Consumo ou total que mudou (também vai ao vivo para a tela da organização)."""

    name: str
    used: float


class Cleaned(BaseModel):
    usage_log: int
    usage: int


# ── Conta: mensalidade, situação e cancelamento (alinhamento pós-N7, itens 2 e 13) ──

class Cancelamento(BaseModel):
    pedido_em: datetime
    por: str | None = Field(None, description="Id de quem pediu")
    origem: Literal["cliente", "cogniventure"]
    motivo: str | None = None
    efetivo_em: datetime = Field(..., description="Quando a conta encerra: o fim do mês pago (meia-noite de Brasília)")


class Conta(BaseModel):
    tenant: str
    situacao: Situacao
    valor: float = Field(..., description="Mensalidade cobrada no fechamento: a combinada com o cliente ou o preço do plano")
    valor_combinado: bool = Field(..., description="A Cogniventure combinou um valor só deste cliente")
    moeda: Currency
    vencimento: int = Field(..., description="Dia do mês em que a mensalidade vence")
    suspensa_em: datetime | None = None
    motivo: str | None = Field(None, description="Por que foi suspensa")
    cancelamento: Cancelamento | None = None
    encerrada_em: datetime | None = None
    exclusao_em: datetime | None = Field(None, description="Quando os dados saem de vez (30 dias depois do encerramento)")
    aviso: str | None = Field(None, description="O que a organização vê no workspace e em Plano")
    pode_desfazer: bool = Field(False, description="O dono desfaz o cancelamento que pediu (até a exclusão)")


class ContaAcao(BaseModel):
    """rpc.plans.conta (só o svc-staff, agindo na organização do cliente): ver, mudar a mensalidade e o vencimento,
    suspender, reativar, encerrar ou desfazer o encerramento."""

    acao: Literal["ver", "cobranca", "suspender", "reativar", "encerrar", "desfazer"]
    valor: float | None = Field(None, ge=0, description="cobranca: a mensalidade combinada (null: mantém)")
    vencimento: int | None = Field(None, ge=1, le=28, description="cobranca: o dia do vencimento (null: mantém)")
    motivo: str | None = Field(None, max_length=300)
    por: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Quem do staff agiu")


class CancelamentoIn(_Input):
    motivo: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class FechamentoIn(_Input):
    mes: str | None = Field(None, pattern=r"^\d{4}-\d{2}$", description="AAAA-MM (vazio: o mês atual)")


class Cobrado(BaseModel):
    tenant: str
    nome: str
    valor: float
    vencimento: str = Field(..., description="AAAA-MM-DD")
    execucao: str | None = Field(None, description="A execução do Faturamento e cobrança na Cogniventure")
    erro: str | None = None


class Fechamento(BaseModel):
    mes: str
    cobrados: list[Cobrado]


class Encerramentos(BaseModel):
    encerradas: int
    excluidas: int


class ContaEncerrada(BaseModel):
    """events.plans.encerrada, publicado como a organização: cada serviço desliga o que é dela (carteira do staff,
    conexões, webhooks, chaves de IA)."""

    tenant: str
    em: datetime


class Exportacao(BaseModel):
    id: str
    status: Literal["preparando", "pronta", "falhou"]
    created_at: datetime | None = None
    pronta_em: datetime | None = None
    tamanho: int | None = Field(None, description="Bytes do pacote")
    url: str | None = Field(None, description="Link para baixar (10 min), quando pronta")
    aviso: str | None = Field(None, description="O que ficou de fora (um serviço fora do ar) ou por que falhou")


class ExportacaoAtual(BaseModel):
    item: Exportacao | None = None


class ExportacaoRef(BaseModel):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class IniciarModelo(BaseModel):
    """rpc.processos.iniciar_modelo: inicia o processo publicado deste modelo na organização de quem pede."""

    modelo: str
    dados: dict[str, Any]
    chave: str = Field(..., description="A mesma chave não inicia duas vezes")
    resumo: str | None = None


class ExecucaoIniciada(BaseModel):
    id: str
    processo: str
    titulo: str


Current.model_rebuild()
