"""svc-staff · lógica de negócio pura. Fonte da verdade: specs/staff.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py, e vira a activity "staff.<método>".

O staff é a equipe da Cogniventure: quem é membro da organização da plataforma (PLATFORM_TENANT); dono e admin dela
são gestores da carteira. Tudo deste serviço fica nessa organização: a carteira (quem cuida de qual cliente) e a fila
(o que espera o staff em cada cliente, espelhado dos eventos do svc-processos). Entrar na carteira dá o papel operador
na organização do cliente (svc-identity); sair tira. Para resolver, a pessoa entra na organização do cliente.
"""
from datetime import UTC, datetime
from typing import Any

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import notify
from core.security import Principal, acting_as, current, current_tenant, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    ACOMPANHAMENTO_SUBJECT,
    CARTEIRAS,
    FILA,
    GESTORES,
    LIVE_CARTEIRAS,
    LIVE_FILA,
    OPERADOR_SUBJECT,
    ORGANIZACOES_SUBJECT,
    SERVICE,
    Acompanhamento,
    Atribuicao,
    Carteira,
    CarteiraMudou,
    CarteiraRef,
    Carteiras,
    Empty,
    Escalados,
    FilaMudou,
    FilaPage,
    FilaQuery,
    ItemFila,
    ItemRef,
    ItemStaff,
    MinhaCarteira,
    NovaCarteira,
    OperadorAcesso,
    OperadorResultado,
    Organizacao,
    Organizacoes,
    Resumo,
    Saude,
    StaffSettings,
)

MIGRATIONS: list[Migration] = []
settings = StaffSettings()


@activities("staff")
class StaffService:
    # ── Carteira ─────────────────────────────────────────────────────────────

    async def organizacoes(self, data: Empty) -> Organizacoes:
        """As organizações clientes (todas menos a da Cogniventure), para o gestor montar as carteiras."""
        _gestor()
        return Organizacoes(items=[o for o in await _organizacoes() if o.id != settings.platform_tenant])

    async def carteiras(self, data: Empty) -> Carteiras:
        """O gestor vê todas; cada pessoa do staff, as suas."""
        who = _staff()
        if GESTORES & who.roles:
            rows = await db.query(f"SELECT * FROM {CARTEIRAS} WHERE tenant = $tenant ORDER BY organizacao_nome")
        else:
            rows = await db.query(f"SELECT * FROM {CARTEIRAS} WHERE tenant = $tenant AND pessoa = $p ORDER BY organizacao_nome", p=who.sub)
        return Carteiras(itens=[Carteira.model_validate(r) for r in rows])

    async def atribuir_carteira(self, data: NovaCarteira) -> Carteira:
        """O cliente entra na carteira da pessoa: ela ganha o papel operador na organização dele."""
        _gestor()
        organizacao = next((o for o in await _organizacoes() if o.id == data.organizacao), None)
        if organizacao is None or organizacao.id == settings.platform_tenant:
            raise ServiceError("ERRO_STAFF_ORGANIZACAO", "Organização cliente não encontrada.", 404)
        if await db.query(f"SELECT id FROM {CARTEIRAS} WHERE tenant = $tenant AND pessoa = $p AND organizacao = $o LIMIT 1",
                          p=data.pessoa, o=data.organizacao):
            raise ServiceError("ERRO_STAFF_JA_NA_CARTEIRA", "Esta organização já está na carteira desta pessoa.", 409)
        await _operador(data.pessoa, data.organizacao, ativo=True)
        try:
            row = await db.create(CARTEIRAS, {"pessoa": data.pessoa, "organizacao": data.organizacao, "organizacao_nome": organizacao.name})
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_STAFF_JA_NA_CARTEIRA", "Esta organização já está na carteira desta pessoa.", 409) from None
            raise
        carteira = Carteira.model_validate(row)
        await bus.live(LIVE_CARTEIRAS, CarteiraMudou(id=carteira.id, action="atribuida"))
        return carteira

    async def remover_carteira(self, data: CarteiraRef) -> Carteira:
        """O cliente sai da carteira: a pessoa perde o papel operador na organização dele."""
        _gestor()
        row = await db.select(f"{CARTEIRAS}:{data.id}")
        if row is None:
            raise ServiceError("ERRO_STAFF_NAO_ENCONTRADO", "Carteira não encontrada.", 404)
        carteira = Carteira.model_validate(row)
        await _operador(carteira.pessoa, carteira.organizacao, ativo=False)
        await db.delete(f"{CARTEIRAS}:{data.id}")
        await bus.live(LIVE_CARTEIRAS, CarteiraMudou(id=carteira.id, action="removida"))
        return carteira

    async def carteira(self, data: Empty) -> MinhaCarteira:
        """Cada cliente da carteira com a saúde dele: execuções, autonomia e o que espera o staff."""
        who = _staff()
        minhas = (await self.carteiras(Empty())).itens
        organizacoes = {c.organizacao: c.organizacao_nome for c in minhas}
        abertos = await db.query(f"SELECT organizacao, tipo, count() AS n FROM {FILA} WHERE tenant = $tenant AND status = 'aberta' "
                                 "GROUP BY organizacao, tipo")
        itens = []
        for org, nome in organizacoes.items():
            contagem = {r["tipo"]: r["n"] for r in abertos if r["organizacao"] == org}
            saude = Saude(organizacao=org, nome=nome, excecoes=contagem.get("excecao", 0), revisoes=contagem.get("revisao", 0),
                          ajudas=contagem.get("ajuda", 0))
            try:
                with acting_as(system(SERVICE, org)):
                    a = await bus.request(ACOMPANHAMENTO_SUBJECT, Empty(), Acompanhamento, timeout=5)
                saude = saude.model_copy(update={"andamento": a.andamento, "concluidas": a.concluidas, "incidentes": a.incidentes,
                                                 "autonomia": a.autonomia})
            except (NatsError, TimeoutError, ServiceError):
                saude = saude.model_copy(update={"disponivel": False})
            itens.append(saude)
        return MinhaCarteira(gestor=bool(GESTORES & who.roles), itens=itens)

    # ── Fila ─────────────────────────────────────────────────────────────────

    async def receber(self, data: ItemStaff) -> Empty:
        """events.processos.staff: algo espera (ou deixou de esperar) o staff numa organização cliente."""
        if not settings.platform_tenant:
            return Empty()
        organizacao = current_tenant()
        chave = f"{organizacao}:{data.tipo}:{data.ref}"
        with acting_as(system(SERVICE, settings.platform_tenant)):
            existente = await db.query(f"SELECT * FROM {FILA} WHERE tenant = $tenant AND chave = $c LIMIT 1", c=chave)
            if data.status == "aberta":
                dados = {"titulo": data.titulo, "detalhe": data.detalhe, "prazo": data.prazo, "link": data.link, "status": "aberta"}
                if existente:
                    row = await db.merge(_ref(existente[0]), {**dados, "escalada": False, "assumida_por": None})
                else:
                    nome = await _nome(organizacao)
                    try:
                        row = await db.create(FILA, {"chave": chave, "organizacao": organizacao, "organizacao_nome": nome,
                                                     "tipo": data.tipo, "ref": data.ref, "escalada": False, **dados})
                    except ServiceError as exc:  # outra entrega do mesmo aviso chegou junto
                        if exc.code != "ERRO_RECORD_DUPLICATE":
                            raise
                        return Empty()
            elif existente:
                row = await db.merge(_ref(existente[0]), {"status": "concluida"})
            else:
                return Empty()
            item = ItemFila.model_validate(row)
            await bus.live(LIVE_FILA, FilaMudou(id=item.id, action="chegou" if data.status == "aberta" else "mudou"))
        return Empty()

    async def fila(self, data: FilaQuery) -> FilaPage:
        """A fila das organizações da carteira de quem pede (o gestor pede todas), pelo prazo."""
        who = _staff()
        consulta = data.model_copy(update={"todas": None})
        if not (data.todas and GESTORES & who.roles):
            minhas = [c.organizacao for c in (await self.carteiras(Empty())).itens if c.pessoa == who.sub]
            pedidas = set(data.organizacao or minhas) & set(minhas)
            consulta = consulta.model_copy(update={"organizacao": sorted(pedidas) or ["-"]})
        return await db.page(FILA, consulta, FilaPage)

    async def assumir(self, data: ItemRef) -> ItemFila:
        """Quem assume responde pelo item: ele não sobe para o gestor quando o prazo passar."""
        who = _staff()
        item = await _item(data.id)
        if not GESTORES & who.roles and item.organizacao not in {c.organizacao for c in (await self.carteiras(Empty())).itens}:
            raise ServiceError("ERRO_STAFF_FORBIDDEN", "Esta organização não está na sua carteira.", 403)
        row = await db.merge(f"{FILA}:{item.id}", {"assumida_por": who.sub})
        await bus.live(LIVE_FILA, FilaMudou(id=item.id, action="mudou"))
        return ItemFila.model_validate(row)

    async def atribuir(self, data: Atribuicao) -> ItemFila:
        """O gestor passa um item para alguém do staff (ex.: o que subiu por prazo)."""
        _gestor()
        item = await _item(data.id)
        row = await db.merge(f"{FILA}:{item.id}", {"atribuida_a": data.pessoa, "assumida_por": data.pessoa})
        await notify.user(data.pessoa, title=f"Para você: {item.titulo}", body=f"{item.organizacao_nome} · {item.detalhe or ''}".strip(" ·"),
                          link="/staff", key=f"atribuido-{item.id}-{data.pessoa}")
        await bus.live(LIVE_FILA, FilaMudou(id=item.id, action="mudou"))
        return ItemFila.model_validate(row)

    async def escalar(self, data: Empty) -> Escalados:
        """Agendado (a cada minuto): exceção aberta que passou do prazo sem ninguém assumir sobe para o gestor."""
        if not settings.platform_tenant:
            return Escalados(itens=0)
        with acting_as(system(SERVICE, settings.platform_tenant)):
            rows = await db.query(f"SELECT * FROM {FILA} WHERE tenant = $tenant AND status = 'aberta' AND tipo = 'excecao' "
                                  "AND escalada = false AND (assumida_por = NONE OR assumida_por = NULL) AND prazo != NONE "
                                  "AND prazo < time::now()")
            for row in rows:
                item = ItemFila.model_validate(await db.merge(_ref(row), {"escalada": True}))
                await notify.roles("owner", "admin", title=f"Passou do prazo sem dono: {item.titulo}",
                                   body=f"{item.organizacao_nome} · {item.detalhe or 'exceção para o staff'}", link="/staff",
                                   key=f"escalada-{item.id}")
                await bus.live(LIVE_FILA, FilaMudou(id=item.id, action="escalada"))
        return Escalados(itens=len(rows))

    async def resumo(self, data: Empty) -> Resumo:
        """Para a tela: quem pergunta é do staff? E o que há na fila dele."""
        who = current()
        if who is None or not settings.platform_tenant or who.tenant != settings.platform_tenant:
            return Resumo(staff=False, gestor=False)
        gestor = bool(GESTORES & who.roles)
        minhas = {c.organizacao for c in (await self.carteiras(Empty())).itens if gestor or c.pessoa == who.sub}
        rows = await db.query(f"SELECT organizacao, tipo, prazo, escalada FROM {FILA} WHERE tenant = $tenant AND status = 'aberta'")
        rows = [r for r in rows if gestor or r["organizacao"] in minhas]
        agora = datetime.now(UTC)
        return Resumo(staff=True, gestor=gestor, organizacoes=len(minhas),
                      excecoes=sum(1 for r in rows if r["tipo"] == "excecao"), revisoes=sum(1 for r in rows if r["tipo"] == "revisao"),
                      ajudas=sum(1 for r in rows if r["tipo"] == "ajuda"), escaladas=sum(1 for r in rows if r.get("escalada")),
                      atrasadas=sum(1 for r in rows if r.get("prazo") and _quando(r["prazo"]) < agora))


# ── Ajudantes ────────────────────────────────────────────────────────────────

def _staff() -> Principal:
    """A área do staff é de quem é da organização da Cogniventure."""
    who = current()
    if who is None or not settings.platform_tenant or who.tenant != settings.platform_tenant:
        raise ServiceError("ERRO_STAFF_FORBIDDEN", "A área do staff é da equipe da Cogniventure.", 403)
    return who


def _gestor() -> Principal:
    who = _staff()
    if not GESTORES & who.roles:
        raise ServiceError("ERRO_STAFF_FORBIDDEN", "Só o gestor da carteira (dono ou admin da Cogniventure) faz isso.", 403)
    return who


def _ref(row: dict[str, Any]) -> str:
    return f"{str(row['id']).partition(':')[0]}:{_chave(row['id'])}"


def _chave(record_id: Any) -> str:
    return str(record_id).partition(":")[2].strip("⟨⟩`") if ":" in str(record_id) else str(record_id)


async def _item(item_id: str) -> ItemFila:
    row = await db.select(f"{FILA}:{item_id}")
    if row is None:
        raise ServiceError("ERRO_STAFF_NAO_ENCONTRADO", "Item não encontrado na fila.", 404)
    return ItemFila.model_validate(row)


async def _organizacoes() -> list[Organizacao]:
    try:
        with acting_as(system(SERVICE, settings.platform_tenant)):
            return (await bus.request(ORGANIZACOES_SUBJECT, Empty(), Organizacoes, timeout=5)).items
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_STAFF_IDENTIDADE", "O serviço de identidade não respondeu. Tente de novo em instantes.", 503) from None


async def _nome(organizacao: str) -> str:
    """O nome da organização: da carteira, se já está em alguma; senão, da identidade."""
    rows = await db.query(f"SELECT organizacao_nome FROM {CARTEIRAS} WHERE tenant = $tenant AND organizacao = $o LIMIT 1", o=organizacao)
    if rows:
        return rows[0]["organizacao_nome"]
    try:
        return next((o.name for o in await _organizacoes() if o.id == organizacao), organizacao)
    except ServiceError:
        return organizacao


async def _operador(pessoa: str, organizacao: str, *, ativo: bool) -> OperadorResultado:
    try:
        with acting_as(system(SERVICE, settings.platform_tenant)):
            return await bus.request(OPERADOR_SUBJECT, OperadorAcesso(user=pessoa, tenant=organizacao, ativo=ativo), OperadorResultado, timeout=5)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_STAFF_IDENTIDADE", "O serviço de identidade não respondeu. Tente de novo em instantes.", 503) from None
    except ServiceError as exc:
        if exc.status == 404:
            raise ServiceError("ERRO_STAFF_PESSOA", "A pessoa não é da equipe da Cogniventure.", 404) from None
        raise


def _quando(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    data = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    return data if data.tzinfo else data.replace(tzinfo=UTC)
