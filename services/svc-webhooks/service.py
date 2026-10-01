"""svc-webhooks · lógica de negócio pura. Fonte da verdade: specs/webhooks.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "webhooks.<método>".
Helpers começam com _ e nunca viram activities.

Serviço de plataforma (README §5.16): o único que chama os endereços das organizações, sempre pelo core.http_client
(SSRF conferido a cada envio, sem redirect). Segredos guardados com AES-256-GCM (WEBHOOKS_SECRETS_KEY).
"""
import base64
import functools
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from surrealdb import RecordID

from core.envelope import ServiceError
from core.http_client import http
from core.nats_bus import bus
from core.notify import notify
from core.plans import plans
from core.security import Principal, acting_as, assert_public_url, current, current_tenant, system
from core.surreal import Migration, Page, db
from core.temporal_runner import activities
from core.webhooks import new_secret, sign

from schemas import (
    ALL_EVENTS,
    DELIVERIES,
    DELIVERY_LIVE,
    DISABLE_AFTER,
    ENDPOINTS,
    KEEP_DAYS,
    MANAGERS,
    RETRY_SUBJECT,
    SERVICE,
    TEST_EVENT,
    TIMEOUT_SECONDS,
    Catalog,
    Cleaned,
    Delivery,
    DeliveryChanged,
    DeliveryPage,
    DeliveryQuery,
    DeliveryRef,
    Empty,
    Endpoint,
    EndpointInput,
    EndpointList,
    EndpointRef,
    EndpointSecret,
    EndpointUpdate,
    EventList,
    Outgoing,
    Ping,
    Planned,
    WebhooksSettings,
)

# Mudanças de dados versionadas, rodadas uma vez por banco no boot (README §5.13). Nunca edite uma já publicada.
MIGRATIONS: list[Migration] = []


@functools.cache
def settings() -> WebhooksSettings:
    """Lida e conferida no boot (main.py): sem WEBHOOKS_SECRETS_KEY de 32 bytes o serviço não sobe."""
    s = WebhooksSettings()
    _aead(s)
    return s


@activities("webhooks")
class WebhooksService:
    # ── Endereços (donos e administradores) ─────────────────────────────────

    async def list_endpoints(self, data: Empty) -> EndpointList:
        _manager()
        rows = await db.query("SELECT * FROM webhook_endpoints WHERE tenant = $tenant ORDER BY created_at")
        return EndpointList(items=[_endpoint(row) for row in rows])

    async def create_endpoint(self, data: EndpointInput) -> EndpointSecret:
        _manager()
        await plans.check("enderecos", used=await _endpoint_count())  # 402 ERRO_PLAN_LIMIT (README §5.17)
        await _check_url(data.url)
        events = await _check_events(data.events)
        row = await db.create(ENDPOINTS, {
            "url": data.url, "description": data.description, "events": events, "enabled": True, "failures": 0,
            "disabled_reason": None, "secret": "",
        })
        secret = new_secret()
        row = await db.merge(row["id"], {"secret": _encrypt(_key(row["id"]), secret)})  # preso a este endereço
        await plans.count("enderecos", await _endpoint_count())
        return EndpointSecret(endpoint=_endpoint(row), secret=secret)

    async def update_endpoint(self, data: EndpointUpdate) -> Endpoint:
        _manager()
        row = await _endpoint_row(data.id)
        changes: dict[str, Any] = {}
        if data.url is not None:
            await _check_url(data.url)
            changes["url"] = data.url
        if data.description is not None:
            changes["description"] = data.description
        if data.events is not None:
            changes["events"] = await _check_events(data.events)
        if data.enabled is not None:
            changes["enabled"] = data.enabled
            if data.enabled:
                changes.update(failures=0, disabled_reason=None)  # reativar começa a contagem do zero
        if changes:
            row = await db.merge(row["id"], changes)
        return _endpoint(row)

    async def remove_endpoint(self, data: EndpointRef) -> EndpointList:
        _manager()
        row = await _endpoint_row(data.id)
        await db.delete(row["id"])  # entregas pendentes viram skipped na próxima tentativa
        await plans.count("enderecos", await _endpoint_count())
        return await self.list_endpoints(Empty())

    async def rotate_secret(self, data: EndpointRef) -> EndpointSecret:
        _manager()
        row = await _endpoint_row(data.id)
        secret = new_secret()
        row = await db.merge(row["id"], {"secret": _encrypt(data.id, secret)})  # o antigo deixa de valer agora
        return EndpointSecret(endpoint=_endpoint(row), secret=secret)

    async def test_endpoint(self, data: EndpointRef) -> Delivery:
        """Envia webhooks.teste agora, uma tentativa só, e devolve o resultado para a tela."""
        _manager()
        endpoint = await _endpoint_row(data.id)
        ping = Ping(message="Teste enviado pela tela de webhooks.", endpoint=data.id)
        row = await db.create(DELIVERIES, {
            "message": f"msg_{uuid.uuid4().hex}", "endpoint": data.id, "url": endpoint["url"], "event": TEST_EVENT,
            "body": _body(TEST_EVENT, _now(), ping.model_dump(mode="json")), "status": "pending", "attempts": 0,
        })
        return await self._attempt(row, endpoint, last=True)

    # ── Entregas (donos e administradores) ──────────────────────────────────

    async def list_deliveries(self, data: DeliveryQuery) -> DeliveryPage:
        _manager()
        rows = await db.page(DELIVERIES, data, Page[dict[str, Any]])
        return DeliveryPage(**rows.model_dump(exclude={"items"}), items=[_delivery(row) for row in rows.items])

    async def retry_delivery(self, data: DeliveryRef) -> Delivery:
        """Reenvia o mesmo corpo com o mesmo webhook-id (quem recebe reconhece a repetição)."""
        _manager()
        row = await db.select(f"{DELIVERIES}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_WEBHOOKS_DELIVERY_NOT_FOUND", "Entrega não encontrada.", 404)
        if row["status"] != "pending":
            row = await db.merge(row["id"], {"status": "pending", "error": None})
            await bus.publish(RETRY_SUBJECT, DeliveryRef(id=data.id), msg_id=f"retry-{data.id}-{uuid.uuid4().hex}")
            await _changed(row)
        return _delivery(row)

    async def list_events(self, data: Empty) -> EventList:
        _manager()
        rows = await db.query_shared("SELECT name, service, description, payload_schema FROM webhook_events ORDER BY name")
        return EventList.model_validate({"items": rows})

    # ── Catálogo (events.webhooks.catalog, publicado pelo core no boot de cada serviço) ─

    async def record_catalog(self, data: Catalog) -> Empty:
        for event in data.events:
            await db.query_shared(
                "UPSERT $id SET name = $name, service = $service, description = $description, payload_schema = $schema",
                id=RecordID("webhook_events", event.name), name=event.name, service=data.service,
                description=event.description, schema=event.payload_schema,
            )
        await db.query_shared(  # o que saiu da lista do serviço sai do catálogo
            "DELETE webhook_events WHERE service = $service AND name NOT IN $names",
            service=data.service, names=[e.name for e in data.events],
        )
        return Empty()

    # ── Entrega (WebhooksWorkflow e RedeliverWorkflow) ──────────────────────

    async def fan_out(self, data: Outgoing) -> Planned:
        """Uma entrega por endereço ativo inscrito no evento; a reentrega da mesma mensagem não cria outra."""
        emitted = data.emitted
        endpoints = await db.query(
            "SELECT * FROM webhook_endpoints WHERE tenant = $tenant AND enabled = true "
            "AND (events CONTAINS $event OR events CONTAINS $all)",
            event=emitted.event, all=ALL_EVENTS,
        )
        message = "msg_" + hashlib.sha256(data.message.encode()).hexdigest()[:32]  # o mesmo para todos os endereços
        body = _body(emitted.event, emitted.occurred_at, emitted.data)
        planned = []
        for endpoint in endpoints:
            key = _key(endpoint["id"])
            try:
                row = await db.create(DELIVERIES, {
                    "message": message, "endpoint": key, "url": endpoint["url"], "event": emitted.event, "body": body,
                    "status": "pending", "attempts": 0,
                })
            except ServiceError as exc:
                if exc.code != "ERRO_RECORD_DUPLICATE":
                    raise
                row = (await db.query(
                    "SELECT id FROM webhook_deliveries WHERE tenant = $tenant AND message = $m AND endpoint = $e",
                    m=message, e=key,
                ))[0]
            planned.append(_key(row["id"]))
        return Planned(deliveries=planned)

    async def deliver(self, data: DeliveryRef) -> DeliveryChanged:
        """Uma tentativa. Falha temporária vira ServiceError 503: o Temporal tenta de novo com espera crescente."""
        row = await db.select(f"{DELIVERIES}:{data.id}")
        if row is None or row["status"] != "pending":
            return DeliveryChanged(id=data.id, status=row["status"] if row else "skipped")
        endpoint = await db.select(f"{ENDPOINTS}:{row['endpoint']}")
        if endpoint is None or not endpoint["enabled"]:
            row = await db.merge(row["id"], {"status": "skipped", "error": "Endereço removido ou desativado."})
            await _changed(row)
            return DeliveryChanged(id=data.id, status="skipped")
        result = await self._attempt(row, endpoint, last=False)
        return DeliveryChanged(id=result.id, status=result.status)

    async def give_up(self, data: DeliveryRef) -> DeliveryChanged:
        """Tentativas esgotadas: falha registrada e, depois de DISABLE_AFTER seguidas, o endereço é desativado."""
        row = await db.select(f"{DELIVERIES}:{data.id}")
        if row is None or row["status"] != "pending":
            return DeliveryChanged(id=data.id, status=row["status"] if row else "skipped")
        row = await db.merge(row["id"], {"status": "failed"})
        await _changed(row)
        counted = await db.query(
            "UPDATE webhook_endpoints SET failures += 1 WHERE tenant = $tenant AND id = $id RETURN AFTER",
            id=RecordID(ENDPOINTS, row["endpoint"]),
        )
        if counted and counted[0]["enabled"] and counted[0]["failures"] >= DISABLE_AFTER:
            await _disable(counted[0], f"Desativado depois de {DISABLE_AFTER} entregas seguidas sem sucesso.")
        return DeliveryChanged(id=data.id, status="failed")

    # ── Manutenção (agendamento diário) ─────────────────────────────────────

    async def cleanup(self, data: Empty) -> Cleaned:
        removed = 0
        before = _now() - timedelta(days=KEEP_DAYS)
        for org in await db.tenants(DELIVERIES):
            with acting_as(system(SERVICE, org)):
                gone = await db.query(
                    "DELETE webhook_deliveries WHERE tenant = $tenant AND status != 'pending' AND created_at < $before "
                    "RETURN BEFORE",
                    before=before,
                )
                removed += len(gone or [])
        return Cleaned(deliveries=removed)

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _attempt(self, row: dict, endpoint: dict, *, last: bool) -> Delivery:
        """POST assinado. 2xx entregue; 410 desativa o endereço; o resto tenta de novo (ou falha, se last)."""
        timestamp = int(time.time())
        body = row["body"].encode()
        secret = _decrypt(_key(endpoint["id"]), endpoint["secret"])
        headers = {
            "content-type": "application/json",
            "user-agent": "cv-frame-webhooks",
            "webhook-id": row["message"],
            "webhook-timestamp": str(timestamp),
            "webhook-signature": sign(secret, row["message"], timestamp, body),
        }
        local = settings().environment == "development"  # receptor de teste na rede interna (o core recusa em produção)
        started = time.monotonic()
        code: int | None = None
        error: str | None = None
        try:
            reply = await http.post(
                endpoint["url"], content=body, headers=headers, timeout=TIMEOUT_SECONDS, allow_http=local, allow_private=local
            )
            code = reply.status_code
        except ServiceError as exc:  # SSRF: o endereço passou a apontar para rede interna
            error = exc.code
        except httpx.HTTPError as exc:  # fora do ar, tempo esgotado, TLS
            error = type(exc).__name__
        changes: dict[str, Any] = {
            "attempts": row["attempts"] + 1, "response_status": code, "error": error,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if code is not None and 200 <= code < 300:
            row = await db.merge(row["id"], {**changes, "status": "sent", "delivered_at": _now()})
            if endpoint.get("failures"):
                await db.merge(endpoint["id"], {"failures": 0})
        elif code == 410:
            row = await db.merge(row["id"], {**changes, "status": "failed"})
            await _disable(endpoint, "O endereço respondeu 410 (Gone): pediu para não receber mais.")
        elif last:
            row = await db.merge(row["id"], {**changes, "status": "failed"})
        else:
            row = await db.merge(row["id"], changes)
            await _changed(row)
            raise ServiceError("ERRO_WEBHOOKS_DELIVERY_FAILED", "O endereço não confirmou o recebimento.", 503)
        await _changed(row)
        return _delivery(row)


def _manager() -> Principal:
    who = current()
    if who is None or not who.tenant or not MANAGERS & who.roles:
        raise ServiceError("ERRO_WEBHOOKS_FORBIDDEN", "Só donos e administradores gerenciam webhooks.", 403)
    return who


async def _endpoint_count() -> int:
    counted = await db.query("SELECT count() AS total FROM (SELECT id FROM webhook_endpoints WHERE tenant = $tenant) GROUP ALL")
    return counted[0]["total"] if counted else 0


async def _endpoint_row(endpoint_id: str) -> dict:
    row = await db.select(f"{ENDPOINTS}:{endpoint_id}")
    if row is None:
        raise ServiceError("ERRO_WEBHOOKS_ENDPOINT_NOT_FOUND", "Endereço não encontrado.", 404)
    return row


async def _check_url(url: str) -> None:
    local = settings().environment == "development"
    try:
        await assert_public_url(url, allow_http=local, allow_private=local)
    except ServiceError:
        raise ServiceError(
            "ERRO_WEBHOOKS_UNSAFE_URL", "O endereço precisa ser https e público (rede interna só em desenvolvimento).", 422
        ) from None


async def _check_events(events: list[str]) -> list[str]:
    if ALL_EVENTS in events:
        return [ALL_EVENTS]
    wanted = list(dict.fromkeys(events))
    known = set(await db.query_shared("SELECT VALUE name FROM webhook_events WHERE name IN $names", names=wanted))
    unknown = [name for name in wanted if name not in known]
    if unknown:
        raise ServiceError("ERRO_WEBHOOKS_UNKNOWN_EVENT", f"Evento desconhecido: {', '.join(unknown)}.", 422)
    return wanted


async def _disable(endpoint: dict, reason: str) -> None:
    await db.merge(endpoint["id"], {"enabled": False, "disabled_reason": reason})
    await notify.roles(
        "owner", "admin",
        title="Webhook desativado",
        body=f"{endpoint['url']}\n\n{reason} Confira o endereço e reative na tela de webhooks.",
        link="/webhooks",
        action="Ver webhooks",
        key=f"webhook-off-{_key(endpoint['id'])}-{int(time.time())}",
    )


async def _changed(row: dict) -> None:
    await bus.live(DELIVERY_LIVE, DeliveryChanged(id=_key(row["id"]), status=row["status"]))


def _body(event: str, occurred_at: datetime, data: dict[str, Any]) -> str:
    """Corpo do Standard Webhooks; guardado como texto: toda tentativa manda exatamente os mesmos bytes."""
    stamp = occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": event, "timestamp": stamp, "data": data}, ensure_ascii=False, separators=(",", ":"))


def _endpoint(row: dict) -> Endpoint:
    return Endpoint.model_validate({**row, "id": _key(row["id"])})


def _delivery(row: dict) -> Delivery:
    return Delivery.model_validate({**row, "id": _key(row["id"])})


def _aead(s: WebhooksSettings | None = None) -> AESGCM:
    raw = (s or settings()).webhooks_secrets_key.get_secret_value()
    key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    if len(key) != 32:
        raise RuntimeError("WEBHOOKS_SECRETS_KEY precisa de 32 bytes (base64url): rode uv run python -m core.security keygen")
    return AESGCM(key)


def _encrypt(endpoint_id: str, secret: str) -> str:
    """Preso à organização e ao endereço: copiar o valor para outro registro não abre."""
    nonce = os.urandom(12)
    sealed = _aead().encrypt(nonce, secret.encode(), f"{current_tenant()}:{endpoint_id}".encode())
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def _decrypt(endpoint_id: str, blob: str) -> str:
    raw = base64.urlsafe_b64decode(blob)
    return _aead().decrypt(raw[:12], raw[12:], f"{current_tenant()}:{endpoint_id}".encode()).decode()


def _now() -> datetime:
    return datetime.now(UTC)


def _key(record_id: str) -> str:
    return str(record_id).partition(":")[2].strip("⟨⟩`")
