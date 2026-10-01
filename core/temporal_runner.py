"""Temporal: cliente, worker e a metaprogramação que transforma o service em activities.

@activities("<serviço>") faz de cada método público a activity "<serviço>.<método>" e valida o trilho no
import: async def m(self, data: Modelo) -> Modelo. Método de streaming (README §5.10) é um gerador assíncrono,
async def m(self, data: Modelo) -> AsyncIterator[...], e não vira activity. ServiceError com status < 500 vira erro não
re-tentável (regra de negócio não melhora tentando de novo); qualquer outra falha é re-tentada.

Quem age viaja junto (README §5.9): start_workflow grava o Principal do contexto num cabeçalho do Temporal, o
workflow o repassa a cada activity e a activity roda dentro de acting_as(...). O serviço não escreve nada:
current_tenant() funciona na activity como funcionou na requisição ou no evento que a disparou.

Agendamentos (README §5.13): runner.worker(..., schedules=[Schedule("limpeza", "0 4 * * *", Workflow.run, arg)]) cria,
atualiza e remove os agendamentos do Temporal no boot, conforme a lista (id <task_queue>/<id>). Execução sobreposta é
pulada e, se o Temporal ficar fora do ar, só a última execução perdida (até 10 min) é recuperada. Activity sem
pessoa por trás (agendamento, migração) roda como system("svc-<serviço>").

Trace (README §5.18): o interceptor do OpenTelemetry do próprio SDK continua o trace de quem iniciou o workflow em cada
workflow e activity (StartWorkflow → RunWorkflow → StartActivity → RunActivity).

Payloads cifrados (README §5.7): com TEMPORAL_PAYLOAD_KEY, tudo o que vai ao Temporal (entradas, resultados e cabeçalhos
de cada workflow e activity) sai em AES-256-GCM: o histórico, guardado pelo Temporal ou pelo Temporal Cloud, não tem
e-mail, link de senha nem conteúdo de aviso em claro. Obrigatória com ENVIRONMENT=production. A tela do Temporal
mostra esses payloads cifrados.

Variáveis: TEMPORAL_ADDRESS (padrão localhost:7233), TEMPORAL_NAMESPACE (padrão default),
TEMPORAL_API_KEY (Temporal Cloud; liga TLS), TEMPORAL_PAYLOAD_KEY (32 bytes em base64url; o keygen gera).
"""
import base64
import dataclasses
import functools
import hashlib
import inspect
import os
import logging
import re
import typing
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio import activity, client, worker
from temporalio import client as client_module
from temporalio.api.common.v1 import Payload
from temporalio.client import (
    Client,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
    WorkflowHandle,
)
from temporalio.client import HeaderCodecBehavior
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.converter import PayloadCodec
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.worker import Worker

from core.envelope import ServiceError
from core.security import Principal, acting_as, current, system

_MARK = "__cv_activity__"
_PRINCIPAL_HEADER = "cv-principal"
_SCHEDULE_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_NO_ARG = object()
log = logging.getLogger("core.temporal_runner")


@dataclass(frozen=True)
class Schedule:
    """Tarefa recorrente declarada no serviço (workflows.py), mantida no Temporal pelo runner a cada boot.

        SCHEDULES = [Schedule("limpeza", "0 4 * * *", LimpezaWorkflow.run, Empty())]   # todo dia às 4h (UTC)

    cron com 5 campos: minuto, hora, dia do mês, mês, dia da semana. timezone: nome IANA (ex.: America/Sao_Paulo).
    Sem pessoa por trás: as activities rodam como system("svc-<serviço>"); para tabelas por organização, use
    db.tenants(TABELA) e acting_as(system(SERVICE, org)).
    """

    id: str
    cron: str
    workflow: Callable[..., Any]
    arg: Any = _NO_ARG
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        if not _SCHEDULE_ID.match(self.id):
            raise ValueError(f"Schedule {self.id!r}: id em kebab-case (ex.: limpeza-diaria)")
        if len(self.cron.split()) != 5:
            raise ValueError(f"Schedule {self.id!r}: cron com 5 campos (minuto hora dia mês dia-da-semana), veio {self.cron!r}")


class TemporalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEMPORAL_", env_ignore_empty=True)  # variável vazia no compose = não definida

    address: str = "localhost:7233"
    namespace: str = "default"
    api_key: SecretStr | None = None
    payload_key: SecretStr | None = None
    environment: Literal["production", "development"] = Field("production", validation_alias="ENVIRONMENT")

    @model_validator(mode="after")
    def _encrypted_in_production(self) -> "TemporalSettings":
        if self.environment == "production" and not self.payload_key:
            raise ValueError("produção exige TEMPORAL_PAYLOAD_KEY: o histórico do Temporal não guarda dado em claro (README §5.7)")
        return self


class EncryptedPayloads(PayloadCodec):
    """AES-256-GCM em cada payload. O id da chave vai junto: payload de outra chave falha alto, nunca vira lixo."""

    ENCODING = b"binary/encrypted"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("TEMPORAL_PAYLOAD_KEY precisa de 32 bytes (base64url): rode uv run python -m core.security keygen")
        self._aead = AESGCM(key)
        self._key_id = hashlib.sha256(key).hexdigest()[:12].encode()

    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        sealed = []
        for payload in payloads:
            nonce = os.urandom(12)
            data = nonce + self._aead.encrypt(nonce, payload.SerializeToString(), self._key_id)
            sealed.append(Payload(metadata={"encoding": self.ENCODING, "encryption-key-id": self._key_id}, data=data))
        return sealed

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        opened = []
        for payload in payloads:
            if payload.metadata.get("encoding") != self.ENCODING:
                opened.append(payload)  # gravado antes da chave existir: segue como veio
                continue
            if payload.metadata.get("encryption-key-id") != self._key_id:
                raise ValueError("payload do Temporal cifrado com outra TEMPORAL_PAYLOAD_KEY")
            opened.append(Payload.FromString(self._aead.decrypt(payload.data[:12], payload.data[12:], self._key_id)))
        return opened


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
            try:
                s = TemporalSettings()
            except ValidationError as exc:
                raise RuntimeError(f"core.temporal_runner: configuração ausente ou insegura (README §5.7)\n{exc}") from None
            api_key = s.api_key.get_secret_value() if s.api_key else None
            codec = EncryptedPayloads(_b64d(s.payload_key.get_secret_value())) if s.payload_key else None
            self._client = await Client.connect(
                s.address,
                namespace=s.namespace,
                api_key=api_key,
                tls=api_key is not None,
                data_converter=dataclasses.replace(pydantic_data_converter, payload_codec=codec),
                header_codec_behavior=HeaderCodecBehavior.CODEC if codec else HeaderCodecBehavior.NO_CODEC,
                # Valem também para os workers criados com este cliente: quem age e o trace atravessam o Temporal.
                interceptors=[_PrincipalPropagation(), TracingInterceptor()],
            )
        return self._client

    @asynccontextmanager
    async def worker(
        self, task_queue: str, *, workflows: Sequence[type], service: object, schedules: Sequence[Schedule] = ()
    ) -> AsyncIterator[Worker | None]:
        """Roda o worker no mesmo loop do FastAPI, registrando as activities de @activities, e alinha os agendamentos.
        Serviço ainda sem activities nem workflows (ex.: um pacote que só declara ações) fica só com o cliente."""
        acts = [getattr(service, n) for n, fn in vars(type(service)).items() if getattr(fn, _MARK, False)]
        if len({s.id for s in schedules}) != len(schedules):
            raise ValueError("schedules: id repetido")
        if not acts and not workflows:
            await self.client()
            await self.sync_schedules(task_queue, schedules)
            yield None
            return
        async with Worker(await self.client(), task_queue=task_queue, workflows=workflows, activities=acts) as w:
            await self.sync_schedules(task_queue, schedules)
            yield w

    async def sync_schedules(self, task_queue: str, schedules: Sequence[Schedule]) -> None:
        """Deixa no Temporal exatamente os agendamentos declarados para esta fila: cria, atualiza e remove."""
        client = await self.client()
        prefix = f"{task_queue}/"
        existing = {listed.id async for listed in await client.list_schedules() if listed.id.startswith(prefix)}
        for declared in schedules:
            schedule_id = prefix + declared.id
            args = [] if declared.arg is _NO_ARG else [declared.arg]
            definition = client_module.Schedule(
                action=ScheduleActionStartWorkflow(declared.workflow, args=args, id=schedule_id, task_queue=task_queue),
                spec=ScheduleSpec(cron_expressions=[declared.cron], time_zone_name=declared.timezone),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(minutes=10)),
            )
            handle = client.get_schedule_handle(schedule_id)
            if schedule_id not in existing:
                try:
                    await client.create_schedule(schedule_id, definition)
                    log.info("agendamento %s criado (%s, %s)", schedule_id, declared.cron, declared.timezone)
                    continue
                except ScheduleAlreadyRunningError:  # outra réplica criou primeiro (ou a listagem ainda não o via)
                    pass
            await handle.update(lambda _input, definition=definition: ScheduleUpdate(schedule=definition))
        for stale in existing - {prefix + d.id for d in schedules}:
            await client.get_schedule_handle(stale).delete()
            log.info("agendamento %s removido (saiu da lista do serviço)", stale)

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


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


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
        who = _decode(input.headers.get(_PRINCIPAL_HEADER))
        if who is None:  # sem pessoa por trás (agendamento): age a própria plataforma, como "system:svc-<serviço>"
            who = system("svc-" + activity.info().activity_type.split(".")[0])
        with acting_as(who):
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
