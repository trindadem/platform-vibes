"""svc-financeiro · contratos (DTOs, enums, constantes). Fonte da verdade: specs/financeiro.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.plans import Module
from core.processes import Action, Condition, Flow, Fluxo, ProcessModel, Step, Trigger
from core.resources import Fields, Money, Resource
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-financeiro"
TASK_QUEUE = "financeiro-queue"
AGENDAR_SUBJECT = "rpc.integracoes.banco_agendar"  # o banco da organização (svc-integracoes)
COBRAR_SUBJECT = "rpc.integracoes.banco_cobrar"  # emite a cobrança (boleto) no banco da organização
EXTRATO_SUBJECT = "rpc.integracoes.banco_extrato"  # o extrato do banco da organização (conciliação)
EMAIL_SUBJECT = "rpc.integracoes.enviar_email"  # e-mail que sai da caixa de entrada da organização
TITULOS = "financeiro_titulos"
FATURAS = "financeiro_faturas"
TABLES = [TITULOS, FATURAS]
UNIQUE = {TITULOS: ["pagamento_id"]}
CONTA_PADRAO = "2.1.01 Fornecedores"
LIVE_TITULOS = "financeiro.titulos"
LIVE_FATURAS = "financeiro.faturas"
PRAZO_PADRAO = 15  # dias até o vencimento de uma fatura, quando o processo não diz
ALIQUOTA_PADRAO = 6.0  # % do Simples Nacional (anexo III, primeira faixa), quando o processo não diz
REGUA = {"D-3": "vence em 3 dias", "D+1": "venceu ontem", "D+7": "está vencida há uma semana"}  # lembretes da cobrança

MODULE = Module("Financeiro", "Pacote de ações financeiras do BPO: contas a pagar, conciliação, cobrança e fechamento",
                category="Pacotes")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _chave(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


# Cadastro (README §5.19): os fornecedores que a empresa paga. A conferência usa o valor do contrato e a
# classificação usa a conta; fornecedor que não está aqui é "novo" (e entra aqui ao ser classificado).
class Fornecedor(Fields):
    nome: str = Field(..., min_length=2, max_length=200, title="Nome")
    cnpj: str | None = Field(None, max_length=20, title="CNPJ")
    conta: str = Field(CONTA_PADRAO, min_length=2, max_length=80, title="Conta do plano de contas")
    centro_custo: str | None = Field(None, max_length=80, title="Centro de custo")
    valor_contrato: Money | None = Field(None, title="Valor do contrato", description="Mensal; documento com outro valor diverge")


FORNECEDORES = Resource(SERVICE, "fornecedores", Fornecedor, "Fornecedores", search=("nome", "cnpj"), sort=("nome",),
                        unique=("nome",), write=("owner", "admin", "operador"))
RESOURCES = [FORNECEDORES]


# ── Contas a pagar ───────────────────────────────────────────────────────────

class Documento(BaseModel):
    fornecedor: str | None = Field(None, description="Razão social ou nome do fornecedor")
    cnpj: str | None = None
    valor: float | None = Field(None, description="Valor do documento, em reais")
    vencimento: str | None = Field(None, description="Data de vencimento (AAAA-MM-DD)")
    linha_digitavel: str | None = None


class Conferencia(BaseModel):
    divergente: bool = Field(..., description="O valor ou o fornecedor não batem com o pedido ou o contrato")
    diferenca: float = Field(0, description="Diferença entre o documento e o pedido, em reais")
    pedido: str | None = Field(None, description="Pedido ou contrato encontrado")
    fornecedor_novo: bool = Field(False, description="Fornecedor que a empresa nunca pagou")


class Classificacao(BaseModel):
    conta: str = Field(..., description="Conta do plano de contas")
    centro_custo: str | None = None


class Pagamento(BaseModel):
    valor: float
    vencimento: str
    fornecedor: str | None = None
    linha_digitavel: str | None = None


class Agendamento(BaseModel):
    pagamento_id: str = Field(..., description="Identificador do pagamento no banco (chave do comprovante)")
    data: str = Field(..., description="Data agendada (AAAA-MM-DD)")


class Comprovante(BaseModel):
    pagamento_id: str


class Conciliacao(BaseModel):
    conciliado: bool
    diferenca: float = 0


# ── Conciliação bancária ─────────────────────────────────────────────────────

class Janela(BaseModel):
    dias: int | None = Field(None, description="Quantos dias de extrato conferir (vazio: desde ontem)")


class ConciliacaoDia(BaseModel):
    lancamentos: int = Field(..., description="Lançamentos do extrato no período")
    conciliados: int = Field(..., description="Lançamentos que casaram com um título ou uma fatura")
    sem_par: int = Field(..., description="Lançamentos sem título nem fatura")
    valor_sem_par: float = Field(0, description="Soma dos lançamentos sem par, em reais")


# ── Faturamento e cobrança ───────────────────────────────────────────────────

class Faturamento(BaseModel):
    cliente: str | None = Field(None, description="Quem paga")
    cnpj: str | None = None
    email: str | None = Field(None, description="Para onde vai a cobrança")
    descricao: str | None = Field(None, description="O que foi vendido")
    valor: float | None = Field(None, description="Valor a faturar, em reais")
    prazo_pagamento: int | None = Field(None, description="Dias até o vencimento (vazio: 15)")
    vencimento: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                                   description="AAAA-MM-DD, quando a data já foi combinada (a mensalidade do plano); vale mais que o prazo")
    proposta_id: str | None = Field(None, description="A proposta aceita que originou a venda")


class FaturaAberta(BaseModel):
    fatura_id: str
    vencimento: str = Field(..., description="AAAA-MM-DD")


class NotaIn(BaseModel):
    fatura_id: str


class Nota(BaseModel):
    nota_numero: str = Field(..., description="Número da NFS-e emitida")


class CobrancaIn(BaseModel):
    fatura_id: str
    nota_numero: str | None = None


class Cobranca(BaseModel):
    cobranca_id: str = Field(..., description="A cobrança no banco (chave do recebimento)")
    linha_digitavel: str
    vencimento: str
    enviada: bool = Field(False, description="O boleto foi por e-mail ao cliente")


class Recebimento(BaseModel):
    cobranca_id: str


class Baixa(BaseModel):
    recebido: bool = Field(..., description="O banco confirmou o recebimento")
    valor: float = 0


# ── Fechamento do mês ────────────────────────────────────────────────────────

class Mes(BaseModel):
    referencia: str | None = Field(None, description="Mês (AAAA-MM); vazio: o mês passado")


class Pendencias(BaseModel):
    referencia: str = Field(..., description="Mês (AAAA-MM)")
    pendencias: int = Field(..., description="O que falta para fechar: pagamentos sem comprovante, faturas sem nota")
    resumo: str


class EnvioContador(BaseModel):
    email_contador: str | None = Field(None, description="E-mail do escritório contábil (parâmetro do processo)")
    referencia: str | None = None


class Envio(BaseModel):
    enviado_em: str = Field(..., description="AAAA-MM-DD")


class Apuracao(BaseModel):
    referencia: str | None = None
    aliquota: float | None = Field(None, description="Alíquota efetiva do Simples (%); vazio: 6")


class Das(BaseModel):
    valor: float = Field(..., description="Valor do DAS, em reais")
    vencimento: str = Field(..., description="Dia 20 do mês seguinte (AAAA-MM-DD)")
    fornecedor: str = Field("Receita Federal — DAS", description="A quem se paga")
    linha_digitavel: str | None = None


class Dre(BaseModel):
    referencia: str
    receita: float
    despesas: float
    resultado: float
    resumo: str


# ── Do svc-integracoes (rpc.integracoes.*): os contratos repetidos aqui, de quem consome ──

class AgendarPagamento(BaseModel):
    valor: float
    vencimento: str | None = None
    fornecedor: str | None = None
    linha_digitavel: str | None = None


class PagamentoAgendado(BaseModel):
    pagamento_id: str
    data: str


class CobrarNoBanco(BaseModel):
    valor: float
    vencimento: str
    pagador: str | None = None
    descricao: str | None = None


class CobrancaEmitida(BaseModel):
    cobranca_id: str
    linha_digitavel: str
    vencimento: str


class ExtratoPedido(BaseModel):
    desde: str


class Lancamento(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tipo: Literal["pagamento", "recebimento"]
    id: str = Field(..., description="pagamento_id (pagamento) ou cobranca_id (recebimento)")
    valor: float
    data: str
    descricao: str | None = None


class Extrato(BaseModel):
    itens: list[Lancamento]


class EnviarEmail(BaseModel):
    para: str
    assunto: str
    texto: str


class EmailEnviado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mensagem_id: str
    de: str


# ── Telas: títulos (contas a pagar) e faturas (contas a receber) ─────────────

class Titulo(BaseModel):
    """Uma conta a pagar que o processo agendou: do agendamento à conciliação."""

    id: str
    fornecedor: str | None = None
    valor: float
    vencimento: str | None = None
    data: str = Field(..., description="Data agendada no banco")
    pagamento_id: str
    status: Literal["agendado", "pago"]
    conciliado: bool = Field(False, description="Casou com o extrato do banco")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _chave(value)


class TituloQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "data", "valor")
    default_sort: ClassVar[str | None] = "-created_at"
    status: Literal["agendado", "pago"] | None = None


class TituloPage(Page[Titulo]):
    pass


class TituloMudou(BaseModel):
    id: str
    action: Literal["agendado", "pago", "conciliado"]


StatusFatura = Literal["aberta", "cobrada", "paga"]


class Fatura(BaseModel):
    """Uma venda faturada pelo processo: nota, cobrança no banco, régua de lembretes e recebimento."""

    id: str
    cliente: str
    cnpj: str | None = None
    email: str | None = None
    descricao: str | None = None
    valor: float
    vencimento: str
    nota_numero: str | None = None
    cobranca_id: str | None = None
    linha_digitavel: str | None = None
    status: StatusFatura
    regua: list[str] = Field(default_factory=list, description="Lembretes já enviados (D-3, D+1, D+7)")
    recebido_em: datetime | None = None
    conciliada: bool = False
    proposta_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _chave(value)


class FaturaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "vencimento", "valor")
    default_sort: ClassVar[str | None] = "-created_at"
    status: StatusFatura | None = None


class FaturaPage(Page[Fatura]):
    pass


class FaturaMudou(BaseModel):
    id: str
    action: Literal["aberta", "cobrada", "paga", "lembrete"]


class Regua(BaseModel):
    """O que a régua de cobrança enviou numa rodada (agendamento diário)."""

    lembretes: int


# ── Ações (o que os passos chamam) e modelos (o desenho de cada organização começa daqui) ──

ACTIONS = [
    Action("conferir_pedido", "Conferir com o pedido", "Compara o documento com o pedido ou o contrato e diz se diverge",
           Documento, Conferencia, risk="leitura",
           example=Conferencia(divergente=False, diferenca=0, pedido="PC-1042", fornecedor_novo=False)),
    Action("classificar", "Classificar no plano de contas", "Escolhe a conta e o centro de custo pelas regras aprendidas",
           Documento, Classificacao, risk="escrita", example=Classificacao(conta="2.1.01 Fornecedores", centro_custo="Produção")),
    Action("agendar_pagamento", "Agendar pagamento", "Agenda o pagamento no banco da empresa para o vencimento",
           Pagamento, Agendamento, risk="irreversivel", connections=("Banco",),
           example=Agendamento(pagamento_id="PG-88231", data="2026-10-15")),
    Action("conciliar", "Conciliar o comprovante", "Casa o comprovante do banco com o lançamento do pagamento",
           Comprovante, Conciliacao, risk="escrita", connections=("Banco",), example=Conciliacao(conciliado=True)),
    Action("conciliar_extrato", "Conciliar o extrato", "Casa o extrato do banco com os pagamentos e os recebimentos da empresa",
           Janela, ConciliacaoDia, risk="escrita", connections=("Banco",),
           example=ConciliacaoDia(lancamentos=12, conciliados=12, sem_par=0, valor_sem_par=0)),
    Action("faturar", "Faturar a venda", "Abre a fatura do cliente com o valor e o vencimento",
           Faturamento, FaturaAberta, risk="escrita", example=FaturaAberta(fatura_id="ft1", vencimento="2026-10-30")),
    Action("emitir_nota", "Emitir a nota fiscal", "Emite a NFS-e da fatura na prefeitura",
           NotaIn, Nota, risk="externa", connections=("NFS-e",), example=Nota(nota_numero="2026/000123")),
    Action("cobrar", "Cobrar o cliente", "Emite o boleto no banco e envia a cobrança ao cliente por e-mail",
           CobrancaIn, Cobranca, risk="externa", connections=("Banco", "Caixa de entrada"),
           example=Cobranca(cobranca_id="CB-1A2B3C4D", linha_digitavel="34191.79001 01043.510047 91020.150008 1 10000000480000",
                            vencimento="2026-10-30", enviada=True)),
    Action("baixar", "Baixar o recebimento", "Dá baixa na fatura que o banco confirmou como recebida",
           Recebimento, Baixa, risk="escrita", example=Baixa(recebido=True, valor=4800.0)),
    Action("pendencias_do_mes", "Levantar pendências do mês", "Lista o que falta para fechar o mês: comprovantes e notas",
           Mes, Pendencias, risk="leitura", example=Pendencias(referencia="2026-09", pendencias=0, resumo="Nada pendente.")),
    Action("enviar_ao_contador", "Enviar ao contador", "Envia ao escritório contábil o resumo e os lançamentos do mês",
           EnvioContador, Envio, risk="externa", connections=("Caixa de entrada",), example=Envio(enviado_em="2026-10-01")),
    Action("apurar_das", "Apurar o DAS", "Calcula o DAS do Simples pela receita do mês e a alíquota",
           Apuracao, Das, risk="escrita", example=Das(valor=288.0, vencimento="2026-10-20")),
    Action("montar_dre", "Montar a DRE gerencial", "Soma receitas e despesas do mês e avisa a empresa com o resumo",
           Mes, Dre, risk="escrita",
           example=Dre(referencia="2026-09", receita=4800.0, despesas=3100.0, resultado=1700.0, resumo="Lucro de R$ 1.700,00.")),
]

C, F, P = Condition, Flow, Step
MODELS = [
    ProcessModel("contas-a-pagar", Fluxo(
        gatilho=Trigger(tipo="evento", evento="documento.recebido", descricao="Boleto ou NF chega"),
        parametros={"limite_aprovacao": 5000},
        passos=[
            P(id="ler_documento", tipo="agente", nome="Ler o documento", excecao=True, leitura=True,
              objetivo="Extrair do boleto ou da nota o fornecedor, o CNPJ, o valor, o vencimento e a linha digitável",
              saidas=["fornecedor", "cnpj", "valor", "vencimento", "linha_digitavel"],
              exemplo={"fornecedor": "Moinho Sul", "cnpj": "12.345.678/0001-90", "valor": 1250.0, "vencimento": "2026-10-15"}),
            P(id="conferir", tipo="acao", nome="Conferir com o pedido", acao="financeiro.conferir_pedido"),
            P(id="divergente", tipo="decisao", nome="Confere com o pedido?"),
            P(id="revisar", tipo="tarefa", nome="Resolver divergência", responsavel="staff", pergunta="Seguir com o pagamento?", horas=24),
            P(id="revisado", tipo="decisao", nome="Seguir?"),
            P(id="precisa_aprovacao", tipo="decisao", nome="Precisa de aprovação?"),
            P(id="aprovar", tipo="tarefa", nome="Aprovar o pagamento", responsavel="cliente", pergunta="Aprovar o pagamento?", horas=24),
            P(id="aprovado", tipo="decisao", nome="Aprovado?"),
            P(id="classificar", tipo="acao", nome="Classificar no plano de contas", acao="financeiro.classificar"),
            P(id="agendar", tipo="acao", nome="Agendar o pagamento", acao="financeiro.agendar_pagamento", excecao=True),
            P(id="aguardar", tipo="espera", nome="Aguardar comprovante", espera="mensagem", mensagem="banco.pago",
              chave="agendar.pagamento_id", horas=48),
            P(id="conciliar", tipo="acao", nome="Conciliar", acao="financeiro.conciliar"),
            P(id="pago", tipo="fim", nome="Pago", resultado="pago"),
            P(id="recusado", tipo="fim", nome="Recusado", resultado="recusado"),
        ],
        ligacoes=[
            F(de="inicio", para="ler_documento"), F(de="ler_documento", para="conferir"), F(de="conferir", para="divergente"),
            F(de="divergente", para="revisar", condicao=C(campo="conferir.divergente", operador="verdadeiro")),
            F(de="divergente", para="precisa_aprovacao"),
            F(de="revisar", para="revisado"),
            F(de="revisado", para="precisa_aprovacao", condicao=C(campo="revisar.aprovado", operador="verdadeiro")),
            F(de="revisado", para="recusado"),
            F(de="precisa_aprovacao", para="aprovar",
              condicao=C(campo="ler_documento.valor", operador=">", valor="parametros.limite_aprovacao")),
            F(de="precisa_aprovacao", para="classificar"),
            F(de="aprovar", para="aprovado"),
            F(de="aprovado", para="classificar", condicao=C(campo="aprovar.aprovado", operador="verdadeiro")),
            F(de="aprovado", para="recusado"),
            F(de="classificar", para="agendar"), F(de="agendar", para="aguardar"), F(de="aguardar", para="conciliar"),
            F(de="conciliar", para="pago"),
        ],
    )),
    ProcessModel("conciliacao-bancaria", Fluxo(
        gatilho=Trigger(tipo="agenda", agenda="0 11 * * *", descricao="Todo dia"),
        parametros={"tolerancia": 50},
        passos=[
            P(id="conciliar_dia", tipo="acao", nome="Conciliar o extrato", acao="financeiro.conciliar_extrato", excecao=True),
            P(id="sobrou", tipo="decisao", nome="Sobrou lançamento sem par?"),
            P(id="revisar", tipo="tarefa", nome="Classificar lançamentos sem par", responsavel="staff",
              pergunta="Os lançamentos sem par foram classificados?", horas=24),
            P(id="conciliado", tipo="fim", nome="Conciliado", resultado="conciliado"),
            P(id="revisado", tipo="fim", nome="Revisado pelo staff", resultado="revisado"),
        ],
        ligacoes=[
            F(de="inicio", para="conciliar_dia"), F(de="conciliar_dia", para="sobrou"),
            F(de="sobrou", para="revisar", condicao=C(campo="conciliar_dia.valor_sem_par", operador=">", valor="parametros.tolerancia")),
            F(de="sobrou", para="conciliado"), F(de="revisar", para="revisado"),
        ],
    )),
    ProcessModel("faturamento-cobranca", Fluxo(
        gatilho=Trigger(tipo="processo", processo="proposta-comercial", resultado="aceita", descricao="Proposta aceita"),
        parametros={"prazo_pagamento": PRAZO_PADRAO},
        passos=[
            P(id="faturar", tipo="acao", nome="Faturar a venda", acao="financeiro.faturar", excecao=True),
            P(id="emitir", tipo="acao", nome="Emitir a nota fiscal", acao="financeiro.emitir_nota", excecao=True),
            P(id="cobrar", tipo="acao", nome="Cobrar o cliente", acao="financeiro.cobrar", excecao=True),
            P(id="receber", tipo="espera", nome="Aguardar o pagamento", espera="mensagem", mensagem="banco.recebido",
              chave="cobrar.cobranca_id", horas=24 * 25),
            P(id="baixar", tipo="acao", nome="Baixar o recebimento", acao="financeiro.baixar"),
            P(id="pago", tipo="decisao", nome="Recebeu?"),
            P(id="recebido", tipo="fim", nome="Recebido", resultado="recebido"),
            P(id="inadimplente", tipo="fim", nome="Inadimplente", resultado="inadimplente"),
        ],
        ligacoes=[
            F(de="inicio", para="faturar"), F(de="faturar", para="emitir"), F(de="emitir", para="cobrar"),
            F(de="cobrar", para="receber"), F(de="receber", para="baixar"), F(de="baixar", para="pago"),
            F(de="pago", para="recebido", condicao=C(campo="baixar.recebido", operador="verdadeiro")),
            F(de="pago", para="inadimplente"),
        ],
    )),
    ProcessModel("fechamento-mes", Fluxo(
        gatilho=Trigger(tipo="agenda", agenda="0 11 1 * *", descricao="Dia 1"),
        parametros={"email_contador": "", "aliquota": ALIQUOTA_PADRAO},
        passos=[
            P(id="pendencias", tipo="acao", nome="Levantar pendências", acao="financeiro.pendencias_do_mes"),
            P(id="faltam", tipo="decisao", nome="Falta documento?"),
            P(id="cobrar_documentos", tipo="tarefa", nome="Enviar o que falta", responsavel="cliente",
              pergunta="Você enviou os documentos que faltam para fechar o mês?", horas=72),
            P(id="enviar_contador", tipo="acao", nome="Enviar ao contador", acao="financeiro.enviar_ao_contador", excecao=True),
            P(id="apurar", tipo="acao", nome="Apurar o DAS", acao="financeiro.apurar_das"),
            P(id="tem_das", tipo="decisao", nome="Tem DAS a pagar?"),
            P(id="aprovar_das", tipo="tarefa", nome="Aprovar o DAS", responsavel="cliente", pergunta="Pagar o DAS do mês?", horas=48),
            P(id="aprovado", tipo="decisao", nome="Aprovado?"),
            P(id="pagar_das", tipo="acao", nome="Agendar o DAS", acao="financeiro.agendar_pagamento", excecao=True),
            P(id="dre", tipo="acao", nome="Montar a DRE", acao="financeiro.montar_dre"),
            P(id="fechado", tipo="fim", nome="Mês fechado", resultado="fechado"),
        ],
        ligacoes=[
            F(de="inicio", para="pendencias"), F(de="pendencias", para="faltam"),
            F(de="faltam", para="cobrar_documentos", condicao=C(campo="pendencias.pendencias", operador=">", valor=0)),
            F(de="faltam", para="enviar_contador"), F(de="cobrar_documentos", para="enviar_contador"),
            F(de="enviar_contador", para="apurar"), F(de="apurar", para="tem_das"),
            F(de="tem_das", para="aprovar_das", condicao=C(campo="apurar.valor", operador=">", valor=0)),
            F(de="tem_das", para="dre"), F(de="aprovar_das", para="aprovado"),
            F(de="aprovado", para="pagar_das", condicao=C(campo="aprovar_das.aprovado", operador="verdadeiro")),
            F(de="aprovado", para="dre"), F(de="pagar_das", para="dre"), F(de="dre", para="fechado"),
        ],
    )),
]
