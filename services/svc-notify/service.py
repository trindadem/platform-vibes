"""svc-notify · lógica de negócio pura. Fonte da verdade: specs/notify.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "notify.<método>".
Helpers começam com _ e nunca viram activities.

Serviço de plataforma (README §5.15): único com as credenciais SMTP. Avisos por organização; e-mails e preferências
em tabelas globais (db.query_shared). O conteúdo do e-mail é apagado depois de enviado.
"""
import asyncio
import functools
import html
import logging
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Any
from urllib.parse import unquote, urlsplit

from surrealdb import RecordID

from core.envelope import ServiceError
from core.nats_bus import bus
from core.security import Principal, acting_as, current, system
from core.surreal import Migration, Page, db
from core.temporal_runner import activities

from schemas import (
    CONTACTS_SUBJECT,
    EMAILS,
    ITEMS,
    KEEP_EMAIL_DAYS,
    KEEP_READ_DAYS,
    NEW_LIVE,
    PREFS,
    SERVICE,
    Cleaned,
    Contacts,
    ContactsRequest,
    EmailRef,
    EmailResult,
    Empty,
    Notification,
    NotificationPage,
    NotificationQuery,
    NotifyRequest,
    NotifySettings,
    Outgoing,
    Preferences,
    Prepared,
    ReadRequest,
    Unread,
)

# Mudanças de dados versionadas, rodadas uma vez por banco no boot (README §5.13). Nunca edite uma já publicada.
MIGRATIONS: list[Migration] = []

log = logging.getLogger("svc-notify")

_UNREAD = (
    "SELECT count() AS total FROM (SELECT id FROM notify_items WHERE tenant = $tenant AND user = $me AND read = false) "
    "GROUP ALL"
)


@functools.cache
def settings() -> NotifySettings:
    """Lida e conferida no boot (main.py): SMTP_URL inválida ou sem TLS em produção impede o serviço de subir."""
    s = NotifySettings()
    url = urlsplit(s.smtp_url.get_secret_value())
    if url.scheme not in {"smtp", "smtps"} or not url.hostname:
        raise ValueError("SMTP_URL: use smtps://usuário:senha@host:465 ou smtp://usuário:senha@host:587")
    if not parseaddr(s.mail_from)[1] or "@" not in parseaddr(s.mail_from)[1]:
        raise ValueError('MAIL_FROM: use "Nome <nao-responda@dominio>"')
    return s


@activities("notify")
class NotifyService:
    # ── Tela: os avisos de quem chama, na organização ativa ─────────────────

    async def list_items(self, data: NotificationQuery) -> NotificationPage:
        rows = await db.page(ITEMS, data, Page[dict[str, Any]], where="user = $me", me=_who().sub)
        return NotificationPage(**rows.model_dump(exclude={"items"}), items=[_view(row) for row in rows.items])

    async def unread(self, data: Empty) -> Unread:
        rows = await db.query(_UNREAD, me=_who().sub)
        return Unread(count=rows[0]["total"] if rows else 0)

    async def mark_read(self, data: ReadRequest) -> Unread:
        await db.query(
            "UPDATE notify_items SET read = true, read_at = time::now() "
            "WHERE tenant = $tenant AND user = $me AND read = false AND id IN $ids",
            me=_who().sub, ids=[RecordID(ITEMS, i) for i in data.ids],
        )
        return await self.unread(Empty())

    async def mark_all_read(self, data: Empty) -> Unread:
        await db.query(
            "UPDATE notify_items SET read = true, read_at = time::now() WHERE tenant = $tenant AND user = $me AND read = false",
            me=_who().sub,
        )
        return Unread(count=0)

    async def preferences(self, data: Empty) -> Preferences:
        rows = await db.query_shared("SELECT email FROM notify_prefs WHERE user = $me", me=_who().sub)
        return Preferences(email=rows[0]["email"] if rows else True)

    async def set_preferences(self, data: Preferences) -> Preferences:
        me = _who().sub
        await db.query_shared("UPSERT $id SET user = $me, email = $email", id=RecordID(PREFS, me), me=me, email=data.email)
        return data

    # ── Entrega (NotifyWorkflow) ────────────────────────────────────────────

    async def deliver(self, data: Outgoing) -> Prepared:
        """Grava os avisos (um por pessoa, sem repetir na reentrega), avisa ao vivo e prepara os e-mails."""
        request = data.request
        if request.email is not None:  # endereço solto: só e-mail, sempre
            return Prepared(notified=0, emails=[await self._email(data.message, request, request.email, None, None)])
        contacts = await bus.request(CONTACTS_SUBJECT, ContactsRequest(users=request.users, roles=request.roles), Contacts)
        if not contacts.items:
            return Prepared(notified=0, emails=[])
        prefs = await db.query_shared(
            "SELECT user, email FROM notify_prefs WHERE user IN $users", users=[c.id for c in contacts.items]
        )
        email_off = {row["user"] for row in prefs if row.get("email") is False}
        notified, emails = 0, []
        for contact in contacts.items:
            item = await self._item(data.message, contact.id, request)
            if item is not None:
                notified += 1
                await bus.live(NEW_LIVE, item, user=contact.id)
            if request.send_email and contact.id not in email_off:
                emails.append(await self._email(data.message, request, contact.email, contact.name, contacts.tenant_name))
        return Prepared(notified=notified, emails=emails)

    async def send_email(self, data: EmailRef) -> EmailResult:
        """Envia um e-mail preparado. Já enviado ou desistido: não sai de novo. Erro temporário: o Temporal tenta de novo."""
        row = await db.select(f"{EMAILS}:{data.id}")
        if row is None or row["status"] != "pending":
            return EmailResult(id=data.id, status=row["status"] if row else "skipped")
        s = settings()
        message = _message(s, row)
        try:
            await asyncio.to_thread(_smtp_send, s, message)
        except (OSError, smtplib.SMTPException) as exc:
            code = getattr(exc, "smtp_code", None)
            error = f"{type(exc).__name__}{f' {code}' if code else ''}"  # nunca a mensagem do servidor (pode ecoar dados)
            if _permanent(exc):
                await db.merge(row["id"], {"status": "failed", "error": error, "attempts": row["attempts"] + 1, "html": None, "text": None})
                log.warning("e-mail %s recusado (%s)", data.id, error)
                return EmailResult(id=data.id, status="failed")
            await db.merge(row["id"], {"attempts": row["attempts"] + 1, "error": error})
            raise ServiceError("ERRO_NOTIFY_SMTP_UNAVAILABLE", "Servidor de e-mail indisponível.", 503) from None
        await db.merge(row["id"], {"status": "sent", "sent_at": _now(), "attempts": row["attempts"] + 1, "error": None,
                                   "html": None, "text": None})  # o conteúdo (links de senha, convites) não fica no banco
        return EmailResult(id=data.id, status="sent")

    async def give_up(self, data: EmailRef) -> EmailResult:
        """Tentativas esgotadas: marca como falha e apaga o conteúdo."""
        await db.query_shared(
            "UPDATE $id SET status = 'failed', html = NONE, text = NONE WHERE status = 'pending'", id=RecordID(EMAILS, data.id)
        )
        return EmailResult(id=data.id, status="failed")

    # ── Manutenção (agendamento diário) ─────────────────────────────────────

    async def cleanup(self, data: Empty) -> Cleaned:
        items = 0
        read_before = _now() - timedelta(days=KEEP_READ_DAYS)
        for org in await db.tenants(ITEMS):
            with acting_as(system(SERVICE, org)):
                gone = await db.query(
                    "DELETE notify_items WHERE tenant = $tenant AND read = true AND created_at < $before RETURN BEFORE",
                    before=read_before,
                )
                items += len(gone or [])
        emails = await db.query_shared(
            "DELETE notify_emails WHERE created_at < $before RETURN BEFORE", before=_now() - timedelta(days=KEEP_EMAIL_DAYS)
        )
        return Cleaned(items=items, emails=len(emails or []))

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _item(self, message: str, user: str, request: NotifyRequest) -> Notification | None:
        """Um aviso por pessoa e mensagem: a reentrega da mesma mensagem não cria outro (None)."""
        try:
            row = await db.create(ITEMS, {
                "message": message,
                "user": user,
                "title": request.title,
                "body": request.body,
                "link": request.link,
                "action": request.action,
                "service": request.service,
                "read": False,
            })
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                return None
            raise
        return _view(row)

    async def _email(self, message: str, request: NotifyRequest, to: str, name: str | None, tenant_name: str | None) -> str:
        """Prepara o e-mail (único por mensagem e destinatário) e devolve o id."""
        s = settings()
        who = current()
        subject, text, body_html = _render(s, request, name, tenant_name)
        try:
            row = await db.create(EMAILS, {
                "message": message,
                "to": to,
                "name": name,
                "organization": who.tenant if who else None,
                "service": request.service,
                "subject": subject,
                "text": text,
                "html": body_html,
                "status": "pending",
                "attempts": 0,
            })
        except ServiceError as exc:
            if exc.code != "ERRO_RECORD_DUPLICATE":
                raise
            rows = await db.query_shared("SELECT id FROM notify_emails WHERE message = $m AND to = $to", m=message, to=to)
            row = rows[0]
        return _key(row["id"])


def _who() -> Principal:
    who = current()
    if who is None:
        raise ServiceError("ERRO_NOTIFY_UNAUTHENTICATED", "Sessão expirada. Entre de novo.", 401)
    return who


def _view(row: dict) -> Notification:
    return Notification.model_validate({**row, "id": _key(row["id"])})


def _render(s: NotifySettings, request: NotifyRequest, name: str | None, tenant_name: str | None) -> tuple[str, str, str]:
    """Assunto, texto puro e HTML. Tudo o que veio do serviço é escapado; o link é sempre APP_URL + caminho."""
    url = s.app_url + request.link if request.link else None
    action = request.action or "Abrir"
    paragraphs = [p.strip() for p in request.body.split("\n\n") if p.strip()]
    greeting = f"Olá, {name.split()[0]}." if name else None
    if request.email is None:
        footer = (f"Você recebeu este aviso como participante de {tenant_name} em {s.app_name}. "
                  f"Para receber só na tela, desligue o e-mail em {s.app_url}/notificacoes.")
    else:
        footer = f"Enviado por {s.app_name}" + (f" em nome de {tenant_name}." if tenant_name else ".")

    text = "\n\n".join([*([greeting] if greeting else []), request.title, *paragraphs,
                        *([f"{action}: {url}"] if url else []), f"-- \n{footer}"])
    e = html.escape
    button = (
        f'<p style="margin:24px 0"><a href="{e(url)}" style="background:#18181b;color:#ffffff;padding:10px 18px;'
        f'border-radius:6px;text-decoration:none;display:inline-block">{e(action)}</a></p>'
        f'<p style="color:#71717a;font-size:12px">Se o botão não funcionar, copie o endereço: {e(url)}</p>'
        if url else ""
    )
    body_html = (
        '<!doctype html><html lang="pt-BR"><body style="margin:0;padding:24px;background:#f4f4f5;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#18181b">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;padding:32px">'
        f'<p style="margin:0 0 24px;font-weight:600;color:#71717a">{e(s.app_name)}</p>'
        + (f"<p>{e(greeting)}</p>" if greeting else "")
        + f'<h1 style="font-size:20px;margin:0 0 16px">{e(request.title)}</h1>'
        + "".join(f'<p style="line-height:1.5">{e(p).replace(chr(10), "<br>")}</p>' for p in paragraphs)
        + button
        + f'<hr style="border:none;border-top:1px solid #e4e4e7;margin:24px 0"><p style="color:#71717a;font-size:12px">{e(footer)}</p>'
        "</div></body></html>"
    )
    return request.title, text, body_html


def _message(s: NotifySettings, row: dict) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = row["subject"]
    message["From"] = s.mail_from
    local, _, domain = row["to"].rpartition("@")
    message["To"] = Address(display_name=row.get("name") or "", username=local, domain=domain)
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=parseaddr(s.mail_from)[1].rpartition("@")[2] or None)
    message["Auto-Submitted"] = "auto-generated"  # resposta automática (férias) não volta para cá
    message.set_content(row["text"])
    message.add_alternative(row["html"], subtype="html")
    return message


def _smtp_send(s: NotifySettings, message: EmailMessage) -> None:
    """Envio bloqueante (roda em thread). smtps: TLS direto; smtp: STARTTLS, obrigatório fora de development."""
    url = urlsplit(s.smtp_url.get_secret_value())
    context = ssl.create_default_context()
    if url.scheme == "smtps":
        server: smtplib.SMTP = smtplib.SMTP_SSL(url.hostname, url.port or 465, timeout=30, context=context)
    else:
        server = smtplib.SMTP(url.hostname, url.port or 587, timeout=30)
    with server:
        server.ehlo()
        if url.scheme == "smtp":
            if server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
            elif s.environment != "development":
                raise smtplib.SMTPNotSupportedError("servidor sem STARTTLS: senha e conteúdo iriam sem criptografia")
        if url.username:
            server.login(unquote(url.username), unquote(url.password or ""))
        server.send_message(message)


def _permanent(exc: Exception) -> bool:
    """Recusa que não muda tentando de novo (endereço inválido, mensagem recusada, servidor sem TLS). Credencial
    errada, 4xx, servidor fora do ar e tempo esgotado são temporários: alguém corrige e a próxima tentativa sai."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return False
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPNotSupportedError)):
        return True
    return isinstance(exc, smtplib.SMTPResponseException) and exc.smtp_code >= 500


def _now() -> datetime:
    return datetime.now(UTC)


def _key(record_id: str) -> str:
    return str(record_id).partition(":")[2].strip("⟨⟩`")
