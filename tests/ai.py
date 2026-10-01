"""svc-ai · testes sem infraestrutura. Fonte da verdade: specs/ai.md §2 e §4

SurrealDB embutido em memória (mem://) com as tabelas e índices do boot; provedor de IA falso (httpx MockTransport).

Rodar (da raiz): PYTHONPATH=services/svc-ai uv run python -m pytest tests/ai.py
"""
import asyncio

import httpx
import pytest
from pydantic import ValidationError
from surrealdb import AsyncSurreal

from core.envelope import ServiceError
from core.security import Principal, acting_as, new_secret

import service
from schemas import SHARED_TABLES, TENANT_TABLES, UNIQUE, Empty, ModelInput, ModelUpdate, ProviderInput, ProviderRef, ResolveRequest, UsageEvent

PLATAFORMA = Principal(sub="ana", tenant="plat", roles=frozenset({"owner"}))
ACME = Principal(sub="bia", tenant="acme", roles=frozenset({"owner"}))
ACME_MEMBRO = Principal(sub="caio", tenant="acme", roles=frozenset({"member"}))
BETA = Principal(sub="duda", tenant="beta", roles=frozenset({"admin"}))
MODELOS = {"object": "list", "data": [{"id": "llama3.2"}, {"id": "nomic-embed-text"}, {"object": "model"}]}


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("AI_SECRETS_KEY", new_secret(32))
    monkeypatch.setenv("PLATFORM_TENANT", "plat")
    service.settings.cache_clear()
    pedidos = []

    def provedor(request):
        pedidos.append(request)
        return httpx.Response(200, json=MODELOS)

    monkeypatch.setattr(service, "_internal_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(provedor)))
    yield pedidos
    service.settings.cache_clear()


def run(cenario):
    async def go():
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        service.db._conn = conn
        async with service.db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE):
            return await cenario(service.AiService())

    return asyncio.run(go())


def como(who, coro):
    async def go():
        with acting_as(who):
            return await coro()

    return go()


async def _plataforma_com_llama(svc):
    async def criar():
        prov = await svc.create_provider(ProviderInput(name="Ollama", slug="local", base_url="http://ollama:11434/v1/", scope="platform"))
        modelos = await svc.discover_models(ProviderRef(id=prov.id))
        llama = next(m for m in modelos.items if m.model_id == "llama3.2")
        await svc.update_model(ModelUpdate(id=llama.id, enabled=True, alias="rapido", price_input=1.0, price_output=2.0))
        return prov

    return await como(PLATAFORMA, criar)


def _erro(exc, code):
    assert exc.value.code == code, exc.value.code


# ── Provedores e chaves ─────────────────────────────────────────────────────

def test_chave_criptografada_presa_ao_registro_e_nunca_devolvida():
    async def cenario(svc):
        async def criar():
            return await svc.create_provider(ProviderInput(name="OpenRouter", slug="openrouter", base_url="https://1.1.1.1/api/v1", api_key="sk-or-segredo-abcd"))

        prov = await como(ACME, criar)
        row = await service.db.select(f"ai_providers:{prov.id}")
        lista = await como(ACME, lambda: svc.list_providers(Empty()))
        return prov, row, lista

    prov, row, lista = run(cenario)
    assert (prov.key_hint, prov.scope) == ("…abcd", "organization")
    assert "segredo" not in row["key"] and service._decrypt("acme", "openrouter", row["key"]) == "sk-or-segredo-abcd"
    with pytest.raises(Exception):  # copiada para outro dono/apelido, a chave não abre
        service._decrypt("beta", "openrouter", row["key"])
    assert "segredo" not in lista.model_dump_json()


def test_quem_pode_gerenciar():
    async def cenario(svc):
        erros = []
        for who, scope in ((ACME_MEMBRO, "organization"), (ACME, "platform")):
            with pytest.raises(ServiceError) as exc:
                await como(who, lambda: svc.create_provider(ProviderInput(name="Xis", slug="x", base_url="https://1.1.1.1/v1", scope=scope)))
            erros.append(exc.value.code)
        return erros

    assert run(cenario) == ["ERRO_AI_FORBIDDEN", "ERRO_AI_FORBIDDEN"]


@pytest.mark.parametrize("url", ["http://1.1.1.1/v1", "https://10.0.0.5/v1", "https://127.0.0.1:11434/v1"])
def test_organizacao_nao_aponta_para_rede_interna_nem_http(url):
    async def cenario(svc):
        with pytest.raises(ServiceError) as exc:
            await como(ACME, lambda: svc.create_provider(ProviderInput(name="Xis", slug="x", base_url=url)))
        return exc

    _erro(run(cenario), "ERRO_AI_UNSAFE_URL")


def test_apelido_repetido_e_entrada_invalida():
    async def cenario(svc):
        dados = ProviderInput(name="Alfa", slug="dup", base_url="https://1.1.1.1/v1")
        await como(ACME, lambda: svc.create_provider(dados))
        with pytest.raises(ServiceError) as exc:
            await como(ACME, lambda: svc.create_provider(dados))
        await como(BETA, lambda: svc.create_provider(dados))  # outra organização pode usar o mesmo apelido
        return exc

    _erro(run(cenario), "ERRO_AI_SLUG_TAKEN")
    for errado in ({"slug": "Com Espaço"}, {"base_url": "ftp://x"}, {"chave_extra": 1}):
        with pytest.raises(ValidationError):
            ProviderInput.model_validate({"name": "Alfa", "slug": "a", "base_url": "https://x.com/v1", **errado})


# ── Catálogo e resolução ────────────────────────────────────────────────────

def test_descoberta_curadoria_e_resolucao(ambiente):
    async def cenario(svc):
        prov = await _plataforma_com_llama(svc)
        de_novo = await como(PLATAFORMA, lambda: svc.discover_models(ProviderRef(id=prov.id)))
        resolvido = await como(ACME_MEMBRO, lambda: svc.resolve(ResolveRequest(model="local/rapido", kind="chat")))
        pelo_id = await como(BETA, lambda: svc.resolve(ResolveRequest(model="local/llama3.2", kind="chat")))
        erros = []
        for pedido in (ResolveRequest(model="local/nomic-embed-text", kind="embedding"),  # descoberto, mas desativado
                       ResolveRequest(model="local/rapido", kind="embedding"),  # tipo errado
                       ResolveRequest(model="outro/rapido", kind="chat")):
            with pytest.raises(ServiceError) as exc:
                await como(ACME, lambda: svc.resolve(pedido))
            erros.append(exc.value.code)
        return de_novo, resolvido, pelo_id, erros

    de_novo, resolvido, pelo_id, erros = run(cenario)
    assert sorted((m.model_id, m.kind, m.enabled) for m in de_novo.items) == [("llama3.2", "chat", True), ("nomic-embed-text", "embedding", False)]
    assert [r.url.path for r in ambiente] == ["/v1/models", "/v1/models"] and "authorization" not in ambiente[0].headers
    assert (resolvido.model, resolvido.base_url, resolvido.scope, resolvido.price_output) == ("llama3.2", "http://ollama:11434/v1", "platform", 2.0)
    assert pelo_id.model == "llama3.2"
    assert erros == ["ERRO_AI_MODEL_UNAVAILABLE"] * 3


def test_provedor_da_organizacao_tem_prioridade_e_fica_so_nela():
    async def cenario(svc):
        await _plataforma_com_llama(svc)

        async def byok():
            prov = await svc.create_provider(ProviderInput(name="Meu", slug="local", base_url="https://1.1.1.1/v1", api_key="sk-acme-1234"))
            modelo = await svc.add_model(ModelInput(provider=prov.id, model_id="llama3.2"))
            await svc.update_model(ModelUpdate(id=modelo.id, alias="rapido"))
            return prov

        await como(ACME, byok)
        acme = await como(ACME, lambda: svc.resolve(ResolveRequest(model="local/rapido", kind="chat")))
        beta = await como(BETA, lambda: svc.resolve(ResolveRequest(model="local/rapido", kind="chat")))
        visao_beta = await como(BETA, lambda: svc.list_providers(Empty()))

        async def ativar_vetores_da_plataforma():
            modelos = await svc.list_models(Empty())
            vetores = next(m for m in modelos.items if m.model_id == "nomic-embed-text")
            await svc.update_model(ModelUpdate(id=vetores.id, enabled=True))

        await como(PLATAFORMA, ativar_vetores_da_plataforma)
        vetores = ResolveRequest(model="local/nomic-embed-text", kind="embedding")  # só a plataforma tem
        beta_vetores = await como(BETA, lambda: svc.resolve(vetores))
        with pytest.raises(ServiceError) as escondido:  # o "local" da Acme esconde o da plataforma inteiro
            await como(ACME, lambda: svc.resolve(vetores))
        return acme, beta, visao_beta, beta_vetores, escondido

    acme, beta, visao_beta, beta_vetores, escondido = run(cenario)
    assert beta_vetores.scope == "platform"
    _erro(escondido, "ERRO_AI_MODEL_UNAVAILABLE")
    assert (acme.scope, acme.base_url, acme.api_key.get_secret_value()) == ("organization", "https://1.1.1.1/v1", "sk-acme-1234")
    assert (beta.scope, beta.base_url) == ("platform", "http://ollama:11434/v1")
    assert [(p.slug, p.scope) for p in visao_beta.items] == [("local", "platform")]  # a da Acme não aparece


def test_remover_provedor_leva_os_modelos_e_apelido_unico_por_provedor():
    async def cenario(svc):
        prov = await _plataforma_com_llama(svc)
        modelos = await como(PLATAFORMA, lambda: svc.list_models(Empty()))
        outro = next(m for m in modelos.items if m.alias is None)
        with pytest.raises(ServiceError) as exc:
            await como(PLATAFORMA, lambda: svc.update_model(ModelUpdate(id=outro.id, alias="rapido")))
        with pytest.raises(ServiceError) as nao_dono:  # Acme não gerencia o provedor da plataforma
            await como(ACME, lambda: svc.remove_provider(ProviderRef(id=prov.id)))
        await como(PLATAFORMA, lambda: svc.remove_provider(ProviderRef(id=prov.id)))
        return exc, nao_dono, await como(ACME, lambda: svc.list_models(Empty()))

    exc, nao_dono, sobrou = run(cenario)
    _erro(exc, "ERRO_AI_SLUG_TAKEN")
    _erro(nao_dono, "ERRO_AI_FORBIDDEN")
    assert sobrou.items == []


# ── Uso e custo ─────────────────────────────────────────────────────────────

def test_uso_e_custo_por_organizacao():
    async def cenario(svc):
        evento = dict(model="local/rapido", provider="local", kind="chat", input_tokens=1_000_000, output_tokens=500_000, price_input=1.0, price_output=2.0)
        await como(ACME_MEMBRO, lambda: svc.record_usage(UsageEvent(service="svc-pedidos", **evento)))
        await como(ACME_MEMBRO, lambda: svc.record_usage(UsageEvent(service="svc-pedidos", **evento)))
        await como(BETA, lambda: svc.record_usage(UsageEvent(service="svc-relatorios", **evento)))
        acme = await como(ACME, lambda: svc.usage_summary(Empty()))
        beta = await como(BETA, lambda: svc.usage_summary(Empty()))
        with pytest.raises(ServiceError) as membro:
            await como(ACME_MEMBRO, lambda: svc.usage_summary(Empty()))
        return acme, beta, membro

    acme, beta, membro = run(cenario)
    assert (acme.calls, acme.input_tokens, acme.cost) == (2, 2_000_000, 4.0)  # 2 × (1 M × 1 + 0,5 M × 2)
    assert [(i.model, i.service, i.calls) for i in acme.items] == [("local/rapido", "svc-pedidos", 2)]
    assert (beta.calls, beta.items[0].service) == (1, "svc-relatorios")
    _erro(membro, "ERRO_AI_FORBIDDEN")


def test_reentrega_do_mesmo_evento_nao_conta_duas_vezes():
    from core import nats_bus

    async def cenario(svc):
        evento = UsageEvent(model="local/rapido", provider="local", kind="chat", service="svc-pedidos", input_tokens=10, price_input=1.0)
        token = nats_bus._message_id.set("EVENTS-42")  # o mesmo id estável em toda reentrega
        try:
            primeira = await como(ACME_MEMBRO, lambda: svc.record_usage(evento))
            reentrega = await como(ACME_MEMBRO, lambda: svc.record_usage(evento))
        finally:
            nats_bus._message_id.reset(token)
        return primeira, reentrega, await como(ACME, lambda: svc.usage_summary(Empty()))

    primeira, reentrega, resumo = run(cenario)
    assert primeira.id == reentrega.id and resumo.calls == 1
