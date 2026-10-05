"""svc-integracoes · contratos (DTOs, enums, constantes). Fonte da verdade: specs/integracoes.md §2"""
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.plans import Limit, Module
from core.storage import KeepRequest, Upload, UploadRequest
from core.surreal import ListQuery, Page

__all__ = ["KeepRequest", "Upload", "UploadRequest"]  # o contrato de envio de arquivo pela tela (core/storage.py)

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-integracoes"
TASK_QUEUE = "integracoes-queue"
EVENT_SUBJECT = "events.integracoes.evento"  # algo chegou de fora: documento recebido, pagamento confirmado pelo banco
DOCUMENTO_SUBJECT = "rpc.integracoes.documento"  # o texto de um documento recebido (agentes do svc-processos)
AGENDAR_SUBJECT = "rpc.integracoes.banco_agendar"  # agenda um pagamento no banco da organização (svc-financeiro)
FERRAMENTAS_SUBJECT = "rpc.integracoes.ferramentas"  # as ferramentas dos servidores MCP da organização (svc-agentes)
MCP_SUBJECT = "rpc.integracoes.mcp_chamar"  # chama uma ferramenta MCP com a credencial guardada aqui (svc-agentes)
EMAIL_SUBJECT = "rpc.integracoes.enviar_email"  # e-mail que sai da caixa de entrada da organização (pacotes)
COBRAR_SUBJECT = "rpc.integracoes.banco_cobrar"  # emite uma cobrança (boleto) no banco da organização (svc-financeiro)
EXTRATO_SUBJECT = "rpc.integracoes.banco_extrato"  # o extrato do banco da organização (svc-financeiro)
LIVE_CONEXOES = "integracoes.conexoes"
LIVE_SERVIDORES = "integracoes.servidores"
LIVE_DOCUMENTOS = "integracoes.documentos"
LIVE_PAGAMENTOS = "integracoes.pagamentos"
LIVE_COBRANCAS = "integracoes.cobrancas"
LIVE_ENVIADOS = "integracoes.enviados"
LIVE_GATEWAYS = "integracoes.gateways"

CONEXOES = "integracoes_conexoes"
DOCUMENTOS = "integracoes_documentos"
PAGAMENTOS = "integracoes_pagamentos"
SERVIDORES = "integracoes_servidores_mcp"
COBRANCAS = "integracoes_cobrancas"
ENVIADOS = "integracoes_enviados"
GATEWAYS = "integracoes_gateways"  # os gateways que a Cogniventure contrata: só na organização dela (PLATFORM_TENANT)
TABLES = [CONEXOES, DOCUMENTOS, PAGAMENTOS, SERVIDORES, COBRANCAS, ENVIADOS, GATEWAYS]
UNIQUE = {CONEXOES: ["tipo"], DOCUMENTOS: ["origem_id"], PAGAMENTOS: ["pagamento_id"], SERVIDORES: ["nome"], COBRANCAS: ["cobranca_id"],
          GATEWAYS: ["slug"]}
SEARCH = {DOCUMENTOS: ["nome", "assunto", "de"], ENVIADOS: ["para", "assunto"]}
WRITERS = frozenset({"owner", "admin"})
BANK_OPERATORS = frozenset({"owner", "admin", "operador"})  # confirmam à mão um pagamento do banco simulado
SIMULADO = "simulado"  # o gateway embutido: o banco simulado, sempre disponível e sem custo
LIMITE_BANCO = "gateway-banco"  # integracoes.gateway-banco: o gasto do mês com o gateway do banco, repassado no plano
DOCUMENT_MAX_BYTES = 10_000_000
MCP_MAX_BYTES = 1_000_000  # resposta de um servidor MCP
MCP_TIMEOUT = 30.0
TEXT_MAX_CHARS = 20_000
ACCEPTED = ("application/pdf", "text/plain", "text/xml", "application/xml", "image/png", "image/jpeg", "image/webp")
IMAGENS = ("image/png", "image/jpeg", "image/webp")  # o modelo de visão lê (a foto de um boleto, a nota escaneada)
PAGINAS_LIDAS = 4  # PDF escaneado: as imagens das primeiras páginas vão ao modelo
EMAIL_MAX_BYTES = 10_000_000  # e-mail que sai, anexos somados (o limite do Postmark)
ANEXOS_MAX = 5
POSTMARK_API = "https://api.postmarkapp.com/email"
POSTMARK_MAX_BYTES = 40 * 1_048_576  # aviso de e-mail que chega: até 35 MB de mensagem, em base64 dentro do JSON

MODULE = Module(
    "Integrações",
    "Conexões da empresa com o mundo de fora: caixa de entrada de documentos, banco e servidores MCP",
    category="Integrações",
    limits=[Limit(LIMITE_BANCO, "Gasto com o banco no mês (gateway da Cogniventure)", monthly=True, currency="BRL")],
)


class IntegracoesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INTEGRACOES_", extra="ignore")

    dominio: str = Field("entrada.localhost", description="Domínio dos endereços de caixa de entrada")
    mailpit_url: str | None = Field(None, description="Ambiente local: o Mailpit que avisa e entrega os e-mails recebidos")
    postmark_token: SecretStr | None = Field(None, description="Server token do Postmark: os e-mails saem por ele (vale mais que o Mailpit)")
    postmark_stream: str = Field("outbound", description="Message stream transacional do Postmark")
    postmark_entrada: SecretStr | None = Field(None, description="Senha do aviso de entrada do Postmark (usuário:senha na URL do "
                                                                 "webhook, Basic auth); sem ela a rota de entrada não existe")
    modelo_visao: str = Field("cv/visao", description="Modelo que lê foto e PDF escaneado, como cadastrado no svc-ai")
    secrets_key: SecretStr | None = Field(None, description="Chave (32 bytes, base64url) que cifra as credenciais (MCP e "
                                                            "gateways); sem ela o serviço não sobe")
    platform_tenant: str | None = Field(None, validation_alias="PLATFORM_TENANT",
                                        description="A organização da Cogniventure: dono e admin dela gerenciam os gateways")
    environment: str = Field("development", validation_alias="ENVIRONMENT")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _key(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


# ── Conexões ─────────────────────────────────────────────────────────────────

TipoConexao = Literal["caixa_entrada", "banco"]
_SLUG = r"^[a-z][a-z0-9-]{1,39}$"


class Conexao(BaseModel):
    id: str
    tipo: TipoConexao
    nome: str
    endereco: str | None = Field(None, description="caixa_entrada: para onde encaminhar boletos e notas")
    gateway: str | None = Field(None, description="banco: o gateway (simulado, ou um da Cogniventure)")
    gateway_nome: str | None = None
    confirmar_apos: int | None = Field(None, description="banco simulado: segundos até o banco confirmar um pagamento")
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
    gateway: str = Field(SIMULADO, pattern=_SLUG, description="banco: o gateway (GET /gateways); padrão, o simulado")
    confirmar_apos: int = Field(30, ge=5, le=86_400, description="banco simulado: segundos até confirmar o pagamento")


class ConexaoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ConexaoMudou(BaseModel):
    id: str
    action: Literal["conectada", "removida"]


# ── Gateways: o contrato por capacidade (alinhamento pós-N7, item 9) ─────────

Capacidade = Literal["banco"]
OperacaoBanco = Literal["agendar", "cobrar", "extrato"]


class Provedor(BaseModel):
    """Um provedor que o serviço sabe usar (um adaptador da capacidade): o que ele faz e a credencial que pede."""

    provedor: str
    nome: str
    capacidade: Capacidade
    operacoes: list[OperacaoBanco]
    campos: list[str] = Field(default_factory=list, description="Campos da credencial que o gateway guarda (cifrada)")


class Gateway(BaseModel):
    """Um gateway que a Cogniventure contrata e repassa no plano: o provedor, a credencial (só aqui, cifrada) e quanto
    cada operação custa ao cliente (soma no limite integracoes.gateway-<capacidade> do mês)."""

    id: str
    slug: str
    nome: str
    capacidade: Capacidade
    provedor: str
    ativo: bool = True
    custos: dict[OperacaoBanco, float] = Field(default_factory=dict, description="Operação → R$ por chamada")
    operacoes: list[OperacaoBanco] = Field(default_factory=list, description="O que o provedor faz (o resto vai ao staff)")
    embutido: bool = Field(False, description="O banco simulado: sempre disponível, sem custo e sem credencial")
    credencial: list[str] = Field(default_factory=list, description="Os campos guardados (só para quem gerencia a plataforma)")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class Gateways(BaseModel):
    itens: list[Gateway]
    provedores: list[Provedor]
    gerencia: bool = Field(False, description="Quem pergunta gerencia os gateways (dono ou admin da Cogniventure)")


Custos = dict[OperacaoBanco, Annotated[float, Field(ge=0, le=10_000)]]
Credencial = dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")], Annotated[SecretStr, Field(min_length=1, max_length=4000)]]


class NovoGateway(_Input):
    slug: str = Field(..., pattern=_SLUG, description="Identificador curto (a conexão do cliente guarda este)")
    nome: str = Field(..., min_length=2, max_length=80)
    capacidade: Capacidade = "banco"
    provedor: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    custos: Custos = Field(default_factory=dict)
    credencial: Credencial | None = Field(None, description="Os campos que o provedor pede: guardados cifrados, nunca voltam")
    ativo: bool = True


class EdicaoGateway(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    nome: str | None = Field(None, min_length=2, max_length=80)
    custos: Custos | None = None
    credencial: Credencial | None = Field(None, description="Troca a credencial inteira")
    ativo: bool | None = None


class GatewayRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class GatewayMudou(BaseModel):
    id: str
    action: Literal["criado", "alterado", "removido"]


# ── Documentos recebidos ─────────────────────────────────────────────────────

Leitura = Literal["arquivo", "modelo", "lendo", "sem_texto"]


class Documento(BaseModel):
    id: str
    origem: Literal["email", "tela"]
    de: str | None = None
    assunto: str | None = None
    nome: str
    tipo: str
    tamanho: int
    tem_texto: bool = Field(..., description="Há texto para o agente ler (do arquivo ou da leitura do modelo)")
    leitura: Leitura = Field("arquivo", description="arquivo: texto do próprio arquivo; modelo: foto ou PDF escaneado lido pelo "
                                                    "modelo de visão; lendo: a leitura ainda não acabou; sem_texto: nada legível")
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
    texto: str = Field(..., description="Texto do arquivo ou, em foto e PDF escaneado, o que o modelo de visão leu (vazio: nada legível)")
    leitura: Leitura = "arquivo"


class DocumentoMudou(BaseModel):
    id: str
    action: Literal["recebido", "lido"]


class EnviarDocumento(_Input):
    """A tela confirma o arquivo enviado (a key de Upload). iniciar: o documento chega como os do e-mail e inicia os
    processos; falso, só fica guardado (ex.: a nota fiscal que o staff anexa numa exceção)."""

    key: str = Field(..., max_length=300, description="A key devolvida em Upload")
    iniciar: bool = True


class LeituraDocumento(BaseModel):
    """O documento recebido segue para o modelo de visão (foto, PDF escaneado) e só então avisa os processos (a
    organização vai junto com o workflow, como quem age)."""

    id: str
    avisar: bool = True


class AvisoEmail(BaseModel):
    """O que o Mailpit manda ao receber um e-mail (ambiente local): só o id importa; o resto vem da mensagem."""

    model_config = ConfigDict(extra="ignore")

    ID: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Recebidos(BaseModel):
    documentos: int


class PostmarkEndereco(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Email: str = ""


class PostmarkAnexo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Name: str = ""
    Content: str = Field("", description="Base64")
    ContentType: str = "application/octet-stream"


class AvisoPostmark(BaseModel):
    """O aviso de entrada do Postmark (inbound webhook): um e-mail chegou a um endereço do domínio da caixa de entrada.
    RawEmail (a mensagem RFC 822) vem com "Include raw email content" ligado; sem ele, a mensagem é montada dos campos."""

    model_config = ConfigDict(extra="ignore")

    MessageID: str = Field(..., min_length=1, max_length=200)
    From: str = ""
    Subject: str = ""
    OriginalRecipient: str = ""
    ToFull: list[PostmarkEndereco] = Field(default_factory=list)
    CcFull: list[PostmarkEndereco] = Field(default_factory=list)
    BccFull: list[PostmarkEndereco] = Field(default_factory=list)
    TextBody: str = ""
    Attachments: list[PostmarkAnexo] = Field(default_factory=list)
    RawEmail: str | None = None


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
    gateway: str | None = Field(None, description="Por qual gateway passou")
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


# ── Banco simulado: cobranças (contas a receber) e extrato ───────────────────

class CobrarNoBanco(_Input):
    valor: float = Field(..., gt=0, le=10_000_000)
    vencimento: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="AAAA-MM-DD")
    pagador: str | None = Field(None, max_length=200)
    descricao: str | None = Field(None, max_length=500)


class CobrancaEmitida(BaseModel):
    cobranca_id: str
    linha_digitavel: str
    vencimento: str


class Cobranca(BaseModel):
    id: str
    cobranca_id: str
    valor: float
    vencimento: str
    pagador: str | None = None
    descricao: str | None = None
    linha_digitavel: str
    status: Literal["aberta", "recebida"]
    recebido_em: datetime | None = None
    gateway: str | None = Field(None, description="Por qual gateway passou")
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class CobrancaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "vencimento", "valor")
    default_sort: ClassVar[str | None] = "-created_at"
    status: Literal["aberta", "recebida"] | None = None


class CobrancaPage(Page[Cobranca]):
    pass


class CobrancaRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class CobrancaSimulada(BaseModel):
    """O banco simulado confirma o recebimento depois de alguns segundos (workflow durável)."""

    id: str
    segundos: int


class CobrancaMudou(BaseModel):
    id: str
    action: Literal["emitida", "recebida"]


class ExtratoPedido(_Input):
    desde: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="A partir de que dia (AAAA-MM-DD)")


class Lancamento(BaseModel):
    tipo: Literal["pagamento", "recebimento"]
    id: str = Field(..., description="pagamento_id (pagamento) ou cobranca_id (recebimento)")
    valor: float = Field(..., description="Negativo no pagamento, positivo no recebimento")
    data: str
    descricao: str | None = None


class Extrato(BaseModel):
    itens: list[Lancamento]


# ── E-mail que sai da caixa de entrada ───────────────────────────────────────

class AnexoRef(_Input):
    """Um anexo do e-mail que sai: um documento da organização (recebido ou enviado pela tela) ou o boleto de uma
    cobrança emitida no banco. Os arquivos ficam neste serviço: quem pede o envio diz qual, não manda o arquivo."""

    documento: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Id do documento")
    cobranca: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$", description="cobranca_id: vai o boleto em PDF")

    @model_validator(mode="after")
    def _um(self) -> "AnexoRef":
        if (self.documento is None) == (self.cobranca is None):
            raise ValueError("diga documento ou cobranca (um dos dois)")
        return self


class EnviarEmail(_Input):
    para: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    assunto: str = Field(..., min_length=1, max_length=200)
    texto: str = Field(..., min_length=1, max_length=20_000)
    anexos: list[AnexoRef] = Field(default_factory=list, max_length=ANEXOS_MAX)


class EmailEnviado(BaseModel):
    mensagem_id: str
    de: str = Field(..., description="O endereço da caixa de entrada da organização")


class Enviado(BaseModel):
    id: str
    para: str
    assunto: str
    de: str
    anexos: list[str] = Field(default_factory=list, description="Os nomes dos arquivos anexados")
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class EnviadoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at",)
    default_sort: ClassVar[str | None] = "-created_at"


class EnviadoPage(Page[Enviado]):
    pass


class EnviadoMudou(BaseModel):
    id: str
    action: Literal["enviado"]


# ── Eventos para os processos ────────────────────────────────────────────────

class EventoExterno(BaseModel):
    """events.integracoes.evento: algo chegou de fora. O svc-processos inicia os processos cujo gatilho é este evento
    e, com chave, entrega a mensagem à execução que espera por ela (ex.: banco.pago com o id do pagamento)."""

    nome: Literal["documento.recebido", "banco.pago", "banco.recebido"]
    chave: str | None = None
    dados: dict[str, Any] = Field(default_factory=dict)


class Resumo(BaseModel):
    caixa_entrada: str | None = Field(None, description="Endereço da caixa de entrada, se conectada")
    banco: bool = False
    documentos: int = 0
    agendados: int = 0
    cobrancas: int = Field(0, description="Cobranças emitidas e ainda não recebidas")


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
                 descricao="Um endereço de e-mail da empresa: cada anexo que chega vira documento, e as propostas, cobranças e "
                           "pedidos saem por ele."),
    ItemCatalogo(tipo="banco", nome="Banco", disponivel=True,
                 descricao="Agenda pagamentos, emite cobranças e dá o extrato pelo gateway que a Cogniventure contrata (ou pelo "
                           "banco simulado, enquanto o banco de verdade não é escolhido)."),
    ItemCatalogo(tipo="servidor_mcp", nome="Servidor MCP", disponivel=True, varias=True,
                 descricao="Ferramentas de um sistema da empresa (ERP, CRM...) para os agentes, com a credencial guardada aqui."),
    ItemCatalogo(tipo="whatsapp", nome="WhatsApp", disponivel=False, descricao="Documentos e conversas pelo WhatsApp da empresa."),
    ItemCatalogo(tipo="open_finance", nome="Extrato pelo Open Finance", disponivel=False,
                 descricao="O extrato da conta de verdade, autorizado pela empresa no agregador."),
    ItemCatalogo(tipo="nfse", nome="NFS-e", disponivel=False, descricao="Emissão e consulta de notas de serviço na prefeitura."),
    ItemCatalogo(tipo="assinatura", nome="Assinatura eletrônica", disponivel=False, descricao="Contratos assinados pelas partes, sem papel."),
    ItemCatalogo(tipo="esocial", nome="eSocial ou folha", disponivel=False, descricao="Admissões e eventos da folha no eSocial."),
    ItemCatalogo(tipo="tribunais", nome="Tribunais e diários oficiais", disponivel=False,
                 descricao="Publicações e intimações da empresa pelo CNPJ."),
    ItemCatalogo(tipo="certidoes", nome="Portais de certidões", disponivel=False,
                 descricao="Certidões negativas da Receita/PGFN, FGTS, trabalhista, estadual e municipal."),
])


ENCERRADA_SUBJECT = "events.plans.encerrada"  # svc-plans: a conta da organização encerrou (alinhamento pós-N7, item 13)


class ContaEncerrada(BaseModel):
    """events.plans.encerrada (contrato do svc-plans), publicado como a organização que encerrou."""

    tenant: str
    em: datetime
