"""svc-identity · testes sem infraestrutura. Fonte da verdade: specs/identity.md §2 e §4

O SurrealDB roda embutido em memória (mem://, do próprio SDK): a SurrealQL do serviço é executada de verdade,
com os mesmos índices únicos do boot. O NATS vira uma lista em memória.

Rodar (da raiz): PYTHONPATH=services/svc-identity uv run python -m pytest tests/identity.py
"""
import asyncio

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from moto import mock_aws
from pydantic import ValidationError
from surrealdb import AsyncSurreal

from core import security
from core import storage as storage_module
from core.envelope import ServiceError
from core.security import acting_as
from core.notify import SEND_SUBJECT, ContactsRequest
from core.plans import COUNT_SUBJECT, LIMITS_SUBJECT, LimitState, PlanLimits
from core.webhooks import EMIT_SUBJECT
from core.storage import KeepRequest, UploadRequest

import service
from schemas import (
    MEMBER_JOINED_SUBJECT,
    MODULE,
    SHARED_TABLES,
    TENANT_CREATED_SUBJECT,
    UNIQUE,
    WEBHOOKS,
    ColorInput,
    Empty,
    ForgotInput,
    InviteCode,
    InviteInput,
    JoinRequest,
    LoginInput,
    MemberRef,
    RefreshInput,
    ResetInput,
    SignupInput,
    SwitchRequest,
    TenantRequest,
)

PASSWORD = "senha-forte-1"
PLANO = {"membros": None, "contagens": []}  # limite de pessoas do plano (None: sem limite) e totais informados


@pytest.fixture
def events(monkeypatch):
    """Chaves EdDSA de teste e NATS em memória: devolve (subject, mensagem, quem publicou)."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.cv.test")
    monkeypatch.setenv("AUTH_AUDIENCE", "cv-api")
    monkeypatch.setenv("AUTH_PRIVATE_KEY", security._b64e(key.private_bytes_raw()))
    monkeypatch.setenv("AUTH_PUBLIC_KEY", security._b64e(key.public_key().public_bytes_raw()))
    _clear()
    published = []

    async def publish(subject, message, msg_id=None):
        if subject == COUNT_SUBJECT:  # totais para a tela Plano (README §5.17): lista à parte
            PLANO["contagens"].append((message.name, message.total, security.current_tenant()))
        elif not subject.startswith("events.plans."):
            published.append((subject, message, security.current()))

    async def live(topic, message, user=None):
        published.append((f"live:{topic}" + (f":{user}" if user else ""), message, security.current()))

    async def request(subject, message, response_model, timeout=5.0):  # o svc-plans responde (rpc.plans.limits)
        assert subject == LIMITS_SUBJECT, subject
        state = LimitState(name="identity.membros", service="svc-identity", description="Pessoas na organização",
                           default=None, monthly=False, unit="pessoas", limit=PLANO["membros"], used=0)
        return PlanLimits(plan="teste", plan_name="Teste", month="2026-10", limits=[state])

    monkeypatch.setattr(service.bus, "publish", publish)
    monkeypatch.setattr(service.bus, "live", live)
    monkeypatch.setattr(service.bus, "_service", "svc-identity")  # core/notify diz quem pede
    monkeypatch.setattr(service.bus, "request", request)
    service.plans.clear()
    monkeypatch.setattr(service.plans, "_declared", {})
    PLANO.update(membros=None, contagens=[])
    asyncio.run(service.webhooks.declare(WEBHOOKS))  # como o boot: eventos no catálogo
    asyncio.run(service.plans.declare(MODULE))
    published.clear()
    yield published
    _clear()


def _clear():
    security._settings.cache_clear()
    security._own_keys.cache_clear()


def run(scenario):
    """Roda o cenário num SurrealDB novo em memória, com as tabelas e índices do boot do serviço."""

    async def go():
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        service.db._conn = conn
        async with service.db.connected(shared=SHARED_TABLES, unique=UNIQUE):
            return await scenario(service.IdentityService())

    return asyncio.run(go())


def as_user(session):
    """Age com o token de acesso emitido (como o core faz ao receber a requisição)."""
    return acting_as(security.verify_token(session.auth.access_token))


def signup(svc, email="ana@acme.com", organization="Acme", invite=None, name="Ana"):
    return svc.signup(SignupInput(name=name, email=email, password=PASSWORD, organization=organization, invite=invite))


async def _code(svc, owner, role="member"):
    with as_user(owner):
        return (await svc.create_invite(InviteInput(role=role))).code


def _error(exc_info, code, status):
    assert (exc_info.value.code, exc_info.value.status) == (code, status)


# ── Cadastro e login ────────────────────────────────────────────────────────

def test_cadastro_cria_conta_organizacao_dono_e_sessao(events):
    async def scenario(svc):
        session = await signup(svc, email="  Ana@ACME.com ")
        rows = await service.db.query_shared("SELECT email, password_hash FROM identity_users")
        sessions = await service.db.query_shared("SELECT token_hash FROM identity_sessions")
        return session, rows, sessions

    session, users, sessions = run(scenario)
    auth = session.auth
    assert auth.user.email == "ana@acme.com" and auth.tenant.name == "Acme" and auth.tenant.roles == ["owner"]
    claims = security.verify_token(auth.access_token)
    assert (claims.sub, claims.tenant, claims.roles) == (auth.user.id, auth.tenant.id, frozenset({"owner"}))
    assert users[0]["password_hash"].startswith("$argon2id$")  # senha nunca em claro
    assert sessions[0]["token_hash"] != session.refresh_token  # refresh guardado só como hash
    assert [(subject, who.tenant) for subject, _, who in events] == [
        (TENANT_CREATED_SUBJECT, auth.tenant.id),
        (MEMBER_JOINED_SUBJECT, auth.tenant.id),
        ("live:identity.membros", auth.tenant.id),  # a tela de membros da organização atualiza sozinha
    ]


def test_email_repetido_nao_cria_nada(events):
    async def scenario(svc):
        await signup(svc)
        with pytest.raises(ServiceError) as exc:
            await signup(svc, email="ANA@acme.com", organization="Outra")
        return exc, await service.db.query_shared("SELECT VALUE name FROM identity_tenants")

    exc, tenants = run(scenario)
    _error(exc, "ERRO_IDENTITY_EMAIL_TAKEN", 409)
    assert tenants == ["Acme"]  # bloco atômico: a organização "Outra" não ficou pela metade


def test_cadastro_exige_organizacao_ou_convite():
    for extra in ({}, {"organization": "Acme", "invite": "c" * 32}):
        with pytest.raises(ValidationError) as exc:
            SignupInput(name="Ana", email="a@x.com", password=PASSWORD, **extra)
        assert exc.value.errors()[0]["type"] == "one_way_in"
    with pytest.raises(ValidationError):
        SignupInput(name="Ana", email="a@x.com", password=PASSWORD, organization="Acme", roles=["owner"])


def test_login_tem_mensagem_unica_para_email_ou_senha_errados(events):
    async def scenario(svc):
        await signup(svc)
        ok = await svc.login(LoginInput(email="ANA@acme.com", password=PASSWORD))
        errors = []
        for email, password in (("ana@acme.com", "errada-123"), ("ninguem@acme.com", PASSWORD)):
            with pytest.raises(ServiceError) as exc:
                await svc.login(LoginInput(email=email, password=password))
            errors.append((exc.value.code, exc.value.message))
        return ok, errors

    ok, errors = run(scenario)
    assert ok.auth.tenant.name == "Acme"
    assert errors[0] == errors[1] == ("ERRO_IDENTITY_INVALID_CREDENTIALS", "E-mail ou senha inválidos.")


def test_cinco_erros_bloqueiam_o_login(events):
    async def scenario(svc):
        await signup(svc)
        for _ in range(5):
            with pytest.raises(ServiceError):
                await svc.login(LoginInput(email="ana@acme.com", password="errada-123"))
        with pytest.raises(ServiceError) as exc:
            await svc.login(LoginInput(email="ana@acme.com", password=PASSWORD))  # nem a senha certa entra
        return exc

    _error(run(scenario), "ERRO_IDENTITY_LOCKED", 429)


# ── Sessão: refresh girando e reuso ─────────────────────────────────────────

def test_refresh_gira_e_o_antigo_nao_vale_mais(events):
    async def scenario(svc):
        first = await signup(svc)
        second = await svc.refresh(RefreshInput(refresh_token=first.refresh_token))
        with pytest.raises(ServiceError) as reuse:  # dentro dos 30 s: corrida entre abas, não revoga nem desloga
            await svc.refresh(RefreshInput(refresh_token=first.refresh_token))
        third = await svc.refresh(RefreshInput(refresh_token=second.refresh_token))
        return first, second, third, reuse

    first, second, third, reuse = run(scenario)
    assert len({first.refresh_token, second.refresh_token, third.refresh_token}) == 3
    assert third.auth.tenant.id == first.auth.tenant.id
    _error(reuse, "ERRO_IDENTITY_SESSION_ROTATED", 401)


def test_refresh_antigo_reaparecendo_depois_revoga_a_sessao_inteira(events):
    async def scenario(svc):
        first = await signup(svc)
        second = await svc.refresh(RefreshInput(refresh_token=first.refresh_token))
        await service.db.query_shared("UPDATE identity_sessions SET rotated_at = time::now() - 1m WHERE rotated_at != NONE")
        with pytest.raises(ServiceError):
            await svc.refresh(RefreshInput(refresh_token=first.refresh_token))  # cópia roubada
        with pytest.raises(ServiceError) as exc:
            await svc.refresh(RefreshInput(refresh_token=second.refresh_token))  # o legítimo também cai
        return exc

    _error(run(scenario), "ERRO_IDENTITY_INVALID_SESSION", 401)


def test_logout_encerra_a_sessao(events):
    async def scenario(svc):
        session = await signup(svc)
        await svc.logout(RefreshInput(refresh_token=session.refresh_token))
        await svc.logout(RefreshInput(refresh_token=None))  # sem cookie: nada a fazer, sem erro
        with pytest.raises(ServiceError) as exc:
            await svc.refresh(RefreshInput(refresh_token=session.refresh_token))
        return exc

    _error(run(scenario), "ERRO_IDENTITY_INVALID_SESSION", 401)


# ── Convites, várias organizações e membros ─────────────────────────────────

def test_convite_leva_um_novo_usuario_para_a_organizacao(events):
    async def scenario(svc):
        owner = await signup(svc)
        code = await _code(svc, owner)
        info = await svc.invite_info(InviteCode(code=code))
        bia = await signup(svc, email="bia@x.com", organization=None, invite=code, name="Bia")
        with pytest.raises(ServiceError) as reuse:
            await signup(svc, email="caio@x.com", organization=None, invite=code, name="Caio")
        users = await service.db.query_shared("SELECT VALUE email FROM identity_users")
        return owner, info, bia, reuse, users

    owner, info, bia, reuse, users = run(scenario)
    assert (info.tenant_name, info.role) == ("Acme", "member")
    assert (bia.auth.tenant.id, bia.auth.tenant.roles) == (owner.auth.tenant.id, ["member"])
    _error(reuse, "ERRO_IDENTITY_INVITE_INVALID", 404)
    assert sorted(users) == ["ana@acme.com", "bia@x.com"]  # convite usado não cria o Caio


def test_membro_comum_nao_convida(events):
    async def scenario(svc):
        owner = await signup(svc)
        bia = await signup(svc, email="bia@x.com", organization=None, invite=await _code(svc, owner))
        with as_user(bia), pytest.raises(ServiceError) as exc:
            await svc.create_invite(InviteInput())
        return exc

    _error(run(scenario), "ERRO_IDENTITY_FORBIDDEN", 403)


def test_usuario_em_varias_organizacoes(events):
    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@beta.com", organization="Beta", name="Bia")
        code = await _code(svc, ana, role="admin")
        with as_user(bia):
            joined = await svc.join(JoinRequest(code=code, refresh_token=bia.refresh_token))
        with as_user(joined), pytest.raises(ServiceError) as again:
            await svc.join(JoinRequest(code=await _code(svc, ana)))
        with as_user(joined):
            back = await svc.switch_tenant(SwitchRequest(tenant=bia.auth.tenant.id, refresh_token=joined.refresh_token))
            with pytest.raises(ServiceError) as stranger:
                await svc.switch_tenant(SwitchRequest(tenant="naoexiste"))
            me = await svc.me(Empty())
        login = await svc.login(LoginInput(email="bia@beta.com", password=PASSWORD))
        return ana, bia, joined, again, back, stranger, me, login

    ana, bia, joined, again, back, stranger, me, login = run(scenario)
    assert (joined.auth.tenant.id, joined.auth.tenant.roles) == (ana.auth.tenant.id, ["admin"])
    assert [t.name for t in joined.auth.tenants] == ["Beta", "Acme"]
    _error(again, "ERRO_IDENTITY_ALREADY_MEMBER", 409)
    assert back.auth.tenant.name == "Beta" and security.verify_token(back.auth.access_token).tenant == bia.auth.tenant.id
    _error(stranger, "ERRO_IDENTITY_NOT_MEMBER", 403)
    assert me.tenant == ana.auth.tenant.id and len(me.tenants) == 2
    assert login.auth.tenant.name == "Beta"  # login volta para a última organização usada


def test_nova_organizacao_e_troca_de_sessao(events):
    async def scenario(svc):
        ana = await signup(svc)
        with as_user(ana):
            nova = await svc.create_tenant(TenantRequest(name="Nova", refresh_token=ana.refresh_token))
        renewed = await svc.refresh(RefreshInput(refresh_token=nova.refresh_token))
        with pytest.raises(ServiceError) as old:  # o refresh da organização anterior foi substituído
            await svc.refresh(RefreshInput(refresh_token=ana.refresh_token))
        return nova, renewed, old

    nova, renewed, old = run(scenario)
    assert (nova.auth.tenant.name, nova.auth.tenant.roles) == ("Nova", ["owner"])
    assert renewed.auth.tenant.name == "Nova"
    _error(old, "ERRO_IDENTITY_SESSION_ROTATED", 401)  # trocado há menos de 30 s: não vale, mas não derruba


def test_troca_de_organizacao_vence_o_refresh_que_chegou_atrasado(events):
    """Corrida no navegador: um refresh sai com o cookie antigo, gira antes da troca e a resposta dele chega depois.
    O cookie fica com a sessão girada por ele, mas a renovação seguinte já vem na organização escolhida."""
    async def scenario(svc):
        ana = await signup(svc)
        with as_user(ana):
            nova = await svc.create_tenant(TenantRequest(name="Nova", refresh_token=ana.refresh_token))
        with as_user(nova):
            atrasado = await svc.refresh(RefreshInput(refresh_token=nova.refresh_token))  # girou primeiro, ainda na Nova
            trocada = await svc.switch_tenant(SwitchRequest(tenant=ana.auth.tenant.id, refresh_token=nova.refresh_token))
        depois = await svc.refresh(RefreshInput(refresh_token=atrasado.refresh_token))  # o cookie que ficou no navegador
        return atrasado, trocada, depois

    atrasado, trocada, depois = run(scenario)
    assert (atrasado.auth.tenant.name, trocada.auth.tenant.name) == ("Nova", "Acme")
    assert depois.auth.tenant.name == "Acme"


def test_remocao_de_membros(events):
    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@x.com", organization=None, invite=await _code(svc, ana), name="Bia")
        with as_user(bia), pytest.raises(ServiceError) as forbidden:
            await svc.remove_member(MemberRef(user=ana.auth.user.id))
        with as_user(ana):
            before = await svc.list_members(Empty())
            after = await svc.remove_member(MemberRef(user=bia.auth.user.id))
            with pytest.raises(ServiceError) as last_owner:
                await svc.remove_member(MemberRef(user=ana.auth.user.id))
        with pytest.raises(ServiceError) as gone:  # a sessão da Bia nesta organização caiu na hora
            await svc.refresh(RefreshInput(refresh_token=bia.refresh_token))
        with as_user(bia), pytest.raises(ServiceError) as not_member:  # token ainda válido, mas o banco confere
            await svc.list_members(Empty())
        return before, after, forbidden, last_owner, gone, not_member

    before, after, forbidden, last_owner, gone, not_member = run(scenario)
    removed = [(s, m.model_dump(), who.tenant) for s, m, who in events if s.startswith("live:") and "removed" in str(m)]
    bia_id = next(m.id for m in before.items if m.name == "Bia")
    assert removed == [
        ("live:identity.membros", {"user": bia_id, "change": "removed"}, before_tenant := removed[0][2]),
        (f"live:identity.acesso:{bia_id}", {"tenant": before_tenant, "change": "removed"}, before_tenant),
    ]
    assert [(m.name, m.roles) for m in before.items] == [("Ana", ["owner"]), ("Bia", ["member"])]
    assert [m.name for m in after.items] == ["Ana"]
    _error(forbidden, "ERRO_IDENTITY_FORBIDDEN", 403)
    _error(last_owner, "ERRO_IDENTITY_LAST_OWNER", 409)
    _error(gone, "ERRO_IDENTITY_INVALID_SESSION", 401)
    _error(not_member, "ERRO_IDENTITY_NOT_MEMBER", 403)


def test_limpeza_apaga_sessoes_e_convites_vencidos(events):
    async def scenario(svc):
        ana = await signup(svc)
        await _code(svc, ana)
        await service.db.query_shared("UPDATE identity_sessions SET expires_at = time::now() - 1d")
        await service.db.query_shared("UPDATE identity_invites SET expires_at = time::now() - 1d")
        return await svc.cleanup(Empty())

    cleaned = run(scenario)
    assert (cleaned.sessions, cleaned.invites) == (1, 1)


# ── Logo da organização (arquivos, README §5.14) ────────────────────────────

@pytest.fixture
def bucket(monkeypatch):
    """Armazenamento S3 simulado no lugar do RustFS; devolve o client para simular o PUT do navegador."""
    for name, value in {"STORAGE_URL": "https://s3.us-east-1.amazonaws.com", "STORAGE_BUCKET": "cv-teste",
                        "STORAGE_ACCESS_KEY": "a", "STORAGE_SECRET_KEY": "b"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        s = storage_module.Storage()
        asyncio.run(s.connected("svc-identity"))
        monkeypatch.setattr(service, "storage", s)
        yield s._client


async def _send_logo(svc, client, filename="logo.png"):
    """O que a tela faz: pede o link, envia o arquivo (aqui, direto no S3 simulado) e confirma."""
    upload = await svc.logo_upload(UploadRequest(filename=filename, content_type="image/png", size=4))
    meta = {k.removeprefix("x-amz-meta-"): v for k, v in upload.headers.items() if k.startswith("x-amz-meta-")}
    client.put_object(Bucket="cv-teste", Key=upload.key, Body=b"\x89PNG", ContentType="image/png", Metadata=meta)
    return await svc.set_logo(KeepRequest(key=upload.key))


def _stored(client):
    return [o["Key"] for o in client.list_objects_v2(Bucket="cv-teste").get("Contents", [])]


def test_logo_enviado_trocado_e_removido_so_por_quem_gerencia(events, bucket):
    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@x.com", organization=None, invite=await _code(svc, ana))
        caio = await signup(svc, email="caio@x.com", organization="Beta", name="Caio")
        with as_user(ana):
            first = await _send_logo(svc, bucket)
            first_keys = _stored(bucket)
            second = await _send_logo(svc, bucket, filename="novo.png")
            second_keys = _stored(bucket)
            other = await svc.logo_upload(UploadRequest(filename="x.png", content_type="image/png", size=4))
        with as_user(bia):
            seen_by_member = await svc.organization(Empty())
            with pytest.raises(ServiceError) as member_upload:
                await svc.logo_upload(UploadRequest(filename="x.png", content_type="image/png", size=4))
        with as_user(caio), pytest.raises(ServiceError) as foreign_key:  # chave de outra organização
            await svc.set_logo(KeepRequest(key=other.key))
        with as_user(ana):
            with pytest.raises(ServiceError) as wrong_type:
                await svc.logo_upload(UploadRequest(filename="x.svg", content_type="image/svg+xml", size=4))
            removed = await svc.remove_logo(Empty())
        return first, first_keys, second, second_keys, seen_by_member, member_upload, foreign_key, wrong_type, removed

    first, first_keys, second, second_keys, seen_by_member, member_upload, foreign_key, wrong_type, removed = run(scenario)
    assert first.logo_url and "inline" in first.logo_url and "logo.png" in first.logo_url
    assert len(first_keys) == 1 and first_keys[0].startswith(f"t/{first.id}/svc-identity/logo/")
    assert "novo.png" in second.logo_url and len(second_keys) == 1 and second_keys != first_keys  # o antigo foi apagado
    assert seen_by_member.logo_url  # membro vê o logo, só não troca
    _error(member_upload, "ERRO_IDENTITY_FORBIDDEN", 403)
    _error(foreign_key, "ERRO_FILE_NOT_FOUND", 404)
    _error(wrong_type, "ERRO_FILE_TYPE", 422)
    assert removed.logo_url is None and not [k for k in _stored(bucket) if k.startswith("t/")]


def test_cor_da_marca_so_por_quem_gerencia(events):
    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@x.com", organization=None, invite=await _code(svc, ana))
        with as_user(ana):
            colorida = await svc.set_color(ColorInput(color="#1E40AF"))
        with as_user(bia):
            vista = await svc.organization(Empty())
            with pytest.raises(ServiceError) as membro:
                await svc.set_color(ColorInput(color="#000000"))
        with as_user(ana):
            padrao = await svc.set_color(ColorInput(color=None))
        return colorida, vista, membro, padrao

    colorida, vista, membro, padrao = run(scenario)
    assert colorida.color == "#1e40af" and vista.color == "#1e40af"  # minúsculas; membro vê a cor, só não troca
    _error(membro, "ERRO_IDENTITY_FORBIDDEN", 403)
    assert padrao.color is None  # volta à cor da plataforma
    for invalida in ("azul", "#12345", "#gggggg", "rgb(0,0,0)"):
        with pytest.raises(ValidationError):
            ColorInput(color=invalida)


# ── Avisos e e-mail (README §5.15) ──────────────────────────────────────────

def _notices(events):
    """Pedidos ao svc-notify publicados pelo core/notify (events.notify.send)."""
    return [m for subject, m, _ in events if subject == SEND_SUBJECT]


def _code_from(notice):
    return notice.link.partition("codigo=")[2]


def test_contatos_so_da_organizacao_de_quem_pergunta(events):
    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@x.com", organization=None, invite=await _code(svc, ana), name="Bia")
        caio = await signup(svc, email="caio@x.com", organization="Beta", name="Caio")
        with as_user(ana):
            by_id = await svc.contacts(ContactsRequest(users=[bia.auth.user.id, caio.auth.user.id]))
            owners = await svc.contacts(ContactsRequest(roles=["owner"]))
        return by_id, owners

    by_id, owners = run(scenario)
    assert by_id.tenant_name == "Acme"
    assert [(c.name, c.email) for c in by_id.items] == [("Bia", "bia@x.com")]  # Caio é de outra organização
    assert [c.email for c in owners.items] == ["ana@acme.com"]


def test_convite_por_email_e_aviso_para_quem_convidou(events):
    async def scenario(svc):
        ana = await signup(svc)
        with as_user(ana):
            invite = await svc.create_invite(InviteInput(role="admin", email="Bia@X.com"))
        sent = _notices(events)[-1]
        bia = await signup(svc, email="bia@x.com", organization=None, invite=_code_from(sent), name="Bia Souza")
        return ana, invite, sent, bia

    ana, invite, sent, bia = run(scenario)
    assert invite.email == "bia@x.com"
    assert (sent.email, sent.title, sent.action) == ("bia@x.com", "Convite para Acme", "Ver convite")
    assert "Ana convidou você para participar de Acme como administrador." in sent.body
    assert sent.link == f"/convite?codigo={invite.code}"
    joined = _notices(events)[-1]
    assert (joined.users, joined.title, joined.link) == ([ana.auth.user.id], "Bia Souza entrou na organização", "/membros")
    assert bia.auth.tenant.roles == ["admin"]


def test_esqueci_a_senha_nao_revela_quem_tem_conta_e_limita_pedidos(events):
    async def scenario(svc):
        await signup(svc)
        unknown = await svc.forgot_password(ForgotInput(email="ninguem@x.com"))
        for _ in range(5):
            await svc.forgot_password(ForgotInput(email="ANA@acme.com"))
        return unknown

    unknown = run(scenario)
    sent = _notices(events)
    assert unknown.model_dump() == {}  # mesma resposta para quem não tem conta
    assert len(sent) == 3  # MAX_RESETS_PER_HOUR: o resto é ignorado em silêncio
    assert {(n.email, n.title, n.action) for n in sent} == {("ana@acme.com", "Redefinir sua senha", "Redefinir senha")}
    assert all(n.link.startswith("/redefinir-senha?codigo=") for n in sent)


def test_redefinir_a_senha_derruba_as_sessoes_e_o_link_vale_uma_vez(events):
    async def scenario(svc):
        session = await signup(svc)
        await svc.forgot_password(ForgotInput(email="ana@acme.com"))
        code = _code_from(_notices(events)[-1])
        await svc.reset_password(ResetInput(code=code, password="nova-senha-forte"))
        with pytest.raises(ServiceError) as reused:
            await svc.reset_password(ResetInput(code=code, password="outra-senha-forte"))
        with pytest.raises(ServiceError) as old_session:
            await svc.refresh(RefreshInput(refresh_token=session.refresh_token))
        with pytest.raises(ServiceError) as old_password:
            await svc.login(LoginInput(email="ana@acme.com", password=PASSWORD))
        relogged = await svc.login(LoginInput(email="ana@acme.com", password="nova-senha-forte"))
        return reused, old_session, old_password, relogged

    reused, old_session, old_password, relogged = run(scenario)
    _error(reused, "ERRO_IDENTITY_RESET_INVALID", 404)
    _error(old_session, "ERRO_IDENTITY_INVALID_SESSION", 401)
    _error(old_password, "ERRO_IDENTITY_INVALID_CREDENTIALS", 401)
    assert relogged.auth.user.email == "ana@acme.com"
    changed = _notices(events)[-1]
    assert (changed.email, changed.title) == ("ana@acme.com", "Sua senha foi alterada")


def test_webhooks_de_entrada_e_saida_de_membros(events):
    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@x.com", organization=None, invite=await _code(svc, ana), name="Bia")
        with as_user(ana):
            await svc.remove_member(MemberRef(user=bia.auth.user.id))
        return ana, bia

    ana, bia = run(scenario)
    hooks = [(m.event, m.data, who.tenant) for subject, m, who in events if subject == EMIT_SUBJECT]
    tenant = ana.auth.tenant.id
    assert hooks == [  # a Ana criou a organização: não é "entrou" (ninguém teria endereço cadastrado ainda)
        ("identity.membro-entrou", {"id": bia.auth.user.id, "name": "Bia", "email": "bia@x.com", "role": "member"}, tenant),
        ("identity.membro-saiu", {"id": bia.auth.user.id, "name": "Bia", "email": "bia@x.com"}, tenant),
    ]


# ── Plano: pessoas por organização (README §5.17) ───────────────────────────

def test_limite_de_pessoas_do_plano_vale_ao_convidar_e_ao_aceitar(events):
    async def scenario(svc):
        ana = await signup(svc)
        PLANO["membros"] = 2  # o plano muda (o core guardaria 60 s; aqui nada foi conferido ainda)
        code = await _code(svc, ana)  # 1 de 2: convida
        code_2 = await _code(svc, ana)
        await signup(svc, email="bia@x.com", organization=None, invite=code, name="Bia")  # 2 de 2
        with as_user(ana), pytest.raises(ServiceError) as invite:
            await svc.create_invite(InviteInput())
        with pytest.raises(ServiceError) as accept:  # convite criado antes de lotar também para
            await signup(svc, email="caio@x.com", organization=None, invite=code_2, name="Caio")
        dani = await signup(svc, email="dani@x.com", organization="Outra", name="Dani")
        with as_user(dani), pytest.raises(ServiceError) as join:
            await svc.join(JoinRequest(code=code_2))
        users = await service.db.query_shared("SELECT VALUE email FROM identity_users")
        with as_user(ana):
            members = await svc.list_members(Empty())
            await svc.remove_member(MemberRef(user=next(m.id for m in members.items if m.name == "Bia")))
        return ana, invite, accept, join, users

    ana, invite, accept, join, users = run(scenario)
    for exc in (invite, accept, join):
        _error(exc, "ERRO_PLAN_LIMIT", 402)
    assert "Pessoas na organização, até 2 pessoas" in invite.value.message
    assert "caio@x.com" not in users  # nada foi criado
    acme = ana.auth.tenant.id
    assert [(nome, total) for nome, total, org in PLANO["contagens"] if org == acme] == [
        ("identity.membros", 1), ("identity.membros", 2), ("identity.membros", 1)]  # a tela Plano mostra "x de 2"



# ── Staff (svc-staff): a carteira dá e tira o papel operador; lista as organizações ──

def test_carteira_do_staff_da_e_tira_o_papel_operador_so_pelo_svc_staff(events):
    from core.security import Principal

    from schemas import OperadorAcesso

    async def scenario(svc):
        ana = await signup(svc)  # dona da Acme
        otto = await signup(svc, email="otto@cogniventure.com", organization="Cogniventure", name="Otto")
        acme, user = ana.auth.tenant.id, otto.auth.user.id
        staff = Principal(sub="system:svc-staff", tenant=otto.auth.tenant.id, roles=frozenset({"system"}))
        with acting_as(Principal(sub=ana.auth.user.id, tenant=acme, roles=frozenset({"owner"}))):
            with pytest.raises(ServiceError) as cliente:
                await svc.operador(OperadorAcesso(user=user, tenant=acme, ativo=True))  # só o svc-staff
        with acting_as(staff):
            with pytest.raises(ServiceError) as de_fora:
                await svc.operador(OperadorAcesso(user=ana.auth.user.id, tenant=otto.auth.tenant.id, ativo=True))
            entrou = await svc.operador(OperadorAcesso(user=user, tenant=acme, ativo=True))
            de_novo = await svc.operador(OperadorAcesso(user=user, tenant=acme, ativo=True))
            orgs = await svc.organizacoes(Empty())
        with as_user(ana):
            membros = await svc.list_members(Empty())
        with acting_as(staff):
            saiu = await svc.operador(OperadorAcesso(user=user, tenant=acme, ativo=False))
        with as_user(ana):
            depois = await svc.list_members(Empty())
        return cliente.value, de_fora.value, entrou, de_novo, orgs, membros, saiu, depois, user, acme

    cliente, de_fora, entrou, de_novo, orgs, membros, saiu, depois, user, acme = run(scenario)
    assert (cliente.code, cliente.status) == ("ERRO_IDENTITY_FORBIDDEN", 403)
    assert de_fora.status == 404  # quem não é da Cogniventure não vira operador
    assert entrou.roles == ["operador"] and de_novo.roles == ["operador"]  # entrar de novo não duplica
    assert {o.name for o in orgs.items} == {"Acme", "Cogniventure"}
    assert any(m.id == user and m.roles == ["operador"] for m in membros.items)
    assert saiu.roles == [] and not any(m.id == user for m in depois.items)  # sem outro papel, deixa a organização
    vivos = [(s, getattr(m, "change", None), w.tenant) for s, m, w in events if s.startswith("live:identity")]
    assert ("live:identity.membros", "joined", acme) in vivos and ("live:identity.membros", "removed", acme) in vivos
    assert ("live:identity.acesso:" + user, "removed", acme) in vivos  # a pessoa perde o acesso na hora


def test_cogniventure_abre_o_cliente_convida_o_dono_e_acompanha_o_acesso(events):
    from core.security import Principal

    from schemas import MEMBER_LEFT_SUBJECT, ClienteNovo, ConviteDono

    async def scenario(svc):
        gil = await signup(svc, email="gil@cogniventure.com", organization="Cogniventure", name="Gil")
        staff = Principal(sub="system:svc-staff", tenant=gil.auth.tenant.id, roles=frozenset({"system"}))
        with as_user(gil):
            with pytest.raises(ServiceError) as de_pessoa:
                await svc.cliente(ClienteNovo(empresa="Padaria", email="ana@padaria.com"))  # só o svc-staff
        with acting_as(staff):
            criado = await svc.cliente(ClienteNovo(empresa="Padaria Pão Quente", email="Ana@Padaria.com"))
            antes = {o.name: o for o in (await svc.organizacoes(Empty())).items}
            de_novo = await svc.convite_dono(ConviteDono(tenant=criado.tenant))
        convites = [m for s, m, _ in events if s == SEND_SUBJECT and getattr(m, "email", None) == "ana@padaria.com"]
        codigo = convites[-1].link.split("codigo=")[1]
        primeiro = convites[0].link.split("codigo=")[1]
        with pytest.raises(ServiceError) as vencido:
            await svc.invite_info(InviteCode(code=primeiro))  # o convite anterior deixou de valer
        info = await svc.invite_info(InviteCode(code=codigo))
        ana = await signup(svc, email="ana@padaria.com", organization=None, invite=codigo)
        with acting_as(staff):
            depois = {o.name: o for o in (await svc.organizacoes(Empty())).items}
            with pytest.raises(ServiceError) as ja_entrou:
                await svc.convite_dono(ConviteDono(tenant=criado.tenant))
        with as_user(ana):
            membros = await svc.list_members(Empty())
        return de_pessoa.value, criado, antes, de_novo, vencido.value, info, ana, depois, ja_entrou.value, membros, convites

    de_pessoa, criado, antes, de_novo, vencido, info, ana, depois, ja_entrou, membros, convites = run(scenario)
    assert (de_pessoa.code, de_pessoa.status) == ("ERRO_IDENTITY_FORBIDDEN", 403)
    padaria = antes["Padaria Pão Quente"]
    assert padaria.dono is None and padaria.convite.email == "ana@padaria.com" and padaria.ultimo_acesso is None
    assert de_novo.email == "ana@padaria.com" and len(convites) == 2 and "Aceitar o convite" == convites[0].action
    assert vencido.code == "ERRO_IDENTITY_INVITE_INVALID" and info.role == "owner" and info.tenant_name == "Padaria Pão Quente"
    assert ana.auth.tenant.id == criado.tenant and ana.auth.tenant.roles == ["owner"]
    assert [(m.email, m.roles) for m in membros.items] == [("ana@padaria.com", ["owner"])]  # ninguém da Cogniventure dentro
    agora = depois["Padaria Pão Quente"]
    assert agora.dono.email == "ana@padaria.com" and agora.convite is None and agora.ultimo_acesso is not None
    assert depois["Cogniventure"].ultimo_acesso is not None
    assert ja_entrou.code == "ERRO_IDENTITY_DONO_JA_ENTROU"


def test_remover_membro_avisa_a_saida_para_o_staff(events):
    from schemas import MEMBER_LEFT_SUBJECT

    async def scenario(svc):
        ana = await signup(svc)
        bia = await signup(svc, email="bia@acme.com", organization=None, invite=await _code(svc, ana), name="Bia")
        events.clear()
        with as_user(ana):
            await svc.remove_member(MemberRef(user=bia.auth.user.id))
        return ana, bia

    ana, bia = run(scenario)
    saidas = [(m.tenant, m.user) for s, m, _ in events if s == MEMBER_LEFT_SUBJECT]
    assert saidas == [(ana.auth.tenant.id, bia.auth.user.id)]
