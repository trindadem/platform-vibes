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

Variáveis: SURREAL_URL (padrão ws://localhost:8000) e, obrigatórias e sem padrão,
SURREAL_NAMESPACE, SURREAL_DATABASE, SURREAL_USER, SURREAL_PASSWORD.
"""
import asyncio
import re
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from typing import Any, LiteralString

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from surrealdb import AsyncSurreal, ConnectionUnavailableError, RecordID, ServerError, Table

from core.envelope import ServiceError
from core.security import current_tenant

TENANT = "tenant"
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_TENANT_PARAM = re.compile(r"\$tenant\b")
_DUPLICATE = re.compile(r"index `[a-z0-9_]+?__(?P<fields>[a-z0-9_]+)__unique` already contains")


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

    @asynccontextmanager
    async def connected(
        self,
        tables: Iterable[str] = (),
        *,
        shared: Iterable[str] = (),
        unique: Mapping[str, Iterable[str]] | None = None,
    ) -> AsyncIterator["Database"]:
        """Conecta no boot (falha cedo se faltar credencial) e garante tabelas, campo tenant e índices.

        tables: por organização (ganham o campo tenant, READONLY e indexado). shared: globais.
        unique: {"tabela": ["campo", ...]}; em tabela por organização o tenant entra no índice sozinho
        (o mesmo e-mail pode existir em duas organizações). Idempotente. O SurrealDB 3 recusa SELECT em
        tabela que nunca recebeu registro; declarar no boot faz a primeira listagem devolver [] em vez de erro.
        """
        per_tenant, globals_ = [_ident(t) for t in tables], [_ident(t) for t in shared]
        if both := set(per_tenant) & set(globals_):
            raise ValueError(f"tabela declarada em tables e em shared: {sorted(both)}")
        indexes = {_ident(t): [_ident(f) for f in fields] for t, fields in (unique or {}).items()}
        if unknown := set(indexes) - set(per_tenant) - set(globals_):
            raise ValueError(f"unique cita tabela não declarada em tables/shared: {sorted(unknown)}")
        # Nomes validados por _ident (só a-z, 0-9, _): seguros fora de parâmetro, que DEFINE não aceita.
        statements = [f"DEFINE TABLE IF NOT EXISTS {t} SCHEMALESS" for t in per_tenant + globals_]
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
        for statement in statements:
            await self._call("query", statement, None)
        self._tenant_tables, self._shared_tables = frozenset(per_tenant), frozenset(globals_)
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
        return await self._call("query", sql, params or None)

    async def create(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        name = self._declared(_ident(table))
        if name in self._tenant_tables:
            data = {**_without_tenant(data), TENANT: current_tenant()}
        return await self._call("create", Table(name), data)

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
        if tenant is None:
            return await self._call("merge", rid, data)
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
        # Conexão caiu (restart do banco, rede): reconecta uma vez e repete.
        for attempt in (1, 2):
            conn = await self._connection()
            try:
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


def _without_tenant(data: dict[str, Any]) -> dict[str, Any]:
    if TENANT in data:
        raise ValueError("não grave 'tenant' à mão: ele vem do contexto (core.security.current_tenant)")
    return data


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
