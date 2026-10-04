"""svc-juridico · lógica de negócio pura. Fonte da verdade: specs/juridico.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py. As ações do pacote (schemas.ACTIONS) são métodos de mesmo nome: o worker do motor de processos
(core/processes.py) as chama como a organização do processo, com a entrada vinda dos passos anteriores. O que depende
de integração ainda não escolhida vira a exceção do staff (Handoff), com o que ele deve fazer e informar.
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
    CONTRATOS,
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
    Prazo,
    PrazoFinal,
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
        return PrazoFinal(publicada_em=publicada.isoformat(), prazo_final=dia.isoformat(), dias_uteis=data.dias_prazo)

    # ── Certidões negativas ──────────────────────────────────────────────────

    async def emitir_certidoes(self, data: CertidoesIn) -> Certidoes:
        """Os portais (Receita/PGFN, Caixa, TST, Sefaz, prefeitura) ainda não têm integração (decisão 6): o staff emite
        e informa quantas vieram positivas e a validade mais próxima."""
        cnpj = f" do CNPJ {data.cnpj}" if data.cnpj else ""
        raise Handoff(f"A emissão de certidões ainda não tem integração: emita as certidões{cnpj} (Receita/PGFN, FGTS, trabalhista, "
                      "estadual e municipal) e informe quantas vieram positivas e a validade mais próxima.")

    async def registrar_certidoes(self, data: CertidoesEmitidas) -> RegistroCertidoes:
        """As certidões do mês entram no cadastro; o agendamento diário avisa 15 dias antes da validade."""
        validade = _data(data.validade)
        if validade is None:
            raise Handoff("Falta a validade das certidões para guardar e vigiar.")
        item = await resources.create(CERTIDOES, Certidao(referencia=date.today().strftime("%Y-%m"), positivas=max(0, data.positivas or 0),
                                                          validade=validade, resumo=(data.resumo or None) and data.resumo[:2000]))
        return RegistroCertidoes(certidao_id=item.id, aviso_em=(validade - timedelta(days=AVISO_CERTIDAO)).isoformat())

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
