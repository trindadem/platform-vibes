"""svc-juridico · contratos (DTOs, enums, constantes). Fonte da verdade: specs/juridico.md §2"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.plans import Module
from core.processes import (  # IndicatorRequest e IndicatorValues: o contrato de rpc.juridico.indicadores
    Action,
    Condition,
    Flow,
    Fluxo,
    Indicator,
    IndicatorRequest,
    IndicatorValues,
    ProcessModel,
    Step,
    Trigger,
)
from core.resources import Fields, Money, Resource, Text

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-juridico"
TASK_QUEUE = "juridico-queue"
VIGENCIA_PADRAO = 12  # meses de um contrato, quando nem o fim nem a vigência vêm
AVISOS_CONTRATO = (60, 30)  # dias antes do fim (e do reajuste) em que a empresa é avisada
AVISO_CERTIDAO = 15  # dias antes da validade de uma certidão
CERTIDOES_PADRAO = 5  # Receita/PGFN, FGTS, trabalhista, estadual e municipal
JANELA_CONTRATO = 60  # indicador: dias à frente em que um contrato vencendo ou reajustando conta
JANELA_PRAZO = 5  # indicador: dias úteis à frente em que um prazo processual conta

MODULE = Module("Jurídico", "Pacote de ações jurídicas do BPO: contratos, publicações e certidões negativas", category="Pacotes")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


# Cadastros (README §5.19): os contratos que a empresa assinou e as certidões que ela tem. Os processos gravam aqui; a
# empresa e o staff também cadastram à mão (um contrato antigo, uma certidão emitida fora).
class Contrato(Fields):
    parte: str = Field(..., min_length=2, max_length=200, title="Outra parte")
    cnpj: str | None = Field(None, max_length=20, title="CNPJ ou CPF")
    objeto: Text = Field(..., min_length=2, max_length=2000, title="Objeto")
    valor: Money | None = Field(None, title="Valor")
    inicio: date | None = Field(None, title="Início da vigência")
    fim: date | None = Field(None, title="Fim da vigência", description="A empresa é avisada 60 e 30 dias antes")
    reajuste_em: date | None = Field(None, title="Próximo reajuste")
    status: Literal["vigente", "encerrado"] = Field("vigente", title="Situação")
    proposta_id: str | None = Field(None, max_length=64, title="Proposta de origem")


class Certidao(Fields):
    referencia: str = Field(..., min_length=7, max_length=7, pattern=r"^\d{4}-\d{2}$", title="Mês (AAAA-MM)")
    emitidas: int = Field(CERTIDOES_PADRAO, ge=0, le=20, title="Emitidas", description="Quantas certidões foram emitidas no mês")
    positivas: int = Field(0, ge=0, le=20, title="Positivas", description="Quantas vieram positivas (irregularidade)")
    validade: date | None = Field(None, title="Validade mais próxima")
    resumo: Text | None = Field(None, max_length=2000, title="Resumo")


class PrazoProcessual(Fields):
    resumo: Text | None = Field(None, max_length=2000, title="O que a intimação pede")
    publicada_em: date = Field(..., title="Publicada em")
    prazo_final: date = Field(..., title="Prazo final")
    dias_uteis: int = Field(..., ge=1, le=365, title="Dias úteis")
    status: Literal["aberto", "cumprido"] = Field("aberto", title="Situação")


CONTRATOS = Resource(SERVICE, "contratos", Contrato, "Contratos", search=("parte", "objeto"), sort=("fim", "parte"),
                     filters=("status",), columns=("parte", "valor", "inicio", "fim", "reajuste_em", "status"),
                     write=("owner", "admin", "operador"))
CERTIDOES = Resource(SERVICE, "certidoes", Certidao, "Certidões", sort=("referencia", "validade"), write=("owner", "admin", "operador"))
PRAZOS = Resource(SERVICE, "prazos", PrazoProcessual, "Prazos processuais", search=("resumo",), sort=("prazo_final",),
                  filters=("status",), write=("owner", "admin", "operador"))
RESOURCES = [CONTRATOS, CERTIDOES, PRAZOS]


# ── Ações: entradas e saídas ─────────────────────────────────────────────────

class Assinatura(BaseModel):
    parte: str | None = Field(None, description="Quem assina do outro lado")
    email: str | None = None
    objeto: str | None = None


class Assinado(BaseModel):
    assinado_em: str = Field(..., description="Data da última assinatura (AAAA-MM-DD)")


class ContratoIn(BaseModel):
    parte: str | None = None
    cnpj: str | None = None
    objeto: str | None = None
    valor: float | None = None
    inicio: str | None = Field(None, description="AAAA-MM-DD")
    fim: str | None = Field(None, description="AAAA-MM-DD")
    reajuste_em: str | None = Field(None, description="AAAA-MM-DD")
    vigencia_meses: int | None = Field(None, description="Sem fim informado, o fim é o início mais estes meses (padrão 12)")
    assinado_em: str | None = None
    proposta_id: str | None = None


class Arquivado(BaseModel):
    contrato_id: str
    fim: str = Field(..., description="Fim da vigência (AAAA-MM-DD)")
    aviso_em: str = Field(..., description="Quando a empresa é avisada (60 dias antes do fim)")


class Consulta(BaseModel):
    cnpj: str | None = Field(None, description="CNPJ da empresa nos diários e tribunais")


class Publicacoes(BaseModel):
    novas: int = Field(..., description="Intimações novas desde a última consulta")
    resumo: str = Field("", description="O que cada intimação pede")
    disponibilizada_em: str | None = Field(None, description="Data da disponibilização no diário (AAAA-MM-DD)")
    dias_prazo: int | None = Field(None, description="Prazo em dias úteis (o menor, se forem várias)")


class Prazo(BaseModel):
    disponibilizada_em: str | None = None
    dias_prazo: int | None = None
    resumo: str | None = Field(None, description="O que a intimação pede (vai com o prazo para o cadastro)")


class PrazoFinal(BaseModel):
    publicada_em: str = Field(..., description="Primeiro dia útil depois da disponibilização")
    prazo_final: str = Field(..., description="Último dia do prazo (AAAA-MM-DD)")
    dias_uteis: int


class CertidoesIn(BaseModel):
    cnpj: str | None = None


class Certidoes(BaseModel):
    emitidas: int = Field(CERTIDOES_PADRAO, description="Quantas certidões foram emitidas")
    positivas: int = Field(..., description="Quantas certidões vieram positivas")
    validade: str = Field(..., description="Validade mais próxima (AAAA-MM-DD)")
    resumo: str = ""


class CertidoesEmitidas(BaseModel):
    emitidas: int | None = None
    positivas: int | None = None
    validade: str | None = None
    resumo: str | None = None


class RegistroCertidoes(BaseModel):
    certidao_id: str
    aviso_em: str = Field(..., description="15 dias antes da validade (AAAA-MM-DD)")


class Avisos(BaseModel):
    """O que o agendamento diário avisou."""

    contratos: int
    certidoes: int


# ── Ações (o que os passos chamam) e modelos (o desenho de cada organização começa daqui) ──

ACTIONS = [
    Action("coletar_assinaturas", "Coletar as assinaturas", "Envia o contrato para assinatura eletrônica das partes",
           Assinatura, Assinado, risk="externa", connections=("Assinatura eletrônica",), example=Assinado(assinado_em="2026-10-10")),
    Action("arquivar_contrato", "Arquivar e vigiar o contrato", "Guarda o contrato e avisa a empresa 60 e 30 dias antes do fim",
           ContratoIn, Arquivado, risk="escrita",
           example=Arquivado(contrato_id="ct1", fim="2027-10-10", aviso_em="2027-08-11")),
    Action("consultar_publicacoes", "Consultar publicações", "Procura intimações da empresa nos diários e tribunais pelo CNPJ",
           Consulta, Publicacoes, risk="externa", connections=("Tribunais e diários oficiais",),
           example=Publicacoes(novas=0, resumo="Nenhuma intimação nova.")),
    Action("calcular_prazo", "Calcular o prazo", "Conta o prazo processual em dias úteis a partir da publicação",
           Prazo, PrazoFinal, risk="leitura",
           example=PrazoFinal(publicada_em="2026-10-06", prazo_final="2026-10-27", dias_uteis=15)),
    Action("emitir_certidoes", "Emitir as certidões", "Emite as certidões negativas da empresa nos portais",
           CertidoesIn, Certidoes, risk="externa", connections=("Portais de certidões",),
           example=Certidoes(emitidas=5, positivas=0, validade="2026-12-01", resumo="Todas negativas.")),
    Action("registrar_certidoes", "Guardar as certidões", "Guarda as certidões do mês e avisa 15 dias antes de vencer",
           CertidoesEmitidas, RegistroCertidoes, risk="escrita",
           example=RegistroCertidoes(certidao_id="cd1", aviso_em="2026-11-16")),
]

C, F, I, P = Condition, Flow, Indicator, Step
MODELS = [
    ProcessModel("gestao-contratos", Fluxo(
        gatilho=Trigger(tipo="processo", processo="proposta-comercial", resultado="aceita", descricao="Proposta aceita"),
        parametros={"vigencia_meses": VIGENCIA_PADRAO},
        passos=[
            P(id="levantar", tipo="agente", nome="Levantar os termos", excecao=True, leitura=True,
              objetivo="Levantar do contrato (ou da proposta aceita) a outra parte, o CNPJ, o objeto, o valor, o início e o fim "
                       "da vigência e o próximo reajuste",
              saidas=["parte", "cnpj", "objeto", "valor", "inicio", "fim", "reajuste_em"],
              exemplo={"parte": "Padaria Pão Quente", "objeto": "Fornecimento semanal de pães", "valor": 4800.0}),
            P(id="analisar", tipo="agente", nome="Comparar com o padrão", excecao=True,
              objetivo="Comparar os termos com o padrão de contrato da empresa (no conhecimento) e dizer se há cláusula de risco "
                       "alto (multa acima do padrão, foro distante, renovação automática, reajuste sem índice), com os pontos",
              saidas=["risco_alto", "pontos"], exemplo={"risco_alto": False, "pontos": "Dentro do padrão da empresa."}),
            P(id="risco", tipo="decisao", nome="Risco alto?"),
            P(id="revisar", tipo="tarefa", nome="Revisão jurídica", responsavel="staff",
              pergunta="O contrato pode seguir para assinatura?", horas=48),
            P(id="liberado", tipo="decisao", nome="Liberado?"),
            P(id="assinar", tipo="acao", nome="Coletar as assinaturas", acao="juridico.coletar_assinaturas", excecao=True),
            P(id="arquivar", tipo="acao", nome="Arquivar e vigiar", acao="juridico.arquivar_contrato"),
            P(id="vigente", tipo="fim", nome="Vigente", resultado="vigente"),
            P(id="barrado", tipo="fim", nome="Barrado na revisão", resultado="barrado"),
        ],
        ligacoes=[
            F(de="inicio", para="levantar"), F(de="levantar", para="analisar"), F(de="analisar", para="risco"),
            F(de="risco", para="revisar", condicao=C(campo="analisar.risco_alto", operador="verdadeiro")),
            F(de="risco", para="assinar"), F(de="revisar", para="liberado"),
            F(de="liberado", para="assinar", condicao=C(campo="revisar.aprovado", operador="verdadeiro")),
            F(de="liberado", para="barrado"), F(de="assinar", para="arquivar"), F(de="arquivar", para="vigente"),
        ],
    ), indicadores=[
        I("contratos_vigentes", "Contratos vigentes", "pacote",
          descricao="Contratos com a vigência cobrindo o fim do mês (no mês corrente, hoje)"),
        I("vencendo_60_dias", "Vencendo ou reajustando em 60 dias", "pacote",
          descricao="Dos vigentes, os que vencem ou reajustam nos 60 dias seguintes ao fim do mês (no mês corrente, a hoje)"),
        I("dias_ate_assinar", "Da proposta aceita ao contrato assinado", "tempo", unidade="dias", de="inicio", ate="assinar",
          resultado="vigente", descricao="Média, nos contratos que ficaram vigentes no mês, do começo da gestão às assinaturas"),
    ]),
    ProcessModel("publicacoes-processos", Fluxo(
        gatilho=Trigger(tipo="agenda", agenda="0 10 * * 1-5", descricao="Todo dia útil"),
        parametros={"cnpj": ""},
        passos=[
            P(id="consultar", tipo="acao", nome="Consultar publicações", acao="juridico.consultar_publicacoes", excecao=True),
            P(id="tem_intimacao", tipo="decisao", nome="Intimação nova?"),
            P(id="calcular", tipo="acao", nome="Calcular o prazo", acao="juridico.calcular_prazo", excecao=True),
            P(id="advogado", tipo="tarefa", nome="Avisar o advogado", responsavel="cliente",
              pergunta="Intimação nova: o advogado está ciente do prazo?", horas=24),
            P(id="encaminhada", tipo="fim", nome="Encaminhada ao advogado", resultado="encaminhada"),
            P(id="sem_intimacoes", tipo="fim", nome="Sem intimações", resultado="sem_intimacoes"),
        ],
        ligacoes=[
            F(de="inicio", para="consultar"), F(de="consultar", para="tem_intimacao"),
            F(de="tem_intimacao", para="calcular", condicao=C(campo="consultar.novas", operador=">", valor=0)),
            F(de="tem_intimacao", para="sem_intimacoes"), F(de="calcular", para="advogado"), F(de="advogado", para="encaminhada"),
        ],
    ), indicadores=[
        I("intimacoes_recebidas", "Intimações recebidas", "soma", campo="consultar.novas",
          descricao="Intimações novas encontradas nas consultas do mês"),
        I("prazos_proximos", "Prazos nos próximos 5 dias úteis", "pacote",
          descricao="Prazos processuais em aberto que vencem nos 5 dias úteis seguintes ao fim do mês (no mês corrente, a hoje)"),
    ]),
    ProcessModel("certidoes-negativas", Fluxo(
        gatilho=Trigger(tipo="agenda", agenda="0 11 1 * *", descricao="Todo mês"),
        parametros={"cnpj": ""},
        passos=[
            P(id="emitir", tipo="acao", nome="Emitir as certidões", acao="juridico.emitir_certidoes", excecao=True),
            P(id="guardar", tipo="acao", nome="Guardar e vigiar", acao="juridico.registrar_certidoes"),
            P(id="positiva", tipo="decisao", nome="Alguma positiva?"),
            P(id="regularizar", tipo="tarefa", nome="Regularizar", responsavel="staff",
              pergunta="A irregularidade da certidão positiva foi encaminhada?", horas=48),
            P(id="regular", tipo="fim", nome="Regular", resultado="regular"),
            P(id="irregular", tipo="fim", nome="Irregular", resultado="irregular"),
        ],
        ligacoes=[
            F(de="inicio", para="emitir"), F(de="emitir", para="guardar"), F(de="guardar", para="positiva"),
            F(de="positiva", para="regularizar", condicao=C(campo="emitir.positivas", operador=">", valor=0)),
            F(de="positiva", para="regular"), F(de="regularizar", para="irregular"),
        ],
    ), indicadores=[
        I("certidoes_validas", "Certidões válidas", "pacote",
          descricao="Negativas da última emissão, se nenhuma venceu até o fim do mês (no mês corrente, hoje); senão, zero"),
        I("positivas", "Certidões positivas", "soma", campo="emitir.positivas",
          descricao="Certidões que vieram positivas nas emissões do mês"),
        I("dias_ate_validade", "Dias até a próxima validade", "pacote", unidade="dias",
          descricao="Do fim do mês (no mês corrente, de hoje) à validade mais próxima da última emissão; negativo: já venceu"),
    ]),
]
