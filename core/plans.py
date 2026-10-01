"""Módulos, planos e limites (README §5.17): o que cada organização usa, ligado pelo plano e conferido pelo core.

    MODULE = Module("Webhooks", "Eventos para os sistemas da organização", category="Integrações",
                    limits=[Limit("enderecos", "Endereços de webhook", default=20, unit="endereços")])  # schemas.py
    await plans.declare(MODULE)                        # main.py, no lifespan (depois do bus)
    await plans.check("enderecos", used=total)         # antes de criar: 402 ERRO_PLAN_LIMIT se já chegou ao limite
    await plans.count("enderecos", total)              # depois de criar ou remover: a tela mostra "3 de 20"

    Limit("custo", "Gasto com IA no mês", monthly=True, currency="USD")
    await plans.check("custo")                         # antes de gastar: quem já passou do limite do mês para aqui
    await plans.use("custo", 0.0123, key=message_id)   # depois de gastar: soma no mês; aviso em 80% e em 100%

Trilhos:
- Todo serviço é um módulo, com o nome dele (sem svc-). Módulo desligado para a organização recusa as chamadas das
  pessoas dela com 402 ERRO_PLAN_MODULE (HTTP, evento e RPC), sem código no serviço: o core confere antes. Tarefa da
  plataforma (system) passa. core=True: módulo da plataforma, sempre ligado.
- Ligado ou não: o ajuste da organização, senão o plano, senão o default declarado; e só com os requires ligados.
- O limite se chama <serviço>.<nome> (webhooks.enderecos). Só o próprio serviço declara, conta e soma os seus; conferir
  vale também com o nome completo de outro serviço (o core/llm.py confere ai.custo em quem chama a IA).
- O valor vem do plano da organização atual. Limite que o plano não cita, ou organização sem plano, vale o default
  declarado. None: sem limite. 0: o recurso não está no plano.
- Total (padrão): quem conta é o serviço, dono dos dados (used=), antes de criar. Mensal: o svc-plans soma o uso do mês
  (UTC); a chamada que cruza o limite termina e as seguintes param.
- Resolução guardada 60 s por processo: troca de plano, de módulo ou de limite vale em até 1 min. Com o svc-plans fora
  do ar, vale a última resposta e, sem ela, nenhum limite e todo módulo ligado: plano é regra comercial, não de
  segurança.
- Cobrança fica no produto: o serviço de pagamentos confirma o pagamento e, como tarefa da plataforma
  (acting_as(system(SERVICE, org))), chama plans.assign("pro") (ou plans.assign("pro", modules={"juridico": True})).
"""
import hashlib
import logging
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from nats.errors import NoRespondersError
from pydantic import BaseModel, Field, StringConstraints

from core.envelope import ServiceError
from core.nats_bus import bus
from core.security import Principal, add_gate, current, current_tenant

__all__ = [
    "plans", "Plans", "Module", "Limit", "ModuleCatalog", "CatalogModule", "CatalogLimit", "ModuleState", "LimitState",
    "PlanLimits", "LimitsRequest", "UsageReport", "CountReport", "AssignRequest", "Assigned", "ModuleName", "PlanSlug",
    "CATALOG_SUBJECT", "USAGE_SUBJECT", "COUNT_SUBJECT", "LIMITS_SUBJECT", "ASSIGN_SUBJECT",
]

CATALOG_SUBJECT = "events.plans.catalog"
USAGE_SUBJECT = "events.plans.usage"
COUNT_SUBJECT = "events.plans.count"
LIMITS_SUBJECT = "rpc.plans.limits"
ASSIGN_SUBJECT = "rpc.plans.assign"
CACHE_SECONDS = 60
_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_FULL = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*\.[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

log = logging.getLogger("core.plans")

PlanSlug = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", max_length=40)]
ModuleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", max_length=40)]


@dataclass(frozen=True)
class Limit:
    """Um limite que o serviço confere: nome curto (kebab-case), o que mede e o valor quando o plano não diz nada.

    monthly=True: consumo somado no mês (plans.use). Senão, total do que existe agora (o serviço conta: used=).
    unit: o que se conta, no plural ("pessoas", "tokens"); currency: moeda ISO, para limite em dinheiro ("USD").
    """

    name: str
    description: str
    default: float | None = None
    monthly: bool = False
    unit: str = ""
    currency: str | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name) or len(self.name) > 40:
            raise ValueError(f"Limit: nome inválido {self.name!r} (kebab-case, ex.: membros, custo)")
        if not 3 <= len(self.description) <= 120:
            raise ValueError(f"Limit {self.name!r}: descrição de 3 a 120 caracteres")
        if self.default is not None and self.default < 0:
            raise ValueError(f"Limit {self.name!r}: default é None (sem limite) ou um número a partir de 0")
        if self.currency is not None and not _CURRENCY.match(self.currency):
            raise ValueError(f"Limit {self.name!r}: currency é o código ISO da moeda (ex.: USD, BRL)")
        if len(self.unit) > 30:
            raise ValueError(f"Limit {self.name!r}: unit até 30 caracteres")


@dataclass(frozen=True)
class Module:
    """O serviço como módulo da plataforma: o que a organização liga pelo plano e vê no menu (o nome é o do serviço).

    title, description: como aparece no menu, no plano e na comparação. category: o grupo no menu ("Comercial").
    limits: o que o módulo limita. requires: módulos sem os quais este não funciona (nomes de serviço, sem svc-).
    core=True: módulo da plataforma, sempre ligado. default: ligado quando o plano não diz nada (e sem plano).
    """

    title: str
    description: str
    category: str = "Geral"
    limits: Sequence[Limit] = ()
    requires: Sequence[str] = ()
    core: bool = False
    default: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "limits", tuple(self.limits))
        object.__setattr__(self, "requires", tuple(self.requires))
        if not 2 <= len(self.title) <= 40:
            raise ValueError(f"Module {self.title!r}: título de 2 a 40 caracteres")
        if not 3 <= len(self.description) <= 200:
            raise ValueError(f"Module {self.title!r}: descrição de 3 a 200 caracteres")
        if not 2 <= len(self.category) <= 30:
            raise ValueError(f"Module {self.title!r}: categoria de 2 a 30 caracteres")
        names = [limit.name for limit in self.limits]
        if len(names) != len(set(names)):
            raise ValueError(f"Module {self.title!r}: limite repetido")
        for required in self.requires:
            if not _NAME.match(required) or required.startswith("svc-"):
                raise ValueError(f"Module {self.title!r}: requires {required!r} é o nome de outro serviço, sem svc-")
        if self.core and self.requires:
            raise ValueError(f"Module {self.title!r}: módulo da plataforma (core) não depende de outro")


class CatalogLimit(BaseModel):
    name: str = Field(..., description="Nome completo: <serviço>.<limite>")
    service: str
    description: str
    default: float | None = Field(..., description="Valor sem plano (ou que o plano não cita); null: sem limite")
    monthly: bool = Field(..., description="Consumo somado no mês (true) ou total do que existe agora (false)")
    unit: str = ""
    currency: str | None = None


class CatalogModule(BaseModel):
    name: str = Field(..., description="Nome do serviço, sem svc- (o mesmo de /api/v1/<nome>)")
    service: str
    title: str
    description: str
    category: str = Field(..., description="Grupo no menu")
    core: bool = Field(..., description="Módulo da plataforma: sempre ligado")
    default: bool = Field(..., description="Ligado quando o plano não diz nada (e para quem não tem plano)")
    requires: list[str] = Field(..., description="Módulos sem os quais este não funciona")


class ModuleCatalog(BaseModel):
    """events.plans.catalog: o módulo que um serviço declara e os limites dele (o limite que sai da lista sai do catálogo)."""

    service: str
    module: CatalogModule
    limits: list[CatalogLimit]


class ModuleState(CatalogModule):
    enabled: bool = Field(..., description="Ligado para a organização: ajuste dela, plano ou default, com os requires ligados")


class LimitState(CatalogLimit):
    limit: float | None = Field(..., description="O que o plano permite (ou o default); null: sem limite")
    used: float = Field(..., description="Mensal: soma do mês. Total: o último total que o serviço informou")


class PlanLimits(BaseModel):
    """rpc.plans.limits: módulos e limites da organização de quem pergunta, já resolvidos."""

    plan: str | None = Field(..., description="Slug do plano; null: sem plano (valem os defaults)")
    plan_name: str
    month: str = Field(..., description="AAAA-MM, em UTC: o mês dos consumos")
    limits: list[LimitState]
    modules: list[ModuleState] = Field(default_factory=list)

    def get(self, name: str) -> LimitState | None:
        return next((state for state in self.limits if state.name == name), None)

    def module(self, name: str) -> ModuleState | None:
        return next((state for state in self.modules if state.name == name), None)


class LimitsRequest(BaseModel):
    pass


class UsageReport(BaseModel):
    """events.plans.usage: consumo de um limite mensal na organização do cabeçalho."""

    name: str
    amount: float = Field(..., gt=0)
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="Mês (UTC) em que aconteceu")


class CountReport(BaseModel):
    """events.plans.count: total atual de um limite total, para a tela mostrar "3 de 20"."""

    name: str
    total: int = Field(..., ge=0)
    at: datetime


class AssignRequest(BaseModel):
    """rpc.plans.assign: troca o plano da organização do cabeçalho (só tarefa da plataforma)."""

    plan: PlanSlug
    modules: dict[ModuleName, bool] | None = Field(
        None, description="Ajuste da organização: módulo → ligado, além do plano. null: mantém o ajuste; {}: só o plano"
    )


class Assigned(BaseModel):
    tenant: str
    plan: str
    plan_name: str
    modules: dict[str, bool] = Field(default_factory=dict, description="Ajuste da organização além do plano")


class Plans:
    def __init__(self) -> None:
        self._module: Module | None = None
        self._declared: dict[str, Limit] = {}
        self._cache: dict[str, tuple[float, PlanLimits]] = {}

    async def declare(self, module: Module) -> None:
        """No boot: guarda o módulo deste serviço e os limites dele e publica o catálogo para o svc-plans (o plano, o
        menu e a comparação os listam). Daí em diante, chamada de quem tem o módulo desligado é recusada."""
        service = _service()
        prefix = service.removeprefix("svc-")
        if prefix in module.requires:
            raise ValueError(f"plans.declare: o módulo {prefix} não depende de si mesmo")
        self._module = module
        self._declared = {f"{prefix}.{limit.name}": limit for limit in module.limits}
        catalog = ModuleCatalog(
            service=service,
            module=CatalogModule(
                name=prefix, service=service, title=module.title, description=module.description, category=module.category,
                core=module.core, default=module.default, requires=list(module.requires),
            ),
            limits=[
                CatalogLimit(
                    name=name, service=service, description=limit.description, default=limit.default, monthly=limit.monthly,
                    unit=limit.unit, currency=limit.currency,
                )
                for name, limit in self._declared.items()
            ],
        )
        digest = hashlib.sha256(catalog.model_dump_json().encode()).hexdigest()[:24]
        await bus.publish(CATALOG_SUBJECT, catalog, msg_id=f"catalog-{service}-{digest}")  # réplicas: um só

    async def enabled(self, name: str) -> bool:
        """O módulo <name> (nome do serviço, sem svc-) está ligado para a organização atual? Para mostrar ou usar uma
        integração opcional com outro módulo. Sem resposta do svc-plans: ligado."""
        if not _NAME.match(name) or name.startswith("svc-"):
            raise ValueError(f"plans.enabled: {name!r} é o nome de um serviço, sem svc-")
        resolved = await self._resolve()
        state = resolved.module(name) if resolved is not None else None
        return True if state is None else state.enabled

    async def check(self, name: str, *, used: float | None = None, adding: float = 1) -> None:
        """Confere o limite na organização atual. Total: used= é quanto existe agora e adding= quanto vai entrar.
        Mensal (sem used=): para quem já chegou ao limite do mês. Passou → ServiceError 402 ERRO_PLAN_LIMIT."""
        full, own = self._resolve_name(name)
        if own is not None and own.monthly != (used is None):
            hint = "sem used= (o svc-plans soma o mês)" if own.monthly else "com used= (quanto existe agora)"
            raise ValueError(f"plans.check({name!r}): limite {'mensal' if own.monthly else 'total'} se confere {hint}")
        resolved = await self._resolve()
        if resolved is None:  # svc-plans fora do ar e nenhuma resposta guardada: plano não é regra de segurança
            return
        state = resolved.get(full)
        info: LimitState | Limit | None = state or own  # o svc-plans ainda não conhece o limite: vale o declarado
        limit = state.limit if state is not None else (own.default if own is not None else None)
        if info is None or limit is None:
            return
        reached = (state.used if state else 0) >= limit if used is None else used + adding > limit
        if reached:
            plan = f"do plano {resolved.plan_name}" if resolved.plan else "da organização"
            raise ServiceError(
                "ERRO_PLAN_LIMIT", f"Limite {plan} atingido: {info.description}, até {_amount(limit, info)}. Veja em Plano.", status=402
            )

    async def use(self, name: str, amount: float, *, key: str | None = None) -> None:
        """Soma consumo de um limite mensal deste serviço na organização atual (durável). key= evita contar duas vezes."""
        full, own = self._own(name)
        if not own.monthly:
            raise ValueError(f"plans.use({name!r}): é para limite mensal; total se informa com plans.count")
        if amount < 0:
            raise ValueError("plans.use: amount não pode ser negativo")
        current_tenant()  # sem organização, falha aqui (e não em silêncio no svc-plans)
        if amount == 0:
            return
        if key is not None and not _KEY.match(key):
            raise ValueError(f"plans.use: key inválida {key!r} (letras, números e _ . : -, até 120)")
        msg_id = f"usage-{_service()}-{key}" if key else f"usage-{uuid.uuid4().hex}"
        await bus.publish(USAGE_SUBJECT, UsageReport(name=full, amount=amount, month=_month()), msg_id=msg_id)

    async def count(self, name: str, total: int) -> None:
        """Informa o total atual de um limite total deste serviço (depois de criar ou remover), para a tela."""
        full, own = self._own(name)
        if own.monthly:
            raise ValueError(f"plans.count({name!r}): é para limite total; consumo do mês se soma com plans.use")
        current_tenant()
        await bus.publish(COUNT_SUBJECT, CountReport(name=full, total=total, at=datetime.now(UTC)))

    async def limits(self) -> PlanLimits:
        """Módulos e limites da organização atual (plano, valores e consumo do mês), guardados por 60 s. Com o svc-plans
        fora do ar e sem resposta guardada: nenhum limite e nenhum módulo (listas vazias)."""
        return await self._resolve() or PlanLimits(plan=None, plan_name="", month=_month(), limits=[])

    async def _resolve(self) -> PlanLimits | None:
        tenant = current_tenant()
        cached = self._cache.get(tenant)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            resolved = await bus.request(LIMITS_SUBJECT, LimitsRequest(), PlanLimits, timeout=2)
        except (TimeoutError, NoRespondersError) as exc:  # o TimeoutError do nats também é um TimeoutError
            return self._unavailable(cached, exc)
        except ServiceError as exc:
            if exc.status < 500:
                raise
            return self._unavailable(cached, exc)
        self._cache[tenant] = (time.monotonic() + CACHE_SECONDS, resolved)
        return resolved

    async def assign(self, plan: str, *, modules: dict[str, bool] | None = None) -> Assigned:
        """Troca o plano da organização atual. Só tarefa da plataforma: o serviço de pagamentos do produto, depois de
        confirmar, com acting_as(system(SERVICE, org)). modules= ajusta módulos além do plano (um módulo avulso
        comprado: {"juridico": True}); None mantém o ajuste. Plano inexistente → 404 ERRO_PLANS_NOT_FOUND."""
        who = current()
        if who is None or not who.is_system:
            raise PermissionError("plans.assign é para tarefas da plataforma: acting_as(system(SERVICE, org))")
        tenant = current_tenant()
        assigned = await bus.request(ASSIGN_SUBJECT, AssignRequest(plan=plan, modules=modules), Assigned, timeout=5)
        self._cache.pop(tenant, None)
        return assigned

    def clear(self) -> None:
        """Esquece as resoluções guardadas (ex.: testes ou logo depois de trocar um plano)."""
        self._cache.clear()

    async def _gate(self, who: Principal) -> None:
        """Conferência do core em toda chamada de uma pessoa (core/security.py): módulo deste serviço desligado para a
        organização dela → 402 ERRO_PLAN_MODULE. Módulo da plataforma, ou ainda não declarado, passa."""
        module = self._module
        if module is None or module.core:
            return
        resolved = await self._resolve()
        if resolved is None:
            return
        state = resolved.module(_service().removeprefix("svc-"))
        if state is None:  # o svc-plans ainda não gravou o catálogo deste serviço: vale o default declarado
            if module.default:
                return
        elif state.enabled:
            return
        plan = f"no plano {resolved.plan_name}" if resolved.plan else "para a organização"
        raise ServiceError("ERRO_PLAN_MODULE", f"{module.title} não está incluído {plan}. Veja em Plano.", status=402)

    def _unavailable(self, cached: tuple[float, PlanLimits] | None, exc: Exception) -> PlanLimits | None:
        log.warning("svc-plans não respondeu (%s): %s", type(exc).__name__, "vale a última resposta" if cached else "sem limites")
        return cached[1] if cached else None

    def _resolve_name(self, name: str) -> tuple[str, Limit | None]:
        """Nome curto: limite deste serviço (precisa estar declarado). Nome completo: de qualquer serviço."""
        if _FULL.match(name):
            return name, self._declared.get(name)
        return self._own(name)

    def _own(self, name: str) -> tuple[str, Limit]:
        full = f"{_service().removeprefix('svc-')}.{name}"
        own = self._declared.get(full)
        if own is None:
            raise ValueError(f"plans: limite {full!r} não declarado (Module(limits=[...]) e plans.declare no lifespan, README §5.17)")
        return full, own


def _amount(value: float, limit: Limit | CatalogLimit) -> str:
    number = f"{value:,.2f}" if limit.currency else f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    number = number.replace(",", "_").replace(".", ",").replace("_", ".")
    if limit.currency:
        return f"{limit.currency} {number}"
    return number if value == 1 else f"{number} {limit.unit}".strip()  # a unidade é plural: "2 pessoas", "1"


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _service() -> str:
    if bus.service is None:
        raise RuntimeError("plans: bus não conectado (async with bus.connected(SERVICE) no lifespan)")
    return bus.service


plans = Plans()
add_gate(plans._gate)  # módulo desligado recusa a chamada antes do serviço (HTTP, evento e RPC)
