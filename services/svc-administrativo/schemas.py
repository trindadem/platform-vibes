"""svc-administrativo · contratos (DTOs, enums, constantes). Fonte da verdade: specs/administrativo.md §2"""
from datetime import date, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.plans import Module
from core.processes import Action, Condition, Flow, Fluxo, ProcessModel, Step, Trigger
from core.resources import Email, Fields, Money, Resource, Text
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-administrativo"
TASK_QUEUE = "administrativo-queue"
EMAIL_SUBJECT = "rpc.integracoes.enviar_email"  # e-mail que sai da caixa de entrada da organização (svc-integracoes)
REQUISICOES = "administrativo_requisicoes"
TABLES = [REQUISICOES]
SEARCH = {REQUISICOES: ["item", "categoria"]}
LIVE_REQUISICOES = "administrativo.requisicoes"
WRITERS = frozenset({"owner", "admin", "operador"})
ANTECEDENCIA_PADRAO = 30  # dias antes de um vencimento em que a empresa é avisada
DOCUMENTOS_ADMISSAO = ("RG e CPF", "Carteira de trabalho (digital)", "Comprovante de residência", "Título de eleitor",
                       "PIS/NIS", "Certidão de nascimento ou casamento", "Dados bancários para o salário")

MODULE = Module("Administrativo", "Pacote de ações administrativas do BPO: admissões, compras e vencimentos da empresa",
                category="Pacotes")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


# ── Cadastros (README §5.19) ─────────────────────────────────────────────────

class Colaborador(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="Nome")
    email: Email | None = Field(None, title="E-mail")
    cargo: str | None = Field(None, max_length=120, title="Cargo")
    salario: Money | None = Field(None, title="Salário")
    inicio: date | None = Field(None, title="Início")
    status: Literal["admissao", "ativo", "desligado"] = Field("ativo", title="Situação",
                                                              json_schema_extra={"labels": {"admissao": "Em admissão"}})
    exame_em: datetime | None = Field(None, title="Exame admissional")
    acessos: Text | None = Field(None, max_length=1000, title="Acessos a criar")


class FornecedorCompra(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="Nome")
    email: Email | None = Field(None, title="E-mail", description="Para onde vão os pedidos de cotação e de compra")
    categoria: str | None = Field(None, max_length=80, title="Categoria", description="Ex.: embalagens, limpeza, insumos")


class Vencimento(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="O que vence")
    tipo: Literal["alvara", "licenca", "avcb", "seguro", "contrato_servico", "outro"] = Field(
        "outro", title="Tipo", json_schema_extra={"labels": {"alvara": "Alvará", "licenca": "Licença", "avcb": "AVCB",
                                                             "seguro": "Seguro", "contrato_servico": "Contrato de serviço"}})
    vence_em: date = Field(..., title="Vence em")
    exige_vistoria: bool = Field(False, title="Exige vistoria ou presença")
    avisado_em: date | None = Field(None, title="Avisado em", description="Quando a empresa foi avisada da renovação")


COLABORADORES = Resource(SERVICE, "colaboradores", Colaborador, "Colaboradores", search=("nome", "cargo"), sort=("nome",),
                         filters=("status",), write=tuple(WRITERS))
FORNECEDORES = Resource(SERVICE, "fornecedores", FornecedorCompra, "Fornecedores de compras", search=("nome", "categoria"),
                        sort=("nome",), unique=("nome",), write=tuple(WRITERS))
VENCIMENTOS = Resource(SERVICE, "vencimentos", Vencimento, "Vencimentos", search=("nome",), sort=("vence_em", "nome"),
                       filters=("tipo",), write=tuple(WRITERS))
RESOURCES = [COLABORADORES, FORNECEDORES, VENCIMENTOS]
ColaboradorItem = COLABORADORES.item


# ── Rotas: admissão e requisições ────────────────────────────────────────────

class NovaAdmissao(_Input):
    nome: str = Field(..., min_length=2, max_length=200, description="Quem foi contratado")
    email: Email = Field(..., description="Para onde vai o pedido de documentos")
    cargo: str = Field(..., min_length=2, max_length=120)
    salario: float | None = Field(None, gt=0)
    inicio: date | None = Field(None, description="Primeiro dia de trabalho")


class Cotacao(BaseModel):
    fornecedor: str
    valor: float
    prazo_dias: int | None = None


StatusRequisicao = Literal["aberta", "cotando", "pedido", "cancelada"]


class Requisicao(BaseModel):
    """Uma requisição de compra: as cotações que chegaram, a escolhida e o pedido."""

    id: str
    item: str
    quantidade: float
    categoria: str | None = None
    observacao: str | None = None
    status: StatusRequisicao
    cotacoes: list[Cotacao] = Field(default_factory=list)
    melhor_fornecedor: str | None = None
    melhor_valor: float | None = None
    pedido_numero: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class RequisicaoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "item")
    default_sort: ClassVar[str | None] = "-created_at"
    status: StatusRequisicao | None = None


class RequisicaoPage(Page[Requisicao]):
    pass


class NovaRequisicao(_Input):
    item: str = Field(..., min_length=2, max_length=200, description="O que comprar")
    quantidade: float = Field(..., gt=0)
    categoria: str | None = Field(None, max_length=80, description="Para escolher os fornecedores que cotam")
    observacao: str | None = Field(None, max_length=1000)


class NovaCotacao(_Input):
    requisicao: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    fornecedor: str = Field(..., min_length=2, max_length=200)
    valor: float = Field(..., gt=0, description="Valor total da cotação, em reais")
    prazo_dias: int | None = Field(None, ge=0, le=365, description="Prazo de entrega em dias")


class RequisicaoMudou(BaseModel):
    id: str
    action: Literal["aberta", "cotando", "cotacao", "pedido", "cancelada"]


# ── Ações: entradas e saídas ─────────────────────────────────────────────────

class Admissao(BaseModel):
    colaborador_id: str | None = None
    colaborador: str | None = Field(None, description="Nome de quem foi contratado")
    email: str | None = None
    cargo: str | None = None
    inicio: str | None = Field(None, description="AAAA-MM-DD")


class PedidoDocumentos(BaseModel):
    enviado_em: str = Field(..., description="AAAA-MM-DD")


class Esocial(BaseModel):
    recibo: str = Field(..., description="Recibo do evento de admissão (S-2200)")


class Assinado(BaseModel):
    assinado_em: str = Field(..., description="AAAA-MM-DD")


class Exame(BaseModel):
    exame_em: str = Field(..., description="Data e hora do exame admissional (AAAA-MM-DD HH:MM)")


class Acessos(BaseModel):
    acessos: str = Field(..., description="O que criar para o colaborador")


class Admitido(BaseModel):
    status: Literal["ativo"]


class RequisicaoIn(BaseModel):
    requisicao_id: str | None = None
    item: str | None = None
    quantidade: float | None = None
    categoria: str | None = None


class PedidoCotacao(BaseModel):
    fornecedores: int = Field(..., description="Quantos fornecedores receberam o pedido de cotação")


class RequisicaoRef(BaseModel):
    requisicao_id: str | None = None


class Comparacao(BaseModel):
    recebidas: int
    melhor_fornecedor: str
    melhor_valor: float
    prazo_dias: int | None = None


class PedidoIn(BaseModel):
    requisicao_id: str | None = None
    melhor_fornecedor: str | None = None
    melhor_valor: float | None = None


class PedidoCompra(BaseModel):
    pedido_numero: str


class Encerramento(BaseModel):
    requisicao_id: str | None = None
    aprovado: bool | None = None


class Encerrada(BaseModel):
    status: StatusRequisicao


class Antecedencia(BaseModel):
    antecedencia_dias: int | None = Field(None, description="Quantos dias antes avisar (padrão 30)")


class Vencimentos(BaseModel):
    proximos: int = Field(..., description="Quantos vencem dentro da antecedência e foram avisados agora")
    exige_presenca: int = Field(..., description="Destes, quantos exigem vistoria ou presença")
    resumo: str


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
    Action("pedir_documentos", "Pedir os documentos", "Envia ao novo colaborador a lista de documentos da admissão",
           Admissao, PedidoDocumentos, risk="externa", connections=("Caixa de entrada",),
           example=PedidoDocumentos(enviado_em="2026-10-05")),
    Action("enviar_esocial", "Enviar ao eSocial", "Lança a admissão na folha e no eSocial (S-2200)",
           Admissao, Esocial, risk="externa", connections=("eSocial ou folha",), example=Esocial(recibo="1.2.0000000000000000001")),
    Action("coletar_assinatura", "Assinar o contrato de trabalho", "Envia o contrato de trabalho para assinatura eletrônica",
           Admissao, Assinado, risk="externa", connections=("Assinatura eletrônica",), example=Assinado(assinado_em="2026-10-07")),
    Action("agendar_exame", "Agendar o exame admissional", "Marca o exame admissional antes do primeiro dia",
           Admissao, Exame, risk="escrita", example=Exame(exame_em="2026-10-06 09:00")),
    Action("criar_acessos", "Criar os acessos", "Lista e pede os acessos do colaborador conforme o cargo",
           Admissao, Acessos, risk="escrita", example=Acessos(acessos="E-mail da empresa; sistema de vendas")),
    Action("concluir_admissao", "Concluir a admissão", "Deixa o colaborador ativo e avisa a empresa",
           Admissao, Admitido, risk="escrita", example=Admitido(status="ativo")),
    Action("pedir_cotacoes", "Pedir cotações", "Pede cotação por e-mail aos fornecedores da categoria",
           RequisicaoIn, PedidoCotacao, risk="externa", connections=("Caixa de entrada",), example=PedidoCotacao(fornecedores=3)),
    Action("comparar_cotacoes", "Comparar as cotações", "Escolhe a cotação de menor valor entre as que chegaram",
           RequisicaoRef, Comparacao, risk="leitura",
           example=Comparacao(recebidas=3, melhor_fornecedor="Embalagens Sul", melhor_valor=820.0, prazo_dias=5)),
    Action("emitir_pedido", "Emitir o pedido de compra", "Envia o pedido de compra ao fornecedor escolhido",
           PedidoIn, PedidoCompra, risk="externa", connections=("Caixa de entrada",), example=PedidoCompra(pedido_numero="PC-2026-0001")),
    Action("encerrar_requisicao", "Encerrar a requisição", "Cancela a requisição que a empresa não aprovou",
           Encerramento, Encerrada, risk="escrita", example=Encerrada(status="cancelada")),
    Action("verificar_vencimentos", "Verificar vencimentos", "Avisa a empresa do que vence dentro da antecedência e inicia a renovação",
           Antecedencia, Vencimentos, risk="escrita",
           example=Vencimentos(proximos=1, exige_presenca=0, resumo="Seguro do estabelecimento vence em 25/10.")),
]

C, F, P = Condition, Flow, Step
MODELS = [
    ProcessModel("admissao-colaborador", Fluxo(
        gatilho=Trigger(tipo="evento", evento="administrativo.admissao", descricao="Contratação aprovada"),
        passos=[
            P(id="pedir_documentos", tipo="acao", nome="Pedir os documentos", acao="administrativo.pedir_documentos", excecao=True),
            P(id="validar", tipo="tarefa", nome="Validar os documentos", responsavel="staff",
              pergunta="Os documentos do colaborador chegaram e estão válidos?", horas=72),
            P(id="validos", tipo="decisao", nome="Documentos válidos?"),
            P(id="abrir", tipo="paralelo", nome="Ao mesmo tempo"),
            P(id="esocial", tipo="acao", nome="Enviar ao eSocial", acao="administrativo.enviar_esocial", excecao=True),
            P(id="contrato", tipo="acao", nome="Assinar o contrato", acao="administrativo.coletar_assinatura", excecao=True),
            P(id="exame", tipo="acao", nome="Agendar o exame", acao="administrativo.agendar_exame"),
            P(id="acessos", tipo="acao", nome="Criar os acessos", acao="administrativo.criar_acessos"),
            P(id="juntar", tipo="paralelo", nome="Tudo pronto"),
            P(id="concluir", tipo="acao", nome="Concluir a admissão", acao="administrativo.concluir_admissao"),
            P(id="admitido", tipo="fim", nome="Admitido", resultado="admitido"),
            P(id="pendente", tipo="fim", nome="Documento pendente", resultado="pendente"),
        ],
        ligacoes=[
            F(de="inicio", para="pedir_documentos"), F(de="pedir_documentos", para="validar"), F(de="validar", para="validos"),
            F(de="validos", para="abrir", condicao=C(campo="validar.aprovado", operador="verdadeiro")),
            F(de="validos", para="pendente"),
            F(de="abrir", para="esocial"), F(de="abrir", para="contrato"), F(de="abrir", para="exame"), F(de="abrir", para="acessos"),
            F(de="esocial", para="juntar"), F(de="contrato", para="juntar"), F(de="exame", para="juntar"), F(de="acessos", para="juntar"),
            F(de="juntar", para="concluir"), F(de="concluir", para="admitido"),
        ],
    )),
    ProcessModel("compras-cotacao", Fluxo(
        gatilho=Trigger(tipo="evento", evento="administrativo.requisicao", descricao="Requisição interna"),
        passos=[
            P(id="cotar", tipo="acao", nome="Pedir cotações", acao="administrativo.pedir_cotacoes", excecao=True),
            P(id="prazo", tipo="espera", nome="Prazo das cotações", espera="tempo", horas=48),
            P(id="comparar", tipo="acao", nome="Comparar as cotações", acao="administrativo.comparar_cotacoes", excecao=True),
            P(id="aprovar", tipo="tarefa", nome="Aprovar a compra", responsavel="cliente",
              pergunta="Aprovar a compra pela melhor cotação?", horas=24),
            P(id="aprovado", tipo="decisao", nome="Aprovada?"),
            P(id="pedido", tipo="acao", nome="Emitir o pedido", acao="administrativo.emitir_pedido", excecao=True),
            P(id="entrega", tipo="tarefa", nome="Conferir a entrega", responsavel="cliente",
              pergunta="A entrega chegou completa?", horas=240),
            P(id="cancelar", tipo="acao", nome="Encerrar a requisição", acao="administrativo.encerrar_requisicao"),
            P(id="entregue", tipo="fim", nome="Entregue", resultado="entregue"),
            P(id="cancelada", tipo="fim", nome="Cancelada", resultado="cancelada"),
        ],
        ligacoes=[
            F(de="inicio", para="cotar"), F(de="cotar", para="prazo"), F(de="prazo", para="comparar"), F(de="comparar", para="aprovar"),
            F(de="aprovar", para="aprovado"),
            F(de="aprovado", para="pedido", condicao=C(campo="aprovar.aprovado", operador="verdadeiro")),
            F(de="aprovado", para="cancelar"), F(de="cancelar", para="cancelada"),
            F(de="pedido", para="entrega"), F(de="entrega", para="entregue"),
        ],
    )),
    ProcessModel("vencimentos-empresa", Fluxo(
        gatilho=Trigger(tipo="agenda", agenda="0 11 * * *", descricao="Todo dia"),
        parametros={"antecedencia_dias": ANTECEDENCIA_PADRAO},
        passos=[
            P(id="verificar", tipo="acao", nome="Verificar vencimentos", acao="administrativo.verificar_vencimentos"),
            P(id="presenca", tipo="decisao", nome="Exige vistoria?"),
            P(id="vistoria", tipo="tarefa", nome="Agendar a vistoria", responsavel="cliente",
              pergunta="A renovação exige vistoria ou presença: já está agendada?", horas=48),
            P(id="em_dia", tipo="fim", nome="Em dia", resultado="em_dia"),
        ],
        ligacoes=[
            F(de="inicio", para="verificar"), F(de="verificar", para="presenca"),
            F(de="presenca", para="vistoria", condicao=C(campo="verificar.exige_presenca", operador=">", valor=0)),
            F(de="presenca", para="em_dia"), F(de="vistoria", para="em_dia"),
        ],
    )),
]
