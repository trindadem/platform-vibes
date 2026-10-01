"""svc-webhooks · testes sem infraestrutura. Fonte da verdade: specs/webhooks.md §2 e §4

SurrealDB embutido em memória (mem://), com as tabelas e índices do boot e a SurrealQL de verdade; o NATS vira dublê e
o endereço da organização vira um receptor falso que guarda cada POST (e confere a assinatura como um cliente faria).

Rodar (da raiz): PYTHONPATH=services/svc-webhooks uv run python -m pytest tests/webhooks.py
"""
import asyncio
import base64
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from surrealdb import AsyncSurreal

from core import security
from core.envelope import ServiceError
from core.notify import SEND_SUBJECT
from core.plans import PlanLimits
from core.security import Principal, acting_as
from core.webhooks import Catalog, CatalogEvent, Emitted, verify

import service
from schemas import (
    MODULE,
    RETRY_SUBJECT,
    SHARED_TABLES,
    TENANT_TABLES,
    UNIQUE,
    DeliveryQuery,
    DeliveryRef,
    Empty,
    EndpointInput,
    EndpointRef,
    EndpointUpdate,
    Outgoing,
)

ANA = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))
BIA = Principal(sub="bia", tenant="acme", roles=frozenset({"member"}))
CAIO = Principal(sub="caio", tenant="beta", roles=frozenset({"owner"}))
URL = "http://receptor:8000/hooks"
JOINED = "identity.membro-entrou"
LEFT = "identity.membro-saiu"


@pytest.fixture
def hooks(monkeypatch):
    """Desenvolvimento (receptor na rede interna), NATS em memória e receptor falso. Devolve o que aconteceu."""
    key = Ed25519PrivateKey.generate()
    for name, value in {
        "ENVIRONMENT": "development", "AUTH_ISSUER": "https://auth.cv.test", "AUTH_AUDIENCE": "cv-api",
        "AUTH_PUBLIC_KEY": security._b64e(key.public_key().public_bytes_raw()),
        "WEBHOOKS_SECRETS_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }.items():
        monkeypatch.setenv(name, value)
    security._settings.cache_clear()
    service.settings.cache_clear()
    box = SimpleNamespace(posts=[], replies=[], published=[], live=[], counts=[])

    async def post(url, *, content, headers, timeout, allow_http, allow_private):
        await security.assert_public_url(url, allow_http=allow_http, allow_private=allow_private)
        box.posts.append(SimpleNamespace(url=url, body=content, headers=headers))
        reply = box.replies.pop(0) if box.replies else 200
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply)

    async def publish(subject, message, msg_id=None):
        if subject == "events.plans.count":  # plano (README §5.17): totais à parte
            box.counts.append((message.name, message.total))
        elif subject.startswith("events.plans."):
            pass
        else:
            box.published.append((subject, message))

    async def request(subject, message, response_model, timeout=5.0):  # svc-plans ainda sem o limite: vale o default (20)
        return PlanLimits(plan=None, plan_name="Sem plano", month="2026-10", limits=[])

    async def live(topic, message, user=None):
        box.live.append((topic, message.status))

    monkeypatch.setattr(service.http, "post", post)
    monkeypatch.setattr(service.bus, "publish", publish)
    monkeypatch.setattr(service.bus, "live", live)
    monkeypatch.setattr(service.bus, "_service", "svc-webhooks")
    monkeypatch.setattr(service.bus, "request", request)
    service.plans.clear()
    monkeypatch.setattr(service.plans, "_declared", {})
    asyncio.run(service.plans.declare(MODULE))
    box.counts.clear()
    yield box
    security._settings.cache_clear()
    service.settings.cache_clear()


def run(scenario):
    """Roda o cenário com o SurrealDB embutido, já com as tabelas, os índices e o catálogo do boot."""

    async def go():
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        service.db._conn = conn
        async with service.db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE):
            svc = service.WebhooksService()
            await svc.record_catalog(_catalog(JOINED, LEFT))
            return await scenario(svc)

    return asyncio.run(go())


def _catalog(*names):
    return Catalog(service="svc-identity", events=[
        CatalogEvent(name=n, service="svc-identity", description="Evento de teste.", payload_schema={"type": "object"})
        for n in names
    ])


def _emitted(event=JOINED, message="m1"):
    data = {"id": "bia", "name": "Bia", "email": "bia@x.com", "role": "member"}
    return Outgoing(message=message, emitted=Emitted(service="svc-identity", event=event, occurred_at=datetime(2026, 10, 1, 15, tzinfo=UTC), data=data))


async def _create(svc, url=URL, events=(JOINED,)):
    return await svc.create_endpoint(EndpointInput(url=url, events=list(events)))


def _error(exc_info, code, status):
    assert (exc_info.value.code, exc_info.value.status) == (code, status)


def test_endereco_nasce_com_segredo_e_o_teste_sai_assinado(hooks):
    async def scenario(svc):
        with acting_as(ANA):
            created = await _create(svc)
            listed = await svc.list_endpoints(Empty())
            stored = await service.db.select(f"webhook_endpoints:{created.endpoint.id}")
            tested = await svc.test_endpoint(EndpointRef(id=created.endpoint.id))
        return created, listed, stored, tested

    created, listed, stored, tested = run(scenario)
    assert created.secret.startswith("whsec_") and created.secret not in stored["secret"]  # guardado criptografado
    assert [e.url for e in listed.items] == [URL] and "secret" not in listed.items[0].model_dump()
    assert (tested.event, tested.status, tested.response_status, tested.attempts) == ("webhooks.teste", "sent", 200, 1)
    request = hooks.posts[0]
    verify(created.secret, request.headers, request.body)  # o cliente confere a assinatura com o segredo que recebeu
    assert request.headers["webhook-id"].startswith("msg_") and b'"type":"webhooks.teste"' in request.body


def test_evento_vai_so_para_os_enderecos_inscritos_da_organizacao(hooks):
    async def scenario(svc):
        with acting_as(ANA):
            joined = await _create(svc, URL + "/entrou", [JOINED])
            everything = await _create(svc, URL + "/tudo", ["*", LEFT])
            await _create(svc, URL + "/saiu", [LEFT])
            off = await _create(svc, URL + "/desligado", ["*"])
            await svc.update_endpoint(EndpointUpdate(id=off.endpoint.id, enabled=False))
        with acting_as(CAIO):
            await _create(svc, URL + "/beta", ["*"])
        with acting_as(ANA):
            planned = await svc.fan_out(_emitted())
            again = await svc.fan_out(_emitted())  # o NATS entregou de novo a mesma mensagem
            for delivery in planned.deliveries:
                await svc.deliver(DeliveryRef(id=delivery))
        return joined, everything, planned, again

    joined, everything, planned, again = run(scenario)
    assert everything.endpoint.events == ["*"]  # "*" engole o resto
    assert len(planned.deliveries) == 2 and planned == again
    assert sorted(p.url for p in hooks.posts) == [URL + "/entrou", URL + "/tudo"]
    first, second = hooks.posts
    assert first.body == second.body and first.headers["webhook-id"] == second.headers["webhook-id"]
    assert first.body == (b'{"type":"identity.membro-entrou","timestamp":"2026-10-01T15:00:00Z","data":'
                          b'{"id":"bia","name":"Bia","email":"bia@x.com","role":"member"}}')
    secret_of = {URL + "/entrou": joined.secret, URL + "/tudo": everything.secret}
    for post in hooks.posts:
        verify(secret_of[post.url], post.headers, post.body)  # cada endereço assina com o próprio segredo


def test_falha_temporaria_tenta_de_novo_e_410_desativa_o_endereco(hooks):
    async def scenario(svc):
        with acting_as(ANA):
            created = await _create(svc)
            delivery = (await svc.fan_out(_emitted())).deliveries[0]
            hooks.replies[:] = [500, httpx.ConnectError("recusado"), 410]
            with pytest.raises(ServiceError) as first:
                await svc.deliver(DeliveryRef(id=delivery))
            with pytest.raises(ServiceError):
                await svc.deliver(DeliveryRef(id=delivery))
            pending = await service.db.select(f"webhook_deliveries:{delivery}")
            gone = await svc.deliver(DeliveryRef(id=delivery))
            endpoint = (await svc.list_endpoints(Empty())).items[0]
        return first, pending, gone, endpoint

    first, pending, gone, endpoint = run(scenario)
    _error(first, "ERRO_WEBHOOKS_DELIVERY_FAILED", 503)  # >= 500: o Temporal tenta de novo
    assert (pending["status"], pending["attempts"], pending["error"]) == ("pending", 2, "ConnectError")
    assert gone.status == "failed"
    assert (endpoint.enabled, endpoint.disabled_reason) == (False, "O endereço respondeu 410 (Gone): pediu para não receber mais.")
    notices = [m for s, m in hooks.published if s == SEND_SUBJECT]
    assert [(n.roles, n.title, n.link) for n in notices] == [(["owner", "admin"], "Webhook desativado", "/webhooks")]


def test_falhas_seguidas_desativam_e_sucesso_zera_a_contagem(hooks):
    async def scenario(svc):
        with acting_as(ANA):
            weak = await _create(svc, URL + "/fraco", [JOINED])
            healthy = await _create(svc, URL + "/bom", [LEFT])
            await service.db.merge(f"webhook_endpoints:{weak.endpoint.id}", {"failures": 19})
            await service.db.merge(f"webhook_endpoints:{healthy.endpoint.id}", {"failures": 5})
            failed = (await svc.fan_out(_emitted())).deliveries[0]
            await svc.give_up(DeliveryRef(id=failed))  # 20ª entrega sem sucesso
            ok = (await svc.fan_out(_emitted(LEFT, "m2"))).deliveries[0]
            await svc.deliver(DeliveryRef(id=ok))
            endpoints = {e.url: e for e in (await svc.list_endpoints(Empty())).items}
        return endpoints

    endpoints = run(scenario)
    weak, healthy = endpoints[URL + "/fraco"], endpoints[URL + "/bom"]
    assert (weak.enabled, weak.failures) == (False, 20) and "20 entregas seguidas" in weak.disabled_reason
    assert (healthy.enabled, healthy.failures) == (True, 0)
    assert len([s for s, _ in hooks.published if s == SEND_SUBJECT]) == 1


def test_endereco_removido_pula_a_entrega_e_reenviar_repete_corpo_e_id(hooks):
    async def scenario(svc):
        with acting_as(ANA):
            kept = await _create(svc, URL + "/fica", [JOINED])
            removed = await _create(svc, URL + "/sai", [JOINED])
            first, second = (await svc.fan_out(_emitted())).deliveries
            by_endpoint = {}
            for delivery in (first, second):
                row = await service.db.select(f"webhook_deliveries:{delivery}")
                by_endpoint[row["endpoint"]] = delivery
            await svc.remove_endpoint(EndpointRef(id=removed.endpoint.id))
            skipped = await svc.deliver(DeliveryRef(id=by_endpoint[removed.endpoint.id]))
            target = by_endpoint[kept.endpoint.id]
            await svc.deliver(DeliveryRef(id=target))
            retried = await svc.retry_delivery(DeliveryRef(id=target))
            await svc.deliver(DeliveryRef(id=target))
            page = await svc.list_deliveries(DeliveryQuery(endpoint=kept.endpoint.id))
        return skipped, retried, page

    skipped, retried, page = run(scenario)
    assert skipped.status == "skipped"
    assert retried.status == "pending" and [s for s, _ in hooks.published] == [RETRY_SUBJECT]
    assert len(hooks.posts) == 2 and hooks.posts[0].body == hooks.posts[1].body
    assert hooks.posts[0].headers["webhook-id"] == hooks.posts[1].headers["webhook-id"]  # quem recebe reconhece a repetição
    assert [(d.status, d.attempts) for d in page.items] == [("sent", 2)]


def test_so_donos_e_admins_e_cada_organizacao_ve_o_seu(hooks):
    async def scenario(svc):
        with acting_as(ANA):
            created = await _create(svc)
            delivery = (await svc.fan_out(_emitted())).deliveries[0]
        with acting_as(BIA), pytest.raises(ServiceError) as member:
            await svc.list_endpoints(Empty())
        with acting_as(CAIO):
            with pytest.raises(ServiceError) as other_endpoint:
                await svc.update_endpoint(EndpointUpdate(id=created.endpoint.id, enabled=False))
            with pytest.raises(ServiceError) as other_delivery:
                await svc.retry_delivery(DeliveryRef(id=delivery))
            caio = await svc.list_deliveries(DeliveryQuery())
        return member, other_endpoint, other_delivery, caio

    member, other_endpoint, other_delivery, caio = run(scenario)
    _error(member, "ERRO_WEBHOOKS_FORBIDDEN", 403)
    _error(other_endpoint, "ERRO_WEBHOOKS_ENDPOINT_NOT_FOUND", 404)
    _error(other_delivery, "ERRO_WEBHOOKS_DELIVERY_NOT_FOUND", 404)
    assert caio.total == 0


def test_endereco_e_eventos_sao_conferidos(hooks, monkeypatch):
    async def scenario(svc):
        with acting_as(ANA):
            with pytest.raises(ServiceError) as unknown:
                await _create(svc, events=["faturas.paga"])
            for i in range(20):
                await _create(svc, f"{URL}/{i}")
            with pytest.raises(ServiceError) as limit:
                await _create(svc)
            first = (await svc.list_endpoints(Empty())).items[0].id
            monkeypatch.setenv("ENVIRONMENT", "production")
            security._settings.cache_clear()
            service.settings.cache_clear()
            with pytest.raises(ServiceError) as internal:  # rede interna: só em desenvolvimento
                await svc.update_endpoint(EndpointUpdate(id=first, url="https://receptor:8000/hooks"))
            with pytest.raises(ServiceError) as plain:
                await svc.update_endpoint(EndpointUpdate(id=first, url="http://example.com/hooks"))
        return unknown, limit, internal, plain

    unknown, limit, internal, plain = run(scenario)
    _error(unknown, "ERRO_WEBHOOKS_UNKNOWN_EVENT", 422)
    _error(limit, "ERRO_PLAN_LIMIT", 402)  # sem plano: o default declarado, 20 por organização
    assert "Endereços de webhook, até 20 endereços" in limit.value.message
    assert hooks.counts[-1] == ("webhooks.enderecos", 20)  # a tela Plano mostra "20 de 20"
    _error(internal, "ERRO_WEBHOOKS_UNSAFE_URL", 422)
    _error(plain, "ERRO_WEBHOOKS_UNSAFE_URL", 422)


def test_catalogo_acompanha_o_que_cada_servico_declara(hooks):
    async def scenario(svc):
        await svc.record_catalog(_catalog(JOINED))  # o identity deixou de emitir membro-saiu
        with acting_as(ANA):
            return await svc.list_events(Empty())

    events = run(scenario)
    assert [(e.name, e.service) for e in events.items] == [(JOINED, "svc-identity")]


def test_limpeza_apaga_entregas_antigas_concluidas(hooks, monkeypatch):
    async def scenario(svc):
        with acting_as(ANA):
            await _create(svc)
            done = (await svc.fan_out(_emitted())).deliveries[0]
            await svc.deliver(DeliveryRef(id=done))
            await svc.fan_out(_emitted(message="m2"))  # pendente: nunca é apagada
        kept = await svc.cleanup(Empty())
        later = service._now() + timedelta(days=31)
        monkeypatch.setattr(service, "_now", lambda: later)
        cleaned = await svc.cleanup(Empty())
        with acting_as(ANA):
            left = await svc.list_deliveries(DeliveryQuery())
        return kept, cleaned, left

    kept, cleaned, left = run(scenario)
    assert (kept.deliveries, cleaned.deliveries) == (0, 1)
    assert [d.status for d in left.items] == ["pending"]
