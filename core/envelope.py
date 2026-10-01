"""Envelope canônico de I/O: toda resposta, de sucesso ou de erro, sai neste formato.

    {"ok": true,  "service": "svc-x", "data": {...}, "error": null}
    {"ok": false, "service": "svc-x", "data": null,  "error": {"code": "...", "message": "...", "status": 409, "details": []}}

Erro de negócio (spec §4): raise ServiceError("ERRO_X_LIMITE_EXCEDIDO", "mensagem", status=409).
Exceção inesperada nunca vaza detalhe: o cliente recebe um id; o log recebe o traceback.

Resposta em pedaços (README §5.10): stream_response(gerador, service, final=Modelo) vira SSE com
    event: delta  data: <pedaço>            (cada item do gerador)
    event: done   data: <envelope de sucesso com o item final>
    event: error  data: <envelope de erro>   (mesmas regras: erro de negócio com código, inesperado só com id)
e um comentário de batimento a cada 15 s. Quem fecha a aba cancela o gerador.
"""
import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

log = logging.getLogger("core.envelope")

# Mensagens de validação em pt-BR, com os limites do próprio modelo. Tipo não listado: mensagem original.
_VALIDATION_MESSAGES = {
    "missing": "Campo obrigatório.",
    "extra_forbidden": "Campo não permitido.",
    "string_too_short": "Mínimo de {min_length} caracteres.",
    "string_too_long": "Máximo de {max_length} caracteres.",
    "too_short": "Mínimo de {min_length} itens.",
    "too_long": "Máximo de {max_length} itens.",
    "greater_than": "Deve ser maior que {gt}.",
    "greater_than_equal": "Deve ser maior ou igual a {ge}.",
    "less_than": "Deve ser menor que {lt}.",
    "less_than_equal": "Deve ser menor ou igual a {le}.",
    "string_type": "Deve ser um texto.",
    "string_pattern_mismatch": "Formato inválido.",
    "int_type": "Deve ser um número inteiro.",
    "int_parsing": "Deve ser um número inteiro.",
    "float_type": "Deve ser um número.",
    "float_parsing": "Deve ser um número.",
    "bool_type": "Deve ser verdadeiro ou falso.",
    "bool_parsing": "Deve ser verdadeiro ou falso.",
    "literal_error": "Valor não permitido (aceitos: {expected}).",
    "enum": "Valor não permitido (aceitos: {expected}).",
    "json_invalid": "JSON inválido.",
}


class ErrorInfo(BaseModel):
    code: str
    message: str
    status: int
    details: list[dict[str, Any]] = Field(default_factory=list)


class ResponseEnvelope(BaseModel):
    ok: bool
    service: str
    data: Any = None
    error: ErrorInfo | None = None

    @classmethod
    def success(cls, data: Any, service: str) -> "ResponseEnvelope":
        return cls(ok=True, service=service, data=data)

    @classmethod
    def failure(
        cls, code: str, message: str, service: str, status: int, details: list[dict[str, Any]] | None = None
    ) -> "ResponseEnvelope":
        error = ErrorInfo(code=code, message=message, status=status, details=details or [])
        return cls(ok=False, service=service, error=error)


class ServiceError(Exception):
    """Erro mapeado no spec §4. Com status < 500, o Temporal não re-tenta (core/temporal_runner.py)."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def error_code(service: str, suffix: str) -> str:
    """svc-user-auth + INVALID_PAYLOAD → ERRO_USER_AUTH_INVALID_PAYLOAD (convenção do spec §4)."""
    return f"ERRO_{service.removeprefix('svc-').replace('-', '_').upper()}_{suffix}"


def error_response(
    service: str,
    status: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ResponseEnvelope.failure(code, message, service, status, details)
    return JSONResponse(body.model_dump(mode="json"), status_code=status, headers=headers)


def validation_message(error: dict[str, Any]) -> str:
    """Mensagem pt-BR para um erro do Pydantic (usa ctx: min_length, gt, expected...)."""
    template = _VALIDATION_MESSAGES.get(error.get("type", ""))
    ctx = {k: int(v) if isinstance(v, float) and v.is_integer() else v for k, v in error.get("ctx", {}).items()}
    if "expected" in ctx:
        ctx["expected"] = str(ctx["expected"]).replace(" or ", " ou ")
    try:
        return template.format(**ctx) if template else error["msg"]
    except (KeyError, IndexError):
        return error["msg"]


HEARTBEAT_SECONDS = 15
SSE_HEADERS = {"cache-control": "no-store", "x-accel-buffering": "no"}


def sse(event: str, data: str) -> bytes:
    """Um evento SSE. data é JSON numa linha (model_dump_json nunca quebra linha)."""
    return f"event: {event}\ndata: {data}\n\n".encode()


def stream_response(items: AsyncIterator[BaseModel], service: str, *, final: type[BaseModel]) -> StreamingResponse:
    """Gerador de modelos → resposta SSE: itens do tipo final encerram com done; os outros saem como delta."""

    async def events() -> AsyncIterator[bytes]:
        try:
            async for item in items:
                if isinstance(item, final):
                    yield sse("done", ResponseEnvelope.success(item, service).model_dump_json())
                    return
                yield sse("delta", item.model_dump_json())
            raise RuntimeError(f"stream de {service} terminou sem {final.__name__}")
        except ServiceError as exc:
            yield sse("error", ResponseEnvelope.failure(exc.code, exc.message, service, exc.status).model_dump_json())
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            log.error("erro inesperado no stream de %s (id %s)", service, error_id, exc_info=exc)
            failure = ResponseEnvelope.failure(
                error_code(service, "EXECUTION_FAILED"), f"Falha interna. Informe o id {error_id} ao suporte.", service, 500
            )
            yield sse("error", failure.model_dump_json())

    return StreamingResponse(with_heartbeat(events()), media_type="text/event-stream", headers=SSE_HEADERS)


async def with_heartbeat(source: AsyncIterator[bytes], every: float = HEARTBEAT_SECONDS) -> AsyncIterator[bytes]:
    """Intercala um comentário SSE quando a fonte fica quieta: proxies não derrubam a conexão parada."""
    iterator = source.__aiter__()
    pending: asyncio.Future[bytes] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=every)
            if not done:
                yield b": ping\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            finally:
                pending = None
            yield chunk
    finally:
        if pending is not None:  # cliente saiu no meio: cancela o passo em andamento antes de fechar a fonte
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()


def install_envelope(app: FastAPI, service: str) -> None:
    """Faz todo erro do app (negócio, HTTP, validação, inesperado) sair no envelope."""

    async def on_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return error_response(service, exc.status, exc.code, exc.message)

    async def on_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            service, exc.status_code, f"ERRO_HTTP_{exc.status_code}", str(exc.detail), headers=exc.headers
        )

    async def on_invalid_payload(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Sem "input": o erro aponta o campo, nunca ecoa o valor recebido (pode ser uma senha).
        details = [{"loc": list(e["loc"]), "msg": validation_message(e), "type": e["type"]} for e in exc.errors()]
        return error_response(service, 422, error_code(service, "INVALID_PAYLOAD"), "Payload inválido.", details)

    async def on_unexpected(_: Request, exc: Exception) -> JSONResponse:
        error_id = uuid.uuid4().hex[:12]
        log.error("erro inesperado em %s (id %s)", service, error_id, exc_info=exc)
        message = f"Falha interna. Informe o id {error_id} ao suporte."
        return error_response(service, 500, error_code(service, "EXECUTION_FAILED"), message)

    app.add_exception_handler(ServiceError, on_service_error)
    app.add_exception_handler(HTTPException, on_http_error)
    app.add_exception_handler(RequestValidationError, on_invalid_payload)
    app.add_exception_handler(Exception, on_unexpected)
