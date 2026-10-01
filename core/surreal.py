"""SurrealDB: uma conexão WebSocket multiplexada por processo e só queries parametrizadas.

Trilhos:
- SurrealQL nunca é montada com f-string: valores entram como parâmetros ($nome).
  O tipo LiteralString faz o editor acusar SQL dinâmico:  await db.query("SELECT * FROM t WHERE x = $x", x=valor)
- Login sempre como usuário do banco (DEFINE USER ... ON DATABASE), nunca root: menor privilégio.
- Resultados voltam como tipos simples: "tabela:id" em vez de RecordID; select de um registro → dict | None.

Variáveis: SURREAL_URL (padrão ws://localhost:8000) e, obrigatórias e sem padrão,
SURREAL_NAMESPACE, SURREAL_DATABASE, SURREAL_USER, SURREAL_PASSWORD.
"""
import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, LiteralString

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from surrealdb import AsyncSurreal, ConnectionUnavailableError, RecordID, Table

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


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

    @asynccontextmanager
    async def connected(self) -> AsyncIterator["Database"]:
        """Conecta no boot (falha cedo se faltar credencial) e fecha no desligamento."""
        await self._connection()
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
        """Resultado do primeiro statement. Valores sempre via parâmetros: $nome ← nome=valor."""
        return await self._call("query", sql, params or None)

    async def create(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._call("create", Table(_ident(table)), data)

    async def select(self, record_id: str) -> dict[str, Any] | None:
        rows = await self._call("select", _record(record_id))
        if isinstance(rows, list):
            return rows[0] if rows else None
        return rows

    async def merge(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._call("merge", _record(record_id), data)

    async def delete(self, record_id: str) -> None:
        await self._call("delete", _record(record_id))

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


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"nome de tabela inválido: {name!r} (use snake_case: a-z, 0-9, _)")
    return name


def _record(record_id: str) -> RecordID:
    table, sep, key = record_id.partition(":")
    if not sep or not key:
        raise ValueError(f"id de registro inválido: {record_id!r} (formato: tabela:id)")
    return RecordID(_ident(table), key)


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
