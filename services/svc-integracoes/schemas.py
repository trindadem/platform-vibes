"""svc-integracoes · contratos (DTOs, enums, constantes). Fonte da verdade: specs/integracoes.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.plans import Module
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-integracoes"
TASK_QUEUE = "integracoes-queue"
EVENT_SUBJECT = "events.integracoes.evento"  # algo chegou de fora: documento recebido, pagamento confirmado pelo banco
DOCUMENTO_SUBJECT = "rpc.integracoes.documento"  # o texto de um documento recebido (agentes do svc-processos)
AGENDAR_SUBJECT = "rpc.integracoes.banco_agendar"  # agenda um pagamento no banco da organização (svc-financeiro)
FERRAMENTAS_SUBJECT = "rpc.integracoes.ferramentas"  # as ferramentas dos servidores MCP da organização (svc-agentes)
MCP_SUBJECT = "rpc.integracoes.mcp_chamar"  # chama uma ferramenta MCP com a credencial guardada aqui (svc-agentes)
LIVE_CONEXOES = "integracoes.conexoes"
LIVE_SERVIDORES = "integracoes.servidores"
LIVE_DOCUMENTOS = "integracoes.documentos"
LIVE_PAGAMENTOS = "integracoes.pagamentos"

CONEXOES = "integracoes_conexoes"
DOCUMENTOS = "integracoes_documentos"
PAGAMENTOS = "integracoes_pagamentos"
SERVIDORES = "integracoes_servidores_mcp"
TABLES = [CONEXOES, DOCUMENTOS, PAGAMENTOS, SERVIDORES]
UNIQUE = {CONEXOES: ["tipo"], DOCUMENTOS: ["origem_id"], PAGAMENTOS: ["pagamento_id"], SERVIDORES: ["nome"]}
SEARCH = {DOCUMENTOS: ["nome", "assunto", "de"]}
WRITERS = frozenset({"owner", "admin"})
BANK_OPERATORS = frozenset({"owner", "admin", "operador"})  # confirmam à mão um pagamento do banco simulado
DOCUMENT_MAX_BYTES = 10_000_000
MCP_MAX_BYTES = 1_000_000  # resposta de um servidor MCP
MCP_TIMEOUT = 30.0
TEXT_MAX_CHARS = 20_000
ACCEPTED = ("application/pdf", "text/plain", "text/xml", "application/xml", "image/png", "image/jpeg", "image/webp")

MODULE = Module(
    "Integrações",
    "Conexões da empresa com o mundo de fora: caixa de entrada de documentos, banco e servidores MCP",
    category="Integrações",
)


class IntegracoesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INTEGRACOES_", extra="ignore")

    dominio: str = Field("entrada.localhost", description="Domínio dos endereços de caixa de entrada")
    mailpit_url: str | None = Field(None, description="Ambiente local: o Mailpit que avisa e entrega os e-mails recebidos")
    secrets_key: SecretStr | None = Field(None, description="Chave (32 bytes, base64url) que cifra as credenciais MCP; sem ela o serviço não sobe")
    environment: str = Field("development", validation_alias="ENVIRONMENT")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _key(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


# ── Conexões ─────────────────────────────────────────────────────────────────

TipoConexao = Literal["caixa_entrada", "banco_simulado"]


class Conexao(BaseModel):
    id: str
    tipo: TipoConexao
    nome: str
    endereco: str | None = Field(None, description="caixa_entrada: para onde encaminhar boletos e notas")
    confirmar_apos: int | None = Field(None, description="banco_simulado: segundos até o banco confirmar um pagamento")
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class Conexoes(BaseModel):
    itens: list[Conexao]


class NovaConexao(_Input):
    tipo: TipoConexao
    nome: str | None = Field(None, min_length=2, max_length=80)
    confirmar_apos: int = Field(30, ge=5, le=86_400, description="banco_simulado: segundos até confirmar o pagamento")


class ConexaoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ConexaoMudou(BaseModel):
    id: str
    action: Literal["conectada", "removida"]


# ── Documentos recebidos ─────────────────────────────────────────────────────

class Documento(BaseModel):
    id: str
    origem: Literal["email"]
    de: str | None = None
    assunto: str | None = None
    nome: str
    tipo: str
    tamanho: int
    tem_texto: bool = Field(..., description="Falso em imagem ou PDF escaneado: o agente não lê (sem OCR)")
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class DocumentoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "nome")
    default_sort: ClassVar[str | None] = "-created_at"


class DocumentoPage(Page[Documento]):
    pass


class DocumentoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Link(BaseModel):
    url: str
    nome: str
    tipo: str


class DocumentoTexto(BaseModel):
    """rpc.integracoes.documento: o que o agente lê de um documento recebido."""

    id: str
    nome: str
    tipo: str
    de: str | None = None
    assunto: str | None = None
    texto: str = Field(..., description="Texto extraído (vazio em imagem ou PDF escaneado)")


class DocumentoMudou(BaseModel):
    id: str
    action: Literal["recebido"]


class AvisoEmail(BaseModel):
    """O que o Mailpit manda ao receber um e-mail (ambiente local): só o id importa; o resto vem da mensagem."""

    model_config = ConfigDict(extra="ignore")

    ID: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Recebidos(BaseModel):
    documentos: int


# ── Banco simulado ───────────────────────────────────────────────────────────

class AgendarPagamento(_Input):
    valor: float = Field(..., gt=0, le=10_000_000)
    vencimento: str | None = Field(None, description="AAAA-MM-DD; vencido ou vazio: agenda para hoje")
    fornecedor: str | None = Field(None, max_length=200)
    linha_digitavel: str | None = Field(None, max_length=120)


class PagamentoAgendado(BaseModel):
    pagamento_id: str
    data: str


class Pagamento(BaseModel):
    id: str
    pagamento_id: str
    valor: float
    data: str = Field(..., description="Data agendada (AAAA-MM-DD)")
    fornecedor: str | None = None
    linha_digitavel: str | None = None
    status: Literal["agendado", "pago"]
    pago_em: datetime | None = None
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class PagamentoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "data", "valor")
    default_sort: ClassVar[str | None] = "-created_at"
    status: Literal["agendado", "pago"] | None = None


class PagamentoPage(Page[Pagamento]):
    pass


class PagamentoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class PagamentoSimulado(BaseModel):
    """O banco simulado confirma o pagamento depois de alguns segundos (workflow durável)."""

    id: str
    segundos: int


class PagamentoMudou(BaseModel):
    id: str
    action: Literal["agendado", "pago"]


# ── Eventos para os processos ────────────────────────────────────────────────

class EventoExterno(BaseModel):
    """events.integracoes.evento: algo chegou de fora. O svc-processos inicia os processos cujo gatilho é este evento
    e, com chave, entrega a mensagem à execução que espera por ela (ex.: banco.pago com o id do pagamento)."""

    nome: Literal["documento.recebido", "banco.pago"]
    chave: str | None = None
    dados: dict[str, Any] = Field(default_factory=dict)


class Resumo(BaseModel):
    caixa_entrada: str | None = Field(None, description="Endereço da caixa de entrada, se conectada")
    banco: bool = False
    documentos: int = 0
    agendados: int = 0


# ── Servidores MCP: ferramentas de sistemas da empresa para os agentes ───────

Risco = Literal["leitura", "escrita", "externa", "irreversivel"]


class FerramentaMcp(BaseModel):
    """Uma ferramenta anunciada pelo servidor, sanitizada e pinada (a impressão de nome, descrição e schema)."""

    nome: str
    titulo: str | None = None
    descricao: str
    parametros: dict[str, Any] = Field(default_factory=dict, description="JSON schema da entrada")
    risco: Risco = Field("externa", description="Piso externa: o que o servidor diz de si só sobe o risco")
    digest: str
    quarentena: str | None = Field(None, description="Por que a ferramenta não pode ser usada (mudou, texto oculto...)")


class ServidorMcp(BaseModel):
    id: str
    nome: str
    url: str
    cabecalho: str | None = Field(None, description="Cabeçalho que leva a credencial (ex.: Authorization)")
    tem_segredo: bool = False
    ferramentas: list[FerramentaMcp] = Field(default_factory=list)
    servidor: str | None = Field(None, description="Nome e versão que o servidor informou")
    atualizado_em: datetime | None = None
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class ServidoresMcp(BaseModel):
    itens: list[ServidorMcp]


class NovoServidorMcp(_Input):
    nome: str = Field(..., min_length=2, max_length=60, pattern=r"^[\w À-ÿ.-]+$")
    url: str = Field(..., min_length=8, max_length=500, description="Endereço MCP (Streamable HTTP), https")
    cabecalho: str | None = Field("Authorization", max_length=60, pattern=r"^[A-Za-z0-9-]+$")
    segredo: str | None = Field(None, max_length=4000, description="Valor do cabeçalho (ex.: Bearer abc...): guardado cifrado")


class ServidorRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ServidorMudou(BaseModel):
    id: str
    action: Literal["conectado", "atualizado", "removido", "quarentena"]


class FerramentaDisponivel(BaseModel):
    """rpc.integracoes.ferramentas: uma ferramenta que um agente da organização pode usar."""

    servidor: str
    servidor_nome: str
    nome: str
    descricao: str
    parametros: dict[str, Any]
    risco: Risco


class FerramentasDisponiveis(BaseModel):
    itens: list[FerramentaDisponivel]


class ChamadaMcp(_Input):
    servidor: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    ferramenta: str = Field(..., min_length=1, max_length=128)
    argumentos: dict[str, Any] = Field(default_factory=dict)


class ResultadoMcp(BaseModel):
    ok: bool
    texto: str
    dados: Any = Field(None, description="structuredContent, quando o servidor manda")


# ── Catálogo: o que dá para conectar ─────────────────────────────────────────

class ItemCatalogo(BaseModel):
    tipo: str
    nome: str
    descricao: str
    disponivel: bool
    varias: bool = Field(False, description="A organização pode ter mais de uma")


class Catalogo(BaseModel):
    itens: list[ItemCatalogo]


CATALOGO = Catalogo(itens=[
    ItemCatalogo(tipo="caixa_entrada", nome="Caixa de entrada", disponivel=True,
                 descricao="Um endereço de e-mail da empresa para boletos e notas: cada anexo vira documento."),
    ItemCatalogo(tipo="banco_simulado", nome="Banco (simulado)", disponivel=True,
                 descricao="Agenda e confirma pagamentos enquanto o banco de verdade não é escolhido."),
    ItemCatalogo(tipo="servidor_mcp", nome="Servidor MCP", disponivel=True, varias=True,
                 descricao="Ferramentas de um sistema da empresa (ERP, CRM...) para os agentes, com a credencial guardada aqui."),
    ItemCatalogo(tipo="whatsapp", nome="WhatsApp", disponivel=False, descricao="Documentos e conversas pelo WhatsApp da empresa."),
    ItemCatalogo(tipo="banco", nome="Banco (Open Finance ou API do banco)", disponivel=False,
                 descricao="Pagamentos e extratos no banco de verdade."),
    ItemCatalogo(tipo="nfse", nome="NFS-e", disponivel=False, descricao="Emissão e consulta de notas de serviço na prefeitura."),
])
