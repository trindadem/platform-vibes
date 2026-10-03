"""Processos (briefing.md §5): o fluxo tipado, as ações que os pacotes oferecem e o motor (Camunda 8). README §5.20

    ACTIONS = [Action("conferir_pedido", "Conferir com o pedido", "Compara o documento com o pedido ou o contrato",
                      Documento, Conferencia, risk="leitura", example=Conferencia(divergente=False))]
    await processes.declare(ACTIONS)                    # main.py, no lifespan: o catálogo vai para o svc-processos

    async with processes.worker(SERVICE, ACTIONS, svc):  # main.py: cada ação roda o método de mesmo nome do service.py
        ...                                              # (conferir_pedido(self, data: Documento) -> Conferencia)

    xml = to_bpmn(fluxo, process_id=process_id("acme", "contas"), name="Contas a pagar", actions=catalogo)
    definicao = await camunda.deploy(xml, "p_acme_contas")                     # só o svc-processos implanta e inicia
    execucao = await camunda.start("p_acme_contas", {"gatilho": {...}})

Trilhos:
- O fluxo (Fluxo) é o que se edita: passos tipados, ligações e condições estruturadas. Ninguém escreve BPMN nem FEEL:
  to_bpmn gera os dois, com as extensões do Camunda e o desenho (BPMN DI) para a tela.
- Cada passo grava a saída sob o próprio id (ler_documento.valor); condição compara um campo de saída (ou um
  parâmetro, parametros.<nome>) com um valor ou com outro parâmetro. Os parâmetros vão no BPMN, na saída do início:
  mudar um limite é uma versão nova no motor, e a execução usa os valores da versão em que começou.
- Ação: <serviço>.<nome>, com entrada, saída, risco (leitura, escrita, externa, irreversivel), exemplo de saída (a
  simulação usa) e conexões que exige. O exemplo é conferido contra a saída na declaração.
- Execução: o worker de cada pacote pega os jobs <serviço>.<ação> no motor e age como a organização do processo (o id
  no motor é p_<organização>_<processo>, só o svc-processos implanta). A entrada vem dos passos anteriores pelo nome do
  campo (o mais perto antes dele; senão, do gatilho); a saída validada vai para <passo>. Ação que não pode seguir
  levanta Handoff(motivo) (ou um ServiceError de negócio, status < 500): com caminho de exceção, vira a tarefa do staff;
  sem ele, incidente. Erro de infraestrutura volta ao motor para nova tentativa. Módulo fora do plano vira handoff.
- O que cada worker fez num passo sai em events.processos.passo (o acompanhamento no svc-processos). O svc-processos
  também atende os jobs que o BPMN gera para ele: começo da execução, tarefa de pessoa criada, espera e fim.
- Mensagens no motor levam a organização no nome (<organização>.<mensagem>): uma organização não acorda a outra.
- O motor fica atrás deste arquivo: trocar o Camunda por outro motor BPMN muda to_bpmn e o cliente, não os serviços.

Variáveis: CAMUNDA_URL (API REST do Orchestration Cluster; padrão http://localhost:8080).
"""
import asyncio
import hashlib
import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, get_type_hints
from xml.sax.saxutils import escape

import httpx
from opentelemetry import metrics
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.envelope import ServiceError
from core.nats_bus import bus
from core.plans import plans
from core.security import acting_as, system

__all__ = [
    "Action", "ActionCatalog", "Alternative", "CatalogAction", "Condition", "Flow", "Fluxo", "Step", "Trigger", "Deployed",
    "Started", "Job", "Handoff", "StepEvent", "camunda", "processes", "to_bpmn", "process_id", "parse_process_id",
    "CATALOG_SUBJECT", "STEP_SUBJECT", "START", "HANDOFF_ERROR", "JOB_AGENT", "JOB_START", "JOB_TASK", "JOB_WAIT", "JOB_END",
]

CATALOG_SUBJECT = "events.processos.catalogo"
STEP_SUBJECT = "events.processos.passo"  # o que um worker fez num passo (concluiu, handoff, incidente)
START = "inicio"  # id reservado: o começo do fluxo (o gatilho)
HANDOFF_ERROR = "handoff"  # código do erro BPMN que leva um passo à tarefa do staff
HANDOFF_HOURS = 4  # prazo da tarefa de exceção do staff
# Jobs que o BPMN gera para o svc-processos (o acompanhamento): passo de agente e os ouvintes de execução e de tarefa.
JOB_AGENT = "agentes.executar"
JOB_START = "processos.inicio"  # a execução começou (qualquer gatilho, inclusive agenda)
JOB_TASK = "processos.tarefa"  # uma tarefa de pessoa foi criada (aprovação do cliente, exceção do staff)
JOB_WAIT = "processos.espera"  # a execução entrou numa espera (mensagem ou tempo)
JOB_END = "processos.fim"  # a execução chegou a um fim
_PROCESS_ID = re.compile(r"^p_([A-Za-z0-9]{1,40})_([A-Za-z0-9]{1,64})$")
log = logging.getLogger("core.processes")


def process_id(tenant: str, processo: str) -> str:
    """Id do processo no motor: p_<organização>_<processo>. A organização no id é de onde o worker tira quem age."""
    value = f"p_{tenant}_{processo}"
    if not _PROCESS_ID.match(value):
        raise ValueError(f"process_id: organização e processo só com letras e números ({tenant!r}, {processo!r})")
    return value


def parse_process_id(value: str) -> tuple[str, str] | None:
    """p_<organização>_<processo> → (organização, processo); outro formato → None (não é um processo nosso)."""
    match = _PROCESS_ID.match(value or "")
    return (match.group(1), match.group(2)) if match else None
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


class Job(BaseModel):
    """Um job do motor, já traduzido: de que organização e processo, em que passo, com que variáveis."""

    key: str
    type: str
    kind: str = Field("BPMN_ELEMENT", description="BPMN_ELEMENT (passo), TASK_LISTENER ou EXECUTION_LISTENER")
    listener: str = Field("UNSPECIFIED", description="Ouvinte: START, END, CREATING...")
    tenant: str
    processo: str = Field(..., description="Id do processo no svc-processos")
    process_id: str
    version: int = Field(..., description="Versão no motor")
    instance: str = Field(..., description="Execução (process instance) no motor")
    element: str = Field(..., description="Elemento do BPMN: o id do passo (ou do processo, no ouvinte do processo)")
    element_instance: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    user_task: dict[str, Any] | None = None
    retries: int = 3

    @classmethod
    def from_engine(cls, raw: Mapping[str, Any]) -> "Job":
        parsed = parse_process_id(str(raw.get("processDefinitionId", "")))
        if parsed is None:
            raise ValueError(f"job de processo fora do padrão: {raw.get('processDefinitionId')!r}")
        return cls(key=str(raw["jobKey"]), type=raw["type"], kind=raw.get("kind") or "BPMN_ELEMENT",
                   listener=raw.get("listenerEventType") or "UNSPECIFIED", tenant=parsed[0], processo=parsed[1],
                   process_id=raw["processDefinitionId"], version=int(raw.get("processDefinitionVersion") or 0),
                   instance=str(raw["processInstanceKey"]), element=raw.get("elementId") or "",
                   element_instance=str(raw.get("elementInstanceKey") or ""), headers=raw.get("customHeaders") or {},
                   variables=raw.get("variables") or {}, user_task=raw.get("userTask"), retries=int(raw.get("retries") or 0))


class Handoff(Exception):
    """O passo não pode seguir sozinho (documento ilegível, dado faltando, módulo fora do plano): vai para a tarefa de
    exceção do staff com o motivo. Sem caminho de exceção no passo, vira incidente no motor."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo[:500]


class StepEvent(BaseModel):
    """events.processos.passo: o que um worker fez num passo da execução (o acompanhamento no svc-processos)."""

    instancia: str
    processo: str
    motor_versao: int
    passo: str
    tipo: str = Field(..., description="Tipo do job (<serviço>.<ação> ou agentes.executar)")
    status: Literal["concluido", "handoff", "incidente", "tentando"]
    motivo: str | None = None
    saida: dict[str, Any] = Field(default_factory=dict)
    em: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Quando o worker terminou o passo")


class Outcome(BaseModel):
    """Como o job termina: concluído (com variáveis), handoff (erro BPMN) ou falha (o motor tenta de novo ou abre
    incidente quando acabam as tentativas)."""

    status: Literal["concluido", "handoff", "falhou"]
    variables: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    retries: int = 0


JobHandler = Callable[[Job], Awaitable[dict[str, Any] | None]]
_jobs_counter = metrics.get_meter("core.processes").create_counter(
    "cv.processos.jobs", unit="{job}", description="Jobs do motor de processos tratados, por tipo e resultado")


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

    @asynccontextmanager
    async def worker(
        self, service: str, actions: Sequence[Action] = (), implementation: object | None = None, *,
        jobs: Mapping[str, JobHandler] | None = None, concurrency: int = 4, lock_seconds: int = 300,
    ) -> AsyncIterator[None]:
        """No lifespan: pega no motor os jobs das ações deste pacote (cada uma roda implementation.<nome>, conferida
        aqui: um parâmetro do tipo da entrada, retorno do tipo da saída) e os jobs de jobs= (tipo → função(Job)).
        Um laço de espera longa por tipo; até concurrency jobs ao mesmo tempo."""
        prefix = service.removeprefix("svc-")
        handlers: dict[str, JobHandler] = {}
        for action in actions:
            handlers[f"{prefix}.{action.name}"] = self._action_handler(prefix, action, implementation)
        handlers.update(jobs or {})
        if not handlers:
            yield None
            return
        gate = asyncio.Semaphore(concurrency)
        loops = [asyncio.create_task(self._poll(service, kind, handler, gate, lock_seconds), name=f"jobs:{kind}")
                 for kind, handler in handlers.items()]
        try:
            yield None
        finally:
            for loop in loops:
                loop.cancel()
            await asyncio.gather(*loops, return_exceptions=True)

    def _action_handler(self, prefix: str, action: Action, implementation: object | None) -> JobHandler:
        method = getattr(implementation, action.name, None)
        if method is None or not inspect.iscoroutinefunction(method):
            raise RuntimeError(f"processes.worker: a ação {action.name!r} precisa de um método async {action.name}() no service.py")
        hints = get_type_hints(method)
        params = [p for p in inspect.signature(method).parameters.values()]
        if len(params) != 1 or hints.get(params[0].name) is not action.input or hints.get("return") is not action.output:
            raise RuntimeError(f"processes.worker: {action.name}(self, data: {action.input.__name__}) -> {action.output.__name__}")

        async def handle(job: Job) -> dict[str, Any]:
            if not await plans.enabled(prefix):
                raise Handoff(f"O módulo {prefix} não está no plano da organização.")
            try:
                data = action.input.model_validate(job.variables.get("entrada") or {})
            except ValidationError as exc:
                faltam = ", ".join(str(e["loc"][0]) for e in exc.errors() if e.get("loc"))
                raise Handoff(f"Faltam dados para {action.title.lower()}: {faltam or 'entrada inválida'}.") from None
            result = await method(data)
            return {"resultado": result.model_dump(mode="json")}

        return handle

    async def run_job(self, service: str, handler: JobHandler, job: Job) -> Outcome:
        """Roda um job como a organização do processo e diz como ele termina (o kit de testes usa direto)."""
        with acting_as(system(service, job.tenant)):
            try:
                variables = await handler(job)
                return Outcome(status="concluido", variables=variables or {})
            except Handoff as exc:
                return Outcome(status="handoff", message=exc.motivo)
            except ServiceError as exc:
                if exc.status < 500:  # erro de negócio: tentar de novo não muda nada
                    return Outcome(status="handoff", message=exc.message)
                return Outcome(status="falhou", message=exc.message, retries=max(0, job.retries - 1))
            except Exception as exc:  # noqa: BLE001 - infraestrutura: o motor tenta de novo
                log.exception("job %s (%s) falhou", job.type, job.element)
                return Outcome(status="falhou", message=f"Falha interna ({type(exc).__name__}).", retries=max(0, job.retries - 1))

    async def report(self, job: Job, outcome: Outcome) -> None:
        """Publica o que aconteceu num passo (só jobs de passo; os ouvintes são do próprio svc-processos)."""
        if job.kind != "BPMN_ELEMENT":
            return
        status = {"concluido": "concluido", "falhou": "tentando" if outcome.retries else "incidente"}.get(outcome.status)
        if outcome.status == "handoff":
            status = "handoff" if job.headers.get("excecao") else "incidente"
        saida = outcome.variables.get("resultado") if isinstance(outcome.variables.get("resultado"), dict) else {}
        with acting_as(system(bus.service or "svc-processos", job.tenant)):
            await bus.publish(STEP_SUBJECT, StepEvent(
                instancia=job.instance, processo=job.processo, motor_versao=job.version, passo=job.element, tipo=job.type,
                status=status or "incidente", motivo=outcome.message, saida=saida or {},
            ), msg_id=f"passo-{job.key}-{outcome.status}-{outcome.retries}")

    async def _poll(self, service: str, kind: str, handler: JobHandler, gate: asyncio.Semaphore, lock_seconds: int) -> None:
        wait, running = 1.0, set()
        while True:
            try:
                await gate.acquire()
                gate.release()
                raws = await camunda.activate(kind, worker=service, max_jobs=4, lock_seconds=lock_seconds)
                wait = 1.0
            except ServiceError as exc:  # motor fora do ar: espera crescente
                log.warning("motor sem resposta para %s (%s): nova tentativa em %.0fs", kind, exc.code, wait)
                await asyncio.sleep(wait)
                wait = min(wait * 2, 30.0)
                continue
            if not raws:  # a espera longa voltou vazia (ou o motor respondeu na hora): não gira em falso
                await asyncio.sleep(0.2)
            for raw in raws:
                await gate.acquire()
                task = asyncio.create_task(self._handle(service, handler, raw))
                running.add(task)
                task.add_done_callback(lambda t: (running.discard(t), gate.release()))

    async def _handle(self, service: str, handler: JobHandler, raw: Mapping[str, Any]) -> None:
        try:
            job = Job.from_engine(raw)
        except ValueError as exc:  # não é um processo nosso: incidente, sem tentar de novo
            await camunda.fail_job(str(raw.get("jobKey")), retries=0, message=str(exc))
            return
        outcome = await self.run_job(service, handler, job)
        try:
            await self._settle(job, outcome)
            _jobs_counter.add(1, {"type": job.type, "status": outcome.status})
            await self.report(job, outcome)
        except Exception:  # noqa: BLE001 - o motor devolve o job ao vencer o prazo (lock_seconds)
            log.exception("não consegui devolver o job %s ao motor", job.key)

    async def _settle(self, job: Job, outcome: Outcome) -> None:
        if outcome.status == "concluido":
            await camunda.complete_job(job.key, outcome.variables)
        elif outcome.status == "handoff" and job.kind == "BPMN_ELEMENT" and job.headers.get("excecao"):
            await camunda.throw_error(job.key, HANDOFF_ERROR, outcome.message or "Exceção")
        elif outcome.status == "handoff":  # sem caminho de exceção: incidente para o staff ver no motor
            await camunda.fail_job(job.key, retries=0, message=outcome.message or "Exceção")
        else:
            await camunda.fail_job(job.key, retries=outcome.retries, message=outcome.message or "Falha", backoff_ms=15_000)


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
    if step is not None and step.tipo == "espera" and step.espera == "mensagem":
        return "task"  # receiveTask: atividade, aceita o prazo na borda
    if step is None or step.tipo in ("espera", "fim"):
        return "event"
    return "gateway" if step.tipo == "decisao" else "task"


def _handoff_kind(step: Step) -> str | None:
    """De onde sai a tarefa de exceção do staff: erro (ação ou agente com excecao) ou prazo (espera de mensagem)."""
    if step.excecao and step.tipo in ("acao", "agente"):
        return "erro"
    if step.tipo == "espera" and step.espera == "mensagem" and step.horas:
        return "prazo"
    return None


def _ranks(fluxo: Fluxo) -> tuple[dict[str, int], list[str]]:
    """Camada de cada nó pelo caminho mais longo a partir do início (laços não empurram camada)."""
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
    return rank, order


def step_outputs(step: Step, actions: Mapping[str, "CatalogAction"]) -> list[str]:
    """Os campos que o passo grava sob o id dele (o que condições e entradas dos seguintes podem usar)."""
    if step.tipo == "agente":
        return list(step.saidas)
    if step.tipo == "acao" and step.acao in actions:
        return list(actions[step.acao].output_fields)
    if step.tipo == "tarefa":
        return ["aprovado", "comentario"]
    return []


def input_sources(fluxo: Fluxo, step: Step, actions: Mapping[str, "CatalogAction"]) -> dict[str, str]:
    """De onde vem cada campo da entrada de uma ação: do passo mais perto antes dela que tem um campo com esse nome;
    sem nenhum, do gatilho (gatilho.<campo>)."""
    action = actions.get(step.acao or "")
    if action is None:
        return {}
    rank, _ = _ranks(fluxo)
    before: set[str] = set()
    pending = [f.de for f in fluxo.ligacoes if f.para == step.id]
    while pending:
        node = pending.pop()
        if node in before or node == START or fluxo.step(node) is None:
            continue
        before.add(node)
        pending += [f.de for f in fluxo.ligacoes if f.para == node]
    ordered = sorted((fluxo.step(n) for n in before), key=lambda st: -rank.get(st.id, 0))
    sources: dict[str, str] = {}
    for field in action.input_schema.get("properties", {}):
        origin = next((st.id for st in ordered if field in step_outputs(st, actions)), None)
        sources[field] = f"{origin}.{field}" if origin else f"gatilho.{field}"
    return sources


def _layout(fluxo: Fluxo) -> dict[str, tuple[float, float, int, int]]:
    """Posição (x, y, largura, altura) de cada nó: camadas da esquerda para a direita pelo caminho mais longo,
    ramos empilhados; as tarefas de exceção ficam logo abaixo do passo."""
    rank, order = _ranks(fluxo)
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
        if _handoff_kind(step) and step.id in pos:
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


def to_bpmn(fluxo: Fluxo, *, process_id: str, name: str, actions: Mapping[str, CatalogAction] | None = None) -> str:
    """O fluxo tipado como BPMN 2.0 com as extensões do Camunda 8 (zeebe:) e o desenho (DI) para a tela.

    process_id é p_<organização>_<processo> (process_id()): a organização prefixa as mensagens. Com actions (o
    catálogo), cada ação recebe a entrada dos passos anteriores pelo nome do campo (input_sources)."""
    parsed = parse_process_id(process_id)
    if parsed is None:
        raise ValueError(f"to_bpmn: id de processo inválido {process_id!r} (use process_id(organização, processo))")
    tenant = parsed[0]
    catalog = actions or {}
    a = lambda v: escape(str(v), {'"': "&quot;"})  # noqa: E731 - atributo XML
    pos = _layout(fluxo)
    messages: dict[str, str] = {}
    elements: list[str] = []
    flows: list[tuple[str, str, str, Condition | None]] = []
    uses_error = False

    def listener(kind: str, event: str = "start") -> str:
        return f'<zeebe:executionListeners><zeebe:executionListener eventType="{event}" type="{kind}" /></zeebe:executionListeners>'

    def message_ref(message: str, key: str | None) -> str:
        ref = "m_" + re.sub(r"[^a-z0-9]", "_", message)
        sub = f'<bpmn:extensionElements><zeebe:subscription correlationKey="={a(key)}" /></bpmn:extensionElements>' if key else ""
        messages.setdefault(ref, f'<bpmn:message id="{ref}" name="{a(f"{tenant}.{message}")}">{sub}</bpmn:message>')
        return ref

    def user_task(task_id: str, label: str, group: str, hours: float | None, question: str | None) -> str:
        due = f'<zeebe:taskSchedule dueDate="=now() + duration(&quot;PT{int(hours)}H&quot;)" />' if hours else ""
        props = f'<zeebe:properties><zeebe:property name="pergunta" value="{a(question)}" /></zeebe:properties>' if question else ""
        return (f'<bpmn:userTask id="{task_id}" name="{label}"><bpmn:extensionElements><zeebe:userTask />'
                f'<zeebe:assignmentDefinition candidateGroups="{a(group)}" />{due}{props}'
                f'<zeebe:taskListeners><zeebe:taskListener eventType="creating" type="{JOB_TASK}" /></zeebe:taskListeners>'
                "</bpmn:extensionElements></bpmn:userTask>")

    trigger = fluxo.gatilho
    # Evento e manual: o svc-processos inicia pela API (sabe quais processos da organização o evento inicia).
    definition = ""
    if trigger.tipo == "agenda" and trigger.agenda:
        definition = f'<bpmn:timerEventDefinition><bpmn:timeCycle xsi:type="bpmn:tFormalExpression">{escape(trigger.agenda)}</bpmn:timeCycle></bpmn:timerEventDefinition>'
    # Os parâmetros vão no BPMN (saída do início): cada versão publicada carrega os seus valores.
    params = "".join(f'<zeebe:output source="{a("=" + _feel_value(v))}" target="parametros.{k}" />' for k, v in fluxo.parametros.items())
    params = f"<bpmn:extensionElements><zeebe:ioMapping>{params}</zeebe:ioMapping></bpmn:extensionElements>" if params else ""
    elements.append(f'<bpmn:startEvent id="{START}" name="{a(trigger.descricao or "Início")}">{params}{definition}</bpmn:startEvent>')

    for step in fluxo.passos:
        sid, label = step.id, a(step.nome)
        handoff = _handoff_kind(step)
        if step.tipo in ("acao", "agente"):
            job = step.acao if step.tipo == "acao" else JOB_AGENT
            headers = [("passo", sid)]
            if step.tipo == "agente":
                headers += [("objetivo", step.objetivo or ""), ("saidas", ",".join(step.saidas))]
            if handoff:
                headers.append(("excecao", "sim"))
            header_xml = "".join(f'<zeebe:header key="{k}" value="{a(v)}" />' for k, v in headers)
            inputs = "".join(f'<zeebe:input source="={a(src)}" target="entrada.{field}" />'
                             for field, src in input_sources(fluxo, step, catalog).items()) if step.tipo == "acao" else ""
            elements.append(f'<bpmn:serviceTask id="{sid}" name="{label}"><bpmn:extensionElements>'
                            f'<zeebe:taskDefinition type="{a(job or "")}" retries="3" />'
                            f'<zeebe:ioMapping>{inputs}<zeebe:output source="=resultado" target="{sid}" /></zeebe:ioMapping>'
                            f"<zeebe:taskHeaders>{header_xml}</zeebe:taskHeaders></bpmn:extensionElements></bpmn:serviceTask>")
        elif step.tipo == "tarefa":
            elements.append(user_task(sid, label, step.responsavel or "cliente", step.horas, step.pergunta or step.nome))
        elif step.tipo == "decisao":
            default = next((f for f in fluxo.outgoing(sid) if f.condicao is None), None)
            attr = f' default="f_{sid}_{default.para}"' if default else ""
            elements.append(f'<bpmn:exclusiveGateway id="{sid}" name="{label}"{attr} />')
        elif step.tipo == "espera" and step.espera == "mensagem" and step.mensagem:
            elements.append(f'<bpmn:receiveTask id="{sid}" name="{label}" messageRef="{message_ref(step.mensagem, step.chave)}">'
                            f'<bpmn:extensionElements><zeebe:ioMapping><zeebe:output source="=mensagem" target="{sid}" />'
                            f"</zeebe:ioMapping>{listener(JOB_WAIT)}</bpmn:extensionElements></bpmn:receiveTask>")
        elif step.tipo == "espera":
            elements.append(f'<bpmn:intermediateCatchEvent id="{sid}" name="{label}"><bpmn:extensionElements>{listener(JOB_WAIT)}'
                            '</bpmn:extensionElements><bpmn:timerEventDefinition><bpmn:timeDuration xsi:type="bpmn:tFormalExpression">'
                            f"PT{int(step.horas or 1)}H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>")
        else:
            elements.append(f'<bpmn:endEvent id="{sid}" name="{label}"><bpmn:extensionElements>{listener(JOB_END)}'
                            "</bpmn:extensionElements></bpmn:endEvent>")
        for flow in fluxo.outgoing(sid):
            if fluxo.step(flow.para) is not None:  # ligação para passo que não existe (rascunho): fica de fora
                flows.append((f"f_{sid}_{flow.para}", sid, flow.para, flow.condicao if step.tipo == "decisao" else None))
        if handoff:
            nxt = next((f.para for f in fluxo.outgoing(sid) if fluxo.step(f.para) is not None), None)
            if handoff == "erro":
                uses_error = True
                trigger_xml = f'<bpmn:errorEventDefinition errorRef="e_{HANDOFF_ERROR}" />'
                task_name = f"Exceção: {label}"
            else:
                trigger_xml = ('<bpmn:timerEventDefinition><bpmn:timeDuration xsi:type="bpmn:tFormalExpression">'
                               f"PT{int(step.horas or 1)}H</bpmn:timeDuration></bpmn:timerEventDefinition>")
                task_name = f"Prazo: {label}"
            elements.append(f'<bpmn:boundaryEvent id="{sid}__{handoff}" attachedToRef="{sid}">{trigger_xml}</bpmn:boundaryEvent>')
            elements.append(user_task(f"{sid}__excecao", task_name, "staff", HANDOFF_HOURS, None))
            flows.append((f"f_{sid}__{handoff}", f"{sid}__{handoff}", f"{sid}__excecao", None))
            if nxt:
                flows.append((f"f_{sid}__excecao_{nxt}", f"{sid}__excecao", nxt, None))
    for flow in fluxo.outgoing(START):
        if fluxo.step(flow.para) is not None:
            flows.append((f"f_{START}_{flow.para}", START, flow.para, None))

    for fid, src, dst, cond in flows:
        body = f'<bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">{escape(feel(cond))}</bpmn:conditionExpression>' if cond else ""
        elements.append(f'<bpmn:sequenceFlow id="{fid}" sourceRef="{src}" targetRef="{dst}">{body}</bpmn:sequenceFlow>')

    shapes, edges = [], []
    boundary = {f"{st.id}__{kind}": st.id for st in fluxo.passos if (kind := _handoff_kind(st))}
    for node, (x, y, w, h) in pos.items():
        shapes.append(f'<bpmndi:BPMNShape id="{node}_di" bpmnElement="{node}"><dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" /></bpmndi:BPMNShape>')
    for event_id, step_id in boundary.items():
        if step_id in pos:
            sx, sy, sw, sh = pos[step_id]
            shapes.append(f'<bpmndi:BPMNShape id="{event_id}_di" bpmnElement="{event_id}"><dc:Bounds x="{sx + sw - 30:.0f}" y="{sy + sh - 18:.0f}" width="36" height="36" /></bpmndi:BPMNShape>')
    for fid, src, dst, _ in flows:
        if src in boundary:  # do evento na borda de baixo do passo até a exceção logo abaixo
            sx, sy, sw, sh = pos[boundary[src]]
            points = [(sx + sw - 12, sy + sh + 18), (sx + sw - 12, pos[dst][1])]
        elif src in pos and dst in pos:
            points = _edge(pos[src], pos[dst])
        else:
            continue
        waypoints = "".join(f'<di:waypoint x="{px:.0f}" y="{py:.0f}" />' for px, py in points)
        edges.append(f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{waypoints}</bpmndi:BPMNEdge>')

    error = f'<bpmn:error id="e_{HANDOFF_ERROR}" name="Exceção" errorCode="{HANDOFF_ERROR}" />' if uses_error else ""
    process_ext = f"<bpmn:extensionElements>{listener(JOB_START)}</bpmn:extensionElements>"
    return (
        f'{_ANCHOR_BASE}<bpmn:process id="{process_id}" name="{a(name)}" isExecutable="true">{process_ext}{"".join(elements)}</bpmn:process>'
        f"{''.join(messages.values())}{error}"
        f'<bpmndi:BPMNDiagram id="diagrama"><bpmndi:BPMNPlane id="plano" bpmnElement="{process_id}">'
        f"{''.join(shapes)}{''.join(edges)}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
    )


# ── O motor: Camunda 8 (API REST do Orchestration Cluster) ───────────────────

class CamundaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAMUNDA_", extra="ignore")

    url: str = "http://localhost:8080"


class Started(BaseModel):
    """Execução iniciada: a chave dela no motor e a versão do processo em que vai rodar até o fim."""

    instance: str
    version: int


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

    async def start(self, process_id: str, variables: Mapping[str, Any]) -> "Started":
        """Inicia uma execução na última versão implantada do processo."""
        response = await self._call("POST", "/v2/process-instances", json={"processDefinitionId": process_id, "variables": dict(variables)})
        body = self._ok(response, "iniciar a execução")
        return Started(instance=str(body["processInstanceKey"]), version=int(body["processDefinitionVersion"]))

    async def message(self, name: str, key: str, variables: Mapping[str, Any], *, ttl_seconds: int = 3600,
                      message_id: str | None = None) -> None:
        """Publica uma mensagem (<organização>.<mensagem>) para a execução que espera com esta chave; chegando antes da
        espera abrir, fica guardada por ttl_seconds. message_id: a mesma mensagem de novo (reentrega) não duplica."""
        body = {"name": name, "correlationKey": key, "variables": dict(variables), "timeToLive": ttl_seconds * 1000}
        if message_id:
            body["messageId"] = message_id[:200]
        response = await self._call("POST", "/v2/messages/publication", json=body)
        self._ok(response, "entregar a mensagem")

    async def activate(self, job_type: str, *, worker: str, max_jobs: int, lock_seconds: int, wait_seconds: int = 20) -> list[dict[str, Any]]:
        """Pega até max_jobs jobs do tipo (espera até wait_seconds por um); ficam com este worker por lock_seconds."""
        response = await self._call("POST", "/v2/jobs/activation", json={
            "type": job_type, "worker": worker[:60], "timeout": lock_seconds * 1000, "maxJobsToActivate": max_jobs,
            "requestTimeout": wait_seconds * 1000}, timeout=wait_seconds + 15)
        return list(self._ok(response, "pegar jobs").get("jobs", []))

    async def complete_job(self, key: str, variables: Mapping[str, Any]) -> None:
        self._ok(await self._call("POST", f"/v2/jobs/{key}/completion", json={"variables": dict(variables)}), "concluir o job")

    async def throw_error(self, key: str, code: str, message: str) -> None:
        response = await self._call("POST", f"/v2/jobs/{key}/error", json={"errorCode": code, "errorMessage": message[:500]})
        self._ok(response, "levar o passo à exceção")

    async def fail_job(self, key: str, *, retries: int, message: str, backoff_ms: int = 0) -> None:
        response = await self._call("POST", f"/v2/jobs/{key}/failure", json={
            "retries": retries, "errorMessage": message[:500], "retryBackOff": backoff_ms})
        self._ok(response, "devolver o job")

    async def complete_task(self, key: str, variables: Mapping[str, Any]) -> None:
        """Conclui uma tarefa de pessoa; já concluída ou inexistente → 409 ERRO_PROCESSOS_TAREFA_FECHADA."""
        response = await self._call("POST", f"/v2/user-tasks/{key}/completion", json={"variables": dict(variables)})
        if response.status_code in (404, 409):
            raise ServiceError("ERRO_PROCESSOS_TAREFA_FECHADA", "Esta tarefa já foi resolvida.", status=409)
        self._ok(response, "concluir a tarefa")

    async def path(self, instance: str) -> list[dict[str, Any]]:
        """Os elementos por onde a execução passou ou está (id, tipo, estado), na ordem."""
        response = await self._call("POST", "/v2/element-instances/search", json={
            "filter": {"processInstanceKey": instance}, "page": {"limit": 200}, "sort": [{"field": "startDate"}]})
        return [{"id": e["elementId"], "tipo": e["type"], "estado": e["state"], "incidente": e.get("hasIncident", False)}
                for e in self._ok(response, "ler o caminho").get("items", [])]

    async def cancel(self, instance: str) -> None:
        response = await self._call("POST", f"/v2/process-instances/{instance}/cancellation", json={})
        if response.status_code != 404:
            self._ok(response, "cancelar a execução")

    def _ok(self, response: httpx.Response, what: str) -> dict[str, Any]:
        if response.status_code >= 500:
            raise ServiceError("ERRO_PROCESSOS_MOTOR", f"O motor de processos falhou ao {what}.", status=503)
        if response.status_code >= 400:
            raise ServiceError("ERRO_PROCESSOS_MOTOR_RECUSOU", f"O motor recusou {what}: {_problem(response)}", status=422)
        return response.json() if response.content else {}

    async def _call(self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=CamundaSettings().url, timeout=httpx.Timeout(30.0, connect=5.0),
                                             limits=httpx.Limits(max_connections=50))
        if timeout is not None:
            kwargs["timeout"] = httpx.Timeout(timeout, connect=5.0)
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
