"""svc-vendas · lógica de negócio pura. Fonte da verdade: specs/vendas.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py. As ações do pacote (schemas.ACTIONS) são métodos de mesmo nome: o worker do motor de processos
(core/processes.py) as chama como a organização do processo. Leads e pedidos de proposta que chegam aqui iniciam os
processos deles (processes.emit). E-mails saem pela caixa de entrada da organização (svc-integracoes).
"""
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from nats.errors import Error as NatsError
from pydantic import ValidationError

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import notify
from core.processes import Handoff, processes
from core.resources import ResourceRef, resources
from core.security import acting_as, current, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    CLIENTES,
    EMAIL_SUBJECT,
    FOLLOW_UPS,
    HORARIOS,
    INATIVIDADE_PADRAO,
    LEADS,
    LIVE_PROPOSTAS,
    PROPOSTAS,
    SERVICE,
    VALIDADE_DIAS,
    WRITERS,
    Campanha,
    CampanhaEnviada,
    Cliente,
    Desfecho,
    EmailEnviado,
    Empty,
    EnviarEmail,
    FollowUps,
    Inatividade,
    Inativos,
    Lead,
    LeadIn,
    LeadItem,
    LeadRef,
    LeadRegistrado,
    Nutricao,
    PedidoProposta,
    Proposta,
    PropostaEnviada,
    PropostaIn,
    PropostaMontada,
    PropostaMudou,
    PropostaPage,
    PropostaQuery,
    PropostaRef,
    ReceberLead,
    RespostaIn,
    Reuniao,
)

MIGRATIONS: list[Migration] = []


@activities("vendas")
class VendasService:
    # ── Rotas: o que chega e inicia os processos ─────────────────────────────

    async def receber_lead(self, data: ReceberLead) -> LeadItem:
        """Um lead chegou (registrado na tela; os canais de site e WhatsApp entram aqui quando forem integrados): entra
        como novo e o processo de qualificação começa."""
        _escritor()
        item = await resources.create(LEADS, Lead(nome=data.nome, email=data.email, telefone=data.telefone, origem=data.origem,
                                                  interesse=data.interesse))
        await processes.emit("lead", {"lead_id": item.id, "nome": item.nome, "email": item.email, "telefone": item.telefone,
                                      "origem": item.origem, "interesse": item.interesse, "resumo": f"Lead: {item.nome}"}, key=item.id)
        return item

    async def propostas(self, data: PropostaQuery) -> PropostaPage:
        return await db.page(PROPOSTAS, data, PropostaPage)

    async def pedir_proposta(self, data: PedidoProposta) -> Proposta:
        """Um pedido de proposta: entra como pedida e o processo de proposta comercial começa."""
        _escritor()
        row = await db.create(PROPOSTAS, {"cliente": data.cliente, "email": data.email, "pedido": data.pedido, "status": "pedida", "follow_ups": []})
        proposta = Proposta.model_validate(row)
        await processes.emit("pedido_proposta", {"proposta_id": proposta.id, "cliente": proposta.cliente, "email": proposta.email,
                                                 "pedido": proposta.pedido, "resumo": f"Proposta para {proposta.cliente}"}, key=proposta.id)
        await bus.live(LIVE_PROPOSTAS, PropostaMudou(id=proposta.id, action="pedida"))
        return proposta

    # ── Qualificação de leads (o motor chama) ────────────────────────────────

    async def registrar_lead(self, data: LeadIn) -> LeadRegistrado:
        """Com lead_id, o lead já está no CRM; sem, entra (o mesmo e-mail não duplica)."""
        if data.lead_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", data.lead_id) and await db.select(f"{LEADS.table}:{data.lead_id}"):
            return LeadRegistrado(lead_id=data.lead_id, novo=True)
        if not data.nome:
            raise Handoff("O lead chegou sem nome: veja a mensagem original e registre o lead.")
        if data.email:
            rows = await db.query(f"SELECT id FROM {LEADS.table} WHERE tenant = $tenant AND string::lowercase(email ?? '') = $e LIMIT 1",
                                  e=data.email.strip().lower())
            if rows:
                return LeadRegistrado(lead_id=_chave(rows[0]["id"]), novo=False)
        origem = data.origem if data.origem in ("site", "instagram", "whatsapp", "indicacao") else "outro"
        campos = {"nome": data.nome[:200], "email": data.email or None, "telefone": data.telefone or None, "origem": origem,
                  "interesse": (data.interesse or None) and data.interesse[:2000]}
        try:
            lead = Lead.model_validate(campos)
        except ValidationError:  # e-mail ou telefone fora do formato (veio de um canal de fora): o lead entra sem eles
            lead = Lead.model_validate({**campos, "email": None, "telefone": None})
        item = await resources.create(LEADS, lead)
        return LeadRegistrado(lead_id=item.id, novo=True)

    async def agendar_reuniao(self, data: LeadRef) -> Reuniao:
        """O próximo horário livre (dia útil, das 10h às 16h, um lead por hora), com convite por e-mail ao lead e aviso
        à empresa."""
        lead = await _lead(data.lead_id)
        ocupados = {str(r["reuniao_em"])[:16].replace("T", " ") for r in await db.query(
            f"SELECT reuniao_em FROM {LEADS.table} WHERE tenant = $tenant AND reuniao_em != NONE AND reuniao_em != NULL")}
        quando = _proximo_horario(ocupados)
        await resources.update(LEADS, LEADS.update(id=lead.id, status="reuniao", reuniao_em=quando.replace(tzinfo=UTC)))
        rotulo = quando.strftime("%d/%m/%Y às %H:%M")
        await notify.roles("owner", "admin", title=f"Reunião com {lead.nome}: {rotulo}", body=data.resumo or (lead.interesse or ""),
                           link="/vendas/leads", key=f"reuniao-{lead.id}")
        if lead.email:
            texto = (f"Olá, {lead.nome}!\n\nObrigado pelo contato. Marcamos uma conversa com o nosso time em {rotulo}"
                     + (f" sobre: {data.resumo}" if data.resumo else "") + ".\n\nSe o horário não for bom, é só responder este e-mail.")
            try:
                await _email(lead.email, "Nossa conversa", texto)
            except ServiceError as exc:
                if exc.status >= 500:
                    raise
                raise Handoff(f"Reunião marcada para {rotulo}, mas o convite não saiu ({exc.message}): avise {lead.nome} e confirme.") from None
        return Reuniao(reuniao_em=quando.strftime("%Y-%m-%d %H:%M"))

    async def nutrir(self, data: LeadRef) -> Nutricao:
        lead = await _lead(data.lead_id)
        await resources.update(LEADS, LEADS.update(id=lead.id, status="nutricao"))
        return Nutricao(status="nutricao")

    # ── Proposta comercial ───────────────────────────────────────────────────

    async def registrar_proposta(self, data: PropostaIn) -> PropostaMontada:
        """A proposta montada pelo agente do processo (o que, quanto e o desconto), com validade de 15 dias."""
        proposta = await _proposta(data.proposta_id)
        if not data.descricao or data.valor is None or data.valor <= 0:
            raise Handoff("A proposta veio sem descrição ou sem valor: complete antes de enviar.")
        validade = (date.today() + timedelta(days=VALIDADE_DIAS)).isoformat()
        await db.merge(f"{PROPOSTAS}:{proposta.id}", {"descricao": data.descricao[:3000], "valor": round(data.valor, 2),
                                                      "desconto": data.desconto or 0, "validade": validade, "status": "montada",
                                                      "cliente": data.cliente or proposta.cliente, "email": data.email or proposta.email})
        await bus.live(LIVE_PROPOSTAS, PropostaMudou(id=proposta.id, action="montada"))
        return PropostaMontada(proposta_id=proposta.id, validade=validade)

    async def enviar_proposta(self, data: PropostaRef) -> PropostaEnviada:
        proposta = await _proposta(data.proposta_id)
        if not proposta.email:
            raise Handoff(f"A proposta para {proposta.cliente} não tem e-mail: envie por outro canal e confirme o envio.")
        desconto = f" (já com {proposta.desconto:g}% de desconto)" if proposta.desconto else ""
        texto = (f"Olá, {proposta.cliente}!\n\nConforme o seu pedido, segue a nossa proposta:\n\n{proposta.descricao}\n\n"
                 f"Valor total: {_reais(proposta.valor or 0)}{desconto}\nVálida até {_data_br(proposta.validade)}.\n\n"
                 "Para aceitar, é só responder este e-mail.")
        await _email(proposta.email, f"Proposta comercial para {proposta.cliente}"[:200], texto)
        await db.merge(f"{PROPOSTAS}:{proposta.id}", {"status": "enviada", "enviada_em": datetime.now(UTC)})
        await bus.live(LIVE_PROPOSTAS, PropostaMudou(id=proposta.id, action="enviada"))
        return PropostaEnviada(enviada_em=date.today().isoformat())

    async def registrar_resposta(self, data: RespostaIn) -> Desfecho:
        """A resposta do cliente fecha a proposta; a aceita vira cliente com a compra de hoje (e o gatilho por processo
        inicia o contrato e o faturamento)."""
        proposta = await _proposta(data.proposta_id)
        if data.aprovado is None:
            raise Handoff("Não veio a resposta do cliente (aceitou ou não) para fechar a proposta.")
        status = "aceita" if data.aprovado else "recusada"
        await db.merge(f"{PROPOSTAS}:{proposta.id}", {"status": status, "respondida_em": datetime.now(UTC)})
        if data.aprovado:
            await _cliente_comprou(proposta)
        await bus.live(LIVE_PROPOSTAS, PropostaMudou(id=proposta.id, action=status))
        return Desfecho(status=status, aceita=data.aprovado)

    # ── Reativação de carteira ───────────────────────────────────────────────

    async def selecionar_inativos(self, data: Inatividade) -> Inativos:
        inativos = await _inativos(data.dias_sem_comprar)
        return Inativos(clientes=len(inativos), nomes=", ".join(c["nome"] for c in inativos)[:1000])

    async def enviar_campanha(self, data: Campanha) -> CampanhaEnviada:
        """A mensagem da campanha vai a cada cliente parado com e-mail; cada envio grava a data (a próxima campanha não
        repete dentro do período)."""
        if not data.mensagem:
            raise Handoff("A campanha veio sem mensagem.")
        enviados = 0
        for cliente in await _inativos(data.dias_sem_comprar):
            if not cliente.get("email"):
                continue
            await _email(cliente["email"], "Sentimos sua falta", f"Olá, {cliente['nome']}!\n\n{data.mensagem}")
            await resources.update(CLIENTES, CLIENTES.update(id=_chave(cliente["id"]), campanha_em=date.today()))
            enviados += 1
        return CampanhaEnviada(enviados=enviados)

    # ── Agendamento: follow-ups das propostas sem resposta ───────────────────

    async def follow_up(self, data: Empty) -> FollowUps:
        """Agendado (todo dia): proposta enviada e sem resposta há 3 e há 7 dias recebe um follow-up, cada um uma vez."""
        enviados = 0
        agora = datetime.now(UTC)
        for org in await db.tenants(PROPOSTAS):
            with acting_as(system(SERVICE, org)):
                rows = await db.query(f"SELECT * FROM {PROPOSTAS} WHERE tenant = $tenant AND status = 'enviada'")
                for proposta in (Proposta.model_validate(r) for r in rows):
                    if not proposta.email or not proposta.enviada_em:
                        continue
                    dias = (agora - (proposta.enviada_em if proposta.enviada_em.tzinfo else proposta.enviada_em.replace(tzinfo=UTC))).days
                    etapa = next((nome for nome, apos in sorted(FOLLOW_UPS.items(), key=lambda x: -x[1]) if dias >= apos), None)
                    if etapa is None or etapa in proposta.follow_ups:
                        continue
                    texto = (f"Olá, {proposta.cliente}!\n\nConseguiu ver a nossa proposta ({_reais(proposta.valor or 0)}, válida até "
                             f"{_data_br(proposta.validade)})? Ficamos à disposição para ajustar o que for preciso.")
                    try:
                        await _email(proposta.email, f"Sobre a nossa proposta para {proposta.cliente}"[:200], texto)
                    except ServiceError:
                        continue  # sem caixa de entrada ou sem provedor: tenta no dia seguinte
                    await db.merge(f"{PROPOSTAS}:{proposta.id}", {"follow_ups": [*proposta.follow_ups, etapa]})
                    await bus.live(LIVE_PROPOSTAS, PropostaMudou(id=proposta.id, action="follow_up"))
                    enviados += 1
        return FollowUps(enviados=enviados)


def _escritor() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_VENDAS_FORBIDDEN", "Só donos, administradores e operadores registram isto.", 403)


def _chave(value: Any) -> str:
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else str(value)


async def _lead(lead_id: str | None) -> Any:
    if not lead_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", lead_id):
        raise Handoff("O processo não trouxe o lead.")
    try:
        return await resources.get(LEADS, ResourceRef(id=lead_id))
    except ServiceError as exc:
        if exc.status == 404:
            raise Handoff("O lead não está mais no CRM.") from None
        raise


async def _proposta(proposta_id: str | None) -> Proposta:
    row = await db.select(f"{PROPOSTAS}:{proposta_id}") if proposta_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", proposta_id) else None
    if row is None:
        raise Handoff("A proposta não foi encontrada.")
    return Proposta.model_validate(row)


async def _cliente_comprou(proposta: Proposta) -> None:
    """A proposta aceita: o cliente (pelo e-mail, senão pelo nome) fica com a compra de hoje; novo, entra no cadastro."""
    if proposta.email:
        rows = await db.query(f"SELECT id FROM {CLIENTES.table} WHERE tenant = $tenant AND string::lowercase(email ?? '') = $e LIMIT 1",
                              e=proposta.email.lower())
    else:
        rows = await db.query(f"SELECT id FROM {CLIENTES.table} WHERE tenant = $tenant AND string::lowercase(nome) = $n LIMIT 1",
                              n=proposta.cliente.lower())
    if rows:
        await resources.update(CLIENTES, CLIENTES.update(id=_chave(rows[0]["id"]), ultima_compra=date.today()))
    else:
        await resources.create(CLIENTES, Cliente(nome=proposta.cliente, email=proposta.email, ultima_compra=date.today()))


async def _inativos(dias: int | None) -> list[dict[str, Any]]:
    """Clientes com a última compra há mais dos dias pedidos e sem campanha nesse período."""
    limite = (date.today() - timedelta(days=dias if dias is not None else INATIVIDADE_PADRAO)).isoformat()
    rows = await db.query(f"SELECT * FROM {CLIENTES.table} WHERE tenant = $tenant AND ultima_compra != NONE AND ultima_compra != NULL "
                          "ORDER BY nome")
    return [r for r in rows if str(r["ultima_compra"])[:10] < limite and not (r.get("campanha_em") and str(r["campanha_em"])[:10] >= limite)]


def _proximo_horario(ocupados: set[str]) -> datetime:
    """O primeiro horário livre a partir de amanhã: dia útil, das 10h às 16h."""
    dia = date.today() + timedelta(days=1)
    while True:
        if dia.weekday() < 5:
            for hora in HORARIOS:
                quando = datetime.combine(dia, time(hora, 0))
                if quando.strftime("%Y-%m-%d %H:%M") not in ocupados:
                    return quando
        dia += timedelta(days=1)


async def _email(para: str, assunto: str, texto: str) -> None:
    """E-mail pela caixa de entrada da organização (svc-integracoes). Sem a conexão ou sem provedor: o 409 de lá vira
    a exceção do staff; fora do ar: 503 (o motor tenta de novo)."""
    try:
        await bus.request(EMAIL_SUBJECT, EnviarEmail(para=para, assunto=assunto, texto=texto), EmailEnviado, timeout=15)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_VENDAS_INTEGRACOES_FORA", "O serviço de integrações não respondeu.", 503) from None


def _reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(valor: str | None) -> str:
    return "/".join(reversed(valor.split("-"))) if valor and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor) else (valor or "-")
