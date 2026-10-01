"""svc-identity · contratos (DTOs, enums, constantes). Fonte da verdade: specs/identity.md §2"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings

from core.storage import IMAGES, KeepRequest, Upload, UploadRequest  # arquivos (README §5.14): contrato do core

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-identity"
TASK_QUEUE = "identity-queue"
TRIGGER_SUBJECT = "events.identity.trigger"
TENANT_CREATED_SUBJECT = "events.identity.tenant-created"
MEMBER_JOINED_SUBJECT = "events.identity.member-joined"
MEMBERS_LIVE = "identity.membros"  # ao vivo para a organização: alguém entrou ou saiu
ACCESS_LIVE = "identity.acesso"  # ao vivo só para a pessoa: perdeu o acesso a uma organização

# Tabelas globais (README §5.9): só este serviço declara shared=[...].
USERS = "identity_users"
TENANTS = "identity_tenants"
MEMBERSHIPS = "identity_memberships"
INVITES = "identity_invites"
SESSIONS = "identity_sessions"
SHARED_TABLES = [USERS, TENANTS, MEMBERSHIPS, INVITES, SESSIONS]
UNIQUE = {USERS: ["email"], MEMBERSHIPS: ["user", "tenant"], INVITES: ["code_hash"], SESSIONS: ["token_hash"]}

REFRESH_COOKIE = "cv_refresh"
COOKIE_PATH = "/api/v1/identity"
PUBLIC_PATHS = ("/signup", "/login", "/refresh", "/logout", "/invite-info")
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
REUSE_GRACE_SECONDS = 30
INVITE_DAYS = 7

Role = Literal["owner", "admin", "member"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=1024)]
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Code = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,128}$")]


class IdentitySettings(BaseSettings):
    environment: Literal["production", "development"] = "production"
    auth_token_ttl_seconds: int = Field(900, ge=60, le=86_400)  # a mesma variável do core.security
    refresh_days: int = Field(30, ge=1, le=365)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


class SignupInput(_Input):
    name: Name = Field(..., description="Nome da pessoa")
    email: Email = Field(..., description="E-mail de acesso")
    password: Password = Field(..., description="Senha (mínimo de 8 caracteres)")
    organization: Name | None = Field(None, description="Nome da organização nova (quem cadastra vira dono)")
    invite: Code | None = Field(None, description="Código de convite (entra numa organização existente)")

    @model_validator(mode="after")
    def _one_way_in(self) -> "SignupInput":
        if (self.organization is None) == (self.invite is None):
            raise PydanticCustomError("one_way_in", "Informe a organização nova ou o código de convite (um dos dois).")
        return self


class LoginInput(_Input):
    email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    tenant: Id | None = Field(None, description="Organização para entrar (padrão: a última usada)")


class SwitchInput(_Input):
    tenant: Id = Field(..., description="Organização que passa a ser a ativa")


class TenantInput(_Input):
    name: Name = Field(..., description="Nome da organização")


class InviteInput(_Input):
    role: Literal["admin", "member"] = Field("member", description="Papel de quem aceitar o convite")


class InviteCode(_Input):
    code: Code = Field(..., description="Código do convite")


class MemberRef(_Input):
    user: Id = Field(..., description="Id do usuário")


class RefreshInput(_Input):
    """Interno: o main.py lê o cookie e entrega o refresh ao service (nunca vem no corpo)."""

    refresh_token: str | None = None


class SwitchRequest(_Input):
    """Interno: troca de organização; o refresh atual (do cookie) é substituído por um da organização nova."""

    tenant: Id
    refresh_token: str | None = None


class TenantRequest(_Input):
    """Interno: cria uma organização e já entra nela, substituindo o refresh atual."""

    name: Name
    refresh_token: str | None = None


class JoinRequest(_Input):
    """Interno: aceita um convite e já entra na organização, substituindo o refresh atual."""

    code: Code
    refresh_token: str | None = None


class User(BaseModel):
    id: str
    name: str
    email: str


class Tenant(BaseModel):
    id: str
    name: str
    roles: list[Role]


class AuthResult(BaseModel):
    access_token: str = Field(..., description="Token de acesso (Authorization: Bearer)")
    expires_in: int = Field(..., description="Segundos até o token de acesso expirar")
    user: User
    tenant: Tenant | None = Field(..., description="Organização ativa")
    tenants: list[Tenant] = Field(..., description="Todas as organizações do usuário")


class Session(BaseModel):
    """Interno: AuthResult + refresh, que o main.py move para o cookie."""

    auth: AuthResult
    refresh_token: str
    refresh_max_age: int


class Me(BaseModel):
    user: User
    tenant: str | None
    tenants: list[Tenant]


class Invite(BaseModel):
    code: str = Field(..., description="Código para o link de convite (mostrado uma única vez)")
    role: Role
    expires_at: datetime


class InviteInfo(BaseModel):
    tenant_name: str
    role: Role
    expires_at: datetime


class Member(BaseModel):
    id: str
    name: str
    email: str
    roles: list[Role]
    joined_at: datetime


class MemberList(BaseModel):
    items: list[Member]


class TenantCreated(BaseModel):
    tenant: str
    name: str


class MemberJoined(BaseModel):
    tenant: str
    user: str
    roles: list[Role]


class MembersChanged(BaseModel):
    user: str = Field(..., description="Id de quem entrou ou saiu")
    change: Literal["joined", "removed"]


class AccessChanged(BaseModel):
    tenant: str = Field(..., description="Organização que a pessoa deixou de acessar")
    change: Literal["removed"]


class Cleaned(BaseModel):
    sessions: int
    invites: int


# ── Organização: nome e logo (arquivos, README §5.14) ─────────────────────────

LOGO_TYPES = IMAGES
LOGO_MAX_BYTES = 2_000_000
LOGO_SECONDS = 3600  # o link da imagem vale 1 h: a tela pede de novo ao recarregar


class Organization(BaseModel):
    id: str
    name: str
    logo_url: str | None = Field(None, description="Link assinado da imagem do logo (vale 1 h)")
