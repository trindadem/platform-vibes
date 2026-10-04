"""svc-juridico · lógica de negócio pura. Fonte da verdade: specs/juridico.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py. As ações do pacote (schemas.ACTIONS) são métodos de mesmo nome: o worker do motor de processos
(core/processes.py) as chama como a organização do processo, com a entrada vinda dos passos anteriores. O que depende
de integração ainda não escolhida vira a exceção do staff (Handoff), com o que ele deve fazer e informar.
Os indicadores "pacote" dos modelos (schemas.MODELS) saem de indicadores (rpc.juridico.indicadores): contratos vigentes e
vencendo, prazos processuais em aberto e a situação das certidões, com os cadastros da organização.
"""
import re
from datetime import date, timedelta
from functools import lru_cache

from core.notify import notify
from core.processes import Handoff
from core.resources import resources
from core.security import acting_as, system
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    AVISO_CERTIDAO,
    AVISOS_CONTRATO,
    CERTIDOES,
    CERTIDOES_PADRAO,
    CONTRATOS,
    JANELA_CONTRATO,
    JANELA_PRAZO,
    PRAZOS,
    SERVICE,
    VIGENCIA_PADRAO,
    Arquivado,
    Assinado,
    Assinatura,
    Avisos,
    Certidao,
    Certidoes,
    CertidoesEmitidas,
    CertidoesIn,
    Consulta,
    Contrato,
    ContratoIn,
    Empty,
    IndicatorRequest,
    IndicatorValues,
    Prazo,
    PrazoFinal,
    PrazoProcessual,
    Publicacoes,
    RegistroCertidoes,
)

MIGRATIONS: list[Migration] = []


@activities("juridico")
class JuridicoService:
    # ── Gestão de contratos ──────────────────────────────────────────────────

    async def coletar_assinaturas(self, data: Assinatura) -> Assinado:
        """A assinatura eletrônica ainda não tem fornecedor (briefing.md §14, decisão 6): o staff envia o contrato para
        assinatura e informa a data em que a última parte assinou."""
        quem = data.parte or "a outra parte"
        raise Handoff(f"A assinatura eletrônica ainda não tem integração: envie o contrato a {quem}"
                      + (f" ({data.email})" if data.email else "") + " para assinar e informe a data da última assinatura.")

    async def arquivar_contrato(self, data: ContratoIn) -> Arquivado:
        """O contrato entra no cadastro, vigente, e o agendamento diário avisa a empresa 60 e 30 dias antes do fim."""
        faltam = [nome for nome, valor in (("parte", data.parte), ("objeto", data.objeto)) if not valor]
        if faltam:
            raise Handoff(f"Faltam dados para arquivar o contrato: {', '.join(faltam)}.")
        inicio = _data(data.inicio) or _data(data.assinado_em) or date.today()
        fim = _data(data.fim) or _mais_meses(inicio, data.vigencia_meses or VIGENCIA_PADRAO)
        item = await resources.create(CONTRATOS, Contrato(
            parte=data.parte[:200], cnpj=(data.cnpj or None) and data.cnpj[:20], objeto=data.objeto[:2000], valor=data.valor,
            inicio=inicio, fim=fim, reajuste_em=_data(data.reajuste_em), proposta_id=data.proposta_id))
        aviso = fim - timedelta(days=max(AVISOS_CONTRATO))
        return Arquivado(contrato_id=item.id, fim=fim.isoformat(), aviso_em=aviso.isoformat())

    # ── Publicações e processos ──────────────────────────────────────────────

    async def consultar_publicacoes(self, data: Consulta) -> Publicacoes:
        """Os diários e tribunais ainda não têm integração (decisão 6): o staff consulta pelo CNPJ e informa as
        intimações novas (zero se não houver), a data da disponibilização e o prazo em dias úteis."""
        cnpj = f" {data.cnpj}" if data.cnpj else " da empresa"
        raise Handoff(f"A consulta aos diários e tribunais ainda não tem integração: consulte as publicações do CNPJ{cnpj} e "
                      "informe quantas intimações novas há (zero se nenhuma), o resumo, a data da disponibilização e o prazo em dias úteis.")

    async def calcular_prazo(self, data: Prazo) -> PrazoFinal:
        """Publicação: o primeiro dia útil depois da disponibilização no diário. Prazo: em dias úteis a partir do dia
        útil seguinte à publicação, sem fins de semana, feriados nacionais e o recesso de 20/12 a 20/01."""
        disponibilizada = _data(data.disponibilizada_em)
        if disponibilizada is None or not data.dias_prazo or data.dias_prazo <= 0:
            raise Handoff("Faltam a data da disponibilização e o prazo em dias úteis para calcular o prazo.")
        publicada = _proximo_util(disponibilizada)
        dia = publicada
        for _ in range(data.dias_prazo):
            dia = _proximo_util(dia)
        resumo = (data.resumo or None) and data.resumo[:2000]
        existe = await db.query(f"SELECT id FROM {PRAZOS.table} WHERE tenant = $tenant AND publicada_em = $p AND prazo_final = $f "
                                "AND dias_uteis = $d AND resumo = $r LIMIT 1", p=publicada.isoformat(), f=dia.isoformat(),
                                d=data.dias_prazo, r=resumo)
        if not existe:  # o mesmo passo de novo (o motor tentou outra vez): o prazo já está no cadastro
            await resources.create(PRAZOS, PrazoProcessual(resumo=resumo, publicada_em=publicada, prazo_final=dia, dias_uteis=data.dias_prazo))
        return PrazoFinal(publicada_em=publicada.isoformat(), prazo_final=dia.isoformat(), dias_uteis=data.dias_prazo)

    # ── Certidões negativas ──────────────────────────────────────────────────

    async def emitir_certidoes(self, data: CertidoesIn) -> Certidoes:
        """Os portais (Receita/PGFN, Caixa, TST, Sefaz, prefeitura) ainda não têm integração (decisão 6): o staff emite
        e informa quantas vieram positivas e a validade mais próxima."""
        cnpj = f" do CNPJ {data.cnpj}" if data.cnpj else ""
        raise Handoff(f"A emissão de certidões ainda não tem integração: emita as certidões{cnpj} (Receita/PGFN, FGTS, trabalhista, "
                      "estadual e municipal) e informe quantas emitiu, quantas vieram positivas e a validade mais próxima.")

    async def registrar_certidoes(self, data: CertidoesEmitidas) -> RegistroCertidoes:
        """As certidões do mês entram no cadastro; o agendamento diário avisa 15 dias antes da validade."""
        validade = _data(data.validade)
        if validade is None:
            raise Handoff("Falta a validade das certidões para guardar e vigiar.")
        emitidas = data.emitidas if data.emitidas is not None and data.emitidas >= 0 else CERTIDOES_PADRAO
        item = await resources.create(CERTIDOES, Certidao(referencia=date.today().strftime("%Y-%m"), emitidas=emitidas,
                                                          positivas=min(emitidas, max(0, data.positivas or 0)),
                                                          validade=validade, resumo=(data.resumo or None) and data.resumo[:2000]))
        return RegistroCertidoes(certidao_id=item.id, aviso_em=(validade - timedelta(days=AVISO_CERTIDAO)).isoformat())

    # ── Indicadores "pacote" (rpc.juridico.indicadores; o svc-processos pede como system na organização) ──

    async def indicadores(self, data: IndicatorRequest) -> IndicatorValues:
        """O que as execuções não sabem, no corte do mês (o último dia; no mês corrente, hoje): contratos vigentes e os que
        vencem ou reajustam em 60 dias, prazos em aberto nos 5 dias úteis seguintes e a situação da última emissão de
        certidões. Nome desconhecido, mês inválido ou que ainda não começou: null."""
        janela = data.janela()
        calculos = {("gestao-contratos", "contratos_vigentes"): _contratos_vigentes, ("gestao-contratos", "vencendo_60_dias"): _vencendo,
                    ("publicacoes-processos", "prazos_proximos"): _prazos_proximos,
                    ("certidoes-negativas", "certidoes_validas"): _certidoes_validas,
                    ("certidoes-negativas", "dias_ate_validade"): _dias_ate_validade}
        valores: dict[str, float | None] = {}
        for nome in data.nomes:
            calculo = calculos.get((data.modelo, nome))
            valores[nome] = await calculo(janela.dia, data.mes) if calculo and janela else None
        return IndicatorValues(valores=valores)

    # ── Agendamento: os avisos antes de vencer ───────────────────────────────

    async def avisar(self, data: Empty) -> Avisos:
        """Agendado (todo dia): contrato vigente a 60 e a 30 dias do fim ou do reajuste e certidão a 15 dias da validade
        avisam dono e administrador; a chave do aviso impede repetir."""
        hoje = date.today()
        contratos = certidoes = 0
        for org in await db.tenants(CONTRATOS.table):
            with acting_as(system(SERVICE, org)):
                rows = await db.query(f"SELECT * FROM {CONTRATOS.table} WHERE tenant = $tenant AND status = 'vigente'")
                for row in rows:
                    for campo, o_que in (("fim", "vence"), ("reajuste_em", "tem reajuste")):
                        quando = _data(str(row.get(campo) or "")[:10])
                        if quando and (quando - hoje).days in AVISOS_CONTRATO:
                            dias = (quando - hoje).days
                            await notify.roles("owner", "admin", title=f"Contrato com {row['parte']} {o_que} em {dias} dias",
                                               body=f"{row.get('objeto') or ''}\n\nData: {quando.strftime('%d/%m/%Y')}.", link="/juridico",
                                               key=f"contrato-{row['id']}-{campo}-{dias}")
                            contratos += 1
        for org in await db.tenants(CERTIDOES.table):
            with acting_as(system(SERVICE, org)):
                rows = await db.query(f"SELECT * FROM {CERTIDOES.table} WHERE tenant = $tenant")
                for row in rows:
                    validade = _data(str(row.get("validade") or "")[:10])
                    if validade and (validade - hoje).days == AVISO_CERTIDAO:
                        await notify.roles("owner", "admin", title=f"Certidões vencem em {AVISO_CERTIDAO} dias",
                                           body=f"A validade mais próxima é {validade.strftime('%d/%m/%Y')}.", link="/juridico/certidoes",
                                           key=f"certidao-{row['id']}")
                        certidoes += 1
        return Avisos(contratos=contratos, certidoes=certidoes)


async def _vigentes(dia: date) -> list[dict]:
    """Os contratos vigentes no dia: a vigência cobre o dia (início até ele, fim depois dele ou sem fim)."""
    rows = await db.query(f"SELECT * FROM {CONTRATOS.table} WHERE tenant = $tenant AND status = 'vigente'")
    out = []
    for row in rows:
        inicio, fim = _data(str(row.get("inicio") or "")[:10]), _data(str(row.get("fim") or "")[:10])
        if (inicio is None or inicio <= dia) and (fim is None or fim >= dia):
            out.append(row)
    return out


async def _contratos_vigentes(dia: date, mes: str) -> float:
    return float(len(await _vigentes(dia)))


async def _vencendo(dia: date, mes: str) -> float:
    """Dos vigentes no dia, os que vencem ou reajustam nos JANELA_CONTRATO dias seguintes."""
    limite = dia + timedelta(days=JANELA_CONTRATO)
    datas = lambda row: [d for campo in ("fim", "reajuste_em") if (d := _data(str(row.get(campo) or "")[:10]))]  # noqa: E731
    return float(sum(1 for row in await _vigentes(dia) if any(dia < d <= limite for d in datas(row))))


async def _prazos_proximos(dia: date, mes: str) -> float:
    """Prazos em aberto que vencem nos JANELA_PRAZO dias úteis seguintes ao dia."""
    limite = dia
    for _ in range(JANELA_PRAZO):
        limite = _proximo_util(limite)
    rows = await db.query(f"SELECT prazo_final FROM {PRAZOS.table} WHERE tenant = $tenant AND status = 'aberto'")
    return float(sum(1 for r in rows if (final := _data(str(r.get("prazo_final") or "")[:10])) and dia < final <= limite))


async def _ultima_emissao(mes: str) -> dict | None:
    rows = await db.query(f"SELECT * FROM {CERTIDOES.table} WHERE tenant = $tenant AND referencia <= $mes "
                          "ORDER BY referencia DESC, created_at DESC LIMIT 1", mes=mes)
    return rows[0] if rows else None


async def _certidoes_validas(dia: date, mes: str) -> float | None:
    """As negativas da última emissão, se a validade mais próxima não passou do dia; vencida: zero (a renovação atrasou)."""
    emissao = await _ultima_emissao(mes)
    validade = _data(str((emissao or {}).get("validade") or "")[:10])
    if emissao is None or validade is None:
        return None
    if validade < dia:
        return 0.0
    emitidas = int(emissao.get("emitidas") if emissao.get("emitidas") is not None else CERTIDOES_PADRAO)
    return float(max(0, emitidas - int(emissao.get("positivas") or 0)))


async def _dias_ate_validade(dia: date, mes: str) -> float | None:
    emissao = await _ultima_emissao(mes)
    validade = _data(str((emissao or {}).get("validade") or "")[:10])
    return float((validade - dia).days) if validade else None


def _data(valor: str | None) -> date | None:
    """AAAA-MM-DD → data; outro formato (ou vazio) → None."""
    if valor and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor.strip()):
        try:
            return date.fromisoformat(valor.strip())
        except ValueError:
            return None
    return None


def _mais_meses(inicio: date, meses: int) -> date:
    """A mesma data, meses depois (no fim do mês quando o dia não existe: 31/01 + 1 mês = 28/02)."""
    total = inicio.month - 1 + meses
    ano, mes = inicio.year + total // 12, total % 12 + 1
    for dia in (inicio.day, 30, 29, 28):
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue
    return date(ano, mes, 28)


@lru_cache(maxsize=64)
def _feriados(ano: int) -> frozenset[date]:
    """Feriados nacionais (Lei 662/1949 e Lei 14.759/2023) e os da Páscoa em que o forense não funciona."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes, dia = divmod(h + m - 7 * n + 114, 31)
    pascoa = date(ano, mes, dia + 1)
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    moveis = [pascoa - timedelta(days=48), pascoa - timedelta(days=47), pascoa - timedelta(days=2), pascoa + timedelta(days=60)]
    return frozenset([date(ano, m_, d_) for m_, d_ in fixos] + moveis)


def _util(dia: date) -> bool:
    recesso = (dia.month == 12 and dia.day >= 20) or (dia.month == 1 and dia.day <= 20)  # CPC, art. 220
    return dia.weekday() < 5 and dia not in _feriados(dia.year) and not recesso


def _proximo_util(dia: date) -> date:
    seguinte = dia + timedelta(days=1)
    while not _util(seguinte):
        seguinte += timedelta(days=1)
    return seguinte
