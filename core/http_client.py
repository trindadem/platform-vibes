"""HTTP para chamadas EXTERNAS (APIs de terceiros), com as proteções que costumam ser esquecidas.

- Bloqueia SSRF: só https e só hosts com IP público (security.assert_public_url). Nada de
  169.254.169.254, localhost ou rede interna. http:// exige allow_http=True explícito; rede interna exige
  allow_private=True e só vale com ENVIRONMENT=development (receptor de teste local).
- Não segue redirects: um redirect poderia levar para a rede interna depois da checagem.
- Sempre com timeout (5 s para conectar, 30 s para ler/escrever) e 2 novas tentativas só em falha de conexão.
- max_bytes= para o corpo no meio da leitura quando passa do tamanho (ex.: ler o site de alguém): 422
  ERRO_HTTP_TOO_LARGE, sem guardar o resto na memória.
- Nunca guarda cookies: o client é um só por processo e atende todas as organizações; cookie recebido numa
  chamada não volta na próxima (quem precisa de cookie o passa explicitamente na chamada).
Serviços internos não usam este client: serviços conversam por NATS ou pelo Gateway.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from core.envelope import ServiceError
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

    async def request(
        self,
        method: str,
        url: str,
        *,
        allow_http: bool = False,
        allow_private: bool = False,
        max_bytes: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        if "follow_redirects" in kwargs:
            raise TypeError("http_client não segue redirects (proteção contra SSRF)")
        await assert_public_url(url, allow_http=allow_http, allow_private=allow_private)
        if max_bytes is None:
            return await self._http().request(method, url, **kwargs)
        async with self._http().stream(method, url, **kwargs) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ServiceError("ERRO_HTTP_TOO_LARGE", "A resposta passou do tamanho permitido.", status=422)
        return httpx.Response(response.status_code, headers=response.headers, content=bytes(body), request=response.request)

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
                cookies=no_cookie_jar(),
            )
        return self._client


def no_cookie_jar() -> CookieJar:
    """Pote de cookies que recusa tudo: o Set-Cookie continua visível na resposta, mas nunca é reenviado."""
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


http = HttpClient()
