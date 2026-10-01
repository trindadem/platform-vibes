"""SurrealDB: uma conexão WebSocket multiplexada por processo, só queries parametrizadas e isolamento por organização.

Trilhos:
- SurrealQL nunca é montada com f-string: valores entram como parâmetros ($nome).
  O tipo LiteralString faz o editor acusar SQL dinâmico:  await db.query("SELECT * FROM t WHERE x = $x", x=valor)
- Toda tabela é declarada no boot: db.connected(tables=[...]) são tabelas POR ORGANIZAÇÃO (padrão) e
  shared=[...] são tabelas globais (só o serviço de identidade precisa). Tabela não declarada é erro.
- Tabela por organização (README §5.9): create grava o tenant do contexto (current_tenant()); select, merge e
  delete só enxergam registros da organização atual; o banco recusa trocar o tenant depois (READONLY).
  db.query injeta $tenant e recusa SQL que não o cita:  "SELECT * FROM faturas WHERE tenant = $tenant"
- db.query_shared roda sem filtro de organização e só existe para quem declarou shared=[...].
- Login sempre como usuário do banco (DEFINE USER ... ON DATABASE), nunca root: menor privilégio.
- Resultados voltam como tipos simples: "tabela:id" em vez de RecordID; select de um registro → dict | None.
- Valor repetido em índice unique → ServiceError 409 ERRO_RECORD_DUPLICATE (sem ecoar o valor).
- Trace (README §5.18): toda consulta vira um span "surrealdb <comando>" com o texto da SurrealQL (sem os valores, que
  vão sempre como parâmetros) e entra em db.client.operation.duration.
- Carimbos (README §5.13): toda tabela declarada ganha created_at, created_by, updated_at e updated_by, que o próprio
  banco preenche (inclusive na SurrealQL crua): created_* uma vez e imutáveis, updated_* a cada gravação. Quem age
  entra como $cv_actor em toda consulta do core (o sub do Principal; None sem ninguém). Gravar um carimbo à mão é erro.
- Migrações (README §5.13): db.connected(..., service=SERVICE, migrations=[Migration(1, "...", sql="...")]) roda as
  pendentes no boot, em ordem, uma vez por banco (registro em cv_migrations, com trava entre réplicas).
- Listas (README §5.12): db.page(TABELA, query, ModeloPage) devolve uma página filtrada, ordenada e com busca por
  palavras, sempre na organização atual. A query é um ListQuery (page, size, sort, q) cuja subclasse declara os
  filtros como campos: x → igualdade, x_from/x_to → intervalo, list[...] → um dos valores. Só ordena pelos campos
  de `sortable`; só busca nos campos declarados em db.connected(search={"tabela": ["campo"]}).

Variáveis: SURREAL_URL (padrão ws://localhost:8000) e, obrigatórias e sem padrão,
SURREAL_NAMESPACE, SURREAL_DATABASE, SURREAL_USER, SURREAL_PASSWORD.
"""
import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, LiteralString, TypeVar

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from surrealdb import AsyncSurreal, ConnectionUnavailableError, RecordID, ServerError, Table
from surrealdb.errors import parse_query_error

from core.envelope import ServiceError
from core.security import acting_as, current, current_tenant, system

TENANT = "tenant"
ACTOR = "cv_actor"  # parâmetro de toda consulta do core: quem age (carimbos created_by/updated_by)
STAMPS = ("created_at", "created_by", "updated_at", "updated_by")
MIGRATIONS = "cv_migrations"
_STAMP_FIELDS = (
    # created_* uma vez (o banco recusa trocar depois); updated_* recalculados a cada gravação.
    "DEFINE FIELD IF NOT EXISTS created_at ON TABLE {t} TYPE option<datetime> DEFAULT time::now() READONLY",
    "DEFINE FIELD IF NOT EXISTS created_by ON TABLE {t} DEFAULT $cv_actor READONLY",
    "DEFINE FIELD IF NOT EXISTS updated_at ON TABLE {t} TYPE option<datetime> VALUE time::now()",
    "DEFINE FIELD IF NOT EXISTS updated_by ON TABLE {t} VALUE $cv_actor",
)
_STALE_MIGRATION_SECONDS = 600  # migração "em andamento" há mais que isso: a réplica que a rodava caiu
log = logging.getLogger("core.surreal")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_TENANT_PARAM = re.compile(r"\$tenant\b")
_DUPLICATE = re.compile(r"index `[a-z0-9_]+?__(?P<fields>[a-z0-9_]+)__unique` already contains")
_VERSION = re.compile(r"(\d+)\.\d+")
_CASCADE = re.compile(r"not executed due to a failed transaction|Cannot COMMIT")
# Busca por palavras: início de palavra, sem diferença de maiúscula nem de acento ("pad" acha "Padaria", "joao" acha "João").
ANALYZER = "cv_busca"
_ANALYZER_DEF = f"DEFINE ANALYZER IF NOT EXISTS {ANALYZER} TOKENIZERS blank,class,punct FILTERS lowercase,ascii,edgengram(1,20)"
T = TypeVar("T")
P = TypeVar("P", bound=BaseModel)
_tracer = trace.get_tracer("core.surreal")
_duration = metrics.get_meter("core.surreal").create_histogram(
    "db.client.operation.duration", unit="s", description="Tempo de cada consulta ao SurrealDB"
)
_OPERATION = re.compile(r"^\s*\{?\s*(?:LET\s+\$\w+\s*=\s*\(?\s*)?([A-Za-z]+)")


class ListQuery(BaseModel):
    """Parâmetros de uma lista, vindos da URL (README §5.12). A subclasse declara os filtros como campos opcionais:

        class FaturaQuery(ListQuery):
            sortable: ClassVar[tuple[str, ...]] = ("cliente", "valor", "criada_em")
            default_sort: ClassVar[str | None] = "-criada_em"
            status: Literal["aberta", "paga"] | None = None     # status = $status
            valor_from: float | None = None                     # valor >= $valor_from
            cliente: list[str] | None = None                    # cliente IN $cliente

    Parâmetro desconhecido na URL é ignorado (extra="ignore"): a lista só lê o que declarou.
    """

    model_config = ConfigDict(extra="ignore")
    sortable: ClassVar[tuple[str, ...]] = ()
    default_sort: ClassVar[str | None] = None

    page: int = Field(1, ge=1, le=10_000, description="Página, a partir de 1")
    size: int = Field(20, ge=1, le=100, description="Itens por página (até 100)")
    sort: str | None = Field(None, max_length=64, description='Ordem: "campo" (crescente) ou "-campo" (decrescente)')
    q: str | None = Field(None, max_length=200, description="Busca por palavras (início de palavra, sem acento)")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        for name in [*cls.filter_names(), *cls.sortable, (cls.default_sort or "x").lstrip("-")]:
            if not _IDENT.match(name):
                raise TypeError(f"{cls.__name__}: {name!r} não é um nome de campo válido (snake_case)")
        if cls.default_sort and cls.default_sort.lstrip("-") not in cls.sortable:
            raise TypeError(f"{cls.__name__}: default_sort {cls.default_sort!r} precisa estar em sortable")

    @classmethod
    def filter_names(cls) -> list[str]:
        return [name for name in cls.model_fields if name not in ListQuery.model_fields]

    @field_validator("sort")
    @classmethod
    def _sortable(cls, value: str | None) -> str | None:
        if value is not None and value.lstrip("-") not in cls.sortable:
            raise ValueError(f"Ordenação não permitida. Use: {', '.join(cls.sortable) or 'nenhuma'} (com - na frente para decrescente).")
        return value

    @field_validator("q")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> dict[str, Any]:
        """No contrato (contracts.ts), sort vira a lista exata das ordens permitidas: "cliente" | "-cliente" | ..."""
        schema = handler.resolve_ref_schema(handler(core_schema))
        if cls.sortable and "sort" in schema.get("properties", {}):
            options = [option for name in cls.sortable for option in (name, f"-{name}")]
            schema["properties"]["sort"] = {**schema["properties"]["sort"], "anyOf": [{"enum": options}, {"type": "null"}]}
        return schema

    def filters(self) -> dict[str, Any]:
        """Filtros preenchidos (campo da subclasse com valor), na ordem da declaração."""
        return {name: value for name in self.filter_names() if (value := getattr(self, name)) not in (None, [])}


@dataclass(frozen=True)
class Migration:
    """Mudança de dados versionada, rodada uma vez por banco no boot (README §5.13).

        Migration(1, "status padrão nas faturas antigas", sql="UPDATE faturas SET status = 'aberta' WHERE status = NONE")
        Migration(2, "recalcula totais", run=_recalcula_totais)   # função async sem argumentos, em service.py

    A SQL roda numa transação e SEM filtro de organização: é a mudança de dados de todas, revisada no PR. A função
    roda como system(<serviço>). Versões crescentes a partir de 1; nunca edite uma migração já publicada, crie outra.
    """

    version: int
    description: str
    sql: LiteralString | None = None
    run: Callable[[], Awaitable[None]] | None = None


class Page(BaseModel, Generic[T]):
    """Uma página de lista. No schemas.py: class FaturaPage(Page[Fatura]): pass."""

    items: list[T]
    total: int = Field(..., description="Itens que atendem ao filtro, somando todas as páginas")
    page: int
    size: int
    pages: int = Field(..., description="Total de páginas (0 quando não há itens)")


class SurrealSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SURREAL_")

    url: str = "ws://localhost:8000"
    namespace: str
    database: str
    user: str
    password: SecretStr


class Database:
    def __init__(self) -> None:
        self._conn: Any = None
        self._lock = asyncio.Lock()
        self._tenant_tables: frozenset[str] = frozenset()
        self._shared_tables: frozenset[str] = frozenset()
        self._search: dict[str, tuple[str, ...]] = {}

    @asynccontextmanager
    async def connected(
        self,
        tables: Iterable[str] = (),
        *,
        shared: Iterable[str] = (),
        unique: Mapping[str, Iterable[str]] | None = None,
        search: Mapping[str, Iterable[str]] | None = None,
        migrations: Sequence[Migration] = (),
        service: str | None = None,
        resources: Iterable[Any] = (),
    ) -> AsyncIterator["Database"]:
        """Conecta no boot (falha cedo se faltar credencial) e garante tabelas, campo tenant e índices.

        tables: por organização (ganham o campo tenant, READONLY e indexado). shared: globais.
        unique: {"tabela": ["campo", ...]}; em tabela por organização o tenant entra no índice sozinho
        (o mesmo e-mail pode existir em duas organizações). search: {"tabela": ["campo", ...]} cria o índice de busca
        por palavras de cada campo (db.page com q). migrations (com service=SERVICE) roda as mudanças de dados pendentes,
        em ordem. resources (core/resources.py) acrescenta a tabela por organização, a busca e o índice único de cada
        cadastro declarado. Idempotente. O SurrealDB 3 recusa SELECT em
        tabela que nunca recebeu registro; declarar no boot faz a primeira listagem devolver [] em vez de erro.
        """
        resources = list(resources)
        tables = [*tables, *(r.table for r in resources)]
        unique = {**(unique or {}), **{r.table: r.unique for r in resources if r.unique}}
        search = {**(search or {}), **{r.table: r.search for r in resources if r.search}}
        per_tenant, globals_ = [_ident(t) for t in tables], [_ident(t) for t in shared]
        if len(per_tenant) != len(set(per_tenant)):
            raise ValueError(f"tabela declarada duas vezes: {sorted(t for t in per_tenant if per_tenant.count(t) > 1)}")
        if both := set(per_tenant) & set(globals_):
            raise ValueError(f"tabela declarada em tables e em shared: {sorted(both)}")
        indexes = {_ident(t): [_ident(f) for f in fields] for t, fields in (unique or {}).items()}
        if unknown := set(indexes) - set(per_tenant) - set(globals_):
            raise ValueError(f"unique cita tabela não declarada em tables/shared: {sorted(unknown)}")
        searches = {_ident(t): tuple(_ident(f) for f in fields) for t, fields in (search or {}).items()}
        if unknown := set(searches) - set(per_tenant) - set(globals_):
            raise ValueError(f"search cita tabela não declarada em tables/shared: {sorted(unknown)}")
        _check_migrations(migrations, service)
        # Nomes validados por _ident (só a-z, 0-9, _): seguros fora de parâmetro, que DEFINE não aceita.
        statements = [f"DEFINE TABLE IF NOT EXISTS {t} SCHEMALESS" for t in per_tenant + globals_]
        statements += [field.format(t=t) for t in per_tenant + globals_ for field in _STAMP_FIELDS]
        for t in per_tenant:
            statements += [
                f"DEFINE FIELD IF NOT EXISTS {TENANT} ON TABLE {t} TYPE string READONLY",
                f"DEFINE INDEX IF NOT EXISTS {t}__{TENANT} ON TABLE {t} FIELDS {TENANT}",
            ]
        for t, fields in indexes.items():
            columns = [TENANT, *(f for f in fields if f != TENANT)] if t in per_tenant else fields
            statements.append(
                f"DEFINE INDEX IF NOT EXISTS {t}__{'__'.join(fields)}__unique ON TABLE {t} FIELDS {', '.join(columns)} UNIQUE"
            )
        await self._connection()
        if searches:
            # O mesmo índice tem nomes diferentes: FULLTEXT no SurrealDB 3 (servidor), SEARCH no 2.x (o motor embutido
            # do SDK, usado nos testes). A busca se comporta igual nos dois.
            major = _VERSION.search(str(await self._call("version")) or "")
            keyword = "SEARCH" if major and int(major.group(1)) < 3 else "FULLTEXT"
            statements.append(_ANALYZER_DEF)
            for t, fields in searches.items():
                statements += [
                    f"DEFINE INDEX IF NOT EXISTS {t}__busca__{f} ON TABLE {t} FIELDS {f} {keyword} ANALYZER {ANALYZER} BM25"
                    for f in fields
                ]
        for statement in statements:
            await self._call("query", statement, None)
        self._tenant_tables, self._shared_tables = frozenset(per_tenant), frozenset(globals_)
        self._search = searches
        if migrations:
            await self._migrate(service or "", migrations)
        try:
            yield self
        finally:
            await self.close()

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def query(self, sql: LiteralString, **params: Any) -> Any:
        """Resultado do primeiro statement, sempre na organização atual: $tenant entra sozinho e a SQL precisa citá-lo."""
        if TENANT in params:
            raise ValueError("não passe tenant=: $tenant vem do contexto (core.security.current_tenant)")
        _no_actor(params)
        if not _TENANT_PARAM.search(sql):
            raise ValueError(
                "query sem $tenant: filtre a organização (ex.: WHERE tenant = $tenant). "
                "Tabela global? db.query_shared, só para quem declarou db.connected(shared=[...]) (README §5.9)"
            )
        return await self._call("query", sql, {**params, TENANT: current_tenant()})

    async def query_shared(self, sql: LiteralString, **params: Any) -> Any:
        """Query sem filtro de organização, para tabelas globais. Só existe para quem declarou shared=[...]."""
        if not self._shared_tables:
            raise RuntimeError("db.query_shared exige tabelas globais declaradas: db.connected(shared=[...]) (README §5.9)")
        _no_actor(params)
        return await self._call("query", sql, params or None)

    async def page(
        self,
        table: str,
        query: ListQuery,
        model: type[P],
        *,
        where: LiteralString = "",
        select: LiteralString = "*",
        **params: Any,
    ) -> P:
        """Uma página da lista: filtros da query, busca (q), ordem e total, na organização atual.

        Tabela por organização: o filtro de tenant entra sozinho. Tabela global: where= é obrigatório e diz quem
        enxerga o quê (ex.: where="owner = $org", org=...). select acrescenta campos calculados (ex.: "*, provider.slug
        AS slug"); a ordem só aceita campos presentes na seleção, por isso o * fica.
        """
        name = self._declared(_ident(table))
        if TENANT in params or ACTOR in params or any(key.startswith("f_") for key in params) or {"q", "size", "start"} & set(params):
            raise ValueError("parâmetros reservados em db.page: tenant, cv_actor, q, size, start e f_*")
        conditions: list[str] = []
        values: dict[str, Any] = dict(params)
        if name in self._tenant_tables:
            conditions.append(f"{TENANT} = $tenant")
            values[TENANT] = current_tenant()
        elif not where:
            raise ValueError(f"tabela global {name!r}: diga em where= quem enxerga o quê (README §5.12)")
        if where:
            conditions.append(f"({where})")
        for field, value in query.filters().items():
            column, operator = _filter(field, value)
            conditions.append(f"{column} {operator} $f_{field}")  # nomes validados no ListQuery; valor sempre parâmetro
            values[f"f_{field}"] = value
        score = ""
        if query.q:
            fields = self._search.get(name)
            if not fields:
                raise ServiceError("ERRO_SEARCH_UNAVAILABLE", "Esta lista não tem busca por texto.", status=422)
            conditions.append("(" + " OR ".join(f"{f} @{i}@ $q" for i, f in enumerate(fields)) + ")")
            score = ", (" + " + ".join(f"search::score({i})" for i in range(len(fields))) + ") AS _score"
            values["q"] = query.q
        condition = " AND ".join(conditions)
        rows = await self._call(
            "query",
            f"SELECT {select}{score} FROM {name} WHERE {condition} ORDER BY {_order(query, bool(score))} LIMIT $size START $start",
            {**values, "size": query.size, "start": (query.page - 1) * query.size},
        )
        # Conta a partir da subconsulta: o motor 2.x (embutido) soma os índices em vez de cruzá-los num count() direto.
        counted = await self._call(
            "query", f"SELECT count() AS total FROM (SELECT id FROM {name} WHERE {condition}) GROUP ALL", values
        )
        total = counted[0]["total"] if counted else 0
        return model.model_validate({
            "items": [{k: v for k, v in row.items() if k != "_score"} for row in rows],
            "total": total,
            "page": query.page,
            "size": query.size,
            "pages": -(-total // query.size),
        })

    async def create(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        name = self._declared(_ident(table))
        _without_stamps(data)
        if name in self._tenant_tables:
            data = {**_without_tenant(data), TENANT: current_tenant()}
        # Por consulta (e não pelo create do SDK): os carimbos precisam de $cv_actor.
        rows = await self._call("query", "CREATE type::table($tb) CONTENT $data RETURN AFTER", {"tb": name, "data": data})
        return rows[0]

    async def tenants(self, table: str) -> list[str]:
        """Organizações com registros na tabela, para tarefas da plataforma (agendamentos, migrações):

            for org in await db.tenants(FATURAS):
                with acting_as(system(SERVICE, org)):
                    ...

        Só fora de uma requisição ou como system(): uma pessoa nunca lista as organizações dos outros.
        """
        who = current()
        if who is not None and not who.is_system:
            raise PermissionError("db.tenants é só para tarefas da plataforma (acting_as(system(SERVICE)))")
        name = self._declared(_ident(table))
        if name not in self._tenant_tables:
            raise ValueError(f"{name!r} não é tabela por organização")
        rows = await self._call("query", f"SELECT {TENANT} FROM {name} GROUP BY {TENANT}", None)
        return sorted(row[TENANT] for row in rows or [] if row.get(TENANT))

    async def select(self, record_id: str) -> dict[str, Any] | None:
        rid = _record(record_id)
        tenant = self._tenant_of(rid)
        rows = await self._call("select", rid)
        row = (rows[0] if rows else None) if isinstance(rows, list) else rows
        if tenant is not None and row is not None and row.get(TENANT) != tenant:
            return None  # registro de outra organização: para quem pergunta, não existe
        return row

    async def merge(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        rid = _record(record_id)
        tenant = self._tenant_of(rid)
        _without_stamps(data)
        if tenant is None:
            rows = await self._call("query", "UPDATE $rid MERGE $data RETURN AFTER", {"rid": rid, "data": data})
        else:
            rows = await self._call(
                "query", "UPDATE $rid MERGE $data WHERE tenant = $tenant RETURN AFTER",
                {"rid": rid, "data": _without_tenant(data), TENANT: tenant},
            )
        if not rows:
            raise ServiceError("ERRO_RECORD_NOT_FOUND", "Registro não encontrado.", status=404)
        return rows[0]

    async def delete(self, record_id: str) -> None:
        rid = _record(record_id)
        tenant = self._tenant_of(rid)
        if tenant is None:
            await self._call("delete", rid)
        else:
            await self._call("query", "DELETE $rid WHERE tenant = $tenant", {"rid": rid, TENANT: tenant})

    async def _migrate(self, service: str, migrations: Sequence[Migration]) -> None:
        """Roda as migrações pendentes em ordem. Uma réplica por vez: quem cria o registro primeiro roda; as outras
        esperam. Falhou: o boot para (o registro fica failed e a próxima subida tenta de novo)."""
        await self._call("query", f"DEFINE TABLE IF NOT EXISTS {MIGRATIONS} SCHEMALESS", None)
        for m in migrations:
            rid = RecordID(MIGRATIONS, f"{service}-{m.version:04d}")
            if not await self._claim(rid, service, m):
                continue
            log.info("migração %s #%d: %s", service, m.version, m.description)
            try:
                with acting_as(system(service)):
                    if m.sql is not None:
                        await self._call("query", f"BEGIN TRANSACTION; {m.sql}; COMMIT TRANSACTION;", None)
                    else:
                        await m.run()  # type: ignore[misc]
            except Exception as exc:
                await self._call("query", "UPDATE $rid SET status = 'failed', error = $e", {"rid": rid, "e": type(exc).__name__})
                raise RuntimeError(f"migração {service} #{m.version} ({m.description}) falhou: o serviço não sobe") from exc
            await self._call("query", "UPDATE $rid SET status = 'done', finished_at = time::now()", {"rid": rid})

    async def _claim(self, rid: RecordID, service: str, m: Migration) -> bool:
        """True se esta réplica deve rodar a migração; False se já está feita. Espera quem estiver rodando."""
        deadline = time.monotonic() + _STALE_MIGRATION_SECONDS
        while True:
            rows = await self._call("query", "SELECT * FROM $rid", {"rid": rid})
            row = rows[0] if rows else None
            if row is None:
                try:
                    await self._call(
                        "query",
                        "CREATE $rid SET service = $s, version = $v, description = $d, status = 'running', started_at = time::now()",
                        {"rid": rid, "s": service, "v": m.version, "d": m.description},
                    )
                    return True
                except ServerError as exc:
                    if "already exists" not in str(exc):
                        raise
                    continue  # outra réplica criou primeiro: volta e confere o estado
            if row["status"] == "done":
                return False
            # failed (tenta de novo) ou running abandonada (réplica caiu): reivindica só se ninguém fez isso antes
            taken = await self._call(
                "query",
                "UPDATE $rid SET status = 'running', started_at = time::now(), error = NONE "
                "WHERE status = 'failed' OR (status = 'running' AND started_at < time::now() - 10m) RETURN AFTER",
                {"rid": rid},
            )
            if taken:
                return True
            if time.monotonic() > deadline:
                raise RuntimeError(f"migração {service} #{m.version} está em andamento há mais de 10 min (confira {rid})")
            await asyncio.sleep(1)

    def _declared(self, table: str) -> str:
        if table not in self._tenant_tables and table not in self._shared_tables:
            raise ValueError(
                f"tabela {table!r} não declarada: inclua em db.connected(tables=[...]) (por organização) "
                "ou shared=[...] (global)"
            )
        return table

    def _tenant_of(self, rid: RecordID) -> str | None:
        """Organização exigida para tocar no registro (None: tabela global)."""
        return current_tenant() if self._declared(rid.table_name) in self._tenant_tables else None

    async def _connection(self) -> Any:
        async with self._lock:
            if self._conn is None:
                s = SurrealSettings()
                conn = AsyncSurreal(s.url)
                await conn.connect()
                await conn.signin({
                    "namespace": s.namespace,
                    "database": s.database,
                    "username": s.user,
                    "password": s.password.get_secret_value(),
                })
                await conn.use(s.namespace, s.database)
                self._conn = conn
            return self._conn

    async def _call(self, method: str, *args: Any) -> Any:
        operation = method.upper()
        attributes = {"db.system.name": "surrealdb"}
        if method == "query":  # quem age vai em toda consulta: o banco carimba created_by/updated_by com ele
            who = current()
            args = (args[0], {**(args[1] or {}), ACTOR: who.sub if who else None}, *args[2:])
            found = _OPERATION.match(args[0])
            operation = found.group(1).upper() if found else "QUERY"
            attributes["db.query.text"] = args[0][:1000]  # só o texto: os valores vão em parâmetros e nunca entram
        attributes["db.operation.name"] = operation
        started = time.perf_counter()
        with _tracer.start_as_current_span(f"surrealdb {operation}", kind=SpanKind.CLIENT, attributes=attributes):
            try:
                return await self._call_once(method, *args)
            finally:
                _duration.record(time.perf_counter() - started, {"db.system.name": "surrealdb", "db.operation.name": operation})

    async def _call_once(self, method: str, *args: Any) -> Any:
        # Conexão caiu (restart do banco, rede): reconecta uma vez e repete.
        for attempt in (1, 2):
            conn = await self._connection()
            try:
                if method == "query":
                    return _plain(await _query(conn, *args))
                return _plain(await getattr(conn, method)(*args))
            except (ConnectionUnavailableError, ConnectionError):
                if attempt == 2:
                    raise
                async with self._lock:
                    self._conn = None
            except ServerError as exc:
                # Índice único violado é erro de negócio (409), sem ecoar o valor repetido (pode ser um e-mail).
                if duplicate := _DUPLICATE.search(str(exc)):
                    fields = duplicate["fields"].replace("__", ", ")
                    raise ServiceError("ERRO_RECORD_DUPLICATE", f"Já existe um registro com o mesmo valor em: {fields}.", status=409) from None
                raise


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"nome de tabela inválido: {name!r} (use snake_case: a-z, 0-9, _)")
    return name


def _record(record_id: str) -> RecordID:
    table, sep, key = record_id.partition(":")
    if not sep or not key:
        raise ValueError(f"id de registro inválido: {record_id!r} (formato: tabela:id)")
    return RecordID(_ident(table), key)


async def _query(conn: Any, sql: str, params: dict[str, Any] | None) -> Any:
    """Resultado do primeiro comando, conferindo TODOS. O SDK só confere o primeiro: num BEGIN ...; X; COMMIT do
    SurrealDB 3, o BEGIN sai OK e o erro de X passava em silêncio (achado na migração que falhou e ficou "done")."""
    results = (await conn.query_raw(sql, params)).get("result") or []
    if errors := [statement for statement in results if statement.get("status") == "ERR"]:
        # Numa transação, os outros comandos falham por tabela ("not executed due to a failed transaction",
        # "Cannot COMMIT"): a causa é o comando que falhou por conta própria.
        cause = next((e for e in errors if not _CASCADE.search(str(e.get("result")))), errors[0])
        raise parse_query_error(cause)
    return results[0].get("result") if results else None


def _filter(field: str, value: Any) -> tuple[str, str]:
    """Convenção dos filtros do ListQuery: x → x =, x_from → x >=, x_to → x <=, lista → x IN."""
    if field.endswith("_from"):
        return field.removesuffix("_from"), ">="
    if field.endswith("_to"):
        return field.removesuffix("_to"), "<="
    return field, "IN" if isinstance(value, list) else "="


def _order(query: ListQuery, by_score: bool) -> str:
    """sort pedido > relevância da busca > default_sort > id. O id desempata: a mesma página volta igual."""
    sort = query.sort or (None if by_score else type(query).default_sort)
    if sort:
        return f"{sort.lstrip('-')} {'DESC' if sort.startswith('-') else 'ASC'}, id ASC"
    return "_score DESC, id ASC" if by_score else "id ASC"


def _without_tenant(data: dict[str, Any]) -> dict[str, Any]:
    """Tabela por organização: o tenant vem do contexto, nunca dos dados."""
    if TENANT in data:
        raise ValueError("não grave 'tenant' à mão: ele vem do contexto (core.security.current_tenant)")
    return data


def _without_stamps(data: dict[str, Any]) -> None:
    """Qualquer tabela: os carimbos são do banco."""
    if stamped := sorted(set(STAMPS) & set(data)):
        raise ValueError(f"não grave {', '.join(stamped)} à mão: o banco carimba quem e quando (README §5.13)")


def _no_actor(params: Mapping[str, Any]) -> None:
    if ACTOR in params:
        raise ValueError("não passe cv_actor=: quem age vem do contexto (core.security.current)")


def _check_migrations(migrations: Sequence[Migration], service: str | None) -> None:
    if not migrations:
        return
    if not service:
        raise ValueError("migrations exige service=SERVICE (o registro de cada migração é por serviço)")
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migrations: versões precisam ser 1, 2, 3... em ordem e sem buracos (veio {versions})")
    for m in migrations:
        if (m.sql is None) == (m.run is None):
            raise ValueError(f"migração #{m.version}: informe sql= ou run= (só um dos dois)")



def _plain(value: Any) -> Any:
    if isinstance(value, RecordID):
        return str(value)
    if isinstance(value, Table):
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


db = Database()
