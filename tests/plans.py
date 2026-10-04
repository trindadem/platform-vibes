"""svc-plans · testes sem infraestrutura. Fonte da verdade: specs/plans.md §2 e §4

SurrealDB embutido em memória (mem://), com as tabelas e índices do boot e a SurrealQL de verdade (inclusive o bloco
atômico que soma o consumo); o NATS vira dublê e o svc-identity responde o nome das organizações.

Rodar (da raiz): PYTHONPATH=services/svc-plans uv run python -m pytest tests/plans.py
"""
import asyncio
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nats.errors import NoRespondersError
from pydantic import ValidationError
from surrealdb import AsyncSurreal

from core import nats_bus
from core.envelope import ServiceError
from core.notify import SEND_SUBJECT
from core.plans import CatalogLimit, CatalogModule, CountReport, LimitsRequest, ModuleCatalog, UsageReport
from core.security import Principal, acting_as, system
from core.storage import StoredFile
from core.surreal import DataPage

import service
from schemas import (
    SHARED_TABLES,
    TENANT_TABLES,
    UNIQUE,
    USAGE_LIVE,
    CONTACTS_SUBJECT,
    ENCERRADA_SUBJECT,
    INICIAR_MODELO_SUBJECT,
    PURGE_SUBJECT,
    AccountRef,
    AssignInput,
    AssignRequest,
    CancelamentoIn,
    Contacts,
    ContaAcao,
    Empty,
    ExportacaoRef,
    FechamentoIn,
    PlanInput,
    PlanRef,
    PlanUpdate,
)

PLATAFORMA = Principal(sub="ana", tenant="plat", roles=frozenset({"owner"}))
ACME = Principal(sub="bia", tenant="acme", roles=frozenset({"owner"}))
ACME_MEMBRO = Principal(sub="caio", tenant="acme", roles=frozenset({"member"}))
BETA = Principal(sub="duda", tenant="beta", roles=frozenset({"admin"}))
ORGS = {"acme": "Acme", "beta": "Beta", "plat": "Plataforma"}
MES = datetime.now(UTC).strftime("%Y-%m")

def _modulo(name, title, category, core=False, default=True, requires=()):
    return CatalogModule(name=name, service=f"svc-{name}", title=title, description=f"Módulo {title}", category=category,
                         core=core, default=default, requires=list(requires))


CATALOGO = [
    ModuleCatalog(service="svc-ai", module=_modulo("ai", "IA", "Integrações", core=True), limits=[
        CatalogLimit(name="ai.custo", service="svc-ai", description="Gasto com IA no mês", default=None, monthly=True, currency="USD"),
        CatalogLimit(name="ai.tokens", service="svc-ai", description="Tokens de IA no mês", default=None, monthly=True, unit="tokens"),
    ]),
    ModuleCatalog(service="svc-webhooks", module=_modulo("webhooks", "Webhooks", "Integrações", core=True), limits=[
        CatalogLimit(name="webhooks.enderecos", service="svc-webhooks", description="Endereços de webhook", default=20, monthly=False, unit="endereços"),
    ]),
    ModuleCatalog(service="svc-crm", module=_modulo("crm", "CRM", "Comercial"), limits=[]),
    ModuleCatalog(service="svc-vendas", module=_modulo("vendas", "Vendas", "Comercial", requires=["crm"]), limits=[]),
    ModuleCatalog(service="svc-juridico", module=_modulo("juridico", "Jurídico", "Serviços", default=False), limits=[]),
    ModuleCatalog(service="svc-relatorios", module=_modulo("relatorios", "Relatórios", "Gestão", requires=["bi"]), limits=[]),
]


@pytest.fixture(autouse=True)
def box(monkeypatch):
    """PLATFORM_TENANT=plat, NATS em memória e o svc-identity respondendo o nome das organizações."""
    monkeypatch.setenv("PLATFORM_TENANT", "plat")
    service.settings.cache_clear()
    state = SimpleNamespace(published=[], live=[], contacts=[], responders={}, emails={"acme": "bia@acme.com"})

    async def publish(subject, message, msg_id=None):
        state.published.append((subject, message, msg_id))

    async def live(topic, message, user=None):
        state.live.append((topic, message.name, message.used))

    async def request(subject, message, response_model, timeout=5.0):
        tenant = service.current_tenant()
        state.contacts.append((subject, tenant, service.current().sub))
        if subject in state.responders:
            answer = state.responders[subject](message)
            return response_model.model_validate(answer.model_dump() if hasattr(answer, "model_dump") else answer)
        if subject != CONTACTS_SUBJECT:
            raise NoRespondersError
        dono = [{"id": "dono", "name": "Dono", "email": state.emails[tenant]}] if tenant in state.emails and message.roles else []
        return Contacts(tenant_name=ORGS.get(tenant, ""), items=dono)

    monkeypatch.setattr(service.bus, "publish", publish)
    monkeypatch.setattr(service.bus, "live", live)
    monkeypatch.setattr(service.bus, "request", request)
    monkeypatch.setattr(service.bus, "_service", "svc-plans")
    yield state
    service.settings.cache_clear()


def run(cenario):
    async def go():
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        service.db._conn = conn
        async with service.db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE):
            svc = service.PlansService()
            for catalog in CATALOGO:
                await svc.record_catalog(catalog)
            return await cenario(svc)

    return asyncio.run(go())


async def como(who, call):
    with acting_as(who):
        return await call()


async def uso(svc, who, name, amount, message, month=MES):
    """Como o handler do NATS entrega: em nome de quem consumiu e com o id estável da mensagem."""
    token = nats_bus._message_id.set(message)
    try:
        return await como(who, lambda: svc.record_usage(UsageReport(name=name, amount=amount, month=month)))
    finally:
        nats_bus._message_id.reset(token)


async def planos(svc):
    async def criar():
        await svc.create_plan(PlanInput(slug="gratis", name="Grátis", default=True, limits={"ai.custo": 1, "webhooks.enderecos": 2}))
        await svc.create_plan(PlanInput(slug="pro", name="Pro", price=99, limits={"ai.custo": 50, "ai.tokens": None}))
        await svc.create_plan(PlanInput(slug="sob-medida", name="Sob medida", price=999, public=False))

    await como(PLATAFORMA, criar)


def _erro(exc, code, status):
    assert (exc.value.code, exc.value.status) == (code, status), exc.value.code


def _limites(resolved):
    return {s.name: (s.limit, s.used) for s in resolved.limits}


def _ligados(resolved):
    return sorted(m.name for m in resolved.modules if m.enabled)


# ── Catálogo e resolução ────────────────────────────────────────────────────

def test_sem_plano_valem_os_defaults_declarados():
    async def cenario(svc):
        mudou = CATALOGO[0].model_copy(update={"limits": CATALOGO[0].limits[:1]})  # tokens saiu da lista
        await svc.record_catalog(mudou)
        return await como(ACME, lambda: svc.resolve(LimitsRequest())), await como(ACME, lambda: svc.catalog(Empty()))

    resolved, catalogo = run(cenario)
    assert (resolved.plan, resolved.plan_name, resolved.month) == (None, "Sem plano", MES)
    assert _limites(resolved) == {"ai.custo": (None, 0.0), "webhooks.enderecos": (20, 0)}
    assert [c.name for c in catalogo.limits] == ["ai.custo", "webhooks.enderecos"]  # o que saiu da lista sai do catálogo
    # Por categoria e título. Jurídico não vem ligado sem plano; Relatórios precisa de BI, que não está instalado.
    assert [(m.category, m.name) for m in catalogo.modules] == [
        ("Comercial", "crm"), ("Comercial", "vendas"), ("Gestão", "relatorios"), ("Integrações", "ai"),
        ("Integrações", "webhooks"), ("Serviços", "juridico")]
    assert _ligados(resolved) == ["ai", "crm", "vendas", "webhooks"]


def test_plano_padrao_vale_para_quem_nao_tem_e_atribuido_vale_para_quem_tem(box):
    async def cenario(svc):
        await planos(svc)
        antes = await como(ACME, lambda: svc.resolve(LimitsRequest()))
        conta = await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro")))
        depois = await como(ACME, lambda: svc.resolve(LimitsRequest()))
        beta = await como(BETA, lambda: svc.resolve(LimitsRequest()))
        atual = await como(ACME_MEMBRO, lambda: svc.current(Empty()))
        return antes, conta, depois, beta, atual

    antes, conta, depois, beta, atual = run(cenario)
    assert (antes.plan, _limites(antes)) == ("gratis", {"ai.custo": (1, 0.0), "ai.tokens": (None, 0.0), "webhooks.enderecos": (2, 0)})
    assert conta.model_dump() == {"tenant": "acme", "tenant_name": "Acme", "plan": "pro", "plan_name": "Pro", "assigned": True, "modules": {}}
    assert box.contacts == [("rpc.identity.contacts", "acme", "system:svc-plans")]  # confere a organização no svc-identity
    # O plano cita null (sem limite) para tokens e nada para endereços: vale o default declarado (20).
    assert (depois.plan, _limites(depois)) == ("pro", {"ai.custo": (50, 0.0), "ai.tokens": (None, 0.0), "webhooks.enderecos": (20, 0)})
    assert beta.plan == "gratis"
    assert (atual.tenant, atual.plan.slug, atual.plan.price, atual.manages_platform) == ("acme", "pro", 99, False)


def test_so_quem_administra_a_plataforma_gerencia_e_atribui():
    async def cenario(svc):
        await planos(svc)
        erros = []
        for who, call in (
            (ACME, lambda: svc.create_plan(PlanInput(slug="x", name="Xis"))),
            (BETA, lambda: svc.update_plan(PlanUpdate(slug="pro", price=1))),
            (ACME, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro"))),
            (Principal(sub="eva", tenant="plat", roles=frozenset({"member"})), lambda: svc.remove_plan(PlanRef(slug="pro"))),
            (ACME, lambda: svc.assign(AssignRequest(plan="pro"))),  # RPC: só tarefa da plataforma
        ):
            with pytest.raises(ServiceError) as exc:
                await como(who, call)
            erros.append((exc.value.code, exc.value.status))
        return erros

    assert run(cenario) == [("ERRO_PLANS_FORBIDDEN", 403)] * 5


def test_trilhos_dos_planos():
    async def cenario(svc):
        await planos(svc)
        resultados = []
        for call in (
            lambda: svc.create_plan(PlanInput(slug="gratis", name="De novo")),
            lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", limits={"ai.inexistente": 1})),
            lambda: svc.update_plan(PlanUpdate(slug="nao-existe", price=1)),
            lambda: svc.assign_plan(AssignInput(tenant="fantasma", plan="pro")),
            lambda: svc.assign_plan(AssignInput(tenant="acme", plan="nao-existe")),
        ):
            with pytest.raises(ServiceError) as exc:
                await como(PLATAFORMA, call)
            resultados.append((exc.value.code, exc.value.status))
        return resultados

    assert run(cenario) == [
        ("ERRO_PLANS_SLUG_TAKEN", 409), ("ERRO_PLANS_UNKNOWN_LIMIT", 422), ("ERRO_PLANS_NOT_FOUND", 404),
        ("ERRO_PLANS_TENANT_NOT_FOUND", 404), ("ERRO_PLANS_NOT_FOUND", 404),
    ]
    with pytest.raises(ValidationError):
        PlanInput(slug="pro", name="Pro", limits={"ai.custo": -1})
    with pytest.raises(ValidationError):
        PlanInput(slug="Pro Max", name="Pro")


def test_um_padrao_so_comparacao_publica_e_remocao_protegida():
    async def cenario(svc):
        await planos(svc)
        await como(PLATAFORMA, lambda: svc.update_plan(PlanUpdate(slug="pro", default=True, limits={"ai.custo": 80})))
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="beta", plan="sob-medida")))
        todos = await como(PLATAFORMA, lambda: svc.list_plans(Empty()))
        acme = await como(ACME, lambda: svc.list_plans(Empty()))
        beta = await como(BETA, lambda: svc.list_plans(Empty()))
        erros = []
        for slug in ("pro", "sob-medida"):  # padrão e em uso não saem
            with pytest.raises(ServiceError) as exc:
                await como(PLATAFORMA, lambda: svc.remove_plan(PlanRef(slug=slug)))
            erros.append(exc.value.code)
        sobra = await como(PLATAFORMA, lambda: svc.remove_plan(PlanRef(slug="gratis")))
        return todos, acme, beta, erros, sobra

    todos, acme, beta, erros, sobra = run(cenario)
    assert [(p.slug, p.default) for p in todos.items] == [("gratis", False), ("pro", True), ("sob-medida", False)]
    assert todos.manages_platform and todos.items[1].limits == {"ai.custo": 80}
    assert ([p.slug for p in acme.items], acme.current) == (["gratis", "pro"], "pro")  # o sob medida não aparece
    assert ([p.slug for p in beta.items], beta.current) == (["gratis", "pro", "sob-medida"], "sob-medida")  # o seu aparece
    assert erros == ["ERRO_PLANS_IN_USE", "ERRO_PLANS_IN_USE"]
    assert [p.slug for p in sobra.items] == ["pro", "sob-medida"]


# ── Módulos: plano, ajuste da organização e requisitos ──────────────────────

def test_modulos_vem_do_plano_e_do_ajuste_da_organizacao():
    async def cenario(svc):
        await planos(svc)
        await como(PLATAFORMA, lambda: svc.update_plan(PlanUpdate(slug="gratis", modules={"crm": True, "vendas": False})))
        await como(PLATAFORMA, lambda: svc.update_plan(PlanUpdate(slug="pro", modules={"juridico": True})))
        gratis = await como(ACME, lambda: svc.resolve(LimitsRequest()))  # sem plano atribuído: o padrão (grátis)
        conta = await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro", modules={"vendas": False})))
        ajustado = await como(ACME, lambda: svc.resolve(LimitsRequest()))
        mantido = await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro")))  # null: mantém
        acme = await como(PLATAFORMA, lambda: svc.account(AccountRef(tenant="acme")))
        beta = await como(PLATAFORMA, lambda: svc.account(AccountRef(tenant="beta")))
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro", modules={})))  # {}: só o plano
        so_plano = await como(ACME_MEMBRO, lambda: svc.modules(Empty()))
        pro = (await como(PLATAFORMA, lambda: svc.list_plans(Empty()))).items[1]
        return gratis, conta, ajustado, mantido, acme, beta, so_plano, pro

    gratis, conta, ajustado, mantido, acme, beta, so_plano, pro = run(cenario)
    assert _ligados(gratis) == ["ai", "crm", "webhooks"]
    assert conta.modules == {"vendas": False} and mantido.modules == {"vendas": False}
    assert _ligados(ajustado) == ["ai", "crm", "juridico", "webhooks"]  # pro com Jurídico, menos Vendas (só para a Acme)
    assert (acme.plan, acme.assigned, acme.modules, acme.tenant_name) == ("pro", True, {"vendas": False}, "Acme")
    assert (beta.plan, beta.assigned, beta.modules) == ("gratis", False, {})  # sem atribuição: vale o padrão
    assert sorted(m.name for m in so_plano.items if m.enabled) == ["ai", "crm", "juridico", "vendas", "webhooks"]
    assert (pro.slug, pro.modules) == ("pro", {"juridico": True})


def test_instalacao_dedicada_so_lista_os_modulos_instalados(monkeypatch):
    monkeypatch.setenv("MODULES", "crm")
    service.settings.cache_clear()

    async def cenario(svc):
        return await como(ACME, lambda: svc.resolve(LimitsRequest())), await como(ACME, lambda: svc.catalog(Empty()))

    resolved, catalogo = run(cenario)
    assert sorted(m.name for m in catalogo.modules) == ["ai", "crm", "webhooks"]  # vendas, jurídico e relatórios: fora
    assert _ligados(resolved) == ["ai", "crm", "webhooks"]


def test_trilhos_dos_modulos():
    async def cenario(svc):
        await planos(svc)
        resultados = []
        for call in (
            lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", modules={"estoque": True})),
            lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", modules={"ai": False})),
            lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", modules={"crm": False, "vendas": True})),
            lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", modules={"crm": False})),  # vendas vem ligado
            lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", modules={"relatorios": True})),  # BI não instalado
            lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro", modules={"crm": False})),
        ):
            with pytest.raises(ServiceError) as exc:
                await como(PLATAFORMA, call)
            resultados.append((exc.value.code, exc.value.status, exc.value.message))
        ok = await como(PLATAFORMA, lambda: svc.create_plan(PlanInput(slug="novo", name="Novo", modules={"ai": True, "crm": False, "vendas": False})))
        return resultados, ok

    resultados, ok = run(cenario)
    assert [(code, status) for code, status, _ in resultados] == [
        ("ERRO_PLANS_UNKNOWN_MODULE", 422), ("ERRO_PLANS_CORE_MODULE", 422), ("ERRO_PLANS_MODULE_REQUIRES", 422),
        ("ERRO_PLANS_MODULE_REQUIRES", 422), ("ERRO_PLANS_MODULE_REQUIRES", 422), ("ERRO_PLANS_MODULE_REQUIRES", 422),
    ]
    assert resultados[2][2] == "Vendas precisa de CRM: ligue também ou desligue Vendas."
    assert resultados[3][2] == "Vendas precisa de CRM: desligue também ou mantenha ligado."
    assert "bi" in resultados[4][2]
    assert ok.modules == {"crm": False, "vendas": False}  # o da plataforma não é guardado: está sempre ligado
    with pytest.raises(ValidationError):
        PlanInput(slug="x", name="Xis", modules={"Vendas": True})


def test_rpc_assign_com_modulo_avulso():
    async def cenario(svc):
        await planos(svc)
        trocado = await como(system("svc-pagamentos", "acme"), lambda: svc.assign(AssignRequest(plan="gratis", modules={"juridico": True})))
        return trocado, await como(ACME, lambda: svc.resolve(LimitsRequest()))

    trocado, resolved = run(cenario)
    assert trocado.modules == {"juridico": True} and "juridico" in _ligados(resolved)


# ── Consumo do mês, totais e avisos ─────────────────────────────────────────

def test_consumo_soma_no_mes_uma_vez_por_mensagem_e_avisa_em_80_e_100(box):
    async def cenario(svc):
        await planos(svc)  # grátis (padrão): ai.custo = 1
        for message, amount in (("m1", 0.5), ("m1", 0.5), ("m2", 0.35), ("m3", 0.1), ("m4", 0.2), ("m5", 0.3)):
            await uso(svc, ACME, "ai.custo", amount, message)
        await uso(svc, BETA, "ai.custo", 0.9, "b1")
        await uso(svc, ACME, "ai.custo", 7, "antigo", month="2020-01")  # mês passado não conta no mês atual
        return await como(ACME, lambda: svc.resolve(LimitsRequest())), await como(BETA, lambda: svc.resolve(LimitsRequest()))

    acme, beta = run(cenario)
    assert _limites(acme)["ai.custo"] == (1, pytest.approx(1.45))  # m1 repetida (reentrega) somou uma vez
    assert _limites(beta)["ai.custo"] == (1, pytest.approx(0.9))
    avisos = [(m.title, m.roles, m.link, msg_id, m.send_email) for subject, m, msg_id in box.published if subject == SEND_SUBJECT]
    assert avisos == [
        ("Gasto com IA no mês: 80% do limite", ["owner", "admin"], "/plano", f"notify-svc-plans-acme-plano-ai.custo-{MES}-80", True),
        ("Gasto com IA no mês: 100% do limite", ["owner", "admin"], "/plano", f"notify-svc-plans-acme-plano-ai.custo-{MES}-100", True),
        ("Gasto com IA no mês: 80% do limite", ["owner", "admin"], "/plano", f"notify-svc-plans-beta-plano-ai.custo-{MES}-80", True),
    ]  # acme: 80% em m2 e 100% em m4, uma vez cada; beta: 80% (outro id: a mesma key em outra organização não é duplicata)
    assert (USAGE_LIVE, "ai.custo", 0.5) in box.live and len([e for e in box.live if e[1] == "ai.custo"]) == 7


def test_trocar_de_plano_recomeca_os_avisos_do_mes(box):
    async def cenario(svc):
        await planos(svc)
        await uso(svc, ACME, "ai.custo", 0.9, "m1")  # 90% do grátis
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro")))
        await uso(svc, ACME, "ai.custo", 40, "m2")  # 81% do pro: novo aviso
        await uso(svc, ACME, "ai.tokens", 10_000, "m3")  # pro: sem limite de tokens, nada a avisar

    run(cenario)
    titulos = [m.title for subject, m, _ in box.published if subject == SEND_SUBJECT]
    assert titulos == ["Gasto com IA no mês: 80% do limite", "Gasto com IA no mês: 80% do limite"]


def test_total_guarda_o_mais_novo():
    agora = datetime.now(UTC)

    async def cenario(svc):
        for total, quando in ((3, agora), (5, agora + timedelta(seconds=2)), (4, agora + timedelta(seconds=1))):
            await como(ACME, lambda: svc.record_count(CountReport(name="webhooks.enderecos", total=total, at=quando)))
        return await como(ACME, lambda: svc.resolve(LimitsRequest())), await como(BETA, lambda: svc.resolve(LimitsRequest()))

    acme, beta = run(cenario)
    assert _limites(acme)["webhooks.enderecos"] == (20, 5)  # o 4 chegou depois, mas é mais velho
    assert _limites(beta)["webhooks.enderecos"] == (20, 0)


def test_rpc_assign_troca_o_plano_como_tarefa_da_plataforma():
    async def cenario(svc):
        await planos(svc)
        trocado = await como(system("svc-pagamentos", "acme"), lambda: svc.assign(AssignRequest(plan="pro")))
        return trocado, await como(ACME, lambda: svc.resolve(LimitsRequest()))

    trocado, resolved = run(cenario)
    assert (trocado.tenant, trocado.plan, resolved.plan) == ("acme", "pro", "pro")


def test_limpeza_apaga_linhas_velhas_e_somas_de_mais_de_13_meses(monkeypatch):
    async def cenario(svc):
        await uso(svc, ACME, "ai.custo", 1, "m1")
        await uso(svc, BETA, "ai.custo", 1, "m2", month="2020-01")
        with acting_as(system("svc-plans")):
            hoje = await svc.cleanup(Empty())  # linhas recentes ficam; a soma de 2020 já passou de 13 meses
            depois = service._now() + timedelta(days=46)
            monkeypatch.setattr(service, "_now", lambda: depois)
            em_46_dias = await svc.cleanup(Empty())
        restam = await service.db.query_shared("SELECT VALUE month FROM plan_usage")
        return hoje, em_46_dias, restam

    hoje, em_46_dias, restam = run(cenario)
    assert (hoje.usage_log, hoje.usage, em_46_dias.usage_log, em_46_dias.usage, restam) == (0, 1, 2, 0, [MES])


def test_organizacao_e_campos_nao_vem_do_corpo():
    with pytest.raises(ValidationError):
        PlanInput.model_validate({"slug": "x", "name": "Xis", "tenant": "outra"})
    with pytest.raises(ValidationError):
        AssignInput.model_validate({"tenant": "acme", "plan": "pro", "by": "eu"})



# ── Conta: mensalidade, situação, cancelamento, fechamento e exportação (alinhamento pós-N7, itens 2 e 13) ──

STAFF_NO_ACME = system("svc-staff", "acme")


def _avisos(box):
    return [(m.title, sorted(m.roles or m.users)) for s, m, _ in box.published if s == SEND_SUBJECT]


def test_conta_do_cliente_pelo_staff_cobranca_suspensao_e_reativacao(box):
    async def cenario(svc):
        await planos(svc)
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro")))
        ver = await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="ver")))
        cobranca = await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="cobranca", valor=150, vencimento=15)))
        erros = []
        for who, acao in ((STAFF_NO_ACME, ContaAcao(acao="suspender")), (ACME, ContaAcao(acao="ver")),
                          (system("svc-staff", "plat"), ContaAcao(acao="ver")), (STAFF_NO_ACME, ContaAcao(acao="reativar"))):
            with pytest.raises(ServiceError) as exc:
                await como(who, lambda: svc.conta(acao))
            erros.append(exc.value.code)
        suspensa = await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="suspender", motivo="Mensalidade de outubro em aberto", por="gil")))
        resolvido = await como(ACME_MEMBRO, lambda: svc.resolve(LimitsRequest()))
        reativada = await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="reativar")))
        return ver, cobranca, erros, suspensa, resolvido, reativada

    ver, cobranca, erros, suspensa, resolvido, reativada = run(cenario)
    assert (ver.valor, ver.valor_combinado, ver.vencimento, ver.situacao) == (99, False, 10, "ativa")  # o preço do plano
    assert (cobranca.valor, cobranca.valor_combinado, cobranca.vencimento) == (150, True, 15)
    assert erros == ["ERRO_PLANS_MOTIVO", "ERRO_PLANS_FORBIDDEN", "ERRO_PLANS_PLATAFORMA", "ERRO_PLANS_SITUACAO"]
    assert (suspensa.situacao, suspensa.motivo) == ("suspensa", "Mensalidade de outubro em aberto")
    assert (resolvido.situacao, resolvido.aviso.startswith("Conta suspensa")) == ("suspensa", True)  # o core trava execuções novas
    assert reativada.situacao == "ativa" and reativada.aviso is None
    assert ("Conta suspensa", ["admin", "owner"]) in _avisos(box) and ("Conta reativada", ["admin", "owner"]) in _avisos(box)


def test_cancelamento_do_dono_vale_no_fim_do_mes_encerra_e_30_dias_depois_apaga(box, monkeypatch):
    apagados = []

    async def purge():
        apagados.append(service.current_tenant())
        return 3

    monkeypatch.setattr(service.storage, "purge", purge)

    async def cenario(svc):
        await planos(svc)
        with pytest.raises(ServiceError) as membro:
            await como(ACME_MEMBRO, lambda: svc.cancelar(CancelamentoIn(motivo="caro")))
        pedido = await como(ACME, lambda: svc.cancelar(CancelamentoIn(motivo="Vamos internalizar")))
        with pytest.raises(ServiceError) as de_novo:
            await como(ACME, lambda: svc.cancelar(CancelamentoIn()))
        desfeito = await como(ACME, lambda: svc.desfazer_cancelamento(Empty()))
        await como(ACME, lambda: svc.cancelar(CancelamentoIn()))
        efetivo = pedido.cancelamento.efetivo_em
        antes = await como(system("svc-plans"), lambda: svc.encerramentos(Empty()))  # o mês pago ainda não acabou
        monkeypatch.setattr(service, "_now", lambda: efetivo + timedelta(minutes=15))
        encerrou = await como(system("svc-plans"), lambda: svc.encerramentos(Empty()))
        encerrada = await como(ACME, lambda: svc.current(Empty()))
        situacao = await como(ACME, lambda: svc.resolve(LimitsRequest()))
        monkeypatch.setattr(service, "_now", lambda: efetivo + timedelta(days=30, minutes=20))
        apagou = await como(system("svc-plans"), lambda: svc.encerramentos(Empty()))
        sobrou = await service.db.query_shared("SELECT * FROM plan_accounts WHERE org = 'acme'")
        return membro.value, pedido, de_novo.value, desfeito, efetivo, antes, encerrou, encerrada.conta, situacao, apagou, sobrou

    membro, pedido, de_novo, desfeito, efetivo, antes, encerrou, encerrada, situacao, apagou, sobrou = run(cenario)
    assert membro.code == "ERRO_PLANS_FORBIDDEN" and de_novo.code == "ERRO_PLANS_JA_CANCELADA"
    hoje = datetime.now(service.ZoneInfo(service.FUSO))
    seguinte = (hoje.replace(day=28) + timedelta(days=4)).replace(day=1)
    assert efetivo.astimezone(service.ZoneInfo(service.FUSO)).strftime("%Y-%m-%d %H:%M") == f"{seguinte:%Y-%m-%d} 00:00"
    assert pedido.aviso.startswith("Cancelamento pedido: a conta funciona até") and pedido.pode_desfazer
    assert desfeito.cancelamento is None and desfeito.aviso is None
    assert (antes.encerradas, encerrou.encerradas) == (0, 1)
    assert (encerrada.situacao, encerrada.pode_desfazer, situacao.situacao) == ("encerrada", True, "encerrada")
    assert encerrada.exclusao_em - encerrada.encerrada_em == timedelta(days=30)
    eventos = [(s, getattr(m, "tenant", None), service.current_tenant) for s, m, _ in box.published if s in (ENCERRADA_SUBJECT, PURGE_SUBJECT)]
    assert [(s, t) for s, t, _ in eventos] == [(ENCERRADA_SUBJECT, "acme"), (PURGE_SUBJECT, "acme")]
    assert apagou.excluidas == 1 and apagados == ["acme"] and sobrou == []  # arquivos, linhas de todos e a conta
    assert ("Acme pediu o cancelamento", ["admin", "owner"]) in _avisos(box)  # os gestores da Cogniventure sabem


def test_cogniventure_encerra_o_suspenso_na_hora_e_o_ativo_no_fim_do_mes(box):
    async def cenario(svc):
        await planos(svc)
        await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="suspender", motivo="Atraso")))
        acme = await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="encerrar", motivo="Atraso de 60 dias", por="gil")))
        beta = await como(system("svc-staff", "beta"), lambda: svc.conta(ContaAcao(acao="encerrar")))
        with pytest.raises(ServiceError) as dono:  # o dono não desfaz o que a Cogniventure encerrou
            await como(ACME, lambda: svc.desfazer_cancelamento(Empty()))
        reativada = await como(STAFF_NO_ACME, lambda: svc.conta(ContaAcao(acao="desfazer")))
        return acme, beta, dono.value, reativada

    acme, beta, dono, reativada = run(cenario)
    assert (acme.situacao, acme.cancelamento.origem, acme.pode_desfazer) == ("encerrada", "cogniventure", False)
    assert (beta.situacao, beta.cancelamento.origem) == ("ativa", "cogniventure")  # ativo: vale no fim do mês pago
    assert dono.code == "ERRO_PLANS_SEM_CANCELAMENTO"
    assert (reativada.situacao, reativada.cancelamento, reativada.exclusao_em) == ("ativa", None, None)


def test_fechamento_inicia_o_faturamento_de_cada_cliente_pagante_na_cogniventure(box):
    iniciados = []

    def iniciar(pedido):
        iniciados.append((service.current_tenant(), service.current().sub, pedido))
        if pedido.dados["cliente_org"] == "beta":
            raise ServiceError("ERRO_PROCESSOS_SEM_PUBLICADA", "Publique o Faturamento e cobrança para iniciar por aqui.", 409)
        return {"id": "ex1", "processo": "fat", "titulo": "Faturamento e cobrança"}

    box.responders[INICIAR_MODELO_SUBJECT] = iniciar

    async def cenario(svc):
        await planos(svc)
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="acme", plan="pro")))
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="beta", plan="sob-medida")))
        await como(PLATAFORMA, lambda: svc.assign_plan(AssignInput(tenant="plat", plan="sob-medida")))  # a Cogniventure não se cobra
        await como(system("svc-staff", "acme"), lambda: svc.conta(ContaAcao(acao="cobranca", vencimento=20)))
        with pytest.raises(ServiceError) as cliente:
            await como(ACME, lambda: svc.fechar_mes(FechamentoIn()))
        return cliente.value, await como(system("svc-plans"), lambda: svc.fechar_mes(FechamentoIn(mes="2099-11")))

    cliente, fechamento = run(cenario)
    assert cliente.code == "ERRO_PLANS_FORBIDDEN"
    assert [(c.tenant, c.valor, c.vencimento, c.execucao) for c in fechamento.cobrados] == [
        ("acme", 99, "2099-11-20", "ex1"), ("beta", 999, "2099-11-10", None)]
    tenant, quem, pedido = iniciados[0]
    assert (tenant, quem, pedido.modelo, pedido.chave) == ("plat", "system:svc-plans", "faturamento-cobranca", "plano-acme-2099-11")
    assert {k: pedido.dados[k] for k in ("cliente", "email", "valor", "descricao", "cliente_org", "vencimento")} == {
        "cliente": "Acme", "email": "bia@acme.com", "valor": 99, "descricao": "Mensalidade da Cogniventure de novembro de 2099 (plano Pro)",
        "cliente_org": "acme", "vencimento": "2099-11-20"}  # a fatura vence no dia combinado com o cliente
    assert any(t.startswith("Fechamento de novembro de 2099: 1 cliente(s) sem cobrança") for t, _ in _avisos(box))


def test_exportacao_monta_o_pacote_com_cada_servico_e_os_arquivos(box, monkeypatch):
    guardado = {}

    async def keys():
        return ["t/acme/svc-integracoes/documentos/abcdef123456", "t/acme/svc-plans/exportacoes/antigo"]

    async def info(key):
        return StoredFile(key=key, filename="boleto.pdf", content_type="application/pdf", size=3)

    async def read(key, *, max_bytes):
        return b"PDF"

    async def save_file(path, *, filename, content_type, folder="files"):
        with open(path, "rb") as f:
            guardado["zip"] = f.read()
        return StoredFile(key="t/acme/svc-plans/exportacoes/novo", filename=filename, content_type=content_type, size=len(guardado["zip"]))

    async def start_workflow(run, arg, *, task_queue, id=None):
        guardado["workflow"] = (arg.id, id)

    for nome, fn in (("keys", keys), ("info", info), ("read", read), ("save_file", save_file)):
        monkeypatch.setattr(service.storage, nome, fn)
    monkeypatch.setattr(service.storage, "url", lambda key, **kw: f"https://arquivos/{key}")
    monkeypatch.setattr(service.runner, "start_workflow", start_workflow)

    def dados(pedido):
        assert service.current().sub == "system:svc-plans"  # só o svc-plans pede as linhas de uma organização
        linhas = [{"id": "crm_clientes:1", "nome": "Padaria Sol", "tags": ["vip"]}] if pedido.table else []
        return DataPage(service="svc-crm", tables=["crm_clientes"], table=pedido.table, rows=linhas, next=None)

    box.responders["rpc.crm.dados"] = dados

    async def cenario(svc):
        with pytest.raises(ServiceError) as membro:
            await como(ACME_MEMBRO, lambda: svc.pedir_exportacao(Empty()))
        pedido = await como(ACME, lambda: svc.pedir_exportacao(Empty()))
        de_novo = await como(ACME, lambda: svc.pedir_exportacao(Empty()))  # já preparando: o mesmo pedido
        pronta = await como(ACME, lambda: svc.exportar(ExportacaoRef(id=pedido.id)))
        return membro.value, pedido, de_novo, pronta, await como(ACME, lambda: svc.exportacao(Empty()))

    membro, pedido, de_novo, pronta, atual = run(cenario)
    assert membro.code == "ERRO_PLANS_FORBIDDEN"
    assert (pedido.status, de_novo.id, guardado["workflow"]) == ("preparando", pedido.id, (pedido.id, f"exportar-{pedido.id}"))
    assert (pronta.status, atual.item.url) == ("pronta", "https://arquivos/t/acme/svc-plans/exportacoes/novo")
    pacote = zipfile.ZipFile(io.BytesIO(guardado["zip"]))
    assert sorted(pacote.namelist()) == ["LEIA-ME.txt", "arquivos/integracoes/documentos/abcdef12-boleto.pdf", "crm/crm_clientes.csv",
                                         "crm/crm_clientes.json"]
    assert json.loads(pacote.read("crm/crm_clientes.json")) == [{"id": "crm_clientes:1", "nome": "Padaria Sol", "tags": ["vip"]}]
    assert pacote.read("crm/crm_clientes.csv").decode("utf-8-sig").splitlines() == ["id,nome,tags", 'crm_clientes:1,Padaria Sol,"[""vip""]"']
    assert "svc-ai" in pacote.read("LEIA-ME.txt").decode() and "svc-ai" in pronta.aviso  # quem estava fora do ar fica dito
    assert any(t == "Os dados da organização estão prontos" for t, _ in _avisos(box))
