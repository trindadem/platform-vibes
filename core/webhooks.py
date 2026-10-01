"""Webhooks (README §5.16): avisar os sistemas de cada organização quando algo acontece, e conferir os que chegam.

Saída (quem entrega é o svc-webhooks, no padrão Standard Webhooks):

    WEBHOOKS = [WebhookEvent("membro-entrou", "Alguém entrou na organização", MembroEntrou)]   # schemas.py
    await webhooks.declare(WEBHOOKS)                                                           # main.py, no lifespan
    await webhooks.emit("membro-entrou", MembroEntrou(...), key=f"entrou-{org}-{user}")        # service.py

Entrada (sistemas de fora que assinam no mesmo padrão: Svix, Resend, Clerk...):

    webhooks.verify(segredo, request.headers, await request.body())   # ServiceError 401 se a assinatura não bate

Trilhos:
- O evento se chama <serviço>.<nome> (identity.membro-entrou) e só o próprio serviço o emite. Emitir evento que não foi
  declarado é erro: o catálogo que a organização vê na tela é sempre completo, com o JSON Schema de cada evento.
- O evento vale para a organização atual: só os endereços dela recebem. Sem organização, erro.
- data é o modelo declarado do evento, nunca um dict solto. Não ponha segredo nem dado que a organização não deva ver.
- Entrega durável (events.webhooks.emit): o svc-webhooks fora do ar recebe quando voltar. key= dá o mesmo id à mesma
  intenção: repetir com a mesma key não entrega duas vezes.
"""
import base64
import binascii
import hashlib
import hmac
import os
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.envelope import ServiceError
from core.nats_bus import bus
from core.security import current_tenant

__all__ = [
    "webhooks", "Webhooks", "WebhookEvent", "Emitted", "Catalog", "CatalogEvent",
    "EMIT_SUBJECT", "CATALOG_SUBJECT", "SECRET_PREFIX", "new_secret", "sign", "verify",
]

EMIT_SUBJECT = "events.webhooks.emit"
CATALOG_SUBJECT = "events.webhooks.catalog"
SECRET_PREFIX = "whsec_"
TOLERANCE_SECONDS = 300  # assinatura mais velha (ou mais nova) que isso é recusada: impede reenvio de cópia antiga
_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


@dataclass(frozen=True)
class WebhookEvent:
    """Um evento que o serviço pode emitir: nome curto (kebab-case), o que significa e o modelo do data."""

    name: str
    description: str
    model: type[BaseModel]

    def __post_init__(self) -> None:
        if not _NAME.match(self.name) or len(self.name) > 40:
            raise ValueError(f"WebhookEvent: nome inválido {self.name!r} (kebab-case, ex.: fatura-paga)")
        if not 3 <= len(self.description) <= 200:
            raise ValueError(f"WebhookEvent {self.name!r}: descrição de 3 a 200 caracteres")
        if not (isinstance(self.model, type) and issubclass(self.model, BaseModel)):
            raise TypeError(f"WebhookEvent {self.name!r}: model precisa ser um modelo Pydantic")


class CatalogEvent(BaseModel):
    name: str = Field(..., description="Nome completo: <serviço>.<evento>")
    service: str
    description: str
    payload_schema: dict[str, Any] = Field(..., description="JSON Schema do data")


class Catalog(BaseModel):
    """events.webhooks.catalog: tudo o que um serviço emite (o que sair da lista sai do catálogo)."""

    service: str
    events: list[CatalogEvent]


class Emitted(BaseModel):
    """events.webhooks.emit: um evento que aconteceu na organização do cabeçalho."""

    service: str
    event: str
    occurred_at: datetime
    data: dict[str, Any]


def new_secret() -> str:
    """Segredo novo de assinatura: whsec_ + 32 bytes aleatórios em base64 (formato do Standard Webhooks)."""
    return SECRET_PREFIX + base64.b64encode(os.urandom(32)).decode()


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    """Valor do cabeçalho webhook-signature: v1,<base64(HMAC-SHA256(segredo, "{id}.{timestamp}.{corpo}"))>."""
    mac = hmac.new(_key_bytes(secret), f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def verify(secret: str, headers: Mapping[str, str], body: bytes, *, tolerance: int = TOLERANCE_SECONDS) -> None:
    """Confere um webhook recebido (cabeçalhos webhook-* ou svix-*). Assinatura errada ou velha → ServiceError 401."""
    lower = {k.lower(): v for k, v in headers.items()}
    msg_id = lower.get("webhook-id") or lower.get("svix-id")
    stamp = lower.get("webhook-timestamp") or lower.get("svix-timestamp")
    signatures = lower.get("webhook-signature") or lower.get("svix-signature")
    if not (msg_id and stamp and signatures):
        raise _invalid()
    try:
        timestamp = int(stamp)
        expected = sign(secret, msg_id, timestamp, body).partition(",")[2]
    except (ValueError, binascii.Error):
        raise _invalid() from None
    if abs(time.time() - timestamp) > tolerance:
        raise _invalid()
    for candidate in signatures.split():  # o remetente pode mandar várias (troca de segredo em andamento)
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value.encode(), expected.encode()):
            return
    raise _invalid()


def _key_bytes(secret: str) -> bytes:
    raw = secret.removeprefix(SECRET_PREFIX)
    return base64.b64decode(raw, validate=True)


def _invalid() -> ServiceError:
    return ServiceError("ERRO_WEBHOOK_SIGNATURE", "Assinatura do webhook inválida ou vencida.", status=401)


class Webhooks:
    def __init__(self) -> None:
        self._declared: dict[str, WebhookEvent] = {}

    async def declare(self, events: Sequence[WebhookEvent]) -> None:
        """No boot: guarda os eventos que este serviço emite e publica o catálogo para o svc-webhooks."""
        service = _service()
        prefix = service.removeprefix("svc-")
        names = [e.name for e in events]
        if len(names) != len(set(names)):
            raise ValueError("webhooks.declare: evento repetido")
        self._declared = {f"{prefix}.{e.name}": e for e in events}
        catalog = Catalog(service=service, events=[
            CatalogEvent(name=name, service=service, description=e.description, payload_schema=e.model.model_json_schema())
            for name, e in self._declared.items()
        ])
        digest = hashlib.sha256(catalog.model_dump_json().encode()).hexdigest()[:24]
        await bus.publish(CATALOG_SUBJECT, catalog, msg_id=f"catalog-{service}-{digest}")  # réplicas: um só

    async def emit(self, event: str, data: BaseModel, *, key: str | None = None) -> None:
        """Avisa os endereços da organização atual inscritos neste evento (declarado em webhooks.declare)."""
        current_tenant()  # sem organização, falha aqui (e não em silêncio no svc-webhooks)
        service = _service()
        name = f"{service.removeprefix('svc-')}.{event}"
        declared = self._declared.get(name)
        if declared is None:
            raise ValueError(f"webhooks.emit: evento {name!r} não declarado (webhooks.declare no lifespan, README §5.16)")
        if not isinstance(data, declared.model):
            raise TypeError(f"webhooks.emit: {name!r} leva {declared.model.__name__}, não {type(data).__name__}")
        if key is not None and not _KEY.match(key):
            raise ValueError(f"webhooks.emit: key inválida {key!r} (letras, números e _ . : -, até 120)")
        emitted = Emitted(service=service, event=name, occurred_at=datetime.now(UTC), data=data.model_dump(mode="json"))
        msg_id = f"webhook-{service}-{key}" if key else f"webhook-{uuid.uuid4().hex}"
        await bus.publish(EMIT_SUBJECT, emitted, msg_id=msg_id)

    # Os mesmos do módulo, para quem recebe webhooks: webhooks.verify(...).
    new_secret = staticmethod(new_secret)
    sign = staticmethod(sign)
    verify = staticmethod(verify)


def _service() -> str:
    if bus.service is None:
        raise RuntimeError("webhooks: bus não conectado (async with bus.connected(SERVICE) no lifespan)")
    return bus.service


webhooks = Webhooks()
