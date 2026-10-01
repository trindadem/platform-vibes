"""Gateway · lê os manifestos YAML, monta as rotas e despacha para HTTP ou NATS. Fonte da verdade: README §5.8

Nenhuma rota de negócio é escrita aqui: cada rota nasce de gateway/endpoints/<service_name>.yaml.
- HTTP: repassa corpo, query e cabeçalhos permitidos ao serviço; o token segue junto e o serviço verifica de novo.
- NATS: publica o corpo (objeto JSON) e responde 202 com o message_id. Quem chamou viaja no cabeçalho da mensagem
  (core.nats_bus). O cabeçalho Idempotency-Key faz a mesma requisição repetida virar a mesma mensagem (e o mesmo
  workflow); a chave é isolada por organização e usuário.
Corpo acima de 1 MiB é recusado antes de chegar ao serviço.
"""
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import RootModel, ValidationError

from core.envelope import ResponseEnvelope, ServiceError
from core.nats_bus import bus
from core.security import require

from schemas import Endpoint, Manifest

ENDPOINTS_DIR = Path(__file__).parent / "endpoints"
MAX_BODY_BYTES = 1_048_576
FORWARDED_HEADERS = ("authorization", "content-type", "accept", "x-request-id")
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


def public_paths(manifests: list[Manifest]) -> set[str]:
    return {m.base_path + ep.path for m in manifests for ep in m.endpoints if ep.auth == "public"}


def mount(app: FastAPI, manifests: list[Manifest], upstream: httpx.AsyncClient) -> None:
    for manifest in manifests:
        for ep in manifest.endpoints:
            handler = _forward(ep, upstream) if ep.target_type == "http" else _publish(ep)
            app.add_api_route(
                manifest.base_path + ep.path,
                handler,
                methods=[ep.method],
                dependencies=[Depends(require(*ep.roles))] if ep.roles else [],
                name=f"{manifest.service} {ep.method} {ep.path}",
            )


def _forward(ep: Endpoint, upstream: httpx.AsyncClient):
    async def forward(request: Request) -> Response:
        body = await _read_body(request)
        url = ep.target_url.format_map({k: quote(str(v), safe="") for k, v in request.path_params.items()})
        headers = {k: v for k, v in request.headers.items() if k in FORWARDED_HEADERS}
        headers.setdefault("x-request-id", uuid.uuid4().hex)
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
        return Response(reply.content, status_code=reply.status_code, media_type=reply.headers.get("content-type"))

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
