"""NATS: eventos duráveis (JetStream) e RPC (request/reply), sempre com modelos Pydantic.

Trilhos de subject:
- events.<serviço>.<ação>  → publish / subscribe. Durável (stream EVENTS): mensagem publicada com o
  serviço fora do ar é entregue quando ele voltar. Réplicas do mesmo serviço dividem o trabalho;
  serviços diferentes recebem cada um a sua cópia. Entrega at-least-once: use bus.message_id() como
  id idempotente (o mesmo em toda reentrega).
- rpc.<serviço>.<método>   → request / respond. Síncrono; a resposta trafega no ResponseEnvelope.

Mensagem inválida é descartada sem reentrega; handler que falha é re-tentado com espera crescente.
O log nunca inclui o payload. Variáveis: NATS_URL (padrão nats://localhost:4222) e NATS_CREDS
(arquivo .creds com permissões por subject; obrigatório em produção, conforme README §5.7).
"""
import contextvars
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import nats
from nats.js.api import ConsumerConfig, StreamConfig
from nats.js.errors import NotFoundError
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.envelope import ResponseEnvelope, ServiceError, error_code

STREAM = "EVENTS"
MAX_DELIVER = 5
_SUBJECT = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+){2,}$")
_message_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("message_id", default=None)

log = logging.getLogger("core.nats_bus")
M = TypeVar("M", bound=BaseModel)


class NatsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NATS_")

    url: str = "nats://localhost:4222"
    creds: str | None = None


class Bus:
    def __init__(self) -> None:
        self._nc: Any = None
        self._js: Any = None
        self._service: str | None = None

    @asynccontextmanager
    async def connected(self, service: str) -> AsyncIterator["Bus"]:
        """Conecta no boot; no desligamento, termina o que está em andamento (drain) e fecha."""
        s = NatsSettings()
        self._service = service
        self._nc = await nats.connect(
            servers=[s.url],
            name=service,
            user_credentials=s.creds,
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

    def message_id(self) -> str | None:
        """Id estável da mensagem em processamento (igual em toda reentrega). None fora de um handler."""
        return _message_id.get()

    async def publish(self, subject: str, message: BaseModel, *, msg_id: str | None = None) -> None:
        """Publica e espera a confirmação do JetStream. msg_id evita duplicata (janela de 2 min)."""
        _check(subject, "events")
        headers = {"Nats-Msg-Id": msg_id} if msg_id else None
        await self._jetstream().publish(subject, message.model_dump_json().encode(), headers=headers)

    async def subscribe(self, subject: str, handler: Callable[[M], Awaitable[None]], model: type[M]) -> None:
        _check(subject, "events")
        consumer = f"{self._service}-{subject}".replace(".", "_")  # estável: sobrevive a restarts

        async def on_message(msg: Any) -> None:
            try:
                data = model.model_validate_json(msg.data)
            except ValidationError:
                log.warning("mensagem inválida em %s descartada", subject)
                await msg.term()
                return
            meta = msg.metadata
            stable_id = (msg.headers or {}).get("Nats-Msg-Id") or f"{STREAM}-{meta.sequence.stream}"
            token = _message_id.set(stable_id)
            try:
                await handler(data)
            except Exception:
                attempt = meta.num_delivered
                if attempt >= MAX_DELIVER:
                    log.exception("mensagem em %s descartada após %d tentativas", subject, attempt)
                    await msg.term()
                else:
                    log.exception("falha em %s (tentativa %d/%d)", subject, attempt, MAX_DELIVER)
                    await msg.nak(delay=min(2**attempt, 60))
            else:
                await msg.ack()
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
        reply = await self._connection().request(subject, message.model_dump_json().encode(), timeout=timeout)
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
            try:
                envelope = ResponseEnvelope.success(await handler(model.model_validate_json(msg.data)), service)
            except ValidationError:
                envelope = ResponseEnvelope.failure(
                    error_code(service, "INVALID_PAYLOAD"), "Payload inválido.", service, 422
                )
            except ServiceError as exc:
                envelope = ResponseEnvelope.failure(exc.code, exc.message, service, exc.status)
            except Exception:
                log.exception("falha no RPC %s", subject)
                envelope = ResponseEnvelope.failure(
                    error_code(service, "EXECUTION_FAILED"), "Falha interna.", service, 500
                )
            await msg.respond(envelope.model_dump_json().encode())

        await self._connection().subscribe(subject, queue=service, cb=on_request)

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


def _check(subject: str, kind: str) -> None:
    if not subject.startswith(f"{kind}.") or not _SUBJECT.match(subject):
        raise ValueError(f"subject fora do trilho: {subject!r} (use {kind}.<serviço>.<ação>, README §5.3)")


async def _log_error(exc: Exception) -> None:
    log.warning("NATS: %s", exc)


bus = Bus()
