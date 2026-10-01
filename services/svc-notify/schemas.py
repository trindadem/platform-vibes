"""svc-notify · contratos (DTOs, enums, constantes). Fonte da verdade: specs/notify.md §2"""
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from pydantic_settings import BaseSettings

from core.notify import CONTACTS_SUBJECT, SEND_SUBJECT, Contacts, ContactsRequest, NotifyRequest  # contrato com core/notify.py
from core.plans import Module
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-notify"
TASK_QUEUE = "notify-queue"
NEW_LIVE = "notify.nova"  # ao vivo só para a pessoa avisada (README §5.10)

# O módulo (README §5.17): da plataforma, sempre ligado.
MODULE = Module("Avisos", "Avisos na tela e por e-mail", category="Organização", core=True)

# Avisos são por organização; e-mails e preferências são globais (a pessoa é a mesma em todas as organizações).
ITEMS = "notify_items"
EMAILS = "notify_emails"
PREFS = "notify_prefs"
TENANT_TABLES = [ITEMS]
SHARED_TABLES = [EMAILS, PREFS]
UNIQUE = {ITEMS: ["message", "user"], EMAILS: ["message", "to"], PREFS: ["user"]}

EMAIL_ATTEMPTS = 8  # com espera crescente: de 10 s a 10 min entre tentativas (cerca de 30 min no total)
KEEP_READ_DAYS = 90
KEEP_EMAIL_DAYS = 30

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class NotifySettings(BaseSettings):
    environment: Literal["production", "development"] = "production"
    smtp_url: SecretStr = Field(..., description="smtps://usuário:senha@host:465 ou smtp://usuário:senha@host:587")
    mail_from: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)] = Field(
        ..., description='Remetente: "Nome <nao-responda@dominio>"'
    )
    app_url: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^https?://[^\s/]+(:\d+)?$")] = Field(
        ..., description="Endereço da tela, sem barra no fim: os links dos e-mails começam por ele"
    )
    app_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] = "CV-Frame"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


class Notification(BaseModel):
    id: str
    title: str
    body: str = ""
    link: str | None = None
    action: str | None = None
    service: str = Field(..., description="Serviço que avisou (svc-...)")
    read: bool = False
    created_at: datetime


class NotificationQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at",)
    default_sort: ClassVar[str | None] = "-created_at"  # mais novos primeiro
    read: bool | None = Field(None, description="false: só os não lidos")


class NotificationPage(Page[Notification]):
    pass


class Unread(BaseModel):
    count: int


class ReadRequest(_Input):
    ids: list[Id] = Field(..., min_length=1, max_length=100)


class Preferences(_Input):
    email: bool = Field(True, description="Receber os avisos também por e-mail (os de segurança sempre chegam)")


class Outgoing(BaseModel):
    """Entrada do NotifyWorkflow: o pedido e o id estável da mensagem (o mesmo em toda reentrega)."""

    message: str
    request: NotifyRequest


class Prepared(BaseModel):
    """Saída de deliver: os avisos gravados e os e-mails a enviar (ids em notify_emails)."""

    notified: int
    emails: list[str]


class EmailRef(BaseModel):
    id: str


class EmailResult(BaseModel):
    id: str
    status: Literal["sent", "failed", "skipped"]


class Cleaned(BaseModel):
    items: int
    emails: int
