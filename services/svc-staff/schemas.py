"""svc-staff · contratos (DTOs, enums, constantes). Fonte da verdade: specs/staff.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings

from core.plans import Module, PlanSlug
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-staff"
TASK_QUEUE = "staff-queue"
STAFF_SUBJECT = "events.processos.staff"  # do svc-processos: o que espera o staff numa organização
ATENDIMENTO_SUBJECT = "events.atendimento.staff"  # do svc-atendimento: os pedidos de ajuda (o mesmo contrato)
OPERADOR_SUBJECT = "rpc.identity.operador"  # svc-identity: a carteira dá ou tira o papel operador
ORGANIZACOES_SUBJECT = "rpc.identity.organizacoes"  # svc-identity: as organizações clientes
ACOMPANHAMENTO_SUBJECT = "rpc.processos.acompanhamento"  # svc-processos: a saúde de uma organização
CLIENTE_SUBJECT = "rpc.identity.cliente"  # svc-identity: abre a organização do cliente e convida o dono
CONVITE_DONO_SUBJECT = "rpc.identity.convite_dono"  # svc-identity: o convite do dono de novo
MEMBER_LEFT_SUBJECT = "events.identity.member-left"  # svc-identity: alguém saiu de uma organização
CONTEXTO_SUBJECT = "rpc.conhecimento.contexto"  # svc-conhecimento: o briefing da empresa (concluído ou não)
# Resolver pela fila, sem trocar de organização: o svc-staff confere a carteira e pede ao serviço do item, agindo na
# organização do cliente, com quem do staff resolveu (por).
FILA_TAREFA_SUBJECT = "rpc.processos.fila_tarefa"
FILA_RESOLVER_SUBJECT = "rpc.processos.fila_resolver"
FILA_REVISAO_SUBJECT = "rpc.processos.fila_revisao"
FILA_DECIDIR_SUBJECT = "rpc.processos.fila_decidir"
PEDIDO_SUBJECT = "rpc.atendimento.pedido"
RESPONDER_SUBJECT = "rpc.atendimento.responder"
LIVE_FILA = "staff.fila"
LIVE_CARTEIRAS = "staff.carteiras"

CARTEIRAS = "staff_carteiras"
FILA = "staff_fila"
TABLES = [CARTEIRAS, FILA]
UNIQUE = {CARTEIRAS: ["pessoa", "organizacao"], FILA: ["chave"]}
GESTORES = frozenset({"owner", "admin"})  # gestor da carteira: dono ou admin da organização da Cogniventure

# Área da equipe da Cogniventure: desligada para os clientes; o plano da organização da plataforma a liga.
MODULE = Module("Staff", "Área da equipe da Cogniventure: carteira de clientes, exceções, revisões e pedidos de ajuda",
                category="Cogniventure", default=False)


class StaffSettings(BaseSettings):
    platform_tenant: str | None = Field(None, description="A organização da Cogniventure: quem é dela é staff")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _key(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


# ── Carteira: quem do staff cuida de qual organização ────────────────────────

class Carteira(BaseModel):
    id: str
    pessoa: str = Field(..., description="Id da pessoa do staff")
    organizacao: str
    organizacao_nome: str
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class Carteiras(BaseModel):
    itens: list[Carteira]


class NovaCarteira(_Input):
    pessoa: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    organizacao: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class CarteiraRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class CarteiraMudou(BaseModel):
    id: str
    action: Literal["atribuida", "removida"]


class Dono(BaseModel):
    name: str
    email: str


class ConvitePendente(BaseModel):
    email: str | None = None
    expires_at: datetime


class Organizacao(BaseModel):
    """rpc.identity.organizacoes (contrato do svc-identity, repetido aqui por quem consome)."""

    id: str
    name: str
    created_at: datetime | None = None
    dono: Dono | None = None
    convite: ConvitePendente | None = None
    ultimo_acesso: datetime | None = None


class Organizacoes(BaseModel):
    items: list[Organizacao]


class OperadorAcesso(BaseModel):
    user: str
    tenant: str
    ativo: bool


class ClienteNovo(BaseModel):
    """rpc.identity.cliente (contrato do svc-identity)."""

    empresa: str
    email: str


class ClienteCriado(BaseModel):
    tenant: str
    name: str
    convite: ConvitePendente


class ConviteDono(BaseModel):
    """rpc.identity.convite_dono (contrato do svc-identity)."""

    tenant: str
    email: str | None = None


class MemberLeft(BaseModel):
    """events.identity.member-left (contrato do svc-identity): quem saiu de qual organização."""

    tenant: str
    user: str


class ContextoEmpresa(BaseModel):
    """rpc.conhecimento.contexto (contrato do svc-conhecimento, só o que a lista de clientes usa)."""

    model_config = ConfigDict(extra="ignore")

    concluido_em: datetime | None = None


class OperadorResultado(BaseModel):
    user: str
    tenant: str
    roles: list[str]


# ── Fila: o que espera o staff nas organizações da carteira ─────────────────

TipoItem = Literal["excecao", "revisao", "ajuda", "pedido"]


class ItemStaff(BaseModel):
    """events.processos.staff (contrato do svc-processos, repetido aqui por quem consome)."""

    tipo: TipoItem
    ref: str
    titulo: str
    detalhe: str | None = None
    prazo: datetime | None = None
    status: Literal["aberta", "concluida"]
    link: str
    em: datetime
    por: str | None = Field(None, description="Quem resolveu (concluída por uma pessoa)")


class ItemFila(BaseModel):
    id: str
    organizacao: str
    organizacao_nome: str
    tipo: TipoItem
    ref: str
    titulo: str
    detalhe: str | None = None
    prazo: datetime | None = None
    status: Literal["aberta", "concluida"]
    link: str = Field(..., description="Onde resolver, na tela da organização (entre nela antes)")
    assumida_por: str | None = None
    atribuida_a: str | None = None
    escalada: bool = Field(False, description="Passou do prazo sem ninguém assumir: subiu para o gestor da carteira")
    concluida_em: datetime | None = None
    resolvida_por: str | None = Field(None, description="Quem resolveu (pela fila ou na tela do cliente)")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class FilaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("prazo", "created_at")
    default_sort: ClassVar[str | None] = "prazo"
    tipo: TipoItem | None = None
    status: Literal["aberta", "concluida"] | None = None
    escalada: bool | None = None
    todas: bool | None = Field(None, description="Gestor: a fila de todas as carteiras (não é filtro do banco)")
    organizacao: list[str] | None = None


class FilaPage(Page[ItemFila]):
    pass


class ItemRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Atribuicao(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    pessoa: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class FilaMudou(BaseModel):
    id: str
    action: Literal["chegou", "mudou", "escalada"]


class Escalados(BaseModel):
    itens: int


# ── Saúde dos clientes da carteira ───────────────────────────────────────────

class Acompanhamento(BaseModel):
    """rpc.processos.acompanhamento (contrato do svc-processos, só o que a carteira usa)."""

    model_config = ConfigDict(extra="ignore")

    andamento: int
    concluidas: int
    incidentes: int
    tarefas_cliente: int
    tarefas_staff: int
    atrasadas: int
    autonomia: float | None = None
    aceitos: int = 0
    publicados: int = 0


class Saude(BaseModel):
    organizacao: str
    nome: str
    andamento: int | None = None
    concluidas: int | None = None
    incidentes: int | None = None
    autonomia: float | None = None
    excecoes: int = Field(0, description="Exceções abertas na fila")
    revisoes: int = 0
    ajudas: int = 0
    pedidos: int = Field(0, description="Pedidos de ajuda (Falar com a Cogniventure) abertos")
    disponivel: bool = Field(True, description="Falso quando a organização não respondeu agora")


class MinhaCarteira(BaseModel):
    gestor: bool
    itens: list[Saude]


class Resumo(BaseModel):
    staff: bool = Field(..., description="Quem pergunta é da equipe da Cogniventure")
    gestor: bool
    excecoes: int = 0
    atrasadas: int = 0
    escaladas: int = 0
    revisoes: int = 0
    ajudas: int = 0
    pedidos: int = 0
    organizacoes: int = 0


# ── Clientes: a Cogniventure abre o cliente, dá o plano e o staff, e acompanha a jornada ──

Passo = Literal["convite", "briefing", "descoberta", "desenho", "acompanhamento"]


class NovoCliente(_Input):
    empresa: str = Field(..., min_length=2, max_length=80, description="Nome da empresa cliente")
    email: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="E-mail do dono, que recebe o convite")
    plano: PlanSlug = Field(..., description="Slug do plano do cliente")
    pessoa: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Quem do staff cuida dele (entra na carteira)")


class ClienteRef(_Input):
    organizacao: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Cliente(BaseModel):
    organizacao: str
    nome: str
    created_at: datetime | None = None
    plano: str | None = Field(None, description="Nome do plano (null: sem plano atribuído)")
    responsaveis: list[str] = Field(default_factory=list, description="Ids das pessoas do staff com o cliente na carteira")
    dono: Dono | None = None
    convite: ConvitePendente | None = Field(None, description="Convite de dono ainda não aceito")
    passo: Passo | None = Field(None, description="Onde o cliente está na jornada (null: não deu para saber agora)")
    ultimo_acesso: datetime | None = Field(None, description="Último acesso de alguém do cliente (o staff não conta)")
    andamento: int | None = None
    autonomia: float | None = None


class Clientes(BaseModel):
    itens: list[Cliente]


# ── Resolver pela fila (contratos do svc-processos e do svc-atendimento, só o que o cartão usa) ──

class CampoTarefa(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nome: str
    rotulo: str
    tipo: str
    valor: Any = None


class ItemContexto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rotulo: str
    valor: str


class TarefaFila(BaseModel):
    """rpc.processos.fila_tarefa: a exceção como o cartão da fila mostra."""

    model_config = ConfigDict(extra="ignore")

    id: str
    titulo: str
    nome: str
    status: str
    motivo: str | None = None
    campos: list[CampoTarefa] = Field(default_factory=list)
    contexto: list[ItemContexto] = Field(default_factory=list)
    aprende: bool = False
    prazo: datetime | None = None


class RevisaoFila(BaseModel):
    """rpc.processos.fila_revisao: a versão em revisão e o que ela muda."""

    processo: str
    titulo: str
    numero: int
    status: str
    mudancas: list[str] = Field(default_factory=list)


class MensagemPedido(BaseModel):
    model_config = ConfigDict(extra="ignore")

    papel: Literal["cliente", "staff"]
    autor_nome: str | None = None
    texto: str
    em: datetime


class PedidoFila(BaseModel):
    """rpc.atendimento.pedido: o pedido de ajuda com a conversa."""

    model_config = ConfigDict(extra="ignore")

    id: str
    assunto: str
    status: str
    pagina: str | None = None
    mensagens: list[MensagemPedido] = Field(default_factory=list)


class FilaDetalhe(BaseModel):
    item: ItemFila
    tarefa: TarefaFila | None = None
    revisao: RevisaoFila | None = None
    pedido: PedidoFila | None = None


class ResolverExcecao(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dados: dict[str, str | float | bool | None] = Field(default_factory=dict, description="A saída do passo que parou")
    comentario: str | None = Field(None, max_length=500)
    regra: str | None = Field(None, min_length=10, max_length=600, description="Exceção de agente: vira regra depois de avaliada")


class DecidirRevisao(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    aprovar: bool
    motivo: str | None = Field(None, min_length=3, max_length=1000, description="Ao devolver: o que precisa mudar")


class ResponderPedido(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    texto: str = Field(..., min_length=1, max_length=2000)


class ResolucaoStaff(BaseModel):
    """rpc.processos.fila_resolver."""

    id: str
    dados: dict[str, str | float | bool | None]
    comentario: str | None = None
    regra: str | None = None
    por: str


class DecisaoStaff(BaseModel):
    """rpc.processos.fila_decidir."""

    processo: str
    aprovar: bool
    motivo: str | None = None
    por: str


class RespostaStaff(BaseModel):
    """rpc.atendimento.responder."""

    id: str
    texto: str
    por: str
    por_nome: str | None = None


class RefTarefa(BaseModel):
    id: str


class RefRevisao(BaseModel):
    processo: str


# ── Números do gestor: tempo de resolução e prazo cumprido ───────────────────

class NumerosQuery(_Input):
    dias: int = Field(30, ge=1, le=365, description="Os últimos N dias")


class NumeroLinha(BaseModel):
    chave: str = Field(..., description="Id da pessoa ou da organização")
    nome: str | None = Field(None, description="Nome da organização (pessoa: a tela mostra pelo id)")
    resolvidos: int
    no_prazo: int = Field(..., description="Resolvidos até o prazo (item sem prazo conta como no prazo)")
    tempo_medio_min: float | None = Field(None, description="Da chegada à resolução, em minutos")
    abertos: int = 0


class Numeros(BaseModel):
    desde: datetime
    pessoas: list[NumeroLinha]
    clientes: list[NumeroLinha]
