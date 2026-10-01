"""gateway/ · testes sem infraestrutura. Fonte da verdade: README §5.8

Rodar (da raiz): PYTHONPATH=gateway uv run python -m pytest tests/gateway.py
"""
import asyncio
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core import security
from core.nats_bus import bus

BILLING = {
    "service": "billing",
    "base_path": "/api/v1/billing",
    "endpoints": [
        {"path": "/execute", "method": "POST", "auth": "client_jwt", "target_type": "http",
         "target_url": "http://svc-billing:8000/execute", "timeout": 2},
        {"path": "/faturas/{fatura_id}", "method": "GET", "auth": "client_jwt", "roles": ["financeiro"],
         "target_type": "http", "target_url": "http://svc-billing:8000/faturas/{fatura_id}"},
        {"path": "/ping", "method": "GET", "auth": "public", "target_type": "http",
         "target_url": "http://svc-billing:8000/ping"},
        {"path": "/trigger", "method": "POST", "auth": "client_jwt", "target_type": "nats",
         "nats_subject": "events.billing.trigger"},
    ],
}


@pytest.fixture
def auth_env(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.cv.test")
    monkeypatch.setenv("AUTH_AUDIENCE", "cv-api")
    monkeypatch.setenv("AUTH_PRIVATE_KEY", security._b64e(key.private_bytes_raw()))
    _clear()
    yield
    _clear()


def _clear():
    security._settings.cache_clear()
    security._own_keys.cache_clear()


@pytest.fixture
def gateway(auth_env, tmp_path, monkeypatch):
    """Gateway com o manifesto BILLING, serviço falso (MockTransport) e NATS em memória."""
    import interpreter
    import main

    (tmp_path / "billing.yaml").write_text(json.dumps(BILLING))  # JSON é YAML válido
    calls, published = [], []

    def fake_service(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/execute" and request.content == b'{"quebrar": true}':
            raise httpx.ConnectError("fora do ar", request=request)
        return httpx.Response(201, json={"ok": True, "service": "svc-billing", "data": {"eco": request.url.path}})

    async def fake_publish(subject, message, msg_id=None):
        published.append((subject, message.root, msg_id))

    monkeypatch.setattr(bus, "publish", fake_publish)
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(fake_service))
    app = main.create_app(interpreter.load_manifests(tmp_path), upstream)
    return TestClient(app, raise_server_exceptions=False), calls, published


def _bearer(sub="u1", roles=(), tenant=None):
    return {"Authorization": f"Bearer {security.issue_token(sub, tenant=tenant, roles=roles)}"}


# ── Trilhos do manifesto ────────────────────────────────────────────────────

def _manifest(**endpoint_overrides):
    from schemas import Manifest

    endpoint = {**BILLING["endpoints"][0], **endpoint_overrides}
    return Manifest.model_validate({**BILLING, "endpoints": [endpoint]})


def test_manifesto_valido():
    from schemas import Manifest

    assert len(Manifest.model_validate(BILLING).endpoints) == 4


@pytest.mark.parametrize(
    ("override", "erro"),
    [
        ({"target_url": "http://svc-user-auth:8000/execute"}, "http://svc-billing:8000/"),
        ({"target_url": "https://evil.example/x"}, "http://svc-billing:8000/"),
        ({"target_url": "http://169.254.169.254:8000/x"}, "http://svc-billing:8000/"),
        ({"target_url": "http://svc-billing:8000/{conta}"}, "parâmetros que o path não declara"),
        ({"target_type": "nats", "target_url": None, "nats_subject": "events.user-auth.trigger"}, "events.billing."),
        ({"method": "GET", "target_type": "nats", "target_url": None, "nats_subject": "events.billing.x"}, "só aceita POST"),
        ({"auth": "public", "roles": ["admin"]}, "rota pública"),
        ({"path": "/../admin"}, "path inválido"),
        ({"tiemout": 5}, "Extra inputs"),
        ({"request": "execution_input"}, "PascalCase"),
        ({"name": "Executar"}, "camelCase"),
        ({"method": "GET", "request": "ExecutionInput"}, "não tem corpo"),
        ({"target_type": "nats", "target_url": None, "nats_subject": "events.billing.x", "response": "Fatura"}, "remova response"),
        ({"method": "GET", "cookies": True}, "cookies: true só em rota HTTP POST"),
        ({"method": "GET", "headers": ["stripe-signature"]}, "headers só em rota HTTP POST"),
        ({"headers": ["Stripe-Signature"]}, "não pode ser repassado"),
        ({"headers": ["cookie"]}, "não pode ser repassado"),
        ({"headers": ["x-forwarded-for"]}, "não pode ser repassado"),
        ({"stream": True}, "exige delta"),
        ({"delta": "Pedaco"}, "delta só existe com stream: true"),
        ({"target_type": "nats", "target_url": None, "nats_subject": "events.billing.x", "stream": True, "delta": "P"}, "stream: true só em rota HTTP"),
        ({"target_type": "nats", "target_url": None, "nats_subject": "events.billing.x", "cookies": True}, "cookies: true só"),
        ({"query": "FaturaQuery"}, "query (parâmetros da URL) só em rota HTTP GET"),
        ({"method": "GET", "request": None, "query": "fatura_query"}, "PascalCase"),
    ],
)
def test_manifesto_fora_do_trilho_e_recusado(override, erro):
    with pytest.raises(ValidationError) as exc:
        _manifest(**override)
    assert erro in str(exc.value)


@pytest.mark.parametrize(
    ("override", "erro"),
    [
        ({"live": [{"topic": "Criado", "model": "Fatura"}]}, "kebab-case"),
        ({"live": [{"topic": "criado", "model": "fatura"}]}, "PascalCase"),
        ({"live": [{"topic": "criado", "model": "Fatura"}, {"topic": "criado", "model": "Outra"}]}, "topic repetido"),
        ({"service": "live", "base_path": "/api/v1/live"}, "reservado"),
    ],
)
def test_topicos_ao_vivo_e_nome_reservado(override, erro):
    from schemas import Manifest

    with pytest.raises(ValidationError) as exc:
        Manifest.model_validate({**BILLING, **override})
    assert erro in str(exc.value)


def test_manifesto_com_nome_de_arquivo_errado_impede_o_boot(tmp_path):
    import interpreter

    (tmp_path / "cobranca.yaml").write_text(json.dumps(BILLING))
    with pytest.raises(RuntimeError, match="renomeie para billing.yaml"):
        interpreter.load_manifests(tmp_path)


def test_manifesto_invalido_impede_o_boot(tmp_path):
    import interpreter

    (tmp_path / "billing.yaml").write_text(json.dumps({**BILLING, "base_path": "/billing"}))
    with pytest.raises(RuntimeError, match="manifesto inválido"):
        interpreter.load_manifests(tmp_path)


# ── Roteamento HTTP ─────────────────────────────────────────────────────────

def test_sem_token_o_gateway_barra_antes_do_servico(gateway):
    client, calls, _ = gateway
    r = client.post("/api/v1/billing/execute", json={})
    assert (r.status_code, r.json()["error"]["code"], calls) == (401, "ERRO_AUTH_UNAUTHENTICATED", [])


def test_repassa_corpo_query_e_token_ao_servico(gateway):
    client, calls, _ = gateway
    headers = {**_bearer(), "Cookie": "sessao=x", "X-Forwarded-For": "1.2.3.4"}
    r = client.post("/api/v1/billing/execute?modo=rapido", json={"client_id": "c1"}, headers=headers)
    assert (r.status_code, r.json()["data"]) == (201, {"eco": "/execute"})
    sent = calls[0]
    assert str(sent.url) == "http://svc-billing:8000/execute?modo=rapido"
    assert json.loads(sent.content) == {"client_id": "c1"}
    assert sent.headers["authorization"] == headers["Authorization"]
    assert "cookie" not in sent.headers and "x-forwarded-for" not in sent.headers
    assert sent.headers["x-request-id"]


def test_parametro_de_caminho_e_codificado_e_nao_atravessa(gateway):
    client, calls, _ = gateway
    auth = _bearer(roles=["financeiro"])
    assert client.get("/api/v1/billing/faturas/f%201%3Fx", headers=auth).status_code == 201
    assert calls[0].url.raw_path == b"/faturas/f%201%3Fx"
    assert client.get("/api/v1/billing/faturas/..%2Fadmin", headers=auth).status_code == 404
    assert len(calls) == 1


def test_papel_declarado_no_manifesto(gateway):
    client, calls, _ = gateway
    r = client.get("/api/v1/billing/faturas/f1", headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"], calls) == (403, "ERRO_AUTH_FORBIDDEN", [])


def test_rota_publica_do_manifesto(gateway):
    client, _, _ = gateway
    assert client.get("/api/v1/billing/ping").status_code == 201
    assert client.get("/health").json()["data"] == {"routes": 4}


def test_servico_fora_do_ar_vira_502(gateway):
    client, _, _ = gateway
    r = client.post("/api/v1/billing/execute", content=b'{"quebrar": true}', headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"]) == (502, "ERRO_GATEWAY_UNAVAILABLE")


def test_corpo_acima_de_1_mib_e_recusado(gateway):
    client, calls, _ = gateway
    r = client.post("/api/v1/billing/execute", content=b"x" * (1_048_576 + 1), headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"], calls) == (413, "ERRO_GATEWAY_PAYLOAD_TOO_LARGE", [])


def test_corpo_em_partes_sem_tamanho_declarado_tambem_e_limitado(gateway):
    client, calls, _ = gateway
    chunks = iter([b"x" * 600_000, b"x" * 600_000])  # sem Content-Length: chega em partes (chunked)
    r = client.post("/api/v1/billing/execute", content=chunks, headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"], calls) == (413, "ERRO_GATEWAY_PAYLOAD_TOO_LARGE", [])


def test_cabecalhos_de_seguranca_no_gateway(gateway):
    client, _, _ = gateway
    headers = client.get("/health").headers
    assert headers["x-frame-options"] == "DENY" and "max-age" in headers["strict-transport-security"]


# ── Roteamento NATS ─────────────────────────────────────────────────────────

def test_publica_no_nats_e_responde_202(gateway):
    client, _, published = gateway
    r = client.post("/api/v1/billing/trigger", json={"client_id": "c1"}, headers=_bearer())
    assert r.status_code == 202
    assert published == [("events.billing.trigger", {"client_id": "c1"}, r.json()["data"]["message_id"])]


def test_idempotency_key_e_isolada_por_usuario(gateway):
    client, _, published = gateway
    ana = {**_bearer("ana"), "Idempotency-Key": "pedido-1"}
    bia = {**_bearer("bia"), "Idempotency-Key": "pedido-1"}
    first = client.post("/api/v1/billing/trigger", json={}, headers=ana).json()["data"]["message_id"]
    again = client.post("/api/v1/billing/trigger", json={}, headers=ana).json()["data"]["message_id"]
    other = client.post("/api/v1/billing/trigger", json={}, headers=bia).json()["data"]["message_id"]
    assert first == again != other
    assert [msg_id for *_, msg_id in published] == [first, first, other]


def test_idempotency_key_e_isolada_por_organizacao(gateway):
    client, _, _ = gateway
    acme = {**_bearer("ana", tenant="acme"), "Idempotency-Key": "pedido-1"}
    beta = {**_bearer("ana", tenant="beta"), "Idempotency-Key": "pedido-1"}
    first = client.post("/api/v1/billing/trigger", json={}, headers=acme).json()["data"]["message_id"]
    other = client.post("/api/v1/billing/trigger", json={}, headers=beta).json()["data"]["message_id"]
    assert first != other


def test_evento_e_publicado_em_nome_de_quem_chamou(gateway, monkeypatch):
    client, _, _ = gateway
    actors = []

    async def publish(subject, message, msg_id=None):
        actors.append(security.current())  # o core.nats_bus põe este Principal no cabeçalho da mensagem

    monkeypatch.setattr(bus, "publish", publish)
    client.post("/api/v1/billing/trigger", json={}, headers=_bearer("ana", roles=["ops"], tenant="acme"))
    assert [(a.sub, a.tenant, a.roles) for a in actors] == [("ana", "acme", frozenset({"ops"}))]


def test_cookie_so_passa_nas_rotas_que_declaram(auth_env, tmp_path):
    import interpreter
    import main

    manifest = {**BILLING, "endpoints": [
        {**BILLING["endpoints"][0], "path": "/sessao", "target_url": "http://svc-billing:8000/sessao", "cookies": True},
        BILLING["endpoints"][0],
    ]}
    (tmp_path / "billing.yaml").write_text(json.dumps(manifest))
    received = []

    def fake_service(request: httpx.Request) -> httpx.Response:
        received.append(request.headers.get("cookie"))
        headers = [("set-cookie", "cv_refresh=novo; HttpOnly; Path=/api/v1/billing"), ("set-cookie", "outro=1")]
        return httpx.Response(200, json={"ok": True, "service": "svc-billing", "data": {}}, headers=headers)

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(fake_service), cookies=main.no_cookie_jar())
    client = TestClient(main.create_app(interpreter.load_manifests(tmp_path), upstream), raise_server_exceptions=False)
    headers = {**_bearer(), "Cookie": "cv_refresh=antigo"}
    with_cookies = client.post("/api/v1/billing/sessao", json={}, headers=headers)
    without = client.post("/api/v1/billing/execute", json={}, headers=headers)
    assert received == ["cv_refresh=antigo", None]
    assert with_cookies.headers.get_list("set-cookie") == ["cv_refresh=novo; HttpOnly; Path=/api/v1/billing", "outro=1"]
    assert without.headers.get_list("set-cookie") == []


def test_cabecalho_extra_so_passa_na_rota_que_declara(auth_env, tmp_path):
    """Webhook que chega (README §5.16): a assinatura do provedor vem num cabeçalho que só a rota dele recebe."""
    import interpreter
    import main

    manifest = {**BILLING, "endpoints": [
        {**BILLING["endpoints"][0], "path": "/hooks/stripe", "auth": "public",
         "target_url": "http://svc-billing:8000/hooks/stripe", "headers": ["stripe-signature"]},
        BILLING["endpoints"][0],
    ]}
    (tmp_path / "billing.yaml").write_text(json.dumps(manifest))
    received = []

    def fake_service(request: httpx.Request) -> httpx.Response:
        received.append((request.headers.get("stripe-signature"), request.content))
        return httpx.Response(200, json={"ok": True, "service": "svc-billing", "data": {}})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(fake_service), cookies=main.no_cookie_jar())
    client = TestClient(main.create_app(interpreter.load_manifests(tmp_path), upstream), raise_server_exceptions=False)
    raw = b'{"id": "evt_1",  "type": "invoice.paid"}'  # o corpo chega byte a byte: a assinatura é sobre ele
    client.post("/api/v1/billing/hooks/stripe", content=raw, headers={"Stripe-Signature": "t=1,v1=abc", "Content-Type": "application/json"})
    client.post("/api/v1/billing/execute", json={}, headers={**_bearer(), "Stripe-Signature": "t=1,v1=abc"})
    assert received == [("t=1,v1=abc", raw), (None, b"{}")]


def _stream_gateway(tmp_path, reply):
    import interpreter
    import main

    endpoint = {**BILLING["endpoints"][0], "path": "/responder", "target_url": "http://svc-billing:8000/responder",
                "stream": True, "delta": "Pedaco"}
    (tmp_path / "billing.yaml").write_text(json.dumps({**BILLING, "endpoints": [endpoint]}))
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(reply), cookies=main.no_cookie_jar())
    return TestClient(main.create_app(interpreter.load_manifests(tmp_path), upstream), raise_server_exceptions=False)


def test_stream_e_repassado_em_pedacos(auth_env, tmp_path):
    parts = [b'event: delta\ndata: {"texto": "a"}\n\n', b'event: done\ndata: {"ok": true}\n\n']

    async def body():
        for part in parts:
            yield part

    def reply(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    r = _stream_gateway(tmp_path, reply).post("/api/v1/billing/responder", json={}, headers=_bearer())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.content == b"".join(parts)


def test_erro_antes_do_stream_sai_no_envelope_de_sempre(auth_env, tmp_path):
    def reply(request):
        return httpx.Response(422, json={"ok": False, "service": "svc-billing", "data": None, "error": {"code": "X"}})

    r = _stream_gateway(tmp_path, reply).post("/api/v1/billing/responder", json={}, headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"]) == (422, "X")


def test_conexao_ao_vivo_entrega_so_o_feed_de_quem_chamou_e_fecha_quando_o_token_vence(gateway, monkeypatch):
    from contextlib import asynccontextmanager

    client, _, _ = gateway
    feeds = []

    @asynccontextmanager
    async def live_feed(who):
        feeds.append((who.sub, who.tenant))
        queue = asyncio.Queue()
        queue.put_nowait(("pedidos.criado", b'{"valor": 1}'))
        yield queue

    monkeypatch.setattr(bus, "live_feed", live_feed)
    assert client.get("/api/v1/live").status_code == 401
    sem_org = client.get("/api/v1/live", headers=_bearer("ana"))
    assert (sem_org.status_code, sem_org.json()["error"]["code"]) == (403, "ERRO_TENANT_REQUIRED")
    token = security.issue_token("ana", tenant="acme", ttl_seconds=1)  # vence logo: a conexão termina sozinha
    r = client.get("/api/v1/live", headers={"Authorization": f"Bearer {token}"})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert feeds == [("ana", "acme")]
    assert 'event: pedidos.criado\ndata: {"valor": 1}' in r.text and r.text.rstrip().endswith("event: expired\ndata: {}")


@pytest.mark.parametrize("body", [b"[1, 2]", b"nao-e-json", b'"texto"'])
def test_nats_so_aceita_objeto_json(gateway, body):
    client, _, published = gateway
    r = client.post("/api/v1/billing/trigger", content=body, headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"], published) == (422, "ERRO_GATEWAY_INVALID_PAYLOAD", [])


def test_idempotency_key_invalida(gateway):
    client, _, _ = gateway
    r = client.post("/api/v1/billing/trigger", json={}, headers={**_bearer(), "Idempotency-Key": "a b;c"})
    assert r.status_code == 422


def test_timeout_do_servico_vira_504(auth_env, tmp_path, monkeypatch):
    import interpreter
    import main

    manifest = {**BILLING, "endpoints": [{**BILLING["endpoints"][0], "target_url": "http://svc-billing:8000/lento"}]}
    (tmp_path / "billing.yaml").write_text(json.dumps(manifest))

    def slow(request):
        raise httpx.ReadTimeout("lento", request=request)

    app = main.create_app(interpreter.load_manifests(tmp_path), httpx.AsyncClient(transport=httpx.MockTransport(slow)))
    r = TestClient(app).post("/api/v1/billing/execute", json={}, headers=_bearer())
    assert (r.status_code, r.json()["error"]["code"]) == (504, "ERRO_GATEWAY_TIMEOUT")


# ── Contratos tipados (gateway/contracts.py) ────────────────────────────────

LOJA_SCHEMAS = """
from enum import Enum
from typing import ClassVar, Literal
from pydantic import BaseModel, Field
from core.surreal import ListQuery, Page

class Status(str, Enum):
    ABERTA = "aberta"
    PAGA = "paga"

class Item(BaseModel):
    \"\"\"Item da fatura.\"\"\"
    sku: str
    quantidade: int = Field(1, ge=1, description="Unidades compradas")

class FaturaIn(BaseModel):
    cliente: str
    itens: list[Item]
    cupom: str | None = None
    moeda: Literal["BRL", "USD"] = "BRL"

class Fatura(BaseModel):
    id: str
    status: Status
    itens: list[Item]

class FaturaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("cliente", "valor")
    status: Status | None = None

class FaturaPage(Page[Fatura]):
    pass
"""

LOJA = {
    "service": "loja",
    "base_path": "/api/v1/loja",
    "endpoints": [
        {"path": "/faturas", "name": "criar", "method": "POST", "auth": "client_jwt", "request": "FaturaIn",
         "response": "Fatura", "target_type": "http", "target_url": "http://svc-loja:8000/faturas"},
        {"path": "/faturas/{fatura_id}", "name": "detalhe", "method": "GET", "auth": "client_jwt", "roles": ["financeiro"],
         "response": "Fatura", "target_type": "http", "target_url": "http://svc-loja:8000/faturas/{fatura_id}"},
        {"path": "/faturas/emitir", "method": "POST", "auth": "client_jwt", "request": "FaturaIn",
         "target_type": "nats", "nats_subject": "events.loja.emitir"},
        {"path": "/faturas", "name": "listar", "method": "GET", "auth": "client_jwt", "query": "FaturaQuery",
         "response": "FaturaPage", "target_type": "http", "target_url": "http://svc-loja:8000/faturas"},
    ],
}


@pytest.fixture
def loja_dirs(tmp_path):
    endpoints, services = tmp_path / "endpoints", tmp_path / "services"
    (services / "svc-loja").mkdir(parents=True)
    endpoints.mkdir()
    (services / "svc-loja" / "schemas.py").write_text(LOJA_SCHEMAS)
    (endpoints / "loja.yaml").write_text(json.dumps(LOJA))
    return endpoints, services


def test_contrato_versionado_esta_em_dia():
    import contracts

    assert contracts.OUTPUT.read_text(encoding="utf-8") == contracts.generate(), "rode: uv run python gateway/contracts.py"


def test_contrato_gera_tipos_a_partir_do_pydantic(loja_dirs):
    import contracts

    ts = contracts.generate(*loja_dirs)
    assert 'export type LojaStatus = "aberta" | "paga";' in ts
    assert "/** Item da fatura. */\nexport interface LojaItem {" in ts
    assert "  /** Unidades compradas */\n  quantidade?: number;" in ts  # padrão → opcional na entrada
    assert "  cupom?: string | null;" in ts
    assert '  moeda?: "BRL" | "USD";' in ts
    assert "  itens: LojaItem[];" in ts


def test_contrato_gera_uma_funcao_tipada_por_rota(loja_dirs):
    import contracts

    ts = contracts.generate(*loja_dirs)
    assert "  criar: (body: LojaFaturaIn, options?: RequestOptions) =>" in ts
    assert '    request<LojaFatura>("POST", "/api/v1/loja/faturas", body, options),' in ts
    assert "  detalhe: (params: { fatura_id: string }, options?: RequestOptions) =>" in ts
    assert "`/api/v1/loja/faturas/${encodeURIComponent(params.fatura_id)}`" in ts
    assert "exige token com papéis financeiro" in ts
    assert "  emitir: (body: LojaFaturaIn, options?: RequestOptions) =>" in ts  # name derivado do path
    assert '    request<Dispatched>("POST", "/api/v1/loja/faturas/emitir", body, options),' in ts


def test_contrato_de_lista_tipa_os_parametros_da_url_e_a_pagina(loja_dirs):
    import contracts

    ts = contracts.generate(*loja_dirs)
    assert "import { request, withQuery, type RequestOptions } from \"./api\";" in ts
    assert "  listar: (query?: LojaFaturaQuery, options?: RequestOptions) =>" in ts
    assert '    request<LojaFaturaPage>("GET", withQuery("/api/v1/loja/faturas", query), undefined, options),' in ts
    assert '  sort?: "cliente" | "-cliente" | "valor" | "-valor" | null;' in ts  # só as ordens permitidas
    assert "  status?: LojaStatus | null;" in ts and "  page?: number;" in ts
    assert "export interface LojaFaturaPage {\n  items: LojaFatura[];" in ts


def test_contrato_com_modelo_inexistente_e_erro(loja_dirs):
    import contracts

    endpoints, services = loja_dirs
    broken = {**LOJA, "endpoints": [{**LOJA["endpoints"][0], "request": "FaturaInn"}]}
    (endpoints / "loja.yaml").write_text(json.dumps(broken))
    with pytest.raises(RuntimeError, match="cita FaturaInn"):
        contracts.generate(endpoints, services)


def test_contrato_sem_schemas_do_servico_e_erro(loja_dirs):
    import contracts

    endpoints, services = loja_dirs
    (services / "svc-loja" / "schemas.py").unlink()
    with pytest.raises(RuntimeError, match="não tem"):
        contracts.generate(endpoints, services)


def test_duas_rotas_com_o_mesmo_nome_de_funcao_sao_recusadas():
    from schemas import Manifest

    duplicated = {**BILLING, "endpoints": [BILLING["endpoints"][0], {**BILLING["endpoints"][0], "path": "/v2/execute"}]}
    with pytest.raises(ValidationError, match="defina name"):
        Manifest.model_validate(duplicated)
