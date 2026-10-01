"""svc-notify · testes sem infraestrutura. Fonte da verdade: specs/notify.md §2 e §4

SurrealDB embutido em memória (mem://), com as tabelas e índices do boot e a SurrealQL de verdade; o NATS vira dublê
(inclusive o rpc.identity.contacts) e o servidor de e-mail vira um SMTP falso que guarda as mensagens.

Rodar (da raiz): PYTHONPATH=services/svc-notify uv run python -m pytest tests/notify.py
"""
import asyncio
import smtplib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from surrealdb import AsyncSurreal

from core.envelope import ServiceError
from core.notify import Contact, Contacts
from core.security import Principal, acting_as, current_tenant

import service
from schemas import (
    CONTACTS_SUBJECT,
    NEW_LIVE,
    SHARED_TABLES,
    TENANT_TABLES,
    UNIQUE,
    EmailRef,
    Empty,
    NotificationQuery,
    NotifyRequest,
    Outgoing,
    Preferences,
    ReadRequest,
)

ANA = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))
BIA = Principal(sub="bia", tenant="acme", roles=frozenset({"member"}))
CAIO = Principal(sub="caio", tenant="beta", roles=frozenset({"owner"}))
PEOPLE = {  # o que o svc-identity responderia: membros de cada organização
    "acme": [("ana", "Ana Lima", "ana@acme.com", {"owner"}), ("bia", "Bia Souza", "bia@acme.com", {"member"})],
    "beta": [("caio", "Caio", "caio@beta.com", {"owner"})],
}


@pytest.fixture
def mail(monkeypatch):
    """Configuração de desenvolvimento, NATS em memória e SMTP falso. Devolve o que foi publicado e enviado."""
    for name, value in {"SMTP_URL": "smtp://mailpit:1025", "MAIL_FROM": "CV-Frame <nao-responda@cv.test>",
                        "APP_URL": "http://localhost:5173", "ENVIRONMENT": "development"}.items():
        monkeypatch.setenv(name, value)
    service.settings.cache_clear()
    box = SimpleNamespace(sent=[], live=[], error=None, starttls=False, tls=False, login=None)

    async def live(topic, message, user=None):
        box.live.append((topic, message, user))

    async def request(subject, message, model, timeout=5.0):
        assert subject == CONTACTS_SUBJECT
        people = PEOPLE[current_tenant()]  # a organização vem do cabeçalho de quem pediu
        items = [Contact(id=i, name=n, email=e) for i, n, e, roles in people if i in message.users or roles & set(message.roles)]
        return Contacts(tenant_name=current_tenant().title(), items=items)

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            box.server = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def ehlo(self):
            pass

        def has_extn(self, name):
            return box.starttls

        def starttls(self, context=None):
            box.tls = True

        def login(self, user, password):
            box.login = (user, password)

        def send_message(self, message):
            if box.error is not None:
                raise box.error
            box.sent.append(message)

    monkeypatch.setattr(service.bus, "live", live)
    monkeypatch.setattr(service.bus, "request", request)
    monkeypatch.setattr(service.smtplib, "SMTP", FakeSMTP)
    yield box
    service.settings.cache_clear()


def run(scenario):
    """Roda o cenário com o SurrealDB embutido, já com as tabelas e índices do boot."""

    async def go():
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        service.db._conn = conn
        async with service.db.connected(tables=TENANT_TABLES, shared=SHARED_TABLES, unique=UNIQUE):
            return await scenario(service.NotifyService())

    return asyncio.run(go())


def _out(message="m1", **request):
    fields = {"service": "svc-faturas", "title": "Fatura paga", **request}
    return Outgoing(message=message, request=NotifyRequest(**fields))


async def _email_row(email_id):
    return await service.db.select(f"notify_emails:{email_id}")


def test_aviso_chega_na_tela_ao_vivo_e_por_email(mail):
    async def scenario(svc):
        with acting_as(ANA):  # quem avisa: o cabeçalho leva a organização
            prepared = await svc.deliver(_out(
                users=["bia", "caio"], body="A fatura 123 foi paga.\n\nObrigado.", link="/faturas?id=123", action="Ver fatura"
            ))
            result = await svc.send_email(EmailRef(id=prepared.emails[0]))
        with acting_as(BIA):
            page = await svc.list_items(NotificationQuery())
            before = await svc.unread(Empty())
            after = await svc.mark_read(ReadRequest(ids=[page.items[0].id]))
            unread_only = await svc.list_items(NotificationQuery(read=False))
        return prepared, result, page, before, after, unread_only, await _email_row(prepared.emails[0])

    prepared, result, page, before, after, unread_only, row = run(scenario)
    assert (prepared.notified, len(prepared.emails)) == (1, 1)  # Caio é de outra organização: ignorado
    assert [(t, m.title, u) for t, m, u in mail.live] == [(NEW_LIVE, "Fatura paga", "bia")]
    assert result.status == "sent" and len(mail.sent) == 1
    message = mail.sent[0]
    assert (message["To"], message["Subject"], message["From"]) == ("Bia Souza <bia@acme.com>", "Fatura paga", "CV-Frame <nao-responda@cv.test>")
    text = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()
    assert "Olá, Bia." in text and "Ver fatura: http://localhost:5173/faturas?id=123" in text
    assert 'href="http://localhost:5173/faturas?id=123"' in html and "Acme" in html and "/notificacoes" in html
    assert (row["status"], row.get("html"), row.get("text")) == ("sent", None, None)  # conteúdo não fica no banco
    item = page.items[0]
    assert (item.title, item.body, item.link, item.service, item.read) == (
        "Fatura paga", "A fatura 123 foi paga.\n\nObrigado.", "/faturas?id=123", "svc-faturas", False)
    assert (before.count, after.count, unread_only.total) == (1, 0, 0)


def test_reentrega_nao_duplica_aviso_nem_email(mail):
    async def scenario(svc):
        with acting_as(ANA):
            first = await svc.deliver(_out(users=["bia"]))
            again = await svc.deliver(_out(users=["bia"]))  # o NATS entregou de novo a mesma mensagem
            await svc.send_email(EmailRef(id=first.emails[0]))
            resent = await svc.send_email(EmailRef(id=again.emails[0]))
        with acting_as(BIA):
            page = await svc.list_items(NotificationQuery())
        return first, again, resent, page

    first, again, resent, page = run(scenario)
    assert (first.notified, again.notified, first.emails == again.emails) == (1, 0, True)
    assert resent.status == "sent" and len(mail.sent) == 1 and page.total == 1


def test_preferencia_desliga_so_o_email_dos_avisos_comuns(mail):
    async def scenario(svc):
        with acting_as(BIA):
            default = await svc.preferences(Empty())
            await svc.set_preferences(Preferences(email=False))
            saved = await svc.preferences(Empty())
        with acting_as(ANA):
            common = await svc.deliver(_out(users=["bia"]))
            by_role = await svc.deliver(_out("m2", roles=["owner", "member"]))
            security = await svc.deliver(_out("m3", email="bia@acme.com", title="Redefinir sua senha"))
        return default, saved, common, by_role, security

    default, saved, common, by_role, security = run(scenario)
    assert (default.email, saved.email) == (True, False)
    assert (common.notified, common.emails) == (1, [])  # na tela sim, por e-mail não
    assert (by_role.notified, len(by_role.emails)) == (2, 1)  # Ana recebe o e-mail; Bia, só na tela
    assert (security.notified, len(security.emails)) == (0, 1)  # e-mail de segurança sempre sai


def test_avisos_sao_de_cada_pessoa_em_cada_organizacao(mail):
    async def scenario(svc):
        with acting_as(ANA):
            await svc.deliver(_out(users=["bia"]))
        with acting_as(BIA):
            bia_id = (await svc.list_items(NotificationQuery())).items[0].id
        with acting_as(ANA):
            ana_page = await svc.list_items(NotificationQuery())
            await svc.mark_read(ReadRequest(ids=[bia_id]))  # id de outra pessoa: nada acontece
        with acting_as(CAIO):
            caio_page = await svc.list_items(NotificationQuery())
        with acting_as(BIA):
            still = await svc.unread(Empty())
        return ana_page, caio_page, still

    ana_page, caio_page, still = run(scenario)
    assert (ana_page.total, caio_page.total, still.count) == (0, 0, 1)


def test_email_avulso_escapa_o_conteudo(mail):
    async def scenario(svc):
        prepared = await svc.deliver(_out(email="pessoa@x.com", title="<b>Convite</b>", body="Tom & Jerry <script>"))
        await svc.send_email(EmailRef(id=prepared.emails[0]))
        return prepared

    run(scenario)  # sem organização e sem pessoa: como no esqueci a senha
    html = mail.sent[0].get_body(("html",)).get_content()
    assert "&lt;b&gt;Convite&lt;/b&gt;" in html and "Tom &amp; Jerry &lt;script&gt;" in html and "<script>" not in html
    assert "Enviado por CV-Frame." in html and "/notificacoes" not in html  # sem preferência para quem não tem conta
    assert mail.sent[0]["To"] == "pessoa@x.com"


def test_falha_temporaria_tenta_de_novo_e_recusa_definitiva_desiste(mail):
    async def scenario(svc):
        with acting_as(ANA):
            prepared = await svc.deliver(_out(roles=["owner", "member"]))
        down, refused = prepared.emails
        mail.error = ConnectionRefusedError()
        with pytest.raises(ServiceError) as temporary:
            await svc.send_email(EmailRef(id=down))
        after_down = await _email_row(down)
        mail.error = smtplib.SMTPRecipientsRefused({"bia@acme.com": (550, b"no such user")})
        final = await svc.send_email(EmailRef(id=refused))
        gave_up = await svc.give_up(EmailRef(id=down))
        return temporary, after_down, final, gave_up, await _email_row(refused), await _email_row(down)

    temporary, after_down, final, gave_up, refused_row, down_row = run(scenario)
    assert (temporary.value.code, temporary.value.status) == ("ERRO_NOTIFY_SMTP_UNAVAILABLE", 503)  # o Temporal tenta de novo
    assert (after_down["status"], after_down["attempts"], after_down["error"]) == ("pending", 1, "ConnectionRefusedError")
    assert final.status == "failed" and (refused_row["status"], refused_row.get("html")) == ("failed", None)
    assert gave_up.status == "failed" and (down_row["status"], down_row.get("html")) == ("failed", None)


def test_producao_exige_tls_no_smtp(mail, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SMTP_URL", "smtp://usuario:s%40nha@smtp.exemplo.com:587")
    service.settings.cache_clear()

    async def scenario(svc):
        with acting_as(ANA):
            plain = (await svc.deliver(_out(users=["bia"]))).emails[0]
            no_tls = await svc.send_email(EmailRef(id=plain))
            mail.starttls = True
            secure = (await svc.deliver(_out("m2", users=["bia"]))).emails[0]
            with_tls = await svc.send_email(EmailRef(id=secure))
        return no_tls, with_tls

    no_tls, with_tls = run(scenario)
    assert no_tls.status == "failed"  # sem STARTTLS a senha iria aberta: não envia
    assert with_tls.status == "sent" and mail.tls and mail.login == ("usuario", "s@nha")


def test_configuracao_invalida_nao_sobe(monkeypatch):
    for name, value in {"MAIL_FROM": "CV <nao-responda@cv.test>", "APP_URL": "https://app.exemplo.com"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SMTP_URL", "http://smtp.exemplo.com")
    service.settings.cache_clear()
    with pytest.raises(ValueError, match="SMTP_URL"):
        service.settings()
    monkeypatch.setenv("SMTP_URL", "smtps://smtp.exemplo.com")
    monkeypatch.setenv("APP_URL", "https://app.exemplo.com/")  # barra no fim: os links sairiam com //
    service.settings.cache_clear()
    with pytest.raises(ValidationError):
        service.settings()
    service.settings.cache_clear()


def test_pedido_fora_do_trilho_e_recusado():
    with pytest.raises(ValidationError):
        NotifyRequest(service="svc-x", users=["a"], email="b@x.com", title="Dois destinos")
    with pytest.raises(ValidationError):
        NotifyRequest(service="svc-x", users=["a"], title="Link para fora", link="https://phishing.example")
    with pytest.raises(ValidationError):
        NotifyRequest(service="svc-x", users=["a"], title="Link que vira outro domínio", link="//phishing.example")
    with pytest.raises(ValidationError):
        NotifyRequest(service="svc-x", users=["a"], title="Assunto\nBcc: todos@x.com")


def test_limpeza_apaga_lidos_antigos_e_registros_de_email(mail, monkeypatch):
    async def scenario(svc):
        with acting_as(ANA):
            prepared = await svc.deliver(_out(users=["ana", "bia"]))
        with acting_as(BIA):
            await svc.mark_all_read(Empty())
        kept = await svc.cleanup(Empty())  # tudo recente: nada sai
        later = service._now() + timedelta(days=100)
        monkeypatch.setattr(service, "_now", lambda: later)
        cleaned = await svc.cleanup(Empty())
        with acting_as(ANA):
            ana = await svc.unread(Empty())
        return prepared, kept, cleaned, ana

    prepared, kept, cleaned, ana = run(scenario)
    assert (kept.items, kept.emails) == (0, 0)
    assert (cleaned.items, cleaned.emails) == (1, 2)  # o lido da Bia e os dois registros de e-mail
    assert ana.count == 1  # não lido nunca é apagado
