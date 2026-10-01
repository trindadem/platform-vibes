"""Gateway · lê os manifestos YAML, monta as rotas e despacha para HTTP ou NATS. Fonte da verdade: README §5.8

Nenhuma rota de negócio é escrita aqui: cada rota nasce de gateway/endpoints/<service_name>.yaml.
- HTTP: repassa corpo, query e cabeçalhos permitidos ao serviço; o token segue junto e o serviço verifica de novo.
  Cookie só nas rotas com cookies: true, que também devolvem o Set-Cookie do serviço; nas outras, nunca passa.
- NATS: publica o corpo (objeto JSON) e responde 202 com o message_id. Quem chamou viaja no cabeçalho da mensagem
  (core.nats_bus). O cabeçalho Idempotency-Key faz a mesma requisição repetida virar a mesma mensagem (e o mesmo
  workflow); a chave é isolada por organização e usuário.
- stream: true: repassa a resposta em pedaços (SSE), com tempo limite entre pedaços, nunca juntando tudo.
- GET /api/v1/live: conexão ao vivo (SSE) com os eventos da organização do token e da própria pessoa
  (core.nats_bus.live_feed). Fecha quando o token expira; o cliente reabre com o token novo.
Corpo acima de 1 MiB é recusado antes de chegar ao serviço.
O trace começa aqui (core/telemetry.py, edge): o traceparent de fora é ignorado e o do gateway segue para o serviço.
"""
import asyncio
import hashlib
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import propagate
from pydantic import RootModel, ValidationError

from core.envelope import HEARTBEAT_SECONDS, SSE_HEADERS, ResponseEnvelope, ServiceError, sse
from core.nats_bus import bus
from core.security import Principal, principal, require

from schemas import Endpoint, Manifest

ENDPOINTS_DIR = Path(__file__).parent / "endpoints"
MAX_BODY_BYTES = 1_048_576
FORWARDED_HEADERS = ("authorization", "content-type", "accept", "x-request-id")
LIVE_PATH = "/api/v1/live"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class _JsonObject(RootModel[dict[str, Any]]):
    pass


def load_manifests(directory: Path = ENDPOINTS_DIR) -> list[Manifest]:
    manifests = []
    for file in sorted(directory.glob("*.yaml")):
        try:
            manifest = Manifest.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")))
        except (yaml.YAMLError, ValidationError) as exc:
            raise RuntimeError(f"gateway: manifesto inválido {file.name} (README §5.8)\n{exc}") from None
        if file.stem != manifest.service:
            raise RuntimeError(f"gateway: {file.name} declara service {manifest.service!r}; renomeie para {manifest.service}.yaml")
        manifests.append(manifest)
    return manifests


# Serviços da plataforma: sempre instalados. Os demais são módulos de negócio, publicados se estiverem em MODULES.
PLATFORM_SERVICES = frozenset({"identity", "notify", "plans", "ai", "webhooks"})


def installed(manifests: list[Manifest], modules: str | None = None) -> list[Manifest]:
    """Os manifestos que o gateway publica: os da plataforma e os dos módulos em MODULES (vazio: todos). Instalação
    dedicada de um cliente (README §9): só as rotas dos módulos dele existem."""
    chosen = {m.strip() for m in (modules if modules is not None else os.environ.get("MODULES", "")).split(",") if m.strip()}
    return [m for m in manifests if not chosen or m.service in chosen or m.service in PLATFORM_SERVICES]


def public_paths(manifests: list[Manifest]) -> set[str]:
    return {m.base_path + ep.path for m in manifests for ep in m.all_endpoints() if ep.auth == "public"}


def mount(app: FastAPI, manifests: list[Manifest], upstream: httpx.AsyncClient) -> None:
    for manifest in manifests:
        for ep in manifest.all_endpoints():
            if ep.target_type == "nats":
                handler = _publish(ep)
            else:
                handler = _forward_stream(ep, upstream) if ep.stream else _forward(ep, upstream)
            app.add_api_route(
                manifest.base_path + ep.path,
                handler,
                methods=[ep.method],
                dependencies=[Depends(require(*ep.roles))] if ep.roles else [],
                name=f"{manifest.service} {ep.method} {ep.path}",
            )


def mount_live(app: FastAPI) -> None:
    """GET /api/v1/live: eventos ao vivo de quem chama, só da sua organização e para si."""

    async def live(who: Principal = Depends(principal)) -> StreamingResponse:
        if not who.tenant:
            raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", status=403)
        expires_at = who.expires_at or time.time() + 3600

        async def events():
            async with bus.live_feed(who) as queue:
                yield b": conectado\n\n"
                while (remaining := expires_at - time.time()) > 0:
                    try:
                        topic, data = await asyncio.wait_for(queue.get(), timeout=min(HEARTBEAT_SECONDS, remaining))
                    except TimeoutError:
                        yield b": ping\n\n"
                        continue
                    yield sse(topic, data.decode())
                yield sse("expired", "{}")  # token venceu: o cliente reabre com o token renovado

        return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

    app.add_api_route(LIVE_PATH, live, methods=["GET"], name="gateway live")


def _upstream_request(ep: Endpoint, request: Request, body: bytes) -> tuple[str, dict[str, str]]:
    url = ep.target_url.format_map({k: quote(str(v), safe="") for k, v in request.path_params.items()})
    allowed = FORWARDED_HEADERS + (("cookie",) if ep.cookies else ()) + ep.headers  # headers: declarados no manifesto
    headers = {k: v for k, v in request.headers.items() if k in allowed}
    headers.setdefault("x-request-id", uuid.uuid4().hex)
    propagate.inject(headers)  # o serviço continua o trace que começou aqui (README §5.18)
    return url, headers


def _forward_stream(ep: Endpoint, upstream: httpx.AsyncClient):
    async def forward(request: Request) -> Response:
        url, headers = _upstream_request(ep, request, body := await _read_body(request))
        outgoing = upstream.build_request(
            request.method, url, content=body, params=request.query_params.multi_items(), headers=headers,
            timeout=ep.timeout,  # vale entre um pedaço e outro, não para a resposta inteira
        )
        try:
            reply = await upstream.send(outgoing, stream=True)
        except httpx.TimeoutException:
            raise ServiceError("ERRO_GATEWAY_TIMEOUT", "O serviço não respondeu a tempo.", status=504) from None
        except httpx.TransportError:
            raise ServiceError("ERRO_GATEWAY_UNAVAILABLE", "Serviço indisponível.", status=502) from None
        if not reply.headers.get("content-type", "").startswith("text/event-stream"):
            content = await reply.aread()  # erro antes de começar (401, 422...): sai no envelope de sempre
            await reply.aclose()
            return Response(content, status_code=reply.status_code, media_type=reply.headers.get("content-type"))

        async def chunks():
            try:
                async for chunk in reply.aiter_raw():
                    yield chunk
            except httpx.TimeoutException:
                failure = ResponseEnvelope.failure("ERRO_GATEWAY_TIMEOUT", "O serviço parou de responder.", "gateway", 504)
                yield sse("error", failure.model_dump_json())
            finally:
                await reply.aclose()

        return StreamingResponse(chunks(), status_code=reply.status_code, media_type="text/event-stream", headers=SSE_HEADERS)

    return forward


def _forward(ep: Endpoint, upstream: httpx.AsyncClient):
    async def forward(request: Request) -> Response:
        body = await _read_body(request)
        url, headers = _upstream_request(ep, request, body)
        try:
            reply = await upstream.request(
                request.method,
                url,
                content=body,
                params=request.query_params.multi_items(),
                headers=headers,
                timeout=ep.timeout,
            )
        except httpx.TimeoutException:
            raise ServiceError("ERRO_GATEWAY_TIMEOUT", "O serviço não respondeu a tempo.", status=504) from None
        except httpx.TransportError:
            raise ServiceError("ERRO_GATEWAY_UNAVAILABLE", "Serviço indisponível.", status=502) from None
        response = Response(reply.content, status_code=reply.status_code, media_type=reply.headers.get("content-type"))
        if ep.cookies:
            for cookie in reply.headers.get_list("set-cookie"):
                response.headers.append("set-cookie", cookie)
        return response

    return forward


def _publish(ep: Endpoint):
    async def publish(request: Request) -> JSONResponse:
        try:
            payload = _JsonObject.model_validate_json(await _read_body(request))
        except ValidationError:
            raise ServiceError("ERRO_GATEWAY_INVALID_PAYLOAD", "O corpo deve ser um objeto JSON.", status=422) from None
        message_id = _message_id(request)
        await bus.publish(ep.nats_subject, payload, msg_id=message_id)
        body = ResponseEnvelope.success({"message_id": message_id}, "gateway")
        return JSONResponse(body.model_dump(mode="json"), status_code=202)

    return publish


def _message_id(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if key is None:
        return uuid.uuid4().hex
    if not _IDEMPOTENCY_KEY.match(key):
        raise ServiceError("ERRO_GATEWAY_INVALID_IDEMPOTENCY_KEY", "Idempotency-Key: até 128 caracteres A-Z, a-z, 0-9, _ e -.", status=422)
    principal = getattr(request.state, "principal", None)
    owner = f"{principal.tenant or '-'}\n{principal.sub}" if principal else "anonymous"
    # Isolado por organização e usuário: a chave "1" de um nunca colide com a chave "1" de outro.
    return hashlib.sha256(f"{owner}\n{request.url.path}\n{key}".encode()).hexdigest()[:32]


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "0")
    if not declared.isdigit() or int(declared) > MAX_BODY_BYTES:
        raise ServiceError("ERRO_GATEWAY_PAYLOAD_TOO_LARGE", "Corpo acima de 1 MiB.", status=413)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise ServiceError("ERRO_GATEWAY_PAYLOAD_TOO_LARGE", "Corpo acima de 1 MiB.", status=413)
    return bytes(body)
