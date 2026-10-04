"""svc-atendimento · lógica de negócio pura. Fonte da verdade: specs/atendimento.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py, e vira a activity "atendimento.<método>".

O "Falar com a Cogniventure": a pessoa do cliente pede ajuda de qualquer tela; o pedido vai para a fila do staff
(events.atendimento.staff, o contrato da fila) com prazo de 4 h; o operador responde aqui, na organização do cliente,
ou pela fila do staff (rpc.atendimento.responder, só o svc-staff). Quem pediu é avisado da resposta.
"""
from datetime import UTC, datetime, timedelta

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import CONTACTS_SUBJECT, Contacts, ContactsRequest, notify
from core.security import SYSTEM_PREFIX, Principal, acting_as, current, current_tenant, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    GESTORES,
    LIVE_PEDIDOS,
    PEDIDOS,
    PRAZO_HORAS,
    SERVICE,
    STAFF_SERVICE,
    STAFF_SUBJECT,
    VEEM_TODOS,
    AtendimentoSettings,
    Empty,
    ItemStaff,
    Mensagem,
    MensagemNova,
    NovoPedido,
    Pedido,
    PedidoMudou,
    PedidoPage,
    PedidoQuery,
    PedidoRef,
    Resposta,
    Resumo,
)

MIGRATIONS: list[Migration] = []
settings = AtendimentoSettings()


@activities("atendimento")
class AtendimentoService:
    async def resumo(self, data: Empty) -> Resumo:
        """Para a moldura da tela: a pessoa pode pedir ajuda? E quantos pedidos dela (ou da organização) estão abertos."""
        who = _who()
        rows = await db.query(f"SELECT status, autor FROM {PEDIDOS} WHERE tenant = $tenant AND status != 'encerrado'")
        if not VEEM_TODOS & who.roles:
            rows = [r for r in rows if r["autor"] == who.sub]
        return Resumo(pode_pedir=_pode_pedir(who), abertos=sum(1 for r in rows if r["status"] == "aberto"),
                      respondidos=sum(1 for r in rows if r["status"] == "respondido"))

    async def pedidos(self, data: PedidoQuery) -> PedidoPage:
        """O histórico: dono, admin e operador veem os da organização; membro, os seus."""
        who = _who()
        if not VEEM_TODOS & who.roles:
            data = data.model_copy(update={"autor": who.sub})
        return await db.page(PEDIDOS, data, PedidoPage)

    async def item(self, data: PedidoRef) -> Pedido:
        return await _pedido(data.id, _who())

    async def abrir(self, data: NovoPedido) -> Pedido:
        """Abre o pedido: vai para a fila do staff com prazo de 4 h, e os operadores da organização são avisados."""
        who = _who()
        if not _pode_pedir(who):
            raise ServiceError("ERRO_ATENDIMENTO_FORBIDDEN", "Quem é da Cogniventure resolve pela área do staff.", 403)
        agora = datetime.now(UTC)
        nome = await _nome(who.sub)
        mensagem = Mensagem(papel="cliente", autor=who.sub, autor_nome=nome, texto=data.texto, em=agora)
        row = await db.create(PEDIDOS, {
            "assunto": _assunto(data.texto), "status": "aberto", "pagina": data.pagina, "autor": who.sub, "autor_nome": nome,
            "mensagens": [mensagem.model_dump(mode="json")], "prazo": agora + timedelta(hours=PRAZO_HORAS), "respondido_em": None,
        })
        pedido = Pedido.model_validate(row)
        await _fila(pedido)
        await notify.roles("operador", title=f"Pedido de ajuda: {pedido.assunto}", body=f"{nome or 'Alguém do cliente'}: {data.texto[:300]}",
                           link=_link(pedido), key=f"pedido-{pedido.id}-1")
        await bus.live(LIVE_PEDIDOS, PedidoMudou(id=pedido.id, action="aberto"))
        return pedido

    async def mensagem(self, data: MensagemNova) -> Pedido:
        """Na organização do cliente: a pessoa acrescenta (reabre, com prazo novo) ou o operador responde."""
        who = _who()
        pedido = await _pedido(data.id, who)
        papel = "staff" if "operador" in who.roles else "cliente"
        return await _escrever(pedido, papel=papel, autor=who.sub, nome=await _nome(who.sub), texto=data.texto)

    async def encerrar(self, data: PedidoRef) -> Pedido:
        """Quem pediu, dono ou admin encerram: o item sai da fila do staff, se ainda estava lá."""
        who = _who()
        pedido = await _pedido(data.id, who)
        if pedido.autor != who.sub and not GESTORES & who.roles:
            raise ServiceError("ERRO_ATENDIMENTO_FORBIDDEN", "Só quem pediu, o dono ou o administrador encerram o pedido.", 403)
        if pedido.status == "encerrado":
            return pedido
        pedido = Pedido.model_validate(await db.merge(f"{PEDIDOS}:{pedido.id}", {"status": "encerrado"}))
        await _fila(pedido)
        await bus.live(LIVE_PEDIDOS, PedidoMudou(id=pedido.id, action="encerrado"))
        return pedido

    # ── RPCs do staff (só o svc-staff, agindo na organização do cliente) ─────

    async def pedido(self, data: PedidoRef) -> Pedido:
        """rpc.atendimento.pedido: o pedido inteiro, para o cartão da fila do staff."""
        _do_staff()
        return await _pedido(data.id, None)

    async def responder(self, data: Resposta) -> Pedido:
        """rpc.atendimento.responder: o staff responde pela fila, sem entrar na organização do cliente."""
        _do_staff()
        pedido = await _pedido(data.id, None)
        return await _escrever(pedido, papel="staff", autor=data.por, nome=data.por_nome, texto=data.texto)


# ── Ajudantes ────────────────────────────────────────────────────────────────

def _who() -> Principal:
    who = current()
    if who is None or not who.tenant:
        raise ServiceError("ERRO_ATENDIMENTO_FORBIDDEN", "Entre numa organização para falar com a Cogniventure.", 403)
    return who


def _pode_pedir(who: Principal) -> bool:
    """O staff não pede ajuda a si mesmo: nem na organização da Cogniventure, nem onde só é operador."""
    if settings.platform_tenant and who.tenant == settings.platform_tenant:
        return False
    return bool(who.roles - {"operador"})


def _do_staff() -> None:
    who = current()
    if who is None or who.sub != f"{SYSTEM_PREFIX}{STAFF_SERVICE}" or not who.tenant:
        raise ServiceError("ERRO_ATENDIMENTO_FORBIDDEN", "Só o serviço do staff faz isso.", 403)


async def _pedido(pedido_id: str, who: Principal | None) -> Pedido:
    row = await db.select(f"{PEDIDOS}:{pedido_id}")
    if row is None or (who is not None and not VEEM_TODOS & who.roles and row["autor"] != who.sub):
        raise ServiceError("ERRO_ATENDIMENTO_NAO_ENCONTRADO", "Pedido não encontrado.", 404)
    return Pedido.model_validate(row)


async def _escrever(pedido: Pedido, *, papel: str, autor: str, nome: str | None, texto: str) -> Pedido:
    if pedido.status == "encerrado":
        raise ServiceError("ERRO_ATENDIMENTO_ENCERRADO", "Este pedido foi encerrado. Abra um novo, se precisar.", 409)
    agora = datetime.now(UTC)
    mensagem = Mensagem(papel=papel, autor=autor, autor_nome=nome, texto=texto, em=agora)
    mudancas: dict = {"mensagens": [m.model_dump(mode="json") for m in pedido.mensagens] + [mensagem.model_dump(mode="json")]}
    if papel == "staff":
        mudancas |= {"status": "respondido", "respondido_em": agora}
    else:
        mudancas |= {"status": "aberto", "prazo": agora + timedelta(hours=PRAZO_HORAS)}
    pedido = Pedido.model_validate(await db.merge(f"{PEDIDOS}:{pedido.id}", mudancas))
    await _fila(pedido, por=autor if papel == "staff" else None)
    n = len(pedido.mensagens)
    if papel == "staff":
        await notify.user(pedido.autor, title=f"A Cogniventure respondeu: {pedido.assunto}", body=texto[:300], link=_link(pedido),
                          key=f"resposta-{pedido.id}-{n}")
    else:
        await notify.roles("operador", title=f"Pedido de ajuda: {pedido.assunto}", body=f"{nome or 'Alguém do cliente'}: {texto[:300]}",
                           link=_link(pedido), key=f"pedido-{pedido.id}-{n}")
    await bus.live(LIVE_PEDIDOS, PedidoMudou(id=pedido.id, action="respondido" if papel == "staff" else "aberto"))
    return pedido


async def _fila(pedido: Pedido, *, por: str | None = None) -> None:
    """O item da fila do staff: aberto enquanto o pedido espera resposta; concluído quando respondido ou encerrado. Sai
    como tarefa da plataforma (o módulo do staff não é do cliente)."""
    aberto = pedido.status == "aberto"
    ultima = pedido.mensagens[-1]
    item = ItemStaff(tipo="pedido", ref=pedido.id, titulo=f"Pedido de ajuda: {pedido.assunto}",
                     detalhe=f"{ultima.autor_nome or 'Alguém do cliente'}: {ultima.texto[:200]}", prazo=pedido.prazo if aberto else None,
                     status="aberta" if aberto else "concluida", link=_link(pedido), em=datetime.now(UTC), por=por)
    with acting_as(system(SERVICE, current_tenant())):
        await bus.publish(STAFF_SUBJECT, item, msg_id=f"pedido-{pedido.id}-{len(pedido.mensagens)}-{pedido.status}")


async def _nome(user: str) -> str | None:
    """O nome de quem escreve, no svc-identity (fora do ar: a mensagem entra sem nome)."""
    try:
        contatos = await bus.request(CONTACTS_SUBJECT, ContactsRequest(users=[user]), Contacts, timeout=5)
    except (NatsError, TimeoutError, ServiceError):
        return None
    return next((c.name for c in contatos.items if c.id == user), None)


def _assunto(texto: str) -> str:
    palavras = " ".join(texto.split())
    return palavras if len(palavras) <= 80 else palavras[:77].rsplit(" ", 1)[0] + "..."


def _link(pedido: Pedido) -> str:
    return f"/atendimento?pedido={pedido.id}"
