"""svc-webhooks · contratos (DTOs, enums, constantes). Fonte da verdade: specs/webhooks.md §2"""
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from pydantic_settings import BaseSettings

from core.plans import Limit
from core.surreal import ListQuery, Page
from core.webhooks import CATALOG_SUBJECT, EMIT_SUBJECT, Catalog, CatalogEvent, Emitted, WebhookEvent  # contrato do core

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-webhooks"
TASK_QUEUE = "webhooks-queue"
RETRY_SUBJECT = "events.webhooks.retry"  # reenviar pela tela: inicia RedeliverWorkflow
DELIVERY_LIVE = "webhooks.entrega"  # ao vivo para a organização a cada mudança de uma entrega (README §5.10)

# Endereços e entregas são da organização; o catálogo de eventos é um só para a plataforma.
ENDPOINTS = "webhook_endpoints"
DELIVERIES = "webhook_deliveries"
EVENTS = "webhook_events"
TENANT_TABLES = [ENDPOINTS, DELIVERIES]
SHARED_TABLES = [EVENTS]
UNIQUE = {DELIVERIES: ["message", "endpoint"], EVENTS: ["name"]}

MANAGERS = frozenset({"owner", "admin"})
ALL_EVENTS = "*"
DISABLE_AFTER = 20  # entregas seguidas sem sucesso desativam o endereço
ATTEMPTS = 10  # 5 s, 20 s, 80 s... até 5 h entre tentativas: cerca de 15 h no total
TIMEOUT_SECONDS = 15
KEEP_DAYS = 30
TEST_EVENT = "webhooks.teste"

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
EventName = Annotated[str, StringConstraints(pattern=r"^(\*|[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*)$", max_length=81)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^https?://\S+$")]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Status = Literal["pending", "sent", "failed", "skipped"]


class WebhooksSettings(BaseSettings):
    environment: Literal["production", "development"] = "production"
    webhooks_secrets_key: SecretStr = Field(..., description="Chave AES-256 (base64url) que criptografa os segredos dos endereços")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


class Ping(BaseModel):
    """data do webhooks.teste: o que o botão Enviar teste manda."""

    message: str = Field(..., description="Texto fixo do teste")
    endpoint: str = Field(..., description="Id do endereço testado")


# Limite do plano (README §5.17): endereços por organização; sem plano, 20.
LIMITS = [Limit("enderecos", "Endereços de webhook", default=20, unit="endereços")]

WEBHOOKS = [WebhookEvent("teste", "Teste enviado pela tela de webhooks, para conferir o endereço e a assinatura.", Ping)]


class Endpoint(BaseModel):
    id: str
    url: str
    description: str = ""
    events: list[str] = Field(..., description='Eventos inscritos; ["*"] para todos')
    enabled: bool
    failures: int = Field(0, description="Entregas seguidas sem sucesso")
    disabled_reason: str | None = None
    created_at: datetime


class EndpointList(BaseModel):
    items: list[Endpoint]


class EndpointSecret(BaseModel):
    endpoint: Endpoint
    secret: str = Field(..., description="Segredo de assinatura (whsec_...): aparece só agora")


class EndpointInput(_Input):
    url: Url = Field(..., description="Endereço que recebe os eventos (https)")
    description: Description = ""
    events: list[EventName] = Field(..., min_length=1, max_length=100, description='Eventos, ou ["*"] para todos')


class EndpointUpdate(_Input):
    id: Id
    url: Url | None = None
    description: Description | None = None
    events: list[EventName] | None = Field(None, min_length=1, max_length=100)
    enabled: bool | None = None


class EndpointRef(_Input):
    id: Id


class Delivery(BaseModel):
    id: str
    endpoint: str
    url: str
    event: str
    status: Status
    attempts: int = 0
    response_status: int | None = Field(None, description="Código HTTP da última resposta")
    error: str | None = None
    duration_ms: int | None = None
    created_at: datetime
    delivered_at: datetime | None = None


class DeliveryQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at",)
    default_sort: ClassVar[str | None] = "-created_at"  # mais novas primeiro
    endpoint: Id | None = None
    status: Status | None = None
    event: str | None = Field(None, max_length=81)


class DeliveryPage(Page[Delivery]):
    pass


class DeliveryRef(_Input):
    id: Id


class DeliveryChanged(BaseModel):
    id: str
    status: Status


class EventList(BaseModel):
    items: list[CatalogEvent]


class Outgoing(BaseModel):
    """Entrada do WebhooksWorkflow: o evento e o id estável da mensagem (o mesmo em toda reentrega)."""

    message: str
    emitted: Emitted


class Planned(BaseModel):
    deliveries: list[str]


class Cleaned(BaseModel):
    deliveries: int
