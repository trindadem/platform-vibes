"""svc-vendas · contratos (DTOs, enums, constantes). Fonte da verdade: specs/vendas.md §2"""
from datetime import date, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.plans import Module
from core.processes import (  # IndicatorRequest e IndicatorValues: o contrato de rpc.vendas.indicadores
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
from core.resources import Email, Fields, Phone, Resource, Text
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-vendas"
TASK_QUEUE = "vendas-queue"
EMAIL_SUBJECT = "rpc.integracoes.enviar_email"  # e-mail que sai da caixa de entrada da organização (svc-integracoes)
PROPOSTAS = "vendas_propostas"
TABLES = [PROPOSTAS]
SEARCH = {PROPOSTAS: ["cliente", "pedido"]}
LIVE_PROPOSTAS = "vendas.propostas"
WRITERS = frozenset({"owner", "admin", "operador"})
VALIDADE_DIAS = 15  # validade de uma proposta enviada
FOLLOW_UPS = {"D3": 3, "D7": 7}  # dias depois do envio, sem resposta, em que a proposta ganha um follow-up
INATIVIDADE_PADRAO = 90  # dias sem comprar para entrar na reativação
HORARIOS = range(10, 17)  # horas das reuniões com leads (dia útil), uma por hora

MODULE = Module("Vendas", "Pacote de ações de vendas do BPO: leads, propostas e reativação da carteira", category="Pacotes")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


# ── Cadastros (README §5.19) ─────────────────────────────────────────────────

Origem = Literal["site", "instagram", "whatsapp", "indicacao", "outro"]
ORIGENS = {"site": "Site", "instagram": "Instagram", "whatsapp": "WhatsApp", "indicacao": "Indicação", "outro": "Outro"}


class Lead(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="Nome")
    email: Email | None = Field(None, title="E-mail")
    telefone: Phone | None = Field(None, title="Telefone")
    origem: Origem = Field("outro", title="Origem", json_schema_extra={"labels": ORIGENS})
    interesse: Text | None = Field(None, max_length=2000, title="O que ele quer")
    status: Literal["novo", "qualificado", "reuniao", "nutricao", "atendimento", "cliente"] = Field(
        "novo", title="Situação", json_schema_extra={"labels": {"reuniao": "Reunião marcada", "nutricao": "Nutrição", "atendimento": "Atendimento humano"}})
    reuniao_em: datetime | None = Field(None, title="Reunião")


class Cliente(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="Nome")
    email: Email | None = Field(None, title="E-mail")
    telefone: Phone | None = Field(None, title="Telefone")
    ultima_compra: date | None = Field(None, title="Última compra")
    campanha_em: date | None = Field(None, title="Última campanha")


LEADS = Resource(SERVICE, "leads", Lead, "Leads", search=("nome", "email"), sort=("nome",), filters=("status", "origem"),
                 write=tuple(WRITERS))
CLIENTES = Resource(SERVICE, "clientes", Cliente, "Clientes", search=("nome", "email"), sort=("nome", "ultima_compra"),
                    write=tuple(WRITERS))
RESOURCES = [LEADS, CLIENTES]
LeadItem = LEADS.item


# ── Rotas: o que chega e inicia os processos ─────────────────────────────────

class ReceberLead(_Input):
    nome: str = Field(..., min_length=2, max_length=200)
    email: Email | None = None
    telefone: str | None = Field(None, max_length=40)
    origem: Origem = "outro"
    interesse: str | None = Field(None, max_length=2000, description="O que o lead escreveu")


class PedidoProposta(_Input):
    cliente: str = Field(..., min_length=2, max_length=200, description="Para quem é a proposta")
    email: Email | None = Field(None, description="Para onde a proposta vai")
    pedido: str = Field(..., min_length=10, max_length=3000, description="O que o cliente pediu, nas palavras dele")


StatusProposta = Literal["pedida", "montada", "enviada", "aceita", "recusada"]


class Proposta(BaseModel):
    """Uma proposta comercial: do pedido à resposta do cliente."""

    id: str
    cliente: str
    email: str | None = None
    pedido: str
    descricao: str | None = None
    valor: float | None = None
    desconto: float | None = None
    validade: str | None = None
    status: StatusProposta
    enviada_em: datetime | None = None
    follow_ups: list[str] = Field(default_factory=list, description="Follow-ups enviados (D3, D7)")
    respondida_em: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class PropostaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "valor")
    default_sort: ClassVar[str | None] = "-created_at"
    status: StatusProposta | None = None


class PropostaPage(Page[Proposta]):
    pass


class PropostaMudou(BaseModel):
    id: str
    action: Literal["pedida", "montada", "enviada", "follow_up", "aceita", "recusada"]


class FollowUps(BaseModel):
    """O que o agendamento diário enviou."""

    enviados: int


# ── Ações: entradas e saídas ─────────────────────────────────────────────────

class LeadIn(BaseModel):
    lead_id: str | None = None
    nome: str | None = None
    email: str | None = None
    telefone: str | None = None
    origem: str | None = None
    interesse: str | None = None


class LeadRegistrado(BaseModel):
    lead_id: str
    novo: bool = Field(..., description="Falso quando o mesmo e-mail já era um lead")


class LeadRef(BaseModel):
    lead_id: str | None = None
    resumo: str | None = Field(None, description="O que o lead quer (do agente que qualificou)")


class Reuniao(BaseModel):
    reuniao_em: str = Field(..., description="AAAA-MM-DD HH:MM")


class Nutricao(BaseModel):
    status: Literal["nutricao"]


class PropostaIn(BaseModel):
    proposta_id: str | None = None
    cliente: str | None = None
    email: str | None = None
    descricao: str | None = None
    valor: float | None = None
    desconto: float | None = None


class PropostaMontada(BaseModel):
    proposta_id: str
    validade: str = Field(..., description="AAAA-MM-DD")


class PropostaRef(BaseModel):
    proposta_id: str | None = None


class PropostaEnviada(BaseModel):
    enviada_em: str = Field(..., description="AAAA-MM-DD")


class RespostaIn(BaseModel):
    proposta_id: str | None = None
    aprovado: bool | None = Field(None, description="O cliente aceitou (a resposta da tarefa)")


class Desfecho(BaseModel):
    status: Literal["aceita", "recusada"]
    aceita: bool


class Inatividade(BaseModel):
    dias_sem_comprar: int | None = None


class Inativos(BaseModel):
    clientes: int = Field(..., description="Quantos clientes estão sem comprar há mais dos dias")
    nomes: str = ""


class Campanha(BaseModel):
    mensagem: str | None = None
    dias_sem_comprar: int | None = None


class CampanhaEnviada(BaseModel):
    enviados: int


# Do svc-integracoes (rpc.integracoes.enviar_email): o contrato repetido aqui, de quem consome.
class EnviarEmail(BaseModel):
    para: str
    assunto: str
    texto: str


class EmailEnviado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mensagem_id: str
    de: str


# ── Ações (o que os passos chamam) e modelos (o desenho de cada organização começa daqui) ──

ACTIONS = [
    Action("registrar_lead", "Registrar o lead", "Registra o lead no CRM da empresa (o mesmo e-mail não duplica)",
           LeadIn, LeadRegistrado, risk="escrita", example=LeadRegistrado(lead_id="ld1", novo=True)),
    Action("agendar_reuniao", "Marcar a reunião", "Marca a reunião do lead com o vendedor e envia o convite por e-mail",
           LeadRef, Reuniao, risk="externa", connections=("Caixa de entrada",), example=Reuniao(reuniao_em="2026-10-06 10:00")),
    Action("nutrir", "Levar para nutrição", "Põe o lead frio na lista de nutrição (a reativação o alcança)",
           LeadRef, Nutricao, risk="escrita", example=Nutricao(status="nutricao")),
    Action("registrar_proposta", "Registrar a proposta", "Guarda a proposta montada com a validade",
           PropostaIn, PropostaMontada, risk="escrita", example=PropostaMontada(proposta_id="pp1", validade="2026-10-20")),
    Action("enviar_proposta", "Enviar a proposta", "Envia a proposta ao cliente por e-mail",
           PropostaRef, PropostaEnviada, risk="externa", connections=("Caixa de entrada",), example=PropostaEnviada(enviada_em="2026-10-05")),
    Action("registrar_resposta", "Registrar a resposta", "Fecha a proposta como aceita ou recusada; a aceita vira cliente",
           RespostaIn, Desfecho, risk="escrita", example=Desfecho(status="aceita", aceita=True)),
    Action("selecionar_inativos", "Selecionar clientes parados", "Lista os clientes sem comprar há mais dos dias pedidos",
           Inatividade, Inativos, risk="leitura", example=Inativos(clientes=4, nomes="Padaria Pão Quente, Café Central")),
    Action("enviar_campanha", "Enviar a campanha", "Envia a mensagem de reativação por e-mail aos clientes parados",
           Campanha, CampanhaEnviada, risk="externa", connections=("Caixa de entrada",), example=CampanhaEnviada(enviados=4)),
]

C, F, I, P = Condition, Flow, Indicator, Step
MODELS = [
    ProcessModel("qualificacao-leads", Fluxo(
        gatilho=Trigger(tipo="evento", evento="vendas.lead", descricao="Lead no site, Instagram ou WhatsApp"),
        passos=[
            P(id="registrar", tipo="acao", nome="Registrar o lead", acao="vendas.registrar_lead"),
            P(id="qualificar", tipo="agente", nome="Qualificar o lead", excecao=True,
              objetivo="Ler o que o lead escreveu e qualificar pelo perfil de cliente ideal da empresa (no conhecimento): se é um "
                       "bom cliente para a empresa, se pediu para falar com uma pessoa e um resumo do que ele quer",
              saidas=["qualificado", "quer_humano", "resumo"],
              exemplo={"qualificado": True, "quer_humano": False, "resumo": "Quer encomendas semanais de pães para o café"}),
            P(id="humano", tipo="decisao", nome="Pediu uma pessoa?"),
            P(id="atender", tipo="tarefa", nome="Atender o lead", responsavel="cliente",
              pergunta="O lead pediu atendimento humano: um vendedor vai falar com ele?", horas=4),
            P(id="quente", tipo="decisao", nome="Qualificado?"),
            P(id="reuniao", tipo="acao", nome="Marcar a reunião", acao="vendas.agendar_reuniao", excecao=True),
            P(id="nutrir", tipo="acao", nome="Levar para nutrição", acao="vendas.nutrir"),
            P(id="reuniao_marcada", tipo="fim", nome="Reunião marcada", resultado="reuniao"),
            P(id="nutricao", tipo="fim", nome="Em nutrição", resultado="nutricao"),
            P(id="atendimento", tipo="fim", nome="Com um vendedor", resultado="atendimento"),
        ],
        ligacoes=[
            F(de="inicio", para="registrar"), F(de="registrar", para="qualificar"), F(de="qualificar", para="humano"),
            F(de="humano", para="atender", condicao=C(campo="qualificar.quer_humano", operador="verdadeiro")),
            F(de="humano", para="quente"), F(de="atender", para="atendimento"),
            F(de="quente", para="reuniao", condicao=C(campo="qualificar.qualificado", operador="verdadeiro")),
            F(de="quente", para="nutrir"), F(de="reuniao", para="reuniao_marcada"), F(de="nutrir", para="nutricao"),
        ],
    ), indicadores=[
        I("leads_recebidos", "Leads recebidos", "contagem", base="iniciadas", descricao="Leads que chegaram no mês"),
        I("qualificados", "Qualificados", "percentual", unidade="percentual",
          condicao=C(campo="qualificar.qualificado", operador="verdadeiro"),
          descricao="Dos leads encaminhados no mês, os que o agente qualificou como cliente do perfil"),
        I("tempo_primeira_resposta", "Tempo até a primeira resposta", "tempo", unidade="horas", de="inicio", ate="fim",
          descricao="Média, nos leads encaminhados no mês, da chegada ao encaminhamento: reunião marcada, nutrição ou vendedor"),
    ]),
    ProcessModel("proposta-comercial", Fluxo(
        gatilho=Trigger(tipo="evento", evento="vendas.pedido_proposta", descricao="Pedido de proposta"),
        parametros={"desconto_maximo": 10},
        passos=[
            P(id="montar", tipo="agente", nome="Montar a proposta", excecao=True,
              objetivo="Montar a proposta para o pedido do cliente com a tabela de preços e as condições comerciais do "
                       "conhecimento: o cliente, o e-mail, o que vai ser entregue, o valor total em reais e o desconto dado (%)",
              saidas=["cliente", "email", "descricao", "valor", "desconto"],
              exemplo={"cliente": "Padaria Pão Quente", "email": "compras@paoquente.com.br",
                       "descricao": "Fornecimento semanal de 40 kg de pão francês por 3 meses", "valor": 4800.0, "desconto": 5.0}),
            P(id="registrar", tipo="acao", nome="Registrar a proposta", acao="vendas.registrar_proposta"),
            P(id="desconto_alto", tipo="decisao", nome="Desconto acima do limite?"),
            P(id="aprovar_desconto", tipo="tarefa", nome="Aprovar o desconto", responsavel="cliente",
              pergunta="Aprovar o desconto desta proposta?", horas=24),
            P(id="aprovado", tipo="decisao", nome="Desconto aprovado?"),
            P(id="enviar", tipo="acao", nome="Enviar a proposta", acao="vendas.enviar_proposta", excecao=True),
            P(id="resposta", tipo="tarefa", nome="Resposta do cliente", responsavel="cliente",
              pergunta="O cliente aceitou a proposta?", horas=168),
            P(id="desfecho", tipo="acao", nome="Registrar a resposta", acao="vendas.registrar_resposta"),
            P(id="foi_aceita", tipo="decisao", nome="Aceita?"),
            P(id="aceita", tipo="fim", nome="Aceita", resultado="aceita"),
            P(id="recusada", tipo="fim", nome="Recusada", resultado="recusada"),
            P(id="nao_enviada", tipo="fim", nome="Não enviada", resultado="nao_enviada"),
        ],
        ligacoes=[
            F(de="inicio", para="montar"), F(de="montar", para="registrar"), F(de="registrar", para="desconto_alto"),
            F(de="desconto_alto", para="aprovar_desconto",
              condicao=C(campo="montar.desconto", operador=">", valor="parametros.desconto_maximo")),
            F(de="desconto_alto", para="enviar"), F(de="aprovar_desconto", para="aprovado"),
            F(de="aprovado", para="enviar", condicao=C(campo="aprovar_desconto.aprovado", operador="verdadeiro")),
            F(de="aprovado", para="nao_enviada"),
            F(de="enviar", para="resposta"), F(de="resposta", para="desfecho"), F(de="desfecho", para="foi_aceita"),
            F(de="foi_aceita", para="aceita", condicao=C(campo="desfecho.aceita", operador="verdadeiro")),
            F(de="foi_aceita", para="recusada"),
        ],
    ), indicadores=[
        I("propostas_enviadas", "Propostas enviadas", "pacote", descricao="Propostas que saíram para o cliente no mês"),
        I("taxa_aceite", "Taxa de aceite", "pacote", unidade="percentual",
          descricao="Das propostas respondidas no mês, as aceitas"),
        I("valor_aceito", "Valor aceito", "soma", unidade="moeda", campo="montar.valor", resultado="aceita",
          descricao="Soma das propostas aceitas no mês"),
    ]),
    ProcessModel("reativacao-carteira", Fluxo(
        gatilho=Trigger(tipo="agenda", agenda="0 12 * * 1", descricao="Toda segunda"),
        parametros={"dias_sem_comprar": INATIVIDADE_PADRAO},
        passos=[
            P(id="selecionar", tipo="acao", nome="Selecionar clientes parados", acao="vendas.selecionar_inativos"),
            P(id="tem_inativos", tipo="decisao", nome="Algum cliente parado?"),
            P(id="escrever", tipo="agente", nome="Escrever a campanha", excecao=True,
              objetivo="Escrever a mensagem da campanha de reativação no tom da empresa, com uma oferta das condições comerciais "
                       "do conhecimento, para os clientes que pararam de comprar",
              saidas=["mensagem"], exemplo={"mensagem": "Sentimos sua falta! Nesta semana, o pão de fermentação natural sai com 10% de desconto."}),
            P(id="enviar", tipo="acao", nome="Enviar a campanha", acao="vendas.enviar_campanha", excecao=True),
            P(id="enviada", tipo="fim", nome="Campanha enviada", resultado="enviada"),
            P(id="sem_inativos", tipo="fim", nome="Ninguém parado", resultado="sem_inativos"),
        ],
        ligacoes=[
            F(de="inicio", para="selecionar"), F(de="selecionar", para="tem_inativos"),
            F(de="tem_inativos", para="escrever", condicao=C(campo="selecionar.clientes", operador=">", valor=0)),
            F(de="tem_inativos", para="sem_inativos"), F(de="escrever", para="enviar"), F(de="enviar", para="enviada"),
        ],
    ), indicadores=[
        I("clientes_contatados", "Clientes contatados", "soma", campo="enviar.enviados",
          descricao="Clientes parados que receberam a campanha no mês"),
        I("voltaram_a_comprar", "Voltaram a comprar", "pacote",
          descricao="Clientes que compraram no mês depois de receber a campanha (proposta aceita depois dela)"),
    ]),
]
