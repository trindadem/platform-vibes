"""Temporal: cliente, worker e a metaprogramação que transforma o service em activities.

@activities("<serviço>") faz de cada método público a activity "<serviço>.<método>" e valida o trilho no
import: async def m(self, data: Modelo) -> Modelo. Método de streaming (README §5.10) é um gerador assíncrono,
async def m(self, data: Modelo) -> AsyncIterator[...], e não vira activity. ServiceError com status < 500 vira erro não
re-tentável (regra de negócio não melhora tentando de novo); qualquer outra falha é re-tentada.

Quem age viaja junto (README §5.9): start_workflow grava o Principal do contexto num cabeçalho do Temporal, o
workflow o repassa a cada activity e a activity roda dentro de acting_as(...). O serviço não escreve nada:
current_tenant() funciona na activity como funcionou na requisição ou no evento que a disparou.

Variáveis: TEMPORAL_ADDRESS (padrão localhost:7233), TEMPORAL_NAMESPACE (padrão default),
TEMPORAL_API_KEY (Temporal Cloud; liga TLS).
"""
import functools
import inspect
import typing
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio import activity, client, worker
from temporalio.api.common.v1 import Payload
from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.worker import Worker

from core.envelope import ServiceError
from core.security import Principal, acting_as, current

_MARK = "__cv_activity__"
_PRINCIPAL_HEADER = "cv-principal"


class TemporalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEMPORAL_")

    address: str = "localhost:7233"
    namespace: str = "default"
    api_key: SecretStr | None = None


def activities(prefix: str) -> Callable[[type], type]:
    """Decorator de classe: registra os métodos públicos como activities "<prefix>.<método>"."""

    def apply(cls: type) -> type:
        for name, fn in list(vars(cls).items()):
            if name.startswith("_") or not inspect.isfunction(fn):
                continue
            if inspect.isasyncgenfunction(fn):
                _check_stream_rail(cls, name, fn)  # entrega pedaços pelo HTTP; activity não faz streaming
                continue
            _check_rail(cls, name, fn)
            wrapped = _business_errors_are_final(fn)
            setattr(wrapped, _MARK, True)
            setattr(cls, name, activity.defn(name=f"{prefix}.{name}")(wrapped))
        return cls

    return apply


class Runner:
    def __init__(self) -> None:
        self._client: Client | None = None

    async def client(self) -> Client:
        if self._client is None:
            s = TemporalSettings()
            api_key = s.api_key.get_secret_value() if s.api_key else None
            self._client = await Client.connect(
                s.address,
                namespace=s.namespace,
                api_key=api_key,
                tls=api_key is not None,
                data_converter=pydantic_data_converter,
                interceptors=[_PrincipalPropagation()],  # vale também para os workers criados com este cliente
            )
        return self._client

    @asynccontextmanager
    async def worker(self, task_queue: str, *, workflows: Sequence[type], service: object) -> AsyncIterator[Worker]:
        """Roda o worker no mesmo loop do FastAPI, registrando as activities de @activities."""
        acts = [getattr(service, n) for n, fn in vars(type(service)).items() if getattr(fn, _MARK, False)]
        async with Worker(await self.client(), task_queue=task_queue, workflows=workflows, activities=acts) as w:
            yield w

    async def start_workflow(
        self, run: Callable[..., Any], arg: Any, *, task_queue: str, id: str | None = None
    ) -> WorkflowHandle:
        """Inicia o workflow. Com id, é idempotente: o mesmo id nunca inicia duas execuções."""
        client = await self.client()
        if id is None:
            return await client.start_workflow(run, arg, id=f"{task_queue}-{uuid.uuid4().hex}", task_queue=task_queue)
        workflow_id = f"{task_queue}-{id}"
        try:
            return await client.start_workflow(
                run, arg, id=workflow_id, task_queue=task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE
            )
        except WorkflowAlreadyStartedError:
            return client.get_workflow_handle(workflow_id)


# ── Propagação de quem age (cliente → workflow → activities) ────────────────

def _encode(who: Principal) -> Payload:
    return pydantic_data_converter.payload_converter.to_payload(who)


def _decode(payload: Payload | None) -> Principal | None:
    return pydantic_data_converter.payload_converter.from_payload(payload, Principal) if payload else None


class _PrincipalPropagation(client.Interceptor, worker.Interceptor):
    def intercept_client(self, next: client.OutboundInterceptor) -> client.OutboundInterceptor:
        return _ClientOutbound(next)

    def intercept_activity(self, next: worker.ActivityInboundInterceptor) -> worker.ActivityInboundInterceptor:
        return _ActivityInbound(next)

    def workflow_interceptor_class(
        self, input: worker.WorkflowInterceptorClassInput
    ) -> type[worker.WorkflowInboundInterceptor]:
        return _WorkflowInbound


class _ClientOutbound(client.OutboundInterceptor):
    async def start_workflow(self, input: client.StartWorkflowInput) -> WorkflowHandle[Any, Any]:
        who = current()
        if who is not None:
            input.headers = {**input.headers, _PRINCIPAL_HEADER: _encode(who)}
        return await super().start_workflow(input)


class _ActivityInbound(worker.ActivityInboundInterceptor):
    async def execute_activity(self, input: worker.ExecuteActivityInput) -> Any:
        with acting_as(_decode(input.headers.get(_PRINCIPAL_HEADER))):
            return await super().execute_activity(input)


class _WorkflowInbound(worker.WorkflowInboundInterceptor):
    # O cabeçalho só é copiado (nunca decodificado) dentro do workflow: nada de I/O nem de não determinismo.
    header: Payload | None = None

    def init(self, outbound: worker.WorkflowOutboundInterceptor) -> None:
        super().init(_WorkflowOutbound(outbound, self))

    async def execute_workflow(self, input: worker.ExecuteWorkflowInput) -> Any:
        self.header = input.headers.get(_PRINCIPAL_HEADER)
        return await super().execute_workflow(input)


class _WorkflowOutbound(worker.WorkflowOutboundInterceptor):
    def __init__(self, next: worker.WorkflowOutboundInterceptor, inbound: _WorkflowInbound) -> None:
        super().__init__(next)
        self._inbound = inbound

    def _carry(self, input: Any) -> None:
        if self._inbound.header is not None:
            input.headers = {**input.headers, _PRINCIPAL_HEADER: self._inbound.header}

    def start_activity(self, input: worker.StartActivityInput) -> Any:
        self._carry(input)
        return super().start_activity(input)

    def start_local_activity(self, input: worker.StartLocalActivityInput) -> Any:
        self._carry(input)
        return super().start_local_activity(input)

    async def start_child_workflow(self, input: worker.StartChildWorkflowInput) -> Any:
        self._carry(input)
        return await super().start_child_workflow(input)


# ── Trilho das activities ───────────────────────────────────────────────────

def _is_model(tp: Any) -> bool:
    return inspect.isclass(tp) and issubclass(tp, BaseModel)


def _check_rail(cls: type, name: str, fn: Callable[..., Any]) -> None:
    hints = typing.get_type_hints(fn)
    params = list(inspect.signature(fn).parameters)[1:]
    if not (
        inspect.iscoroutinefunction(fn)
        and len(params) == 1
        and _is_model(hints.get(params[0]))
        and _is_model(hints.get("return"))
    ):
        raise TypeError(
            f"{cls.__name__}.{name} viola o trilho: use 'async def {name}(self, data: <Modelo>) -> <Modelo>' "
            f"com modelos de schemas.py, ou renomeie para _{name} se for helper."
        )


def _check_stream_rail(cls: type, name: str, fn: Callable[..., Any]) -> None:
    hints = typing.get_type_hints(fn)
    params = list(inspect.signature(fn).parameters)[1:]
    if not (len(params) == 1 and _is_model(hints.get(params[0])) and "return" in hints):
        raise TypeError(
            f"{cls.__name__}.{name} viola o trilho de streaming: use "
            f"'async def {name}(self, data: <Modelo>) -> AsyncIterator[<Pedaço> | <Final>]' com modelos de schemas.py."
        )


def _business_errors_are_final(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    async def wrapper(self: Any, data: Any) -> Any:
        try:
            return await fn(self, data)
        except ServiceError as exc:
            if exc.status < 500 and activity.in_activity():
                raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from exc
            raise

    return wrapper


runner = Runner()
