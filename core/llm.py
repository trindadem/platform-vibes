"""IA: o único jeito de um serviço chamar modelos (README §5.11). Qualquer API compatível com OpenAI.

    texto   = await llm.ask("openrouter/claude", "Resuma: ...", instructions="Seja breve.")
    fatura  = await llm.ask("local/llama", texto, output=Fatura)             # saída estruturada (modelo Pydantic)
    legenda = await llm.ask("openai/gpt", "O que há na foto?", images=[Image(url="https://...")])
    texto   = await llm.ask("openai/gpt", pergunta, tools=[buscar_cliente])  # ferramentas: funções async com docstring
    async for pedaco in llm.stream("openrouter/claude", pergunta): ...       # texto em pedaços → stream_response
    vetores = await llm.embed("openai/text-embedding-3-small", ["a", "b"])
    agente  = await llm.agent("openrouter/claude", tools=[...])              # Agent do Agno para casos avançados
    feito   = await llm.run_agent("cv/agente", tarefa, instructions=INSTRUCAO, tools=[registrar, buscar],
                                  context=historico, on_step=passos.put_nowait)  # agente com ferramentas (AgentExo)
    remota  = SchemaTool("mcp_erp_consultar_pedido", "Consulta pedidos no ERP", schema, chamar)  # ferramenta por schema

Trilhos:
- O modelo é "<provedor>/<modelo>" como cadastrado no svc-ai (apelido ou id). O svc-ai resolve, na organização de
  quem age, endereço, chave e preço (rpc.ai.resolve): o serviço nunca vê nem guarda chave. A organização tem
  prioridade sobre a plataforma. Resolução guardada 60 s por processo.
- Todo agente sai com telemetria do Agno DESLIGADA (por padrão ele envia dados para os servidores dele) e sem
  banco, memória ou conhecimento do Agno (não respeitam a organização): histórico e documentos ficam em tabelas do
  serviço, pelo core.surreal.
- Toda execução registra o uso (tokens, modelo, serviço, preço) em events.ai.usage; o svc-ai grava por organização.
- Provedor que recusa vira ServiceError sem ecoar a mensagem dele (às vezes traz pedaços da chave):
  401/403 → ERRO_AI_PROVIDER_AUTH, 429 → ERRO_AI_RATE_LIMITED, resto → ERRO_AI_PROVIDER.
- Endereço de provedor da organização é conferido contra SSRF antes de cada uso; HTTP sem redirect e sem cookie.
- Plano (README §5.17): antes de cada chamada, o core confere os limites do mês da organização (ai.custo e ai.tokens,
  somados pelo svc-ai). Quem já chegou ao limite recebe 402 ERRO_PLAN_LIMIT, sem chamar o provedor.

Agentes (run_agent) rodam no laço do AgentExo (exovision-agent, o SDK agêntico da casa), síncrono, numa thread. O que
toca a plataforma continua no core: o modelo vem do svc-ai, cada volta passa pelo mesmo cliente HTTP (sem redirect,
sem cookie, endereço conferido), o plano é conferido a cada volta e o uso de cada volta vai para events.ai.usage.
As ferramentas são funções async do serviço (docstring = descrição; parâmetros tipados = schema, validado pelo
Pydantic antes da chamada) e rodam no loop do serviço, em nome de quem age. Ferramenta só conhecida em tempo de
execução (a de um servidor MCP) entra como SchemaTool: nome, descrição e JSON schema como vieram, e a função recebe os
argumentos num dict (quem a escreve valida, ou deixa o destino validar). Erro de validação ou ServiceError volta
ao modelo como resultado de erro, para ele corrigir; outra exceção vira "falha interna", sem detalhe. O contexto
(histórico, estado) entra pela porta de memória do AgentExo; o histórico e os documentos ficam nas tabelas do serviço.
"""
import asyncio
import inspect
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Literal

os.environ.setdefault("AGNO_TELEMETRY", "false")  # antes de importar o Agno: nada sai para os servidores dele

import httpx
from agno.agent import Agent
from agno.media import Image
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunContentEvent, RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from exovision.harness import Agent as LoopAgent
from exovision.harness import Budget, Recall, Registry, Tool, ToolResult
from exovision.harness import run as run_loop
from exovision.harness.models.drivers import OpenAICompatibleProvider
from exovision.harness.models.provider import ProviderError, Reply, Request
from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel, Field, SecretStr, ValidationError, create_model, field_serializer

from core.envelope import ServiceError
from core.http_client import no_cookie_jar
from core.nats_bus import bus
from core.plans import plans
from core.security import assert_public_url, current_tenant

__all__ = [
    "AgentResult", "AgentStep", "Image", "llm", "Llm", "Resolved", "ResolveRequest", "SchemaTool", "UsageEvent",
    "RESOLVE_SUBJECT", "USAGE_SUBJECT",
]

RESOLVE_SUBJECT = "rpc.ai.resolve"
USAGE_SUBJECT = "events.ai.usage"
PLAN_LIMITS = ("ai.custo", "ai.tokens")  # declarados pelo svc-ai; conferidos antes de cada chamada (README §5.17)
CACHE_SECONDS = 60
AGENT_MAX_TOKENS = 4096  # teto de saída de cada volta do agente
AGENT_WALL_SECONDS = 240.0  # um run_agent inteiro, de todas as voltas
TOOL_SECONDS = 120.0  # uma ferramenta
_MODEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}/\S{1,200}$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

log = logging.getLogger("core.llm")


class ResolveRequest(BaseModel):
    model: str
    kind: Literal["chat", "embedding"]


class Resolved(BaseModel):
    """Resposta do svc-ai: como chamar o modelo pedido, na organização de quem pede."""

    provider: str
    scope: Literal["organization", "platform"]
    model: str = Field(..., description="Id real do modelo no provedor")
    base_url: str
    api_key: SecretStr  # mascarada em repr e log
    price_input: float = 0.0  # por milhão de tokens
    price_output: float = 0.0

    @field_serializer("api_key", when_used="json")
    def _reveal_key(self, key: SecretStr) -> str:
        """Só no JSON da resposta do rpc.ai.resolve (NATS interno); sem isto o SecretStr viajaria como '**********'."""
        return key.get_secret_value()


class UsageEvent(BaseModel):
    model: str
    provider: str
    kind: Literal["chat", "embedding"]
    service: str
    input_tokens: int = 0
    output_tokens: int = 0
    price_input: float = 0.0
    price_output: float = 0.0


@dataclass(frozen=True)
class SchemaTool:
    """Ferramenta descrita por JSON schema, para o que só se conhece em tempo de execução (ex.: a de um servidor MCP).

    call recebe os argumentos como o modelo mandou (um dict) e roda no loop do serviço, como as funções tipadas.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    call: Callable[[dict[str, Any]], Awaitable[Any]]


class AgentStep(BaseModel):
    """Um passo do agente enquanto ele trabalha (para mostrar na tela): a ferramenta e em que pé ela está."""

    tool: str
    status: Literal["running", "done", "failed"]


class AgentResult(BaseModel):
    """O fim de um run_agent: a resposta final e o que custou."""

    text: str
    stop_reason: str = Field(..., description="end_turn, stop, budget:<limite> ou refusal")
    turns: int
    tool_calls: int
    input_tokens: int = 0
    output_tokens: int = 0


class Llm:
    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries  # novas tentativas em 429/5xx, com espera crescente (do SDK openai)
        self._cache: dict[tuple[str, str, str], tuple[float, Resolved]] = {}
        self._transport: httpx.AsyncBaseTransport | None = None

    async def ask(
        self,
        model: str,
        prompt: str,
        *,
        instructions: str | None = None,
        output: type[BaseModel] | None = None,
        tools: Sequence[Callable[..., Any]] = (),
        images: Sequence[Image] = (),
    ) -> Any:
        """Uma resposta inteira: texto, ou o modelo Pydantic pedido em output."""
        statuses: list[int] = []
        agent = await self._agent(model, statuses, instructions=instructions, tools=tools, output=output)
        result = await agent.arun(prompt, images=list(images) or None)
        if result.status == RunStatus.error:
            raise _provider_error(statuses)
        return result.content

    async def stream(
        self,
        model: str,
        prompt: str,
        *,
        instructions: str | None = None,
        tools: Sequence[Callable[..., Any]] = (),
        images: Sequence[Image] = (),
    ) -> AsyncIterator[str]:
        """Texto em pedaços, conforme o modelo gera. Use dentro de um gerador de stream_response (README §5.10)."""
        statuses: list[int] = []
        agent = await self._agent(model, statuses, instructions=instructions, tools=tools)
        async for event in agent.arun(prompt, stream=True, images=list(images) or None):
            if isinstance(event, RunErrorEvent):
                raise _provider_error(statuses)
            if isinstance(event, RunContentEvent) and isinstance(event.content, str) and event.content:
                yield event.content

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        """Vetores para busca semântica (um por texto, na mesma ordem)."""
        resolved = await self._resolve(model, "embedding")
        client = AsyncOpenAI(
            api_key=resolved.api_key.get_secret_value() or "sem-chave",
            base_url=resolved.base_url,
            http_client=self._client([]),
            max_retries=self.max_retries,
        )
        try:
            reply = await client.embeddings.create(model=resolved.model, input=list(texts))
        except APIStatusError as exc:
            raise _provider_error([exc.status_code]) from None
        except httpx.TransportError:
            raise _provider_error([]) from None
        usage = reply.usage.prompt_tokens if reply.usage else 0
        await self._report(model, resolved, "embedding", usage, 0)
        return [item.embedding for item in sorted(reply.data, key=lambda item: item.index)]

    async def agent(
        self,
        model: str,
        *,
        instructions: str | None = None,
        tools: Sequence[Callable[..., Any]] = (),
        output: type[BaseModel] | None = None,
    ) -> Agent:
        """Agent do Agno já resolvido, sem telemetria nem memória do Agno e com o uso registrado a cada execução."""
        return await self._agent(model, [], instructions=instructions, tools=tools, output=output)

    async def run_agent(
        self,
        model: str,
        task: str,
        *,
        instructions: str,
        tools: Sequence[Callable[..., Awaitable[Any]] | SchemaTool] = (),
        context: str = "",
        max_turns: int = 8,
        on_step: Callable[[AgentStep], None] | None = None,
    ) -> AgentResult:
        """Agente com ferramentas até terminar a tarefa (ou o orçamento de voltas acabar), no laço do AgentExo.

        tools: funções async do serviço com docstring e parâmetros tipados (ou um único parâmetro que é modelo Pydantic:
        os campos dele viram os argumentos), ou SchemaTool. context: o que o agente precisa saber antes (histórico da conversa, estado
        atual). on_step: chamado no loop do serviço a cada ferramenta que começa e termina.
        """
        resolved = await self._resolve(model, "chat")
        loop = asyncio.get_running_loop()
        registry = Registry([_schema_tool(t, loop) if isinstance(t, SchemaTool) else _loop_tool(t, loop) for t in tools])
        provider = _MeteredProvider(self, model, resolved, loop)

        def step(event: Any) -> None:
            if on_step is None or event.seam not in ("tool.call", "tool.result"):
                return
            status = "running" if event.seam == "tool.call" else ("done" if event.data.get("ok") else "failed")
            loop.call_soon_threadsafe(on_step, AgentStep(tool=str(event.data.get("tool", "")), status=status))

        agent = LoopAgent(
            provider=provider,
            instruction=instructions,
            name=bus.service or "agente",
            toolset=registry,
            memory=_Context(context),
            budget=Budget(max_turns=max_turns, max_wall_s=AGENT_WALL_SECONDS),
        )
        outcome = await asyncio.to_thread(run_loop, agent, task, on_event=step)
        if outcome.stop_reason == "error":
            raise provider.failure or _provider_error([])
        return AgentResult(
            text=outcome.text,
            stop_reason=outcome.stop_reason,
            turns=outcome.turns,
            tool_calls=outcome.tool_calls,
            input_tokens=int(outcome.usage.get("input_tokens", 0)) + int(outcome.usage.get("cache_read_input_tokens", 0)),
            output_tokens=int(outcome.usage.get("output_tokens", 0)),
        )

    async def _post(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        """Uma volta do agente pelo mesmo cliente HTTP do core, com as novas tentativas do SDK openai (429/5xx/queda)."""
        statuses: list[int] = []
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(min(8.0, 0.5 * 2**attempt))
            try:  # sem fechar o client: o transport (conexões) é compartilhado pelo processo
                response = await self._client(statuses).post(url, json=body, headers=headers, timeout=min(timeout, 120.0))
            except httpx.TransportError:
                if attempt < self.max_retries:
                    continue
                raise _provider_error([]) from None
            if response.status_code in (408, 409, 429) or response.status_code >= 500:
                if attempt < self.max_retries:
                    continue
            if response.status_code >= 400:
                raise _provider_error(statuses)
            return response.json()
        raise _provider_error(statuses)

    async def _agent(
        self,
        model: str,
        statuses: list[int],
        *,
        instructions: str | None = None,
        tools: Sequence[Callable[..., Any]] = (),
        output: type[BaseModel] | None = None,
    ) -> Agent:
        resolved = await self._resolve(model, "chat")

        async def report_usage(run_output: RunOutput) -> None:
            metrics = run_output.metrics
            if metrics is not None:
                await self._report(model, resolved, "chat", metrics.input_tokens or 0, metrics.output_tokens or 0)

        provider = OpenAILike(
            id=resolved.model,
            api_key=resolved.api_key.get_secret_value() or "sem-chave",  # provedores locais aceitam qualquer chave
            base_url=resolved.base_url,
            http_client=self._client(statuses),
            max_retries=self.max_retries,
        )
        return Agent(
            model=provider,
            instructions=instructions,
            tools=list(tools) or None,
            output_schema=output,
            post_hooks=[report_usage],
            telemetry=False,
            db=None,
            markdown=False,
        )

    async def _resolve(self, model: str, kind: Literal["chat", "embedding"]) -> Resolved:
        if not _MODEL.match(model):
            raise ValueError(f"modelo fora do trilho: {model!r} (use <provedor>/<modelo>, como cadastrado no svc-ai)")
        for limit in PLAN_LIMITS:  # quem já gastou o mês do plano não chama o provedor
            await plans.check(limit)
        key = (current_tenant(), model, kind)
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            resolved = cached[1]
        else:
            resolved = await bus.request(RESOLVE_SUBJECT, ResolveRequest(model=model, kind=kind), Resolved, timeout=5)
            self._cache[key] = (time.monotonic() + CACHE_SECONDS, resolved)
        if resolved.scope == "organization":
            await assert_public_url(resolved.base_url)  # o DNS pode ter mudado desde o cadastro
        return resolved

    async def _report(self, model: str, resolved: Resolved, kind: str, input_tokens: int, output_tokens: int) -> None:
        event = UsageEvent(
            model=model,
            provider=resolved.provider,
            kind=kind,
            service=bus.service or "unknown",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            price_input=resolved.price_input,
            price_output=resolved.price_output,
        )
        try:
            await bus.publish(USAGE_SUBJECT, event)
        except Exception:
            log.exception("uso de IA não registrado (%s, %s tokens)", model, input_tokens + output_tokens)

    def _client(self, statuses: list[int]) -> httpx.AsyncClient:
        """Um client por chamada, que anota em statuses os erros HTTP dela (o Agno engole a exceção com o status).
        As conexões ficam no transport, compartilhado por todas as chamadas do processo."""
        if self._transport is None:
            self._transport = httpx.AsyncHTTPTransport()

        async def remember(response: httpx.Response) -> None:
            if response.status_code >= 400:
                statuses.append(response.status_code)

        return httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(120.0, connect=10.0),
            follow_redirects=False,
            cookies=no_cookie_jar(),
            event_hooks={"response": [remember]},
        )

    def clear(self) -> None:
        """Esquece as resoluções guardadas (ex.: testes ou depois de trocar uma chave)."""
        self._cache.clear()


def _provider_error(statuses: list[int]) -> ServiceError:
    status = statuses[-1] if statuses else 0
    if status in (401, 403):
        return ServiceError("ERRO_AI_PROVIDER_AUTH", "A chave do provedor de IA foi recusada. Confira em IA → Provedores.", 502)
    if status == 429:
        return ServiceError("ERRO_AI_RATE_LIMITED", "O provedor de IA limitou o uso. Tente de novo em instantes.", 429)
    return ServiceError("ERRO_AI_PROVIDER", "O provedor de IA não respondeu como esperado.", 502)


class _MeteredProvider:
    """O driver compatível do AgentExo com o que a plataforma exige a cada volta: plano, cliente HTTP do core e uso."""

    def __init__(self, owner: Llm, name: str, resolved: Resolved, loop: asyncio.AbstractEventLoop) -> None:
        self.model = resolved.model
        self.effort = ""
        self.failure: ServiceError | None = None  # o erro da plataforma que derrubou a volta (sobe no fim do run_agent)
        self._owner, self._name, self._resolved, self._loop = owner, name, resolved, loop
        self._driver = OpenAICompatibleProvider(
            base_url=resolved.base_url,
            api_key=resolved.api_key.get_secret_value() or "sem-chave",
            model=resolved.model,
            max_tokens=AGENT_MAX_TOKENS,
            retries=0,  # as novas tentativas são do core (_post), que conhece o status
            transport=self._transport,
        )

    def complete(self, request: Request) -> Reply:
        try:
            self._sync(self._check())
            reply = self._driver.complete(request)
        except ServiceError as exc:
            self.failure = exc
            raise ProviderError(exc.code) from None
        usage = reply.usage
        tokens_in = int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0))
        self._sync(self._owner._report(self._name, self._resolved, "chat", tokens_in, int(usage.get("output_tokens", 0))))
        return reply

    def _transport(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        try:
            return self._sync(self._owner._post(url, body, headers, timeout))
        except ServiceError as exc:  # o driver embrulharia em ProviderError e o código (auth, 429) se perderia
            self.failure = exc
            raise ProviderError(exc.code) from None

    async def _check(self) -> None:
        for limit in PLAN_LIMITS:
            await plans.check(limit)
        if self._resolved.scope == "organization":
            await assert_public_url(self._resolved.base_url)

    def _sync(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


class _Context:
    """Porta de memória do AgentExo que entrega o contexto que o serviço montou (histórico, estado) antes da tarefa."""

    def __init__(self, text: str) -> None:
        self._text = text.strip()

    def recall(self, text: str, *, session: str = "", actor: str = "") -> Recall:
        return Recall(text=self._text, tokens=len(self._text) // 4)

    def observe(self, kind: str, content: str, *, session: str = "", turn: int = 0, **detail: Any) -> None:
        return None

    def commit(self) -> dict[str, Any]:
        return {}


def _loop_tool(fn: Callable[..., Awaitable[Any]], loop: asyncio.AbstractEventLoop) -> Tool:
    """Função async do serviço → ferramenta do AgentExo: schema dos parâmetros tipados, validação e execução no loop."""
    name = fn.__name__.lstrip("_")
    if not inspect.iscoroutinefunction(fn) or not _TOOL_NAME.match(name):
        raise TypeError(f"ferramenta {fn.__name__!r}: use uma função async com nome em snake_case")
    description = (inspect.getdoc(fn) or "").strip()
    if not description:
        raise TypeError(f"ferramenta {name!r} sem docstring: o modelo escolhe a ferramenta pela descrição")
    params = list(inspect.signature(fn).parameters.values())
    for param in params:
        if param.annotation is inspect.Parameter.empty:
            raise TypeError(f"ferramenta {name!r}: o parâmetro {param.name!r} precisa de tipo (vira o schema)")
    # Um único parâmetro que é modelo Pydantic: os campos do modelo são os argumentos (mais fácil para o modelo de IA).
    whole = len(params) == 1 and inspect.isclass(params[0].annotation) and issubclass(params[0].annotation, BaseModel)
    arguments_model: type[BaseModel] = params[0].annotation if whole else create_model(
        f"{name}_argumentos",
        **{p.name: (p.annotation, ... if p.default is inspect.Parameter.empty else p.default) for p in params},
    )

    def call(**arguments: Any) -> ToolResult:
        try:
            parsed = arguments_model.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'argumentos'}: {e['msg']}" for e in exc.errors())
            return ToolResult.error(f"argumentos inválidos: {problems}", code=422)
        return _run_in_loop(name, fn(parsed) if whole else fn(**{p.name: getattr(parsed, p.name) for p in params}), loop)

    return Tool(name=name, description=description, fn=call, input_schema=_inline(arguments_model.model_json_schema()))


def _schema_tool(spec: SchemaTool, loop: asyncio.AbstractEventLoop) -> Tool:
    """SchemaTool → ferramenta do AgentExo: o schema vai como veio (sem $ref) e a chamada roda no loop do serviço."""
    if not _TOOL_NAME.match(spec.name) or not inspect.iscoroutinefunction(spec.call):
        raise TypeError(f"ferramenta {spec.name!r}: nome em snake_case e call async")
    if not spec.description.strip():
        raise TypeError(f"ferramenta {spec.name!r} sem descrição: o modelo escolhe a ferramenta pela descrição")
    schema: dict[str, Any] = {"type": "object", "properties": {}}
    if spec.input_schema.get("type") == "object":
        try:
            schema = _inline(dict(spec.input_schema))
        except (KeyError, TypeError):  # referência fora de $defs ou recursiva: vai como veio, o destino valida
            schema = dict(spec.input_schema)

    def call(**arguments: Any) -> ToolResult:
        return _run_in_loop(spec.name, spec.call(arguments), loop)

    return Tool(name=spec.name, description=spec.description.strip(), fn=call, input_schema=schema)


def _run_in_loop(name: str, coro: Coroutine[Any, Any, Any], loop: asyncio.AbstractEventLoop) -> ToolResult:
    """Roda a ferramenta no loop do serviço (em nome de quem age); erro de negócio volta ao modelo, o resto não vaza."""
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        value = future.result(timeout=TOOL_SECONDS)
    except ServiceError as exc:
        return ToolResult.error(f"{exc.code}: {exc.message}", code=exc.status)
    except Exception:
        future.cancel()
        log.exception("ferramenta %s falhou", name)
        return ToolResult.error("falha interna na ferramenta; tente outro caminho ou avise a pessoa", code=500)
    return ToolResult(text=_tool_text(value))


def _tool_text(value: Any) -> str:
    if value is None:
        return "ok"
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _inline(schema: dict[str, Any]) -> dict[str, Any]:
    """Schema sem $ref/$defs (servidores compatíveis com a OpenAI nem sempre resolvem referências) e sem títulos."""
    defs = schema.pop("$defs", {})

    def walk(node: Any, depth: int = 0, names: bool = False) -> Any:
        if depth > 20:
            raise TypeError("schema de ferramenta recursivo demais: simplifique os parâmetros")
        if isinstance(node, list):
            return [walk(v, depth + 1) for v in node]
        if not isinstance(node, dict):
            return node
        if names:  # chaves de "properties" são nomes de campo (inclusive um campo chamado "title")
            return {k: walk(v, depth + 1) for k, v in node.items()}
        if "$ref" in node:
            return walk(dict(defs[node["$ref"].split("/")[-1]]), depth + 1)
        return {k: walk(v, depth + 1, names=k == "properties") for k, v in node.items() if k != "title"}

    return walk(schema)


llm = Llm()
