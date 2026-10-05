"""svc-integracoes · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/integracoes.md

HTTP /conexoes...        → conexões da organização (caixa de entrada; banco, pelo gateway escolhido).
HTTP /gateways...        → os gateways que a Cogniventure contrata (credencial cifrada, custo por operação); o simulado.
HTTP /documentos...      → documentos recebidos e o link para abrir cada um.
HTTP /pagamentos...      → pagamentos agendados no banco; confirmar à mão.
HTTP /cobrancas...       → cobranças (boletos) emitidas no banco; confirmar o recebimento à mão.
HTTP /enviados           → os e-mails que saíram da caixa de entrada (propostas, cobranças, pedidos).
HTTP /servidores...      → servidores MCP da organização (ferramentas para os agentes); /catalogo, o que dá para conectar.
HTTP /documentos/upload e /documentos/enviar → documento enviado pela tela (vira documento recebido, como o e-mail).
HTTP POST /entrada/mailpit → só na rede interna, no ambiente local: o Mailpit avisa que chegou um e-mail (spec §2).
HTTP POST /entrada/postmark → produção, pelo gateway (rota pública com Basic auth): o Postmark avisa que chegou um e-mail.
NATS rpc.integracoes.documento e rpc.integracoes.banco_agendar → texto do documento (agentes) e agendamento (ações).
NATS rpc.integracoes.ferramentas e rpc.integracoes.mcp_chamar → ferramentas MCP e a chamada com a credencial (svc-agentes).
NATS rpc.integracoes.enviar_email, banco_cobrar e banco_extrato → e-mail, cobrança e extrato para as ações dos pacotes.

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-integracoes main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query, Request
from pydantic import ValidationError

from core.envelope import ResponseEnvelope, ServiceError, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.security import install_security
from core.storage import storage
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import (
    ENCERRADA_SUBJECT,
    ContaEncerrada,
    AGENDAR_SUBJECT,
    COBRAR_SUBJECT,
    DOCUMENTO_SUBJECT,
    EMAIL_SUBJECT,
    EXTRATO_SUBJECT,
    FERRAMENTAS_SUBJECT,
    MCP_SUBJECT,
    MODULE,
    POSTMARK_MAX_BYTES,
    SEARCH,
    SERVICE,
    TABLES,
    TASK_QUEUE,
    UNIQUE,
    AgendarPagamento,
    AvisoEmail,
    AvisoPostmark,
    ChamadaMcp,
    CobrancaQuery,
    CobrancaRef,
    CobrarNoBanco,
    ConexaoRef,
    DocumentoQuery,
    DocumentoRef,
    EdicaoGateway,
    Empty,
    EnviadoQuery,
    EnviarDocumento,
    EnviarEmail,
    ExtratoPedido,
    GatewayRef,
    NovaConexao,
    NovoGateway,
    NovoServidorMcp,
    PagamentoQuery,
    PagamentoRef,
    ServidorRef,
    UploadRequest,
)
from service import MIGRATIONS, IntegracoesService, _aead, autorizado_postmark, settings
from workflows import SCHEDULES, CobrancaSimuladaWorkflow, LeituraDocumentoWorkflow, PagamentoSimuladoWorkflow

svc = IntegracoesService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _aead()  # sem INTEGRACOES_SECRETS_KEY válida o serviço não sobe (as credenciais MCP ficariam sem cifra)
    async with (
        bus.connected(SERVICE),
        db.connected(tables=TABLES, unique=UNIQUE, search=SEARCH, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[PagamentoSimuladoWorkflow, CobrancaSimuladaWorkflow, LeituraDocumentoWorkflow],
                      service=svc, schedules=SCHEDULES),
    ):
        await storage.connected(SERVICE)  # os documentos recebidos (README §5.14)
        await bus.respond(DOCUMENTO_SUBJECT, svc.documento_texto, model=DocumentoRef)  # agentes dos processos
        await bus.subscribe(ENCERRADA_SUBJECT, svc.encerrada, model=ContaEncerrada)  # svc-plans: a conta encerrou
        await bus.respond(AGENDAR_SUBJECT, svc.agendar_pagamento, model=AgendarPagamento)  # ação do svc-financeiro
        await bus.respond(FERRAMENTAS_SUBJECT, svc.ferramentas, model=Empty)  # catálogo de ferramentas dos agentes
        await bus.respond(MCP_SUBJECT, svc.chamar_mcp, model=ChamadaMcp)  # a credencial não sai deste serviço
        await bus.respond(EMAIL_SUBJECT, svc.enviar_email, model=EnviarEmail)  # ações dos pacotes (propostas, cobranças...)
        await bus.respond(COBRAR_SUBJECT, svc.cobrar, model=CobrarNoBanco)  # ação do svc-financeiro
        await bus.respond(EXTRATO_SUBJECT, svc.extrato, model=ExtratoPedido)  # conciliação e baixa do svc-financeiro
        await plans.declare(MODULE)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
# spec §2: aviso do Mailpit (só na rede interna) e do Postmark (pelo gateway, com a senha conferida na rota)
install_security(app, service=SERVICE, public=("/entrada/mailpit", "/entrada/postmark"))
install_telemetry(app, service=SERVICE)


def _ok(data: object) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=data, service=SERVICE)


@app.get("/conexoes", response_model=ResponseEnvelope)
async def conexoes() -> ResponseEnvelope:
    return _ok(await svc.conexoes(Empty()))


@app.post("/conexoes", response_model=ResponseEnvelope)
async def conectar(data: NovaConexao) -> ResponseEnvelope:
    return _ok(await svc.conectar(data))


@app.post("/conexoes/remover", response_model=ResponseEnvelope)
async def desconectar(data: ConexaoRef) -> ResponseEnvelope:
    return _ok(await svc.desconectar(data))


@app.get("/resumo", response_model=ResponseEnvelope)
async def resumo() -> ResponseEnvelope:
    return _ok(await svc.resumo(Empty()))


@app.get("/documentos", response_model=ResponseEnvelope)
async def documentos(data: Annotated[DocumentoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.documentos(data))


@app.get("/documentos/arquivo", response_model=ResponseEnvelope)
async def arquivo(data: Annotated[DocumentoRef, Query()]) -> ResponseEnvelope:
    return _ok(await svc.arquivo(data))


@app.get("/pagamentos", response_model=ResponseEnvelope)
async def pagamentos(data: Annotated[PagamentoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.pagamentos(data))


@app.post("/pagamentos/confirmar", response_model=ResponseEnvelope)
async def confirmar(data: PagamentoRef) -> ResponseEnvelope:
    return _ok(await svc.confirmar_pagamento(data))


@app.post("/entrada/mailpit", response_model=ResponseEnvelope)
async def mailpit(data: AvisoEmail) -> ResponseEnvelope:
    return _ok(await svc.receber_email(data))


@app.post("/entrada/postmark", response_model=ResponseEnvelope)
async def postmark(request: Request) -> ResponseEnvelope:
    """A senha antes do corpo: um aviso sem ela não chega a ser lido (até 40 MB)."""
    if not settings.postmark_entrada:
        raise ServiceError("ERRO_INTEGRACOES_SEM_PROVEDOR", "Nenhum provedor de e-mail configurado.", 404)
    if not autorizado_postmark(request.headers.get("authorization")):
        raise ServiceError("ERRO_INTEGRACOES_NAO_AUTORIZADO", "Aviso de e-mail sem a senha certa.", 401)
    corpo = bytearray()
    async for pedaco in request.stream():
        corpo += pedaco
        if len(corpo) > POSTMARK_MAX_BYTES:
            raise ServiceError("ERRO_INTEGRACOES_EMAIL", "Mensagem grande demais.", 413)
    try:
        aviso = AvisoPostmark.model_validate_json(bytes(corpo))
    except ValidationError:
        raise ServiceError("ERRO_INTEGRACOES_EMAIL", "Aviso de e-mail fora do formato do Postmark.", 422) from None
    return _ok(await svc.receber_postmark(aviso))


@app.post("/documentos/upload", response_model=ResponseEnvelope)
async def documento_upload(data: UploadRequest) -> ResponseEnvelope:
    return _ok(await svc.documento_upload(data))


@app.post("/documentos/enviar", response_model=ResponseEnvelope)
async def enviar_documento(data: EnviarDocumento) -> ResponseEnvelope:
    return _ok(await svc.enviar_documento(data))


@app.get("/catalogo", response_model=ResponseEnvelope)
async def catalogo() -> ResponseEnvelope:
    return _ok(await svc.catalogo(Empty()))


@app.get("/gateways", response_model=ResponseEnvelope)
async def gateways() -> ResponseEnvelope:
    return _ok(await svc.gateways(Empty()))


@app.post("/gateways", response_model=ResponseEnvelope)
async def criar_gateway(data: NovoGateway) -> ResponseEnvelope:
    return _ok(await svc.criar_gateway(data))


@app.post("/gateways/editar", response_model=ResponseEnvelope)
async def editar_gateway(data: EdicaoGateway) -> ResponseEnvelope:
    return _ok(await svc.editar_gateway(data))


@app.post("/gateways/remover", response_model=ResponseEnvelope)
async def remover_gateway(data: GatewayRef) -> ResponseEnvelope:
    return _ok(await svc.remover_gateway(data))


@app.get("/servidores", response_model=ResponseEnvelope)
async def servidores() -> ResponseEnvelope:
    return _ok(await svc.servidores(Empty()))


@app.post("/servidores", response_model=ResponseEnvelope)
async def conectar_mcp(data: NovoServidorMcp) -> ResponseEnvelope:
    return _ok(await svc.conectar_mcp(data))


@app.post("/servidores/atualizar", response_model=ResponseEnvelope)
async def atualizar_mcp(data: ServidorRef) -> ResponseEnvelope:
    return _ok(await svc.atualizar_mcp(data))


@app.post("/servidores/remover", response_model=ResponseEnvelope)
async def remover_mcp(data: ServidorRef) -> ResponseEnvelope:
    return _ok(await svc.remover_mcp(data))


@app.get("/cobrancas", response_model=ResponseEnvelope)
async def cobrancas(data: Annotated[CobrancaQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.cobrancas(data))


@app.post("/cobrancas/confirmar", response_model=ResponseEnvelope)
async def confirmar_cobranca(data: CobrancaRef) -> ResponseEnvelope:
    return _ok(await svc.confirmar_cobranca(data))


@app.get("/enviados", response_model=ResponseEnvelope)
async def enviados(data: Annotated[EnviadoQuery, Query()]) -> ResponseEnvelope:
    return _ok(await svc.enviados(data))
