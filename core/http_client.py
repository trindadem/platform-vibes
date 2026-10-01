"""HTTP para chamadas EXTERNAS (APIs de terceiros), com as proteções que costumam ser esquecidas.

- Bloqueia SSRF: só https e só hosts com IP público (security.assert_public_url). Nada de
  169.254.169.254, localhost ou rede interna. http:// exige allow_http=True explícito.
- Não segue redirects: um redirect poderia levar para a rede interna depois da checagem.
- Sempre com timeout (5 s para conectar, 30 s para ler/escrever) e 2 novas tentativas só em falha de conexão.
Serviços internos não usam este client: serviços conversam por NATS ou pelo Gateway.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from core.security import assert_public_url


class HttpClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def connected(self) -> AsyncIterator["HttpClient"]:
        try:
            yield self
        finally:
            await self.close()

    async def request(self, method: str, url: str, *, allow_http: bool = False, **kwargs: Any) -> httpx.Response:
        if "follow_redirects" in kwargs:
            raise TypeError("http_client não segue redirects (proteção contra SSRF)")
        await assert_public_url(url, allow_http=allow_http)
        return await self._http().request(method, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                follow_redirects=False,
                transport=httpx.AsyncHTTPTransport(retries=2),
                headers={"User-Agent": "cv-frame"},
            )
        return self._client


http = HttpClient()
