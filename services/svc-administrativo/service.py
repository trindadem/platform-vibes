"""svc-administrativo · lógica de negócio pura. Fonte da verdade: specs/administrativo.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py. As ações do pacote (schemas.ACTIONS) são métodos de mesmo nome: o worker do motor de processos
(core/processes.py) as chama como a organização do processo. Admissões e requisições que a empresa registra aqui
iniciam os processos delas (processes.emit). E-mails saem pela caixa de entrada da organização (svc-integracoes).
"""
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import notify
from core.processes import Handoff, processes
from core.resources import ResourceRef, resources
from core.security import current
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    ANTECEDENCIA_PADRAO,
    COLABORADORES,
    DOCUMENTOS_ADMISSAO,
    EMAIL_SUBJECT,
    FORNECEDORES,
    LIVE_REQUISICOES,
    REQUISICOES,
    VENCIMENTOS,
    WRITERS,
    Acessos,
    Admissao,
    Admitido,
    Antecedencia,
    Assinado,
    Colaborador,
    ColaboradorItem,
    Comparacao,
    EmailEnviado,
    Encerrada,
    Encerramento,
    EnviarEmail,
    Esocial,
    Exame,
    IndicatorRequest,
    IndicatorValues,
    NovaAdmissao,
    NovaCotacao,
    NovaRequisicao,
    PedidoCompra,
    PedidoCotacao,
    PedidoDocumentos,
    PedidoIn,
    Requisicao,
    RequisicaoIn,
    RequisicaoMudou,
    RequisicaoPage,
    RequisicaoQuery,
    RequisicaoRef,
    Vencimentos,
)

MIGRATIONS: list[Migration] = []


@activities("administrativo")
class AdministrativoService:
    # ── Rotas: o que a empresa registra e inicia os processos ────────────────

    async def admitir(self, data: NovaAdmissao) -> ColaboradorItem:
        """A contratação foi aprovada: o colaborador entra em admissão e o processo de admissão começa."""
        _escritor()
        item = await resources.create(COLABORADORES, Colaborador(nome=data.nome, email=data.email, cargo=data.cargo, salario=data.salario,
                                                                 inicio=data.inicio, status="admissao"))
        await processes.emit("admissao", {"colaborador_id": item.id, "colaborador": item.nome, "email": item.email, "cargo": item.cargo,
                                          "inicio": item.inicio.isoformat() if item.inicio else None, "resumo": f"Admissão de {item.nome}"},
                             key=item.id)
        return item

    async def requisicoes(self, data: RequisicaoQuery) -> RequisicaoPage:
        return await db.page(REQUISICOES, data, RequisicaoPage)

    async def requisitar(self, data: NovaRequisicao) -> Requisicao:
        """Uma requisição de compra: entra aberta e o processo de compras e cotação começa."""
        _escritor()
        row = await db.create(REQUISICOES, {"item": data.item, "quantidade": data.quantidade, "categoria": data.categoria,
                                            "observacao": data.observacao, "status": "aberta", "cotacoes": []})
        requisicao = Requisicao.model_validate(row)
        quantidade = f"{requisicao.quantidade:g}"
        await processes.emit("requisicao", {"requisicao_id": requisicao.id, "item": requisicao.item, "quantidade": requisicao.quantidade,
                                            "categoria": requisicao.categoria, "resumo": f"Requisição: {quantidade} × {requisicao.item}"},
                             key=requisicao.id)
        await bus.live(LIVE_REQUISICOES, RequisicaoMudou(id=requisicao.id, action="aberta"))
        return requisicao

    async def registrar_cotacao(self, data: NovaCotacao) -> Requisicao:
        """Uma cotação que chegou (por e-mail ou telefone) entra na requisição: comparar escolhe entre elas."""
        _escritor()
        requisicao = await _requisicao(data.requisicao, erro=True)
        cotacoes = [c.model_dump() for c in requisicao.cotacoes if c.fornecedor.lower() != data.fornecedor.lower()]
        cotacoes.append({"fornecedor": data.fornecedor, "valor": data.valor, "prazo_dias": data.prazo_dias})
        requisicao = Requisicao.model_validate(await db.merge(f"{REQUISICOES}:{requisicao.id}", {"cotacoes": cotacoes}))
        await bus.live(LIVE_REQUISICOES, RequisicaoMudou(id=requisicao.id, action="cotacao"))
        return requisicao

    # ── Ações da admissão (o motor chama) ────────────────────────────────────

    async def pedir_documentos(self, data: Admissao) -> PedidoDocumentos:
        """Pede ao novo colaborador os documentos da admissão, por e-mail, com resposta para a caixa de entrada."""
        colaborador = await _colaborador(data)
        if not colaborador.email:
            raise Handoff(f"{colaborador.nome} não tem e-mail: peça os documentos por outro canal e confirme o envio.")
        lista = "\n".join(f"- {d}" for d in DOCUMENTOS_ADMISSAO)
        texto = (f"Olá, {colaborador.nome}.\n\nBem-vindo(a)! Para a sua admissão{' como ' + colaborador.cargo if colaborador.cargo else ''}, "
                 f"responda este e-mail com fotos ou PDFs de:\n\n{lista}\n\nQualquer dúvida, é só responder.")
        await _email(colaborador.email, "Documentos para a sua admissão", texto)
        return PedidoDocumentos(enviado_em=date.today().isoformat())

    async def enviar_esocial(self, data: Admissao) -> Esocial:
        """A folha e o eSocial ainda não têm integração (briefing.md §14, decisão 6): o staff lança a admissão e
        informa o recibo do evento S-2200."""
        colaborador = await _colaborador(data)
        raise Handoff(f"O envio ao eSocial ainda não tem integração: lance a admissão de {colaborador.nome} (S-2200) na folha "
                      "e informe o recibo.")

    async def coletar_assinatura(self, data: Admissao) -> Assinado:
        """A assinatura eletrônica ainda não tem integração (decisão 6): o staff colhe e informa a data."""
        colaborador = await _colaborador(data)
        raise Handoff(f"A assinatura eletrônica ainda não tem integração: envie o contrato de trabalho a {colaborador.nome}"
                      + (f" ({colaborador.email})" if colaborador.email else "") + " e informe a data em que foi assinado.")

    async def agendar_exame(self, data: Admissao) -> Exame:
        """O exame admissional no primeiro dia útil a partir de amanhã, às 9h (antes do início, sempre que der)."""
        colaborador = await _colaborador(data)
        dia = date.today() + timedelta(days=1)
        while dia.weekday() >= 5:
            dia += timedelta(days=1)
        quando = datetime.combine(dia, time(9, 0))
        await resources.update(COLABORADORES, COLABORADORES.update(id=colaborador.id, exame_em=quando.replace(tzinfo=UTC)))
        await notify.roles("owner", "admin", title=f"Exame admissional de {colaborador.nome}",
                           body=f"Marcado para {quando.strftime('%d/%m/%Y às %H:%M')}.", link="/administrativo",
                           key=f"exame-{colaborador.id}")
        return Exame(exame_em=quando.strftime("%Y-%m-%d %H:%M"))

    async def criar_acessos(self, data: Admissao) -> Acessos:
        """Os acessos que o cargo pede (e-mail da empresa sempre); a lista fica no colaborador e vai para a empresa."""
        colaborador = await _colaborador(data)
        cargo = (colaborador.cargo or "").lower()
        acessos = ["E-mail da empresa"]
        for chave, acesso in (("vend", "CRM e WhatsApp da empresa"), ("comerc", "CRM e WhatsApp da empresa"), ("financ", "Banco (consulta)"),
                              ("gerent", "Relatórios gerenciais"), ("gest", "Relatórios gerenciais"), ("atend", "WhatsApp da empresa")):
            if chave in cargo and acesso not in acessos:
                acessos.append(acesso)
        if len(acessos) == 1:
            acessos.append("Sistema da empresa")
        texto = "; ".join(acessos)
        await resources.update(COLABORADORES, COLABORADORES.update(id=colaborador.id, acessos=texto))
        await notify.roles("owner", "admin", title=f"Acessos de {colaborador.nome}", body=texto, link="/administrativo",
                           key=f"acessos-{colaborador.id}")
        return Acessos(acessos=texto)

    async def concluir_admissao(self, data: Admissao) -> Admitido:
        colaborador = await _colaborador(data)
        await resources.update(COLABORADORES, COLABORADORES.update(id=colaborador.id, status="ativo"))
        await notify.roles("owner", "admin", title=f"{colaborador.nome} admitido(a)", body="Documentos, eSocial, contrato, exame e acessos prontos.",
                           link="/administrativo", key=f"admitido-{colaborador.id}")
        return Admitido(status="ativo")

    # ── Ações de compras e cotação ───────────────────────────────────────────

    async def pedir_cotacoes(self, data: RequisicaoIn) -> PedidoCotacao:
        """Pede cotação por e-mail aos fornecedores da categoria (sem categoria, a todos com e-mail)."""
        requisicao = await _requisicao(data.requisicao_id)
        fornecedores = [f for f in await _fornecedores() if f.get("email")]
        if requisicao.categoria:
            da_categoria = [f for f in fornecedores if (f.get("categoria") or "").strip().lower() == requisicao.categoria.strip().lower()]
            fornecedores = da_categoria or fornecedores
        if not fornecedores:
            raise Handoff("Nenhum fornecedor com e-mail para cotar: cadastre fornecedores em Administrativo ou peça as cotações por telefone.")
        texto = (f"Olá!\n\nPodem nos enviar uma cotação de {requisicao.quantidade:g} × {requisicao.item}"
                 + (f" ({requisicao.observacao})" if requisicao.observacao else "") + ", com o valor total e o prazo de entrega?\n\nObrigado!")
        for fornecedor in fornecedores:
            await _email(fornecedor["email"], f"Pedido de cotação: {requisicao.item}"[:200], texto)
        await db.merge(f"{REQUISICOES}:{requisicao.id}", {"status": "cotando"})
        await bus.live(LIVE_REQUISICOES, RequisicaoMudou(id=requisicao.id, action="cotando"))
        return PedidoCotacao(fornecedores=len(fornecedores))

    async def comparar_cotacoes(self, data: RequisicaoRef) -> Comparacao:
        """A de menor valor entre as cotações que chegaram; nenhuma → o staff cobra os fornecedores."""
        requisicao = await _requisicao(data.requisicao_id)
        if not requisicao.cotacoes:
            raise Handoff(f"Nenhum fornecedor respondeu à cotação de {requisicao.item}: cobre os fornecedores e registre as cotações na requisição.")
        melhor = min(requisicao.cotacoes, key=lambda c: c.valor)
        await db.merge(f"{REQUISICOES}:{requisicao.id}", {"melhor_fornecedor": melhor.fornecedor, "melhor_valor": melhor.valor})
        return Comparacao(recebidas=len(requisicao.cotacoes), melhor_fornecedor=melhor.fornecedor, melhor_valor=melhor.valor,
                          prazo_dias=melhor.prazo_dias)

    async def emitir_pedido(self, data: PedidoIn) -> PedidoCompra:
        """O pedido de compra ao fornecedor escolhido, por e-mail, com o número PC-<ano>-<sequência>."""
        requisicao = await _requisicao(data.requisicao_id)
        nome = data.melhor_fornecedor or requisicao.melhor_fornecedor
        fornecedor = next((f for f in await _fornecedores() if nome and f["nome"].lower() == nome.lower()), None)
        if fornecedor is None or not fornecedor.get("email"):
            raise Handoff(f"O fornecedor {nome or '(sem nome)'} não tem e-mail no cadastro: envie o pedido por outro canal e informe o número.")
        ano = date.today().year
        emitidos = await db.query(f"SELECT count() AS n FROM {REQUISICOES} WHERE tenant = $tenant AND string::starts_with(pedido_numero ?? '', $p) GROUP ALL",
                                  p=f"PC-{ano}-")
        numero = f"PC-{ano}-{(emitidos[0]['n'] if emitidos else 0) + 1:04d}"
        valor = data.melhor_valor or requisicao.melhor_valor or 0
        texto = (f"Olá!\n\nFechamos a compra de {requisicao.quantidade:g} × {requisicao.item} pelo valor total de "
                 f"{_reais(valor)}.\nPedido {numero}. Por favor, mande a nota fiscal para este e-mail.\n\nObrigado!")
        await _email(fornecedor["email"], f"Pedido de compra {numero}", texto)
        await db.merge(f"{REQUISICOES}:{requisicao.id}", {"status": "pedido", "pedido_numero": numero, "pedido_em": datetime.now(UTC)})
        await bus.live(LIVE_REQUISICOES, RequisicaoMudou(id=requisicao.id, action="pedido"))
        return PedidoCompra(pedido_numero=numero)

    async def encerrar_requisicao(self, data: Encerramento) -> Encerrada:
        """A empresa não aprovou a compra: a requisição fica cancelada."""
        requisicao = await _requisicao(data.requisicao_id)
        await db.merge(f"{REQUISICOES}:{requisicao.id}", {"status": "cancelada"})
        await bus.live(LIVE_REQUISICOES, RequisicaoMudou(id=requisicao.id, action="cancelada"))
        return Encerrada(status="cancelada")

    # ── Vencimentos da empresa ───────────────────────────────────────────────

    async def verificar_vencimentos(self, data: Antecedencia) -> Vencimentos:
        """O que vence dentro da antecedência e ainda não foi avisado para este vencimento: um aviso só para a empresa,
        e cada item fica com a data do aviso (renovar = mudar o vencimento, que volta a ser vigiado)."""
        antecedencia = data.antecedencia_dias if data.antecedencia_dias is not None else ANTECEDENCIA_PADRAO
        hoje = date.today()
        limite = hoje + timedelta(days=antecedencia)
        rows = await db.query(f"SELECT * FROM {VENCIMENTOS.table} WHERE tenant = $tenant ORDER BY vence_em")
        proximos = []
        for row in rows:
            vence = _data(row.get("vence_em"))
            avisado = _data(row.get("avisado_em"))
            if vence is None or vence > limite or (avisado and avisado >= vence - timedelta(days=antecedencia)):
                continue
            proximos.append((row, vence))
        if not proximos:
            return Vencimentos(proximos=0, exige_presenca=0, resumo="Nada vence nos próximos dias.")
        for row, _ in proximos:
            await resources.update(VENCIMENTOS, VENCIMENTOS.update(id=_chave(row["id"]), avisado_em=hoje))
        linhas = [f"{row['nome']}: {'venceu' if vence < hoje else 'vence'} em {vence.strftime('%d/%m/%Y')}"
                  + (" (exige vistoria ou presença)" if row.get("exige_vistoria") else "") for row, vence in proximos]
        resumo = "; ".join(linhas)
        await notify.roles("owner", "admin", title=f"{len(proximos)} vencimento(s) da empresa chegando", body="\n".join(linhas),
                           link="/administrativo/vencimentos", key=f"vencimentos-{hoje.isoformat()}")
        return Vencimentos(proximos=len(proximos), exige_presenca=sum(1 for row, _ in proximos if row.get("exige_vistoria")), resumo=resumo[:1000])

    # ── Indicadores "pacote" (rpc.administrativo.indicadores; o svc-processos pede como system na organização) ──

    async def indicadores(self, data: IndicatorRequest) -> IndicatorValues:
        """O que as execuções não sabem: pedidos de compra que saíram no mês, a economia nas cotações deles e os
        vencimentos que passaram sem renovação até o corte (o fim do mês; no corrente, hoje). Desconhecido ou mês que
        ainda não começou: null."""
        janela = data.janela()
        valores: dict[str, float | None] = {nome: None for nome in data.nomes}
        if janela is None:
            return IndicatorValues(valores=valores)
        if data.modelo == "compras-cotacao" and {"pedidos_emitidos", "economia_cotacoes"} & set(data.nomes):
            pedidos = await _pedidos_do_mes(janela.inicio, janela.fim)
            economia = sum(max(c.valor for c in r.cotacoes) - (r.melhor_valor if r.melhor_valor is not None else min(c.valor for c in r.cotacoes))
                           for r in pedidos if len(r.cotacoes) >= 2)
            valores |= {k: v for k, v in (("pedidos_emitidos", float(len(pedidos))), ("economia_cotacoes", round(economia, 2))) if k in data.nomes}
        if data.modelo == "vencimentos-empresa" and "vencidos_sem_renovacao" in data.nomes:
            valores["vencidos_sem_renovacao"] = await _vencidos_sem_renovacao(janela.dia)
        return IndicatorValues(valores=valores)


async def _pedidos_do_mes(inicio: datetime, fim: datetime) -> list[Requisicao]:
    rows = await db.query(f"SELECT * FROM {REQUISICOES} WHERE tenant = $tenant AND pedido_em != NONE AND pedido_em != NULL "
                          "AND pedido_em >= $inicio AND pedido_em < $fim", inicio=inicio, fim=fim)
    return [Requisicao.model_validate(r) for r in rows]


async def _vencidos_sem_renovacao(dia: date) -> float:
    """Renovar é mudar o vencimento no cadastro: o que ainda está com o vencimento antes do dia não foi renovado."""
    rows = await db.query(f"SELECT vence_em FROM {VENCIMENTOS.table} WHERE tenant = $tenant")
    return float(sum(1 for r in rows if (vence := _data(r.get("vence_em"))) and vence < dia))


def _escritor() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_ADMINISTRATIVO_FORBIDDEN", "Só donos, administradores e operadores registram isto.", 403)


def _chave(value: Any) -> str:
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else str(value)


def _data(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "")[:10]
    return date.fromisoformat(texto) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto) else None


async def _colaborador(data: Admissao) -> Any:
    """O colaborador da admissão (o id vem do gatilho)."""
    if not data.colaborador_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", data.colaborador_id):
        raise Handoff("A admissão não trouxe o colaborador.")
    try:
        return await resources.get(COLABORADORES, ResourceRef(id=data.colaborador_id))
    except ServiceError as exc:
        if exc.status == 404:
            raise Handoff(f"O colaborador {data.colaborador or data.colaborador_id} não está mais no cadastro.") from None
        raise


async def _requisicao(requisicao_id: str | None, *, erro: bool = False) -> Requisicao:
    row = await db.select(f"{REQUISICOES}:{requisicao_id}") if requisicao_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", requisicao_id) else None
    if row is None:
        if erro:
            raise ServiceError("ERRO_ADMINISTRATIVO_NAO_ENCONTRADA", "Requisição não encontrada.", 404)
        raise Handoff("A requisição de compra não foi encontrada.")
    return Requisicao.model_validate(row)


async def _fornecedores() -> list[dict[str, Any]]:
    return await db.query(f"SELECT * FROM {FORNECEDORES.table} WHERE tenant = $tenant ORDER BY nome")


async def _email(para: str, assunto: str, texto: str) -> None:
    """E-mail pela caixa de entrada da organização (svc-integracoes). Sem a conexão ou sem provedor: o 409 de lá vira
    a exceção do staff; fora do ar: 503 (o motor tenta de novo)."""
    try:
        await bus.request(EMAIL_SUBJECT, EnviarEmail(para=para, assunto=assunto, texto=texto), EmailEnviado, timeout=15)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_ADMINISTRATIVO_INTEGRACOES_FORA", "O serviço de integrações não respondeu.", 503) from None


def _reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
