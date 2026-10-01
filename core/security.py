"""Segurança canônica: um único jeito, importável, de autenticar, autorizar e se proteger.

Regras (README §5.7):
- Nega por padrão: install_security(app) exige token válido em TODA rota. Abrir é explícito: public=("/rota",).
- Identidade vem do token (Principal), nunca do payload. Durante a requisição, o evento ou a activity, ela
  fica no contexto: current() diz quem age e current_tenant() de qual organização (README §5.9).
- Tokens JWT só com chave assimétrica: EdDSA com chaves próprias ou JWKS de um provedor (Auth0, Clerk,
  Keycloak...). "none" e HS256 são recusados; issuer, audience e expiração são obrigatórios.
- Senhas só via hash_password/verify_password (Argon2id, fora do event loop). Segredos só no ambiente.
- URL externa vinda de usuário passa por assert_public_url (bloqueia SSRF para a rede interna).

Variáveis: ENVIRONMENT (production | development; padrão production), AUTH_ISSUER, AUTH_AUDIENCE e
exatamente uma fonte de chave: AUTH_PUBLIC_KEY / AUTH_PRIVATE_KEY (chaves próprias) ou AUTH_JWKS_URL.
Opcionais: AUTH_TOKEN_TTL_SECONDS (900), AUTH_ROLES_CLAIM (roles), AUTH_TENANT_CLAIM (tenant),
CORS_ORIGINS (origens separadas por vírgula; "*" é recusado).

Ambiente local: uv run python -m core.security keygen (cria o .env) e
uv run python -m core.security token <sub> [--tenant <organização>] [papel...].
"""
import asyncio
import base64
import contextvars
import functools
import hmac
import ipaddress
import os
import re
import secrets
import socket
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.envelope import ServiceError, error_response

_JWKS_ALGORITHMS = ["RS256", "ES256", "EdDSA"]
_LEEWAY_SECONDS = 30
_SENSITIVE_KEY = re.compile(r"pass|secret|token|authorization|api[_-]?key|cookie|credential|private", re.I)


# ── Configuração ─────────────────────────────────────────────────────────────

class SecuritySettings(BaseSettings):
    environment: Literal["production", "development"] = "production"
    auth_issuer: str
    auth_audience: str
    auth_public_key: SecretStr | None = None
    auth_private_key: SecretStr | None = None
    auth_jwks_url: str | None = None
    auth_token_ttl_seconds: int = Field(900, ge=60, le=86_400)
    auth_roles_claim: str = "roles"
    auth_tenant_claim: str = "tenant"
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        return [o.strip() for o in value.split(",") if o.strip()] if isinstance(value, str) else value

    @model_validator(mode="after")
    def _one_key_source(self) -> "SecuritySettings":
        own_keys = self.auth_public_key or self.auth_private_key
        if bool(own_keys) == bool(self.auth_jwks_url):
            raise ValueError("defina AUTH_PUBLIC_KEY/AUTH_PRIVATE_KEY (chaves próprias) OU AUTH_JWKS_URL (provedor)")
        if self.auth_jwks_url and not self.auth_jwks_url.startswith("https://"):
            raise ValueError("AUTH_JWKS_URL precisa ser https://")
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS não aceita '*': liste as origens permitidas")
        return self


@functools.cache
def _settings() -> SecuritySettings:
    try:
        return SecuritySettings()
    except ValidationError as exc:
        raise RuntimeError(f"core.security: configuração ausente ou insegura (README §5.7)\n{exc}") from None


@functools.cache
def _own_keys() -> tuple[Ed25519PrivateKey | None, Ed25519PublicKey]:
    s = _settings()
    private = public = None
    if s.auth_private_key:
        private = Ed25519PrivateKey.from_private_bytes(_b64d(s.auth_private_key.get_secret_value()))
    if s.auth_public_key:
        public = Ed25519PublicKey.from_public_bytes(_b64d(s.auth_public_key.get_secret_value()))
    if private and public and private.public_key().public_bytes_raw() != public.public_bytes_raw():
        raise RuntimeError("core.security: AUTH_PRIVATE_KEY e AUTH_PUBLIC_KEY não formam um par")
    return private, public or private.public_key()


@functools.cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(_settings().auth_jwks_url, cache_keys=True, lifespan=300)


# ── Identidade e tokens ──────────────────────────────────────────────────────

class Principal(BaseModel, frozen=True):
    """Quem está chamando. Vem sempre do token verificado: usuário, organização ativa e papéis nela."""

    sub: str
    tenant: str | None = None
    roles: frozenset[str] = frozenset()
    expires_at: int | None = None  # exp do token (epoch); None para quem age sem token (jobs, testes)

    def has(self, *roles: str) -> bool:
        return set(roles) <= self.roles

    @property
    def is_system(self) -> bool:
        """Tarefa da própria plataforma (agendamento, migração), não uma pessoa: veja system()."""
        return self.sub.startswith(SYSTEM_PREFIX)


SYSTEM_PREFIX = "system:"


def system(service: str, tenant: str | None = None) -> Principal:
    """Quem age numa tarefa da plataforma (agendamento, migração), nunca vindo de token.

        for org in await db.tenants(TABELA):
            with acting_as(system(SERVICE, org)):
                await db.query("DELETE faturas WHERE tenant = $tenant AND vence_em < $limite", limite=...)

    Os carimbos de autoria gravam "system:<serviço>". Token nenhum chega com esse sub: issue_token o recusa.
    """
    return Principal(sub=f"{SYSTEM_PREFIX}{service}", tenant=tenant, roles=frozenset({"system"}))


_current: contextvars.ContextVar[Principal | None] = contextvars.ContextVar("cv_principal", default=None)


def current() -> Principal | None:
    """Quem age agora: o Principal da requisição, do evento NATS ou da activity (None fora deles)."""
    return _current.get()


def current_tenant() -> str:
    """Organização de quem age agora. Sem organização → ServiceError 403 (ERRO_TENANT_REQUIRED)."""
    who = _current.get()
    if who is None or not who.tenant:
        raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", status=403)
    return who.tenant


@contextmanager
def acting_as(who: Principal | None) -> Iterator[Principal | None]:
    """Executa o bloco em nome de alguém. O core usa ao receber requisição, evento ou activity;
    use em testes e tarefas internas: with acting_as(Principal(sub="job", tenant="acme")): ..."""
    token = _current.set(who)
    try:
        yield who
    finally:
        _current.reset(token)


def issue_token(
    sub: str, *, tenant: str | None = None, roles: Iterable[str] = (), ttl_seconds: int | None = None
) -> str:
    """Emite um JWT EdDSA. Só funciona onde AUTH_PRIVATE_KEY existe (o serviço que faz login)."""
    if sub.startswith(SYSTEM_PREFIX):
        raise ValueError(f"sub {sub!r} é reservado às tarefas da plataforma (security.system)")
    s = _settings()
    private, _ = _own_keys() if not s.auth_jwks_url else (None, None)
    if private is None:
        raise RuntimeError("issue_token exige AUTH_PRIVATE_KEY (só o serviço emissor de tokens a possui)")
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": s.auth_issuer,
        "aud": s.auth_audience,
        "sub": sub,
        "iat": now,
        "nbf": now,
        "exp": now + (ttl_seconds or s.auth_token_ttl_seconds),
        "jti": uuid.uuid4().hex,
        s.auth_roles_claim: sorted(roles),
    }
    if tenant is not None:
        claims[s.auth_tenant_claim] = tenant
    return jwt.encode(claims, private, algorithm="EdDSA")


def verify_token(token: str) -> Principal:
    """Valida assinatura, algoritmo, issuer, audience e expiração. Falha → ServiceError 401."""
    s = _settings()
    try:
        if s.auth_jwks_url:
            key, algorithms = _jwks().get_signing_key_from_jwt(token).key, _JWKS_ALGORITHMS
        else:
            key, algorithms = _own_keys()[1], ["EdDSA"]
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=s.auth_audience,
            issuer=s.auth_issuer,
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        raise ServiceError("ERRO_AUTH_INVALID_TOKEN", "Token inválido ou expirado.", status=401) from None
    roles = claims.get(s.auth_roles_claim) or []
    if isinstance(roles, str):
        roles = roles.split()
    tenant = claims.get(s.auth_tenant_claim)
    if tenant is not None and not isinstance(tenant, str):
        raise ServiceError("ERRO_AUTH_INVALID_TOKEN", "Token inválido ou expirado.", status=401)
    if str(claims["sub"]).startswith(SYSTEM_PREFIX):  # identidade das tarefas da plataforma nunca vem de fora
        raise ServiceError("ERRO_AUTH_INVALID_TOKEN", "Token inválido.", status=401)
    return Principal(sub=str(claims["sub"]), tenant=tenant or None, roles=frozenset(roles), expires_at=int(claims["exp"]))


# ── Senhas ───────────────────────────────────────────────────────────────────

_hasher = PasswordHasher()  # Argon2id com os parâmetros recomendados pela RFC 9106


async def hash_password(password: str) -> str:
    if not 8 <= len(password) <= 1024:
        raise ServiceError("ERRO_AUTH_WEAK_PASSWORD", "A senha deve ter entre 8 e 1024 caracteres.", status=422)
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True quando os parâmetros do Argon2 evoluíram: re-hash no próximo login bem-sucedido."""
    return _hasher.check_needs_rehash(password_hash)


# ── FastAPI ──────────────────────────────────────────────────────────────────

def install_security(app: FastAPI, *, service: str, public: Iterable[str] = ()) -> None:
    """Nega por padrão + cabeçalhos de segurança + CORS explícito. Sem configuração válida, o app não sobe."""
    s = _settings()
    _jwks() if s.auth_jwks_url else _own_keys()
    open_paths = set(public)
    if s.environment == "development":
        open_paths |= {p for p in (app.docs_url, app.redoc_url, app.openapi_url) if p}
    app.add_middleware(_AuthMiddleware, service=service, public=frozenset(open_paths), jwks=bool(s.auth_jwks_url))
    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )
    app.add_middleware(_HeadersMiddleware, production=s.environment == "production")


def principal(request: Request) -> Principal:
    """Dependência FastAPI: o Principal da requisição. Uso: p: Principal = Depends(principal)."""
    current = getattr(request.state, "principal", None)
    if current is None:
        raise ServiceError("ERRO_AUTH_UNAUTHENTICATED", "Autenticação necessária.", status=401)
    return current


def require(*roles: str) -> Callable[..., Principal]:
    """Dependência FastAPI que exige todos os papéis. Uso: Depends(require("admin"))."""

    def dependency(current: Principal = Depends(principal)) -> Principal:
        if not current.has(*roles):
            raise ServiceError("ERRO_AUTH_FORBIDDEN", "Permissão insuficiente.", status=403)
        return current

    return dependency


class _AuthMiddleware:
    def __init__(self, app: ASGIApp, *, service: str, public: frozenset[str], jwks: bool) -> None:
        self.app, self.service, self.public, self.jwks = app, service, public, jwks

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_public = scope["path"] in self.public
        current, failure = None, None
        scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                current = await asyncio.to_thread(verify_token, token) if self.jwks else verify_token(token)
            except ServiceError as exc:
                failure = exc
        if current is None and not is_public:
            failure = failure or ServiceError("ERRO_AUTH_UNAUTHENTICATED", "Autenticação necessária.", status=401)
            response = error_response(
                self.service, 401, failure.code, failure.message, headers={"WWW-Authenticate": "Bearer"}
            )
            return await response(scope, receive, send)
        scope.setdefault("state", {})["principal"] = current
        with acting_as(current):  # current()/current_tenant() valem até o fim da requisição
            await self.app(scope, receive, send)


class _HeadersMiddleware:
    _BASE = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "cache-control": "no-store",
    }
    _PRODUCTION = {
        "strict-transport-security": "max-age=63072000; includeSubDomains",
        "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    }

    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.headers = {**self._BASE, **(self._PRODUCTION if production else {})}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ── Utilidades ───────────────────────────────────────────────────────────────

def new_secret(nbytes: int = 32) -> str:
    """Segredo aleatório criptograficamente seguro (nunca use random para isso)."""
    return secrets.token_urlsafe(nbytes)


def same(a: str | bytes, b: str | bytes) -> bool:
    """Comparação em tempo constante para tokens, assinaturas e códigos (evita timing attack)."""
    a_bytes = a.encode() if isinstance(a, str) else a
    b_bytes = b.encode() if isinstance(b, str) else b
    return hmac.compare_digest(a_bytes, b_bytes)


def redact(data: Any) -> Any:
    """Cópia segura para log: mascara chaves como password, token, secret, authorization, api_key."""
    if isinstance(data, Mapping):
        return {k: "***" if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact(v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [redact(v) for v in data]
    return data


async def assert_public_url(url: str, *, allow_http: bool = False, allow_private: bool = False) -> None:
    """Bloqueia SSRF: só https (ou http, se permitido) para hosts cujos IPs são todos públicos.

    allow_private aceita rede interna (um receptor de teste no compose), e só com ENVIRONMENT=development: em produção
    o pedido é recusado aqui, seja qual for o serviço que o fez.
    """
    parts = urlsplit(url)
    schemes = {"https", "http"} if allow_http else {"https"}
    if parts.scheme not in schemes or not parts.hostname or parts.username or parts.password:
        raise ServiceError("ERRO_SSRF_BLOCKED", f"URL não permitida (esquemas aceitos: {', '.join(sorted(schemes))}).")
    if allow_private:
        if _settings().environment != "development":
            raise ServiceError("ERRO_SSRF_BLOCKED", "Endereço interno só é aceito em desenvolvimento.")
        return
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ServiceError("ERRO_SSRF_BLOCKED", "Host não encontrado.") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ServiceError("ERRO_SSRF_BLOCKED", "URL aponta para endereço interno ou reservado.")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ── Linha de comando (desenvolvimento local) ─────────────────────────────────

_LOCAL_ENV = """\
# Desenvolvimento local. Gerado por: uv run python -m core.security keygen. Nunca versionar.
# Produção: segredos no gerenciador do provedor; AUTH_PRIVATE_KEY só no serviço que emite tokens.
ENVIRONMENT=development
AUTH_ISSUER=http://localhost:8088
AUTH_AUDIENCE=cv-frame
AUTH_PRIVATE_KEY={private}
AUTH_PUBLIC_KEY={public}
CORS_ORIGINS=http://localhost:5173
SURREAL_NAMESPACE=cv
SURREAL_DATABASE=app
SURREAL_USER=app
SURREAL_PASSWORD={surreal_password}
SURREAL_ROOT_PASSWORD={surreal_root_password}
# Arquivos (README §5.14): credenciais do armazenamento S3 local (RustFS, no compose).
STORAGE_BUCKET=cv-frame
STORAGE_ACCESS_KEY={storage_access_key}
STORAGE_SECRET_KEY={storage_secret_key}
# IA (README §5.11): chave que criptografa as chaves dos provedores; só o svc-ai a recebe.
AI_SECRETS_KEY={ai_secrets_key}
# Webhooks (README §5.16): chave que criptografa os segredos de assinatura dos endereços; só o svc-webhooks a recebe.
WEBHOOKS_SECRETS_KEY={webhooks_secrets_key}
# Organização dona da plataforma (provedores de IA para todas): o id dela, depois de criada pela tela de cadastro.
# PLATFORM_TENANT=
"""

_USAGE = """uso:
  uv run python -m core.security keygen                                   cria o .env local (chaves e senhas aleatórias)
  uv run python -m core.security token <sub> [--tenant <org>] [papel...]  emite um token de teste com as chaves do .env"""


def _keygen(env_file: Path) -> None:
    if env_file.exists():
        sys.exit(f"{env_file} já existe; nada foi alterado. Apague-o para gerar chaves novas.")
    key = Ed25519PrivateKey.generate()
    env_file.write_text(_LOCAL_ENV.format(
        private=_b64e(key.private_bytes_raw()),
        public=_b64e(key.public_key().public_bytes_raw()),
        surreal_password=new_secret(24),
        surreal_root_password=new_secret(24),
        ai_secrets_key=new_secret(32),
        webhooks_secrets_key=new_secret(32),
        storage_access_key="cv" + new_secret(9).lower().replace("_", "").replace("-", "")[:10],
        storage_secret_key=new_secret(24),
    ))
    env_file.chmod(0o600)
    print(f"{env_file} criado (chaves EdDSA e senhas aleatórias). Ele está no .gitignore: nunca o versione.")


def _token(env_file: Path, sub: str, args: list[str]) -> None:
    tenant = None
    if "--tenant" in args:
        at = args.index("--tenant")
        if at + 1 >= len(args):
            sys.exit(_USAGE)
        tenant = args[at + 1]
        args = args[:at] + args[at + 2:]
    for line in env_file.read_text().splitlines() if env_file.exists() else []:
        name, sep, value = line.partition("=")
        if sep and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip())
    print(issue_token(sub, tenant=tenant, roles=args))


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["keygen"]:
            _keygen(Path(".env"))
        case ["token", sub, *args]:
            _token(Path(".env"), sub, args)
        case _:
            sys.exit(_USAGE)
