"""svc-identity · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/identity.md

HTTP: cadastro, login e sessão (rotas públicas em PUBLIC_PATHS, iguais às do gateway/endpoints/identity.yaml) e
conta, organizações, convites e membros (exigem token). O refresh vive só no cookie cv_refresh: entra pelo
cookie, sai pelo Set-Cookie e nunca aparece no corpo.
NATS TRIGGER_SUBJECT → inicia IdentityWorkflow (limpeza de sessões e convites vencidos).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-identity main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Cookie, FastAPI, Response
from fastapi.responses import JSONResponse

from core.envelope import ResponseEnvelope, ServiceError, error_response, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.security import install_security
from core.storage import storage
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner
from core.webhooks import webhooks

from schemas import (
    CLIENTE_SUBJECT,
    CONTACTS_SUBJECT,
    CONVITE_DONO_SUBJECT,
    COOKIE_PATH,
    MODULE,
    OPERADOR_SUBJECT,
    ORGANIZACOES_SUBJECT,
    PUBLIC_PATHS,
    REFRESH_COOKIE,
    SERVICE,
    SHARED_TABLES,
    TASK_QUEUE,
    TRIGGER_SUBJECT,
    UNIQUE,
    WEBHOOKS,
    ClienteNovo,
    ColorInput,
    ContactsRequest,
    ConviteDono,
    Empty,
    ForgotInput,
    InviteCode,
    InviteInput,
    JoinRequest,
    KeepRequest,
    LoginInput,
    MemberRef,
    OperadorAcesso,
    RefreshInput,
    ResetInput,
    Session,
    SignupInput,
    SwitchInput,
    SwitchRequest,
    TenantInput,
    TenantRequest,
    UploadRequest,
)
from service import IdentityService, settings
from workflows import SCHEDULES, IdentityWorkflow

svc = IdentityService()
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


async def on_trigger(data: Empty) -> None:
    # id = id estável da mensagem: reentrega do NATS nunca inicia um segundo workflow.
    await runner.start_workflow(IdentityWorkflow.run, data, task_queue=TASK_QUEUE, id=bus.message_id())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(shared=SHARED_TABLES, unique=UNIQUE),
        runner.worker(TASK_QUEUE, workflows=[IdentityWorkflow], service=svc, schedules=SCHEDULES),
    ):
        await storage.connected(SERVICE)  # logo da organização (README §5.14)
        await bus.subscribe(TRIGGER_SUBJECT, on_trigger, model=Empty)
        await bus.respond(CONTACTS_SUBJECT, svc.contacts, model=ContactsRequest)  # svc-notify: quem são as pessoas
        await bus.respond(OPERADOR_SUBJECT, svc.operador, model=OperadorAcesso)  # svc-staff: a carteira
        await bus.respond(ORGANIZACOES_SUBJECT, svc.organizacoes, model=Empty)  # svc-staff: as organizações clientes
        await bus.respond(CLIENTE_SUBJECT, svc.cliente, model=ClienteNovo)  # svc-staff: abre o cliente e convida o dono
        await bus.respond(CONVITE_DONO_SUBJECT, svc.convite_dono, model=ConviteDono)  # svc-staff: o convite de novo
        await webhooks.declare(WEBHOOKS)  # membro-entrou e membro-saiu no catálogo (README §5.16)
        await plans.declare(MODULE)  # o módulo, com pessoas por organização, no catálogo dos planos (README §5.17)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE, public=PUBLIC_PATHS)  # specs/identity.md §2 declara estas rotas públicas
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


def _session(response: Response, session: Session) -> ResponseEnvelope:
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=session.refresh_max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
    )
    return _ok(session.auth)


def _without_session(exc: ServiceError) -> JSONResponse:
    response = error_response(SERVICE, exc.status, exc.code, exc.message)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


# ── Públicas ────────────────────────────────────────────────────────────────

@app.post("/signup", response_model=ResponseEnvelope)
async def signup(data: SignupInput, response: Response) -> ResponseEnvelope:
    return _session(response, await svc.signup(data))


@app.post("/login", response_model=ResponseEnvelope)
async def login(data: LoginInput, response: Response) -> ResponseEnvelope:
    return _session(response, await svc.login(data))


@app.post("/refresh", response_model=ResponseEnvelope)
async def refresh(data: Empty, response: Response, refresh_token: RefreshCookie = None):
    try:
        return _session(response, await svc.refresh(RefreshInput(refresh_token=refresh_token)))
    except ServiceError as exc:
        return _without_session(exc)


@app.post("/logout", response_model=ResponseEnvelope)
async def logout(data: Empty, response: Response, refresh_token: RefreshCookie = None) -> ResponseEnvelope:
    result = await svc.logout(RefreshInput(refresh_token=refresh_token))
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return _ok(result)


@app.post("/invite-info", response_model=ResponseEnvelope)
async def invite_info(data: InviteCode) -> ResponseEnvelope:
    return _ok(await svc.invite_info(data))


@app.post("/password/forgot", response_model=ResponseEnvelope)
async def forgot_password(data: ForgotInput) -> ResponseEnvelope:
    return _ok(await svc.forgot_password(data))


@app.post("/password/reset", response_model=ResponseEnvelope)
async def reset_password(data: ResetInput) -> ResponseEnvelope:
    return _ok(await svc.reset_password(data))


# ── Com token ───────────────────────────────────────────────────────────────

@app.get("/me", response_model=ResponseEnvelope)
async def me() -> ResponseEnvelope:
    return _ok(await svc.me(Empty()))


@app.post("/switch", response_model=ResponseEnvelope)
async def switch(data: SwitchInput, response: Response, refresh_token: RefreshCookie = None) -> ResponseEnvelope:
    return _session(response, await svc.switch_tenant(SwitchRequest(tenant=data.tenant, refresh_token=refresh_token)))


@app.post("/tenants", response_model=ResponseEnvelope)
async def create_tenant(data: TenantInput, response: Response, refresh_token: RefreshCookie = None) -> ResponseEnvelope:
    return _session(response, await svc.create_tenant(TenantRequest(name=data.name, refresh_token=refresh_token)))


@app.post("/join", response_model=ResponseEnvelope)
async def join(data: InviteCode, response: Response, refresh_token: RefreshCookie = None) -> ResponseEnvelope:
    return _session(response, await svc.join(JoinRequest(code=data.code, refresh_token=refresh_token)))


@app.post("/invites", response_model=ResponseEnvelope)
async def create_invite(data: InviteInput) -> ResponseEnvelope:
    return _ok(await svc.create_invite(data))


@app.get("/members", response_model=ResponseEnvelope)
async def members() -> ResponseEnvelope:
    return _ok(await svc.list_members(Empty()))


@app.post("/members/remove", response_model=ResponseEnvelope)
async def remove_member(data: MemberRef) -> ResponseEnvelope:
    return _ok(await svc.remove_member(data))


@app.get("/organization", response_model=ResponseEnvelope)
async def organization() -> ResponseEnvelope:
    return _ok(await svc.organization(Empty()))


@app.post("/organization/logo/upload", response_model=ResponseEnvelope)
async def logo_upload(data: UploadRequest) -> ResponseEnvelope:
    return _ok(await svc.logo_upload(data))


@app.post("/organization/logo", response_model=ResponseEnvelope)
async def set_logo(data: KeepRequest) -> ResponseEnvelope:
    return _ok(await svc.set_logo(data))


@app.post("/organization/color", response_model=ResponseEnvelope)
async def set_color(data: ColorInput) -> ResponseEnvelope:
    return _ok(await svc.set_color(data))


@app.post("/organization/logo/remove", response_model=ResponseEnvelope)
async def remove_logo() -> ResponseEnvelope:
    return _ok(await svc.remove_logo(Empty()))
