"""Observabilidade (README §5.18): logs estruturados, rastreamento ponta a ponta, métricas e saúde. Uma linha no main.py:

    install_telemetry(app, service=SERVICE)

Trilhos:
- Logs: uma linha JSON por evento em stdout (LOG_FORMAT=text, padrão no desenvolvimento, é legível para gente), com
  service, trace_id, span_id, tenant e user (o sub; nunca nome, e-mail, corpo nem segredo). Antes de logar dados de
  fora, redact(...). Uma linha por requisição (método, rota, status, duração); /health não entra.
- Rastreamento (OpenTelemetry): requisição HTTP, chamada HTTP de saída, mensagem NATS (core/nats_bus.py), workflow e
  activity do Temporal (core/temporal_runner.py) e consulta ao SurrealDB (core/surreal.py) viram spans do mesmo trace:
  gateway → serviço → NATS → Temporal → banco. O gateway (edge=True) ignora traceparent vindo de fora: cada requisição
  pública começa um trace. Sem baggage (dado de fora não viaja entre serviços).
- Métricas: duração das requisições HTTP (servidor e cliente), das mensagens NATS e das consultas; métricas do serviço
  com telemetry.counter / telemetry.histogram (nome cv.<serviço>.<nome>). Organização e pessoa nunca viram atributo
  de métrica (cardinalidade); ficam no trace e no log.
- Exportação: OTLP/HTTP para OTEL_EXPORTER_OTLP_ENDPOINT (Grafana, Tempo, Jaeger, Honeycomb, Datadog...), com as
  variáveis padrão do OpenTelemetry (OTEL_TRACES_SAMPLER, OTEL_RESOURCE_ATTRIBUTES...). Sem a variável, nada sai do
  processo: os ids de trace continuam nos logs.
- Saúde: GET /health (público, sem dado nenhum) confere NATS, SurrealDB e Temporal do processo; 503 se algum falhar.
- Erro 500: o id que o usuário informa ao suporte é o trace_id (core/envelope.py): leva ao trace e aos logs.

Variáveis: LOG_LEVEL (INFO), LOG_FORMAT (json | text), OTEL_EXPORTER_OTLP_ENDPOINT (opcional).
"""
import asyncio
import json
import logging
import os
import sys
import time
import types
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")  # métricas HTTP no padrão estável (segundos), como as demais

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from opentelemetry import metrics, propagate, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic_settings import BaseSettings
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.envelope import ResponseEnvelope, error_response, trace_id
from core.security import HEALTH_PATH, current, redact

__all__ = ["install_telemetry", "telemetry", "Telemetry", "TRACE_HEADER"]

TRACE_HEADER = "x-trace-id"  # devolvido em toda resposta: o mesmo id do trace e dos logs
_INCOMING_CONTEXT = (b"traceparent", b"tracestate", b"baggage")
_QUIET = {name: logging.WARNING for name in ("httpx", "httpx2", "httpcore", "opentelemetry")}  # a linha por requisição já basta
# Atributos que todo LogRecord já tem: o resto (extra=) vai para o JSON, mascarado por redact.
_RECORD_FIELDS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}
_CONTEXT_FIELDS = ("service", "trace_id", "span_id", "tenant", "user")

log = logging.getLogger("core.telemetry")


class TelemetrySettings(BaseSettings):
    environment: Literal["production", "development"] = "production"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] | None = None  # padrão: json em produção, text em desenvolvimento
    otel_exporter_otlp_endpoint: str | None = None


class Telemetry:
    def __init__(self) -> None:
        self.service: str | None = None
        self._handler: logging.Handler | None = None
        self._exporting = False

    def setup(self, service: str) -> None:
        """Logs, propagação e provedores de trace e métrica do processo. Idempotente: o primeiro serviço define o
        recurso (um processo é um serviço); chamadas seguintes só refazem os logs."""
        s = TelemetrySettings()
        first = self.service is None
        self.service = self.service or service
        self._logging(s)
        if not first:
            return
        propagate.set_global_textmap(TraceContextTextMapPropagator())  # só traceparent: sem baggage
        resource = Resource.create({"service.name": self.service, "deployment.environment.name": s.environment})
        tracer_provider = TracerProvider(resource=resource)
        readers = []
        self._exporting = bool(s.otel_exporter_otlp_endpoint)
        if self._exporting:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
            logger_provider = LoggerProvider(resource=resource)
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
            exported = LoggingHandler(logger_provider=logger_provider)
            exported.addFilter(_Context(self))
            exported.addFilter(lambda record: not record.name.startswith("opentelemetry"))  # sem laço do exportador
            logging.getLogger().addHandler(exported)
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
        HTTPXClientInstrumentor().instrument()  # todo httpx do processo: gateway, http_client, IA, webhooks
        log.info("telemetria de %s pronta (%s)", self.service, "exportando por OTLP" if self._exporting else "só logs")

    def counter(self, name: str, description: str, unit: str = "1") -> metrics.Counter:
        """Contador do serviço: telemetry.counter("faturas_pagas", "Faturas pagas").add(1, {"forma": "pix"})."""
        return metrics.get_meter(self._prefix()).create_counter(f"cv.{self._prefix()}.{name}", unit=unit, description=description)

    def histogram(self, name: str, description: str, unit: str = "s") -> metrics.Histogram:
        """Distribuição do serviço (duração, tamanho): telemetry.histogram("geracao", "Tempo de gerar o PDF").record(1.2)."""
        return metrics.get_meter(self._prefix()).create_histogram(f"cv.{self._prefix()}.{name}", unit=unit, description=description)

    def _prefix(self) -> str:
        if self.service is None:
            raise RuntimeError("telemetry: chame install_telemetry(app, service=SERVICE) no main.py")
        return self.service.removeprefix("svc-")

    def _logging(self, s: TelemetrySettings) -> None:
        root = logging.getLogger()
        if self._handler is not None:
            root.removeHandler(self._handler)
        handler = logging.StreamHandler(sys.stdout)
        handler.addFilter(_Context(self))
        text = (s.log_format or ("text" if s.environment == "development" else "json")) == "text"
        handler.setFormatter(_TextFormatter() if text else _JsonFormatter())
        root.addHandler(handler)
        root.setLevel(s.log_level.upper())
        self._handler = handler
        for name in ("uvicorn", "uvicorn.error"):  # o uvicorn configura os próprios logs antes de importar o app
            logging.getLogger(name).handlers.clear()
            logging.getLogger(name).propagate = True
        access = logging.getLogger("uvicorn.access")  # a linha por requisição é a do core (com trace e organização)
        access.handlers.clear()
        access.propagate = False
        access.disabled = True
        for name, level in _QUIET.items():
            logging.getLogger(name).setLevel(level)


telemetry = Telemetry()


def install_telemetry(
    app: FastAPI, *, service: str, edge: bool = False, health: Callable[[], dict[str, Any]] | None = None
) -> None:
    """Logs, trace e métricas do app, e GET /health. edge=True só no gateway: ignora o traceparent de fora.
    health= acrescenta dados à resposta de /health (o gateway diz quantas rotas publica)."""
    telemetry.setup(service)
    original = app.build_middleware_stack

    def with_request_log(self: FastAPI) -> ASGIApp:
        # Entra por fora dos middlewares do serviço (vê 401 e 500) e por dentro do span do OpenTelemetry (tem trace_id).
        if not any(m.cls is _RequestLog for m in self.user_middleware):
            self.user_middleware.insert(0, Middleware(_RequestLog, service=service))
        return original()

    app.build_middleware_stack = types.MethodType(with_request_log, app)
    FastAPIInstrumentor.instrument_app(app, excluded_urls=f"{HEALTH_PATH}$", exclude_spans=["receive", "send"])
    if edge:
        instrumented = app.build_middleware_stack

        def without_outside_context(self: FastAPI) -> ASGIApp:
            return _WithoutIncomingContext(instrumented())

        app.build_middleware_stack = types.MethodType(without_outside_context, app)

    async def health_route() -> JSONResponse:
        checks = await _health_checks()
        failing = [{"loc": [name], "msg": result} for name, result in checks.items() if result != "ok"]
        if failing:
            return error_response(service, 503, "ERRO_UNHEALTHY", "Dependência fora do ar.", failing)
        data = {"status": "ok", "checks": checks, **(health() if health else {})}
        return JSONResponse(ResponseEnvelope.success(data, service).model_dump(mode="json"))

    app.add_api_route(HEALTH_PATH, health_route, methods=["GET"], include_in_schema=False)


async def _health_checks() -> dict[str, str]:
    """Só o que o processo usa: módulo do core não importado (o gateway não tem banco) não é conferido."""
    checks: dict[str, Any] = {}
    bus = getattr(sys.modules.get("core.nats_bus"), "bus", None)
    if bus is not None:
        checks["nats"] = lambda: _nats_ok(bus)
    db = getattr(sys.modules.get("core.surreal"), "db", None)
    if db is not None and db._conn is not None:  # direto na conexão: a checagem a cada 10 s não vira span nem métrica
        checks["surrealdb"] = lambda: db._conn.query("RETURN true")
    runner = getattr(sys.modules.get("core.temporal_runner"), "runner", None)
    if runner is not None and runner._client is not None:
        checks["temporal"] = lambda: runner._client.service_client.check_health()
    results = {}
    for name, check in checks.items():
        try:
            await asyncio.wait_for(check(), timeout=2)
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001 — saúde nunca derruba; diz o que falhou sem detalhe interno
            results[name] = "fora do ar"
            log.warning("saúde: %s fora do ar (%s)", name, type(exc).__name__)
    return results


async def _nats_ok(bus: Any) -> None:
    if bus._nc is None or not bus._nc.is_connected:
        raise ConnectionError("NATS desconectado")


class _Context(logging.Filter):
    """Cada linha de log leva o serviço, o trace e quem age (organização e o sub da pessoa)."""

    def __init__(self, owner: Telemetry) -> None:
        super().__init__()
        self.owner = owner

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.owner.service
        span = trace.get_current_span().get_span_context()
        record.trace_id = format(span.trace_id, "032x") if span.is_valid else None
        record.span_id = format(span.span_id, "016x") if span.is_valid else None
        who = current()
        record.tenant = getattr(record, "tenant", None) or (who.tenant if who else None)
        record.user = getattr(record, "user", None) or (who.sub if who else None)
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        data.update({k: v for k in _CONTEXT_FIELDS if (v := getattr(record, k, None))})
        extra = {k: v for k, v in vars(record).items() if k not in _RECORD_FIELDS and k not in _CONTEXT_FIELDS}
        data.update(redact(extra))
        if record.exc_info:
            data["error"] = {"type": record.exc_info[0].__name__ if record.exc_info[0] else None, "stack": self.formatException(record.exc_info)}
        return json.dumps(data, ensure_ascii=False, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        context = " ".join(
            f"{label}={value}"
            for label, value in (("trace", (getattr(record, "trace_id", None) or "")[:8]), ("org", getattr(record, "tenant", None)), ("user", getattr(record, "user", None)))
            if value
        )
        line = f"{stamp} {record.levelname:<7} {record.name}: {record.getMessage()}" + (f"  [{context}]" if context else "")
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class _RequestLog:
    """Uma linha por requisição (método, rota, status, duração, organização, pessoa) e o x-trace-id na resposta."""

    def __init__(self, app: ASGIApp, *, service: str) -> None:
        self.app, self.service = app, service
        self.log = logging.getLogger(f"{service}.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == HEALTH_PATH:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500
        current_trace = trace_id()

        async def send_with_trace(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                if current_trace:
                    MutableHeaders(scope=message).setdefault(TRACE_HEADER, current_trace)
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            route = getattr(scope.get("route"), "path", None) or scope["path"]  # o molde (/itens/{id}), não o id
            who = (scope.get("state") or {}).get("principal")
            self.log.log(
                logging.WARNING if status >= 500 else logging.INFO,
                "%s %s %d",
                scope["method"],
                route,
                status,
                extra={
                    "http_method": scope["method"],
                    "http_route": route,
                    "http_status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "tenant": who.tenant if who else None,
                    "user": who.sub if who else None,
                },
            )


class _WithoutIncomingContext:
    """Gateway: traceparent, tracestate e baggage de fora não entram (ninguém de fora escolhe o trace nem a amostragem)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() not in _INCOMING_CONTEXT]}
        await self.app(scope, receive, send)
