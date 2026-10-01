"""Gateway · entrada única HTTP: verifica o token, aplica os manifestos e despacha. Fonte da verdade: README §5.8

Manifesto inválido ou configuração de segurança ausente impedem o boot.
Rodar (da raiz): python -m uvicorn --app-dir gateway main:app --port 8080 --env-file .env
"""
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.security import install_security

from interpreter import load_manifests, mount, public_paths
from schemas import Manifest

SERVICE = "gateway"


def create_app(manifests: list[Manifest], upstream: httpx.AsyncClient) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with bus.connected(SERVICE), upstream:
            yield

    app = FastAPI(title=SERVICE, lifespan=lifespan)
    install_envelope(app, service=SERVICE)
    install_security(app, service=SERVICE, public=public_paths(manifests) | {"/health"})
    mount(app, manifests, upstream)

    @app.get("/health")
    async def health() -> ResponseEnvelope:
        return ResponseEnvelope.success({"routes": sum(len(m.endpoints) for m in manifests)}, SERVICE)

    return app


# O upstream só fala com os serviços declarados nos manifestos (validados em schemas.py).
app = create_app(load_manifests(), httpx.AsyncClient(follow_redirects=False))
