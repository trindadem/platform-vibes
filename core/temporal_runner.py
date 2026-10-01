"""Temporal: cliente, worker e a metaprogramação que transforma o service em activities.

@activities("<serviço>") faz de cada método público a activity "<serviço>.<método>" e valida o trilho no
import: async def m(self, data: Modelo) -> Modelo. ServiceError com status < 500 vira erro não
re-tentável (regra de negócio não melhora tentando de novo); qualquer outra falha é re-tentada.

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
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.worker import Worker

from core.envelope import ServiceError

_MARK = "__cv_activity__"


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
