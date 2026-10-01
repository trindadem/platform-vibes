"""NATS: eventos duráveis (JetStream) e RPC (request/reply), sempre com modelos Pydantic.

Trilhos de subject:
- events.<serviço>.<ação>  → publish / subscribe. Durável (stream EVENTS): mensagem publicada com o
  serviço fora do ar é entregue quando ele voltar. Réplicas do mesmo serviço dividem o trabalho;
  serviços diferentes recebem cada um a sua cópia. Entrega at-least-once: use bus.message_id() como
  id idempotente (o mesmo em toda reentrega).
- rpc.<serviço>.<método>   → request / respond. Síncrono; a resposta trafega no ResponseEnvelope.
- live.<org>.org.<tópico> e live.<org>.user.<pessoa>.<tópico> → bus.live / bus.live_feed. Ao vivo para a tela
  (README §5.10): NATS simples, efêmero (a verdade está no banco). A organização vem sempre do contexto, então um
  serviço não consegue avisar outra organização; o tópico é <serviço>.<evento> e só o próprio serviço o emite.

Quem age viaja junto (README §5.9): publish e request anexam o Principal do contexto no cabeçalho Cv-Principal;
subscribe e respond o restauram antes do handler, então current_tenant() funciona igual ao HTTP. O cabeçalho é
confiável porque só a plataforma publica no NATS (em produção, NATS_CREDS com permissão por subject).

O trace viaja junto (README §5.18): publish e request levam o traceparent no cabeçalho; subscribe e respond continuam o
mesmo trace, num span por mensagem, e contam cada resultado em cv.nats.processed (ok, retry, dropped, invalid).

Mensagem inválida é descartada sem reentrega; handler que falha é re-tentado com espera crescente.
O log nunca inclui o payload. Variáveis: NATS_URL (padrão nats://localhost:4222) e a credencial: NATS_USER e
NATS_PASSWORD (o compose.prod.yaml cria um usuário para os serviços e outro, restrito, para o gateway) ou NATS_CREDS
(arquivo .creds de contas NATS). Com ENVIRONMENT=production, conexão sem credencial não sobe (README §5.7).
"""
import asyncio
import contextvars
import hashlib
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal, TypeVar

import time

import nats
from nats.js.api import ConsumerConfig, StreamConfig
from opentelemetry import metrics, propagate, trace
from opentelemetry.trace import SpanKind, StatusCode
from nats.js.errors import NotFoundError
from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.envelope import ResponseEnvelope, ServiceError, error_code
from core.security import Principal, acting_as, current, current_tenant

STREAM = "EVENTS"
PRINCIPAL_HEADER = "Cv-Principal"
MAX_DELIVER = 5
_SUBJECT = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+){2,}$")
_TOPIC = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*\.[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIVE_QUEUE = 256  # eventos guardados por conexão lenta antes de descartar os mais novos
_message_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("message_id", default=None)

log = logging.getLogger("core.nats_bus")
M = TypeVar("M", bound=BaseModel)
_tracer = trace.get_tracer("core.nats_bus")
_meter = metrics.get_meter("core.nats_bus")
_processed = _meter.create_counter("cv.nats.processed", unit="{message}", description="Mensagens processadas, por subject e resultado")
_duration = _meter.create_histogram("cv.nats.duration", unit="s", description="Tempo de processar uma mensagem ou um RPC")


class NatsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NATS_", env_ignore_empty=True)  # variável vazia no compose = não definida

    url: str = "nats://localhost:4222"
    creds: str | None = None
    user: str | None = None
    password: SecretStr | None = None
    environment: Literal["production", "development"] = Field("production", validation_alias="ENVIRONMENT")

    @model_validator(mode="after")
    def _authenticated_in_production(self) -> "NatsSettings":
        if bool(self.user) != bool(self.password):
            raise ValueError("NATS_USER e NATS_PASSWORD andam juntos")
        if self.environment == "production" and not (self.creds or self.user):
            raise ValueError("produção exige credencial no NATS: NATS_USER/NATS_PASSWORD ou NATS_CREDS (README §5.7)")
        return self


class Bus:
    def __init__(self) -> None:
        self._nc: Any = None
        self._js: Any = None
        self._service: str | None = None

    @asynccontextmanager
    async def connected(self, service: str) -> AsyncIterator["Bus"]:
        """Conecta no boot; no desligamento, termina o que está em andamento (drain) e fecha."""
        try:
            s = NatsSettings()
        except ValidationError as exc:
            raise RuntimeError(f"core.nats_bus: configuração ausente ou insegura (README §5.7)\n{exc}") from None
        self._service = service
        self._nc = await nats.connect(
            servers=[s.url],
            name=service,
            user_credentials=s.creds,
            user=s.user,
            password=s.password.get_secret_value() if s.password else None,
            max_reconnect_attempts=-1,
            error_cb=_log_error,
        )
        self._js = self._nc.jetstream()
        await self._ensure_stream()
        try:
            yield self
        finally:
            await self._nc.drain()
            self._nc = self._js = None

    @property
    def service(self) -> str | None:
        """Nome do serviço conectado (svc-...), ou None antes do bus.connected."""
        return self._service

    def message_id(self) -> str | None:
        """Id estável da mensagem em processamento (igual em toda reentrega). None fora de um handler."""
        return _message_id.get()

    async def publish(self, subject: str, message: BaseModel, *, msg_id: str | None = None) -> None:
        """Publica e espera a confirmação do JetStream. msg_id evita duplicata (janela de 2 min)."""
        _check(subject, "events")
        with _tracer.start_as_current_span(f"publish {subject}", kind=SpanKind.PRODUCER, attributes=_attributes(subject)):
            headers = _context_headers({"Nats-Msg-Id": msg_id} if msg_id else {})
            await self._jetstream().publish(subject, message.model_dump_json().encode(), headers=headers)

    async def subscribe(self, subject: str, handler: Callable[[M], Awaitable[None]], model: type[M]) -> None:
        _check(subject, "events")
        consumer = f"{self._service}-{subject}".replace(".", "_")  # estável: sobrevive a restarts

        async def on_message(msg: Any) -> None:
            started = time.perf_counter()
            parent = propagate.extract(msg.headers or {})  # continua o trace de quem publicou
            with _tracer.start_as_current_span(f"process {subject}", context=parent, kind=SpanKind.CONSUMER, attributes=_attributes(subject)) as span:
                outcome = await _process(msg)
                span.set_attribute("cv.outcome", outcome)
                if outcome != "ok":
                    span.set_status(StatusCode.ERROR)
            _processed.add(1, {"messaging.destination.name": subject, "cv.outcome": outcome})
            _duration.record(time.perf_counter() - started, {"messaging.destination.name": subject})

        async def _process(msg: Any) -> str:
            try:
                data = model.model_validate_json(msg.data)
                who = _principal_from(msg.headers)
            except ValidationError:
                log.warning("mensagem inválida em %s descartada", subject)
                await msg.term()
                return "invalid"
            meta = msg.metadata
            stable_id = (msg.headers or {}).get("Nats-Msg-Id") or f"{STREAM}-{meta.sequence.stream}"
            token = _message_id.set(stable_id)
            try:
                with acting_as(who):
                    await handler(data)
            except Exception as exc:
                trace.get_current_span().record_exception(exc)
                attempt = meta.num_delivered
                if attempt >= MAX_DELIVER:
                    log.exception("mensagem em %s descartada após %d tentativas", subject, attempt)
                    await msg.term()
                    return "dropped"
                log.exception("falha em %s (tentativa %d/%d)", subject, attempt, MAX_DELIVER)
                await msg.nak(delay=min(2**attempt, 60))
                return "retry"
            else:
                await msg.ack()
                return "ok"
            finally:
                _message_id.reset(token)

        await self._jetstream().subscribe(
            subject,
            queue=consumer,
            cb=on_message,
            manual_ack=True,
            config=ConsumerConfig(max_deliver=MAX_DELIVER, ack_wait=60),
        )

    async def request(self, subject: str, message: BaseModel, response_model: type[M], *, timeout: float = 5.0) -> M:
        """RPC: envia, espera a resposta e devolve o modelo. Erro remoto vira ServiceError com o mesmo código."""
        _check(subject, "rpc")
        payload = message.model_dump_json().encode()
        with _tracer.start_as_current_span(f"request {subject}", kind=SpanKind.CLIENT, attributes=_attributes(subject)):
            reply = await self._connection().request(subject, payload, timeout=timeout, headers=_context_headers({}))
        envelope = ResponseEnvelope.model_validate_json(reply.data)
        if not envelope.ok:
            raise ServiceError(envelope.error.code, envelope.error.message, status=envelope.error.status)
        return response_model.model_validate(envelope.data)

    async def respond(
        self, subject: str, handler: Callable[[M], Awaitable[BaseModel]], model: type[M]
    ) -> None:
        """Atende um RPC. Réplicas dividem as requisições; toda resposta sai no envelope."""
        _check(subject, "rpc")
        service = self._service or "unknown"

        async def on_request(msg: Any) -> None:
            started = time.perf_counter()
            parent = propagate.extract(msg.headers or {})
            with _tracer.start_as_current_span(f"respond {subject}", context=parent, kind=SpanKind.SERVER, attributes=_attributes(subject)) as span:
                try:
                    data, who = model.model_validate_json(msg.data), _principal_from(msg.headers)
                    with acting_as(who):
                        envelope = ResponseEnvelope.success(await handler(data), service)
                except ValidationError:
                    envelope = ResponseEnvelope.failure(
                        error_code(service, "INVALID_PAYLOAD"), "Payload inválido.", service, 422
                    )
                except ServiceError as exc:
                    envelope = ResponseEnvelope.failure(exc.code, exc.message, service, exc.status)
                except Exception as exc:
                    span.record_exception(exc)
                    log.exception("falha no RPC %s", subject)
                    envelope = ResponseEnvelope.failure(
                        error_code(service, "EXECUTION_FAILED"), "Falha interna.", service, 500
                    )
                outcome = "ok" if envelope.ok else f"error-{envelope.error.status}"
                span.set_attribute("cv.outcome", outcome)
                if not envelope.ok and envelope.error.status >= 500:
                    span.set_status(StatusCode.ERROR)
                await msg.respond(envelope.model_dump_json().encode())
            _processed.add(1, {"messaging.destination.name": subject, "cv.outcome": outcome})
            _duration.record(time.perf_counter() - started, {"messaging.destination.name": subject})

        await self._connection().subscribe(subject, queue=service, cb=on_request)

    async def live(self, topic: str, message: BaseModel, *, user: str | None = None) -> None:
        """Avisa a tela ao vivo: a organização inteira ou só uma pessoa (user=sub), sempre na organização atual."""
        prefix = (self._service or "").removeprefix("svc-")
        if not _TOPIC.match(topic) or topic.split(".")[0] != prefix:
            raise ValueError(f"tópico ao vivo fora do trilho: {topic!r} (use {prefix or '<serviço>'}.<evento>, README §5.10)")
        tenant = _subject_token(current_tenant())
        audience = f"user.{_subject_token(user)}" if user is not None else "org"
        await self._connection().publish(f"live.{tenant}.{audience}.{topic}", message.model_dump_json().encode())

    @asynccontextmanager
    async def live_feed(self, who: Principal) -> AsyncIterator["asyncio.Queue[tuple[str, bytes]]"]:
        """Fila com os eventos ao vivo de quem age: os da organização do token e os endereçados a essa pessoa."""
        if not who.tenant:
            raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", status=403)
        queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=LIVE_QUEUE)
        tenant, person = _subject_token(who.tenant), _subject_token(who.sub)
        prefixes = (f"live.{tenant}.org.", f"live.{tenant}.user.{person}.")

        async def on_event(msg: Any) -> None:
            topic = next(msg.subject.removeprefix(p) for p in prefixes if msg.subject.startswith(p))
            try:
                queue.put_nowait((topic, msg.data))
            except asyncio.QueueFull:
                log.warning("conexão ao vivo lenta: evento %s descartado", topic)

        subscriptions = [await self._connection().subscribe(p + ">", cb=on_event) for p in prefixes]
        try:
            yield queue
        finally:
            for subscription in subscriptions:
                await subscription.unsubscribe()

    async def _ensure_stream(self) -> None:
        try:
            await self._js.stream_info(STREAM)
        except NotFoundError:
            config = StreamConfig(name=STREAM, subjects=["events.>"], max_age=7 * 24 * 3600, duplicate_window=120)
            await self._js.add_stream(config)

    def _connection(self) -> Any:
        if self._nc is None:
            raise RuntimeError("bus não conectado: use 'async with bus.connected(SERVICE)' no lifespan")
        return self._nc

    def _jetstream(self) -> Any:
        self._connection()
        return self._js


def _context_headers(headers: dict[str, str]) -> dict[str, str] | None:
    """Quem age (Cv-Principal) e o trace em andamento (traceparent) vão no cabeçalho da mensagem."""
    who = current()
    if who is not None:
        headers[PRINCIPAL_HEADER] = who.model_dump_json()
    propagate.inject(headers)
    return headers or None


def _attributes(subject: str) -> dict[str, str]:
    return {"messaging.system": "nats", "messaging.destination.name": subject}


def _principal_from(headers: dict[str, str] | None) -> Principal | None:
    raw = (headers or {}).get(PRINCIPAL_HEADER)
    return Principal.model_validate_json(raw) if raw else None


def _subject_token(value: str) -> str:
    """Id seguro como pedaço de subject (sem ponto, espaço ou curinga); ids de fora viram um hash estável."""
    return value if _TOKEN.match(value) else "h" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _check(subject: str, kind: str) -> None:
    if not subject.startswith(f"{kind}.") or not _SUBJECT.match(subject):
        raise ValueError(f"subject fora do trilho: {subject!r} (use {kind}.<serviço>.<ação>, README §5.3)")


async def _log_error(exc: Exception) -> None:
    log.warning("NATS: %s", exc)


bus = Bus()
