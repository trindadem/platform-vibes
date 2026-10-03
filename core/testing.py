"""Kit de testes de serviço (README §5.5): o main.py de verdade, pelas rotas, sem nenhuma infraestrutura.

    from core.testing import service_app                         # tests/<serviço>.py (PYTHONPATH=services/svc-<nome>)

    def test_cria_cliente():
        async def cenario(app):
            ana = app.user("ana", "acme", "owner")
            criado = await ana.post("/clientes", json={"nome": "Padaria"})
            assert criado.status_code == 200 and criado.json()["data"]["nome"] == "Padaria"
            assert app.live[-1] == ("vendas.clientes", criado.json()["data"]["id"], "created")
        service_app(cenario)

O lifespan do main.py roda inteiro, com o que ele declara (tabelas, índices, migrações, cadastros, módulo):
- SurrealDB embutido em memória (mem://), a SurrealQL de verdade;
- NATS em memória: publish (app.published), live (app.live) e request vão para listas; subscribe e respond guardam o
  handler. app.respond(subject, função) atende um RPC de outro serviço (ex.: o svc-plans); sem quem atenda, o core se
  comporta como com o serviço fora do ar;
- Temporal em memória: start_workflow vai para app.workflows (os agendamentos não rodam);
- motor de processos em memória (app.motor): implantar, iniciar, mensagens e tarefas concluídas vão para listas; os
  workers não pegam jobs sozinhos: app.job(tipo, ...) passa um job pelo handler de verdade e devolve como ele termina;
- armazenamento de arquivos desligado; tokens assinados com chaves de teste (app.user(sub, organização, *papéis)).
Trilho: toda rota HTTP do manifesto do serviço (gateway/endpoints/<nome>.yaml) precisa existir no main.py; faltou,
o teste para dizendo qual (no ar, o gateway devolveria 404).
"""
import asyncio
import importlib
import importlib.util
import os
import sys
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nats.errors import NoRespondersError
from pydantic import BaseModel
from surrealdb import AsyncSurreal

__all__ = ["service_app", "ServiceApp"]

_KEY = Ed25519PrivateKey.generate()


def _environment() -> None:
    """Variáveis de teste antes do main.py ser importado (install_security lê a configuração no import)."""
    from core import security

    defaults = {
        "ENVIRONMENT": "development",
        "AUTH_ISSUER": "https://auth.cv.test",
        "AUTH_AUDIENCE": "cv-api",
        "AUTH_PRIVATE_KEY": security._b64e(_KEY.private_bytes_raw()),
        "AUTH_PUBLIC_KEY": security._b64e(_KEY.public_key().public_bytes_raw()),
        "SURREAL_NAMESPACE": "cv",
        "SURREAL_DATABASE": "app",
        "SURREAL_USER": "teste",
        "SURREAL_PASSWORD": "teste",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)
    for name in ("AUTH_JWKS_URL",):
        os.environ.pop(name, None)
    security._settings.cache_clear()
    security._own_keys.cache_clear()


class ServiceApp:
    """O serviço no ar, em memória: clientes HTTP por pessoa e o que ele publicou."""

    def __init__(self, main: ModuleType) -> None:
        self.main = main
        self.published: list[tuple[str, BaseModel]] = []
        self.live: list[tuple[str, Any, Any]] = []
        self.requests: list[tuple[str, BaseModel]] = []
        self.workflows: list[tuple[str, Any]] = []
        self.handlers: dict[str, Callable[[Any], Awaitable[Any]]] = {}
        self.jobs: dict[str, Any] = {}
        self.motor = FakeEngine()
        self._responders: dict[str, Callable[[Any], Any]] = {}
        self._worker_service = ""

    def user(self, sub: str, tenant: str | None = None, *roles: str) -> httpx.AsyncClient:
        """Cliente HTTP com o token de uma pessoa (organização ativa e papéis nela)."""
        from core import security

        token = security.issue_token(sub, tenant=tenant, roles=roles)
        return self._client({"Authorization": f"Bearer {token}"})

    def anonymous(self) -> httpx.AsyncClient:
        return self._client({})

    def respond(self, subject: str, handler: Callable[[Any], Any]) -> None:
        """Atende um RPC (rpc.<serviço>.<método>) que o serviço testado faz a outro serviço."""
        self._responders[subject] = handler

    async def deliver(self, subject: str, data: BaseModel, *, who: Any = None, msg_id: str | None = None) -> None:
        """Entrega um evento NATS ao handler que o serviço assinou (subscribe), em nome de quem. msg_id: o id estável
        da mensagem (bus.message_id()); entregar de novo com o mesmo id é a reentrega do NATS."""
        from core.nats_bus import _message_id
        from core.security import acting_as, check_gates

        handler = self.handlers[subject]
        token = _message_id.set(msg_id)
        try:
            with acting_as(who):
                await check_gates(who)
                await handler(data)
        finally:
            _message_id.reset(token)

    async def job(
        self, job_type: str, *, tenant: str = "acme", processo: str = "proc1", element: str = "passo", variables: dict | None = None,
        headers: dict | None = None, kind: str = "BPMN_ELEMENT", listener: str = "UNSPECIFIED", user_task: dict | None = None,
        version: int = 1, instance: str = "9001",
    ) -> Any:
        """Passa um job do motor pelo handler que o serviço registrou em processes.worker (ação ou jobs=), como o
        worker de verdade, e devolve o Outcome (concluido com as variáveis, handoff ou falhou). O relato do passo vai
        para app.published."""
        from core.processes import Job, processes

        self.motor._seq += 1
        job = Job(key=str(self.motor._seq), type=job_type, kind=kind, listener=listener, tenant=tenant, processo=processo,
                  process_id=f"p_{tenant}_{processo}", version=version, instance=instance, element=element,
                  element_instance=str(self.motor._seq), headers=headers or {}, variables=variables or {}, user_task=user_task)
        outcome = await processes.run_job(self._worker_service, self.jobs[job_type], job)
        await processes.report(job, outcome)
        return outcome

    def _client(self, headers: dict[str, str]) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.main.app)
        return httpx.AsyncClient(transport=transport, base_url="http://servico", headers=headers)

    # ── Dublês do NATS e do Temporal ─────────────────────────────────────────

    @asynccontextmanager
    async def _bus_connected(self, service: str):
        from core.nats_bus import bus

        bus._service = service
        try:
            yield bus
        finally:
            bus._service = None

    async def _publish(self, subject: str, message: BaseModel, *, msg_id: str | None = None) -> None:
        self.published.append((subject, message))

    async def _live(self, topic: str, message: BaseModel, *, user: str | None = None) -> None:
        self.live.append((topic, getattr(message, "id", message), getattr(message, "action", None)))

    async def _request(self, subject: str, message: BaseModel, response_model: type[BaseModel], *, timeout: float = 5.0) -> Any:
        self.requests.append((subject, message))
        handler = self._responders.get(subject)
        if handler is None:
            raise NoRespondersError
        result = handler(message)
        if asyncio.iscoroutine(result):
            result = await result
        return response_model.model_validate(result.model_dump() if isinstance(result, BaseModel) else result)

    async def _subscribe(self, subject: str, handler: Callable[[Any], Awaitable[None]], model: type[BaseModel]) -> None:
        self.handlers[subject] = handler

    async def _respond(self, subject: str, handler: Callable[[Any], Awaitable[BaseModel]], model: type[BaseModel]) -> None:
        self.handlers[subject] = handler

    @asynccontextmanager
    async def _worker(self, task_queue: str, *, workflows: Any, service: object, schedules: Any = ()):
        yield None

    async def _start_workflow(self, run: Callable[..., Any], arg: Any, *, task_queue: str, id: str | None = None) -> None:
        self.workflows.append((getattr(run, "__qualname__", str(run)), arg))

    async def _storage_connected(self, service: str) -> None:
        return None

    @asynccontextmanager
    async def _process_worker(self, service: str, actions: Any = (), implementation: object | None = None, *,
                              jobs: Any = None, concurrency: int = 4, lock_seconds: int = 300):
        from core.processes import processes

        prefix = service.removeprefix("svc-")
        self._worker_service = service
        self.jobs = {f"{prefix}.{a.name}": processes._action_handler(prefix, a, implementation) for a in actions}
        self.jobs.update(jobs or {})
        yield None


class FakeEngine:
    """O motor de processos em memória (core/processes.py: camunda). Implantar dá a versão seguinte do processo."""

    def __init__(self) -> None:
        self.deployed: list[tuple[str, str]] = []
        self.started: list[tuple[str, dict]] = []
        self.messages: list[tuple[str, str, dict]] = []
        self.completed: list[tuple[str, dict]] = []
        self.cancelled: list[str] = []
        self.paths: dict[str, list[dict]] = {}
        self._seq = 9000

    async def deploy(self, xml: str, process_id: str) -> Any:
        from core.processes import Deployed

        self.deployed.append((process_id, xml))
        version = sum(1 for pid, _ in self.deployed if pid == process_id)
        return Deployed(process_id=process_id, key=f"k-{process_id}-{version}", version=version)

    async def start(self, process_id: str, variables: Any) -> Any:
        from core.processes import Started

        self._seq += 1
        self.started.append((process_id, dict(variables)))
        version = sum(1 for pid, _ in self.deployed if pid == process_id) or 1
        return Started(instance=str(self._seq), version=version)

    async def message(self, name: str, key: str, variables: Any, *, ttl_seconds: int = 3600, message_id: str | None = None) -> None:
        self.messages.append((name, key, dict(variables)))

    async def complete_task(self, key: str, variables: Any) -> None:
        from core.envelope import ServiceError

        if any(k == key for k, _ in self.completed):
            raise ServiceError("ERRO_PROCESSOS_TAREFA_FECHADA", "Esta tarefa já foi resolvida.", status=409)
        self.completed.append((key, dict(variables)))

    async def path(self, instance: str) -> list[dict]:
        return self.paths.get(instance, [])

    async def cancel(self, instance: str) -> None:
        self.cancelled.append(instance)


def service_app(cenario: Callable[[ServiceApp], Awaitable[Any]], *, main: str = "main") -> Any:
    """Sobe o main.py do serviço (o que está no PYTHONPATH) em memória, roda o cenário e desliga tudo."""
    _environment()
    module = sys.modules.get(main) or importlib.import_module(main)

    async def run() -> Any:
        from core.nats_bus import bus
        from core.plans import plans
        from core.processes import camunda, processes
        from core.storage import storage
        from core.surreal import db
        from core.temporal_runner import runner

        app = ServiceApp(module)
        patches = {
            (bus, "connected"): app._bus_connected, (bus, "publish"): app._publish, (bus, "live"): app._live,
            (bus, "request"): app._request, (bus, "subscribe"): app._subscribe, (bus, "respond"): app._respond,
            (runner, "worker"): app._worker, (runner, "start_workflow"): app._start_workflow,
            (storage, "connected"): app._storage_connected, (processes, "worker"): app._process_worker,
            **{(camunda, name): getattr(app.motor, name) for name in ("deploy", "start", "message", "complete_task", "path", "cancel")},
        }
        saved = {key: key[0].__dict__.get(key[1]) for key in patches}
        for (target, name), value in patches.items():
            setattr(target, name, value)
        conn = AsyncSurreal("mem://")
        await conn.connect()
        await conn.use("cv", "app")
        db._conn = conn
        plans.clear()
        try:
            async with module.app.router.lifespan_context(module.app):
                _routes_match_manifest(module.app, bus.service)
                return await cenario(app)
        finally:
            for (target, name), value in saved.items():
                if value is None:
                    delattr(target, name)
                else:
                    setattr(target, name, value)
            plans.clear()
            plans._module, plans._declared = None, {}  # a conferência de módulo é do processo: não vaza para outro teste

    return asyncio.run(run())


def _routes_match_manifest(app: Any, service: str | None, root: Path | None = None) -> None:
    """Cada rota HTTP que o manifesto publica para este serviço existe no main.py (método e caminho)."""
    if not service:
        return
    root = root or Path(__file__).resolve().parent.parent
    manifest = root / "gateway" / "endpoints" / f"{service.removeprefix('svc-')}.yaml"
    if not manifest.exists():
        return
    spec = importlib.util.spec_from_file_location("cv_gateway_schemas", root / "gateway" / "schemas.py")
    gateway_schemas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gateway_schemas)  # o schemas.py do gateway, com outro nome: o do serviço já está carregado
    _Manifest = gateway_schemas.Manifest
    declared = _Manifest.model_validate(yaml.safe_load(manifest.read_text(encoding="utf-8")))
    served = {(method, route.path) for route in app.routes for method in getattr(route, "methods", None) or ()}
    missing = [
        f"{ep.method} {urlsplit(ep.target_url).path}"
        for ep in declared.all_endpoints()
        if ep.target_type == "http" and (ep.method, urlsplit(ep.target_url).path) not in served
    ]
    if missing:
        raise AssertionError(
            f"o manifesto gateway/endpoints/{manifest.name} publica rotas que o main.py não tem: {', '.join(missing)} "
            "(declare a rota no main.py com o mesmo método e caminho do target_url)"
        )
