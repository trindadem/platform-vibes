"""svc-processos · contratos (DTOs, enums, constantes). Fonte da verdade: specs/processos.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.plans import Module
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-processos"
TASK_QUEUE = "processos-queue"
TRIGGER_SUBJECT = "events.processos.trigger"
PROCESSED_SUBJECT = "events.processos.processed"
LIVE_PROCESSOS = "processos.processos"
CONTEXTO_SUBJECT = "rpc.conhecimento.contexto"  # do svc-conhecimento: perfil e tópicos da empresa
BUSCA_SUBJECT = "rpc.conhecimento.busca"  # do svc-conhecimento: busca no conhecimento

PROCESSOS = "processos_processos"
TABLES = [PROCESSOS]
SEARCH = {PROCESSOS: ["titulo", "descricao"]}
WRITERS = frozenset({"owner", "admin"})

MODULE = Module(
    "Processos",
    "Os processos que a Cogniventure executa para a empresa: sugeridos, descritos e aceitos",
    category="Sua empresa",
)


class ProcessosSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROCESSOS_", extra="ignore")

    model: str = Field("cv/agente", description="Modelo dos agentes de descoberta e descrição, como cadastrado no svc-ai")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


# ── Biblioteca: o que a Cogniventure executa (briefing.md §10) ───────────────

Area = Literal["financeiro", "juridico", "administrativo", "vendas"]
ModeloId = Literal[
    "contas-a-pagar", "conciliacao-bancaria", "faturamento-cobranca", "fechamento-mes",
    "gestao-contratos", "publicacoes-processos", "certidoes-negativas",
    "admissao-colaborador", "compras-cotacao", "vencimentos-empresa",
    "qualificacao-leads", "proposta-comercial", "reativacao-carteira",
]


class ModeloProcesso(BaseModel):
    id: ModeloId
    area: Area
    titulo: str
    resumo: str
    gatilho: str
    roda_sozinho: str = Field(..., description="O que agentes e automações fazem sem ninguém")
    handoff: str = Field(..., description="Quando uma pessoa entra (a exceção)")
    integracoes: list[str] = Field(default_factory=list, description="O que precisa estar conectado")
    sinais: list[str] = Field(default_factory=list, description="O que, no perfil, indica que o processo serve")


def _m(id: str, area: str, titulo: str, resumo: str, gatilho: str, roda: str, handoff: str, integracoes: list[str],
       sinais: list[str]) -> ModeloProcesso:
    return ModeloProcesso(id=id, area=area, titulo=titulo, resumo=resumo, gatilho=gatilho, roda_sozinho=roda,
                          handoff=handoff, integracoes=integracoes, sinais=sinais)


BIBLIOTECA: list[ModeloProcesso] = [
    _m("contas-a-pagar", "financeiro", "Contas a pagar", "Boletos e notas que chegam viram pagamentos agendados e conciliados.",
       "Boleto ou NF chega por e-mail ou WhatsApp",
       "Agente extrai fornecedor, valor, vencimento e linha digitável; confere com o pedido ou contrato; classifica no "
       "plano de contas; agenda o pagamento no banco; concilia o comprovante",
       "Valor diferente do pedido, fornecedor novo, documento ilegível; aprovação do cliente acima de um valor",
       ["Caixa de entrada", "Banco"], ["paga fornecedores por boleto", "notas e boletos chegam por e-mail", "atraso em pagamentos"]),
    _m("conciliacao-bancaria", "financeiro", "Conciliação bancária", "Extratos casados com os lançamentos todo dia.",
       "Todo dia", "Puxa extratos (Open Finance ou OFX), casa com os lançamentos e classifica pelas regras aprendidas",
       "Lançamento sem par acima da tolerância", ["Banco"], ["conciliar o caixa toma tempo", "muitos recebimentos por Pix e cartão"]),
    _m("faturamento-cobranca", "financeiro", "Faturamento e cobrança", "Notas emitidas, cobrança enviada e régua de lembretes.",
       "Pedido entregue ou contrato do mês",
       "Emite a NFS-e, envia boleto ou Pix e roda a régua (D-3, D+1, D+7 no WhatsApp); negocia dentro dos limites do briefing",
       "Inadimplente além de N dias ou desconto fora do limite", ["Prefeitura (NFS-e)", "Banco", "WhatsApp"],
       ["vende a prazo ou por contrato", "clientes empresas", "inadimplência"]),
    _m("fechamento-mes", "financeiro", "Fechamento do mês", "Documentos ao contador, impostos pagos e DRE gerencial.",
       "Dia 1", "Cobra do cliente os documentos que faltam, envia ao escritório contábil, gera e paga o DAS e monta a DRE "
       "gerencial com um resumo", "Documento que não chega ou divergência no imposto", ["E-mail do contador", "Banco"],
       ["contabilidade externa", "Simples Nacional", "quer números confiáveis"]),
    _m("gestao-contratos", "juridico", "Gestão de contratos", "Contratos lidos, comparados ao padrão e vigiados até o vencimento.",
       "Contrato recebido", "Agente extrai partes, valores, vigência, multa, reajuste e renovação; compara com o padrão da "
       "empresa; arquiva e avisa 60 e 30 dias antes de vencer ou reajustar", "Cláusula de risco alto: o advogado revisa",
       ["Caixa de entrada", "Assinatura eletrônica"], ["contratos com clientes ou fornecedores", "aluguel", "serviços recorrentes"]),
    _m("publicacoes-processos", "juridico", "Publicações e processos", "Intimações encontradas, resumidas e com prazo calculado.",
       "Todo dia", "Consulta tribunais e diários pelo CNPJ, resume cada intimação e calcula o prazo",
       "Toda intimação vira tarefa com prazo para o advogado (handoff obrigatório)", ["Tribunais e diários oficiais"],
       ["processos judiciais", "ações trabalhistas", "advogado externo"]),
    _m("certidoes-negativas", "juridico", "Certidões negativas", "Certidões emitidas, guardadas e renovadas antes de vencer.",
       "Todo mês", "Emite as certidões (Receita/PGFN, FGTS, trabalhista, estadual, municipal), guarda e avisa o vencimento",
       "Certidão positiva ou irregularidade", ["Portais da Receita, Caixa, TST, Sefaz e prefeitura"],
       ["vende para empresas ou governo", "licitações", "financiamento"]),
    _m("admissao-colaborador", "administrativo", "Admissão de colaborador", "Do sim ao primeiro dia: documentos, eSocial, contrato e acessos.",
       "Contratação aprovada", "Coleta documentos por formulário ou WhatsApp, valida, envia à folha e ao eSocial, manda o "
       "contrato para assinatura eletrônica, agenda o exame e cria acessos", "Documento inválido ou pendência no eSocial",
       ["eSocial ou folha", "Assinatura eletrônica", "WhatsApp"], ["equipe crescendo", "rotatividade", "contrata com frequência"]),
    _m("compras-cotacao", "administrativo", "Compras e cotação", "Requisições viram três cotações, pedido e entrega acompanhada.",
       "Requisição interna", "Pede 3 cotações, compara e, aprovado pelo cliente, emite o pedido e acompanha a entrega; a NF "
       "entra no contas a pagar", "Fornecedor sem resposta ou item fora do catálogo", ["E-mail ou WhatsApp dos fornecedores"],
       ["compra insumos com frequência", "gerente cuida das compras", "regra de cotação"]),
    _m("vencimentos-empresa", "administrativo", "Vencimentos da empresa", "Alvarás, licenças, seguros e contratos de serviço renovados a tempo.",
       "Todo dia", "Alvarás, licenças, AVCB, seguros e contratos de serviço: avisa e inicia a renovação",
       "Renovação que exige presença ou vistoria", [], ["estabelecimento físico", "vigilância sanitária", "alvará"]),
    _m("qualificacao-leads", "vendas", "Qualificação de leads", "Lead respondido em minutos, qualificado e com reunião marcada.",
       "Lead no site, Instagram ou WhatsApp", "Agente responde em minutos, qualifica pelo perfil de cliente ideal, agenda a "
       "reunião com o vendedor e registra no CRM; lead frio vai para nutrição", "Cliente pede humano ou pedido fora do padrão",
       ["WhatsApp", "Site ou Instagram", "Agenda"], ["vende pelo WhatsApp ou Instagram", "encomendas", "atendimento demora"]),
    _m("proposta-comercial", "vendas", "Proposta comercial", "Propostas montadas com a tabela e acompanhadas até a resposta.",
       "Pedido de proposta", "Monta com a tabela e as condições do conhecimento, envia e faz os follow-ups",
       "Desconto acima do limite: aprovação do cliente", ["E-mail ou WhatsApp"], ["vende para empresas", "encomendas grandes", "tabela de preços"]),
    _m("reativacao-carteira", "vendas", "Reativação de carteira", "Clientes parados há 90 dias recebem uma campanha que vira oportunidade.",
       "Cliente sem comprar há 90 dias", "Campanha personalizada; as respostas viram oportunidades no CRM",
       "Resposta com reclamação", ["WhatsApp ou e-mail"], ["clientes recorrentes", "base de clientes cadastrada"]),
]


class Biblioteca(BaseModel):
    itens: list[ModeloProcesso]


# ── Processos da organização ─────────────────────────────────────────────────

Status = Literal["sugerido", "aceito", "recusado"]
Prioridade = Literal["alta", "media", "baixa"]


class Processo(BaseModel):
    id: str
    modelo: ModeloId | None = Field(None, description="Modelo da biblioteca; vazio num processo só da empresa")
    area: Area
    titulo: str
    descricao: str
    motivo: str | None = Field(None, description="Por que o agente sugeriu (o que no briefing indica o processo)")
    origem: Literal["sugestao", "cliente"]
    status: Status
    prioridade: Prioridade = "media"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class ProcessoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "titulo", "prioridade")
    default_sort: ClassVar[str | None] = "-created_at"
    status: Status | None = None
    area: Area | None = None


class ProcessoPage(Page[Processo]):
    pass


class ProcessoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ProcessoMudou(BaseModel):
    id: str
    action: Literal["sugerido", "aceito", "recusado", "descrito"]


class Sugestao(_Input):
    """Um processo da biblioteca que serve para a empresa, com o porquê."""

    modelo: ModeloId = Field(..., description="Id do modelo na biblioteca")
    motivo: str = Field(..., min_length=10, max_length=600,
                        description="Por que serve para esta empresa, citando o que ela contou no briefing")
    prioridade: Prioridade = Field("media", description="alta quando ataca uma dor que a empresa citou")


class ProcessoDescrito(_Input):
    """O processo que o cliente descreveu, organizado."""

    titulo: str = Field(..., min_length=3, max_length=120, description="Nome curto do processo")
    area: Area
    descricao: str = Field(..., min_length=10, max_length=3000,
                           description="Gatilho, o que acontece, quem participa e quando é exceção, nas palavras do cliente")
    modelo: ModeloId | None = Field(None, description="Modelo da biblioteca muito parecido, se houver")


class Descricao(_Input):
    texto: str = Field(..., min_length=10, max_length=3000, description="O processo, como o cliente explicaria a alguém")


class PassoAgente(BaseModel):
    """Um passo do agente enquanto trabalha (pedaço do stream)."""

    ferramenta: str
    texto: str
    status: Literal["running", "done", "failed"]


class Descoberta(BaseModel):
    texto: str = Field(..., description="Resumo do agente para o cliente")
    processos: list[Processo] = Field(..., description="Os sugeridos agora")


class Resumo(BaseModel):
    sugeridos: int
    aceitos: int
    recusados: int


# Do svc-conhecimento (rpc.conhecimento.*): o que este serviço lê da resposta.
class ContextoEmpresa(BaseModel):
    perfil: dict[str, Any]
    topicos: list[dict[str, Any]]
    concluido_em: datetime | None = None


class BuscaQuery(_Input):
    q: str


class Achados(BaseModel):
    itens: list[dict[str, Any]]


PASSOS = {
    "buscar_conhecimento": "Consultando o conhecimento",
    "sugerir_processo": "Sugerindo um processo",
    "registrar_processo": "Organizando o processo",
}

DESCOBERTA_INSTRUCOES = """Você é o agente de descoberta de processos da Cogniventure, uma empresa de BPO: executamos \
processos contínuos para pequenas e médias empresas, com agentes de IA e humanos nas exceções.

Sua tarefa: a partir do perfil da empresa (no contexto) e do que houver no conhecimento dela, escolher na biblioteca os \
processos que fazem sentido para ela e chamar sugerir_processo para cada um.

Regras:
- Sugira de 3 a 6 processos, só da biblioteca (use o id do modelo). Comece pelos que atacam as dores que a empresa citou.
- O motivo cita fatos do perfil ou do conhecimento ("vocês pagam fornecedores por boleto e as notas chegam por \
e-mail"), em uma ou duas frases, falando com o cliente. Nunca invente fatos.
- prioridade alta só para o que ataca uma dor citada; baixa para o que é útil mas não urgente.
- Não sugira de novo o que a empresa já aceitou ou recusou (veja "Processos da empresa" no contexto).
- Use buscar_conhecimento quando precisar confirmar um detalhe (fornecedores, contratos, equipe).
- No fim, escreva para o cliente um resumo curto (2 a 4 frases) do que sugeriu e por quê. Em português do Brasil."""

DESCRICAO_INSTRUCOES = """Você organiza a descrição de um processo que o cliente da Cogniventure (BPO) escreveu. \
Chame registrar_processo uma única vez, com um título curto, a área (financeiro, juridico, administrativo ou vendas), \
a descrição organizada nas palavras do cliente (gatilho, o que acontece, quem participa, quando é exceção) e, se houver \
na biblioteca (no contexto) um modelo muito parecido, o id dele. Não invente etapas que o cliente não disse. Depois, \
responda em uma frase o que registrou."""
