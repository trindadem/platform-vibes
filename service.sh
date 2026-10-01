#!/usr/bin/env bash
# service.sh — scaffolder determinístico canônico do CV-Frame.
#
#   ./service.sh <nome-em-kebab-case>        ex.: ./service.sh billing | ./service.sh user-auth
#
# Um nome, quatro grafias derivadas (nenhuma é digitada à mão):
#   kebab   user-auth    pastas e arquivos, URL, subjects NATS, task queue, prefixo das activities
#   snake   user_auth    tabela SurrealDB
#   Pascal  UserAuth     classes Python
#   UPPER   USER_AUTH    códigos de erro
#
# Cada serviço roda de dentro da própria pasta (imports irmãos: from schemas import ...).
# Motivo: o sandbox do Temporal reimporta o workflow pelo nome do módulo, e "svc-x" com hífen
# não é importável como pacote. Bônus: nenhum "import" de outro serviço funciona (vira SyntaxError
# ou ModuleNotFoundError) — o acoplamento lateral quebra na hora, não em produção.
#
# Garantias: valida o nome; nunca sobrescreve; preserva um spec já escrito (spec-first);
# gera tudo numa área temporária, confere a sintaxe e só então publica (tudo ou nada).
# Roda no bash 3.2 do macOS.
set -euo pipefail
cd "$(dirname "$0")"

die() { echo "Erro: $*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "uso: ./service.sh <nome-em-kebab-case>   ex.: ./service.sh user-auth"
NAME="$1"
NAME_RE='^[a-z][a-z0-9]*(-[a-z0-9]+)*$'
[[ "$NAME" != svc-* ]] || die "não inclua o prefixo 'svc-'. Use: ./service.sh ${NAME#svc-}"
if ! [[ "$NAME" =~ $NAME_RE ]] || (( ${#NAME} > 40 )); then
  die "nome inválido '$NAME'. Use kebab-case minúsculo (a-z, 0-9, hífen), até 40 caracteres."
fi

SNAKE="$(printf '%s' "$NAME" | tr '-' '_')"
UPPER="$(printf '%s' "$SNAKE" | tr '[:lower:]' '[:upper:]')"
PASCAL="$(printf '%s' "$NAME" | awk -F- '{ for (i = 1; i <= NF; i++) printf "%s%s", toupper(substr($i, 1, 1)), substr($i, 2) }')"

SVC_DIR="services/svc-${NAME}"
SPEC_FILE="specs/${NAME}.md"
ENDPOINT_FILE="gateway/endpoints/${NAME}.yaml"
TEST_FILE="tests/${NAME}.py"

# 1. Idempotência: nada é tocado se o serviço, a rota ou o teste já existirem.
for target in "$SVC_DIR" "$ENDPOINT_FILE" "$TEST_FILE"; do
  if [[ -e "$target" ]]; then die "'$target' já existe. Nada foi alterado."; fi
done
KEEP_SPEC=0
if [[ -f "$SPEC_FILE" ]]; then KEEP_SPEC=1; fi

# 2. Gera tudo numa área temporária no mesmo disco (a publicação vira um rename).
STAGE="$(mktemp -d .scaffold.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/svc"

render() {  # render <destino>  — template via stdin, placeholders __NAME__ __SNAKE__ __PASCAL__ __UPPER__
  sed -e "s/__NAME__/${NAME}/g" -e "s/__SNAKE__/${SNAKE}/g" \
      -e "s/__PASCAL__/${PASCAL}/g" -e "s/__UPPER__/${UPPER}/g" > "$1"
}

render "$STAGE/spec.md" <<'EOF'
# Spec: __NAME__

## 1. Objetivo Operacional
TODO: em 2 a 3 linhas, a dor que este serviço resolve e o resultado de negócio esperado.

## 2. Contrato de Entrada e Saída
- Request (schemas.ExecutionInput): { client_id: str, payload: {...} }
- Response (schemas.ExecutionResult, dentro do envelope): { task_id: str, status: str, data: {...} }

## 3. Fluxo de Execução
1. Persistência SurrealDB — tabela: __SNAKE___records
2. Evento NATS — subject: events.__NAME__.processed (payload: ExecutionResult)
3. Temporal — __PASCAL__Workflow → activity __NAME__.process_task (timeout 5 min, 3 tentativas)

## 4. Casos de Borda e Erros Mapeados
- ERRO___UPPER___INVALID_PAYLOAD: payload inconsistente (HTTP 422).
- ERRO___UPPER___EXECUTION_FAILED: falha na orquestração (HTTP 500).
EOF

render "$STAGE/svc/schemas.py" <<'EOF'
"""svc-__NAME__ · contratos (DTOs, enums, constantes). Fonte da verdade: specs/__NAME__.md §2"""
from typing import Any

from pydantic import BaseModel, Field

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-__NAME__"
TASK_QUEUE = "__NAME__-queue"
TRIGGER_SUBJECT = "events.__NAME__.trigger"
PROCESSED_SUBJECT = "events.__NAME__.processed"
TABLE = "__SNAKE___records"


class ExecutionInput(BaseModel):
    client_id: str = Field(..., description="ID do cliente ou da célula")
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    task_id: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
EOF

render "$STAGE/svc/service.py" <<'EOF'
"""svc-__NAME__ · lógica de negócio pura. Fonte da verdade: specs/__NAME__.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "__NAME__.<método>".
Helpers começam com _ e nunca viram activities.
"""
from core.nats_bus import bus
from core.surreal import db
from core.temporal_runner import activities

from schemas import PROCESSED_SUBJECT, TABLE, ExecutionInput, ExecutionResult


@activities("__NAME__")
class __PASCAL__Service:
    async def process_task(self, data: ExecutionInput) -> ExecutionResult:
        record = await db.create(TABLE, data.model_dump())
        result = ExecutionResult(task_id=str(record["id"]), status="SUCCESS", data=record)
        await bus.publish(PROCESSED_SUBJECT, result)
        return result
EOF

render "$STAGE/svc/workflows.py" <<'EOF'
"""svc-__NAME__ · orquestração durável. Fonte da verdade: specs/__NAME__.md §3

As activities já existem: cada método público de __PASCAL__Service é registrado sozinho
(core/temporal_runner.py). Aqui só se encadeiam chamadas, referenciando o método real.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from schemas import ExecutionInput, ExecutionResult
    from service import __PASCAL__Service


@workflow.defn
class __PASCAL__Workflow:
    @workflow.run
    async def run(self, data: ExecutionInput) -> ExecutionResult:
        return await workflow.execute_activity_method(
            __PASCAL__Service.process_task,
            data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
EOF

render "$STAGE/svc/main.py" <<'EOF'
"""svc-__NAME__ · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/__NAME__.md

HTTP POST /execute  → chamada direta ao service (síncrona).
NATS TRIGGER_SUBJECT → inicia __PASCAL__Workflow (assíncrona e durável).

Rodar (da raiz): python -m uvicorn --app-dir services/svc-__NAME__ main:app
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.temporal_runner import runner

from schemas import SERVICE, TASK_QUEUE, TRIGGER_SUBJECT, ExecutionInput
from service import __PASCAL__Service
from workflows import __PASCAL__Workflow

svc = __PASCAL__Service()


async def on_trigger(data: ExecutionInput) -> None:
    await runner.start_workflow(__PASCAL__Workflow.run, data, task_queue=TASK_QUEUE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with bus.connected(), runner.worker(TASK_QUEUE, workflows=[__PASCAL__Workflow], service=svc):
        await bus.subscribe(TRIGGER_SUBJECT, on_trigger, model=ExecutionInput)
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)


@app.post("/execute", response_model=ResponseEnvelope)
async def execute(data: ExecutionInput) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=await svc.process_task(data), service=SERVICE)
EOF

render "$STAGE/endpoint.yaml" <<'EOF'
# svc-__NAME__ · rotas públicas no Gateway. Fonte da verdade: specs/__NAME__.md §2
service: __NAME__
base_path: /api/v1/__NAME__

endpoints:
  - path: /execute
    method: POST
    auth: client_jwt
    target_type: http
    target_url: http://svc-__NAME__:8000/execute
    timeout: 30

  - path: /trigger
    method: POST
    auth: client_jwt
    target_type: nats
    nats_subject: events.__NAME__.trigger
EOF

render "$STAGE/test.py" <<'EOF'
"""svc-__NAME__ · testes sem infraestrutura. Fonte da verdade: specs/__NAME__.md §2 e §4

Rodar (da raiz): PYTHONPATH=services/svc-__NAME__ python -m pytest tests/__NAME__.py
"""
import asyncio

import pytest
from pydantic import ValidationError

import service
from schemas import PROCESSED_SUBJECT, ExecutionInput, ExecutionResult


@pytest.fixture
def published(monkeypatch):
    """Troca SurrealDB e NATS por dublês em memória e devolve os eventos publicados."""
    events = []

    async def create(table, data):
        return {"id": f"{table}:1", **data}

    async def publish(subject, message):
        events.append((subject, message))

    monkeypatch.setattr(service.db, "create", create)
    monkeypatch.setattr(service.bus, "publish", publish)
    return events


def test_process_task(published):
    result = asyncio.run(service.__PASCAL__Service().process_task(ExecutionInput(client_id="c1")))
    assert isinstance(result, ExecutionResult) and result.status == "SUCCESS"
    assert [subject for subject, _ in published] == [PROCESSED_SUBJECT]


def test_payload_sem_client_id_e_rejeitado():
    with pytest.raises(ValidationError):
        ExecutionInput.model_validate({"payload": {}})
EOF

# 3. Autoverificação: nenhum placeholder sobrando e Python sintaticamente válido.
if grep -rl '__[A-Z][A-Z_]*__' "$STAGE" >/dev/null; then
  die "placeholder não substituído (bug do próprio service.sh)."
fi
if command -v python3 >/dev/null; then
  python3 - "$STAGE"/svc/*.py "$STAGE/test.py" <<'PY' || die "template gerou Python inválido (bug do próprio service.sh)."
import ast, sys
for path in sys.argv[1:]:
    ast.parse(open(path, encoding="utf-8").read(), path)
PY
fi

# 4. Publica. Se um rename falhar no meio, desfaz o que já foi movido.
mkdir -p services specs gateway/endpoints tests
publish() {
  mv "$STAGE/svc" "$SVC_DIR" || return 1
  mv "$STAGE/endpoint.yaml" "$ENDPOINT_FILE" || { rm -rf "$SVC_DIR"; return 1; }
  mv "$STAGE/test.py" "$TEST_FILE" || { rm -rf "$SVC_DIR" "$ENDPOINT_FILE"; return 1; }
  if [[ $KEEP_SPEC -eq 0 ]]; then
    mv "$STAGE/spec.md" "$SPEC_FILE" || { rm -rf "$SVC_DIR" "$ENDPOINT_FILE" "$TEST_FILE"; return 1; }
  fi
}
publish || die "falha ao publicar; nada foi mantido."

if [[ $KEEP_SPEC -eq 1 ]]; then SPEC_STATUS="preservado"; else SPEC_STATUS="novo"; fi
cat <<EOF
==> svc-${NAME} provisionado.
    ${SPEC_FILE}  (${SPEC_STATUS})
    ${SVC_DIR}/{schemas,service,workflows,main}.py
    ${ENDPOINT_FILE}
    ${TEST_FILE}

Próximo passo: preencha ${SPEC_FILE} e peça à IA:
  "Implemente specs/${NAME}.md em ${SVC_DIR}/ seguindo o README."
Testes: PYTHONPATH=${SVC_DIR} python -m pytest ${TEST_FILE}
EOF
