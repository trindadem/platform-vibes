"""svc-ai · contratos (DTOs, enums, constantes). Fonte da verdade: specs/ai.md §2"""
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from pydantic_settings import BaseSettings

from core.llm import RESOLVE_SUBJECT, USAGE_SUBJECT, Resolved, ResolveRequest, UsageEvent  # contrato com core/llm.py
from core.plans import Limit, Module
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-ai"
TASK_QUEUE = "ai-queue"
TRIGGER_SUBJECT = "events.ai.trigger"
USAGE_LIVE = "ai.uso"  # ao vivo para a organização a cada uso gravado (README §5.10)

# Tabelas: provedores e modelos são globais (owner = organização ou "platform"); uso é por organização.
PROVIDERS = "ai_providers"
MODELS = "ai_models"
USAGE = "ai_usage"
SHARED_TABLES = [PROVIDERS, MODELS]
TENANT_TABLES = [USAGE]
UNIQUE = {PROVIDERS: ["owner", "slug"], MODELS: ["owner", "provider", "model_id"], USAGE: ["message"]}
SEARCH = {MODELS: ["model_id", "alias"]}  # busca por palavras na lista de modelos (README §5.12)
PLATFORM = "platform"
MANAGERS = frozenset({"owner", "admin"})

# O módulo (README §5.17), da plataforma. Limites somados aqui a cada uso gravado; o core/llm.py confere antes de cada
# chamada.
MODULE = Module("IA", "Modelos de IA, chaves e consumo", category="Integrações", core=True, limits=[
    Limit("custo", "Gasto com IA no mês", monthly=True, currency="USD"),
    Limit("tokens", "Tokens de IA no mês", monthly=True, unit="tokens"),
])

Scope = Literal["organization", "platform"]
Kind = Literal["chat", "embedding"]
Slug = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-z0-9][a-z0-9-]{0,29}$")]
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class AiSettings(BaseSettings):
    ai_secrets_key: SecretStr = Field(..., description="Chave AES-256 (base64url) que criptografa as chaves dos provedores")
    platform_tenant: str | None = Field(None, description="Organização dona da plataforma (provedores para todas)")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


class ProviderInput(_Input):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)] = Field(..., description="Nome para exibir")
    slug: Slug = Field(..., description="Apelido usado no nome do modelo (ex.: openrouter → openrouter/claude)")
    base_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300, pattern=r"^https?://\S+$")] = Field(
        ..., description="Endereço base da API compatível com OpenAI (ex.: https://openrouter.ai/api/v1)"
    )
    api_key: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = Field(
        "", description="Chave do provedor (vazia para provedores locais sem chave)"
    )
    scope: Scope = Field("organization", description="organization (só a sua organização) ou platform (todas)")


class ProviderRef(_Input):
    id: Id


class Provider(BaseModel):
    id: str
    name: str
    slug: str
    base_url: str = Field(..., description="Vazio no provedor da plataforma visto por outra organização")
    key_hint: str = Field(..., description="Só os últimos 4 caracteres da chave (vazio no provedor da plataforma visto de fora)")
    scope: Scope


class ProviderList(BaseModel):
    items: list[Provider]
    manages_platform: bool = Field(False, description="Quem pede administra os provedores da plataforma")


class ModelInput(_Input):
    provider: Id = Field(..., description="Id do provedor")
    model_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    kind: Kind = "chat"


class ModelUpdate(_Input):
    id: Id
    enabled: bool | None = None
    alias: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^([a-z0-9][a-z0-9.-]{0,59})?$")] | None = Field(
        None, description="Nome curto (ex.: claude → openrouter/claude); vazio remove o apelido"
    )
    kind: Kind | None = None
    price_input: float | None = Field(None, ge=0, description="Preço por milhão de tokens de entrada")
    price_output: float | None = Field(None, ge=0, description="Preço por milhão de tokens de saída")


class Model(BaseModel):
    id: str
    name: str = Field(..., description="O que se passa ao llm.*: <provedor>/<apelido ou id>")
    provider: str
    model_id: str
    alias: str | None
    kind: Kind
    enabled: bool
    price_input: float
    price_output: float
    scope: Scope


class ModelQuery(ListQuery):
    """Lista de modelos: busca por id ou apelido, filtros de liberado e tipo. Membro só recebe os liberados."""

    sortable: ClassVar[tuple[str, ...]] = ("model_id", "alias")
    default_sort: ClassVar[str | None] = "model_id"
    enabled: bool | None = Field(None, description="Só liberados (true) ou só não liberados (false)")
    kind: Kind | None = None


class ModelPage(Page[Model]):
    pass


class Discovered(BaseModel):
    found: int = Field(..., description="Modelos que o provedor listou")
    added: int = Field(..., description="Novos no catálogo (nascem não liberados)")


class UsageItem(BaseModel):
    model: str
    service: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float


class UsageSummary(BaseModel):
    month: str = Field(..., description="AAAA-MM, em UTC")
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    items: list[UsageItem]


class Recorded(BaseModel):
    """Uso gravado (também vai ao vivo para a tela da organização)."""

    id: str
    model: str
    service: str
    cost: float
    at: datetime
