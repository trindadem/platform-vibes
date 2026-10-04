"""svc-atendimento · contratos (DTOs, enums, constantes). Fonte da verdade: specs/atendimento.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings

from core.plans import Module
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-atendimento"
TASK_QUEUE = "atendimento-queue"
STAFF_SUBJECT = "events.atendimento.staff"  # para a fila do svc-staff (o contrato ItemStaff da fila)
PEDIDO_SUBJECT = "rpc.atendimento.pedido"  # svc-staff: o pedido, para o cartão da fila
RESPONDER_SUBJECT = "rpc.atendimento.responder"  # svc-staff: o staff responde pela fila, sem trocar de organização
STAFF_SERVICE = "svc-staff"  # o único que chama as RPCs do staff
LIVE_PEDIDOS = "atendimento.pedidos"

PEDIDOS = "atendimento_pedidos"
TABLES = [PEDIDOS]
SEARCH = {PEDIDOS: ["assunto"]}
PRAZO_HORAS = 4  # o staff responde em até 4 horas (alinhamento pós-N7, item 5)
VEEM_TODOS = frozenset({"owner", "admin", "operador"})  # o resto (membro) vê só os próprios pedidos
GESTORES = frozenset({"owner", "admin"})

# Da plataforma (sempre ligado): todo cliente fala com a Cogniventure, qualquer que seja o plano.
MODULE = Module("Falar com a Cogniventure", "Pedidos de ajuda ao staff da Cogniventure, com resposta em até 4 horas",
                category="Organização", core=True)


class AtendimentoSettings(BaseSettings):
    platform_tenant: str | None = Field(None, description="A organização da Cogniventure: ela não pede ajuda a si mesma")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _key(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


StatusPedido = Literal["aberto", "respondido", "encerrado"]


class Mensagem(BaseModel):
    papel: Literal["cliente", "staff"]
    autor: str = Field(..., description="Id de quem escreveu")
    autor_nome: str | None = None
    texto: str
    em: datetime


class Pedido(BaseModel):
    id: str
    assunto: str = Field(..., description="As primeiras palavras do pedido")
    status: StatusPedido
    pagina: str | None = Field(None, description="A tela de onde a pessoa pediu ajuda")
    autor: str
    autor_nome: str | None = None
    mensagens: list[Mensagem]
    prazo: datetime | None = Field(None, description="Até quando o staff responde (4 h depois da última mensagem do cliente)")
    respondido_em: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class PedidoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "updated_at")
    default_sort: ClassVar[str | None] = "-updated_at"
    status: StatusPedido | None = None
    autor: str | None = Field(None, description="Só os pedidos desta pessoa (o membro vê sempre só os seus)")


class PedidoPage(Page[Pedido]):
    pass


class NovoPedido(_Input):
    texto: str = Field(..., min_length=3, max_length=2000, description="O que a pessoa precisa")
    pagina: str | None = Field(None, max_length=300, pattern=r"^/[^\s]*$", description="A tela de onde pediu (ex.: /processos/execucoes)")


class MensagemNova(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    texto: str = Field(..., min_length=1, max_length=2000)


class PedidoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Resposta(BaseModel):
    """rpc.atendimento.responder: o staff responde pela fila (o svc-staff conferiu que a pessoa cuida do cliente)."""

    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    texto: str = Field(..., min_length=1, max_length=2000)
    por: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Id da pessoa do staff")
    por_nome: str | None = Field(None, max_length=80)


class Resumo(BaseModel):
    pode_pedir: bool = Field(..., description="Falso na organização da Cogniventure e para quem só é operador ali")
    abertos: int = 0
    respondidos: int = 0


class PedidoMudou(BaseModel):
    id: str
    action: Literal["aberto", "respondido", "encerrado"]


class ItemStaff(BaseModel):
    """events.atendimento.staff: o contrato da fila do svc-staff (o mesmo de events.processos.staff)."""

    tipo: Literal["pedido"]
    ref: str
    titulo: str
    detalhe: str | None = None
    prazo: datetime | None = None
    status: Literal["aberta", "concluida"]
    link: str
    em: datetime
    por: str | None = Field(None, description="Quem resolveu (concluída pelo staff)")
