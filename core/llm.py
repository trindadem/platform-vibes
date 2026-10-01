"""IA: o único jeito de um serviço chamar modelos (README §5.11). Qualquer API compatível com OpenAI, pelo Agno.

    texto   = await llm.ask("openrouter/claude", "Resuma: ...", instructions="Seja breve.")
    fatura  = await llm.ask("local/llama", texto, output=Fatura)             # saída estruturada (modelo Pydantic)
    legenda = await llm.ask("openai/gpt", "O que há na foto?", images=[Image(url="https://...")])
    texto   = await llm.ask("openai/gpt", pergunta, tools=[buscar_cliente])  # ferramentas: funções async com docstring
    async for pedaco in llm.stream("openrouter/claude", pergunta): ...       # texto em pedaços → stream_response
    vetores = await llm.embed("openai/text-embedding-3-small", ["a", "b"])
    agente  = await llm.agent("openrouter/claude", tools=[...])              # Agent do Agno para casos avançados

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
"""
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Literal

os.environ.setdefault("AGNO_TELEMETRY", "false")  # antes de importar o Agno: nada sai para os servidores dele

import httpx
from agno.agent import Agent
from agno.media import Image
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunContentEvent, RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel, Field, SecretStr, field_serializer

from core.envelope import ServiceError
from core.http_client import no_cookie_jar
from core.nats_bus import bus
from core.security import assert_public_url, current_tenant

__all__ = ["Image", "llm", "Llm", "Resolved", "ResolveRequest", "UsageEvent", "RESOLVE_SUBJECT", "USAGE_SUBJECT"]

RESOLVE_SUBJECT = "rpc.ai.resolve"
USAGE_SUBJECT = "events.ai.usage"
CACHE_SECONDS = 60
_MODEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}/\S{1,200}$")

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


llm = Llm()
