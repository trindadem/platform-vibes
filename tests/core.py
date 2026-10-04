"""core/ · testes sem infraestrutura. Fonte da verdade: README §5.6, §5.7 e §5.9

Rodar (da raiz): uv run python -m pytest tests/core.py
"""
import asyncio
import json
from pathlib import Path
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar, Literal

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from surrealdb import AsyncSurreal, RecordID
from surrealdb.errors import InternalError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from core import envelope, nats_bus, security, surreal, temporal_runner
from core.envelope import ServiceError
from core.http_client import HttpClient, http
from core.llm import Image
from core.security import Principal, principal, require


@pytest.fixture
def auth_env(monkeypatch):
    """Ambiente com chaves EdDSA próprias; limpa os caches de configuração antes e depois."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.cv.test")
    monkeypatch.setenv("AUTH_AUDIENCE", "cv-api")
    monkeypatch.setenv("AUTH_PRIVATE_KEY", security._b64e(key.private_bytes_raw()))
    monkeypatch.setenv("AUTH_PUBLIC_KEY", security._b64e(key.public_key().public_bytes_raw()))
    _clear_caches()
    yield key
    _clear_caches()


def _clear_caches():
    security._settings.cache_clear()
    security._own_keys.cache_clear()
    security._jwks.cache_clear()


def _claims(**overrides):
    now = int(time.time())
    claims = {"iss": "https://auth.cv.test", "aud": "cv-api", "sub": "u1", "iat": now, "exp": now + 300}
    return {**claims, **overrides}


def _rejected(token):
    with pytest.raises(ServiceError) as exc:
        security.verify_token(token)
    assert exc.value.status == 401


# ── Tokens ──────────────────────────────────────────────────────────────────

def test_token_ida_e_volta(auth_env):
    token = security.issue_token("u1", tenant="acme", roles=["admin", "ops"])
    who = security.verify_token(token)
    assert who.model_copy(update={"expires_at": None}) == Principal(sub="u1", tenant="acme", roles=frozenset({"admin", "ops"}))
    assert 0 < who.expires_at - time.time() <= 900


def test_token_expirado_e_recusado(auth_env):
    _rejected(security.issue_token("u1", ttl_seconds=-120))


def test_token_de_outro_issuer_ou_audience_e_recusado(auth_env):
    _rejected(jwt.encode(_claims(aud="outra-api"), auth_env, algorithm="EdDSA"))
    _rejected(jwt.encode(_claims(iss="https://atacante.test"), auth_env, algorithm="EdDSA"))


def test_token_sem_expiracao_e_recusado(auth_env):
    claims = _claims()
    del claims["exp"]
    _rejected(jwt.encode(claims, auth_env, algorithm="EdDSA"))


def test_token_alg_none_e_recusado(auth_env):
    _rejected(jwt.encode(_claims(), key=None, algorithm="none"))


def test_token_hs256_assinado_com_a_chave_publica_e_recusado(auth_env):
    # Ataque de confusão de algoritmo: a chave pública é conhecida, então vira "segredo" do HS256.
    public = security._own_keys()[1].public_bytes_raw()
    _rejected(jwt.encode(_claims(), public, algorithm="HS256"))


def test_token_adulterado_e_recusado(auth_env):
    header, payload, signature = security.issue_token("u1").split(".")
    forged = jwt.utils.base64url_encode(b'{"sub":"admin","roles":["admin"]}').decode()
    _rejected(f"{header}.{forged}.{signature}")


def test_token_de_outra_chave_e_recusado(auth_env):
    _rejected(jwt.encode(_claims(), Ed25519PrivateKey.generate(), algorithm="EdDSA"))


# ── Configuração insegura não sobe ──────────────────────────────────────────

@pytest.mark.parametrize(
    "env",
    [
        {"CORS_ORIGINS": "*"},
        {"AUTH_JWKS_URL": "https://idp.test/.well-known/jwks.json"},  # duas fontes de chave
        {"AUTH_ISSUER": ""},
    ],
)
def test_configuracao_insegura_impede_o_boot(auth_env, monkeypatch, env):
    for name, value in env.items():
        if value:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name)
    _clear_caches()
    with pytest.raises(RuntimeError, match="README §5.7"):
        security._settings()


def test_jwks_sem_https_e_recusado(monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", "i")
    monkeypatch.setenv("AUTH_AUDIENCE", "a")
    monkeypatch.setenv("AUTH_JWKS_URL", "http://idp.test/jwks.json")
    _clear_caches()
    with pytest.raises(RuntimeError, match="https"):
        security._settings()
    _clear_caches()


def test_par_de_chaves_trocado_e_recusado(auth_env, monkeypatch):
    other = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    monkeypatch.setenv("AUTH_PUBLIC_KEY", security._b64e(other))
    _clear_caches()
    with pytest.raises(RuntimeError, match="não formam um par"):
        security._own_keys()


# ── Senhas ──────────────────────────────────────────────────────────────────

def test_senha_argon2id():
    hashed = asyncio.run(security.hash_password("correta-cavalo-bateria"))
    assert hashed.startswith("$argon2id$")
    assert asyncio.run(security.verify_password(hashed, "correta-cavalo-bateria"))
    assert not asyncio.run(security.verify_password(hashed, "errada"))
    assert not asyncio.run(security.verify_password("hash-corrompido", "qualquer"))
    assert not security.password_needs_rehash(hashed)


def test_senha_curta_e_recusada():
    with pytest.raises(ServiceError) as exc:
        asyncio.run(security.hash_password("1234567"))
    assert exc.value.status == 422


# ── HTTP: nega por padrão, envelope e cabeçalhos ────────────────────────────

class Eco(BaseModel):
    password: str
    quantidade: int


def _app(public=("/aberta",)):
    app = FastAPI()
    envelope.install_envelope(app, service="svc-teste")
    security.install_security(app, service="svc-teste", public=public)

    @app.get("/privada")
    async def privada(p: Principal = Depends(principal)):
        return {"sub": p.sub}

    @app.get("/admin")
    async def admin(p: Principal = Depends(require("admin"))):
        return {"sub": p.sub}

    @app.get("/aberta")
    async def aberta():
        return {"ok": True}

    @app.post("/eco")
    async def eco(data: Eco):
        return data

    @app.get("/limite")
    async def limite():
        raise ServiceError("ERRO_TESTE_LIMITE", "Limite excedido.", status=409)

    @app.get("/quebra")
    async def quebra():
        raise RuntimeError("segredo-interno-que-nao-pode-vazar")

    return TestClient(app, raise_server_exceptions=False)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_rota_sem_token_e_negada_por_padrao(auth_env):
    r = _app().get("/privada")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json() == {
        "ok": False,
        "service": "svc-teste",
        "data": None,
        "error": {"code": "ERRO_AUTH_UNAUTHENTICATED", "message": "Autenticação necessária.", "status": 401, "details": []},
    }


def test_token_invalido_e_negado(auth_env):
    r = _app().get("/privada", headers=_bearer("nao.e.um.jwt"))
    assert (r.status_code, r.json()["error"]["code"]) == (401, "ERRO_AUTH_INVALID_TOKEN")


def test_token_valido_entrega_o_principal(auth_env):
    r = _app().get("/privada", headers=_bearer(security.issue_token("u1")))
    assert (r.status_code, r.json()) == (200, {"sub": "u1"})


def test_papel_exigido(auth_env):
    client = _app()
    sem_papel = client.get("/admin", headers=_bearer(security.issue_token("u1")))
    assert (sem_papel.status_code, sem_papel.json()["error"]["code"]) == (403, "ERRO_AUTH_FORBIDDEN")
    com_papel = client.get("/admin", headers=_bearer(security.issue_token("u1", roles=["admin"])))
    assert com_papel.status_code == 200


def test_rota_publica_e_explicita(auth_env):
    assert _app().get("/aberta").status_code == 200
    assert _app(public=()).get("/aberta").status_code == 401


def test_cabecalhos_de_seguranca_em_producao(auth_env):
    headers = _app().get("/aberta").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cache-control"] == "no-store"
    assert "max-age" in headers["strict-transport-security"]
    assert "default-src 'none'" in headers["content-security-policy"]


def test_docs_so_abertas_em_desenvolvimento(auth_env, monkeypatch):
    assert _app().get("/docs").status_code == 401
    monkeypatch.setenv("ENVIRONMENT", "development")
    _clear_caches()
    assert _app().get("/docs").status_code == 200


def test_payload_invalido_nao_ecoa_o_valor(auth_env):
    r = _app().post("/eco", headers=_bearer(security.issue_token("u1")), json={"password": "s3nh4-secreta"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ERRO_TESTE_INVALID_PAYLOAD"
    assert r.json()["error"]["details"][0]["loc"] == ["body", "quantidade"]
    assert r.json()["error"]["details"][0]["msg"] == "Campo obrigatório."
    assert "s3nh4-secreta" not in r.text


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"type": "string_too_short", "msg": "String should have at least 2 characters", "ctx": {"min_length": 2}}, "Mínimo de 2 caracteres."),
        ({"type": "greater_than", "msg": "Input should be greater than 0", "ctx": {"gt": 0}}, "Deve ser maior que 0."),
        ({"type": "greater_than", "msg": "Input should be greater than 0", "ctx": {"gt": 0.0}}, "Deve ser maior que 0."),
        ({"type": "less_than_equal", "msg": "...", "ctx": {"le": 9.5}}, "Deve ser menor ou igual a 9.5."),
        ({"type": "literal_error", "msg": "...", "ctx": {"expected": "'aberta' or 'paga'"}}, "Valor não permitido (aceitos: 'aberta' ou 'paga')."),
        ({"type": "value_error", "msg": "Value error, CPF inválido"}, "Value error, CPF inválido"),
        ({"type": "greater_than", "msg": "Input should be greater than 0"}, "Input should be greater than 0"),
    ],
)
def test_mensagem_de_validacao_em_portugues(error, expected):
    assert envelope.validation_message(error) == expected


def test_erro_de_negocio_sai_no_envelope(auth_env):
    r = _app().get("/limite", headers=_bearer(security.issue_token("u1")))
    assert (r.status_code, r.json()["error"]["code"]) == (409, "ERRO_TESTE_LIMITE")


def test_erro_inesperado_nao_vaza_detalhe(auth_env):
    r = _app().get("/quebra", headers=_bearer(security.issue_token("u1")))
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "ERRO_TESTE_EXECUTION_FAILED"
    assert "Informe o id" in r.json()["error"]["message"]
    assert "segredo-interno" not in r.text and "RuntimeError" not in r.text


def test_erro_inesperado_nao_chega_ao_servidor(auth_env):
    """Se a exceção subisse até o uvicorn, ele fecharia a conexão (502 avulso no gateway, que reaproveita conexões)."""
    client = TestClient(_app().app)  # raise_server_exceptions: exceção que chegasse ao servidor explodiria aqui
    r = client.get("/quebra", headers=_bearer(security.issue_token("u1")))
    assert (r.status_code, r.json()["error"]["code"]) == (500, "ERRO_TESTE_EXECUTION_FAILED")


def test_rota_inexistente_tambem_sai_no_envelope(auth_env):
    r = _app().get("/nao-existe", headers=_bearer(security.issue_token("u1")))
    assert (r.status_code, r.json()["error"]["code"]) == (404, "ERRO_HTTP_404")


# ── SSRF ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "http://1.1.1.1",  # http sem allow_http
        "https://127.0.0.1",
        "https://localhost",
        "https://169.254.169.254/latest/meta-data",  # metadados de nuvem
        "https://10.0.0.5",
        "https://192.168.0.10",
        "https://[::1]",
        "https://[::ffff:127.0.0.1]",
        "https://usuario:senha@1.1.1.1",
        "file:///etc/passwd",
    ],
)
def test_ssrf_bloqueado(url):
    with pytest.raises(ServiceError) as exc:
        asyncio.run(security.assert_public_url(url))
    assert exc.value.code == "ERRO_SSRF_BLOCKED"


def test_ip_publico_permitido():
    asyncio.run(security.assert_public_url("https://1.1.1.1/dns-query"))
    asyncio.run(security.assert_public_url("http://1.1.1.1", allow_http=True))


def test_rede_interna_so_em_desenvolvimento(auth_env, monkeypatch):
    """allow_private (receptor de teste no compose) é recusado pelo próprio core fora de development."""
    with pytest.raises(ServiceError, match="só é aceito em desenvolvimento"):
        asyncio.run(security.assert_public_url("http://receptor:8000/hooks", allow_http=True, allow_private=True))
    monkeypatch.setenv("ENVIRONMENT", "development")
    _clear_caches()
    asyncio.run(security.assert_public_url("http://receptor:8000/hooks", allow_http=True, allow_private=True))
    with pytest.raises(ServiceError):  # o esquema continua conferido
        asyncio.run(security.assert_public_url("file:///etc/passwd", allow_http=True, allow_private=True))


def test_http_client_nao_segue_redirects():
    with pytest.raises(TypeError, match="redirects"):
        asyncio.run(http.get("https://1.1.1.1", follow_redirects=True))


def test_http_client_para_de_ler_o_corpo_acima_de_max_bytes():
    async def chamadas():
        client = HttpClient()
        client._http()._transport = httpx.MockTransport(lambda request: httpx.Response(200, text="x" * 3000))
        cabe = await client.get("https://1.1.1.1/pagina", max_bytes=5000)
        with pytest.raises(ServiceError) as exc:
            await client.get("https://1.1.1.1/pagina", max_bytes=1000)
        await client.close()
        return cabe, exc.value

    cabe, erro = asyncio.run(chamadas())
    assert (cabe.status_code, len(cabe.text)) == (200, 3000)
    assert (erro.code, erro.status) == ("ERRO_HTTP_TOO_LARGE", 422)


def test_http_client_com_teto_le_resposta_comprimida_uma_vez_so():
    """Achado do N4: o Mailpit (e quase todo site) responde em gzip; o corpo lido com teto não pode ser descomprimido de novo."""
    import gzip

    async def chamada():
        client = HttpClient()
        client._http()._transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=gzip.compress(b"From: x\r\n\r\ncorpo"), headers={"Content-Encoding": "gzip"}))
        resposta = await client.get("https://1.1.1.1/raw", max_bytes=5000)
        await client.close()
        return resposta

    resposta = asyncio.run(chamada())
    assert resposta.content == b"From: x\r\n\r\ncorpo" and "content-encoding" not in resposta.headers


# ── Utilidades ──────────────────────────────────────────────────────────────

def test_http_client_nunca_reenvia_cookie():
    def servico(request):
        return httpx.Response(200, headers={"set-cookie": "sessao=de-outra-organizacao"}, json={"cookie": request.headers.get("cookie")})

    async def duas_chamadas():
        client = HttpClient()._http()
        client._transport = httpx.MockTransport(servico)
        primeira = await client.get("https://api.exemplo.com/a")
        segunda = await client.get("https://api.exemplo.com/b")
        await client.aclose()
        return primeira, segunda

    primeira, segunda = asyncio.run(duas_chamadas())
    assert primeira.headers["set-cookie"] == "sessao=de-outra-organizacao"
    assert segunda.json()["cookie"] is None


def test_redact_mascara_campos_sensiveis():
    data = {"user": "ana", "password": "x", "auth": {"Authorization": "Bearer y", "api_key": "z"}, "itens": [{"token": "t"}]}
    assert security.redact(data) == {
        "user": "ana",
        "password": "***",
        "auth": {"Authorization": "***", "api_key": "***"},
        "itens": [{"token": "***"}],
    }


def test_segredos_e_comparacao():
    assert len({security.new_secret() for _ in range(100)}) == 100
    assert security.same("abc", b"abc") and not security.same("abc", "abd")


# ── Metaprogramação Temporal ────────────────────────────────────────────────

class Entrada(BaseModel):
    valor: int


class Saida(BaseModel):
    valor: int


def test_trilho_de_activity_bloqueia_assinatura_fora_do_padrao():
    with pytest.raises(TypeError, match="viola o trilho"):

        @temporal_runner.activities("x")
        class Ruim:
            async def cobrar(self, valor: float, moeda: str) -> dict: ...


def test_activities_registra_so_metodos_publicos():
    @temporal_runner.activities("x")
    class Bom:
        async def dobrar(self, data: Entrada) -> Saida:
            return Saida(valor=await self._vezes(data.valor, 2))

        async def _vezes(self, a: int, b: int) -> int:
            return a * b

    assert getattr(Bom.dobrar, temporal_runner._MARK, False)
    assert not getattr(Bom._vezes, temporal_runner._MARK, False)
    assert asyncio.run(Bom().dobrar(Entrada(valor=4))) == Saida(valor=8)


def test_erro_de_negocio_nao_e_retentado_e_erro_de_infra_e():
    @temporal_runner.activities("x")
    class Svc:
        async def negocio(self, data: Entrada) -> Saida:
            raise ServiceError("ERRO_X_LIMITE", "Limite.", status=409)

        async def infra(self, data: Entrada) -> Saida:
            raise ServiceError("ERRO_X_INDISPONIVEL", "Fora do ar.", status=503)

    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc:
        asyncio.run(env.run(Svc().negocio, Entrada(valor=1)))
    assert exc.value.non_retryable and exc.value.type == "ERRO_X_LIMITE"
    with pytest.raises(ServiceError):
        asyncio.run(env.run(Svc().infra, Entrada(valor=1)))
    with pytest.raises(ServiceError):  # fora do Temporal (rota HTTP), continua ServiceError → envelope
        asyncio.run(Svc().negocio(Entrada(valor=1)))


# ── Trilhos de NATS e SurrealDB ─────────────────────────────────────────────

@pytest.mark.parametrize("subject", ["billing.trigger", "events.billing", "rpc.billing.cobrar", "events.Billing.x"])
def test_subject_fora_do_trilho(subject):
    with pytest.raises(ValueError, match="fora do trilho"):
        asyncio.run(nats_bus.Bus().publish(subject, Entrada(valor=1)))


def test_bus_desconectado_explica_o_que_fazer():
    with pytest.raises(RuntimeError, match="bus.connected"):
        asyncio.run(nats_bus.Bus().publish("events.billing.trigger", Entrada(valor=1)))


@pytest.mark.parametrize("table", ["users; REMOVE TABLE users", "Users", "1users", ""])
def test_nome_de_tabela_injetado_e_recusado(table):
    with pytest.raises(ValueError, match="tabela inválido"):
        asyncio.run(surreal.Database().create(table, {}))


def test_tabela_declarada_no_boot_e_validada_antes_de_conectar():
    async def boot():
        async with surreal.Database().connected(tables=["faturas; REMOVE TABLE users"]):
            pass

    with pytest.raises(ValueError, match="tabela inválido"):
        asyncio.run(boot())


def test_resultados_do_surreal_viram_tipos_simples():
    raw = {"id": RecordID("users", "abc"), "amigos": [RecordID("users", "x")], "n": 1}
    assert surreal._plain(raw) == {"id": "users:abc", "amigos": ["users:x"], "n": 1}


def test_codigo_de_erro_segue_o_nome_do_servico():
    assert envelope.error_code("svc-user-auth", "INVALID_PAYLOAD") == "ERRO_USER_AUTH_INVALID_PAYLOAD"


# ── Multi-tenancy: contexto, banco e propagação (README §5.9) ───────────────

ACME = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))


def test_tenant_que_nao_e_texto_e_recusado(auth_env):
    token = jwt.encode(_claims(tenant=["acme", "beta"]), auth_env, algorithm="EdDSA")
    _rejected(token)


def test_sem_organizacao_e_403():
    for who in (None, Principal(sub="ana")):
        with security.acting_as(who), pytest.raises(ServiceError) as exc:
            security.current_tenant()
        assert (exc.value.code, exc.value.status) == ("ERRO_TENANT_REQUIRED", 403)


def test_acting_as_restaura_o_contexto_anterior():
    with security.acting_as(ACME):
        with security.acting_as(Principal(sub="job", tenant="beta")):
            assert security.current_tenant() == "beta"
        assert security.current() == ACME
    assert security.current() is None


def test_requisicao_roda_em_nome_do_token(auth_env):
    app = FastAPI()
    envelope.install_envelope(app, service="svc-teste")
    security.install_security(app, service="svc-teste")

    @app.get("/quem")
    async def quem():
        return {"sub": security.current().sub, "tenant": security.current_tenant()}

    @app.get("/quem-sync")
    def quem_sync():  # rota síncrona roda em outra thread: o contexto vai junto
        return {"tenant": security.current_tenant()}

    client = TestClient(app, raise_server_exceptions=False)
    acme = _bearer(security.issue_token("ana", tenant="acme"))
    assert client.get("/quem", headers=acme).json() == {"sub": "ana", "tenant": "acme"}
    assert client.get("/quem-sync", headers=acme).json() == {"tenant": "acme"}
    sem_org = client.get("/quem", headers=_bearer(security.issue_token("ana")))
    assert (sem_org.status_code, sem_org.json()["error"]["code"]) == (403, "ERRO_TENANT_REQUIRED")
    assert security.current() is None


class _FakeSurreal:
    """Conexão falsa: registra o que o core manda ao banco e devolve respostas programadas."""

    def __init__(self, select=None, query=None, error=None):
        self.calls, self._select, self._query, self._error = [], select, query, error

    async def query_raw(self, sql, vars=None):
        if sql.startswith("CREATE type::table($tb)"):  # o db.create grava por consulta (carimbos com $cv_actor)
            if self._error:
                raise self._error
            return {"result": [{"status": "OK", "result": [{"id": RecordID(vars["tb"], "f1"), **vars["data"]}]}]}
        self.calls.append((sql, vars))
        return {"result": [{"status": "OK", "result": self._query}]}

    async def create(self, table, data):
        if self._error:
            raise self._error
        return {"id": RecordID(str(table), "f1"), **data}

    async def select(self, rid):
        return self._select

    async def merge(self, rid, data):
        return {"id": rid, **data}

    async def delete(self, rid):
        self.calls.append(("DELETE", rid))

    async def close(self):
        pass


def _with_db(fn, conn=None, *, who=ACME, tables=("faturas",), shared=(), unique=None, **boot):
    conn = conn or _FakeSurreal()

    async def run():
        d = surreal.Database()
        d._conn = conn
        async with d.connected(tables=tables, shared=shared, unique=unique, **boot):
            with security.acting_as(who):
                return await fn(d)

    return asyncio.run(run()), conn


def test_boot_garante_tenant_readonly_e_indices():
    _, conn = _with_db(lambda d: asyncio.sleep(0), shared=("contas",), unique={"faturas": ["numero"], "contas": ["email"]})
    sqls = [sql for sql, _ in conn.calls]
    assert "DEFINE FIELD IF NOT EXISTS tenant ON TABLE faturas TYPE string READONLY" in sqls
    assert "DEFINE INDEX IF NOT EXISTS faturas__numero__unique ON TABLE faturas FIELDS tenant, numero UNIQUE" in sqls
    assert "DEFINE INDEX IF NOT EXISTS contas__email__unique ON TABLE contas FIELDS email UNIQUE" in sqls
    assert not any("ON TABLE contas TYPE string" in sql for sql in sqls)  # tabela global não tem tenant


def test_unique_em_tabela_global_mantem_um_campo_chamado_tenant():
    _, conn = _with_db(lambda d: asyncio.sleep(0), tables=(), shared=("vinculos",), unique={"vinculos": ["user", "tenant"]})
    assert conn.calls[-1][0] == "DEFINE INDEX IF NOT EXISTS vinculos__user__tenant__unique ON TABLE vinculos FIELDS user, tenant UNIQUE"


@pytest.mark.parametrize(
    "boot, erro",
    [
        ({"tables": ("faturas",), "shared": ("faturas",)}, "em tables e em shared"),
        ({"tables": ("faturas",), "unique": {"outra": ["x"]}}, "unique cita tabela não declarada"),
    ],
)
def test_declaracao_inconsistente_impede_o_boot(boot, erro):
    with pytest.raises(ValueError, match=erro):
        _with_db(lambda d: asyncio.sleep(0), **boot)


def test_create_grava_a_organizacao_do_contexto():
    record, _ = _with_db(lambda d: d.create("faturas", {"valor": 10}))
    assert record == {"id": "faturas:f1", "valor": 10, "tenant": "acme"}


def test_organizacao_nunca_e_gravada_a_mao():
    with pytest.raises(ValueError, match="vem do contexto"):
        _with_db(lambda d: d.create("faturas", {"valor": 10, "tenant": "beta"}))
    with pytest.raises(ValueError, match="vem do contexto"):
        _with_db(lambda d: d.merge("faturas:1", {"tenant": "beta"}))


def test_tabela_nao_declarada_e_recusada():
    with pytest.raises(ValueError, match="não declarada"):
        _with_db(lambda d: d.create("outra", {}))


def test_sem_organizacao_o_banco_recusa():
    with pytest.raises(ServiceError) as exc:
        _with_db(lambda d: d.create("faturas", {}), who=Principal(sub="ana"))
    assert exc.value.code == "ERRO_TENANT_REQUIRED"


def test_query_precisa_citar_tenant_e_o_recebe_do_contexto():
    with pytest.raises(ValueError, match="query sem \\$tenant"):
        _with_db(lambda d: d.query("SELECT * FROM faturas"))
    with pytest.raises(ValueError, match="não passe tenant="):
        _with_db(lambda d: d.query("SELECT * FROM faturas WHERE tenant = $tenant", tenant="beta"))
    _, conn = _with_db(lambda d: d.query("SELECT * FROM faturas WHERE tenant = $tenant AND v > $v", v=1))
    assert conn.calls[-1] == ("SELECT * FROM faturas WHERE tenant = $tenant AND v > $v", {"v": 1, "tenant": "acme", "cv_actor": "ana"})


def test_registro_de_outra_organizacao_nao_existe():
    beta = _FakeSurreal(select={"id": "faturas:1", "tenant": "beta"})
    assert _with_db(lambda d: d.select("faturas:1"), beta)[0] is None
    acme = _FakeSurreal(select={"id": "faturas:1", "tenant": "acme"})
    assert _with_db(lambda d: d.select("faturas:1"), acme)[0] == {"id": "faturas:1", "tenant": "acme"}


def test_merge_e_delete_filtram_a_organizacao():
    with pytest.raises(ServiceError) as exc:  # nenhum registro da organização com esse id
        _with_db(lambda d: d.merge("faturas:1", {"valor": 0}), _FakeSurreal(query=[]))
    assert exc.value.status == 404
    _, conn = _with_db(lambda d: d.delete("faturas:1"))
    sql, params = conn.calls[-1]
    assert sql == "DELETE $rid WHERE tenant = $tenant" and params["tenant"] == "acme"


def test_query_shared_so_para_quem_declarou_tabelas_globais():
    with pytest.raises(RuntimeError, match="shared=\\[...\\]"):
        _with_db(lambda d: d.query_shared("SELECT * FROM contas"))
    _, conn = _with_db(lambda d: d.query_shared("SELECT * FROM contas WHERE email = $e", e="a@x"), shared=("contas",))
    assert conn.calls[-1] == ("SELECT * FROM contas WHERE email = $e", {"e": "a@x", "cv_actor": "ana"})


def test_valor_repetido_vira_409_sem_ecoar_o_valor():
    dup = InternalError("internal", "Database index `contas__email__unique` already contains 'a@x.com', with record `contas:1`")
    with pytest.raises(ServiceError) as exc:
        _with_db(lambda d: d.create("contas", {"email": "a@x.com"}), _FakeSurreal(error=dup), shared=("contas",))
    assert (exc.value.code, exc.value.status) == ("ERRO_RECORD_DUPLICATE", 409)
    assert "email" in exc.value.message and "a@x.com" not in exc.value.message


class _FakeJetStream:
    def __init__(self):
        self.published, self.callback = [], None

    async def publish(self, subject, data, headers=None):
        self.published.append((subject, headers))

    async def subscribe(self, subject, queue, cb, manual_ack, config):
        self.callback = cb


class _FakeMsg:
    def __init__(self, data, headers):
        self.data, self.headers, self.acked, self.termed = data, headers, False, False
        self.metadata = SimpleNamespace(sequence=SimpleNamespace(stream=7), num_delivered=1)

    async def ack(self):
        self.acked = True

    async def term(self):
        self.termed = True


def _connected_bus():
    b = nats_bus.Bus()
    b._nc, b._js, b._service = object(), _FakeJetStream(), "svc-teste"
    return b


def test_evento_leva_quem_publicou():
    b = _connected_bus()
    with security.acting_as(ACME):
        asyncio.run(b.publish("events.billing.trigger", Entrada(valor=1), msg_id="m1"))
    asyncio.run(b.publish("events.billing.trigger", Entrada(valor=1)))  # fora de contexto: sem cabeçalho
    (_, headers), (_, sem_contexto) = b._js.published
    assert headers["Nats-Msg-Id"] == "m1"
    assert Principal.model_validate_json(headers[nats_bus.PRINCIPAL_HEADER]) == ACME
    assert nats_bus.PRINCIPAL_HEADER not in (sem_contexto or {})  # fora de contexto: ninguém age (o trace pode ir)


def test_handler_roda_em_nome_de_quem_publicou():
    b, seen = _connected_bus(), []

    async def handler(data):
        seen.append(security.current())

    async def run():
        await b.subscribe("events.billing.trigger", handler, Entrada)
        msg = _FakeMsg(b'{"valor": 1}', {nats_bus.PRINCIPAL_HEADER: ACME.model_dump_json()})
        await b._js.callback(msg)
        await b._js.callback(_FakeMsg(b'{"valor": 1}', None))
        return msg.acked

    assert asyncio.run(run()) and seen == [ACME, None]
    assert security.current() is None


def test_cabecalho_do_temporal_ida_e_volta():
    assert temporal_runner._decode(temporal_runner._encode(ACME)) == ACME
    assert temporal_runner._decode(None) is None


def test_workflow_iniciado_leva_quem_age():
    class Next:
        async def start_workflow(self, input):
            return input.headers

    outbound = temporal_runner._ClientOutbound(Next())
    with security.acting_as(ACME):
        headers = asyncio.run(outbound.start_workflow(SimpleNamespace(headers={})))
    assert temporal_runner._decode(headers[temporal_runner._PRINCIPAL_HEADER]) == ACME


def test_workflow_repassa_quem_age_para_as_activities():
    class NextOut:
        def start_activity(self, input):
            return input.headers

    class NextIn:
        def init(self, outbound):
            self.outbound = outbound

        async def execute_workflow(self, input):
            return self.outbound.start_activity(SimpleNamespace(headers={}))

    inbound = temporal_runner._WorkflowInbound(NextIn())
    inbound.init(NextOut())
    header = temporal_runner._encode(ACME)
    carried = asyncio.run(inbound.execute_workflow(SimpleNamespace(headers={temporal_runner._PRINCIPAL_HEADER: header})))
    assert carried[temporal_runner._PRINCIPAL_HEADER] == header


def test_activity_roda_em_nome_de_quem_disparou():
    class Next:
        async def execute_activity(self, input):
            return security.current_tenant()

    inbound = temporal_runner._ActivityInbound(Next())
    input = SimpleNamespace(headers={temporal_runner._PRINCIPAL_HEADER: temporal_runner._encode(ACME)})
    assert asyncio.run(inbound.execute_activity(input)) == "acme"
    assert security.current() is None


# ── Tempo real e streaming (README §5.10) ───────────────────────────────────

class Pedaco(BaseModel):
    texto: str


class Final(BaseModel):
    texto: str


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _stream_app(gerador):
    app = FastAPI()
    envelope.install_envelope(app, service="svc-teste")

    @app.post("/responder")
    async def responder():
        return envelope.stream_response(gerador(), "svc-teste", final=Final)

    return TestClient(app, raise_server_exceptions=False)


def test_stream_entrega_pedacos_e_o_resultado_no_envelope():
    async def gerador():
        yield Pedaco(texto="Olá")
        yield Pedaco(texto=", mundo")
        yield Final(texto="Olá, mundo")

    r = _stream_app(gerador).post("/responder")
    assert r.headers["content-type"].startswith("text/event-stream") and r.headers["cache-control"] == "no-store"
    assert _sse_events(r.text) == [
        ("delta", {"texto": "Olá"}),
        ("delta", {"texto": ", mundo"}),
        ("done", {"ok": True, "service": "svc-teste", "data": {"texto": "Olá, mundo"}, "error": None}),
    ]


def test_stream_com_erro_de_negocio_ou_inesperado_sai_no_envelope_sem_vazar():
    async def negocio():
        yield Pedaco(texto="a")
        raise ServiceError("ERRO_TESTE_LIMITE", "Limite excedido.", status=409)

    async def quebra():
        yield Pedaco(texto="a")
        raise RuntimeError("segredo-interno")

    async def sem_final():
        yield Pedaco(texto="a")

    assert _sse_events(_stream_app(negocio).post("/responder").text)[-1][1]["error"]["code"] == "ERRO_TESTE_LIMITE"
    for gerador in (quebra, sem_final):
        body = _stream_app(gerador).post("/responder").text
        event, data = _sse_events(body)[-1]
        assert (event, data["error"]["code"], data["error"]["status"]) == ("error", "ERRO_TESTE_EXECUTION_FAILED", 500)
        assert "segredo" not in body and "Informe o id" in data["error"]["message"]


def test_batimento_quando_a_fonte_demora_e_fonte_fechada_quando_o_cliente_sai():
    closed = []

    async def lenta():
        try:
            await asyncio.sleep(0.05)
            yield b"pedaco"
            await asyncio.sleep(10)
            yield b"nunca"
        finally:
            closed.append(True)

    async def consumir():
        stream = envelope.with_heartbeat(lenta(), every=0.01)
        first = [await anext(stream), await anext(stream)]
        while (chunk := await anext(stream)) != b"pedaco":
            first.append(chunk)
        await stream.aclose()  # a aba fechou no meio
        return first

    chunks = asyncio.run(consumir())
    assert chunks[:2] == [b": ping\n\n", b": ping\n\n"]
    assert closed == [True]


class _FakeNats:
    def __init__(self):
        self.published, self.subscriptions = [], {}

    async def publish(self, subject, data):
        self.published.append((subject, data))

    async def subscribe(self, subject, cb):
        self.subscriptions[subject] = cb
        return SimpleNamespace(unsubscribe=lambda: self._unsubscribe(subject))

    async def _unsubscribe(self, subject):
        self.subscriptions.pop(subject)


def _live_bus(service="svc-pedidos"):
    b = nats_bus.Bus()
    b._nc, b._service = _FakeNats(), service
    return b


def test_aviso_ao_vivo_fica_na_organizacao_de_quem_age():
    b = _live_bus()
    with security.acting_as(ACME):
        asyncio.run(b.live("pedidos.criado", Entrada(valor=1)))
        asyncio.run(b.live("pedidos.criado", Entrada(valor=2), user="bia"))
        asyncio.run(b.live("pedidos.criado", Entrada(valor=3), user="auth0|123"))
    subjects = [subject for subject, _ in b._nc.published]
    assert subjects[:2] == ["live.acme.org.pedidos.criado", "live.acme.user.bia.pedidos.criado"]
    assert subjects[2].startswith("live.acme.user.h") and "|" not in subjects[2]  # id de fora vira hash seguro


@pytest.mark.parametrize("topic", ["identity.membros", "pedidos", "pedidos.Criado", "pedidos.criado.x", "live.acme.org.x"])
def test_topico_ao_vivo_fora_do_trilho(topic):
    with security.acting_as(ACME), pytest.raises(ValueError, match="fora do trilho"):
        asyncio.run(_live_bus().live(topic, Entrada(valor=1)))


def test_aviso_ao_vivo_sem_organizacao_e_recusado():
    with pytest.raises(ServiceError) as exc:
        asyncio.run(_live_bus().live("pedidos.criado", Entrada(valor=1)))
    assert exc.value.code == "ERRO_TENANT_REQUIRED"


def test_feed_ao_vivo_so_assina_a_organizacao_e_a_pessoa_do_token():
    b = _live_bus("gateway")

    async def run():
        async with b.live_feed(ACME) as queue:
            subjects = sorted(b._nc.subscriptions)
            org, user = b._nc.subscriptions["live.acme.org.>"], b._nc.subscriptions["live.acme.user.ana.>"]
            await org(SimpleNamespace(subject="live.acme.org.pedidos.criado", data=b'{"valor": 1}'))
            await user(SimpleNamespace(subject="live.acme.user.ana.identity.acesso", data=b"{}"))
            received = [queue.get_nowait(), queue.get_nowait()]
        return subjects, received, dict(b._nc.subscriptions)

    subjects, received, left = asyncio.run(run())
    assert subjects == ["live.acme.org.>", "live.acme.user.ana.>"]
    assert received == [("pedidos.criado", b'{"valor": 1}'), ("identity.acesso", b"{}")]
    assert left == {}  # conexão fechada: assinaturas desfeitas
    with pytest.raises(ServiceError):
        asyncio.run(b.live_feed(Principal(sub="ana")).__aenter__())


def test_metodo_de_streaming_nao_vira_activity_e_segue_trilho():
    @temporal_runner.activities("x")
    class Svc:
        async def responder(self, data: Entrada) -> AsyncIterator[Pedaco | Final]:
            yield Final(texto="ok")

    assert not getattr(Svc.responder, temporal_runner._MARK, False)
    with pytest.raises(TypeError, match="trilho de streaming"):

        @temporal_runner.activities("x")
        class Ruim:
            async def responder(self, pergunta: str, extra: int):
                yield pergunta


# ── IA: core/llm.py contra um provedor OpenAI-compatível falso (README §5.11) ─

def _fake_provider(request: httpx.Request) -> httpx.Response:
    """/models, /chat/completions (com e sem stream, ferramenta) e /embeddings, como um provedor de verdade."""
    body = json.loads(request.content or b"{}")
    usage = lambda p, c: {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}  # noqa: E731
    if request.url.path.endswith("/embeddings"):
        data = [{"object": "embedding", "index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"object": "list", "model": body["model"], "data": data, "usage": {"prompt_tokens": 7, "total_tokens": 7}})
    last, tools = body["messages"][-1], body.get("tools") or []
    if tools and last["role"] != "tool":
        call = {"id": "c1", "type": "function", "function": {"name": tools[0]["function"]["name"], "arguments": '{"nome": "Acme"}'}}
        message = {"role": "assistant", "content": None, "tool_calls": [call]}
        return httpx.Response(200, json={"id": "1", "object": "chat.completion", "created": 0, "model": body["model"],
                                         "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}], "usage": usage(20, 5)})
    if last["role"] == "tool":
        text = f"Ferramenta disse: {last['content']}"
    elif body.get("response_format") or "json" in json.dumps(body["messages"]).lower():
        text = '{"texto": "estruturado"}'
    else:
        text = "Resposta para " + json.dumps(last["content"], ensure_ascii=False)[:60]
    if body.get("stream"):
        words = text.split(" ")
        chunks = [{"id": "s", "object": "chat.completion.chunk", "created": 0, "model": body["model"],
                   "choices": [{"index": 0, "delta": {"content": w + (" " if i < len(words) - 1 else "")}, "finish_reason": None}]}
                  for i, w in enumerate(words)]
        chunks.append({"id": "s", "object": "chat.completion.chunk", "created": 0, "model": body["model"],
                       "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage(12, len(words))})
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())
    return httpx.Response(200, json={"id": "2", "object": "chat.completion", "created": 0, "model": body["model"],
                                     "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                     "usage": usage(12, 6)})


@pytest.fixture
def ia(monkeypatch):
    """core.llm com resolução e NATS falsos; devolve (llm, pedidos ao provedor, eventos de uso, resoluções)."""
    from core import llm as llm_module

    from core import plans as plans_module

    sent, usage_events, resolutions = [], [], []
    state = {"handler": _fake_provider, "scope": "platform", "base_url": "http://provedor-interno:9000/v1", "auth": [], "plano": []}

    def transport(request):
        sent.append(json.loads(request.content or b"{}"))
        state["auth"].append(request.headers.get("authorization"))
        return state["handler"](request)

    async def request(subject, message, response_model, timeout=5.0):
        if subject == plans_module.LIMITS_SUBJECT:  # o svc-plans responde os limites do mês da organização
            return plans_module.PlanLimits(plan="pro", plan_name="Pro", month="2026-10", limits=state["plano"])
        resolutions.append((subject, message.model, message.kind, security.current_tenant()))
        resolved = llm_module.Resolved(provider=message.model.split("/")[0], scope=state["scope"], model="falso-1",
                                       base_url=state["base_url"], api_key="sk-segredo-abcd", price_input=3.0, price_output=15.0)
        raw = envelope.ResponseEnvelope.success(resolved, "svc-ai").model_dump_json()  # como o bus.respond serializa
        return response_model.model_validate(envelope.ResponseEnvelope.model_validate_json(raw).data)

    async def publish(subject, message, msg_id=None):
        usage_events.append((subject, message))

    client = llm_module.Llm(max_retries=0)  # sem esperar novas tentativas nos testes de erro
    client._transport = httpx.MockTransport(transport)
    monkeypatch.setattr(nats_bus.bus, "request", request)
    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-pedidos")
    plans_module.plans.clear()
    with security.acting_as(ACME):
        yield client, sent, usage_events, resolutions, state
    plans_module.plans.clear()


def test_ia_responde_e_registra_uso_e_guarda_a_resolucao(ia):
    llm, sent, usage, resolutions, state = ia
    first = asyncio.run(llm.ask("local/rapido", "Olá", instructions="Seja breve."))
    asyncio.run(llm.ask("local/rapido", "De novo"))
    vectors = asyncio.run(llm.embed("local/vetores", ["um"]))
    assert first.startswith("Resposta para") and vectors
    assert state["auth"] == ["Bearer sk-segredo-abcd"] * 3  # a chave atravessa o rpc.ai.resolve inteira, não '****'
    assert sent[0]["model"] == "falso-1" and sent[0]["messages"][0]["role"] == "system"
    assert resolutions == [("rpc.ai.resolve", "local/rapido", "chat", "acme"),  # a segunda veio do cache
                           ("rpc.ai.resolve", "local/vetores", "embedding", "acme")]
    subject, event = usage[0]
    assert subject == "events.ai.usage"
    assert event.model_dump() == {"model": "local/rapido", "provider": "local", "kind": "chat", "service": "svc-pedidos",
                                   "input_tokens": 12, "output_tokens": 6, "price_input": 3.0, "price_output": 15.0}


def test_ia_chave_resolvida_mascarada_fora_do_json():
    from core.llm import Resolved

    resolved = Resolved(provider="p", scope="platform", model="m", base_url="https://x/v1", api_key="sk-segredo-abcd")
    assert "sk-" not in repr(resolved) and "sk-" not in str(resolved.model_dump())
    assert "sk-segredo-abcd" in resolved.model_dump_json()


def test_ia_agente_sem_telemetria_nem_memoria(ia):
    llm = ia[0]
    agent = asyncio.run(llm.agent("local/rapido"))
    assert agent.telemetry is False and agent.db is None and agent.post_hooks


def test_ia_em_pedacos_saida_estruturada_ferramenta_e_imagem(ia):
    llm, sent, usage, _, _ = ia

    async def pedacos():  # como o stream_response consome: cada passo numa tarefa própria (batimento)
        return [p async for p in envelope.with_heartbeat(llm.stream("local/rapido", "conte algo"))]

    class Saida(BaseModel):
        texto: str

    async def buscar_cliente(nome: str) -> str:
        """Busca um cliente pelo nome."""
        return f"cliente {nome} encontrado"

    parts = asyncio.run(pedacos())
    assert len(parts) > 2 and "".join(parts).startswith("Resposta para")
    assert asyncio.run(llm.ask("local/rapido", "responda em json", output=Saida)) == Saida(texto="estruturado")
    assert asyncio.run(llm.ask("local/rapido", "busque", tools=[buscar_cliente])) == "Ferramenta disse: cliente Acme encontrado"
    asyncio.run(llm.ask("local/rapido", "o que há na foto?", images=[Image(url="https://exemplo.com/foto.png")]))
    assert any(part.get("type") == "image_url" for part in sent[-1]["messages"][-1]["content"])
    assert [e.output_tokens > 0 for _, e in usage] == [True] * len(usage) and len(usage) == 4


def test_ia_embeddings(ia):
    llm, _, usage, resolutions, _ = ia
    vectors = asyncio.run(llm.embed("local/vetores", ["um", "dois"]))
    assert vectors == [[2.0, 1.0], [4.0, 1.0]]
    assert resolutions[-1][2] == "embedding" and usage[-1][1].kind == "embedding" and usage[-1][1].input_tokens == 7


@pytest.mark.parametrize(("status", "code"), [(401, "ERRO_AI_PROVIDER_AUTH"), (429, "ERRO_AI_RATE_LIMITED"), (500, "ERRO_AI_PROVIDER")])
def test_ia_erro_do_provedor_vira_envelope_sem_ecoar_a_mensagem_dele(ia, status, code):
    llm, _, _, _, state = ia
    state["handler"] = lambda r: httpx.Response(status, headers={"retry-after-ms": "0"}, json={"error": {"message": "chave sk-...abcd inválida"}})

    async def em_pedacos():
        return [p async for p in llm.stream("local/rapido", "oi")]

    async def em_pedacos_com_batimento():  # como o stream_response consome
        return [p async for p in envelope.with_heartbeat(llm.stream("local/rapido", "oi"))]

    calls = (lambda: llm.ask("local/rapido", "oi"), em_pedacos, em_pedacos_com_batimento, lambda: llm.embed("local/vetores", ["a"]))
    for call in calls:
        with pytest.raises(ServiceError) as exc:
            asyncio.run(call())
        assert exc.value.code == code and "sk-" not in exc.value.message


def test_ia_trilhos_de_nome_organizacao_e_rede(ia):
    llm, _, _, _, state = ia
    with pytest.raises(ValueError, match="fora do trilho"):
        asyncio.run(llm.ask("sem-provedor", "oi"))
    with security.acting_as(Principal(sub="ana")), pytest.raises(ServiceError) as exc:
        asyncio.run(llm.ask("local/rapido", "oi"))
    assert exc.value.code == "ERRO_TENANT_REQUIRED"
    state.update(scope="organization", base_url="https://10.0.0.5/v1")  # provedor da organização apontando para dentro
    llm.clear()
    with pytest.raises(ServiceError) as exc:
        asyncio.run(llm.ask("byok/modelo", "oi"))
    assert exc.value.code == "ERRO_SSRF_BLOCKED"


def test_ia_para_antes_do_provedor_quando_o_plano_do_mes_acabou(ia):
    from core.plans import LimitState

    llm, sent, usage, resolutions, state = ia
    custo = dict(name="ai.custo", service="svc-ai", description="Gasto com IA no mês", default=None, monthly=True, currency="USD")
    state["plano"] = [LimitState(**custo, limit=5, used=5.01)]
    with pytest.raises(ServiceError) as exc:
        asyncio.run(llm.ask("local/rapido", "oi"))
    assert (exc.value.code, exc.value.status) == ("ERRO_PLAN_LIMIT", 402)
    assert "Gasto com IA no mês, até USD 5,00" in exc.value.message and "Pro" in exc.value.message
    assert (sent, usage, resolutions) == ([], [], [])  # nem resolve o modelo nem chama o provedor


# ── Agentes: llm.run_agent no laço do AgentExo, com o mesmo provedor falso (README §5.11) ─

def test_agente_chama_a_ferramenta_no_loop_em_nome_de_quem_age_e_registra_cada_volta(ia):
    llm, sent, usage, resolutions, state = ia
    vistos, passos = [], []

    async def buscar_cliente(nome: str) -> str:
        """Busca um cliente da organização pelo nome."""
        vistos.append((nome, security.current_tenant()))
        return f"cliente {nome} encontrado"

    async def cenario():
        return await llm.run_agent("local/rapido", "ache a Acme", instructions="Use as ferramentas.",
                                   tools=[buscar_cliente], context="Conversa até aqui: nada.", on_step=passos.append)

    feito = asyncio.run(cenario())
    assert feito.text == "Ferramenta disse: cliente Acme encontrado"
    assert (feito.turns, feito.tool_calls, feito.input_tokens, feito.output_tokens) == (2, 1, 32, 11)
    assert vistos == [("Acme", "acme")]  # a ferramenta roda no loop do serviço, como a organização de quem pediu
    assert [(p.tool, p.status) for p in passos] == [("buscar_cliente", "running"), ("buscar_cliente", "done")]
    assert [(e.model, e.service, e.input_tokens, e.output_tokens) for _, e in usage] == [
        ("local/rapido", "svc-pedidos", 20, 5), ("local/rapido", "svc-pedidos", 12, 6)]  # uma por volta
    assert sent[0]["tools"][0]["function"]["name"] == "buscar_cliente"
    assert sent[0]["tools"][0]["function"]["description"] == "Busca um cliente da organização pelo nome."
    assert "Conversa até aqui: nada." in json.dumps(sent[0]["messages"], ensure_ascii=False)  # o contexto entra antes da tarefa
    assert state["auth"] == ["Bearer sk-segredo-abcd"] * 2 and len(resolutions) == 1


def test_agente_recebe_de_volta_o_erro_de_validacao_e_o_erro_de_negocio_para_corrigir(ia):
    llm, sent, _, _, _ = ia
    chamadas, passos = [], []

    async def reservar(nome: str, quantidade: int) -> str:
        """Reserva uma quantidade para um cliente."""
        chamadas.append((nome, quantidade))
        return "reservado"

    feito = asyncio.run(llm.run_agent("local/rapido", "reserve", instructions="x", tools=[reservar], on_step=passos.append))
    assert chamadas == [] and "argumentos inválidos: quantidade" in feito.text
    assert passos[-1].status == "failed"

    async def bloquear(nome: str) -> str:
        """Bloqueia um cliente."""
        raise ServiceError("ERRO_PEDIDOS_BLOQUEIO", "Cliente com pedido aberto não pode ser bloqueado.", status=409)

    feito = asyncio.run(llm.run_agent("local/rapido", "bloqueie", instructions="x", tools=[bloquear]))
    assert feito.text == "Ferramenta disse: ERRO_PEDIDOS_BLOQUEIO: Cliente com pedido aberto não pode ser bloqueado."

    async def quebrar(nome: str) -> str:
        """Quebra."""
        raise RuntimeError("segredo interno")

    feito = asyncio.run(llm.run_agent("local/rapido", "quebre", instructions="x", tools=[quebrar]))
    assert "falha interna" in feito.text and "segredo" not in feito.text


def test_agente_usa_ferramenta_descrita_por_schema_como_as_de_um_servidor_mcp(ia):
    from core.llm import SchemaTool

    llm, sent, _, _, _ = ia
    recebidos = []
    schema = {"type": "object", "properties": {"nome": {"type": "string", "title": "Nome", "description": "Quem buscar"}},
              "required": ["nome"]}

    async def chamar(argumentos):
        recebidos.append((argumentos, security.current_tenant()))
        if argumentos.get("nome") == "Acme":
            return {"pedidos": [{"numero": "PC-1", "valor": 7200}]}
        raise ServiceError("ERRO_X", "não achei")

    remota = SchemaTool("mcp_erp_consultar", "Consulta pedidos no ERP do cliente.", schema, chamar)
    feito = asyncio.run(llm.run_agent("local/rapido", "ache a Acme", instructions="x", tools=[remota]))
    assert recebidos == [({"nome": "Acme"}, "acme")]  # o dict como o modelo mandou, no loop, como a organização
    assert feito.text == 'Ferramenta disse: {"pedidos": [{"numero": "PC-1", "valor": 7200}]}'
    definicao = sent[0]["tools"][0]["function"]
    assert (definicao["name"], definicao["description"]) == ("mcp_erp_consultar", "Consulta pedidos no ERP do cliente.")
    assert definicao["parameters"]["properties"]["nome"] == {"type": "string", "description": "Quem buscar"}
    assert schema["properties"]["nome"]["title"] == "Nome"  # o schema de quem chamou não muda
    with pytest.raises(TypeError, match="snake_case"):
        asyncio.run(llm.run_agent("local/rapido", "x", instructions="x", tools=[SchemaTool("Ruim-Nome", "d", schema, chamar)]))


def test_agente_sobe_o_erro_do_provedor_e_do_plano_sem_ecoar_a_mensagem(ia):
    from core.plans import LimitState, plans

    llm, sent, usage, resolutions, state = ia
    state["handler"] = lambda request: httpx.Response(401, json={"error": {"message": "chave sk-segredo-abcd inválida"}})
    with pytest.raises(ServiceError) as exc:
        asyncio.run(llm.run_agent("local/rapido", "oi", instructions="x"))
    assert exc.value.code == "ERRO_AI_PROVIDER_AUTH" and "sk-" not in exc.value.message and usage == []

    sent.clear()
    plans.clear()  # os limites do mês ficam guardados por instantes no processo
    tokens = dict(name="ai.tokens", service="svc-ai", description="Tokens de IA no mês", default=None, monthly=True)
    state["plano"] = [LimitState(**tokens, limit=10, used=10)]
    with pytest.raises(ServiceError) as exc:
        asyncio.run(llm.run_agent("local/rapido", "oi", instructions="x"))
    assert exc.value.code == "ERRO_PLAN_LIMIT" and sent == []


def test_ferramenta_de_agente_precisa_de_docstring_e_tipos_e_o_schema_sai_sem_referencias(ia):
    llm, sent, _, _, _ = ia

    async def sem_doc(nome: str) -> str:
        return nome

    async def sem_tipo(nome) -> str:  # noqa: ANN001
        """Sem tipo."""
        return nome

    for ferramenta in (sem_doc, sem_tipo):
        with pytest.raises(TypeError):
            asyncio.run(llm.run_agent("local/rapido", "oi", instructions="x", tools=[ferramenta]))

    class Endereco(BaseModel):
        title: str  # um campo chamado title não some do schema
        cidade: str

    async def cadastrar(nome: str, endereco: Endereco, vip: bool = False) -> str:
        """Cadastra um cliente."""
        return "ok"

    asyncio.run(llm.run_agent("local/rapido", "cadastre", instructions="x", tools=[cadastrar]))
    schema = sent[0]["tools"][0]["function"]["parameters"]
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    assert schema["properties"]["endereco"]["properties"].keys() == {"title", "cidade"}
    assert schema["required"] == ["nome", "endereco"]

    class Contato(BaseModel):
        nome: str
        telefone: str | None = None

    recebidos = []

    async def anotar(contato: Contato) -> str:
        """Anota um contato."""
        recebidos.append(contato)
        return "anotado"

    sent.clear()
    asyncio.run(llm.run_agent("local/rapido", "anote", instructions="x", tools=[anotar]))
    assert sent[0]["tools"][0]["function"]["parameters"]["properties"].keys() == {"nome", "telefone"}  # campos achatados
    assert recebidos == [Contato(nome="Acme")]  # a função recebe o modelo validado


# ── Listas: db.page no SurrealDB embutido, com a SurrealQL de verdade (README §5.12) ─

class FaturaQuery(surreal.ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("cliente", "valor")
    default_sort: ClassVar[str | None] = "-valor"
    status: Literal["aberta", "paga"] | None = None
    valor_from: float | None = None
    valor_to: float | None = None
    cliente: list[str] | None = None


class Fatura(BaseModel):
    id: str
    cliente: str
    valor: float


class FaturaPage(surreal.Page[Fatura]):
    pass


FATURAS = [
    ("acme", "Padaria Aurora", "pão francês e café", 150, "aberta"),
    ("acme", "João da Silva", "consultoria fiscal", 900, "paga"),
    ("acme", "Mercado Bom Preço", "cestas básicas", 40, "aberta"),
    ("acme", "Aurora Tecidos", "tecidos finos", 300, "paga"),
    ("beta", "Padaria Beta", "segredo da beta", 999, "aberta"),
]


def _paginas(*queries, table="faturas", **page_kwargs):
    """Grava FATURAS no SurrealDB embutido e devolve os clientes de cada página pedida, como a Acme."""

    async def run():
        d = surreal.Database()
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        d._conn = conn
        async with d.connected(tables=["faturas", "notas"], shared=["modelos"], search={"faturas": ["cliente", "descricao"]}):
            for tenant, cliente, descricao, valor, status in FATURAS:
                with security.acting_as(Principal(sub="x", tenant=tenant)):
                    await d.create("faturas", {"cliente": cliente, "descricao": descricao, "valor": valor, "status": status})
            with security.acting_as(ACME):
                return [await d.page(table, q, FaturaPage, **page_kwargs) for q in queries]

    return asyncio.run(run())


def _clientes(page):
    return [f.cliente for f in page.items]


def test_lista_pagina_com_ordem_padrao_total_e_so_da_organizacao():
    um, dois, tres = _paginas(FaturaQuery(size=2), FaturaQuery(size=2, page=2), FaturaQuery(size=2, page=3))
    assert _clientes(um) == ["João da Silva", "Aurora Tecidos"]  # default_sort -valor; a Beta não aparece
    assert _clientes(dois) == ["Padaria Aurora", "Mercado Bom Preço"]
    assert (um.total, um.pages, um.page, um.size) == (4, 2, 1, 2)
    assert (tres.items, tres.total) == ([], 4)  # página depois da última: vazia, com o total certo


def test_lista_filtra_por_igualdade_intervalo_e_lista_e_ordena_pelo_pedido():
    abertas, faixa, escolhidos, por_nome = _paginas(
        FaturaQuery(status="aberta"),
        FaturaQuery(valor_from=100, valor_to=500),
        FaturaQuery(cliente=["Mercado Bom Preço", "Padaria Beta"]),
        FaturaQuery(sort="cliente"),
    )
    assert _clientes(abertas) == ["Padaria Aurora", "Mercado Bom Preço"]
    assert _clientes(faixa) == ["Aurora Tecidos", "Padaria Aurora"]
    assert _clientes(escolhidos) == ["Mercado Bom Preço"]  # a da Beta não vaza nem pedindo pelo nome
    assert _clientes(por_nome) == ["Aurora Tecidos", "João da Silva", "Mercado Bom Preço", "Padaria Aurora"]


def test_lista_busca_por_inicio_de_palavra_sem_acento_em_varios_campos():
    pad, joao, aurora, cafe, nada, ordenada = _paginas(
        FaturaQuery(q="pad"), FaturaQuery(q="joao"), FaturaQuery(q="AURORA"), FaturaQuery(q="cafe"),
        FaturaQuery(q="xyz"), FaturaQuery(q="aurora", sort="-valor"),
    )
    assert _clientes(pad) == ["Padaria Aurora"]  # a Padaria Beta é de outra organização
    assert _clientes(joao) == ["João da Silva"]
    assert sorted(_clientes(aurora)) == ["Aurora Tecidos", "Padaria Aurora"] and aurora.total == 2
    assert _clientes(cafe) == ["Padaria Aurora"]  # achada pela descrição
    assert (nada.items, nada.total, nada.pages) == ([], 0, 0)
    assert _clientes(ordenada) == ["Aurora Tecidos", "Padaria Aurora"]


def test_lista_recusa_o_que_esta_fora_do_trilho():
    with pytest.raises(ServiceError) as exc:  # notas não declarou busca
        _paginas(FaturaQuery(q="x"), table="notas")
    assert (exc.value.code, exc.value.status) == ("ERRO_SEARCH_UNAVAILABLE", 422)
    with pytest.raises(ValueError, match="tabela global"):
        _paginas(FaturaQuery(), table="modelos")
    with pytest.raises(ValueError, match="reservados"):
        _paginas(FaturaQuery(), tenant="beta")
    with pytest.raises(ValidationError):
        FaturaQuery(sort="descricao")  # não está em sortable
    with pytest.raises(ValidationError):
        FaturaQuery(size=101)
    assert FaturaQuery.model_validate({"page": "2", "aba": "modelos"}).page == 2  # parâmetro alheio da URL é ignorado
    with pytest.raises(TypeError, match="sortable"):
        class Ruim(surreal.ListQuery):
            default_sort: ClassVar[str | None] = "-valor"


# ── Ciclo de vida: carimbos, tarefas da plataforma e migrações (README §5.13) ─

def _banco(cenario, **boot):
    """SurrealDB embutido com as tabelas do boot; devolve o que o cenário devolver."""

    async def run():
        d = surreal.Database()
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        d._conn = conn
        async with d.connected(**{"tables": ["notas"], **boot}):
            return await cenario(d)

    return asyncio.run(run())


def test_carimbos_de_quem_criou_e_alterou_e_quando():
    async def cenario(d):
        with security.acting_as(ACME):
            nota = await d.create("notas", {"texto": "a"})
        await asyncio.sleep(0.01)
        with security.acting_as(Principal(sub="bia", tenant="acme")):
            alterada = await d.merge(nota["id"], {"texto": "b"})
            crua = await d.query("UPDATE notas SET texto = 'c' WHERE tenant = $tenant RETURN AFTER")
        with security.acting_as(security.system("svc-notas", "acme")):
            sistema = await d.query("UPDATE notas SET texto = 'd' WHERE tenant = $tenant RETURN AFTER")
        return nota, alterada, crua[0], sistema[0]

    nota, alterada, crua, sistema = _banco(cenario)
    assert (nota["created_by"], nota["updated_by"]) == ("ana", "ana") and nota["created_at"] is not None
    assert (alterada["created_by"], alterada["updated_by"]) == ("ana", "bia")  # quem criou não muda
    assert alterada["created_at"] == nota["created_at"] and alterada["updated_at"] > nota["updated_at"]
    assert crua["updated_by"] == "bia"  # vale também para a SurrealQL crua do serviço
    assert sistema["updated_by"] == "system:svc-notas"


def test_carimbo_nunca_e_gravado_a_mao_nem_trocado():
    with pytest.raises(ValueError, match="carimba"):
        _with_db(lambda d: d.create("faturas", {"valor": 1, "created_at": "2020-01-01"}))
    with pytest.raises(ValueError, match="carimba"):
        _with_db(lambda d: d.merge("faturas:1", {"updated_by": "outro"}))
    with pytest.raises(ValueError, match="cv_actor"):
        _with_db(lambda d: d.query("SELECT * FROM faturas WHERE tenant = $tenant", cv_actor="outro"))

    async def troca(d):
        with security.acting_as(ACME):
            nota = await d.create("notas", {"texto": "a"})
            await d.query("UPDATE $rid SET created_by = 'intruso' WHERE tenant = $tenant", rid=RecordID("notas", nota["id"].split(":")[1]))

    with pytest.raises(Exception, match="created_by"):  # o próprio banco recusa (READONLY)
        _banco(troca)


def test_tarefa_da_plataforma_lista_organizacoes_e_pessoa_nao():
    async def cenario(d):
        for org in ("beta", "acme", "acme"):
            with security.acting_as(Principal(sub="x", tenant=org)):
                await d.create("notas", {"texto": org})
        sem_ninguem = await d.tenants("notas")
        with security.acting_as(security.system("svc-notas")):
            como_sistema = await d.tenants("notas")
        with security.acting_as(ACME), pytest.raises(PermissionError):
            await d.tenants("notas")
        return sem_ninguem, como_sistema

    assert _banco(cenario) == (["acme", "beta"], ["acme", "beta"])
    with pytest.raises(ValueError, match="reservado"):
        security.issue_token("system:svc-notas")


def _migracoes(*levas):
    """Sobe o banco uma vez por leva de migrações (como boots sucessivos) e devolve as notas e o registro."""

    async def run():
        d = surreal.Database()
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        resultados = []
        for leva in levas:
            d._conn = conn
            try:
                async with d.connected(tables=["notas"], migrations=leva, service="svc-notas"):
                    pass
                resultados.append("ok")
            except RuntimeError as exc:
                resultados.append(str(exc))
            d._conn = conn
        registro = await conn.query("SELECT version, status, error FROM cv_migrations ORDER BY version")
        notas = await conn.query("SELECT texto, created_by FROM notas ORDER BY texto")
        return resultados, registro, notas

    return asyncio.run(run())


def test_migracoes_rodam_uma_vez_em_ordem_e_param_o_boot_quando_falham():
    chamadas = []

    async def via_python():
        chamadas.append(security.current().sub)

    async def quebra():
        raise RuntimeError("bug")

    um = surreal.Migration(1, "cria nota", sql="CREATE notas SET texto = 'm1', tenant = 'acme'")
    dois = surreal.Migration(2, "via python", run=via_python)
    tres_quebrada = surreal.Migration(3, "quebra", run=quebra)
    tres_corrigida = surreal.Migration(3, "corrigida", sql="UPDATE notas SET texto = 'm3' WHERE texto = 'm1'")
    resultados, registro, notas = _migracoes([um, dois], [um, dois], [um, dois, tres_quebrada], [um, dois, tres_corrigida])
    assert resultados[:2] == ["ok", "ok"] and "#3 (quebra) falhou" in resultados[2] and resultados[3] == "ok"
    assert chamadas == ["system:svc-notas"]  # a #2 rodou uma vez só, como tarefa da plataforma
    assert [(r["version"], r["status"]) for r in registro] == [(1, "done"), (2, "done"), (3, "done")]
    assert [(n["texto"], n["created_by"]) for n in notas] == [("m3", "system:svc-notas")]  # #1 uma vez; a #3 corrigida rodou


@pytest.mark.parametrize(
    ("migracoes", "service", "erro"),
    [
        ([surreal.Migration(2, "x", sql="RETURN 1")], "svc-notas", "1, 2, 3"),
        ([surreal.Migration(1, "x", sql="RETURN 1"), surreal.Migration(1, "y", sql="RETURN 1")], "svc-notas", "1, 2, 3"),
        ([surreal.Migration(1, "x")], "svc-notas", "sql= ou run="),
        ([surreal.Migration(1, "x", sql="RETURN 1")], None, "service=SERVICE"),
    ],
)
def test_migracoes_fora_do_trilho_impedem_o_boot(migracoes, service, erro):
    with pytest.raises(ValueError, match=erro):
        _with_db(lambda d: asyncio.sleep(0), migrations=migracoes, service=service)


# ── Agendamentos (core/temporal_runner.py, README §5.13) ────────────────────

from temporalio import workflow as _workflow  # noqa: E402
from temporalio.client import ScheduleAlreadyRunningError, ScheduleOverlapPolicy  # noqa: E402


@_workflow.defn
class _Limpeza:
    @_workflow.run
    async def run(self) -> None:
        pass


class _FakeSchedules:
    """Temporal falso: guarda os agendamentos por id e registra criar, atualizar e remover."""

    def __init__(self, existing):
        self.existing, self.calls = set(existing), []

    async def list_schedules(self):
        async def listed():
            for schedule_id in sorted(self.existing):
                yield SimpleNamespace(id=schedule_id)

        return listed()

    async def create_schedule(self, schedule_id, schedule):
        if schedule_id in self.existing:
            raise ScheduleAlreadyRunningError()
        self.existing.add(schedule_id)
        self.calls.append(("criar", schedule_id, list(schedule.spec.cron_expressions), schedule.spec.time_zone_name, schedule.policy.overlap))

    def get_schedule_handle(self, schedule_id):
        fake = self

        class Handle:
            async def update(self, updater):
                fake.calls.append(("atualizar", schedule_id, list(updater(None).schedule.spec.cron_expressions)))

            async def delete(self):
                fake.existing.discard(schedule_id)
                fake.calls.append(("remover", schedule_id))

        return Handle()


def test_agendamentos_declarados_sao_criados_atualizados_e_removidos():
    fake = _FakeSchedules({"fila/antigo", "fila/limpeza", "outra-fila/dela"})
    runner = temporal_runner.Runner()
    runner._client = fake
    declarados = [
        temporal_runner.Schedule("limpeza", "0 4 * * *", _Limpeza.run),
        temporal_runner.Schedule("relatorio", "0 8 * * 1", _Limpeza.run, timezone="America/Sao_Paulo"),
    ]
    asyncio.run(runner.sync_schedules("fila", declarados))
    asyncio.run(runner.sync_schedules("fila", declarados))  # segundo boot: só atualiza
    assert fake.calls == [
        ("atualizar", "fila/limpeza", ["0 4 * * *"]),
        ("criar", "fila/relatorio", ["0 8 * * 1"], "America/Sao_Paulo", ScheduleOverlapPolicy.SKIP),
        ("remover", "fila/antigo"),  # saiu da lista do serviço
        ("atualizar", "fila/limpeza", ["0 4 * * *"]),
        ("atualizar", "fila/relatorio", ["0 8 * * 1"]),
    ]
    assert "outra-fila/dela" in fake.existing  # o de outro serviço não é tocado


@pytest.mark.parametrize(("args", "erro"), [(("Limpeza", "0 4 * * *"), "kebab-case"), (("limpeza", "0 4 * *"), "5 campos")])
def test_agendamento_fora_do_trilho(args, erro):
    with pytest.raises(ValueError, match=erro):
        temporal_runner.Schedule(*args, _Limpeza.run)


def test_erro_em_qualquer_comando_da_consulta_chega_ao_servico():
    """O SDK só conferia o primeiro comando: no SurrealDB 3, num BEGIN; X; COMMIT o erro de X passava em silêncio."""

    async def cenario(d):
        with security.acting_as(ACME):
            await d.create("notas", {"texto": "a"})
            with pytest.raises(Exception, match="falha de propósito"):
                await d.query("UPDATE notas SET texto = 'b' WHERE tenant = $tenant; THROW 'falha de propósito'")
            with pytest.raises(Exception, match="falha de propósito"):
                await d.query("BEGIN TRANSACTION; UPDATE notas SET texto = 'c' WHERE tenant = $tenant; THROW 'falha de propósito'; COMMIT TRANSACTION;")
            return await d.query("SELECT VALUE texto FROM notas WHERE tenant = $tenant")

    assert _banco(cenario) == ["b"]  # sem transação o UPDATE valeu; com transação, nada mudou


def test_migracao_que_falha_em_comando_seguinte_nao_fica_como_feita():
    quebra = surreal.Migration(1, "quebra no segundo comando", sql="UPDATE notas SET x = 1; THROW 'falha de propósito'")
    resultados, registro, _ = _migracoes([quebra])
    assert "#1 (quebra no segundo comando) falhou" in resultados[0]
    assert [(r["version"], r["status"]) for r in registro] == [(1, "failed")]


# ── Arquivos (core/storage.py, README §5.14) — S3 simulado pelo moto ─────────

from moto import mock_aws  # noqa: E402

from core import storage as storage_module  # noqa: E402
from core.storage import UploadRequest  # noqa: E402


@pytest.fixture
def arquivos(monkeypatch):
    """storage conectado a um S3 simulado; devolve (storage, client) para simular o PUT do navegador."""
    for name, value in {"STORAGE_URL": "https://s3.us-east-1.amazonaws.com", "STORAGE_BUCKET": "cv-teste", "STORAGE_ACCESS_KEY": "a",
                        "STORAGE_SECRET_KEY": "b", "STORAGE_CORS_ORIGINS": "http://localhost:5173"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        s = storage_module.Storage()
        asyncio.run(s.connected("svc-notas"))
        yield s, s._client


def _envia(client, upload, body):
    """O que o navegador faz com o link: PUT com os cabeçalhos devolvidos (aqui, direto no S3 simulado)."""
    meta = {k.removeprefix("x-amz-meta-"): v for k, v in upload.headers.items() if k.startswith("x-amz-meta-")}
    client.put_object(Bucket="cv-teste", Key=upload.key, Body=body, ContentType=upload.headers["Content-Type"], Metadata=meta)


def test_arquivo_envio_assinado_guardado_e_baixado_so_pela_organizacao(arquivos):
    s, client = arquivos
    with security.acting_as(ACME):
        upload = asyncio.run(s.upload(UploadRequest(filename="C:\\fotos\\logo final.png", content_type="image/png", size=4),
                                      accept=storage_module.IMAGES, max_bytes=1000))
        _envia(client, upload, b"\x89PNG")
        guardado = asyncio.run(s.keep(upload.key))
        link = s.url(guardado.key, filename=guardado.filename, content_type=guardado.content_type)
    assert upload.key.startswith("tmp/acme/svc-notas/files/") and "Signature" in upload.url
    assert "content-length" in upload.url.lower()  # o tamanho entra na assinatura: outro tamanho é recusado
    assert (guardado.key.split("/")[:4], guardado.filename, guardado.size) == (["t", "acme", "svc-notas", "files"], "logo final.png", 4)
    assert "inline" in link and "logo%2520final.png" in link  # imagem abre na tela, com o nome original
    assert client.list_objects_v2(Bucket="cv-teste", Prefix="tmp/").get("KeyCount") == 0  # saiu da área temporária
    with security.acting_as(Principal(sub="bia", tenant="beta")):
        for tentativa in (lambda: s.url(guardado.key), lambda: asyncio.run(s.delete(guardado.key))):
            with pytest.raises(ServiceError) as exc:
                tentativa()
            assert exc.value.code == "ERRO_FILE_NOT_FOUND"  # de outra organização: não existe
    with security.acting_as(ACME):
        with pytest.raises(ServiceError):  # confirmar de novo: o temporário já não existe
            asyncio.run(s.keep(upload.key))
        asyncio.run(s.delete(guardado.key))
    assert client.list_objects_v2(Bucket="cv-teste").get("KeyCount") == 0


def test_arquivo_guardado_e_lido_pelo_servico_com_teto_de_tamanho(arquivos):
    s, client = arquivos
    with security.acting_as(ACME):
        upload = asyncio.run(s.upload(UploadRequest(filename="contrato.txt", content_type="text/plain", size=11),
                                      accept=("text/",), max_bytes=100))
        _envia(client, upload, b"ola contrato")
        guardado = asyncio.run(s.keep(upload.key))
        assert asyncio.run(s.read(guardado.key, max_bytes=100)) == b"ola contrato"
        with pytest.raises(ServiceError) as exc:
            asyncio.run(s.read(guardado.key, max_bytes=5))
        assert exc.value.code == "ERRO_FILE_TOO_LARGE"
    with security.acting_as(Principal(sub="bia", tenant="beta")), pytest.raises(ServiceError) as exc:
        asyncio.run(s.read(guardado.key, max_bytes=100))
    assert exc.value.code == "ERRO_FILE_NOT_FOUND"  # de outra organização: não existe


def test_arquivo_recebido_pelo_servico_e_guardado_direto_na_organizacao(arquivos):
    s, client = arquivos
    with security.acting_as(ACME):
        guardado = asyncio.run(s.save(b"%PDF-1.4 boleto", filename="../boleto maio.pdf", content_type="application/pdf", max_bytes=100))
        assert asyncio.run(s.read(guardado.key, max_bytes=100)) == b"%PDF-1.4 boleto"
        with pytest.raises(ServiceError) as grande:
            asyncio.run(s.save(b"x" * 101, filename="a.pdf", content_type="application/pdf", max_bytes=100))
    assert guardado.key.split("/")[:4] == ["t", "acme", "svc-notas", "files"] and guardado.filename == "boleto maio.pdf"
    assert grande.value.code == "ERRO_FILE_TOO_LARGE"
    with security.acting_as(Principal(sub="bia", tenant="beta")), pytest.raises(ServiceError):
        asyncio.run(s.read(guardado.key, max_bytes=100))  # de outra organização: não existe


def test_arquivo_recusado_antes_de_assinar_e_chaves_forjadas(arquivos):
    s, client = arquivos
    with security.acting_as(ACME):
        for pedido, codigo in (
            (UploadRequest(filename="a.html", content_type="text/html", size=10), "ERRO_FILE_TYPE"),
            (UploadRequest(filename="a.png", content_type="image/png", size=5000), "ERRO_FILE_TOO_LARGE"),
        ):
            with pytest.raises(ServiceError) as exc:
                asyncio.run(s.upload(pedido, accept=("image/",), max_bytes=1000))
            assert (exc.value.code, exc.value.status) == (codigo, 422)
        for forjada in ("tmp/beta/svc-notas/files/" + "a" * 32, "t/acme/svc-notas/files/" + "a" * 32, "tmp/acme/svc-outro/files/x",
                        "tmp/acme/svc-notas/../../t/beta"):
            with pytest.raises(ServiceError):
                asyncio.run(s.keep(forjada))
        pdf = s.url("t/acme/svc-notas/files/" + "b" * 32, filename="r.pdf", content_type="application/pdf")
        svg = s.url("t/acme/svc-notas/files/" + "c" * 32, filename="x.svg", content_type="image/svg+xml")
    assert "inline" in pdf and "attachment" in svg and "application%2Foctet-stream" in svg  # SVG pode ter script
    lifecycle = client.get_bucket_lifecycle_configuration(Bucket="cv-teste")["Rules"]
    assert any(r["Filter"]["Prefix"] == "tmp/" and r["Expiration"]["Days"] == 1 for r in lifecycle)
    assert client.get_bucket_cors(Bucket="cv-teste")["CORSRules"][0]["AllowedOrigins"] == ["http://localhost:5173"]
    with pytest.raises(ValidationError):
        UploadRequest(filename="a", content_type="não é tipo", size=1)


# ── Avisos: core/notify.py (README §5.15) ────────────────────────────────────

from core import notify as notify_module  # noqa: E402
from core.notify import SEND_SUBJECT, NotifyRequest, notify  # noqa: E402


@pytest.fixture
def avisos(monkeypatch):
    """Bus em memória: devolve (subject, pedido, msg_id, quem age) de cada publicação."""
    sent = []

    async def publish(subject, message, msg_id=None):
        sent.append((subject, message, msg_id, security.current()))

    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-faturas")
    return sent


def test_aviso_vai_para_o_svc_notify_com_quem_age_e_id_estavel(avisos):
    async def go():
        with security.acting_as(ACME):
            await notify.user("bia", "Fatura paga", "A fatura 123 foi paga.", link="/faturas?id=123", key="fatura-123-paga")
            await notify.user(["bia", "caio", "bia"], "Duas pessoas", send_email=False)
            await notify.roles("owner", "admin", title="Limite de IA", link="/ia")
        await notify.email("Pessoa@X.com", "Convite para Acme", link="/convite?codigo=abc", action="Ver convite")

    asyncio.run(go())
    (s1, r1, id1, who1), (_, r2, id2, _), (_, r3, _, _), (_, r4, id4, who4) = avisos
    assert (s1, r1.service, r1.users, r1.link, id1) == (SEND_SUBJECT, "svc-faturas", ["bia"], "/faturas?id=123", "notify-svc-faturas-fatura-123-paga")
    assert who1.tenant == "acme"  # a organização viaja no cabeçalho, nunca no pedido
    assert (r2.users, r2.send_email) == (["bia", "caio"], False) and id2.startswith("notify-") and id2 != id1
    assert r3.roles == ["owner", "admin"]
    assert (r4.email, r4.action, who4) == ("pessoa@x.com", "Ver convite", None)  # e-mail avulso: sem organização


def test_aviso_fora_do_trilho_nao_sai(avisos):
    async def go(call):
        with security.acting_as(ACME):
            await call()

    with pytest.raises(ValidationError):  # link para fora vira phishing: só caminho da aplicação
        asyncio.run(go(lambda: notify.user("bia", "Oi", link="https://outro.site/x")))
    with pytest.raises(ValidationError):
        asyncio.run(go(lambda: notify.email("não é e-mail", "Oi")))
    with pytest.raises(ValueError, match="key"):
        asyncio.run(go(lambda: notify.user("bia", "Oi", key="tem espaço")))
    with pytest.raises(ServiceError) as sem_org:  # sem organização não há quem avisar
        asyncio.run(notify.user("bia", "Oi"))
    assert sem_org.value.code == "ERRO_TENANT_REQUIRED"
    with pytest.raises(ValidationError):
        NotifyRequest(service="svc-x", title="Sem destino")
    assert avisos == []


def test_aviso_exige_bus_conectado(monkeypatch):
    monkeypatch.setattr(nats_bus.bus, "_service", None)
    with pytest.raises(RuntimeError, match="bus não conectado"):
        asyncio.run(notify_module.notify.email("a@b.com", "Oi"))


# ── Webhooks: core/webhooks.py (README §5.16) ────────────────────────────────

from core import webhooks as webhooks_module  # noqa: E402
from core.webhooks import CATALOG_SUBJECT, EMIT_SUBJECT, WebhookEvent, webhooks  # noqa: E402


class FaturaPaga(BaseModel):
    id: str
    valor: float


class Outro(BaseModel):
    x: int = 1


@pytest.fixture
def ganchos(monkeypatch):
    """Bus em memória e um serviço que declara um evento; devolve (subject, mensagem, msg_id, quem age)."""
    sent = []

    async def publish(subject, message, msg_id=None):
        sent.append((subject, message, msg_id, security.current()))

    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-faturas")
    monkeypatch.setattr(webhooks, "_declared", {})
    asyncio.run(webhooks.declare([WebhookEvent("paga", "Uma fatura foi paga.", FaturaPaga)]))
    return sent


def test_webhook_declarado_vai_ao_catalogo_e_emite_na_organizacao(ganchos):
    async def go():
        with security.acting_as(ACME):
            await webhooks.emit("paga", FaturaPaga(id="f1", valor=10.5), key="f1-paga")

    asyncio.run(go())
    (s1, catalog, id1, _), (s2, emitted, id2, who) = ganchos
    assert (s1, catalog.service, [e.name for e in catalog.events]) == (CATALOG_SUBJECT, "svc-faturas", ["faturas.paga"])
    assert catalog.events[0].payload_schema["properties"]["valor"]["type"] == "number"  # o cliente vê o formato do data
    assert id1.startswith("catalog-svc-faturas-")  # réplicas que sobem juntas publicam uma vez só
    assert (s2, emitted.event, emitted.data, id2, who.tenant) == (
        EMIT_SUBJECT, "faturas.paga", {"id": "f1", "valor": 10.5}, "webhook-svc-faturas-f1-paga", "acme")


def test_webhook_fora_do_trilho_nao_sai(ganchos):
    ganchos.clear()

    async def go(call):
        with security.acting_as(ACME):
            await call()

    with pytest.raises(ValueError, match="não declarado"):
        asyncio.run(go(lambda: webhooks.emit("estornada", FaturaPaga(id="f1", valor=1))))
    with pytest.raises(TypeError, match="leva FaturaPaga"):
        asyncio.run(go(lambda: webhooks.emit("paga", Outro())))
    with pytest.raises(ServiceError) as sem_org:
        asyncio.run(webhooks.emit("paga", FaturaPaga(id="f1", valor=1)))
    assert sem_org.value.code == "ERRO_TENANT_REQUIRED"
    with pytest.raises(ValueError, match="kebab-case"):
        WebhookEvent("Fatura_Paga", "Uma fatura foi paga.", FaturaPaga)
    with pytest.raises(ValueError, match="repetido"):
        asyncio.run(webhooks.declare([WebhookEvent("paga", "Uma.", FaturaPaga), WebhookEvent("paga", "Outra.", FaturaPaga)]))
    assert ganchos == []


def test_assinatura_segue_o_padrao_e_confere_quem_chega():
    # Vetor publicado do Standard Webhooks: quem recebe com qualquer biblioteca do padrão confere igual.
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    body = b'{"test": 2432232314}'
    assert webhooks.sign(secret, "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, body) == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
    now = int(time.time())
    good = webhooks.sign(secret, "msg_1", now, body)
    webhooks.verify(secret, {"webhook-id": "msg_1", "webhook-timestamp": str(now), "webhook-signature": good}, body)
    webhooks.verify(secret, {"Svix-Id": "msg_1", "Svix-Timestamp": str(now), "Svix-Signature": f"v1,AAAA {good}"}, body)
    bad_cases = [
        ({"webhook-id": "msg_1", "webhook-timestamp": str(now), "webhook-signature": good}, body + b" "),  # corpo mexido
        ({"webhook-id": "msg_2", "webhook-timestamp": str(now), "webhook-signature": good}, body),  # outro id
        ({"webhook-id": "msg_1", "webhook-timestamp": str(now - 600),
          "webhook-signature": webhooks.sign(secret, "msg_1", now - 600, body)}, body),  # cópia velha
        ({"webhook-id": "msg_1", "webhook-timestamp": "x", "webhook-signature": good}, body),
        ({"webhook-id": "msg_1", "webhook-timestamp": str(now)}, body),
    ]
    for headers, raw in bad_cases:
        with pytest.raises(ServiceError) as exc:
            webhooks.verify(secret, headers, raw)
        assert (exc.value.code, exc.value.status) == ("ERRO_WEBHOOK_SIGNATURE", 401)
    assert webhooks.new_secret().startswith("whsec_") and webhooks.new_secret() != webhooks.new_secret()


def test_webhook_exige_bus_conectado(monkeypatch):
    monkeypatch.setattr(nats_bus.bus, "_service", None)
    with pytest.raises(RuntimeError, match="bus não conectado"):
        asyncio.run(webhooks_module.webhooks.declare([]))


# ── Planos e limites: core/plans.py (README §5.17) ───────────────────────────

from core import plans as plans_module  # noqa: E402
from core.plans import (  # noqa: E402
    ASSIGN_SUBJECT,
    COUNT_SUBJECT,
    LIMITS_SUBJECT,
    USAGE_SUBJECT,
    Assigned,
    Limit,
    LimitState,
    Module,
    ModuleState,
    PlanLimits,
    plans,
)

BETA = Principal(sub="bia", tenant="beta", roles=frozenset({"owner"}))
ENDERECOS = Limit("enderecos", "Endereços de webhook", default=20, unit="endereços")
CUSTO = Limit("custo", "Gasto com IA no mês", monthly=True, currency="USD")
MODULO_FATURAS = Module("Faturas", "Faturas e cobranças da organização", category="Financeiro", limits=[ENDERECOS, CUSTO])


def _modulo(name="faturas", enabled=True, title="Faturas"):
    return ModuleState(name=name, service=f"svc-{name}", title=title, description="Módulo de teste", category="Financeiro",
                       core=False, default=True, requires=[], enabled=enabled)


def _estado(name, limit, used=0, monthly=False, description="Endereços de webhook", unit="endereços", currency=None):
    return LimitState(name=name, service="svc-x", description=description, default=None, monthly=monthly, unit=unit,
                      currency=currency, limit=limit, used=used)


@pytest.fixture
def plano(monkeypatch):
    """Serviço svc-faturas (módulo com dois limites) e um svc-plans de mentira. Devolve o que aconteceu."""
    box = SimpleNamespace(published=[], requests=[], limits=[], modules=[], plan="pro", fail=None)

    async def publish(subject, message, msg_id=None):
        box.published.append((subject, message, msg_id, security.current()))

    async def request(subject, message, response_model, timeout=5.0):
        box.requests.append((subject, security.current_tenant()))
        if box.fail is not None:
            raise box.fail
        if subject == ASSIGN_SUBJECT:
            return Assigned(tenant=security.current_tenant(), plan=message.plan, plan_name=message.plan.title(), modules=message.modules or {})
        return PlanLimits(plan=box.plan, plan_name=(box.plan or "").title(), month="2026-10", limits=box.limits, modules=box.modules)

    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "request", request)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-faturas")
    monkeypatch.setattr(plans, "_declared", {})
    monkeypatch.setattr(plans, "_module", None)  # a conferência de módulo é do processo: volta ao fim do teste
    plans.clear()
    asyncio.run(plans.declare(MODULO_FATURAS))
    yield box
    plans.clear()


def _como(who, call):
    async def go():
        with security.acting_as(who):
            return await call()

    return asyncio.run(go())


def _limite(call):
    with pytest.raises(ServiceError) as exc:
        call()
    assert (exc.value.code, exc.value.status) == ("ERRO_PLAN_LIMIT", 402)
    return exc.value.message


def test_modulo_e_limites_declarados_vao_ao_catalogo(plano):
    subject, catalog, msg_id, _ = plano.published[0]
    assert (subject, catalog.service, msg_id.startswith("catalog-svc-faturas-")) == ("events.plans.catalog", "svc-faturas", True)
    module = catalog.module
    assert (module.name, module.title, module.category, module.core, module.default, module.requires) == (
        "faturas", "Faturas", "Financeiro", False, True, [])
    assert [(c.name, c.default, c.monthly, c.unit, c.currency) for c in catalog.limits] == [
        ("faturas.enderecos", 20, False, "endereços", None), ("faturas.custo", None, True, "", "USD")]
    with pytest.raises(ValueError, match="repetido"):
        Module("Faturas", "Faturas da organização", limits=[ENDERECOS, ENDERECOS])
    with pytest.raises(ValueError, match="kebab-case"):
        Limit("Endereços", "Endereços de webhook")
    with pytest.raises(ValueError, match="sem svc-"):
        Module("Vendas", "Funil e propostas", requires=["svc-crm"])
    with pytest.raises(ValueError, match="não depende"):
        Module("Pessoas", "Contas e acesso", core=True, requires=["crm"])
    with pytest.raises(ValueError, match="si mesmo"):
        asyncio.run(plans.declare(Module("Faturas", "Faturas da organização", requires=["faturas"])))


def test_modulo_desligado_recusa_quem_chama_e_o_default_vale_ate_o_catalogo(plano, monkeypatch):
    plano.modules = [_modulo(enabled=False)]
    with pytest.raises(ServiceError) as fora:
        _como(ACME, lambda: plans._gate(ACME))
    assert (fora.value.code, fora.value.status) == ("ERRO_PLAN_MODULE", 402)
    assert fora.value.message == "Faturas não está incluído no plano Pro. Veja em Plano."
    plano.modules, plano.plan = [_modulo(enabled=True)], None
    plans.clear()
    _como(ACME, lambda: plans._gate(ACME))
    plano.modules = []  # o svc-plans ainda não gravou o catálogo: vale o default declarado
    plans.clear()
    _como(ACME, lambda: plans._gate(ACME))
    monkeypatch.setattr(plans, "_module", Module("Faturas", "Faturas da organização", default=False))
    plans.clear()
    with pytest.raises(ServiceError, match="para a organização"):
        _como(ACME, lambda: plans._gate(ACME))
    plano.fail = nats_bus.nats.errors.NoRespondersError()  # svc-plans fora do ar e nada guardado: todo módulo ligado
    plans.clear()
    _como(ACME, lambda: plans._gate(ACME))
    monkeypatch.setattr(plans, "_module", Module("Pessoas", "Contas e acesso", core=True))
    plano.fail, plano.modules = None, [_modulo(enabled=False)]
    plans.clear()
    _como(ACME, lambda: plans._gate(ACME))  # módulo da plataforma: sempre ligado, nem pergunta
    assert [s for s, _ in plano.requests].count(LIMITS_SUBJECT) == 5  # o da plataforma não perguntou


def test_modulo_desligado_recusa_http_evento_e_rpc_mas_nao_a_plataforma(plano, auth_env):
    plano.modules = [_modulo(enabled=False)]
    client = _app()
    acme = {"Authorization": f"Bearer {security.issue_token('u1', tenant='acme')}"}
    sem_org = {"Authorization": f"Bearer {security.issue_token('u1')}"}
    negado = client.get("/privada", headers=acme)
    assert negado.status_code == 402 and negado.json()["error"]["code"] == "ERRO_PLAN_MODULE"
    assert client.get("/privada", headers=sem_org).status_code == 200  # sem organização: o serviço decide
    assert client.get("/aberta").status_code == 200  # rota pública não tem organização de quem chama

    b, seen, replies = _connected_bus(), [], []

    async def handler(data):
        seen.append(security.current().sub)
        return data

    async def subscribe(subject, queue, cb):
        b._rpc_callback = cb

    async def respond(raw):
        replies.append(envelope.ResponseEnvelope.model_validate_json(raw))

    b._nc = SimpleNamespace(subscribe=subscribe)

    async def run():
        await b.subscribe("events.faturas.trigger", handler, Entrada)
        recusada = _FakeMsg(b'{"valor": 1}', {nats_bus.PRINCIPAL_HEADER: ACME.model_dump_json()})
        await b._js.callback(recusada)
        tarefa = _FakeMsg(b'{"valor": 1}', {nats_bus.PRINCIPAL_HEADER: security.system("svc-faturas", "acme").model_dump_json()})
        await b._js.callback(tarefa)
        await b.respond("rpc.faturas.total", handler, Entrada)
        pedido = SimpleNamespace(data=b'{"valor": 1}', headers={nats_bus.PRINCIPAL_HEADER: ACME.model_dump_json()}, respond=respond)
        await b._rpc_callback(pedido)
        return recusada, tarefa

    recusada, tarefa = asyncio.run(run())
    assert (recusada.termed, recusada.acked, tarefa.acked) == (True, False, True)  # recusada sem reentrega
    assert seen == ["system:svc-faturas"]  # a tarefa da plataforma passa
    assert (replies[0].ok, replies[0].error.code, replies[0].error.status) == (False, "ERRO_PLAN_MODULE", 402)


def test_modulo_de_outro_servico_ligado_ou_nao(plano):
    plano.modules = [_modulo("crm", enabled=False, title="CRM"), _modulo("estoque")]
    assert _como(ACME, lambda: plans.enabled("crm")) is False
    assert _como(ACME, lambda: plans.enabled("estoque")) is True
    assert _como(ACME, lambda: plans.enabled("desconhecido")) is True  # o svc-plans não conhece: não bloqueia
    with pytest.raises(ValueError, match="sem svc-"):
        _como(ACME, lambda: plans.enabled("svc-crm"))


def test_limite_total_confere_quanto_existe_e_o_default_vale_sem_plano(plano):
    plano.limits = [_estado("faturas.enderecos", 3)]
    _como(ACME, lambda: plans.check("enderecos", used=2))  # 2 + 1 = 3: cabe
    message = _limite(lambda: _como(ACME, lambda: plans.check("enderecos", used=3)))
    assert message == "Limite do plano Pro atingido: Endereços de webhook, até 3 endereços. Veja em Plano."
    _limite(lambda: _como(ACME, lambda: plans.check("enderecos", used=1, adding=3)))
    plano.limits, plano.plan = [], None  # o svc-plans ainda não conhece o limite: vale o default declarado (20)
    plans.clear()
    _como(ACME, lambda: plans.check("enderecos", used=19))
    assert "da organização atingido" in _limite(lambda: _como(ACME, lambda: plans.check("enderecos", used=20)))


def test_limite_mensal_para_quem_ja_chegou_e_vale_por_nome_completo(plano):
    plano.limits = [_estado("faturas.custo", 10, used=9.99, monthly=True, description="Gasto", unit="", currency="USD"),
                    _estado("ai.tokens", 1000, used=1000, monthly=True, description="Tokens de IA no mês", unit="tokens")]
    _como(ACME, lambda: plans.check("custo"))
    assert "Tokens de IA no mês, até 1.000 tokens" in _limite(lambda: _como(ACME, lambda: plans.check("ai.tokens")))
    _como(ACME, lambda: plans.check("ai.desconhecido"))  # limite que ninguém declarou: sem limite
    assert plano.requests == [(LIMITS_SUBJECT, "acme")]  # uma consulta: o resto veio da resolução guardada (60 s)
    _como(BETA, lambda: plans.check("custo"))
    assert plano.requests[-1] == (LIMITS_SUBJECT, "beta")  # cada organização tem a sua
    with pytest.raises(ValueError, match="mensal"):
        _como(ACME, lambda: plans.check("custo", used=1))
    with pytest.raises(ValueError, match="total"):
        _como(ACME, lambda: plans.check("enderecos"))
    with pytest.raises(ValueError, match="não declarado"):
        _como(ACME, lambda: plans.check("outro", used=1))
    with pytest.raises(ServiceError) as sem_org:
        asyncio.run(plans.check("custo"))
    assert sem_org.value.code == "ERRO_TENANT_REQUIRED"


def test_consumo_e_total_vao_ao_svc_plans_na_organizacao_de_quem_age(plano):
    plano.published.clear()
    _como(ACME, lambda: plans.use("custo", 0.25, key="EVENTS-7-custo"))
    _como(ACME, lambda: plans.use("custo", 0))  # nada a somar
    _como(ACME, lambda: plans.count("enderecos", 4))
    (s1, usage, id1, who1), (s2, count, id2, _) = plano.published
    assert (s1, usage.name, usage.amount, id1, who1.tenant) == (USAGE_SUBJECT, "faturas.custo", 0.25, "usage-svc-faturas-EVENTS-7-custo", "acme")
    assert usage.month == time.strftime("%Y-%m", time.gmtime())
    assert (s2, count.name, count.total, id2) == (COUNT_SUBJECT, "faturas.enderecos", 4, None)
    for call, erro in (
        (lambda: plans.use("enderecos", 1), "mensal"),
        (lambda: plans.count("custo", 1), "total"),
        (lambda: plans.use("custo", -1), "negativo"),
        (lambda: plans.use("custo", 1, key="tem espaço"), "key"),
        (lambda: plans.use("outro", 1), "não declarado"),
    ):
        with pytest.raises(ValueError, match=erro):
            _como(ACME, call)


def test_svc_plans_fora_do_ar_usa_a_ultima_resposta_ou_nenhum_limite(plano):
    plano.limits = [_estado("faturas.enderecos", 1)]
    _limite(lambda: _como(ACME, lambda: plans.check("enderecos", used=1)))
    plans._cache = {tenant: (0.0, resolved) for tenant, (_, resolved) in plans._cache.items()}  # os 60 s passaram
    plano.fail = nats_bus.nats.errors.NoRespondersError()
    _limite(lambda: _como(ACME, lambda: plans.check("enderecos", used=1)))  # vale a última resposta
    plano.fail = TimeoutError()
    _como(BETA, lambda: plans.check("enderecos", used=50))  # nunca respondeu para a Beta: sem limite
    plano.fail = ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização.", 403)
    plans.clear()
    with pytest.raises(ServiceError) as negado:  # erro de quem pergunta não é queda do serviço
        _como(ACME, lambda: plans.check("enderecos", used=0))
    assert negado.value.status == 403


def test_trocar_de_plano_so_como_tarefa_da_plataforma(plano):
    _como(ACME, lambda: plans.check("enderecos", used=0))  # resolução guardada para a Acme
    with pytest.raises(PermissionError):
        _como(ACME, lambda: plans.assign("pro"))
    assigned = _como(security.system("svc-pagamentos", "acme"), lambda: plans.assign("pro"))
    assert (assigned.tenant, assigned.plan, plano.requests[-1]) == ("acme", "pro", (ASSIGN_SUBJECT, "acme"))
    avulso = _como(security.system("svc-pagamentos", "acme"), lambda: plans.assign("pro", modules={"juridico": True}))
    assert avulso.modules == {"juridico": True}  # módulo comprado à parte, além do plano
    _como(ACME, lambda: plans.check("enderecos", used=0))
    assert [s for s, _ in plano.requests].count(LIMITS_SUBJECT) == 2  # trocar esquece a resolução guardada


def test_planos_exigem_bus_conectado(monkeypatch):
    monkeypatch.setattr(nats_bus.bus, "_service", None)
    with pytest.raises(RuntimeError, match="bus não conectado"):
        asyncio.run(plans_module.plans.declare(MODULO_FATURAS))


# ── Observabilidade: core/telemetry.py (README §5.18) ────────────────────────

import logging  # noqa: E402

from opentelemetry import trace as otel_trace  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from core import telemetry as telemetry_module  # noqa: E402
from core.telemetry import install_telemetry, telemetry  # noqa: E402

_EXPORTER = InMemorySpanExporter()


@pytest.fixture
def spans(auth_env):
    """Telemetria do processo ligada uma vez (como no boot) e os spans terminados guardados em memória."""
    if telemetry.service is None:
        telemetry.setup("svc-teste")
        otel_trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(_EXPORTER))
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


def _app_com_telemetria():
    app = FastAPI()
    envelope.install_envelope(app, service="svc-teste")
    security.install_security(app, service="svc-teste")
    install_telemetry(app, service="svc-teste")

    @app.get("/itens/{item_id}")
    async def item(item_id: str):
        logging.getLogger("svc-teste").info("lendo item", extra={"item": item_id, "password": "nunca"})
        return {"id": item_id}

    @app.get("/quebra")
    async def quebra():
        raise RuntimeError("segredo-interno")

    return TestClient(app, raise_server_exceptions=False)


def _linhas(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def test_log_em_json_com_trace_organizacao_e_pessoa_e_uma_linha_por_requisicao(spans, auth_env, monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    client = _app_com_telemetria()
    token = security.issue_token("ana", tenant="acme")
    r = client.get("/itens/i-42", headers=_bearer(token))
    client.get("/itens/i-1")  # sem token: 401 também tem a sua linha
    lendo, req, negado = [l for l in _linhas(capsys) if l["logger"].startswith("svc-teste")]
    assert (lendo["message"], lendo["item"], lendo["password"]) == ("lendo item", "i-42", "***")  # extra= mascarado
    assert (lendo["service"], lendo["tenant"], lendo["user"]) == ("svc-teste", "acme", "ana")
    assert lendo["trace_id"] == req["trace_id"] == r.headers["x-trace-id"]  # o mesmo id no log e na resposta
    assert (req["http_route"], req["http_status"], req["tenant"], req["user"]) == ("/itens/{item_id}", 200, "acme", "ana")
    assert (negado["http_status"], negado.get("user")) == (401, None) and negado["trace_id"] != req["trace_id"]
    server = [s for s in spans.get_finished_spans() if s.kind == otel_trace.SpanKind.SERVER]
    assert [s.name for s in server][:1] == ["GET /itens/{item_id}"]  # o molde, nunca o id


def test_erro_500_informa_o_trace_id_e_o_log_traz_o_erro(spans, auth_env, monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    client = _app_com_telemetria()
    r = client.get("/quebra", headers=_bearer(security.issue_token("ana", tenant="acme")))
    trace_id = r.headers["x-trace-id"]
    assert r.status_code == 500 and trace_id in r.json()["error"]["message"] and "segredo" not in r.text
    erro = next(l for l in _linhas(capsys) if l["logger"] == "core.envelope")
    assert erro["trace_id"] == trace_id and erro["error"]["type"] == "RuntimeError"


def test_texto_legivel_no_desenvolvimento(spans):
    record = logging.LogRecord("svc-teste", logging.INFO, __file__, 1, "olá %s", ("mundo",), None)
    record.trace_id, record.tenant, record.user = "a" * 32, "acme", "ana"
    linha = telemetry_module._TextFormatter().format(record)
    assert linha.endswith("INFO    svc-teste: olá mundo  [trace=aaaaaaaa org=acme user=ana]")


def test_trace_atravessa_o_nats_do_publish_ao_handler(spans):
    b, vistos = _connected_bus(), []

    async def handler(data):
        vistos.append(otel_trace.get_current_span().get_span_context().trace_id)

    async def run():
        await b.subscribe("events.billing.trigger", handler, Entrada)
        with otel_trace.get_tracer("teste").start_as_current_span("requisição") as origem:
            await b.publish("events.billing.trigger", Entrada(valor=1))
        _, headers = b._js.published[-1]
        await b._js.callback(_FakeMsg(b'{"valor": 1}', headers))
        return origem.get_span_context().trace_id

    origem = asyncio.run(run())
    assert vistos == [origem]  # o handler roda no mesmo trace de quem publicou
    nomes = {s.name: s for s in spans.get_finished_spans()}
    assert nomes["process events.billing.trigger"].attributes["cv.outcome"] == "ok"
    assert nomes["process events.billing.trigger"].parent.span_id == nomes["publish events.billing.trigger"].context.span_id


def test_consulta_vira_span_sem_os_valores(spans):
    _with_db(lambda d: d.query("SELECT * FROM faturas WHERE tenant = $tenant AND cliente = $c", c="Padaria Aurora"))
    consultas = [s for s in spans.get_finished_spans() if s.name == "surrealdb SELECT"]
    assert consultas and consultas[-1].attributes["db.query.text"].startswith("SELECT * FROM faturas")
    assert "Padaria" not in str(dict(consultas[-1].attributes))  # valores vão em parâmetros e nunca no span


def test_saude_confere_o_que_o_processo_usa(spans, auth_env, monkeypatch):
    client = _app_com_telemetria()
    monkeypatch.setattr(nats_bus.bus, "_nc", SimpleNamespace(is_connected=True))
    monkeypatch.setattr(surreal.db, "_conn", _FakeSurreal(query=[True]))
    monkeypatch.setattr(_FakeSurreal, "query", lambda self, sql: asyncio.sleep(0), raising=False)
    ok = client.get("/health")  # sem token: aberta, como manda o core
    assert (ok.status_code, ok.json()["data"]) == (200, {"status": "ok", "checks": {"nats": "ok", "surrealdb": "ok"}})
    monkeypatch.setattr(nats_bus.bus, "_nc", None)
    caiu = client.get("/health")
    assert (caiu.status_code, caiu.json()["error"]["details"]) == (503, [{"loc": ["nats"], "msg": "fora do ar"}])


def test_metricas_do_servico_levam_o_prefixo(spans):
    contador = telemetry.counter("faturas_pagas", "Faturas pagas")
    assert contador.name == "cv.teste.faturas_pagas"



# ── Produção: credencial no NATS, payloads cifrados no Temporal e .env de produção (README §5.7 e §9) ──────

from temporalio.api.common.v1 import Payload  # noqa: E402

from core.temporal_runner import EncryptedPayloads, TemporalSettings  # noqa: E402


def test_producao_exige_credencial_no_nats_e_chave_no_temporal(monkeypatch):
    for name in ("ENVIRONMENT", "NATS_USER", "NATS_PASSWORD", "NATS_CREDS", "TEMPORAL_PAYLOAD_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError, match="NATS_USER/NATS_PASSWORD ou NATS_CREDS"):
        nats_bus.NatsSettings()
    with pytest.raises(ValidationError, match="TEMPORAL_PAYLOAD_KEY"):
        TemporalSettings()
    with pytest.raises(RuntimeError, match="configuração ausente ou insegura"):
        asyncio.run(nats_bus.Bus().connected("svc-teste").__aenter__())
    monkeypatch.setenv("NATS_USER", "services")
    monkeypatch.setenv("NATS_PASSWORD", "")  # vazio no compose = não definida: senha faltando
    with pytest.raises(ValidationError, match="andam juntos"):
        nats_bus.NatsSettings()
    monkeypatch.setenv("NATS_PASSWORD", "segredo")
    monkeypatch.setenv("TEMPORAL_PAYLOAD_KEY", security._b64e(b"k" * 32))
    assert nats_bus.NatsSettings().user == "services" and TemporalSettings().payload_key is not None
    monkeypatch.setenv("ENVIRONMENT", "development")  # local: sem senha e sem cifra, como antes
    for name in ("NATS_USER", "NATS_PASSWORD", "TEMPORAL_PAYLOAD_KEY"):
        monkeypatch.setenv(name, "")
    assert (nats_bus.NatsSettings().user, TemporalSettings().payload_key) == (None, None)


def test_payloads_do_temporal_saem_cifrados_e_presos_a_chave():
    codec = EncryptedPayloads(b"k" * 32)
    original = Payload(metadata={"encoding": b"json/plain"}, data=b'{"email": "ana@acme.com", "link": "/redefinir?codigo=x"}')
    (sealed,) = asyncio.run(codec.encode([original]))
    assert sealed.metadata["encoding"] == b"binary/encrypted" and b"ana@acme.com" not in sealed.data
    assert asyncio.run(codec.decode([sealed])) == [original]
    antigo = Payload(metadata={"encoding": b"json/plain"}, data=b"{}")  # gravado antes da chave: segue como veio
    assert asyncio.run(codec.decode([antigo])) == [antigo]
    with pytest.raises(ValueError, match="outra TEMPORAL_PAYLOAD_KEY"):
        asyncio.run(EncryptedPayloads(b"z" * 32).decode([sealed]))
    with pytest.raises(ValueError, match="32 bytes"):
        EncryptedPayloads(b"curta")


def test_keygen_de_producao(tmp_path, capsys):
    env = tmp_path / ".env"
    security._keygen(env, "app.exemplo.com")
    values = dict(line.split("=", 1) for line in env.read_text().splitlines() if line and not line.startswith("#"))
    assert values["ENVIRONMENT"] == "production" and values["AUTH_ISSUER"] == "https://app.exemplo.com"
    assert values["STORAGE_PUBLIC_URL"] == "https://files.app.exemplo.com" and values["SMTP_URL"] == ""
    assert values["STORAGE_CORS_ORIGINS"] == "https://app.exemplo.com"  # o navegador envia arquivo direto ao armazenamento
    assert len(security._b64d(values["TEMPORAL_PAYLOAD_KEY"])) == 32 and values["NATS_GATEWAY_PASSWORD"] != values["NATS_SERVICES_PASSWORD"]
    assert oct(env.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(SystemExit, match="já existe"):
        security._keygen(env, "app.exemplo.com")
    with pytest.raises(SystemExit, match="domínio inválido"):
        security._keygen(tmp_path / "outro.env", "nao é domínio")
    assert (values["MODULES"], values["COMPOSE_PROFILES"]) == ("", "modules")  # sem lista: todos os módulos


def test_keygen_de_instalacao_dedicada(tmp_path):
    env = tmp_path / ".env"
    security._keygen(env, "cliente.exemplo.com", "crm, vendas")
    values = dict(line.split("=", 1) for line in env.read_text().splitlines() if line and not line.startswith("#"))
    assert (values["MODULES"], values["COMPOSE_PROFILES"]) == ("crm,vendas", "crm,vendas")  # só os do cliente sobem
    with pytest.raises(SystemExit, match="módulo inválido"):
        security._keygen(tmp_path / "outro.env", "cliente.exemplo.com", "svc-crm")


# ── Recursos: core/resources.py (README §5.19) ───────────────────────────────

from datetime import date as _date  # noqa: E402

from pydantic import Field as _Field  # noqa: E402

from core import resources as resources_module  # noqa: E402
from core.resources import Email, Fields, Money, Resource, ResourceRef, Text, resources  # noqa: E402


class ClienteCampos(Fields):
    nome: str = _Field(..., min_length=2, max_length=120, title="Nome ou razão social")
    email: Email | None = None
    status: Literal["ativo", "inativo"] = "ativo"
    limite: Money = 0
    desde: _date | None = None
    obs: Text | None = None


CLIENTES = Resource(
    "svc-vendas", "clientes", ClienteCampos, "Clientes", search=("nome", "email"), sort=("nome", "limite"),
    filters=("status",), unique=("nome",), limit="clientes",
)
ANA_VENDAS = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))
CAIO_VENDAS = Principal(sub="caio", tenant="acme", roles=frozenset({"member"}))
BIA_VENDAS = Principal(sub="bia", tenant="beta", roles=frozenset({"owner"}))


@pytest.fixture
def vendas(monkeypatch):
    """Serviço svc-vendas com o cadastro de clientes no SurrealDB embutido e um svc-plans de mentira (limite 3)."""
    box = SimpleNamespace(live=[], counts=[], limit=3)

    async def live(topic, message, user=None):
        box.live.append((topic, message.id, message.action))

    async def publish(subject, message, msg_id=None):
        if subject == plans_module.COUNT_SUBJECT:
            box.counts.append((message.name, message.total))

    async def request(subject, message, response_model, timeout=5.0):
        state = LimitState(name="vendas.clientes", service="svc-vendas", description="Clientes cadastrados", default=None,
                           monthly=False, limit=box.limit, used=0)
        return PlanLimits(plan="pro", plan_name="Pro", month="2026-10", limits=[state])

    monkeypatch.setattr(nats_bus.bus, "live", live)
    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "request", request)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-vendas")
    monkeypatch.setattr(plans, "_module", None)
    monkeypatch.setattr(plans, "_declared", {})
    plans.clear()
    asyncio.run(plans.declare(Module("Vendas", "Clientes e propostas", limits=[Limit("clientes", "Clientes cadastrados")])))
    yield box
    plans.clear()


def _no_banco(cenario, items=(CLIENTES,)):
    async def run():
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        surreal.db._conn = conn
        async with surreal.db.connected(resources=items):
            return await cenario()

    return asyncio.run(run())


async def _como_async(who, call):
    with security.acting_as(who):
        return await call()


def test_recurso_deriva_tabela_modelos_e_a_descricao_da_tela():
    assert (CLIENTES.table, CLIENTES.live, CLIENTES.sort) == ("vendas_clientes", "vendas.clientes", ("nome", "limite", "created_at"))
    meta = CLIENTES.meta()
    assert [(f["name"], f["kind"], f["required"]) for f in meta["fields"]] == [
        ("nome", "text", True), ("email", "email", False), ("status", "select", False), ("limite", "money", False),
        ("desde", "date", False), ("obs", "textarea", False)]
    assert meta["fields"][0]["label"] == "Nome ou razão social"
    assert [c["key"] for c in meta["columns"]] == ["nome", "email", "status", "limite", "desde"]  # texto longo fica fora
    assert meta["filters"] == [{"name": "status", "label": "Status", "options": [
        {"value": "ativo", "label": "Ativo"}, {"value": "inativo", "label": "Inativo"}]}]
    assert meta["search"] == "nome ou razão social, email"
    assert CLIENTES.item.model_validate({"id": "vendas_clientes:⟨abc⟩", "nome": "Ana", "tenant": "acme"}).id == "abc"
    assert CLIENTES.update(id="abc", status="inativo").model_dump(exclude_unset=True) == {"id": "abc", "status": "inativo"}
    with pytest.raises(ValidationError):
        CLIENTES.update(id="abc", nome="A")  # as regras do campo valem também na edição
    with pytest.raises(ValidationError):
        ClienteCampos(nome="Ana", tenant="outra")  # campo não declarado
    with pytest.raises(ValidationError):
        CLIENTES.query(sort="email")  # só ordena pelo que declarou


def test_recurso_com_rotulos_de_escolha_com_acento():
    class Item(Fields):
        tipo: Literal["politica", "outro"] = _Field("outro", title="Tipo", json_schema_extra={"labels": {"politica": "Política"}})

    meta = Resource("svc-vendas", "itens", Item, "Itens", filters=("tipo",)).meta()
    assert meta["filters"][0]["options"] == [{"value": "politica", "label": "Política"}, {"value": "outro", "label": "Outro"}]


def test_recurso_com_declaracao_errada_nao_nasce():
    class Ruim(Fields):
        nome: str
        created_at: str | None = None

    class Livre(BaseModel):
        nome: str

    for call, erro in (
        (lambda: Resource("vendas", "clientes", ClienteCampos, "Clientes"), "SERVICE"),
        (lambda: Resource("svc-vendas", "Clientes", ClienteCampos, "Clientes"), "kebab-case"),
        (lambda: Resource("svc-vendas", "clientes", Livre, "Clientes"), "Fields"),
        (lambda: Resource("svc-vendas", "clientes", Ruim, "Clientes"), "do banco"),
        (lambda: Resource("svc-vendas", "clientes", ClienteCampos, "Clientes", search=("cpf",)), "não tem"),
        (lambda: Resource("svc-vendas", "clientes", ClienteCampos, "Clientes", filters=("nome",)), "Literal"),
        (lambda: Resource("svc-vendas", "clientes", ClienteCampos, "Clientes", unique=("email",)), "obrigatório"),
    ):
        with pytest.raises((ValueError, TypeError), match=erro):
            call()


def test_crud_na_organizacao_de_quem_age_com_limite_e_aviso_ao_vivo(vendas):
    async def cenario():
        criar = lambda who, **campos: _como_async(who, lambda: resources.create(CLIENTES, ClienteCampos(**campos)))  # noqa: E731
        padaria = await criar(ANA_VENDAS, nome="Padaria Aurora", email="Contato@Aurora.com", limite=500, desde=_date(2024, 5, 2))
        await criar(ANA_VENDAS, nome="Mercado Bom Preço", status="inativo")
        await criar(BIA_VENDAS, nome="Cliente da Beta")
        lista = await _como_async(ANA_VENDAS, lambda: resources.list(CLIENTES, CLIENTES.query(q="aurora")))
        inativos = await _como_async(ANA_VENDAS, lambda: resources.list(CLIENTES, CLIENTES.query(status="inativo", sort="nome")))
        mudou = await _como_async(ANA_VENDAS, lambda: resources.update(CLIENTES, CLIENTES.update(id=padaria.id, limite=900)))
        da_beta = await _como_async(BIA_VENDAS, lambda: resources.list(CLIENTES, CLIENTES.query()))
        erros = []
        for who, call in (
            (BIA_VENDAS, lambda: resources.get(CLIENTES, ResourceRef(id=padaria.id))),  # de outra organização: não existe
            (BIA_VENDAS, lambda: resources.update(CLIENTES, CLIENTES.update(id=padaria.id, nome="Invadido"))),
            (BIA_VENDAS, lambda: resources.remove(CLIENTES, ResourceRef(id=padaria.id))),
            (ANA_VENDAS, lambda: resources.create(CLIENTES, ClienteCampos(nome="Padaria Aurora"))),  # nome repetido
            (ANA_VENDAS, lambda: resources.create(CLIENTES, ClienteCampos(nome="Terceiro"))),
            (ANA_VENDAS, lambda: resources.create(CLIENTES, ClienteCampos(nome="Quarto"))),  # limite 3: o quarto para
        ):
            try:
                await _como_async(who, call)
            except ServiceError as exc:
                erros.append((exc.code, exc.status))
        removido = await _como_async(ANA_VENDAS, lambda: resources.remove(CLIENTES, ResourceRef(id=padaria.id)))
        sobra = await _como_async(ANA_VENDAS, lambda: resources.list(CLIENTES, CLIENTES.query(sort="nome")))
        return padaria, lista, inativos, mudou, da_beta, erros, removido, sobra

    padaria, lista, inativos, mudou, da_beta, erros, removido, sobra = _no_banco(cenario)
    assert (padaria.email, padaria.limite, padaria.desde, padaria.created_by) == ("contato@aurora.com", 500, _date(2024, 5, 2), "ana")
    assert ":" not in padaria.id and padaria.created_at is not None
    assert [c.nome for c in lista.items] == ["Padaria Aurora"]
    assert [c.nome for c in inativos.items] == ["Mercado Bom Preço"]
    assert (mudou.limite, mudou.nome, mudou.updated_by) == (900, "Padaria Aurora", "ana")  # só o que veio mudou
    assert [c.nome for c in da_beta.items] == ["Cliente da Beta"]
    assert erros == [
        ("ERRO_RECORD_NOT_FOUND", 404), ("ERRO_RECORD_NOT_FOUND", 404), ("ERRO_RECORD_NOT_FOUND", 404),
        ("ERRO_RECORD_DUPLICATE", 409), ("ERRO_PLAN_LIMIT", 402)]
    assert removido.id == padaria.id and [c.nome for c in sobra.items] == ["Mercado Bom Preço", "Terceiro"]
    assert vendas.counts[-1] == ("vendas.clientes", 2)  # a tela Plano mostra o total
    assert ("vendas.clientes", padaria.id, "updated") in vendas.live and ("vendas.clientes", padaria.id, "removed") in vendas.live


def test_escrita_so_com_o_papel_declarado(vendas):
    restrito = Resource("svc-vendas", "contratos", ClienteCampos, "Contratos", write=("owner", "admin"))

    async def cenario():
        dono = await _como_async(ANA_VENDAS, lambda: resources.create(restrito, ClienteCampos(nome="Contrato A")))
        with pytest.raises(ServiceError) as negado:
            await _como_async(CAIO_VENDAS, lambda: resources.create(restrito, ClienteCampos(nome="Contrato B")))
        visto = await _como_async(CAIO_VENDAS, lambda: resources.get(restrito, ResourceRef(id=dono.id)))  # ler, pode
        return negado.value, visto

    negado, visto = _no_banco(cenario, items=(restrito,))
    assert (negado.code, negado.status) == ("ERRO_VENDAS_FORBIDDEN", 403) and visto.nome == "Contrato A"


def test_rotas_do_recurso_pelo_http(vendas, auth_env):
    app = FastAPI()
    envelope.install_envelope(app, service="svc-vendas")
    security.install_security(app, service="svc-vendas")
    resources.mount(app, [CLIENTES])
    token = {"Authorization": f"Bearer {security.issue_token('ana', tenant='acme', roles=['owner'])}"}

    async def cenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc") as client:
            criado = await client.post("/clientes", json={"nome": "Padaria Aurora", "limite": 10}, headers=token)
            item_id = criado.json()["data"]["id"]
            lista = await client.get("/clientes", params={"q": "padaria", "sort": "-limite"}, headers=token)
            um = await client.get("/clientes/item", params={"id": item_id}, headers=token)
            mudou = await client.post("/clientes/update", json={"id": item_id, "status": "inativo"}, headers=token)
            invalido = await client.post("/clientes", json={"nome": "X", "tenant": "beta"}, headers=token)
            removido = await client.post("/clientes/remove", json={"id": item_id}, headers=token)
            sem_token = await client.get("/clientes")
            return criado, lista, um, mudou, invalido, removido, sem_token

    criado, lista, um, mudou, invalido, removido, sem_token = _no_banco(cenario)
    assert criado.status_code == 200 and criado.json()["data"]["status"] == "ativo"
    assert lista.json()["data"]["total"] == 1 and um.json()["data"]["nome"] == "Padaria Aurora"
    assert mudou.json()["data"]["status"] == "inativo"
    assert invalido.status_code == 422  # nome curto e campo tenant não declarado
    assert removido.json()["data"] == {"id": criado.json()["data"]["id"]}
    assert sem_token.status_code == 401


# ── Kit de testes de serviço: core/testing.py (README §5.5) ──────────────────

from core.testing import service_app  # noqa: E402

_KIT_MAIN = """
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import Field
from core.envelope import install_envelope
from core.nats_bus import bus
from core.plans import Module, plans
from core.resources import Fields, Resource, resources
from core.security import install_security
from core.surreal import db

class Nota(Fields):
    texto: str = Field(..., min_length=1)

NOTAS = Resource("svc-kit", "notas", Nota, "Notas", search=("texto",))
MODULE = Module("Kit", "Serviço de teste do kit", default=False)

async def on_evento(data: Nota) -> None:
    await resources.create(NOTAS, data)

@asynccontextmanager
async def lifespan(app):
    async with bus.connected("svc-kit"), db.connected(resources=[NOTAS]):
        await bus.subscribe("events.kit.trigger", on_evento, model=Nota)
        await plans.declare(MODULE)
        yield

app = FastAPI(lifespan=lifespan)
install_envelope(app, service="svc-kit")
install_security(app, service="svc-kit")
resources.mount(app, [NOTAS])
"""


def test_kit_sobe_o_main_do_servico_em_memoria(tmp_path, monkeypatch):
    (tmp_path / "kit_main.py").write_text(_KIT_MAIN)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("AUTH_ISSUER", "AUTH_AUDIENCE", "AUTH_PRIVATE_KEY", "AUTH_PUBLIC_KEY"):
        monkeypatch.delenv(name, raising=False)  # o kit põe as suas

    async def cenario(app):
        sem_plano = await app.user("ana", "acme", "owner").post("/notas", json={"texto": "oi"})  # svc-plans fora: liga
        app.respond(LIMITS_SUBJECT, lambda _: PlanLimits(plan="basico", plan_name="Básico", month="2026-10", limits=[], modules=[
            ModuleState(name="kit", service="svc-kit", title="Kit", description="Teste", category="Geral", core=False,
                        default=False, requires=[], enabled=security.current_tenant() == "acme")]))  # só a Acme tem
        plans.clear()
        fora = await app.user("bia", "beta", "owner").post("/notas", json={"texto": "oi"})
        from core.security import Principal as P
        await app.deliver("events.kit.trigger", app.main.Nota(texto="do evento"), who=P(sub="ana", tenant="acme"))
        lista = await app.user("ana", "acme").get("/notas")
        return sem_plano, fora, lista, list(app.published), list(app.live)

    sem_plano, fora, lista, published, live = service_app(cenario, main="kit_main")
    assert sem_plano.status_code == 200
    assert fora.status_code == 402 and fora.json()["error"]["code"] == "ERRO_PLAN_MODULE"  # o portão do core vale no kit
    assert lista.json()["data"]["total"] == 2  # a da rota e a do evento
    assert [s for s, _ in published] == ["events.plans.catalog"] and [t for t, _, _ in live] == ["kit.notas", "kit.notas"]
    assert plans._module is None  # nada vaza para o próximo teste


def test_kit_recusa_rota_do_manifesto_que_o_main_nao_tem(tmp_path):
    from core import testing as testing_module

    (tmp_path / "gateway" / "endpoints").mkdir(parents=True)
    (tmp_path / "gateway" / "schemas.py").write_text((Path(testing_module.__file__).parent.parent / "gateway" / "schemas.py").read_text())
    (tmp_path / "gateway" / "endpoints" / "kit.yaml").write_text(json.dumps({
        "service": "kit", "base_path": "/api/v1/kit", "resources": ["notas"],
        "endpoints": [{"path": "/abrir", "method": "POST", "auth": "client_jwt", "target_type": "http",
                       "target_url": "http://svc-kit:8000/abrir"}],
    }))
    app = FastAPI()
    resources.mount(app, [Resource("svc-kit", "notas", ClienteCampos, "Notas")])
    with pytest.raises(AssertionError, match="POST /abrir"):
        testing_module._routes_match_manifest(app, "svc-kit", root=tmp_path)

    @app.post("/abrir")
    async def abrir():
        return {}

    testing_module._routes_match_manifest(app, "svc-kit", root=tmp_path)  # com a rota, passa


# ── Processos: fluxo tipado → BPMN do Camunda 8, ações declaradas e motor (core/processes.py) ─

from xml.etree import ElementTree as _ET  # noqa: E402

from core import processes as processes_module  # noqa: E402
from core.processes import Action, Condition, Flow, Fluxo, Step, Trigger, feel, to_bpmn  # noqa: E402

_NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL", "zeebe": "http://camunda.org/schema/zeebe/1.0",
       "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI"}


def _fluxo_pagamento() -> Fluxo:
    return Fluxo(
        gatilho=Trigger(tipo="evento", evento="documento.recebido", descricao="Boleto chega"),
        parametros={"limite": 5000},
        passos=[
            Step(id="ler", tipo="agente", nome="Ler", objetivo='Extrair "valor"', saidas=["valor"], excecao=True),
            Step(id="precisa", tipo="decisao", nome="Precisa aprovar?"),
            Step(id="aprovar", tipo="tarefa", nome="Aprovar", responsavel="cliente", pergunta="Aprovar?", horas=24),
            Step(id="pagar", tipo="acao", nome="Pagar", acao="financeiro.agendar_pagamento"),
            Step(id="aguardar", tipo="espera", nome="Comprovante", espera="mensagem", mensagem="banco.pago", chave="pagar.id"),
            Step(id="fim", tipo="fim", nome="Pago"),
        ],
        ligacoes=[
            Flow(de="inicio", para="ler"), Flow(de="ler", para="precisa"),
            Flow(de="precisa", para="aprovar", condicao=Condition(campo="ler.valor", operador=">", valor="parametros.limite")),
            Flow(de="precisa", para="pagar"), Flow(de="aprovar", para="pagar"), Flow(de="pagar", para="aguardar"),
            Flow(de="aguardar", para="fim"),
        ],
    )


def _catalogo_pagamento() -> dict:
    from core.processes import CatalogAction

    entrada = {"properties": {"valor": {"type": "number"}, "vencimento": {"type": "string"}, "documento_id": {"type": "string"}}}
    return {"financeiro.agendar_pagamento": CatalogAction(
        name="financeiro.agendar_pagamento", service="svc-financeiro", title="Agendar", description="Agenda", risk="irreversivel",
        output_fields=["id", "data"], input_schema=entrada)}


def test_fluxo_vira_bpmn_do_camunda_com_extensoes_condicoes_e_desenho():
    fluxo = _fluxo_pagamento()
    fluxo.passos[4].horas = 48  # espera do comprovante com prazo: vira exceção do staff
    raiz = _ET.fromstring(to_bpmn(fluxo, process_id="p_acme_pagar", name="Pagar & conferir", actions=_catalogo_pagamento()))
    processo = raiz.find("bpmn:process", _NS)
    assert processo.get("id") == "p_acme_pagar" and processo.get("name") == "Pagar & conferir"
    ouvintes = {(o.get("eventType"), o.get("type")) for o in processo.find("bpmn:extensionElements", _NS).iter(f"{{{_NS['zeebe']}}}executionListener")}
    assert ouvintes == {("start", "processos.inicio")}  # o svc-processos fica sabendo de toda execução
    inicio = processo.find("bpmn:startEvent", _NS)
    assert inicio.get("id") == "inicio" and inicio.find("bpmn:messageEventDefinition", _NS) is None  # evento: o svc-processos inicia
    saidas = [(o.get("source"), o.get("target")) for o in inicio.findall(".//zeebe:output", _NS)]
    assert saidas == [("=5000", "parametros.limite")]  # o parâmetro vai com a versão
    tarefas = {t.get("id"): t for t in processo.findall("bpmn:serviceTask", _NS)}
    assert tarefas["pagar"].find(".//zeebe:taskDefinition", _NS).get("type") == "financeiro.agendar_pagamento"
    assert tarefas["ler"].find(".//zeebe:taskDefinition", _NS).get("type") == "agentes.executar"
    headers = {h.get("key"): h.get("value") for h in tarefas["ler"].findall(".//zeebe:header", _NS)}
    assert headers == {"passo": "ler", "objetivo": 'Extrair "valor"', "saidas": "valor", "excecao": "sim"}
    entradas = {i.get("target"): i.get("source") for i in tarefas["pagar"].findall(".//zeebe:input", _NS)}
    assert entradas == {"entrada.valor": "=ler.valor", "entrada.vencimento": "=gatilho.vencimento", "entrada.documento_id": "=gatilho.documento_id"}
    assert [(o.get("source"), o.get("target")) for o in tarefas["pagar"].findall(".//zeebe:output", _NS)] == [("=resultado", "pagar")]
    humanas = {t.get("id"): t for t in processo.findall("bpmn:userTask", _NS)}
    assert humanas["aprovar"].find(".//zeebe:assignmentDefinition", _NS).get("candidateGroups") == "cliente"
    assert humanas["aprovar"].find(".//zeebe:taskListener", _NS).get("type") == "processos.tarefa"
    assert humanas["ler__excecao"].find(".//zeebe:assignmentDefinition", _NS).get("candidateGroups") == "staff"
    assert "PT4H" in humanas["ler__excecao"].find(".//zeebe:taskSchedule", _NS).get("dueDate")  # handoff tem prazo
    assert humanas["aguardar__excecao"].get("name") == "Prazo: Comprovante"
    bordas = {b.get("id"): b for b in processo.findall("bpmn:boundaryEvent", _NS)}
    assert bordas["ler__erro"].get("attachedToRef") == "ler" and bordas["aguardar__prazo"].get("attachedToRef") == "aguardar"
    espera = processo.find("bpmn:receiveTask", _NS)
    assert espera.get("id") == "aguardar" and [(o.get("source"), o.get("target")) for o in espera.findall(".//zeebe:output", _NS)] == [("=mensagem", "aguardar")]
    assert processo.find("bpmn:endEvent", _NS).find(".//zeebe:executionListener", _NS).get("type") == "processos.fim"
    decisao = processo.find("bpmn:exclusiveGateway", _NS)
    assert decisao.get("default") == "f_precisa_pagar"
    caminhos = {f.get("id"): f for f in processo.findall("bpmn:sequenceFlow", _NS)}
    assert caminhos["f_precisa_aprovar"].find("bpmn:conditionExpression", _NS).text == "=ler.valor > parametros.limite"
    assert caminhos["f_ler__excecao_precisa"].get("targetRef") == "precisa"  # a exceção resolvida segue o fluxo
    mensagens = {m.get("name"): m for m in raiz.findall("bpmn:message", _NS)}
    assert mensagens["acme.banco.pago"].find(".//zeebe:subscription", _NS).get("correlationKey") == "=pagar.id"  # só da acme
    desenhados = {s.get("bpmnElement") for s in raiz.findall(".//bpmndi:BPMNShape", _NS)}
    assert {"inicio", "ler", "precisa", "aprovar", "pagar", "aguardar", "fim", "ler__excecao", "ler__erro", "aguardar__prazo"} <= desenhados
    assert len(raiz.findall(".//bpmndi:BPMNEdge", _NS)) == len(caminhos)
    with pytest.raises(ValueError):
        to_bpmn(fluxo, process_id="contas", name="x")  # sem a organização no id: mensagens e workers não saberiam de quem é


def test_condicao_vira_feel_com_valor_escapado():
    assert feel(Condition(campo="conferir.divergente", operador="verdadeiro")) == "=conferir.divergente = true"
    assert feel(Condition(campo="ler.fornecedor", operador="=", valor='Moinho "Sul"')) == '=ler.fornecedor = "Moinho \\"Sul\\""'
    assert feel(Condition(campo="ler.valor", operador=">=", valor=2000.5)) == "=ler.valor >= 2000.5"
    assert feel(Condition(campo="ler.valor", operador="<", valor="parametros.x or true")) == '=ler.valor < "parametros.x or true"'
    with pytest.raises(ValidationError):
        Condition(campo="ler.valor) or (true", operador="=", valor=1)
    with pytest.raises(ValidationError):
        Step(id="Passo-1", tipo="fim", nome="Fim")  # id vira id de elemento BPMN: só snake_case


class _Conferencia(BaseModel):
    divergente: bool


class _Documento(BaseModel):
    valor: float


def test_acoes_declaradas_vao_ao_catalogo_com_saida_e_exemplo(monkeypatch):
    publicados = []

    async def publish(subject, message, msg_id=None):
        publicados.append((subject, message, msg_id))

    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-financeiro")
    acao = Action("conferir_pedido", "Conferir com o pedido", "Compara o documento com o pedido", _Documento, _Conferencia,
                  risk="leitura", example=_Conferencia(divergente=False))
    asyncio.run(processes_module.processes.declare([acao]))
    subject, catalogo, msg_id = publicados[0]
    assert subject == "events.processos.catalogo" and msg_id.startswith("acoes-svc-financeiro-")
    item = catalogo.actions[0]
    assert (item.name, item.risk, item.output_fields, item.example) == (
        "financeiro.conferir_pedido", "leitura", ["divergente"], {"divergente": False})
    with pytest.raises(TypeError):
        Action("x", "X", "Ação x", _Documento, _Conferencia, risk="leitura", example=_Documento(valor=1))
    with pytest.raises(ValueError):
        Action("Pagar-Boleto", "X", "Ação x", _Documento, _Conferencia, risk="leitura", example=_Conferencia(divergente=True))


def test_implantar_no_camunda_devolve_a_versao_e_traduz_os_erros(monkeypatch):
    pedidos = []

    def motor(request):
        pedidos.append(request)
        if b"quebrado" in request.content:
            return httpx.Response(400, json={"title": "INVALID_ARGUMENT", "detail": "Element 'x' has no outgoing flow"})
        definicao = {"processDefinitionId": "p_acme_pagar", "processDefinitionKey": 2251799813685249, "processDefinitionVersion": 3}
        return httpx.Response(200, json={"deploymentKey": "1", "deployments": [{"processDefinition": definicao}]})

    async def cenario():
        motor_falso = processes_module.Camunda()
        motor_falso._client = httpx.AsyncClient(base_url="http://camunda:8080", transport=httpx.MockTransport(motor))
        ok = await motor_falso.deploy("<bpmn/>", "p_acme_pagar")
        with pytest.raises(ServiceError) as recusado:
            await motor_falso.deploy("<quebrado/>", "p_acme_pagar")
        await motor_falso.close()
        return ok, recusado.value

    ok, recusado = asyncio.run(cenario())
    assert (ok.key, ok.version) == ("2251799813685249", 3) and pedidos[0].url.path == "/v2/deployments"
    assert b'filename="p_acme_pagar.bpmn"' in pedidos[0].content
    assert (recusado.code, recusado.status) == ("ERRO_PROCESSOS_BPMN", 422) and "no outgoing flow" in recusado.message


def test_condicao_com_alternativas_vira_or_no_feel():
    condicao = Condition(campo="ler.valor", operador=">", valor="parametros.limite",
                         ou=[{"campo": "conferir.fornecedor_novo", "operador": "verdadeiro"}])
    assert feel(condicao) == "=(ler.valor > parametros.limite) or (conferir.fornecedor_novo = true)"


class _Pagamento(BaseModel):
    valor: float
    vencimento: str


class _Agendamento(BaseModel):
    pagamento_id: str


_AGENDAR = Action("agendar", "Agendar pagamento", "Agenda no banco", _Pagamento, _Agendamento, risk="irreversivel",
                  example=_Agendamento(pagamento_id="PG-1"))


class _Pacote:
    def __init__(self):
        self.recebidos = []

    async def agendar(self, data: _Pagamento) -> _Agendamento:
        self.recebidos.append(data)
        if data.valor > 1_000_000:
            raise ServiceError("ERRO_FINANCEIRO_LIMITE_BANCO", "Acima do limite do banco.", 409)
        if data.valor == 503:
            raise ServiceError("ERRO_INTEGRACOES_FORA", "Banco fora do ar.", 503)
        return _Agendamento(pagamento_id=f"PG-{int(data.valor)}")


def _job_bruto(**extra):
    bruto = {"jobKey": 77, "type": "financeiro.agendar", "processDefinitionId": "p_acme_contas", "processDefinitionVersion": 2,
             "processInstanceKey": 501, "elementId": "agendar", "elementInstanceKey": 502, "customHeaders": {"passo": "agendar"},
             "variables": {"entrada": {"valor": 1250.0, "vencimento": "2026-10-15"}}, "retries": 3, "kind": "BPMN_ELEMENT"}
    return {**bruto, **extra}


def test_job_do_motor_roda_a_acao_como_a_organizacao_do_processo(monkeypatch):
    from core.processes import Handoff, Job, processes as procs
    from core.security import current

    async def ligado(nome):
        return True

    monkeypatch.setattr(processes_module.plans, "enabled", ligado)
    pacote = _Pacote()
    handler = procs._action_handler("financeiro", _AGENDAR, pacote)
    quem = []

    async def espia(job):
        quem.append((current().sub, current().tenant))
        raise Handoff("Documento ilegível")

    async def cenario():
        ok = await procs.run_job("svc-financeiro", handler, Job.from_engine(_job_bruto()))
        faltando = await procs.run_job("svc-financeiro", handler, Job.from_engine(_job_bruto(variables={"entrada": {"valor": None}})))
        negocio = await procs.run_job("svc-financeiro", handler, Job.from_engine(_job_bruto(variables={"entrada": {"valor": 2e6, "vencimento": "x"}})))
        fora = await procs.run_job("svc-financeiro", handler, Job.from_engine(_job_bruto(variables={"entrada": {"valor": 503, "vencimento": "x"}})))
        handoff = await procs.run_job("svc-financeiro", espia, Job.from_engine(_job_bruto()))
        return ok, faltando, negocio, fora, handoff

    ok, faltando, negocio, fora, handoff = asyncio.run(cenario())
    assert (ok.status, ok.variables) == ("concluido", {"resultado": {"pagamento_id": "PG-1250"}})
    assert faltando.status == "handoff" and "valor" in faltando.message and "vencimento" in faltando.message
    assert (negocio.status, negocio.message) == ("handoff", "Acima do limite do banco.")  # erro de negócio não se tenta de novo
    assert (fora.status, fora.retries) == ("falhou", 2)  # infraestrutura: o motor tenta de novo
    assert (handoff.status, handoff.message) == ("handoff", "Documento ilegível")
    assert quem == [("system:svc-financeiro", "acme")]  # a organização vem do id do processo no motor
    with pytest.raises(ValueError):
        Job.from_engine(_job_bruto(processDefinitionId="processo_de_outro"))

    class _Errado:
        async def agendar(self, data: _Pagamento) -> _Pagamento:
            return data

    with pytest.raises(RuntimeError, match="agendar"):
        procs._action_handler("financeiro", _AGENDAR, _Errado())  # retorno fora da saída declarada: não sobe


def test_worker_pega_jobs_e_devolve_cada_resultado_ao_motor(monkeypatch):
    from core.processes import Handoff, processes as procs

    chamadas, publicados = [], []
    fila = [[_job_bruto()], [_job_bruto(jobKey=78, customHeaders={"excecao": "sim"}, variables={"entrada": {}})],
            [_job_bruto(jobKey=79, variables={"entrada": {}})]]

    devolvidos = {}

    def motor(request):
        corpo = json.loads(request.content) if request.content else {}
        chamadas.append((request.url.path, corpo))
        if request.url.path == "/v2/jobs/activation":
            return httpx.Response(200, json={"jobs": fila.pop(0) if fila else []})
        devolvidos[request.url.path] = datetime.now(UTC)
        return httpx.Response(204)

    async def publish(subject, message, msg_id=None):
        publicados.append((subject, message))

    async def ligado(nome):
        return nome == "financeiro"

    monkeypatch.setattr(processes_module.plans, "enabled", ligado)
    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-financeiro")
    monkeypatch.setattr(processes_module.camunda, "_client",
                        httpx.AsyncClient(base_url="http://camunda:8080", transport=httpx.MockTransport(motor)))

    async def cenario():
        async with procs.worker("svc-financeiro", [_AGENDAR], _Pacote()):
            for _ in range(200):
                if sum(1 for path, _ in chamadas if path != "/v2/jobs/activation") >= 3:
                    break
                await asyncio.sleep(0.01)

    asyncio.run(cenario())
    respostas = {path: corpo for path, corpo in chamadas if path != "/v2/jobs/activation"}
    assert respostas["/v2/jobs/77/completion"] == {"variables": {"resultado": {"pagamento_id": "PG-1250"}}}
    assert respostas["/v2/jobs/78/error"]["errorCode"] == "handoff"  # com caminho de exceção: tarefa do staff
    assert respostas["/v2/jobs/79/failure"]["retries"] == 0  # sem caminho de exceção: incidente
    ativacao = next(corpo for path, corpo in chamadas if path == "/v2/jobs/activation")
    assert ativacao["type"] == "financeiro.agendar" and ativacao["worker"] == "svc-financeiro"
    assert sorted(m.status for _, m in publicados) == ["concluido", "handoff", "incidente"]
    assert all(subject == "events.processos.passo" and m.instancia == "501" and m.processo == "contas" for subject, m in publicados)
    # A hora do passo é a de quando o worker terminou, antes de devolver o job: o motor segue (e o fim chega ao
    # svc-processos) logo depois da devolução, e a linha do tempo fica na ordem certa.
    concluido = next(m for _, m in publicados if m.status == "concluido")
    assert concluido.em <= devolvidos["/v2/jobs/77/completion"]
    assert Handoff("x").motivo == "x"


def test_motor_inicia_entrega_mensagem_e_conclui_tarefa(monkeypatch):
    def motor(request):
        if request.url.path == "/v2/process-instances":
            return httpx.Response(200, json={"processInstanceKey": 9, "processDefinitionVersion": 4})
        if request.url.path == "/v2/user-tasks/5/completion":
            return httpx.Response(409, json={"title": "INVALID_STATE"})
        if request.url.path == "/v2/messages/publication":
            assert json.loads(request.content)["name"] == "acme.banco.pago"
            return httpx.Response(200, json={"messageKey": "1"})
        return httpx.Response(500)

    async def cenario():
        motor_falso = processes_module.Camunda()
        motor_falso._client = httpx.AsyncClient(base_url="http://camunda:8080", transport=httpx.MockTransport(motor))
        iniciada = await motor_falso.start("p_acme_contas", {"gatilho": {"documento_id": "d1"}})
        await motor_falso.message("acme.banco.pago", "PG-1", {"mensagem": {"valor": 10}})
        with pytest.raises(ServiceError) as fechada:
            await motor_falso.complete_task("5", {"aprovar": {"aprovado": True}})
        with pytest.raises(ServiceError) as caiu:
            await motor_falso.complete_job("6", {})
        await motor_falso.close()
        return iniciada, fechada.value, caiu.value

    iniciada, fechada, caiu = asyncio.run(cenario())
    assert (iniciada.instance, iniciada.version) == ("9", 4)
    assert (fechada.code, fechada.status) == ("ERRO_PROCESSOS_TAREFA_FECHADA", 409)
    assert (caiu.code, caiu.status) == ("ERRO_PROCESSOS_MOTOR", 503)
    assert processes_module.process_id("acme", "contas") == "p_acme_contas"
    assert processes_module.parse_process_id("p_acme_contas") == ("acme", "contas")
    with pytest.raises(ValueError):
        processes_module.process_id("acme", "contas_a_pagar")  # o _ separa organização e processo


def test_conflito_de_escrita_entre_transacoes_e_repetido_pelo_core():
    """Achado do N4: duas aberturas simultâneas do desenho → "Transaction write conflict ... can be retried" (500)."""

    class _Conexao:
        def __init__(self, falhas):
            self.falhas, self.chamadas = falhas, 0

        async def query_raw(self, sql, params):
            self.chamadas += 1
            if self.chamadas <= self.falhas:
                raise RuntimeError("There was a problem with the key-value store: Transaction conflict: Transaction write "
                                   "conflict. This transaction can be retried")
            return {"result": [{"status": "OK", "result": [{"ok": True}]}]}

    async def cenario(falhas):
        d = surreal.Database()
        d._conn = _Conexao(falhas)
        with security.acting_as(ACME):
            try:
                return await d.query("SELECT * FROM notas WHERE tenant = $tenant"), d._conn.chamadas
            except RuntimeError:
                return "falhou", d._conn.chamadas

    assert asyncio.run(cenario(2)) == ([{"ok": True}], 3)  # repetiu e passou
    assert asyncio.run(cenario(9)) == ("falhou", 4)  # desiste depois de 3 repetições


# ── N7: modelos dos pacotes, paralelo, gatilho por outro processo e eventos de pacote ──

def test_modelo_do_pacote_vai_ao_catalogo_e_acao_nao_declarada_impede_o_boot(monkeypatch):
    from core.processes import ProcessModel

    publicados = []

    async def publish(subject, message, msg_id=None):
        publicados.append((subject, message, msg_id))

    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-financeiro")
    fluxo = Fluxo(gatilho=Trigger(tipo="processo", processo="proposta-comercial", resultado="aceita", descricao="Proposta aceita"),
                  passos=[Step(id="agendar", tipo="acao", nome="Agendar", acao="financeiro.agendar"),
                          Step(id="avisar", tipo="acao", nome="Avisar", acao="vendas.avisar"),  # de outro pacote: não dá para conferir aqui
                          Step(id="fim", tipo="fim", nome="Fim")],
                  ligacoes=[Flow(de="inicio", para="agendar"), Flow(de="agendar", para="avisar"), Flow(de="avisar", para="fim")])
    asyncio.run(processes_module.processes.declare([_AGENDAR], [ProcessModel("faturamento-cobranca", fluxo)]))
    subject, catalogo, _ = publicados[0]
    assert subject == "events.processos.catalogo" and [a.name for a in catalogo.actions] == ["financeiro.agendar"]
    assert [(m.id, m.service) for m in catalogo.models] == [("faturamento-cobranca", "svc-financeiro")]
    assert catalogo.models[0].fluxo.gatilho.resultado == "aceita"
    errado = fluxo.model_copy(deep=True)
    errado.passos[0].acao = "financeiro.agendr"  # erro de digitação na ação do próprio pacote: não sobe
    with pytest.raises(ValueError, match="financeiro.agendr"):
        asyncio.run(processes_module.processes.declare([_AGENDAR], [ProcessModel("faturamento-cobranca", errado)]))
    with pytest.raises(ValueError, match="modelo repetido"):
        asyncio.run(processes_module.processes.declare([_AGENDAR], [ProcessModel("x-y", fluxo), ProcessModel("x-y", fluxo)]))
    with pytest.raises(ValueError):
        ProcessModel("Contas a pagar", fluxo)  # o id é o do modelo na biblioteca


def test_paralelo_vira_parallel_gateway_e_a_entrada_vem_do_parametro():
    from core.processes import CatalogAction

    fluxo = Fluxo(
        gatilho=Trigger(tipo="processo", processo="proposta-comercial", resultado="aceita", descricao="Proposta aceita"),
        parametros={"prazo_pagamento": 15},
        passos=[Step(id="abrir", tipo="paralelo", nome="Ao mesmo tempo"),
                Step(id="faturar", tipo="acao", nome="Faturar", acao="financeiro.faturar"),
                Step(id="exame", tipo="tarefa", nome="Exame", responsavel="cliente"),
                Step(id="juntar", tipo="paralelo", nome="Tudo pronto"),
                Step(id="fim", tipo="fim", nome="Fim")],
        ligacoes=[Flow(de="inicio", para="abrir"), Flow(de="abrir", para="faturar"), Flow(de="abrir", para="exame"),
                  Flow(de="faturar", para="juntar"), Flow(de="exame", para="juntar"), Flow(de="juntar", para="fim")])
    entrada = {"properties": {"cliente": {"type": "string"}, "prazo_pagamento": {"type": "integer"}}}
    catalogo = {"financeiro.faturar": CatalogAction(name="financeiro.faturar", service="svc-financeiro", title="Faturar",
                                                    description="Fatura", risk="escrita", output_fields=["fatura_id"], input_schema=entrada)}
    raiz = _ET.fromstring(to_bpmn(fluxo, process_id="p_acme_fat", name="Faturar", actions=catalogo))
    processo = raiz.find("bpmn:process", _NS)
    paralelos = {g.get("id") for g in processo.findall("bpmn:parallelGateway", _NS)}
    assert paralelos == {"abrir", "juntar"} and not processo.findall("bpmn:exclusiveGateway", _NS)
    inicio = processo.find("bpmn:startEvent", _NS)
    assert inicio.get("name") == "Proposta aceita" and inicio.find("bpmn:timerEventDefinition", _NS) is None  # o svc-processos inicia
    faturar = next(t for t in processo.findall("bpmn:serviceTask", _NS) if t.get("id") == "faturar")
    entradas = {i.get("target"): i.get("source") for i in faturar.findall(".//zeebe:input", _NS)}
    assert entradas == {"entrada.cliente": "=gatilho.cliente", "entrada.prazo_pagamento": "=parametros.prazo_pagamento"}
    caminhos = {f.get("id") for f in processo.findall("bpmn:sequenceFlow", _NS)}
    assert {"f_abrir_faturar", "f_abrir_exame", "f_faturar_juntar", "f_exame_juntar", "f_juntar_fim"} <= caminhos
    assert all(f.find("bpmn:conditionExpression", _NS) is None for f in processo.findall("bpmn:sequenceFlow", _NS))
    desenhados = {s.get("bpmnElement"): s for s in raiz.findall(".//bpmndi:BPMNShape", _NS)}
    y = lambda no: float(desenhados[no].find("{http://www.omg.org/spec/DD/20100524/DC}Bounds").get("y"))  # noqa: E731
    assert y("faturar") != y("exame")  # os ramos ficam um embaixo do outro
    with pytest.raises(ValidationError):
        Trigger(tipo="processo", processo="proposta comercial")


def test_evento_de_pacote_sai_com_o_nome_do_pacote(monkeypatch):
    publicados = []

    async def publish(subject, message, msg_id=None):
        publicados.append((subject, message, msg_id))

    class _Pedido(BaseModel):
        proposta_id: str
        valor: float

    monkeypatch.setattr(nats_bus.bus, "publish", publish)
    monkeypatch.setattr(nats_bus.bus, "_service", "svc-vendas")
    asyncio.run(processes_module.processes.emit("pedido_proposta", _Pedido(proposta_id="p1", valor=10), key="p1"))
    asyncio.run(processes_module.processes.emit("proposta_respondida", {"aceita": True}, chave="p1"))
    (s1, e1, id1), (s2, e2, id2) = publicados
    assert s1 == s2 == "events.processos.evento"
    assert (e1.nome, e1.dados, e1.chave, id1) == ("vendas.pedido_proposta", {"proposta_id": "p1", "valor": 10.0}, None,
                                                   "evento-vendas-pedido_proposta-p1")
    assert (e2.nome, e2.chave, id2) == ("vendas.proposta_respondida", "p1", None)
    with pytest.raises(ValueError):
        asyncio.run(processes_module.processes.emit("Pedido Proposta", {}))


def test_agenda_vira_o_cron_de_seis_campos_do_motor():
    """Achado do N7: o Camunda 8 lê o cron do Spring (com segundos); com os 5 campos do fluxo, recusava o BPMN."""
    from core.processes import cron

    assert cron("0 11 * * 1-5") == "0 0 11 * * 1-5" and cron("0 0 11 * * *") == "0 0 11 * * *"
    fluxo = Fluxo(gatilho=Trigger(tipo="agenda", agenda="0 11 1 * *", descricao="Dia 1"),
                  passos=[Step(id="fim", tipo="fim", nome="Fim")], ligacoes=[Flow(de="inicio", para="fim")])
    raiz = _ET.fromstring(to_bpmn(fluxo, process_id="p_acme_fechar", name="Fechar"))
    ciclo = raiz.find("bpmn:process/bpmn:startEvent/bpmn:timerEventDefinition/bpmn:timeCycle", _NS)
    assert ciclo.text == "0 0 11 1 * *"
