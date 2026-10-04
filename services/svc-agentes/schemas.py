"""svc-agentes · contratos (DTOs, enums, constantes). Fonte da verdade: specs/agentes.md §2"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.plans import Module

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-agentes"
TASK_QUEUE = "agentes-queue"
EXECUTAR_SUBJECT = "rpc.agentes.executar"  # svc-processos: um passo de processo com um agente da organização
LISTA_SUBJECT = "rpc.agentes.lista"  # svc-processos: os agentes e o status deles (desenho e validação)
FERRAMENTAS_SUBJECT = "rpc.integracoes.ferramentas"  # svc-integracoes: as ferramentas MCP da organização
MCP_SUBJECT = "rpc.integracoes.mcp_chamar"  # svc-integracoes: chama a ferramenta com a credencial guardada lá
DOCUMENTO_SUBJECT = "rpc.integracoes.documento"  # svc-integracoes: o texto de um documento recebido
BUSCA_SUBJECT = "rpc.conhecimento.busca"  # svc-conhecimento: busca no conhecimento da empresa
LIVE_AGENTES = "agentes.agentes"

AGENTES = "agentes_agentes"
TABLES = [AGENTES]
UNIQUE = {AGENTES: ["nome"]}
WRITERS = frozenset({"owner", "admin", "operador"})  # a empresa e o staff da Cogniventure (ajuda no setup)
STAFF = frozenset({"operador"})  # só o staff marca um agente como confiável
MODELO_PADRAO = "cv/agente"
MAX_CASOS = 20
MAX_FERRAMENTAS = 20

MODULE = Module("Agentes", "Agentes da empresa: instrução, ferramentas do catálogo, política e suíte de avaliação",
                category="Sua empresa")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


def _key(value: Any) -> Any:
    """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave."""
    return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


Risco = Literal["leitura", "escrita", "externa", "irreversivel"]
Modo = Literal["permitir", "perguntar"]
Status = Literal["rascunho", "verificado", "confiavel"]
Tipo = Literal["texto", "numero", "sim_nao"]
Valor = str | float | bool
_REF = r"^(conhecimento|documento|mcp:[A-Za-z0-9_-]{1,64}:[^\s:]{1,128})$"


# ── O catálogo: o que um agente pode usar ────────────────────────────────────

class FerramentaCatalogo(BaseModel):
    ref: str = Field(..., description="conhecimento, documento ou mcp:<servidor>:<ferramenta>")
    nome: str
    descricao: str
    origem: Literal["plataforma", "mcp"]
    servidor_nome: str | None = None
    risco: Risco
    parametros: dict[str, Any] = Field(default_factory=dict)


class CatalogoFerramentas(BaseModel):
    itens: list[FerramentaCatalogo]
    integracoes: bool = Field(True, description="Falso quando o svc-integracoes não respondeu (só as da plataforma)")


# ── O agente ─────────────────────────────────────────────────────────────────

class FerramentaAgente(BaseModel):
    ref: str = Field(..., pattern=_REF)
    modo: Modo = Field("permitir", description="perguntar: o agente não usa sozinho; o passo vai para uma pessoa aprovar")


class Caso(BaseModel):
    """Um caso da suíte: dada a tarefa e os dados, o agente devolve o esperado."""

    id: str = Field(..., pattern=r"^[a-z0-9_-]{1,40}$")
    nome: str = Field(..., min_length=2, max_length=80)
    tarefa: str = Field(..., min_length=3, max_length=2000)
    dados: dict[str, Any] = Field(default_factory=dict, description="O que o passo teria à mão (ex.: ler_documento.*)")
    esperado: dict[str, Valor] = Field(..., min_length=1, description="Campo → valor que o agente precisa devolver")


class ResultadoCaso(BaseModel):
    caso: str
    ok: bool
    saida: dict[str, Any] = Field(default_factory=dict)
    detalhes: list[str] = Field(default_factory=list)
    ferramentas: list[str] = Field(default_factory=list, description="O que o agente chamou")


class Avaliacao(BaseModel):
    versao: int
    ok: bool
    resultados: list[ResultadoCaso]
    em: datetime


class Agente(BaseModel):
    id: str
    nome: str
    descricao: str = ""
    instrucao: str
    modelo: str = MODELO_PADRAO
    ferramentas: list[FerramentaAgente] = Field(default_factory=list)
    casos: list[Caso] = Field(default_factory=list)
    status: Status = Field("rascunho", description="verificado: passou na suíte; confiável: o staff decidiu")
    versao: int = Field(1, description="Sobe a cada mudança no que o agente faz; a avaliação vale para uma versão")
    avaliando: bool = False
    avaliacao: Avaliacao | None = None
    confiavel_por: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return _key(value)


class Agentes(BaseModel):
    itens: list[Agente]


class NovoAgente(_Input):
    nome: str = Field(..., min_length=2, max_length=60)
    descricao: str = Field("", max_length=300)
    instrucao: str = Field(..., min_length=10, max_length=4000)
    modelo: str = Field(MODELO_PADRAO, pattern=r"^[a-z0-9][a-z0-9-]{0,29}/\S{1,200}$")
    ferramentas: list[FerramentaAgente] = Field(default_factory=list, max_length=MAX_FERRAMENTAS)
    casos: list[Caso] = Field(default_factory=list, max_length=MAX_CASOS)


class EdicaoAgente(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    nome: str | None = Field(None, min_length=2, max_length=60)
    descricao: str | None = Field(None, max_length=300)
    instrucao: str | None = Field(None, min_length=10, max_length=4000)
    modelo: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9-]{0,29}/\S{1,200}$")
    ferramentas: list[FerramentaAgente] | None = Field(None, max_length=MAX_FERRAMENTAS)
    casos: list[Caso] | None = Field(None, max_length=MAX_CASOS)


class AgenteRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class SuiteRef(BaseModel):
    """Workflow da suíte: a versão avaliada (mudou no meio, o resultado não verifica a versão nova)."""

    id: str
    versao: int


class AgenteMudou(BaseModel):
    id: str
    action: Literal["criado", "alterado", "avaliando", "avaliado", "confiavel", "removido"]


# ── Rodar um agente ──────────────────────────────────────────────────────────

class Teste(_Input):
    """Experimentar o agente na tela, com uma tarefa e dados quaisquer."""

    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    tarefa: str = Field(..., min_length=3, max_length=2000)
    dados: dict[str, Any] = Field(default_factory=dict)
    saidas: dict[str, Tipo] = Field(..., min_length=1, description="Campo → tipo do que ele devolve")


class ExecutarAgente(BaseModel):
    """rpc.agentes.executar: um passo de processo com um agente da organização (o svc-processos confere o resultado)."""

    agente: str
    tarefa: str
    contexto: str = ""
    saidas: dict[str, Tipo]
    leitura: bool = Field(False, description="Passo de leitura: cada saída com o trecho de onde saiu (fontes)")
    regras: list[str] = Field(default_factory=list, description="O que o staff ensinou para este passo")
    obrigatorias: list[str] | None = Field(None, description="Sem estas o passo não conclui; vazio: todas as saídas")


class Execucao(BaseModel):
    saidas: dict[str, Any] = Field(default_factory=dict)
    fontes: dict[str, str] = Field(default_factory=dict)
    ajuda: str | None = Field(None, description="O agente pediu ajuda: o motivo")
    aprovacao: str | None = Field(None, description="A política pede aprovação de uma pessoa para o que ele ia fazer")
    ferramentas: list[str] = Field(default_factory=list, description="O que ele chamou, na ordem")
    lidos: list[str] = Field(default_factory=list, description="O que ele leu (documentos e respostas das ferramentas)")
    texto: str = ""


class ResumoAgente(BaseModel):
    id: str
    nome: str
    descricao: str
    status: Status
    ferramentas: list[str]


class ListaAgentes(BaseModel):
    itens: list[ResumoAgente]


# ── Contratos de quem este serviço consome (repetidos aqui por quem consome) ─

class FerramentaDisponivel(BaseModel):
    """rpc.integracoes.ferramentas (svc-integracoes)."""

    servidor: str
    servidor_nome: str
    nome: str
    descricao: str
    parametros: dict[str, Any]
    risco: Risco


class FerramentasDisponiveis(BaseModel):
    itens: list[FerramentaDisponivel]


class ChamadaMcp(BaseModel):
    servidor: str
    ferramenta: str
    argumentos: dict[str, Any] = Field(default_factory=dict)


class ResultadoMcp(BaseModel):
    ok: bool
    texto: str
    dados: Any = None


class DocumentoRef(BaseModel):
    id: str


class DocumentoTexto(BaseModel):
    """rpc.integracoes.documento (svc-integracoes)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    nome: str
    tipo: str
    assunto: str | None = None
    texto: str


class BuscaQuery(BaseModel):
    q: str


class Achados(BaseModel):
    """rpc.conhecimento.busca (svc-conhecimento)."""

    itens: list[dict[str, Any]]


# ── Argumentos das ferramentas da plataforma ─────────────────────────────────

class LeituraDocumento(BaseModel):
    documento_id: str = Field(..., description="O id do documento (gatilho.documento_id)")


class Consulta(BaseModel):
    consulta: str = Field(..., min_length=2, max_length=300, description="O que procurar no conhecimento da empresa")


class PedidoAjuda(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=400, description="Por que não dá para concluir com segurança")


INSTRUCOES_PLATAFORMA = """Regras da plataforma (valem acima da instrução do agente):
- Use só as ferramentas que tem; o que não está nelas nem nos dados você não sabe.
- Quando tiver certeza, chame concluir com as saídas pedidas. Valores em reais são números (1250.5); datas, AAAA-MM-DD; sim/não, true ou false.
- Se não der para concluir com segurança (falta dado, ferramenta falhou, resposta duvidosa, pedido fora da política), não chute: chame pedir_ajuda com o motivo em uma frase. Uma pessoa resolve.
- Ferramenta que responde pedindo aprovação não foi executada: chame pedir_ajuda dizendo o que ia fazer.
- Chame concluir ou pedir_ajuda uma única vez e termine."""
