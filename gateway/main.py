"""Gateway · entrada única HTTP: verifica o token, aplica os manifestos e despacha. Fonte da verdade: README §5.8

Manifesto inválido ou configuração de segurança ausente impedem o boot.
Rodar (da raiz): uv run python -m uvicorn --app-dir gateway main:app --port 8090 --env-file .env
"""
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from core.envelope import install_envelope
from core.http_client import no_cookie_jar
from core.nats_bus import bus
from core.security import install_security
from core.telemetry import install_telemetry

from interpreter import installed, load_manifests, mount, mount_live, public_paths
from schemas import Manifest

SERVICE = "gateway"


def create_app(manifests: list[Manifest], upstream: httpx.AsyncClient) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with bus.connected(SERVICE), upstream:
            yield

    app = FastAPI(title=SERVICE, lifespan=lifespan)
    install_envelope(app, service=SERVICE)
    install_security(app, service=SERVICE, public=public_paths(manifests))
    # edge: cada requisição de fora começa um trace (traceparent de fora não entra); /health diz também as rotas.
    install_telemetry(app, service=SERVICE, edge=True, health=lambda: {"routes": sum(len(m.all_endpoints()) for m in manifests)})
    mount(app, manifests, upstream)
    mount_live(app)
    return app


# Só os manifestos da plataforma e dos módulos instalados (MODULES, README §9). O upstream só fala com os serviços
# declarados nos manifestos (validados em schemas.py) e nunca guarda cookie:
# um Set-Cookie devolvido a um usuário não pode voltar na requisição de outro.
app = create_app(installed(load_manifests()), httpx.AsyncClient(follow_redirects=False, cookies=no_cookie_jar()))
