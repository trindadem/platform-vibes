"""svc-staff · lógica de negócio pura. Fonte da verdade: specs/staff.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py, e vira a activity "staff.<método>".

O staff é a equipe da Cogniventure: quem é membro da organização da plataforma (PLATFORM_TENANT); dono e admin dela
são gestores da carteira. Tudo deste serviço fica nessa organização: a carteira (quem cuida de qual cliente) e a fila
(o que espera o staff em cada cliente, espelhado dos eventos do svc-processos). Entrar na carteira dá o papel operador
na organização do cliente (svc-identity); sair tira. Para resolver, a pessoa entra na organização do cliente.
O gestor também abre os clientes (organização, convite do dono, plano e carteira) e os acompanha pela jornada; combina
a mensalidade e o vencimento, suspende o cliente em atraso, reativa e encerra (a conta é do svc-plans).
"""
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import CONTACTS_SUBJECT, Contacts, ContactsRequest, notify
from core.plans import plans
from core.security import Principal, acting_as, current, current_tenant, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    ACOMPANHAMENTO_SUBJECT,
    CARTEIRAS,
    CLIENTE_SUBJECT,
    CONTA_SUBJECT,
    CONTEXTO_SUBJECT,
    CONVITE_DONO_SUBJECT,
    FILA_DECIDIR_SUBJECT,
    FILA_RESOLVER_SUBJECT,
    FILA_REVISAO_SUBJECT,
    FILA_TAREFA_SUBJECT,
    PEDIDO_SUBJECT,
    RESPONDER_SUBJECT,
    RESULTADOS_SUBJECT,
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
    Cliente,
    ClienteCriado,
    CobrancaCliente,
    ContaAcao,
    ContaCliente,
    ContaEncerrada,
    ClienteNovo,
    ClienteRef,
    Clientes,
    ContextoEmpresa,
    ConviteDono,
    ConvitePendente,
    DecidirRevisao,
    DecisaoStaff,
    Empty,
    Escalados,
    FilaDetalhe,
    FilaMudou,
    FilaPage,
    FilaQuery,
    ItemFila,
    ItemRef,
    ItemStaff,
    MemberLeft,
    MinhaCarteira,
    NumeroLinha,
    Numeros,
    NumerosQuery,
    NovaCarteira,
    NovoCliente,
    OperadorAcesso,
    OperadorResultado,
    Organizacao,
    Organizacoes,
    PedidoFila,
    RefRevisao,
    RefTarefa,
    ResolucaoStaff,
    ResultadosCliente,
    ResultadosPedido,
    ResultadosQuery,
    ResolverExcecao,
    ResponderPedido,
    RespostaStaff,
    Resumo,
    RevisaoFila,
    Saude,
    SituacaoCliente,
    StaffSettings,
    TarefaFila,
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
                          ajudas=contagem.get("ajuda", 0), pedidos=contagem.get("pedido", 0))
            try:
                with acting_as(system(SERVICE, org)):
                    a = await bus.request(ACOMPANHAMENTO_SUBJECT, Empty(), Acompanhamento, timeout=5)
                saude = saude.model_copy(update={"andamento": a.andamento, "concluidas": a.concluidas, "incidentes": a.incidentes,
                                                 "autonomia": a.autonomia})
            except (NatsError, TimeoutError, ServiceError):
                saude = saude.model_copy(update={"disponivel": False})
            itens.append(saude)
        return MinhaCarteira(gestor=bool(GESTORES & who.roles), itens=itens)

    async def resultados(self, data: ResultadosQuery) -> ResultadosCliente:
        """Os resultados de um cliente da carteira (o gestor vê de qualquer um): os mesmos números da tela Resultados
        dele, sem trocar de organização."""
        who = _staff()
        nome = next((c.organizacao_nome for c in (await self.carteiras(Empty())).itens if c.organizacao == data.organizacao), None)
        if nome is None:
            if not GESTORES & who.roles:
                raise ServiceError("ERRO_STAFF_FORBIDDEN", "Esta organização não está na sua carteira.", 403)
            nome = next((o.name for o in await _organizacoes() if o.id == data.organizacao), None)
            if nome is None or data.organizacao == settings.platform_tenant:
                raise ServiceError("ERRO_STAFF_ORGANIZACAO", "Organização cliente não encontrada.", 404)
        try:
            with acting_as(system(SERVICE, data.organizacao)):
                resultados = await bus.request(RESULTADOS_SUBJECT, ResultadosPedido(mes=data.mes), ResultadosCliente, timeout=15)
        except (NatsError, TimeoutError):
            raise ServiceError("ERRO_STAFF_CLIENTE", "Os números deste cliente não responderam. Tente de novo em instantes.", 503) from None
        return resultados.model_copy(update={"organizacao": data.organizacao, "nome": nome})

    async def saiu(self, data: MemberLeft) -> Empty:
        """events.identity.member-left: quem sai da Cogniventure sai de todas as carteiras e perde o papel operador nos
        clientes; o que estava com a pessoa na fila volta sem dono (e sobe para o gestor quando o prazo passar)."""
        if not settings.platform_tenant or current_tenant() != settings.platform_tenant:
            return Empty()
        with acting_as(system(SERVICE, settings.platform_tenant)):
            for row in await db.query(f"SELECT * FROM {CARTEIRAS} WHERE tenant = $tenant AND pessoa = $p", p=data.user):
                carteira = Carteira.model_validate(row)
                try:
                    await _operador(carteira.pessoa, carteira.organizacao, ativo=False)
                except ServiceError as exc:
                    if exc.status != 404:  # pessoa ou organização que já não existe: só a carteira sai
                        raise
                await db.delete(f"{CARTEIRAS}:{carteira.id}")
                await bus.live(LIVE_CARTEIRAS, CarteiraMudou(id=carteira.id, action="removida"))
            await db.query(f"UPDATE {FILA} SET assumida_por = NONE, atribuida_a = NONE WHERE tenant = $tenant AND status = 'aberta' "
                           "AND (assumida_por = $p OR atribuida_a = $p)", p=data.user)
        return Empty()

    # ── Clientes ─────────────────────────────────────────────────────────────

    async def clientes(self, data: Empty) -> Clientes:
        """Os clientes da Cogniventure: o plano, quem do staff cuida, o dono (ou o convite pendente), onde cada um está
        na jornada e o último acesso de alguém dele."""
        _gestor()
        organizacoes = [o for o in await _organizacoes() if o.id != settings.platform_tenant]
        carteiras = await db.query(f"SELECT pessoa, organizacao FROM {CARTEIRAS} WHERE tenant = $tenant")
        itens = await asyncio.gather(*(_cliente(o, [c["pessoa"] for c in carteiras if c["organizacao"] == o.id]) for o in organizacoes))
        return Clientes(itens=list(itens))

    async def novo_cliente(self, data: NovoCliente) -> Cliente:
        """A Cogniventure abre o cliente: a organização (sem ninguém dela dentro) com o convite do dono por e-mail, o
        plano e a carteira de quem vai cuidar dele."""
        _gestor()
        await _do_staff(data.pessoa)
        criado = await _identidade(CLIENTE_SUBJECT, ClienteNovo(empresa=data.empresa, email=data.email), ClienteCriado)
        with acting_as(system(SERVICE, criado.tenant)):
            await plans.assign(data.plano)
        if data.valor is not None or data.vencimento is not None:
            await _conta(criado.tenant, ContaAcao(acao="cobranca", valor=data.valor, vencimento=data.vencimento, por=current().sub))
        await self.atribuir_carteira(NovaCarteira(pessoa=data.pessoa, organizacao=criado.tenant))
        return await _cliente(Organizacao(id=criado.tenant, name=criado.name, convite=criado.convite), [data.pessoa])

    async def convidar_dono(self, data: ClienteRef) -> Cliente:
        """O convite do dono de novo, enquanto ele não entrou: o anterior deixa de valer."""
        _gestor()
        await _identidade(CONVITE_DONO_SUBJECT, ConviteDono(tenant=data.organizacao), ConvitePendente)
        organizacao = next((o for o in await _organizacoes() if o.id == data.organizacao), None)
        if organizacao is None:
            raise ServiceError("ERRO_STAFF_ORGANIZACAO", "Organização cliente não encontrada.", 404)
        rows = await db.query(f"SELECT VALUE pessoa FROM {CARTEIRAS} WHERE tenant = $tenant AND organizacao = $o", o=data.organizacao)
        return await _cliente(organizacao, list(rows))

    async def cobranca(self, data: CobrancaCliente) -> Cliente:
        """A mensalidade e o vencimento combinados com o cliente: o fechamento do mês cobra assim."""
        who = _gestor()
        await _conta(data.organizacao, ContaAcao(acao="cobranca", valor=data.valor, vencimento=data.vencimento, por=who.sub))
        return await _um_cliente(data.organizacao)

    async def situacao(self, data: SituacaoCliente) -> Cliente:
        """Suspender o cliente em atraso (nenhuma execução nova começa), reativar quando o pagamento entra, encerrar (no
        fim do mês pago; na hora, se suspenso) ou desfazer o encerramento."""
        who = _gestor()
        await _conta(data.organizacao, ContaAcao(acao=data.acao, motivo=data.motivo, por=who.sub))
        return await _um_cliente(data.organizacao)

    async def encerrada(self, data: ContaEncerrada) -> Empty:
        """events.plans.encerrada (como a organização do cliente): o staff sai da carteira dele (perde o papel operador)
        e o que esperava na fila fecha."""
        if not settings.platform_tenant:
            return Empty()
        organizacao = current_tenant()
        with acting_as(system(SERVICE, settings.platform_tenant)):
            for row in await db.query(f"SELECT * FROM {CARTEIRAS} WHERE tenant = $tenant AND organizacao = $o", o=organizacao):
                carteira = Carteira.model_validate(row)
                try:
                    await _operador(carteira.pessoa, carteira.organizacao, ativo=False)
                except ServiceError as exc:
                    if exc.status != 404:
                        raise
                await db.delete(f"{CARTEIRAS}:{carteira.id}")
                await bus.live(LIVE_CARTEIRAS, CarteiraMudou(id=carteira.id, action="removida"))
            await db.query(f"UPDATE {FILA} SET status = 'concluida', concluida_em = time::now() WHERE tenant = $tenant "
                           "AND organizacao = $o AND status = 'aberta'", o=organizacao)
        return Empty()

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
                    row = await db.merge(_ref(existente[0]), {**dados, "escalada": False, "assumida_por": None, "concluida_em": None,
                                                              "resolvida_por": None})
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
                atual = existente[0]
                row = await db.merge(_ref(atual), {"status": "concluida", "concluida_em": atual.get("concluida_em") or datetime.now(UTC),
                                                   "resolvida_por": atual.get("resolvida_por") or data.por})
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

    # ── Resolver pela fila, sem trocar de organização ───────────────────────

    async def detalhe(self, data: ItemRef) -> FilaDetalhe:
        """O item com o que precisa para resolver ali mesmo: a exceção (campos e contexto), a revisão (o que muda) ou o
        pedido de ajuda (a conversa), perguntados ao serviço do item na organização do cliente."""
        item = await _da_minha_carteira(data.id)
        if item.tipo == "excecao":
            return FilaDetalhe(item=item, tarefa=await _no_cliente(item, FILA_TAREFA_SUBJECT, RefTarefa(id=item.ref), TarefaFila))
        if item.tipo == "revisao":
            return FilaDetalhe(item=item, revisao=await _no_cliente(item, FILA_REVISAO_SUBJECT, RefRevisao(processo=item.ref), RevisaoFila))
        if item.tipo == "pedido":
            return FilaDetalhe(item=item, pedido=await _no_cliente(item, PEDIDO_SUBJECT, ItemRef(id=item.ref), PedidoFila))
        return FilaDetalhe(item=item)  # ajuda no desenho: a conversa é na tela do cliente

    async def resolver(self, data: ResolverExcecao) -> ItemFila:
        """A exceção resolvida pela fila: a saída do passo vai ao processo do cliente como se fosse na tela dele."""
        who = _staff()
        item = await _da_minha_carteira(data.id, tipo="excecao")
        await _no_cliente(item, FILA_RESOLVER_SUBJECT, ResolucaoStaff(id=item.ref, dados=data.dados, comentario=data.comentario,
                                                                       regra=data.regra, por=who.sub), TarefaFila)
        return await _resolvido(item, who.sub)

    async def decidir(self, data: DecidirRevisao) -> ItemFila:
        """A revisão pela fila: aprovar publica a versão; devolver volta para a empresa com o que precisa mudar."""
        who = _staff()
        item = await _da_minha_carteira(data.id, tipo="revisao")
        if not data.aprovar and not data.motivo:
            raise ServiceError("ERRO_STAFF_MOTIVO", "Diga o que precisa mudar para devolver.", 422)
        await _no_cliente(item, FILA_DECIDIR_SUBJECT, DecisaoStaff(processo=item.ref, aprovar=data.aprovar, motivo=data.motivo, por=who.sub),
                          RevisaoFila)
        return await _resolvido(item, who.sub)

    async def responder(self, data: ResponderPedido) -> ItemFila:
        """O pedido de ajuda respondido pela fila: quem pediu é avisado e vê a resposta no histórico."""
        who = _staff()
        item = await _da_minha_carteira(data.id, tipo="pedido")
        await _no_cliente(item, RESPONDER_SUBJECT, RespostaStaff(id=item.ref, texto=data.texto, por=who.sub, por_nome=await _nome_staff(who.sub)),
                          PedidoFila)
        return await _resolvido(item, who.sub)

    async def numeros(self, data: NumerosQuery) -> Numeros:
        """Para o gestor equilibrar as carteiras: por pessoa e por cliente, quantos itens resolveu, quantos no prazo e o
        tempo médio da chegada à resolução, nos últimos N dias."""
        _gestor()
        desde = datetime.now(UTC) - timedelta(days=data.dias)
        rows = await db.query(f"SELECT * FROM {FILA} WHERE tenant = $tenant AND (status = 'aberta' OR concluida_em >= $desde)", desde=desde)
        feitos = [r for r in rows if r["status"] == "concluida" and r.get("concluida_em")]
        pessoas = _linhas(feitos, lambda r: r.get("resolvida_por"))
        clientes = _linhas(feitos, lambda r: r["organizacao"], nomes={r["organizacao"]: r["organizacao_nome"] for r in rows})
        abertos: dict[str, int] = {}
        for r in rows:
            if r["status"] == "aberta":
                abertos[r["organizacao"]] = abertos.get(r["organizacao"], 0) + 1
        clientes = [c.model_copy(update={"abertos": abertos.pop(c.chave, 0)}) for c in clientes]
        clientes += [NumeroLinha(chave=org, nome=next(r["organizacao_nome"] for r in rows if r["organizacao"] == org), resolvidos=0, no_prazo=0,
                                 abertos=n) for org, n in abertos.items()]
        return Numeros(desde=desde, pessoas=pessoas, clientes=sorted(clientes, key=lambda c: (c.nome or "")))

    async def escalar(self, data: Empty) -> Escalados:
        """Agendado (a cada minuto): exceção ou pedido de ajuda aberto que passou do prazo sem ninguém assumir sobe para o
        gestor."""
        if not settings.platform_tenant:
            return Escalados(itens=0)
        with acting_as(system(SERVICE, settings.platform_tenant)):
            rows = await db.query(f"SELECT * FROM {FILA} WHERE tenant = $tenant AND status = 'aberta' AND tipo IN ['excecao', 'pedido'] "
                                  "AND escalada = false AND (assumida_por = NONE OR assumida_por = NULL) AND prazo != NONE "
                                  "AND prazo < time::now()")
            for row in rows:
                item = ItemFila.model_validate(await db.merge(_ref(row), {"escalada": True}))
                await notify.roles("owner", "admin", title=f"Passou do prazo sem dono: {item.titulo}",
                                   body=f"{item.organizacao_nome} · {item.detalhe or 'item para o staff'}", link="/staff",
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
                      ajudas=sum(1 for r in rows if r["tipo"] == "ajuda"), pedidos=sum(1 for r in rows if r["tipo"] == "pedido"),
                      escaladas=sum(1 for r in rows if r.get("escalada")),
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


async def _identidade(subject: str, pedido: Any, resposta: type) -> Any:
    """RPC do staff no svc-identity, agindo na organização da Cogniventure."""
    try:
        with acting_as(system(SERVICE, settings.platform_tenant)):
            return await bus.request(subject, pedido, resposta, timeout=5)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_STAFF_IDENTIDADE", "O serviço de identidade não respondeu. Tente de novo em instantes.", 503) from None


async def _do_staff(pessoa: str) -> None:
    """A pessoa é da Cogniventure? (antes de abrir o cliente: depois, a carteira recusaria com a organização já criada)"""
    try:
        with acting_as(system(SERVICE, settings.platform_tenant)):
            contatos = await bus.request(CONTACTS_SUBJECT, ContactsRequest(users=[pessoa]), Contacts, timeout=5)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_STAFF_IDENTIDADE", "O serviço de identidade não respondeu. Tente de novo em instantes.", 503) from None
    if not any(c.id == pessoa for c in contatos.items):
        raise ServiceError("ERRO_STAFF_PESSOA", "A pessoa não é da equipe da Cogniventure.", 404)


async def apagar_cliente() -> None:
    """A organização do cliente saiu de vez (db.connected(on_purge=...), como ela): a fila e as carteiras dela, que
    ficam na organização da Cogniventure, saem também."""
    organizacao = current_tenant()
    if not settings.platform_tenant or organizacao == settings.platform_tenant:
        return
    with acting_as(system(SERVICE, settings.platform_tenant)):
        await db.query(f"DELETE {FILA} WHERE tenant = $tenant AND organizacao = $o", o=organizacao)
        await db.query(f"DELETE {CARTEIRAS} WHERE tenant = $tenant AND organizacao = $o", o=organizacao)


async def _conta(organizacao: str, acao: ContaAcao) -> ContaCliente:
    """A conta do cliente no svc-plans, agindo nele (só o svc-staff pode)."""
    if organizacao == settings.platform_tenant or not any(o.id == organizacao for o in await _organizacoes()):
        raise ServiceError("ERRO_STAFF_ORGANIZACAO", "Organização cliente não encontrada.", 404)
    try:
        with acting_as(system(SERVICE, organizacao)):
            return await bus.request(CONTA_SUBJECT, acao, ContaCliente, timeout=10)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_STAFF_PLANOS", "O serviço de planos não respondeu. Tente de novo em instantes.", 503) from None


async def _um_cliente(organizacao_id: str) -> Cliente:
    organizacao = next((o for o in await _organizacoes() if o.id == organizacao_id), None)
    if organizacao is None:
        raise ServiceError("ERRO_STAFF_ORGANIZACAO", "Organização cliente não encontrada.", 404)
    rows = await db.query(f"SELECT VALUE pessoa FROM {CARTEIRAS} WHERE tenant = $tenant AND organizacao = $o", o=organizacao_id)
    return await _cliente(organizacao, list(rows))


async def _cliente(organizacao: Organizacao, responsaveis: list[str]) -> Cliente:
    """Um cliente na lista: o que a identidade sabe, mais o plano, a conta e o passo da jornada, perguntados como ele."""
    cliente = Cliente(organizacao=organizacao.id, nome=organizacao.name, created_at=organizacao.created_at, responsaveis=responsaveis,
                      dono=organizacao.dono, convite=organizacao.convite, ultimo_acesso=organizacao.ultimo_acesso)
    with acting_as(system(SERVICE, organizacao.id)):
        limites = await plans.limits()
        cliente.plano = limites.plan_name if limites.plan else None
        try:
            cliente.conta = await bus.request(CONTA_SUBJECT, ContaAcao(acao="ver"), ContaCliente, timeout=5)
        except (NatsError, TimeoutError, ServiceError):
            cliente.conta = None
        if organizacao.dono is None:
            cliente.passo = "convite"
            return cliente
        try:
            contexto = await bus.request(CONTEXTO_SUBJECT, Empty(), ContextoEmpresa, timeout=5)
            a = await bus.request(ACOMPANHAMENTO_SUBJECT, Empty(), Acompanhamento, timeout=5)
        except (NatsError, TimeoutError, ServiceError):
            return cliente  # sem resposta agora: o passo fica em branco, o resto aparece
    cliente.andamento, cliente.autonomia = a.andamento, a.autonomia
    cliente.passo = ("briefing" if contexto.concluido_em is None else "descoberta" if not a.aceitos
                     else "desenho" if not a.publicados else "acompanhamento")
    return cliente


async def _da_minha_carteira(item_id: str, tipo: str | None = None) -> ItemFila:
    """O item existe, é do tipo pedido e da carteira de quem pede (o gestor alcança todos)."""
    who = _staff()
    item = await _item(item_id)
    if tipo is not None and item.tipo != tipo:
        raise ServiceError("ERRO_STAFF_TIPO", "Este item não se resolve assim.", 409)
    if not GESTORES & who.roles:
        rows = await db.query(f"SELECT id FROM {CARTEIRAS} WHERE tenant = $tenant AND pessoa = $p AND organizacao = $o LIMIT 1",
                              p=who.sub, o=item.organizacao)
        if not rows:
            raise ServiceError("ERRO_STAFF_FORBIDDEN", "Esta organização não está na sua carteira.", 403)
    if item.status != "aberta" and tipo is not None:
        raise ServiceError("ERRO_STAFF_RESOLVIDO", "Este item já foi resolvido.", 409)
    return item


async def _no_cliente(item: ItemFila, subject: str, pedido: Any, resposta: type) -> Any:
    """RPC ao serviço do item, agindo na organização do cliente (só o svc-staff pode)."""
    try:
        with acting_as(system(SERVICE, item.organizacao)):
            return await bus.request(subject, pedido, resposta, timeout=15)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_STAFF_CLIENTE", "O serviço deste item não respondeu. Tente de novo em instantes.", 503) from None


async def _resolvido(item: ItemFila, pessoa: str) -> ItemFila:
    """Fecha o item na hora (o aviso do serviço do item chega depois e confirma)."""
    row = await db.merge(f"{FILA}:{item.id}", {"status": "concluida", "concluida_em": datetime.now(UTC), "resolvida_por": pessoa})
    await bus.live(LIVE_FILA, FilaMudou(id=item.id, action="mudou"))
    return ItemFila.model_validate(row)


async def _nome_staff(pessoa: str) -> str | None:
    try:
        with acting_as(system(SERVICE, settings.platform_tenant)):
            contatos = await bus.request(CONTACTS_SUBJECT, ContactsRequest(users=[pessoa]), Contacts, timeout=5)
    except (NatsError, TimeoutError, ServiceError):
        return None
    return next((c.name for c in contatos.items if c.id == pessoa), None)


def _linhas(feitos: list[dict[str, Any]], chave: Any, nomes: dict[str, str] | None = None) -> list[NumeroLinha]:
    grupos: dict[str, list[dict[str, Any]]] = {}
    for r in feitos:
        if k := chave(r):
            grupos.setdefault(k, []).append(r)
    linhas = []
    for k, itens in grupos.items():
        tempos = [(_quando(r["concluida_em"]) - _quando(r["created_at"])).total_seconds() / 60 for r in itens if r.get("created_at")]
        no_prazo = sum(1 for r in itens if not r.get("prazo") or _quando(r["concluida_em"]) <= _quando(r["prazo"]))
        linhas.append(NumeroLinha(chave=k, nome=(nomes or {}).get(k), resolvidos=len(itens), no_prazo=no_prazo,
                                  tempo_medio_min=round(sum(tempos) / len(tempos), 1) if tempos else None))
    return sorted(linhas, key=lambda linha: -linha.resolvidos)


def _quando(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    data = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    return data if data.tzinfo else data.replace(tzinfo=UTC)
