"""svc-ai · lógica de negócio pura. Fonte da verdade: specs/ai.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "ai.<método>".
Helpers começam com _ e nunca viram activities.

Chaves dos provedores: AES-256-GCM com AI_SECRETS_KEY, presas ao owner e ao slug (uma chave copiada para outro
registro não abre). Nunca saem daqui, a não ser descriptografadas no rpc.ai.resolve para o core/llm.py.
"""
import base64
import functools
import os
import uuid
from datetime import UTC, datetime

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from surrealdb import RecordID

from core.envelope import ServiceError
from core.http_client import http, no_cookie_jar
from core.nats_bus import bus
from core.security import Principal, assert_public_url, current
from core.surreal import db
from core.temporal_runner import activities

from schemas import (
    MANAGERS,
    MODELS,
    PLATFORM,
    PROVIDERS,
    USAGE,
    AiSettings,
    Empty,
    Model,
    ModelInput,
    ModelList,
    ModelUpdate,
    Provider,
    ProviderInput,
    ProviderList,
    ProviderRef,
    Recorded,
    Resolved,
    ResolveRequest,
    UsageEvent,
    UsageItem,
    UsageSummary,
)


@functools.cache
def settings() -> AiSettings:
    return AiSettings()


@activities("ai")
class AiService:
    # ── Provedores ──────────────────────────────────────────────────────────

    async def list_providers(self, data: Empty) -> ProviderList:
        who = _manager()
        rows = await db.query_shared(
            "SELECT * FROM ai_providers WHERE (owner = $org OR owner = $plat) ORDER BY owner, slug", **_visible(who)
        )
        return ProviderList(items=[_provider_view(row) for row in rows])

    async def create_provider(self, data: ProviderInput) -> Provider:
        who = _manager()
        owner = _owner_for(who, data.scope)
        base_url = data.base_url.rstrip("/")
        if data.scope == "organization":
            await _safe_url(base_url)
        record = {
            "owner": owner,
            "slug": data.slug,
            "name": data.name,
            "base_url": base_url,
            "key": _encrypt(owner, data.slug, data.api_key),
            "key_hint": data.api_key[-4:] if data.api_key else "",
            "created_by": who.sub,
            "created_at": _now(),
        }
        try:
            row = await db.create(PROVIDERS, record)
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_AI_SLUG_TAKEN", f"Já existe um provedor com o apelido {data.slug}.", 409) from None
            raise
        return _provider_view(row)

    async def remove_provider(self, data: ProviderRef) -> ProviderList:
        who = _manager()
        provider = await self._provider(who, data.id, manage=True)
        await db.query_shared("DELETE ai_models WHERE provider = $p", p=_rid(provider["id"]))
        await db.delete(provider["id"])
        return await self.list_providers(Empty())

    # ── Catálogo de modelos ─────────────────────────────────────────────────

    async def discover_models(self, data: ProviderRef) -> ModelList:
        """Busca GET {base_url}/models e grava os novos ids desativados (quem administra ativa)."""
        who = _manager()
        provider = await self._provider(who, data.id, manage=True)
        ids = await _fetch_model_ids(provider)
        known = set(await db.query_shared("SELECT VALUE model_id FROM ai_models WHERE provider = $p", p=_rid(provider["id"])))
        for model_id in sorted(set(ids) - known):
            kind = "embedding" if "embed" in model_id.lower() else "chat"
            await db.create(MODELS, _model_record(provider, model_id, kind, enabled=False))
        return await self.list_models(Empty())

    async def add_model(self, data: ModelInput) -> Model:
        """Cadastro manual (provedor sem /models): já nasce ativo."""
        who = _manager()
        provider = await self._provider(who, data.provider, manage=True)
        try:
            row = await db.create(MODELS, _model_record(provider, data.model_id, data.kind, enabled=True))
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_AI_SLUG_TAKEN", "Este modelo já está cadastrado neste provedor.", 409) from None
            raise
        return await self._model_view(row)

    async def update_model(self, data: ModelUpdate) -> Model:
        who = _manager()
        model = await db.select(f"{MODELS}:{data.id}")
        if model is None or model["owner"] not in _owners(who):
            raise ServiceError("ERRO_AI_MODEL_NOT_FOUND", "Modelo não encontrado.", 404)
        _owner_for(who, "platform" if model["owner"] == PLATFORM else "organization")  # da plataforma: só quem a administra
        changes = data.model_dump(exclude={"id"}, exclude_none=True)
        if alias := changes.get("alias"):
            taken = await db.query_shared(
                "SELECT VALUE id FROM ai_models WHERE provider = $p AND alias = $a AND id != $id",
                p=_rid(model["provider"]), a=alias, id=_rid(model["id"]),
            )
            if taken:
                raise ServiceError("ERRO_AI_SLUG_TAKEN", f"Outro modelo deste provedor já usa o apelido {alias}.", 409)
        row = await db.merge(model["id"], changes) if changes else model
        return await self._model_view(row)

    async def list_models(self, data: Empty) -> ModelList:
        """Modelos visíveis para a organização: os dela e os da plataforma."""
        who = _member()
        rows = await db.query_shared(
            "SELECT *, provider.slug AS slug FROM ai_models WHERE (owner = $org OR owner = $plat) ORDER BY slug, model_id",
            **_visible(who),
        )
        return ModelList(items=[_model_view(row) for row in rows])

    # ── Uso dos serviços (core/llm.py) ──────────────────────────────────────

    async def resolve(self, data: ResolveRequest) -> Resolved:
        """rpc.ai.resolve: o provedor da organização com esse apelido esconde o da plataforma (sem mistura)."""
        who = _member()
        slug, _, name = data.model.partition("/")
        providers = await db.query_shared(
            "SELECT * FROM ai_providers WHERE slug = $slug AND (owner = $org OR owner = $plat)", slug=slug, **_visible(who)
        )
        provider = next((p for p in providers if p["owner"] != PLATFORM), providers[0] if providers else None)
        models = []
        if provider is not None:
            models = await db.query_shared(
                "SELECT * FROM ai_models WHERE provider = $p AND (alias = $name OR model_id = $name) "
                "AND enabled = true AND kind = $kind",
                p=_rid(provider["id"]), name=name, kind=data.kind,
            )
        if not models:
            raise ServiceError("ERRO_AI_MODEL_UNAVAILABLE", f"Modelo {data.model} indisponível para esta organização.", 404)
        model = models[0]
        return Resolved(
            provider=provider["slug"],
            scope="platform" if provider["owner"] == PLATFORM else "organization",
            model=model["model_id"],
            base_url=provider["base_url"],
            api_key=_decrypt(provider["owner"], provider["slug"], provider["key"]),
            price_input=model.get("price_input", 0.0),
            price_output=model.get("price_output", 0.0),
        )

    async def record_usage(self, data: UsageEvent) -> Recorded:
        """events.ai.usage: tokens e custo (preço do momento da chamada), na organização de quem usou.

        Idempotente: o id estável da mensagem é único na tabela, então a reentrega do NATS não conta duas vezes."""
        who = _member()
        message = bus.message_id() or uuid.uuid4().hex
        cost = (data.input_tokens * data.price_input + data.output_tokens * data.price_output) / 1_000_000
        record = {**data.model_dump(exclude={"price_input", "price_output"}), "cost": cost, "actor": who.sub, "at": _now(), "message": message}
        try:
            row = await db.create(USAGE, record)
        except ServiceError as exc:
            if exc.code != "ERRO_RECORD_DUPLICATE":
                raise
            row = (await db.query("SELECT * FROM ai_usage WHERE tenant = $tenant AND message = $m", m=message))[0]
        return Recorded(id=row["id"], cost=row["cost"], at=row["at"])

    async def usage_summary(self, data: Empty) -> UsageSummary:
        _manager()
        start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = await db.query(
            "SELECT model, service, count() AS calls, math::sum(input_tokens) AS input_tokens, "
            "math::sum(output_tokens) AS output_tokens, math::sum(cost) AS cost "
            "FROM ai_usage WHERE tenant = $tenant AND at >= $start GROUP BY model, service ORDER BY cost DESC",
            start=start,
        )
        items = [UsageItem.model_validate(row) for row in rows]
        return UsageSummary(
            month=start.strftime("%Y-%m"),
            calls=sum(i.calls for i in items),
            input_tokens=sum(i.input_tokens for i in items),
            output_tokens=sum(i.output_tokens for i in items),
            cost=round(sum(i.cost for i in items), 6),
            items=items,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _provider(self, who: Principal, provider_id: str, *, manage: bool) -> dict:
        provider = await db.select(f"{PROVIDERS}:{provider_id}")
        if provider is None or provider["owner"] not in _owners(who):
            raise ServiceError("ERRO_AI_PROVIDER_NOT_FOUND", "Provedor não encontrado.", 404)
        if manage and provider["owner"] == PLATFORM and who.tenant != settings().platform_tenant:
            raise _forbidden()
        return provider

    async def _model_view(self, row: dict) -> Model:
        provider = await db.select(row["provider"])
        return _model_view({**row, "slug": provider["slug"] if provider else "?"})


async def _fetch_model_ids(provider: dict) -> list[str]:
    url = provider["base_url"] + "/models"
    key = _decrypt(provider["owner"], provider["slug"], provider["key"])
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        if provider["owner"] == PLATFORM:  # da plataforma pode estar na rede interna (Ollama, vLLM)
            async with _internal_client() as client:
                reply = await client.get(url, headers=headers)
        else:
            reply = await http.get(url, headers=headers, timeout=20)
        reply.raise_for_status()
        return [item["id"] for item in reply.json().get("data", []) if isinstance(item, dict) and item.get("id")]
    except (httpx.HTTPError, ValueError, KeyError):
        raise ServiceError("ERRO_AI_DISCOVERY_FAILED", "O provedor não listou os modelos (confira endereço e chave).", 502) from None


def _internal_client() -> httpx.AsyncClient:
    """Para provedores da plataforma, que podem estar na rede interna: sem redirect e sem cookie."""
    return httpx.AsyncClient(timeout=20, follow_redirects=False, cookies=no_cookie_jar())


def _model_record(provider: dict, model_id: str, kind: str, *, enabled: bool) -> dict:
    return {
        "owner": provider["owner"],
        "provider": _rid(provider["id"]),
        "model_id": model_id,
        "alias": None,
        "kind": kind,
        "enabled": enabled,
        "price_input": 0.0,
        "price_output": 0.0,
        "created_at": _now(),
    }


def _provider_view(row: dict) -> Provider:
    return Provider(
        id=_key(row["id"]),
        name=row["name"],
        slug=row["slug"],
        base_url=row["base_url"],
        key_hint=f"…{row['key_hint']}" if row.get("key_hint") else "",
        scope="platform" if row["owner"] == PLATFORM else "organization",
    )


def _model_view(row: dict) -> Model:
    return Model(
        id=_key(row["id"]),
        name=f"{row['slug']}/{row.get('alias') or row['model_id']}",
        provider=_key(row["provider"]),
        model_id=row["model_id"],
        alias=row.get("alias"),
        kind=row["kind"],
        enabled=row["enabled"],
        price_input=row.get("price_input", 0.0),
        price_output=row.get("price_output", 0.0),
        scope="platform" if row["owner"] == PLATFORM else "organization",
    )


def _member() -> Principal:
    who = current()
    if who is None or not who.tenant:
        raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", 403)
    return who


def _manager() -> Principal:
    who = _member()
    if not MANAGERS & who.roles:
        raise _forbidden()
    return who


def _owners(who: Principal) -> list[str]:
    """Donos visíveis para quem age: a própria organização e, se configurada, a plataforma."""
    return [who.tenant, PLATFORM] if settings().platform_tenant else [who.tenant]


def _visible(who: Principal) -> dict[str, str]:
    """Parâmetros $org e $plat das consultas. Sem IN de propósito: no SurrealDB embutido (testes), IN sobre o 1º campo
    de um índice composto devolve vazio; com OR o resultado é o mesmo no embutido e no servidor."""
    return {"org": who.tenant, "plat": PLATFORM if settings().platform_tenant else who.tenant}


def _owner_for(who: Principal, scope: str) -> str:
    if scope == "platform":
        if not settings().platform_tenant or who.tenant != settings().platform_tenant:
            raise _forbidden()
        return PLATFORM
    return who.tenant


async def _safe_url(url: str) -> None:
    try:
        await assert_public_url(url)
    except ServiceError:
        raise ServiceError(
            "ERRO_AI_UNSAFE_URL", "O endereço do provedor precisa ser https e público (rede interna só para a plataforma).", 422
        ) from None


def _aead() -> AESGCM:
    raw = settings().ai_secrets_key.get_secret_value()
    key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    if len(key) != 32:
        raise RuntimeError("AI_SECRETS_KEY precisa de 32 bytes (base64url): rode uv run python -m core.security keygen")
    return AESGCM(key)


def _encrypt(owner: str, slug: str, secret: str) -> str:
    nonce = os.urandom(12)
    sealed = _aead().encrypt(nonce, secret.encode(), f"{owner}:{slug}".encode())
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def _decrypt(owner: str, slug: str, blob: str) -> str:
    raw = base64.urlsafe_b64decode(blob)
    return _aead().decrypt(raw[:12], raw[12:], f"{owner}:{slug}".encode()).decode()


def _forbidden() -> ServiceError:
    return ServiceError("ERRO_AI_FORBIDDEN", "Só donos e administradores gerenciam a IA da organização.", 403)


def _now() -> datetime:
    return datetime.now(UTC)


def _key(record_id: str) -> str:
    return record_id.partition(":")[2].strip("⟨⟩`")


def _rid(record_id: str) -> RecordID:
    table, _, key = record_id.partition(":")
    return RecordID(table, key.strip("⟨⟩`"))
