"""core/ · testes sem infraestrutura. Fonte da verdade: README §5.6 e §5.7

Rodar (da raiz): uv run python -m pytest tests/core.py
"""
import asyncio
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from surrealdb import RecordID
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from core import envelope, nats_bus, security, surreal, temporal_runner
from core.envelope import ServiceError
from core.http_client import http
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
    token = security.issue_token("u1", roles=["admin", "ops"], client_id="c9")
    assert security.verify_token(token) == Principal(sub="u1", roles=frozenset({"admin", "ops"}), client_id="c9")


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
