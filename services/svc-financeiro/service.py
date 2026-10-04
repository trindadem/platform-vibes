"""svc-financeiro · lógica de negócio pura. Fonte da verdade: specs/financeiro.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py. As ações do pacote (schemas.ACTIONS) são métodos de mesmo nome: o worker do motor de processos
(core/processes.py) as chama como a organização do processo, com a entrada vinda dos passos anteriores.
O banco e o e-mail são do svc-integracoes (rpc.integracoes.*): sem a conexão, o 409 de lá vira a exceção do staff.
Os indicadores "pacote" dos modelos (schemas.MODELS) saem de indicadores (rpc.financeiro.indicadores): o que as
execuções não sabem, com os títulos e as faturas da organização.
"""
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nats.errors import Error as NatsError
from pydantic import BaseModel

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import notify
from core.processes import Handoff
from core.resources import resources
from core.security import acting_as, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    AGENDAR_SUBJECT,
    ALIQUOTA_PADRAO,
    COBRAR_SUBJECT,
    CONTA_PADRAO,
    EMAIL_SUBJECT,
    EXTRATO_SUBJECT,
    FATURAS,
    FORNECEDORES,
    FUSO,
    LIVE_FATURAS,
    LIVE_TITULOS,
    PRAZO_PADRAO,
    REGUA,
    SERVICE,
    TITULOS,
    Agendamento,
    AgendarPagamento,
    Apuracao,
    Baixa,
    Classificacao,
    Cobranca,
    CobrancaEmitida,
    CobrancaIn,
    CobrarNoBanco,
    Comprovante,
    Conciliacao,
    ConciliacaoDia,
    Conferencia,
    Das,
    Documento,
    Dre,
    EmailEnviado,
    Empty,
    EnviarEmail,
    Envio,
    EnvioContador,
    Extrato,
    ExtratoPedido,
    Fatura,
    FaturaAberta,
    Faturamento,
    FaturaMudou,
    FaturaPage,
    FaturaQuery,
    IndicatorRequest,
    IndicatorValues,
    Fornecedor,
    Janela,
    Mes,
    Nota,
    NotaIn,
    Pagamento,
    PagamentoAgendado,
    Pendencias,
    Recebimento,
    Regua,
    Titulo,
    TituloMudou,
    TituloPage,
    TituloQuery,
)

MIGRATIONS: list[Migration] = []


@activities("financeiro")
class FinanceiroService:
    # ── Ações do contas a pagar (o motor chama) ──────────────────────────────

    async def conferir_pedido(self, data: Documento) -> Conferencia:
        """Fornecedor conhecido? O valor bate com o contrato dele? Sem valor no documento não dá para conferir."""
        if data.valor is None:
            raise Handoff("O documento não trouxe o valor: não dá para conferir.")
        fornecedor = await _fornecedor(data)
        if fornecedor is None:
            return Conferencia(divergente=False, diferenca=0, pedido=None, fornecedor_novo=True)
        contrato = fornecedor.get("valor_contrato")
        if not contrato:
            return Conferencia(divergente=False, diferenca=0, pedido=None, fornecedor_novo=False)
        diferenca = round(data.valor - float(contrato), 2)
        return Conferencia(divergente=abs(diferenca) > max(1.0, float(contrato) * 0.01), diferenca=diferenca,
                           pedido=f"Contrato {fornecedor['nome']}", fornecedor_novo=False)

    async def classificar(self, data: Documento) -> Classificacao:
        """A conta do fornecedor; fornecedor novo entra no cadastro com a conta padrão (a próxima nota já não é nova)."""
        fornecedor = await _fornecedor(data)
        if fornecedor is None:
            if not data.fornecedor:
                return Classificacao(conta=CONTA_PADRAO, centro_custo=None)
            try:
                await resources.create(FORNECEDORES, Fornecedor(nome=data.fornecedor[:200], cnpj=data.cnpj))
            except ServiceError as exc:
                if exc.code != "ERRO_RECORD_DUPLICATE":  # outro processo cadastrou o mesmo fornecedor agora
                    raise
            return Classificacao(conta=CONTA_PADRAO, centro_custo=None)
        return Classificacao(conta=fornecedor.get("conta") or CONTA_PADRAO, centro_custo=fornecedor.get("centro_custo"))

    async def agendar_pagamento(self, data: Pagamento) -> Agendamento:
        """Agenda no banco conectado da organização (svc-integracoes) e abre o título a pagar."""
        agendado = await _integracoes(AGENDAR_SUBJECT, AgendarPagamento(
            valor=data.valor, vencimento=data.vencimento, fornecedor=data.fornecedor, linha_digitavel=data.linha_digitavel,
        ), PagamentoAgendado)
        row = await db.create(TITULOS, {"fornecedor": data.fornecedor, "valor": data.valor, "vencimento": data.vencimento,
                                        "data": agendado.data, "pagamento_id": agendado.pagamento_id, "status": "agendado",
                                        "conciliado": False})
        await bus.live(LIVE_TITULOS, TituloMudou(id=Titulo.model_validate(row).id, action="agendado"))
        return Agendamento(pagamento_id=agendado.pagamento_id, data=agendado.data)

    async def conciliar(self, data: Comprovante) -> Conciliacao:
        """O banco confirmou: o título agendado com este pagamento fica pago."""
        rows = await db.query(f"SELECT * FROM {TITULOS} WHERE tenant = $tenant AND pagamento_id = $p LIMIT 1", p=data.pagamento_id)
        if not rows:
            raise Handoff(f"O pagamento {data.pagamento_id} não está nos títulos agendados.")
        titulo = Titulo.model_validate(rows[0])
        if titulo.status != "pago":
            await db.merge(f"{TITULOS}:{titulo.id}", {"status": "pago"})
            await bus.live(LIVE_TITULOS, TituloMudou(id=titulo.id, action="pago"))
        return Conciliacao(conciliado=True, diferenca=0)

    # ── Conciliação bancária ─────────────────────────────────────────────────

    async def conciliar_extrato(self, data: Janela) -> ConciliacaoDia:
        """Casa cada lançamento do extrato com um título (pagamento) ou uma fatura (recebimento) da empresa; o que não
        casa é sem par (o staff classifica quando passa da tolerância)."""
        desde = (date.today() - timedelta(days=max(1, data.dias or 1))).isoformat()
        extrato = await _integracoes(EXTRATO_SUBJECT, ExtratoPedido(desde=desde), Extrato)
        conciliados, sem_par, valor_sem_par = 0, 0, 0.0
        for item in extrato.itens:
            if item.tipo == "pagamento":
                rows = await db.query(f"SELECT * FROM {TITULOS} WHERE tenant = $tenant AND pagamento_id = $id LIMIT 1", id=item.id)
                if rows:
                    titulo = Titulo.model_validate(rows[0])
                    await db.merge(f"{TITULOS}:{titulo.id}", {"status": "pago", "conciliado": True})
                    await bus.live(LIVE_TITULOS, TituloMudou(id=titulo.id, action="conciliado"))
            else:
                rows = await db.query(f"SELECT * FROM {FATURAS} WHERE tenant = $tenant AND cobranca_id = $id LIMIT 1", id=item.id)
                if rows:
                    fatura = Fatura.model_validate(rows[0])
                    await db.merge(f"{FATURAS}:{fatura.id}", {"conciliada": True})
            if rows:
                conciliados += 1
            else:
                sem_par += 1
                valor_sem_par += abs(item.valor)
        return ConciliacaoDia(lancamentos=len(extrato.itens), conciliados=conciliados, sem_par=sem_par, valor_sem_par=round(valor_sem_par, 2))

    # ── Faturamento e cobrança ───────────────────────────────────────────────

    async def faturar(self, data: Faturamento) -> FaturaAberta:
        """Abre a fatura da venda: quem paga, o quê, quanto e quando vence (a data combinada, se veio; senão, hoje + o
        prazo do processo)."""
        faltam = [nome for nome, valor in (("cliente", data.cliente), ("valor", data.valor)) if valor in (None, "")]
        if faltam or (data.valor or 0) <= 0:
            raise Handoff(f"Faltam dados para faturar: {', '.join(faltam) or 'valor maior que zero'}.")
        vencimento = data.vencimento or (date.today() + timedelta(days=data.prazo_pagamento or PRAZO_PADRAO)).isoformat()
        row = await db.create(FATURAS, {"cliente": data.cliente, "cnpj": data.cnpj, "email": data.email, "descricao": data.descricao,
                                        "valor": round(float(data.valor), 2), "vencimento": vencimento, "status": "aberta",
                                        "regua": [], "conciliada": False, "proposta_id": data.proposta_id})
        fatura = Fatura.model_validate(row)
        await bus.live(LIVE_FATURAS, FaturaMudou(id=fatura.id, action="aberta"))
        return FaturaAberta(fatura_id=fatura.id, vencimento=vencimento)

    async def emitir_nota(self, data: NotaIn) -> Nota:
        """A NFS-e sai pela prefeitura do cliente, e a integração ainda não foi escolhida (briefing.md §14, decisão 6):
        o staff emite no portal e informa o número, que segue para a cobrança."""
        fatura = await _fatura(data.fatura_id)
        if fatura.nota_numero:
            return Nota(nota_numero=fatura.nota_numero)
        raise Handoff(f"A emissão de NFS-e ainda não tem integração: emita a nota de {fatura.cliente} ({_reais(fatura.valor)}) "
                      "no portal da prefeitura e informe o número.")

    async def cobrar(self, data: CobrancaIn) -> Cobranca:
        """Emite o boleto no banco e envia a cobrança por e-mail ao cliente (se ele tem e-mail e a caixa de entrada
        está conectada; senão, a cobrança fica emitida e enviada = falso)."""
        fatura = await _fatura(data.fatura_id)
        if fatura.cobranca_id and fatura.linha_digitavel:
            return Cobranca(cobranca_id=fatura.cobranca_id, linha_digitavel=fatura.linha_digitavel, vencimento=fatura.vencimento)
        emitida = await _integracoes(COBRAR_SUBJECT, CobrarNoBanco(valor=fatura.valor, vencimento=fatura.vencimento, pagador=fatura.cliente,
                                                                  descricao=fatura.descricao), CobrancaEmitida)
        nota = data.nota_numero or fatura.nota_numero
        row = await db.merge(f"{FATURAS}:{fatura.id}", {"cobranca_id": emitida.cobranca_id, "linha_digitavel": emitida.linha_digitavel,
                                                        "nota_numero": nota, "status": "cobrada"})
        fatura = Fatura.model_validate(row)
        enviada = False
        if fatura.email:
            texto = (f"Olá, {fatura.cliente}.\n\nSegue a cobrança de {fatura.descricao or 'nossa venda'}"
                     + (f" (nota fiscal {nota})" if nota else "") + f".\n\nValor: {_reais(fatura.valor)}\nVencimento: {_data_br(fatura.vencimento)}\n"
                     f"Linha digitável: {emitida.linha_digitavel}\n\nObrigado!")
            enviada = await _email(fatura.email, f"Cobrança: {fatura.descricao or 'venda'}"[:200], texto, obrigatorio=False)
        await bus.live(LIVE_FATURAS, FaturaMudou(id=fatura.id, action="cobrada"))
        return Cobranca(cobranca_id=emitida.cobranca_id, linha_digitavel=emitida.linha_digitavel, vencimento=emitida.vencimento, enviada=enviada)

    async def baixar(self, data: Recebimento) -> Baixa:
        """A espera do processo acordou (o banco avisou) ou o prazo venceu e o staff negociou: confere no extrato do
        banco se a cobrança foi recebida e, se foi, a fatura fica paga; senão, recebido = falso."""
        rows = await db.query(f"SELECT * FROM {FATURAS} WHERE tenant = $tenant AND cobranca_id = $c LIMIT 1", c=data.cobranca_id)
        if not rows:
            raise Handoff(f"A cobrança {data.cobranca_id} não está nas faturas.")
        fatura = Fatura.model_validate(rows[0])
        if fatura.status != "paga":
            desde = (fatura.created_at or datetime.now(UTC)).date().isoformat()
            extrato = await _integracoes(EXTRATO_SUBJECT, ExtratoPedido(desde=desde), Extrato)
            if not any(i.tipo == "recebimento" and i.id == data.cobranca_id for i in extrato.itens):
                return Baixa(recebido=False, valor=0)
            await db.merge(f"{FATURAS}:{fatura.id}", {"status": "paga", "recebido_em": datetime.now(UTC)})
            await bus.live(LIVE_FATURAS, FaturaMudou(id=fatura.id, action="paga"))
        return Baixa(recebido=True, valor=fatura.valor)

    # ── Fechamento do mês ────────────────────────────────────────────────────

    async def pendencias_do_mes(self, data: Mes) -> Pendencias:
        """O que falta para fechar o mês: pagamentos agendados sem comprovante e faturas sem nota fiscal."""
        referencia = _referencia(data.referencia)
        titulos = [t for t in await _titulos_do_mes(referencia) if t.status != "pago"]
        faturas = [f for f in await _faturas_do_mes(referencia) if not f.nota_numero]
        partes = [f"{len(titulos)} pagamento(s) sem comprovante" if titulos else "", f"{len(faturas)} fatura(s) sem nota fiscal" if faturas else ""]
        resumo = "; ".join(p for p in partes if p) or "Nada pendente."
        return Pendencias(referencia=referencia, pendencias=len(titulos) + len(faturas), resumo=resumo)

    async def enviar_ao_contador(self, data: EnvioContador) -> Envio:
        """O resumo do mês e os lançamentos vão por e-mail ao escritório contábil (o endereço é parâmetro do processo)."""
        if not data.email_contador or "@" not in data.email_contador:
            raise Handoff("Falta o e-mail do contador: diga no desenho do processo qual é (parâmetro email_contador).")
        referencia = _referencia(data.referencia)
        titulos, faturas = await _titulos_do_mes(referencia), await _faturas_do_mes(referencia)
        linhas = [f"Fechamento de {referencia}", "", f"Receitas (faturas): {_reais(sum(f.valor for f in faturas))}",
                  f"Despesas (pagamentos): {_reais(sum(t.valor for t in titulos))}", "", "Faturas:"]
        linhas += [f"- {_data_br(f.vencimento)} {f.cliente}: {_reais(f.valor)} · nota {f.nota_numero or 'sem nota'}" for f in faturas] or ["- nenhuma"]
        linhas += ["", "Pagamentos:"]
        linhas += [f"- {_data_br(t.data)} {t.fornecedor or 'sem fornecedor'}: {_reais(t.valor)} · {t.status}" for t in titulos] or ["- nenhum"]
        await _email(data.email_contador, f"Fechamento de {referencia}", "\n".join(linhas))
        return Envio(enviado_em=date.today().isoformat())

    async def apurar_das(self, data: Apuracao) -> Das:
        """DAS do Simples: a receita do mês (faturas) vezes a alíquota efetiva; vence no dia 20 do mês seguinte."""
        referencia = _referencia(data.referencia)
        receita = sum(f.valor for f in await _faturas_do_mes(referencia))
        ano, mes = (int(p) for p in referencia.split("-"))
        vencimento = date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 20).isoformat()
        aliquota = data.aliquota if data.aliquota is not None else ALIQUOTA_PADRAO
        return Das(valor=round(receita * aliquota / 100, 2), vencimento=vencimento)

    async def montar_dre(self, data: Mes) -> Dre:
        """A DRE gerencial do mês (receitas das faturas, despesas dos pagamentos) e o aviso à empresa com o resumo."""
        referencia = _referencia(data.referencia)
        receita = round(sum(f.valor for f in await _faturas_do_mes(referencia)), 2)
        despesas = round(sum(t.valor for t in await _titulos_do_mes(referencia)), 2)
        resultado = round(receita - despesas, 2)
        resumo = f"{'Lucro' if resultado >= 0 else 'Prejuízo'} de {_reais(abs(resultado))} (receitas {_reais(receita)}, despesas {_reais(despesas)})."
        await notify.roles("owner", "admin", title=f"DRE de {referencia}", body=resumo, link="/financeiro/receber", key=f"dre-{referencia}")
        return Dre(referencia=referencia, receita=receita, despesas=despesas, resultado=resultado, resumo=resumo)

    # ── Agendamento: a régua de cobrança (D-3, D+1, D+7) ─────────────────────

    async def regua(self, data: Empty) -> Regua:
        """Agendado (todo dia): lembra por e-mail o cliente da fatura cobrada e ainda não paga, 3 dias antes do
        vencimento, um dia depois e uma semana depois (cada lembrete uma vez). Na semana de atraso, avisa também o
        dono e o administrador da organização (alinhamento pós-N7, item 2: a vencida além do prazo chega ao gestor)."""
        enviados = 0
        hoje = date.today()
        for org in await db.tenants(FATURAS):
            with acting_as(system(SERVICE, org)):
                rows = await db.query(f"SELECT * FROM {FATURAS} WHERE tenant = $tenant AND status = 'cobrada' AND email != NONE AND email != NULL")
                for fatura in (Fatura.model_validate(r) for r in rows):
                    dias = (date.fromisoformat(fatura.vencimento) - hoje).days
                    etapa = "D+7" if dias <= -7 else "D+1" if dias <= -1 else "D-3" if dias <= 3 else None
                    if etapa is None or etapa in fatura.regua:
                        continue
                    texto = (f"Olá, {fatura.cliente}.\n\nLembrete: a cobrança de {_reais(fatura.valor)} {REGUA[etapa]} "
                             f"({_data_br(fatura.vencimento)}).\nLinha digitável: {fatura.linha_digitavel or '-'}\n\n"
                             "Se já pagou, desconsidere. Obrigado!")
                    try:
                        await _email(fatura.email or "", f"Lembrete de pagamento: {fatura.descricao or 'cobrança'}"[:200], texto)
                    except ServiceError:
                        continue  # sem caixa de entrada ou sem provedor: tenta no dia seguinte
                    await db.merge(f"{FATURAS}:{fatura.id}", {"regua": [*fatura.regua, etapa]})
                    await bus.live(LIVE_FATURAS, FaturaMudou(id=fatura.id, action="lembrete"))
                    enviados += 1
                    if etapa == "D+7":  # atraso além do prazo: chega ao gestor (na Cogniventure, ele suspende o cliente)
                        await notify.roles("owner", "admin", title=f"Cobrança vencida há 7 dias: {fatura.cliente}"[:120],
                                           body=f"{fatura.descricao or 'Cobrança'} de {_reais(fatura.valor)}, vencida em "
                                                f"{_data_br(fatura.vencimento)}. O cliente já recebeu três lembretes.",
                                           link="/financeiro/receber", action="Ver a cobrança", key=f"atraso-{fatura.id}")
        return Regua(lembretes=enviados)

    # ── Indicadores "pacote" (rpc.financeiro.indicadores; o svc-processos pede como system na organização) ──

    async def indicadores(self, data: IndicatorRequest) -> IndicatorValues:
        """Os indicadores do mês (em Brasília) que as execuções não sabem: pagos em atraso (contas a pagar) e valor em
        atraso (faturamento e cobrança). Nome desconhecido, mês inválido ou que ainda não começou: null."""
        calculos = {("contas-a-pagar", "pagos_em_atraso"): _pagos_em_atraso, ("faturamento-cobranca", "valor_em_atraso"): _valor_em_atraso}
        limites = _limites_do_mes(data.mes)
        valores: dict[str, float | None] = {}
        for nome in data.nomes:
            calculo = calculos.get((data.modelo, nome))
            valores[nome] = await calculo(data.mes, limites[1]) if calculo and limites and limites[0] <= datetime.now(UTC) else None
        return IndicatorValues(valores=valores)

    # ── Telas ────────────────────────────────────────────────────────────────

    async def titulos(self, data: TituloQuery) -> TituloPage:
        return await db.page(TITULOS, data, TituloPage)

    async def faturas(self, data: FaturaQuery) -> FaturaPage:
        return await db.page(FATURAS, data, FaturaPage)


async def _fornecedor(data: Documento) -> dict[str, Any] | None:
    """O fornecedor do documento: pelo CNPJ (só os dígitos) e, sem ele, pelo nome."""
    digitos = re.sub(r"\D", "", data.cnpj or "")
    if digitos:
        rows = await db.query(f"SELECT * FROM {FORNECEDORES.table} WHERE tenant = $tenant")
        achado = next((r for r in rows if re.sub(r"\D", "", r.get("cnpj") or "") == digitos), None)
        if achado:
            return achado
    if data.fornecedor:
        rows = await db.query(f"SELECT * FROM {FORNECEDORES.table} WHERE tenant = $tenant AND string::lowercase(nome) = $n LIMIT 1",
                              n=data.fornecedor.strip().lower())
        return rows[0] if rows else None
    return None


async def _integracoes(subject: str, pedido: BaseModel, modelo: type[Any]) -> Any:
    """Pede ao svc-integracoes (banco, e-mail) na organização de quem age. Fora do ar: 503 (o motor tenta de novo);
    o 409 de lá (sem conexão) sobe e vira a exceção do staff."""
    try:
        return await bus.request(subject, pedido, modelo, timeout=15)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_FINANCEIRO_INTEGRACOES_FORA", "O serviço de integrações não respondeu.", 503) from None


async def _email(para: str, assunto: str, texto: str, *, obrigatorio: bool = True) -> bool:
    """E-mail pela caixa de entrada da organização. obrigatorio=False: sem conexão ou sem provedor, devolve False."""
    try:
        await _integracoes(EMAIL_SUBJECT, EnviarEmail(para=para, assunto=assunto, texto=texto), EmailEnviado)
        return True
    except ServiceError as exc:
        if obrigatorio or exc.status >= 500:
            raise
        return False


async def _fatura(fatura_id: str) -> Fatura:
    row = await db.select(f"{FATURAS}:{fatura_id}") if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fatura_id or "") else None
    if row is None:
        raise Handoff(f"A fatura {fatura_id} não foi encontrada.")
    return Fatura.model_validate(row)


def _referencia(valor: str | None) -> str:
    """AAAA-MM; vazio (ou fora do formato): o mês passado."""
    if valor and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", valor):
        return valor
    passado = date.today().replace(day=1) - timedelta(days=1)
    return passado.strftime("%Y-%m")


async def _titulos_do_mes(referencia: str) -> list[Titulo]:
    rows = await db.query(f"SELECT * FROM {TITULOS} WHERE tenant = $tenant AND string::starts_with(data, $mes) ORDER BY data", mes=referencia)
    return [Titulo.model_validate(r) for r in rows]


async def _faturas_do_mes(referencia: str) -> list[Fatura]:
    """As faturas abertas no mês (a receita do mês é o que foi faturado nele)."""
    rows = await db.query(f"SELECT * FROM {FATURAS} WHERE tenant = $tenant ORDER BY created_at")
    return [f for f in (Fatura.model_validate(r) for r in rows) if f.created_at and f.created_at.strftime("%Y-%m") == referencia]


def _limites_do_mes(mes: str) -> tuple[datetime, datetime] | None:
    """Começo e fim (exclusivo) do mês civil em Brasília, em UTC; mês inválido: None."""
    try:
        ano, numero = (int(x) for x in mes.split("-"))
        fuso = ZoneInfo(FUSO)
        inicio = datetime(ano, numero, 1, tzinfo=fuso)
        fim = datetime(ano + (numero == 12), 1 if numero == 12 else numero + 1, 1, tzinfo=fuso)
    except ValueError:
        return None
    return inicio.astimezone(UTC), fim.astimezone(UTC)


async def _pagos_em_atraso(mes: str, fim: datetime) -> float:
    """Títulos pagos (comprovante ou extrato) com a data do pagamento no mês e depois do vencimento: o banco agenda
    para hoje o boleto que chega vencido. É a situação de agora: título do mês ainda sem comprovante não entra."""
    rows = await db.query(f"SELECT * FROM {TITULOS} WHERE tenant = $tenant AND status = 'pago' AND string::starts_with(data, $mes)", mes=mes)
    dia = re.compile(r"\d{4}-\d{2}-\d{2}")
    return float(sum(1 for r in rows if dia.fullmatch(str(r.get("data"))) and dia.fullmatch(str(r.get("vencimento")))
                     and r["data"] > r["vencimento"]))


async def _valor_em_atraso(mes: str, fim: datetime) -> float:
    """Faturas cobradas (boleto emitido) vencidas e não recebidas no fim do mês (no mês corrente, agora): vencimento
    antes do dia de corte e sem recebimento até ele (recebido_em guarda quando a fatura foi paga)."""
    corte = min(datetime.now(UTC), fim)
    dia = corte.astimezone(ZoneInfo(FUSO)).date().isoformat()
    rows = await db.query(f"SELECT * FROM {FATURAS} WHERE tenant = $tenant AND cobranca_id != NONE AND cobranca_id != NULL "
                          "AND vencimento < $dia", dia=dia)
    total = 0.0
    for fatura in (Fatura.model_validate(r) for r in rows):
        if fatura.created_at and _utc(fatura.created_at) >= corte:
            continue  # ainda não existia
        if fatura.status == "paga" and (fatura.recebido_em is None or _utc(fatura.recebido_em) < corte):
            continue
        total += fatura.valor
    return round(total, 2)


def _utc(quando: datetime) -> datetime:
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


def _reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(valor: str | None) -> str:
    return "/".join(reversed(valor.split("-"))) if valor and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor) else (valor or "-")
