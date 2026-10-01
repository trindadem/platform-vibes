"""svc-plans · lógica de negócio pura. Fonte da verdade: specs/plans.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "plans.<método>".
Helpers começam com _ e nunca viram activities.

Serviço de plataforma (README §5.17): guarda o catálogo de limites que os serviços declaram, os planos (geridos por
quem administra a plataforma, PLATFORM_TENANT), o plano de cada organização e o consumo do mês. Quem confere o limite
é o core/plans.py, no serviço que vai criar ou gastar; aqui só se resolve, soma e avisa.
"""
import functools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from surrealdb import RecordID

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import notify
from core.security import Principal, acting_as, current, current_tenant, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    ACCOUNTS,
    ALERTS,
    CONTACTS_SUBJECT,
    COUNTS,
    KEEP_LOG_DAYS,
    KEEP_MONTHS,
    MANAGERS,
    NO_PLAN,
    SERVICE,
    TIERS,
    USAGE,
    USAGE_LIVE,
    USAGE_LOG,
    Account,
    Assigned,
    AssignInput,
    AssignRequest,
    CatalogLimit,
    Cleaned,
    Contacts,
    ContactsRequest,
    CountReport,
    Current,
    Empty,
    LimitCatalog,
    LimitList,
    LimitsRequest,
    LimitState,
    Plan,
    PlanInput,
    PlanLimits,
    PlanList,
    PlanRef,
    PlansSettings,
    PlanUpdate,
    UsageChanged,
    UsageReport,
)

# Mudanças de dados versionadas, rodadas uma vez por banco no boot (README §5.13). Nunca edite uma já publicada.
MIGRATIONS: list[Migration] = []

# Bloco atômico: a linha da mensagem e a soma do mês entram juntas ou nenhuma. Mensagem repetida (reentrega do NATS)
# viola o índice único da linha e nada é somado.
_ADD_USAGE = """{
    CREATE plan_usage_log CONTENT { tenant: $tenant, message: $message, name: $name, month: $month, amount: $amount };
    LET $row = (UPDATE plan_usage SET used += $amount
        WHERE tenant = $tenant AND name = $name AND month = $month RETURN AFTER)[0];
    IF $row = NONE {
        LET $new = CREATE ONLY plan_usage CONTENT { tenant: $tenant, name: $name, month: $month, used: $amount, alerted: 0 };
        RETURN $new;
    };
    RETURN $row;
}"""


@functools.cache
def settings() -> PlansSettings:
    return PlansSettings()


@activities("plans")
class PlansService:
    # ── Organização (qualquer membro) ───────────────────────────────────────

    async def current(self, data: Empty) -> Current:
        who = _member()
        tier = await self._tier_of(who.tenant)
        resolved = await self.resolve(LimitsRequest())
        return Current(
            tenant=who.tenant, plan=_plan(tier) if tier else None, month=resolved.month, limits=resolved.limits,
            manages_platform=_manages_platform(who),
        )

    async def list_plans(self, data: Empty) -> PlanList:
        """Os públicos e o da própria organização; quem administra a plataforma vê todos."""
        who = _member()
        tier = await self._tier_of(who.tenant)
        manages = _manages_platform(who)
        rows = await db.query_shared(
            "SELECT * FROM plan_tiers WHERE public = true OR slug = $current OR $all = true ORDER BY price, name",
            current=tier["slug"] if tier else "", all=manages,
        )
        return PlanList(items=[_plan(row) for row in rows], current=tier["slug"] if tier else None, manages_platform=manages)

    async def list_limits(self, data: Empty) -> LimitList:
        _member()
        rows = await db.query_shared("SELECT * FROM plan_limits ORDER BY name")
        return LimitList(items=[_catalog(row) for row in rows])

    # ── Planos (quem administra a plataforma) ───────────────────────────────

    async def create_plan(self, data: PlanInput) -> Plan:
        _platform_manager()
        record = {
            "slug": data.slug, "name": data.name, "description": data.description, "price": data.price,
            "currency": data.currency, "public": data.public, "is_default": data.default,
            "limits": await _checked_limits(data.limits),
        }
        try:
            row = await db.create(TIERS, record)
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_PLANS_SLUG_TAKEN", f"Já existe um plano {data.slug}.", 409) from None
            raise
        if data.default:
            await _only_default(data.slug)
        return _plan(row)

    async def update_plan(self, data: PlanUpdate) -> Plan:
        _platform_manager()
        row = await _tier(data.slug)
        changes = data.model_dump(exclude={"slug", "default", "limits"}, exclude_none=True)
        if data.limits is not None:
            changes["limits"] = await _checked_limits(data.limits)
        if data.default is not None:
            changes["is_default"] = data.default
        if changes:
            row = await db.merge(row["id"], changes)
        if data.default:
            await _only_default(data.slug)
        return _plan(row)

    async def remove_plan(self, data: PlanRef) -> PlanList:
        _platform_manager()
        row = await _tier(data.slug)
        if row.get("is_default"):
            raise ServiceError("ERRO_PLANS_IN_USE", "Este é o plano padrão: marque outro como padrão antes de remover.", 409)
        using = await db.query_shared(
            "SELECT count() AS total FROM (SELECT id FROM plan_accounts WHERE plan = $slug) GROUP ALL", slug=data.slug
        )
        if using and using[0]["total"]:
            raise ServiceError(
                "ERRO_PLANS_IN_USE", f"{using[0]['total']} organização(ões) usam este plano: troque o plano delas antes.", 409
            )
        await db.delete(row["id"])
        return await self.list_plans(Empty())

    async def assign_plan(self, data: AssignInput) -> Account:
        """Pela tela: quem administra a plataforma troca o plano de uma organização, pelo id dela."""
        who = _platform_manager()
        tier = await _tier(data.plan)
        with acting_as(system(SERVICE, data.tenant)):
            found = await bus.request(CONTACTS_SUBJECT, ContactsRequest(), Contacts, timeout=5)
            if not found.tenant_name:
                raise ServiceError("ERRO_PLANS_TENANT_NOT_FOUND", "Organização não encontrada.", 404)
            await self._assign(tier, by=who.sub)
        return Account(tenant=data.tenant, tenant_name=found.tenant_name, plan=tier["slug"], plan_name=tier["name"])

    async def assign(self, data: AssignRequest) -> Assigned:
        """rpc.plans.assign: o serviço de pagamentos do produto troca o plano, como tarefa da plataforma."""
        who = current()
        if who is None or not who.is_system:
            raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só tarefas da plataforma trocam o plano por aqui.", 403)
        tier = await _tier(data.plan)
        await self._assign(tier, by=who.sub)
        return Assigned(tenant=current_tenant(), plan=tier["slug"], plan_name=tier["name"])

    # ── Serviços (core/plans.py) ────────────────────────────────────────────

    async def resolve(self, data: LimitsRequest) -> PlanLimits:
        """rpc.plans.limits: plano da organização de quem pergunta, valores de cada limite e consumo do mês."""
        tenant = current_tenant()
        tier = await self._tier_of(tenant)
        values = _values(tier)
        month = _month()
        sums = {row["name"]: row["used"] for row in await db.query(
            "SELECT name, used FROM plan_usage WHERE tenant = $tenant AND month = $month", month=month
        )}
        totals = {row["name"]: row["total"] for row in await db.query("SELECT name, total FROM plan_counts WHERE tenant = $tenant")}
        states = []
        for row in await db.query_shared("SELECT * FROM plan_limits ORDER BY name"):
            limit = _catalog(row)
            states.append(LimitState(
                **limit.model_dump(),
                limit=values[limit.name] if limit.name in values else limit.default,
                used=sums.get(limit.name, 0.0) if limit.monthly else totals.get(limit.name, 0),
            ))
        return PlanLimits(plan=tier["slug"] if tier else None, plan_name=tier["name"] if tier else NO_PLAN, month=month, limits=states)

    async def record_catalog(self, data: LimitCatalog) -> Empty:
        for limit in data.limits:
            await db.query_shared(
                "UPSERT $id SET name = $name, service = $service, description = $description, default_value = $default, "
                "monthly = $monthly, unit = $unit, currency = $currency",
                id=RecordID("plan_limits", limit.name), name=limit.name, service=data.service, description=limit.description,
                default=limit.default, monthly=limit.monthly, unit=limit.unit, currency=limit.currency,
            )
        await db.query_shared(  # o que saiu da lista do serviço sai do catálogo
            "DELETE plan_limits WHERE service = $service AND name NOT IN $names",
            service=data.service, names=[limit.name for limit in data.limits],
        )
        return Empty()

    async def record_usage(self, data: UsageReport) -> UsageChanged:
        """events.plans.usage: soma no mês da organização de quem consumiu, uma vez por mensagem."""
        message = bus.message_id() or uuid.uuid4().hex
        params = {"message": message, "name": data.name, "month": data.month, "amount": data.amount}
        try:
            row = await db.query(_ADD_USAGE, **params)
        except ServiceError as exc:
            if exc.code != "ERRO_RECORD_DUPLICATE":
                raise
            seen = await db.query("SELECT id FROM plan_usage_log WHERE tenant = $tenant AND message = $message", message=message)
            if not seen:
                raise  # duas mensagens criaram a soma do mês ao mesmo tempo: a reentrega do NATS soma esta
            row = (await db.query(
                "SELECT * FROM plan_usage WHERE tenant = $tenant AND name = $name AND month = $month", name=data.name, month=data.month
            ))[0]
            return UsageChanged(name=data.name, used=row["used"])  # reentrega: já somado e avisado
        changed = UsageChanged(name=data.name, used=row["used"])
        await bus.live(USAGE_LIVE, changed)  # a tela Plano aberta atualiza sozinha
        await self._alert(row)
        return changed

    async def record_count(self, data: CountReport) -> UsageChanged:
        """events.plans.count: o total que o serviço informou, se for mais novo que o guardado."""
        params = {"name": data.name, "total": data.total, "at": data.at}
        updated = await db.query(
            "UPDATE plan_counts SET total = $total, at = $at WHERE tenant = $tenant AND name = $name AND at < $at RETURN AFTER",
            **params,
        )
        if not updated:
            older = await db.query("SELECT total FROM plan_counts WHERE tenant = $tenant AND name = $name", name=data.name)
            if older:
                return UsageChanged(name=data.name, used=older[0]["total"])  # chegou depois de um total mais novo
            await db.create(COUNTS, params)
        changed = UsageChanged(name=data.name, used=data.total)
        await bus.live(USAGE_LIVE, changed)
        return changed

    # ── Manutenção (agendamento diário) ─────────────────────────────────────

    async def cleanup(self, data: Empty) -> Cleaned:
        before = _now() - timedelta(days=KEEP_LOG_DAYS)
        oldest = _month(_now() - timedelta(days=31 * KEEP_MONTHS))
        removed_log = removed_usage = 0
        for org in await db.tenants(USAGE_LOG):
            with acting_as(system(SERVICE, org)):
                gone = await db.query(
                    "DELETE plan_usage_log WHERE tenant = $tenant AND created_at < $before RETURN BEFORE", before=before
                )
                removed_log += len(gone or [])
        for org in await db.tenants(USAGE):
            with acting_as(system(SERVICE, org)):
                gone = await db.query("DELETE plan_usage WHERE tenant = $tenant AND month < $oldest RETURN BEFORE", oldest=oldest)
                removed_usage += len(gone or [])
        return Cleaned(usage_log=removed_log, usage=removed_usage)

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _tier_of(self, org: str) -> dict | None:
        """Plano em vigor: o atribuído à organização ou, sem ele, o padrão (None: sem plano, valem os defaults)."""
        rows = await db.query_shared(
            "SELECT * FROM plan_tiers WHERE slug = (SELECT VALUE plan FROM plan_accounts WHERE org = $org)[0]", org=org
        )
        if rows:
            return rows[0]
        rows = await db.query_shared("SELECT * FROM plan_tiers WHERE is_default = true ORDER BY slug LIMIT 1")
        return rows[0] if rows else None

    async def _assign(self, tier: dict, *, by: str) -> None:
        """Troca o plano da organização atual e recomeça os patamares de aviso do mês."""
        org = current_tenant()
        rows = await db.query_shared("SELECT id FROM plan_accounts WHERE org = $org", org=org)
        if rows:
            await db.merge(rows[0]["id"], {"plan": tier["slug"], "assigned_by": by})
        else:
            await db.create(ACCOUNTS, {"org": org, "plan": tier["slug"], "assigned_by": by})
        await db.query("UPDATE plan_usage SET alerted = 0 WHERE tenant = $tenant AND month = $month", month=_month())

    async def _alert(self, row: dict) -> None:
        """Avisa donos e administradores ao cruzar 80% e 100% de um limite mensal (uma vez por mês e por patamar)."""
        if row["month"] != _month() or row.get("alerted", 0) >= ALERTS[0]:
            return
        tier = await self._tier_of(current_tenant())
        catalog = await db.query_shared("SELECT * FROM plan_limits WHERE name = $name", name=row["name"])
        if not catalog:
            return
        limit = _catalog(catalog[0])
        values = _values(tier)
        value = values[limit.name] if limit.name in values else limit.default
        if not value:  # sem limite (None) ou fora do plano (0): nada a avisar
            return
        reached = next((threshold for threshold in ALERTS if row["used"] >= value * threshold / 100), None)
        if reached is None or row.get("alerted", 0) >= reached:
            return
        claimed = await db.query(
            "UPDATE plan_usage SET alerted = $level WHERE tenant = $tenant AND id = $id AND alerted < $level RETURN AFTER",
            id=_rid(row["id"]), level=reached,
        )
        if not claimed:
            return  # outra mensagem já avisou este patamar
        plan = tier["name"] if tier else NO_PLAN
        ending = (
            "O limite foi atingido: o uso fica bloqueado até o mês que vem ou até a troca de plano."
            if reached >= 100
            else "Ao chegar a 100%, o uso fica bloqueado até o mês que vem ou até a troca de plano."
        )
        await notify.roles(
            "owner", "admin",
            title=f"{limit.description[:90]}: {reached}% do limite",
            body=f"A organização usou {reached}% do que o plano {plan} permite neste mês.\n\n{ending}",
            link="/plano",
            action="Ver plano",
            key=f"plano-{limit.name}-{row['month']}-{reached}",
        )


async def _tier(slug: str) -> dict:
    rows = await db.query_shared("SELECT * FROM plan_tiers WHERE slug = $slug", slug=slug)
    if not rows:
        raise ServiceError("ERRO_PLANS_NOT_FOUND", "Plano não encontrado.", 404)
    return rows[0]


async def _only_default(slug: str) -> None:
    await db.query_shared("UPDATE plan_tiers SET is_default = false WHERE is_default = true AND slug != $slug", slug=slug)


async def _checked_limits(limits: dict[str, float | None]) -> list[dict[str, Any]]:
    """Só limites do catálogo; guardados como lista de { name, value } (o nome tem ponto: não serve de chave)."""
    known = set(await db.query_shared("SELECT VALUE name FROM plan_limits WHERE name IN $names", names=list(limits)))
    if unknown := sorted(set(limits) - known):
        raise ServiceError("ERRO_PLANS_UNKNOWN_LIMIT", f"Limite fora do catálogo: {', '.join(unknown)}.", 422)
    return [{"name": name, "value": value} for name, value in sorted(limits.items())]


def _values(tier: dict | None) -> dict[str, float | None]:
    """Limites que o plano cita. Sem value (o banco não guarda nulo dentro do objeto): sem limite."""
    return {item["name"]: item.get("value") for item in (tier or {}).get("limits", [])}


def _plan(row: dict) -> Plan:
    return Plan(
        slug=row["slug"], name=row["name"], description=row.get("description", ""), price=row["price"],
        currency=row["currency"], public=row["public"], default=bool(row.get("is_default")), limits=_values(row),
    )


def _catalog(row: dict) -> CatalogLimit:
    return CatalogLimit(
        name=row["name"], service=row["service"], description=row["description"], default=row.get("default_value"),
        monthly=row["monthly"], unit=row.get("unit") or "", currency=row.get("currency"),
    )


def _member() -> Principal:
    who = current()
    if who is None or not who.tenant:
        raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", 403)
    return who


def _manages_platform(who: Principal) -> bool:
    platform = settings().platform_tenant
    return bool(platform) and who.tenant == platform and bool(MANAGERS & who.roles)


def _platform_manager() -> Principal:
    who = _member()
    if not _manages_platform(who):
        raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só quem administra a plataforma gerencia os planos.", 403)
    return who


def _now() -> datetime:
    return datetime.now(UTC)


def _month(at: datetime | None = None) -> str:
    return (at or _now()).strftime("%Y-%m")


def _rid(record_id: str) -> RecordID:
    table, _, key = record_id.partition(":")
    return RecordID(table, key.strip("⟨⟩`"))
