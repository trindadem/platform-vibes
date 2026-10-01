"""svc-plans · lógica de negócio pura. Fonte da verdade: specs/plans.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "plans.<método>".
Helpers começam com _ e nunca viram activities.

Serviço de plataforma (README §5.17): guarda o catálogo de módulos e limites que os serviços declaram, os planos
(geridos por quem administra a plataforma, PLATFORM_TENANT), o plano e o ajuste de módulos de cada organização e o
consumo do mês. Quem confere é o core/plans.py, no serviço chamado (módulo) ou que vai criar ou gastar (limite); aqui
só se resolve, soma e avisa.
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
    MODULE_CATALOG,
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
    AccountRef,
    Assigned,
    AssignInput,
    AssignRequest,
    Catalog,
    CatalogLimit,
    CatalogModule,
    Cleaned,
    Contacts,
    ContactsRequest,
    CountReport,
    Current,
    Empty,
    LimitsRequest,
    LimitState,
    ModuleCatalog,
    ModuleList,
    ModuleState,
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
        tier, _ = await self._plan_of(who.tenant)
        resolved = await self.resolve(LimitsRequest())
        return Current(
            tenant=who.tenant, plan=_plan(tier) if tier else None, month=resolved.month, limits=resolved.limits,
            modules=resolved.modules, manages_platform=_manages_platform(who),
        )

    async def modules(self, data: Empty) -> ModuleList:
        """Os módulos e se cada um está ligado para a organização ativa: o menu da tela esconde os desligados."""
        _member()
        return ModuleList(items=(await self.resolve(LimitsRequest())).modules)

    async def list_plans(self, data: Empty) -> PlanList:
        """Os públicos e o da própria organização; quem administra a plataforma vê todos."""
        who = _member()
        tier, _ = await self._plan_of(who.tenant)
        manages = _manages_platform(who)
        rows = await db.query_shared(
            "SELECT * FROM plan_tiers WHERE public = true OR slug = $current OR $all = true ORDER BY price, name",
            current=tier["slug"] if tier else "", all=manages,
        )
        return PlanList(items=[_plan(row) for row in rows], current=tier["slug"] if tier else None, manages_platform=manages)

    async def catalog(self, data: Empty) -> Catalog:
        _member()
        return Catalog(modules=list((await _module_catalog()).values()), limits=await _limit_catalog())

    # ── Planos (quem administra a plataforma) ───────────────────────────────

    async def create_plan(self, data: PlanInput) -> Plan:
        _platform_manager()
        record = {
            "slug": data.slug, "name": data.name, "description": data.description, "price": data.price,
            "currency": data.currency, "public": data.public, "is_default": data.default,
            "limits": await _checked_limits(data.limits), "modules": await _checked_modules(data.modules, {}),
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
        changes = data.model_dump(exclude={"slug", "default", "limits", "modules"}, exclude_none=True)
        if data.limits is not None:
            changes["limits"] = await _checked_limits(data.limits)
        if data.modules is not None:
            changes["modules"] = await _checked_modules(data.modules, {})
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

    async def account(self, data: AccountRef) -> Account:
        """Pela tela: quem administra a plataforma vê o plano e o ajuste de módulos de uma organização, pelo id dela."""
        _platform_manager()
        name = await _tenant_name(data.tenant)
        tier, account = await self._plan_of(data.tenant)
        return Account(
            tenant=data.tenant, tenant_name=name, plan=tier["slug"] if tier else None, plan_name=tier["name"] if tier else NO_PLAN,
            assigned=account is not None, modules=_flags(account, "modules"),
        )

    async def assign_plan(self, data: AssignInput) -> Account:
        """Pela tela: quem administra a plataforma troca o plano (e o ajuste de módulos) de uma organização, pelo id."""
        who = _platform_manager()
        tier = await _tier(data.plan)
        name = await _tenant_name(data.tenant)
        with acting_as(system(SERVICE, data.tenant)):
            modules = await self._assign(tier, data.modules, by=who.sub)
        return Account(
            tenant=data.tenant, tenant_name=name, plan=tier["slug"], plan_name=tier["name"], assigned=True, modules=modules
        )

    async def assign(self, data: AssignRequest) -> Assigned:
        """rpc.plans.assign: o serviço de pagamentos do produto troca o plano, como tarefa da plataforma."""
        who = current()
        if who is None or not who.is_system:
            raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só tarefas da plataforma trocam o plano por aqui.", 403)
        tier = await _tier(data.plan)
        modules = await self._assign(tier, data.modules, by=who.sub)
        return Assigned(tenant=current_tenant(), plan=tier["slug"], plan_name=tier["name"], modules=modules)

    # ── Serviços (core/plans.py) ────────────────────────────────────────────

    async def resolve(self, data: LimitsRequest) -> PlanLimits:
        """rpc.plans.limits: plano da organização de quem pergunta, módulos ligados, valores de cada limite e consumo
        do mês."""
        tenant = current_tenant()
        tier, account = await self._plan_of(tenant)
        values = _values(tier)
        month = _month()
        sums = {row["name"]: row["used"] for row in await db.query(
            "SELECT name, used FROM plan_usage WHERE tenant = $tenant AND month = $month", month=month
        )}
        totals = {row["name"]: row["total"] for row in await db.query("SELECT name, total FROM plan_counts WHERE tenant = $tenant")}
        states = [
            LimitState(
                **limit.model_dump(),
                limit=values[limit.name] if limit.name in values else limit.default,
                used=sums.get(limit.name, 0.0) if limit.monthly else totals.get(limit.name, 0),
            )
            for limit in await _limit_catalog()
        ]
        return PlanLimits(
            plan=tier["slug"] if tier else None, plan_name=tier["name"] if tier else NO_PLAN, month=month, limits=states,
            modules=_module_states(await _module_catalog(), tier, account),
        )

    async def record_catalog(self, data: ModuleCatalog) -> Empty:
        """events.plans.catalog: o módulo e os limites que um serviço declarou no boot."""
        module = data.module
        await db.query_shared(
            "UPSERT $id SET name = $name, service = $service, title = $title, description = $description, "
            "category = $category, is_core = $core, default_enabled = $default, requires = $requires",
            id=RecordID(MODULE_CATALOG, module.name), name=module.name, service=data.service, title=module.title,
            description=module.description, category=module.category, core=module.core, default=module.default,
            requires=module.requires,
        )
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

    async def _plan_of(self, org: str) -> tuple[dict | None, dict | None]:
        """Plano em vigor (o atribuído ou, sem ele, o padrão; None: sem plano, valem os defaults) e a linha da
        organização em plan_accounts (o ajuste de módulos), se houver."""
        accounts = await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org)
        account = accounts[0] if accounts else None
        if account:
            rows = await db.query_shared("SELECT * FROM plan_tiers WHERE slug = $slug", slug=account["plan"])
            if rows:
                return rows[0], account
        rows = await db.query_shared("SELECT * FROM plan_tiers WHERE is_default = true ORDER BY slug LIMIT 1")
        return (rows[0] if rows else None), account

    async def _assign(self, tier: dict, modules: dict[str, bool] | None, *, by: str) -> dict[str, bool]:
        """Troca o plano da organização atual (e o ajuste de módulos, se veio) e recomeça os patamares de aviso do
        mês. Devolve o ajuste que ficou."""
        org = current_tenant()
        rows = await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org)
        own = _flags(rows[0] if rows else None, "modules") if modules is None else modules
        stored = await _checked_modules(own, _flags(tier, "modules"))
        record = {"plan": tier["slug"], "modules": stored, "assigned_by": by}
        if rows:
            await db.merge(rows[0]["id"], record)
        else:
            await db.create(ACCOUNTS, {"org": org, **record})
        await db.query("UPDATE plan_usage SET alerted = 0 WHERE tenant = $tenant AND month = $month", month=_month())
        return {item["name"]: item["enabled"] for item in stored}

    async def _alert(self, row: dict) -> None:
        """Avisa donos e administradores ao cruzar 80% e 100% de um limite mensal (uma vez por mês e por patamar)."""
        if row["month"] != _month() or row.get("alerted", 0) >= ALERTS[0]:
            return
        tier, _ = await self._plan_of(current_tenant())
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


async def _checked_modules(modules: dict[str, bool], base: dict[str, bool]) -> list[dict[str, Any]]:
    """Só módulos do catálogo; os da plataforma ficam sempre ligados (ligar é ignorado, desligar é erro). Quem fica
    ligado precisa dos requires ligados, contando base (o plano, para o ajuste de uma organização) e os defaults."""
    catalog = await _module_catalog()
    if unknown := sorted(set(modules) - set(catalog)):
        raise ServiceError("ERRO_PLANS_UNKNOWN_MODULE", f"Módulo fora do catálogo: {', '.join(unknown)}.", 422)
    if core := sorted(catalog[name].title for name, on in modules.items() if catalog[name].core and not on):
        raise ServiceError("ERRO_PLANS_CORE_MODULE", f"{', '.join(core)}: módulo da plataforma, sempre ligado.", 422)
    chosen = {name: module.core or modules.get(name, base.get(name, module.default)) for name, module in catalog.items()}
    for name in sorted(name for name, on in modules.items() if on):  # quem liga precisa dos requires ligados
        if missing := [required for required in catalog[name].requires if not chosen.get(required, False)]:
            titles = ", ".join(catalog[required].title if required in catalog else required for required in missing)
            raise ServiceError(
                "ERRO_PLANS_MODULE_REQUIRES", f"{catalog[name].title} precisa de {titles}: ligue também ou desligue {catalog[name].title}.", 422
            )
    for name in sorted(name for name, on in modules.items() if not on):  # quem desliga não pode faltar a um ligado
        if needed_by := [catalog[other].title for other in catalog if chosen[other] and name in catalog[other].requires]:
            raise ServiceError(
                "ERRO_PLANS_MODULE_REQUIRES", f"{', '.join(needed_by)} precisa de {catalog[name].title}: desligue também ou mantenha ligado.", 422
            )
    return [{"name": name, "enabled": on} for name, on in sorted(modules.items()) if not catalog[name].core]


def _module_states(catalog: dict[str, CatalogModule], tier: dict | None, account: dict | None) -> list[ModuleState]:
    """Ligado: módulo da plataforma; senão o ajuste da organização, o plano ou o default. E só com os requires ligados
    (requisito fora do catálogo, não instalado, desliga quem depende dele)."""
    plan, own = _flags(tier, "modules"), _flags(account, "modules")
    chosen = {name: module.core or own.get(name, plan.get(name, module.default)) for name, module in catalog.items()}
    effective: dict[str, bool] = {}

    def on(name: str, path: tuple[str, ...] = ()) -> bool:
        if name in effective:
            return effective[name]
        if not chosen.get(name, False) or name in path:  # fora do catálogo, desligado ou dependência circular
            return False
        effective[name] = all(on(required, (*path, name)) for required in catalog[name].requires)
        return effective[name]

    return [ModuleState(**module.model_dump(), enabled=on(name)) for name, module in catalog.items()]


async def _module_catalog() -> dict[str, CatalogModule]:
    """Os módulos que os serviços declararam; numa instalação dedicada (MODULES), só os da plataforma e os instalados."""
    rows = await db.query_shared("SELECT * FROM plan_modules ORDER BY category, title")
    chosen = settings().installed()
    return {row["name"]: _module(row) for row in rows if chosen is None or row.get("is_core") or row["name"] in chosen}


async def _limit_catalog() -> list[CatalogLimit]:
    return [_catalog(row) for row in await db.query_shared("SELECT * FROM plan_limits ORDER BY name")]


async def _tenant_name(tenant: str) -> str:
    """Nome da organização pelo svc-identity; inexistente → 404."""
    with acting_as(system(SERVICE, tenant)):
        found = await bus.request(CONTACTS_SUBJECT, ContactsRequest(), Contacts, timeout=5)
    if not found.tenant_name:
        raise ServiceError("ERRO_PLANS_TENANT_NOT_FOUND", "Organização não encontrada.", 404)
    return found.tenant_name


def _flags(row: dict | None, field: str) -> dict[str, bool]:
    """Lista de { name, enabled } (módulos do plano ou o ajuste da organização) → módulo → ligado."""
    return {item["name"]: bool(item["enabled"]) for item in (row or {}).get(field) or []}


def _values(tier: dict | None) -> dict[str, float | None]:
    """Limites que o plano cita. Sem value (o banco não guarda nulo dentro do objeto): sem limite."""
    return {item["name"]: item.get("value") for item in (tier or {}).get("limits", [])}


def _plan(row: dict) -> Plan:
    return Plan(
        slug=row["slug"], name=row["name"], description=row.get("description", ""), price=row["price"],
        currency=row["currency"], public=row["public"], default=bool(row.get("is_default")), limits=_values(row),
        modules=_flags(row, "modules"),
    )


def _catalog(row: dict) -> CatalogLimit:
    return CatalogLimit(
        name=row["name"], service=row["service"], description=row["description"], default=row.get("default_value"),
        monthly=row["monthly"], unit=row.get("unit") or "", currency=row.get("currency"),
    )


def _module(row: dict) -> CatalogModule:
    return CatalogModule(
        name=row["name"], service=row["service"], title=row["title"], description=row["description"],
        category=row["category"], core=bool(row.get("is_core")), default=bool(row.get("default_enabled")),
        requires=row.get("requires") or [],
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
