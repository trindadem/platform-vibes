"""core/ · testes sem infraestrutura. Fonte da verdade: README §5.6, §5.7 e §5.9

Rodar (da raiz): uv run python -m pytest tests/core.py
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator
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


def test_http_client_nao_segue_redirects():
    with pytest.raises(TypeError, match="redirects"):
        asyncio.run(http.get("https://1.1.1.1", follow_redirects=True))


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
        self.data, self.headers, self.acked = data, headers, False
        self.metadata = SimpleNamespace(sequence=SimpleNamespace(stream=7), num_delivered=1)

    async def ack(self):
        self.acked = True


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
    assert sem_contexto is None


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

    sent, usage_events, resolutions = [], [], []
    state = {"handler": _fake_provider, "scope": "platform", "base_url": "http://provedor-interno:9000/v1", "auth": []}

    def transport(request):
        sent.append(json.loads(request.content or b"{}"))
        state["auth"].append(request.headers.get("authorization"))
        return state["handler"](request)

    async def request(subject, message, response_model, timeout=5.0):
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
    with security.acting_as(ACME):
        yield client, sent, usage_events, resolutions, state


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
