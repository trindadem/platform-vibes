"""Envelope canônico de I/O: toda resposta, de sucesso ou de erro, sai neste formato.

    {"ok": true,  "service": "svc-x", "data": {...}, "error": null}
    {"ok": false, "service": "svc-x", "data": null,  "error": {"code": "...", "message": "...", "status": 409, "details": []}}

Erro de negócio (spec §4): raise ServiceError("ERRO_X_LIMITE_EXCEDIDO", "mensagem", status=409).
Exceção inesperada nunca vaza detalhe: o cliente recebe um id; o log recebe o traceback.
"""
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

log = logging.getLogger("core.envelope")


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
        details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
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
