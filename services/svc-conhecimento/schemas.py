"""svc-conhecimento · contratos (DTOs, enums, constantes). Fonte da verdade: specs/conhecimento.md §2"""
from datetime import date, datetime
from typing import Annotated, Any, ClassVar, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.plans import Limit, Module
from core.resources import Fields, Resource, Text
from core.storage import KeepRequest, Upload, UploadRequest  # arquivos (README §5.14): contrato do core
from core.surreal import ListQuery, Page

__all__ = ["KeepRequest", "Upload", "UploadRequest"]

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-conhecimento"
TASK_QUEUE = "conhecimento-queue"
TRIGGER_SUBJECT = "events.conhecimento.trigger"
PROCESSED_SUBJECT = "events.conhecimento.processed"
LIVE_BRIEFING = "conhecimento.briefing"  # perfil ou conversa mudou
LIVE_LEITURAS = "conhecimento.leituras"  # leitura de site ou documento mudou de estado
CONTEXTO_SUBJECT = "rpc.conhecimento.contexto"  # outros serviços (svc-processos) leem o perfil da empresa
BUSCA_SUBJECT = "rpc.conhecimento.busca"  # e buscam no conhecimento, sempre na organização de quem pede

PERFIL = "conhecimento_perfil"  # um por organização (chave fixa, única)
MENSAGENS = "conhecimento_mensagens"
LEITURAS = "conhecimento_leituras"
TABLES = [PERFIL, MENSAGENS, LEITURAS]
UNIQUE = {PERFIL: ["chave"]}
SEARCH = {LEITURAS: ["origem"]}

WRITERS = frozenset({"owner", "admin"})  # quem conduz o briefing e mexe no conhecimento (briefing.md §2)
HISTORY = 20  # mensagens da conversa que o agente recebe no contexto
SEARCH_RESULTS = 5
ITEM_CHARS = 4500  # tamanho de cada item gerado de uma leitura (o campo aceita 5000)
DOCUMENT_MAX_BYTES = 10_000_000
DOCUMENT_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/csv",
)
PAGE_MAX_BYTES = 2_000_000
DOCUMENT_MAX_ITEMS = 60

MODULE = Module(
    "Conhecimento",
    "Briefing da empresa e a base de conhecimento que os agentes consultam",
    category="Sua empresa",
    limits=[Limit("itens", "Itens na base de conhecimento", default=2000, unit="itens")],
)


class ConhecimentoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONHECIMENTO_", extra="ignore")

    model: str = Field("cv/agente", description="Modelo do agente de briefing, como cadastrado no svc-ai")
    site_pages: int = Field(8, ge=1, le=30, description="Páginas lidas de um site, a primeira incluída")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


# ── Perfil da empresa e tópicos do briefing ──────────────────────────────────

Porte = Literal["mei", "micro", "pequena", "media", "grande"]
Regime = Literal["mei", "simples", "presumido", "real", "nao_sei"]
Curto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Longo = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)]


class Perfil(_Input):
    """O perfil da empresa. Todo campo é opcional: o briefing vai preenchendo; vazio apaga."""

    atividade: Longo | None = Field(None, title="O que a empresa faz")
    segmento: Curto | None = Field(None, title="Segmento", description="Ex.: padaria, clínica, indústria de embalagens")
    porte: Porte | None = Field(None, title="Porte")
    cidade: Curto | None = Field(None, title="Cidade")
    uf: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$")] | None = Field(
        None, title="UF"
    )
    site: Curto | None = Field(None, title="Site")
    produtos: Longo | None = Field(None, title="Produtos e serviços")
    clientes: Longo | None = Field(None, title="Quem são os clientes")
    canais_venda: Longo | None = Field(None, title="Canais de venda")
    bancos: Curto | None = Field(None, title="Bancos")
    recebimentos: Longo | None = Field(None, title="Como recebe", description="Boleto, Pix, cartão, prazo...")
    pagamentos: Longo | None = Field(None, title="Como paga fornecedores e contas")
    contabilidade: Curto | None = Field(None, title="Contabilidade", description="Escritório contábil ou interna")
    regime_tributario: Regime | None = Field(None, title="Regime tributário")
    sistemas: Longo | None = Field(None, title="Sistemas e planilhas que usa")
    documentos: Longo | None = Field(None, title="Por onde chegam documentos", description="NF, boletos, contratos")
    colaboradores: int | None = Field(None, ge=0, le=100_000, title="Colaboradores")
    equipe: Longo | None = Field(None, title="Quem cuida do quê")
    dores: Longo | None = Field(None, title="O que mais toma tempo ou dá problema")
    objetivos: Longo | None = Field(None, title="O que espera da Cogniventure")


class TopicDef(BaseModel):
    id: str
    titulo: str
    campos: tuple[str, ...]  # o que o tópico cobre (na ordem da tela)
    obrigatorios: tuple[str, ...]  # o que precisa estar preenchido para o tópico estar feito


TOPICOS: list[TopicDef] = [
    TopicDef(id="negocio", titulo="O negócio", campos=("atividade", "segmento", "porte", "cidade", "uf", "site"),
             obrigatorios=("atividade", "segmento", "porte")),
    TopicDef(id="clientes", titulo="Clientes e vendas", campos=("produtos", "clientes", "canais_venda"),
             obrigatorios=("produtos", "clientes")),
    TopicDef(id="financeiro", titulo="Financeiro", campos=("bancos", "recebimentos", "pagamentos", "contabilidade", "regime_tributario"),
             obrigatorios=("recebimentos", "pagamentos")),
    TopicDef(id="sistemas", titulo="Sistemas e documentos", campos=("sistemas", "documentos"), obrigatorios=("sistemas", "documentos")),
    TopicDef(id="equipe", titulo="Equipe", campos=("colaboradores", "equipe"), obrigatorios=("colaboradores",)),
    TopicDef(id="objetivos", titulo="Dores e objetivos", campos=("dores", "objetivos"), obrigatorios=("dores",)),
]


class Topico(BaseModel):
    id: str
    titulo: str
    status: Literal["feito", "em_andamento", "a_fazer"]
    faltam: list[str] = Field(default_factory=list, description="Rótulos do que falta para o tópico ficar feito")


class Mensagem(BaseModel):
    id: str
    papel: Literal["cliente", "agente"]
    texto: str
    passos: list[str] = Field(default_factory=list, description="O que o agente fez para responder")
    created_at: datetime | None = None


class Briefing(BaseModel):
    perfil: Perfil
    topicos: list[Topico]
    mensagens: list[Mensagem]
    concluido_em: datetime | None = None
    pode_concluir: bool


class ContextoEmpresa(BaseModel):
    """Resposta do rpc.conhecimento.contexto: o que os outros agentes precisam saber da empresa."""

    perfil: Perfil
    topicos: list[Topico]
    concluido_em: datetime | None = None


class MensagemIn(_Input):
    texto: str = Field(..., min_length=1, max_length=4000, description="O que a pessoa escreveu")


class Passo(BaseModel):
    """Um passo do agente enquanto responde (pedaço do stream)."""

    ferramenta: str
    texto: str
    status: Literal["running", "done", "failed"]


class BriefingMudou(BaseModel):
    action: Literal["mensagem", "perfil", "concluido", "reaberto"]


# O agente de briefing: instrução, abertura fixa e o que cada ferramenta mostra na tela enquanto roda.
BRIEFING_ABERTURA = (
    "Olá! Sou o agente de briefing da Cogniventure. Vou conhecer a sua empresa com algumas perguntas rápidas, "
    "anotando tudo no perfil ao lado; você pode corrigir qualquer coisa a qualquer momento. Para começar: o que a "
    "sua empresa faz, e em que cidade ela fica?"
)
BRIEFING_INSTRUCOES = """Você é o agente de briefing da Cogniventure, uma empresa de BPO: executamos processos \
contínuos (financeiro, contábil, jurídico, administrativo e vendas) para pequenas e médias empresas, com agentes de IA \
e humanos nas exceções. Seu trabalho é conhecer a empresa do cliente numa conversa curta e agradável.

Como conduzir:
- Fale em português do Brasil, com frases curtas e tom cordial. Nada de jargão.
- Faça uma ou duas perguntas por vez, sempre sobre o que ainda falta (veja "Tópicos" no contexto). Siga a ordem dos \
tópicos, mas aproveite o que a pessoa contar fora de ordem.
- Sempre que a pessoa contar algo que corresponde a um campo do perfil, chame registrar_perfil com esses campos, com \
as palavras dela resumidas. Isso inclui as dores (campo dores) e o que ela espera da Cogniventure (campo objetivos). \
Nunca invente nem suponha um valor que ela não disse; se ficou ambíguo, pergunte.
- Só o que não cabe em nenhum campo do perfil (como funciona a aprovação de pagamentos, fornecedores principais, \
regras de desconto, prazos) vai para registrar_conhecimento, um assunto por item.
- Se a pessoa informar o site da empresa, registre no perfil e chame ler_site uma vez; diga que a leitura acontece em \
segundo plano. Para responder sobre algo que já está no conhecimento, use buscar_conhecimento.
- Pergunte se há documentos úteis (contratos, tabela de preços, manuais); eles são enviados na tela de Conhecimento.
- Quando todos os tópicos estiverem feitos, resuma em poucas linhas o que entendeu e convide a pessoa a revisar o \
perfil e clicar em "Concluir briefing".
- Não prometa prazos, preços nem processos específicos; isso vem no próximo passo da jornada.
- A sua resposta final é a próxima fala do agente para o cliente: nunca repita nem copie a mensagem do cliente."""

PASSOS = {
    "registrar_perfil": "Anotando no perfil",
    "registrar_conhecimento": "Guardando no conhecimento",
    "buscar_conhecimento": "Consultando o conhecimento",
    "ler_site": "Começando a leitura do site",
}


TipoItem = Literal["empresa", "produto", "cliente", "fornecedor", "processo", "politica", "contato", "outro"]
Fonte = Literal["briefing", "site", "documento", "manual"]
TIPO_ROTULOS = {"produto": "Produto ou serviço", "politica": "Política ou regra"}


class NovoConhecimento(_Input):
    """Um assunto que a pessoa contou e que não cabe no perfil."""

    titulo: str = Field(..., min_length=2, max_length=160, description="Assunto, em poucas palavras")
    conteudo: str = Field(..., min_length=2, max_length=5000, description="O que a pessoa disse, organizado")
    tipo: TipoItem = Field("outro", description="Do que se trata")

    @field_validator("tipo", mode="before")
    @classmethod
    def _tipo_conhecido(cls, value: Any) -> Any:
        """O agente às vezes inventa um tipo ("equipe"): vira "outro" em vez de uma volta perdida."""
        return value if value in get_args(TipoItem) else "outro"


# ── Base de conhecimento ─────────────────────────────────────────────────────



class Conhecimento(Fields):
    """Um item da base de conhecimento: um assunto, com a fonte de onde veio."""

    titulo: str = Field(..., min_length=2, max_length=160, title="Título")
    conteudo: Text = Field(..., title="Conteúdo")
    tipo: TipoItem = Field("outro", title="Tipo", json_schema_extra={"labels": TIPO_ROTULOS})
    fonte: Fonte = Field("manual", title="Fonte", description="De onde veio: briefing, site, documento ou manual")
    origem: str | None = Field(None, max_length=300, title="Origem", description="Endereço ou arquivo de onde veio")
    validade: date | None = Field(None, title="Vale até", description="Ex.: tabela de preços ou contrato com vencimento")


ITENS = Resource(SERVICE, "itens", Conhecimento, "Conhecimento", search=("titulo", "conteudo"), sort=("titulo", "validade"),
                 filters=("tipo", "fonte"), columns=("titulo", "tipo", "fonte", "origem", "validade"), limit="itens",
                 write=tuple(WRITERS))
RESOURCES = [ITENS]
ConhecimentoItem = ITENS.item


class BuscaQuery(_Input):
    q: str = Field(..., min_length=2, max_length=300, description="Palavras da busca, em qualquer ordem")


class Achado(BaseModel):
    id: str
    titulo: str
    trecho: str
    fonte: Fonte
    origem: str | None = None
    nota: float


class Achados(BaseModel):
    itens: list[Achado]


# ── Leituras: site e documentos ──────────────────────────────────────────────

class SiteIn(_Input):
    url: str = Field(..., min_length=4, max_length=300, description="Endereço do site (com ou sem https://)")


class Leitura(BaseModel):
    id: str
    tipo: Literal["site", "documento"]
    origem: str = Field(..., description="Endereço do site ou nome do arquivo")
    status: Literal["lendo", "pronta", "falhou"]
    paginas: int = 0
    itens: int = 0
    erro: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class LeituraQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "origem")
    default_sort: ClassVar[str | None] = "-created_at"
    tipo: Literal["site", "documento"] | None = None
    status: Literal["lendo", "pronta", "falhou"] | None = None


class LeituraPage(Page[Leitura]):
    pass


class LeituraRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class LeituraPedido(_Input):
    """Gatilho do LeituraWorkflow (events.conhecimento.trigger)."""

    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    tipo: Literal["site", "documento"]


class LeituraFalha(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    erro: str = Field(..., max_length=300)


class LeituraMudou(BaseModel):
    id: str
    status: Literal["lendo", "pronta", "falhou", "removida"]


# ── Workspace ────────────────────────────────────────────────────────────────

class Resumo(BaseModel):
    """O passo de briefing e conhecimento da jornada, para o workspace."""

    topicos_feitos: int
    topicos_total: int
    concluido_em: datetime | None = None
    itens: int
    por_fonte: dict[str, int] = Field(default_factory=dict, description="Itens por fonte (briefing, site, documento, manual)")
    leituras_lendo: int
