"""Processos (briefing.md §5): o fluxo tipado, as ações que os pacotes oferecem e o motor (Camunda 8). README §5.20

    ACTIONS = [Action("conferir_pedido", "Conferir com o pedido", "Compara o documento com o pedido ou o contrato",
                      Documento, Conferencia, risk="leitura", example=Conferencia(divergente=False))]
    await processes.declare(ACTIONS)                    # main.py, no lifespan: o catálogo vai para o svc-processos

    xml = to_bpmn(fluxo, process_id="p_acme_contas", name="Contas a pagar")   # o fluxo tipado vira BPMN com diagrama
    definicao = await camunda.deploy(xml, "p_acme_contas")                     # só o svc-processos implanta

Trilhos:
- O fluxo (Fluxo) é o que se edita: passos tipados, ligações e condições estruturadas. Ninguém escreve BPMN nem FEEL:
  to_bpmn gera os dois, com as extensões do Camunda e o desenho (BPMN DI) para a tela.
- Cada passo grava a saída sob o próprio id (ler_documento.valor); condição compara um campo de saída (ou um
  parâmetro, parametros.<nome>) com um valor ou com outro parâmetro. Os parâmetros vão no BPMN, na saída do início:
  mudar um limite é uma versão nova no motor, e a execução usa os valores da versão em que começou.
- Ação: <serviço>.<nome>, com entrada, saída, risco (leitura, escrita, externa, irreversivel), exemplo de saída (a
  simulação usa) e conexões que exige. O exemplo é conferido contra a saída na declaração.
- O motor fica atrás deste arquivo: trocar o Camunda por outro motor BPMN muda to_bpmn e o cliente, não os serviços.

Variáveis: CAMUNDA_URL (API REST do Orchestration Cluster; padrão http://localhost:8080).
"""
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from xml.sax.saxutils import escape

import httpx
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.envelope import ServiceError
from core.nats_bus import bus

__all__ = [
    "Action", "ActionCatalog", "Alternative", "CatalogAction", "Condition", "Flow", "Fluxo", "Step", "Trigger", "Deployed",
    "camunda", "processes", "to_bpmn", "CATALOG_SUBJECT", "START", "HANDOFF_ERROR",
]

CATALOG_SUBJECT = "events.processos.catalogo"
START = "inicio"  # id reservado: o começo do fluxo (o gatilho)
HANDOFF_ERROR = "handoff"  # código do erro BPMN que leva um passo à tarefa do staff
Risk = Literal["leitura", "escrita", "externa", "irreversivel"]
_ID = r"^[a-z][a-z0-9_]{0,39}$"
_ACTION = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_]{0,39}$")


# ── O fluxo tipado ───────────────────────────────────────────────────────────

class Alternative(BaseModel):
    campo: str = Field(..., pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", description="<passo>.<campo> ou parametros.<nome>")
    operador: Literal["=", "!=", ">", ">=", "<", "<=", "verdadeiro", "falso"]
    valor: str | float | bool | None = Field(None, description="Valor comparado; parametros.<nome> compara com um parâmetro")


class Condition(Alternative):
    """Condição de um caminho que sai de uma decisão: campo, operador e valor (ou parametros.<nome>); com ou, basta
    uma delas valer (ex.: valor acima do limite ou fornecedor novo)."""

    ou: list[Alternative] = Field(default_factory=list, description="Outras condições: o caminho vale se qualquer uma valer")

    def alternatives(self) -> list[Alternative]:
        return [self, *self.ou]


class Flow(BaseModel):
    de: str = Field(..., pattern=_ID)
    para: str = Field(..., pattern=_ID)
    condicao: Condition | None = Field(None, description="Só saindo de decisão; sem condição é o caminho padrão")


class Step(BaseModel):
    id: str = Field(..., pattern=_ID, description="Identificador curto em snake_case (a saída fica sob ele)")
    tipo: Literal["acao", "agente", "tarefa", "decisao", "espera", "fim"]
    nome: str = Field(..., min_length=2, max_length=80)
    acao: str | None = Field(None, description="acao: nome no catálogo (<pacote>.<ação>)")
    objetivo: str | None = Field(None, max_length=600, description="agente: o que o agente faz neste passo")
    saidas: list[str] = Field(default_factory=list, description="agente: campos que o agente devolve")
    exemplo: dict[str, str | float | bool] = Field(default_factory=dict, description="agente: saída de exemplo para a simulação")
    responsavel: Literal["cliente", "staff"] | None = Field(None, description="tarefa: quem decide")
    pergunta: str | None = Field(None, max_length=200, description="tarefa: o que a pessoa decide (a saída é aprovado)")
    espera: Literal["mensagem", "tempo"] | None = None
    mensagem: str | None = Field(None, pattern=r"^[a-z][a-z0-9_.-]{1,60}$", description="espera: mensagem que chega (ex.: banco.pago)")
    chave: str | None = Field(None, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", description="espera: campo que identifica a execução")
    horas: float | None = Field(None, gt=0, le=24 * 365, description="espera tempo: quanto; tarefa e espera de mensagem: prazo")
    excecao: bool = Field(False, description="acao e agente: caminho de handoff para o staff")
    resultado: str | None = Field(None, max_length=40, description="fim: como termina (ex.: pago, recusado)")


class Trigger(BaseModel):
    tipo: Literal["evento", "agenda", "manual"] = "manual"
    evento: str | None = Field(None, pattern=r"^[a-z][a-z0-9_.-]{1,60}$", description="evento: mensagem que inicia")
    agenda: str | None = Field(None, max_length=60, description="agenda: cron (ex.: 0 8 * * *)")
    descricao: str | None = Field(None, max_length=200)


class Fluxo(BaseModel):
    gatilho: Trigger = Field(default_factory=Trigger)
    passos: list[Step] = Field(default_factory=list)
    ligacoes: list[Flow] = Field(default_factory=list)
    parametros: dict[str, str | float | bool] = Field(default_factory=dict)

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.passos if s.id == step_id), None)

    def outgoing(self, step_id: str) -> list[Flow]:
        return [f for f in self.ligacoes if f.de == step_id]


# ── Ações dos pacotes ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Action:
    """Uma ação que o pacote oferece aos processos: nome curto (snake), entrada, saída, risco e exemplo de saída."""

    name: str
    title: str
    description: str
    input: type[BaseModel]
    output: type[BaseModel]
    risk: Risk
    example: BaseModel
    connections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.match(_ID, self.name):
            raise ValueError(f"Action: nome inválido {self.name!r} (snake_case, ex.: agendar_pagamento)")
        if not isinstance(self.example, self.output):
            raise TypeError(f"Action {self.name!r}: o exemplo precisa ser um {self.output.__name__}")
        if not 3 <= len(self.description) <= 300:
            raise ValueError(f"Action {self.name!r}: descrição de 3 a 300 caracteres")


class CatalogAction(BaseModel):
    name: str = Field(..., description="<pacote>.<ação>")
    service: str
    title: str
    description: str
    risk: Risk
    connections: list[str] = Field(default_factory=list)
    output_fields: list[str] = Field(default_factory=list, description="Campos da saída (o que as condições podem usar)")
    example: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ActionCatalog(BaseModel):
    service: str
    actions: list[CatalogAction]


class Processes:
    def __init__(self) -> None:
        self._declared: dict[str, Action] = {}

    async def declare(self, actions: Sequence[Action]) -> None:
        """No boot: publica para o svc-processos as ações que este pacote oferece (o catálogo do desenho)."""
        service = bus.service
        if not service:
            raise RuntimeError("processes.declare: chame dentro de bus.connected(SERVICE)")
        prefix = service.removeprefix("svc-")
        names = [a.name for a in actions]
        if len(names) != len(set(names)):
            raise ValueError("processes.declare: ação repetida")
        self._declared = {f"{prefix}.{a.name}": a for a in actions}
        catalog = ActionCatalog(service=service, actions=[
            CatalogAction(name=name, service=service, title=a.title, description=a.description, risk=a.risk,
                          connections=list(a.connections), output_fields=list(a.output.model_fields),
                          example=a.example.model_dump(mode="json"), input_schema=a.input.model_json_schema(),
                          output_schema=a.output.model_json_schema())
            for name, a in self._declared.items()
        ])
        digest = hashlib.sha256(catalog.model_dump_json().encode()).hexdigest()[:24]
        await bus.publish(CATALOG_SUBJECT, catalog, msg_id=f"acoes-{service}-{digest}")  # réplicas: um só

    def declared(self) -> dict[str, Action]:
        return dict(self._declared)


processes = Processes()


# ── Do fluxo ao BPMN do Camunda 8 ────────────────────────────────────────────

_SIZE = {"event": (36, 36), "task": (110, 70), "gateway": (50, 50)}
_GAP_X, _ROW_Y, _LEFT, _TOP = 150, 120, 60, 60
_ANCHOR_BASE = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" \
xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" \
xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:modeler="http://camunda.org/schema/modeler/1.0" \
id="definicoes" targetNamespace="https://cogniventure.com/processos" modeler:executionPlatform="Camunda Cloud" \
modeler:executionPlatformVersion="8.10.0">"""


def _feel_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str) and value.startswith("parametros.") and re.match(r"^parametros\.[a-z][a-z0-9_]*$", value):
        return value
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _feel_one(alt: Alternative) -> str:
    if alt.operador == "verdadeiro":
        return f"{alt.campo} = true"
    if alt.operador == "falso":
        return f"{alt.campo} = false"
    return f"{alt.campo} {alt.operador} {_feel_value(alt.valor)}"


def feel(condition: Condition) -> str:
    """Condição estruturada → expressão FEEL (=campo > 5000; com ou: =(a) or (b)). Valores sempre escapados."""
    partes = [_feel_one(alt) for alt in condition.alternatives()]
    return "=" + (partes[0] if len(partes) == 1 else " or ".join(f"({p})" for p in partes))


def _kind(step: Step | None) -> str:
    if step is None or step.tipo in ("espera", "fim"):
        return "event"
    return "gateway" if step.tipo == "decisao" else "task"


def _layout(fluxo: Fluxo) -> dict[str, tuple[float, float, int, int]]:
    """Posição (x, y, largura, altura) de cada nó: camadas da esquerda para a direita pelo caminho mais longo,
    ramos empilhados; as tarefas de exceção ficam logo abaixo do passo."""
    rank: dict[str, int] = {START: 0}
    order = [START]
    stack: set[str] = set()

    def visit(node: str) -> None:
        stack.add(node)
        for flow in fluxo.outgoing(node):
            if flow.para in stack or fluxo.step(flow.para) is None:
                continue  # volta (laço) ou destino inexistente: não empurra camada
            if rank.get(flow.para, -1) < rank[node] + 1:
                rank[flow.para] = rank[node] + 1
                if flow.para not in order:
                    order.append(flow.para)
                visit(flow.para)
        stack.discard(node)

    visit(START)
    for step in fluxo.passos:  # soltos (ainda sem ligação) ficam no fim
        if step.id not in rank:
            rank[step.id] = max(rank.values()) + 1
            order.append(step.id)
    rows: dict[int, int] = {}
    pos: dict[str, tuple[float, float, int, int]] = {}
    for node in order:
        layer = rank[node]
        row = rows.get(layer, 0)
        rows[layer] = row + 1
        w, h = _SIZE[_kind(fluxo.step(node))] if node != START else _SIZE["event"]
        cx, cy = _LEFT + layer * _GAP_X + 55, _TOP + row * _ROW_Y + 40
        pos[node] = (cx - w / 2, cy - h / 2, w, h)
    for step in fluxo.passos:
        if step.excecao and step.tipo in ("acao", "agente") and step.id in pos:
            x, y, w, h = pos[step.id]
            pos[f"{step.id}__excecao"] = (x, y + h + 70, *_SIZE["task"])
    return pos


def _edge(src: tuple[float, float, int, int], dst: tuple[float, float, int, int]) -> list[tuple[float, float]]:
    sx, sy, sw, sh = src
    tx, ty, tw, th = dst
    start, end = (sx + sw, sy + sh / 2), (tx, ty + th / 2)
    if end[0] <= start[0]:  # volta: por baixo
        low = max(sy + sh, ty + th) + 40
        return [(sx + sw / 2, sy + sh), (sx + sw / 2, low), (tx + tw / 2, low), (tx + tw / 2, ty + th)]
    if abs(start[1] - end[1]) < 1:
        return [start, end]
    mid = (start[0] + end[0]) / 2
    return [start, (mid, start[1]), (mid, end[1]), end]


def to_bpmn(fluxo: Fluxo, *, process_id: str, name: str) -> str:
    """O fluxo tipado como BPMN 2.0 com as extensões do Camunda 8 (zeebe:) e o desenho (DI) para a tela."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.-]{0,99}$", process_id):
        raise ValueError(f"to_bpmn: id de processo inválido {process_id!r}")
    a = lambda v: escape(str(v), {'"': "&quot;"})  # noqa: E731 - atributo XML
    pos = _layout(fluxo)
    messages: dict[str, str] = {}
    elements: list[str] = []
    flows: list[tuple[str, str, str, Condition | None]] = []
    uses_error = False

    def message_ref(message: str, key: str | None) -> str:
        ref = "m_" + re.sub(r"[^a-z0-9]", "_", message)
        sub = f'<bpmn:extensionElements><zeebe:subscription correlationKey="={a(key)}" /></bpmn:extensionElements>' if key else ""
        messages.setdefault(ref, f'<bpmn:message id="{ref}" name="{a(message)}">{sub}</bpmn:message>')
        return ref

    trigger = fluxo.gatilho
    if trigger.tipo == "evento" and trigger.evento:
        definition = f'<bpmn:messageEventDefinition messageRef="{message_ref(trigger.evento, None)}" />'
    elif trigger.tipo == "agenda" and trigger.agenda:
        definition = f'<bpmn:timerEventDefinition><bpmn:timeCycle xsi:type="bpmn:tFormalExpression">{escape(trigger.agenda)}</bpmn:timeCycle></bpmn:timerEventDefinition>'
    else:
        definition = ""
    # Os parâmetros vão no BPMN (saída do início): cada versão publicada carrega os seus valores.
    params = "".join(f'<zeebe:output source="{a("=" + _feel_value(v))}" target="parametros.{k}" />' for k, v in fluxo.parametros.items())
    params = f"<bpmn:extensionElements><zeebe:ioMapping>{params}</zeebe:ioMapping></bpmn:extensionElements>" if params else ""
    elements.append(f'<bpmn:startEvent id="{START}" name="{a(trigger.descricao or "Início")}">{params}{definition}</bpmn:startEvent>')

    for step in fluxo.passos:
        sid, label = step.id, a(step.nome)
        if step.tipo in ("acao", "agente"):
            job = step.acao if step.tipo == "acao" else "agentes.executar"
            headers = [("passo", sid)]
            if step.tipo == "agente":
                headers += [("objetivo", step.objetivo or ""), ("saidas", ",".join(step.saidas))]
            header_xml = "".join(f'<zeebe:header key="{k}" value="{a(v)}" />' for k, v in headers)
            elements.append(f'<bpmn:serviceTask id="{sid}" name="{label}"><bpmn:extensionElements>'
                            f'<zeebe:taskDefinition type="{a(job or "")}" retries="3" />'
                            f"<zeebe:taskHeaders>{header_xml}</zeebe:taskHeaders></bpmn:extensionElements></bpmn:serviceTask>")
        elif step.tipo == "tarefa":
            due = f'<zeebe:taskSchedule dueDate="=now() + duration(&quot;PT{int(step.horas)}H&quot;)" />' if step.horas else ""
            elements.append(f'<bpmn:userTask id="{sid}" name="{label}"><bpmn:extensionElements><zeebe:userTask />'
                            f'<zeebe:assignmentDefinition candidateGroups="{a(step.responsavel or "cliente")}" />{due}'
                            f'<zeebe:properties><zeebe:property name="pergunta" value="{a(step.pergunta or step.nome)}" /></zeebe:properties>'
                            "</bpmn:extensionElements></bpmn:userTask>")
        elif step.tipo == "decisao":
            default = next((f for f in fluxo.outgoing(sid) if f.condicao is None), None)
            attr = f' default="f_{sid}_{default.para}"' if default else ""
            elements.append(f'<bpmn:exclusiveGateway id="{sid}" name="{label}"{attr} />')
        elif step.tipo == "espera":
            if step.espera == "mensagem" and step.mensagem:
                inner = f'<bpmn:messageEventDefinition messageRef="{message_ref(step.mensagem, step.chave)}" />'
            else:
                inner = f'<bpmn:timerEventDefinition><bpmn:timeDuration xsi:type="bpmn:tFormalExpression">PT{int(step.horas or 1)}H</bpmn:timeDuration></bpmn:timerEventDefinition>'
            elements.append(f'<bpmn:intermediateCatchEvent id="{sid}" name="{label}">{inner}</bpmn:intermediateCatchEvent>')
        else:
            elements.append(f'<bpmn:endEvent id="{sid}" name="{label}" />')
        for flow in fluxo.outgoing(sid):
            if fluxo.step(flow.para) is not None:  # ligação para passo que não existe (rascunho): fica de fora
                flows.append((f"f_{sid}_{flow.para}", sid, flow.para, flow.condicao if step.tipo == "decisao" else None))
        if step.excecao and step.tipo in ("acao", "agente"):
            uses_error = True
            nxt = next((f.para for f in fluxo.outgoing(sid) if fluxo.step(f.para) is not None), None)
            elements.append(f'<bpmn:boundaryEvent id="{sid}__erro" attachedToRef="{sid}">'
                            f'<bpmn:errorEventDefinition errorRef="e_{HANDOFF_ERROR}" /></bpmn:boundaryEvent>')
            elements.append(f'<bpmn:userTask id="{sid}__excecao" name="Exceção: {label}"><bpmn:extensionElements>'
                            '<zeebe:userTask /><zeebe:assignmentDefinition candidateGroups="staff" /></bpmn:extensionElements></bpmn:userTask>')
            flows.append((f"f_{sid}__erro", f"{sid}__erro", f"{sid}__excecao", None))
            if nxt:
                flows.append((f"f_{sid}__excecao_{nxt}", f"{sid}__excecao", nxt, None))
    for flow in fluxo.outgoing(START):
        if fluxo.step(flow.para) is not None:
            flows.append((f"f_{START}_{flow.para}", START, flow.para, None))

    for fid, src, dst, cond in flows:
        body = f'<bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">{escape(feel(cond))}</bpmn:conditionExpression>' if cond else ""
        elements.append(f'<bpmn:sequenceFlow id="{fid}" sourceRef="{src}" targetRef="{dst}">{body}</bpmn:sequenceFlow>')

    shapes, edges = [], []
    for node, (x, y, w, h) in pos.items():
        shapes.append(f'<bpmndi:BPMNShape id="{node}_di" bpmnElement="{node}"><dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" /></bpmndi:BPMNShape>')
        if node.endswith("__excecao"):
            step_id = node.removesuffix("__excecao")
            sx, sy, sw, sh = pos[step_id]
            shapes.append(f'<bpmndi:BPMNShape id="{step_id}__erro_di" bpmnElement="{step_id}__erro"><dc:Bounds x="{sx + sw - 30:.0f}" y="{sy + sh - 18:.0f}" width="36" height="36" /></bpmndi:BPMNShape>')
    for fid, src, dst, _ in flows:
        if src.endswith("__erro"):  # do evento de erro, na borda de baixo do passo, até a exceção logo abaixo
            sx, sy, sw, sh = pos[src.removesuffix("__erro")]
            points = [(sx + sw - 12, sy + sh + 18), (sx + sw - 12, pos[dst][1])]
        elif src in pos and dst in pos:
            points = _edge(pos[src], pos[dst])
        else:
            continue
        waypoints = "".join(f'<di:waypoint x="{px:.0f}" y="{py:.0f}" />' for px, py in points)
        edges.append(f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{waypoints}</bpmndi:BPMNEdge>')

    error = f'<bpmn:error id="e_{HANDOFF_ERROR}" name="Exceção" errorCode="{HANDOFF_ERROR}" />' if uses_error else ""
    return (
        f'{_ANCHOR_BASE}<bpmn:process id="{process_id}" name="{a(name)}" isExecutable="true">{"".join(elements)}</bpmn:process>'
        f"{''.join(messages.values())}{error}"
        f'<bpmndi:BPMNDiagram id="diagrama"><bpmndi:BPMNPlane id="plano" bpmnElement="{process_id}">'
        f"{''.join(shapes)}{''.join(edges)}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
    )


# ── O motor: Camunda 8 (API REST do Orchestration Cluster) ───────────────────

class CamundaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAMUNDA_", extra="ignore")

    url: str = "http://localhost:8080"


class Deployed(BaseModel):
    """O que o motor guardou: o id do processo, a chave da definição e a versão dele (1, 2, 3...)."""

    process_id: str
    key: str
    version: int


class Camunda:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def deploy(self, xml: str, process_id: str) -> Deployed:
        """Implanta o BPMN. Mesmo id de processo = versão seguinte; execuções em andamento ficam na versão delas."""
        files = {"resources": (f"{process_id}.bpmn", xml.encode(), "application/xml")}
        response = await self._call("POST", "/v2/deployments", files=files)
        if response.status_code >= 400:
            detail = _problem(response)
            raise ServiceError("ERRO_PROCESSOS_BPMN", f"O motor recusou o processo: {detail}", status=422)
        for item in response.json().get("deployments", []):
            definition = item.get("processDefinition")
            if definition and definition.get("processDefinitionId") == process_id:
                return Deployed(process_id=process_id, key=str(definition["processDefinitionKey"]),
                                version=int(definition["processDefinitionVersion"]))
        raise ServiceError("ERRO_PROCESSOS_MOTOR", "O motor não devolveu a definição implantada.", status=502)

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=CamundaSettings().url, timeout=httpx.Timeout(30.0, connect=5.0))
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.TransportError:
            raise ServiceError("ERRO_PROCESSOS_MOTOR", "O motor de processos não respondeu. Tente de novo em instantes.", status=503) from None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _problem(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    return str(body.get("detail") or body.get("title") or f"HTTP {response.status_code}")[:300]


camunda = Camunda()


def parse_fluxo(data: Any) -> Fluxo:
    """Fluxo guardado (dict) → modelo, com erro claro se o formato mudou."""
    try:
        return Fluxo.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"fluxo guardado inválido: {exc.errors()[0]['msg']}") from None
