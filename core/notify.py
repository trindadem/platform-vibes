"""Avisos: na tela e por e-mail (README §5.15). O serviço nunca fala com servidor de e-mail: só o svc-notify.

    await notify.user(sub, "Fatura paga", "A fatura 123 foi paga.", link="/faturas?id=123")    # tela + e-mail
    await notify.roles("owner", "admin", title="Limite de IA", body="...", link="/ia")         # por papel
    await notify.email("pessoa@x.com", "Convite para Acme", "...", link="/convite?codigo=...", action="Ver convite")

Trilhos:
- notify.user e notify.roles avisam pessoas da organização atual: quem não é membro dela é ignorado, e não há como
  avisar outra organização. O e-mail respeita a preferência da pessoa (send_email=False: só na tela).
- notify.email é para quem ainda não tem conta (convite) ou para segurança (senha): sempre sai, só por e-mail.
- link é um caminho da aplicação ("/faturas?id=1"); o svc-notify monta APP_URL + link. Endereço de fora é erro.
- Texto puro: o svc-notify escapa tudo no HTML. Parágrafos do body separados por linha em branco.
- Entrega durável (events.notify.send, JetStream): o svc-notify fora do ar recebe quando voltar. key= dá o mesmo id
  à mesma intenção: repetir com a mesma key não avisa duas vezes.
"""
import re
import uuid
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from core.nats_bus import bus
from core.security import current_tenant

__all__ = ["notify", "Notify", "NotifyRequest", "ContactsRequest", "Contact", "Contacts", "SEND_SUBJECT", "CONTACTS_SUBJECT"]

SEND_SUBJECT = "events.notify.send"
CONTACTS_SUBJECT = "rpc.identity.contacts"  # o svc-notify pergunta ao svc-identity quem são as pessoas
MAX_USERS = 100
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")

Role = Literal["owner", "admin", "member"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\r\n]+$")]
Body = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Link = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^/([^/\\\s]\S*)?$")]
Action = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[^\r\n]+$")]
Address = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$"),
]
UserId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class NotifyRequest(BaseModel):
    """O que viaja em events.notify.send: um destino (users, roles ou email) e o conteúdo."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(..., description="Quem pediu (svc-...)")
    users: list[UserId] = Field(default_factory=list, max_length=MAX_USERS)
    roles: list[Role] = Field(default_factory=list, max_length=3)
    email: Address | None = None
    title: Title
    body: Body = ""
    link: Link | None = Field(None, description="Caminho da aplicação; vira APP_URL + link")
    action: Action | None = Field(None, description="Texto do botão do link (padrão: Abrir)")
    send_email: bool = Field(True, description="Também por e-mail, se a pessoa não desligou")

    @model_validator(mode="after")
    def _one_destination(self) -> "NotifyRequest":
        if sum((bool(self.users), bool(self.roles), self.email is not None)) != 1:
            raise ValueError("diga um destino: users, roles ou email")
        return self


class ContactsRequest(BaseModel):
    """rpc.identity.contacts: pessoas da organização de quem pergunta, por id ou por papel."""

    users: list[UserId] = Field(default_factory=list, max_length=MAX_USERS)
    roles: list[Role] = Field(default_factory=list, max_length=3)


class Contact(BaseModel):
    id: str
    name: str
    email: str


class Contacts(BaseModel):
    tenant_name: str
    items: list[Contact]


class Notify:
    async def user(
        self,
        user: str | Sequence[str],
        title: str,
        body: str = "",
        *,
        link: str | None = None,
        action: str | None = None,
        send_email: bool = True,
        key: str | None = None,
    ) -> None:
        """Avisa uma pessoa (ou uma lista, até 100) da organização atual: na tela e, se ela não desligou, por e-mail."""
        current_tenant()  # sem organização, falha aqui (e não em silêncio no svc-notify)
        users = [user] if isinstance(user, str) else list(dict.fromkeys(user))
        if not users:
            return
        await self._send(NotifyRequest(
            service=_service(), users=users, title=title, body=body, link=link, action=action, send_email=send_email
        ), key)

    async def roles(
        self,
        *roles: Role,
        title: str,
        body: str = "",
        link: str | None = None,
        action: str | None = None,
        send_email: bool = True,
        key: str | None = None,
    ) -> None:
        """Avisa quem tem algum destes papéis na organização atual (ex.: "owner", "admin")."""
        current_tenant()
        if not roles:
            raise ValueError("notify.roles: diga ao menos um papel")
        await self._send(NotifyRequest(
            service=_service(), roles=list(dict.fromkeys(roles)), title=title, body=body, link=link, action=action,
            send_email=send_email,
        ), key)

    async def email(
        self, to: str, title: str, body: str = "", *, link: str | None = None, action: str | None = None, key: str | None = None
    ) -> None:
        """Só e-mail, para um endereço (convite, senha). Sempre sai: não depende de conta nem de preferência."""
        await self._send(NotifyRequest(service=_service(), email=to, title=title, body=body, link=link, action=action), key)

    async def _send(self, request: NotifyRequest, key: str | None) -> None:
        if key is not None and not _KEY.match(key):
            raise ValueError(f"notify: key inválida {key!r} (letras, números e _ . : -, até 120)")
        msg_id = f"notify-{request.service}-{key}" if key else f"notify-{uuid.uuid4().hex}"
        await bus.publish(SEND_SUBJECT, request, msg_id=msg_id)


def _service() -> str:
    if bus.service is None:
        raise RuntimeError("notify: bus não conectado (async with bus.connected(SERVICE) no lifespan)")
    return bus.service


notify = Notify()
