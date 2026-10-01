#!/usr/bin/env bash
# service.sh — scaffolder determinístico canônico do CV-Frame.
#
#   ./service.sh <nome-em-kebab-case>        ex.: ./service.sh billing | ./service.sh user-auth
#
# Um nome, seis grafias derivadas (nenhuma é digitada à mão):
#   kebab   user-auth    pastas e arquivos, URL, subjects NATS, task queue, prefixo das activities, módulo
#   snake   user_auth    tabela SurrealDB
#   Pascal  UserAuth     classes Python e a tela
#   camel   userAuth     cliente do frontend (core/contracts.ts)
#   UPPER   USER_AUTH    códigos de erro
#   Título  User auth    nome do módulo no menu e no plano (troque à vontade no MODULE e no meta da tela)
#
# Cada serviço roda de dentro da própria pasta (imports irmãos: from schemas import ...).
# Motivo: o sandbox do Temporal reimporta o workflow pelo nome do módulo, e "svc-x" com hífen
# não é importável como pacote. Bônus: nenhum "import" de outro serviço funciona (vira SyntaxError
# ou ModuleNotFoundError) — o acoplamento lateral quebra na hora, não em produção.
#
# Todo serviço é um módulo (README §5.17): MODULE no schemas.py, declarado no boot, e a tela
# frontend/src/modules/<nome>/page.tsx, que entra no menu e some quando o plano não inclui o módulo.
# O serviço nasce com um cadastro declarado (Resource "registros", README §5.19): lista, criação, edição e remoção
# saem do core, e a tela é useResource + ResourceList.
#
# Garantias: valida o nome; nunca sobrescreve; preserva um spec ou uma tela já escritos (spec-first);
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
CAMEL="$(printf '%s' "$PASCAL" | awk '{ printf "%s%s", tolower(substr($0, 1, 1)), substr($0, 2) }')"
TITLE="$(printf '%s' "$NAME" | tr '-' ' ' | awk '{ printf "%s%s", toupper(substr($0, 1, 1)), substr($0, 2) }')"

SVC_DIR="services/svc-${NAME}"
SPEC_FILE="specs/${NAME}.md"
ENDPOINT_FILE="gateway/endpoints/${NAME}.yaml"
TEST_FILE="tests/${NAME}.py"
COMPOSE_FILE="compose.yaml"
PAGES_DIR="frontend/src/modules"
PAGE_FILE="${PAGES_DIR}/${NAME}/page.tsx"

# 1. Idempotência: nada é tocado se o serviço, a rota ou o teste já existirem.
for target in "$SVC_DIR" "$ENDPOINT_FILE" "$TEST_FILE"; do
  if [[ -e "$target" ]]; then die "'$target' já existe. Nada foi alterado."; fi
done
if [[ -f "$COMPOSE_FILE" ]] && grep -q "^  svc-${NAME}:$" "$COMPOSE_FILE"; then
  die "svc-${NAME} já está em ${COMPOSE_FILE}. Nada foi alterado."
fi
KEEP_SPEC=0
if [[ -f "$SPEC_FILE" ]]; then KEEP_SPEC=1; fi
# Tela: só onde há frontend; a que já existe é preservada (como o spec).
MAKE_PAGE=0
if [[ -d "$PAGES_DIR" && ! -e "$PAGES_DIR/$NAME" ]]; then MAKE_PAGE=1; fi

# 2. Gera tudo numa área temporária no mesmo disco (a publicação vira um rename).
STAGE="$(mktemp -d .scaffold.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/svc"

render() {  # render <destino>  — template via stdin, placeholders __NAME__ __SNAKE__ __PASCAL__ __CAMEL__ __UPPER__ __TITLE__
  sed -e "s/__NAME__/${NAME}/g" -e "s/__SNAKE__/${SNAKE}/g" -e "s/__PASCAL__/${PASCAL}/g" \
      -e "s/__CAMEL__/${CAMEL}/g" -e "s/__UPPER__/${UPPER}/g" -e "s/__TITLE__/${TITLE}/g" > "$1"
}

render "$STAGE/spec.md" <<'EOF'
# Spec: __NAME__

## 1. Objetivo Operacional
TODO: em 2 a 3 linhas, a dor que este serviço resolve e o resultado de negócio esperado.
Módulo (schemas.MODULE): "__TITLE__", categoria Geral, ligado por padrão; tela em /__NAME__.

## 2. Contrato de Entrada e Saída
- Cadastro registros (schemas.REGISTROS, README §5.19): Registro { title, notes? }. GET /registros (página, busca
  por palavras no title, ordem), GET /registros/item?id=, POST /registros, POST /registros/update e
  POST /registros/remove; ao vivo __NAME__.registros.
- POST /execute (schemas.ExecutionInput { title, payload }) → ExecutionResult { task_id, status, data }: cria um
  registro; POST /trigger faz o mesmo de forma durável (NATS + Temporal).
- Quem chama e a organização vêm do token (core.security.current_tenant()), nunca do corpo.

## 3. Fluxo de Execução
1. Persistência SurrealDB — cadastro por organização: __SNAKE___registros (o core grava, filtra o tenant e carimba)
2. Evento NATS — subject: events.__NAME__.processed (payload: ExecutionResult)
3. Temporal — __PASCAL__Workflow → activity __NAME__.process_task (timeout 5 min, 3 tentativas)
4. Ciclo de vida (README §5.13) — agendamentos (workflows.SCHEDULES) e migrações (service.MIGRATIONS): nenhum ainda.

## 4. Casos de Borda e Erros Mapeados
- ERRO_RECORD_NOT_FOUND (404): registro inexistente ou de outra organização.
- ERRO___UPPER___INVALID_PAYLOAD: payload inconsistente (HTTP 422).
- ERRO___UPPER___EXECUTION_FAILED: falha na orquestração (HTTP 500).
EOF

render "$STAGE/svc/schemas.py" <<'EOF'
"""svc-__NAME__ · contratos (DTOs, enums, constantes). Fonte da verdade: specs/__NAME__.md §2"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.plans import Module
from core.resources import Fields, Resource, Text

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-__NAME__"
TASK_QUEUE = "__NAME__-queue"
TRIGGER_SUBJECT = "events.__NAME__.trigger"
PROCESSED_SUBJECT = "events.__NAME__.processed"

# O serviço como módulo (README §5.17): título e categoria no menu e no plano; limits=[Limit(...)] o que ele limita;
# requires=("outro",) os módulos sem os quais não funciona; default=False se só entra quando o plano incluir.
MODULE = Module("__TITLE__", "Descreva em uma frase o que o módulo faz (specs/__NAME__.md §1)", category="Geral")


# Cadastros (README §5.19): lista, criação, edição, remoção, rotas, contrato e tela saem da declaração.
# Campo novo = uma linha aqui (title= é o rótulo na tela); outro cadastro = outro Resource em RESOURCES.
class Registro(Fields):
    title: str = Field(..., min_length=1, max_length=200, title="Título", description="Aparece na lista e entra na busca")
    notes: Text | None = Field(None, title="Observações")


REGISTROS = Resource(SERVICE, "registros", Registro, "Registros", search=("title",), sort=("title",))
RESOURCES = [REGISTROS]


class ExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)

    title: str = Field(..., min_length=1, max_length=200, description="Título do registro que a tarefa cria")
    payload: dict[str, Any] = Field(default_factory=dict, description="Dados da tarefa")


class ExecutionResult(BaseModel):
    task_id: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
EOF

render "$STAGE/svc/service.py" <<'EOF'
"""svc-__NAME__ · lógica de negócio pura. Fonte da verdade: specs/__NAME__.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "__NAME__.<método>".
Helpers começam com _ e nunca viram activities. O cadastro (RESOURCES) não precisa de código aqui: o core faz
lista, leitura, criação, edição e remoção; aqui fica só a regra de negócio (README §5.19).
"""
from core.nats_bus import bus
from core.resources import resources
from core.surreal import Migration
from core.temporal_runner import activities

from schemas import PROCESSED_SUBJECT, REGISTROS, ExecutionInput, ExecutionResult, Registro

# Mudanças de dados versionadas, rodadas uma vez por banco no boot (README §5.13). Nunca edite uma já publicada:
#   Migration(1, "observação padrão nos registros antigos", sql="UPDATE __SNAKE___registros SET notes = '' WHERE notes = NONE")
MIGRATIONS: list[Migration] = []


@activities("__NAME__")
class __PASCAL__Service:
    async def process_task(self, data: ExecutionInput) -> ExecutionResult:
        """Uma ação de negócio (POST /execute, ou durável pelo gatilho NATS): cria um registro no cadastro."""
        item = await resources.create(REGISTROS, Registro(title=data.title))
        result = ExecutionResult(task_id=item.id, status="SUCCESS", data={**item.model_dump(mode="json"), "payload": data.payload})
        await bus.publish(PROCESSED_SUBJECT, result, msg_id=result.task_id)
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
    from core.temporal_runner import Schedule
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


# Tarefas recorrentes (README §5.13): o runner as cria, atualiza e remove no Temporal a cada boot. Exemplo:
#   Schedule("resumo-diario", "0 6 * * *", ResumoWorkflow.run, Empty(), timezone="America/Sao_Paulo")
SCHEDULES: list[Schedule] = []
EOF

render "$STAGE/svc/main.py" <<'EOF'
"""svc-__NAME__ · ingress duplo + worker Temporal no mesmo loop. Fonte da verdade: specs/__NAME__.md

HTTP /registros...  → cadastro declarado em schemas.RESOURCES (core/resources.py): lista, item, cria, edita, remove.
HTTP POST /execute  → chamada direta ao service (síncrona). Exige token: nega por padrão.
NATS TRIGGER_SUBJECT → inicia __PASCAL__Workflow (assíncrona, durável e idempotente).

Rodar (da raiz): uv run python -m uvicorn --app-dir services/svc-__NAME__ main:app --port 8100 --env-file .env
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.envelope import ResponseEnvelope, install_envelope
from core.nats_bus import bus
from core.plans import plans
from core.resources import resources
from core.security import install_security
from core.surreal import db
from core.telemetry import install_telemetry
from core.temporal_runner import runner

from schemas import MODULE, RESOURCES, SERVICE, TASK_QUEUE, TRIGGER_SUBJECT, ExecutionInput
from service import MIGRATIONS, __PASCAL__Service
from workflows import SCHEDULES, __PASCAL__Workflow

svc = __PASCAL__Service()


async def on_trigger(data: ExecutionInput) -> None:
    # id = id estável da mensagem: reentrega do NATS nunca inicia um segundo workflow.
    await runner.start_workflow(__PASCAL__Workflow.run, data, task_queue=TASK_QUEUE, id=bus.message_id())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with (
        bus.connected(SERVICE),
        db.connected(resources=RESOURCES, migrations=MIGRATIONS, service=SERVICE),
        runner.worker(TASK_QUEUE, workflows=[__PASCAL__Workflow], service=svc, schedules=SCHEDULES),
    ):
        await bus.subscribe(TRIGGER_SUBJECT, on_trigger, model=ExecutionInput)
        await plans.declare(MODULE)  # módulo no catálogo dos planos; desligado para a organização, o core recusa
        yield


app = FastAPI(title=SERVICE, lifespan=lifespan)
install_envelope(app, service=SERVICE)
install_security(app, service=SERVICE)  # rota pública só se o spec §2 declarar: public=("/rota",)
install_telemetry(app, service=SERVICE)  # logs, trace, métricas e /health (README §5.18)
resources.mount(app, RESOURCES)  # as rotas dos cadastros (README §5.19)


@app.post("/execute", response_model=ResponseEnvelope)
async def execute(data: ExecutionInput) -> ResponseEnvelope:
    return ResponseEnvelope.success(data=await svc.process_task(data), service=SERVICE)
EOF

render "$STAGE/endpoint.yaml" <<'EOF'
# svc-__NAME__ · rotas públicas no Gateway. Fonte da verdade: specs/__NAME__.md §2
service: __NAME__
base_path: /api/v1/__NAME__

# Cadastros do schemas.py (core/resources.py, README §5.19): cada um publica 5 rotas e o aviso ao vivo
# __NAME__.<cadastro>, e vira __CAMEL__.<cadastro> no frontend.
resources: [registros]

endpoints:
  - path: /execute
    method: POST
    auth: client_jwt
    request: ExecutionInput        # modelos de schemas.py: viram os tipos do frontend (gateway/contracts.py)
    response: ExecutionResult
    target_type: http
    target_url: http://svc-__NAME__:8000/execute
    timeout: 30

  - path: /trigger
    method: POST
    auth: client_jwt
    request: ExecutionInput
    target_type: nats
    nats_subject: events.__NAME__.trigger
EOF

render "$STAGE/test.py" <<'EOF'
"""svc-__NAME__ · testes sem infraestrutura. Fonte da verdade: specs/__NAME__.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória, com o SurrealDB embutido, NATS, Temporal e
plano de mentira. O cadastro em si (lista, busca, edição, isolamento) já é testado no core; aqui ficam as regras e as
rotas deste serviço. Cadastro que muda de nome: troque a rota (/registros) e os campos nos testes abaixo.

Rodar (da raiz): PYTHONPATH=services/svc-__NAME__ uv run python -m pytest tests/__NAME__.py
"""
import pytest
from pydantic import ValidationError

from core.testing import service_app

from schemas import PROCESSED_SUBJECT, TRIGGER_SUBJECT, ExecutionInput


def test_rotas_do_servico_de_ponta_a_ponta():
    """Token, rotas do cadastro, /execute, o gatilho NATS e o isolamento por organização."""

    async def cenario(app):
        ana = app.user("ana", "acme", "owner")
        criado = await ana.post("/registros", json={"title": "Pelo cadastro"})
        executado = await ana.post("/execute", json={"title": "Pela ação", "payload": {"x": 1}})
        lista = await ana.get("/registros", params={"sort": "title"})
        busca = await ana.get("/registros", params={"q": "acao"})
        da_beta = await app.user("bia", "beta", "owner").get("/registros")
        sem_token = await app.anonymous().get("/registros")
        await app.handlers[TRIGGER_SUBJECT](ExecutionInput(title="Pelo gatilho"))  # o NATS entrega: vira workflow
        return criado, executado, lista, busca, da_beta, sem_token, app.workflows, app.published

    criado, executado, lista, busca, da_beta, sem_token, workflows, published = service_app(cenario)
    assert criado.status_code == 200, criado.text
    resultado = executado.json()["data"]
    assert resultado["status"] == "SUCCESS" and resultado["data"]["payload"] == {"x": 1}
    assert [r["title"] for r in lista.json()["data"]["items"]] == ["Pela ação", "Pelo cadastro"]
    assert [r["title"] for r in busca.json()["data"]["items"]] == ["Pela ação"]  # sem acento, pelo início da palavra
    assert da_beta.json()["data"]["total"] == 0 and sem_token.status_code == 401
    assert [name for name, _ in workflows] == ["__PASCAL__Workflow.run"]
    assert PROCESSED_SUBJECT in [subject for subject, _ in published]


def test_campo_nao_declarado_e_rejeitado():
    with pytest.raises(ValidationError):
        ExecutionInput.model_validate({"title": "x", "is_admin": True})
EOF

if [[ $MAKE_PAGE -eq 1 ]]; then
  render "$STAGE/page.tsx" <<'EOF'
// Tela do módulo __NAME__ (gerada pelo service.sh): só compõe o catálogo (src/components/CATALOG.md, README §6).
// Fonte da verdade: specs/__NAME__.md. Telas a mais: src/modules/__NAME__/<parte>/page.tsx ou [id]/page.tsx.
import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { __CAMEL__ } from "@/core/contracts";

export const meta: PageMeta = { title: "__TITLE__", module: "__NAME__" };

export default function __PASCAL__() {
  const registros = useResource(__CAMEL__.registros); // lista ao vivo, criar, editar e remover (README §5.19)
  return (
    <Page title="__TITLE__" description="Registros do módulo, só da sua organização.">
      <ResourceList resource={registros} noun="registro" />
    </Page>
  );
}
EOF
fi

# O compose.yaml novo também nasce na área temporária: a troca é um rename, nunca um arquivo pela metade.
COMPOSE_STATUS="ausente: serviço não registrado"
if [[ -f "$COMPOSE_FILE" ]]; then
  render "$STAGE/compose-block.yaml" <<'EOF'

  svc-__NAME__:
    <<: *service
    build: { <<: *service-build, args: { SERVICE: __NAME__ } }
    profiles: [modules, __NAME__]  # módulo de negócio: sobe com COMPOSE_PROFILES (README §9)
EOF
  cat "$COMPOSE_FILE" "$STAGE/compose-block.yaml" > "$STAGE/compose.yaml"
  COMPOSE_STATUS="svc-${NAME} registrado"
fi

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
undo() {  # desfaz o que já foi publicado
  rm -rf "$SVC_DIR" "$ENDPOINT_FILE" "$TEST_FILE"
  if [[ $KEEP_SPEC -eq 0 ]]; then rm -f "$SPEC_FILE"; fi
  if [[ $MAKE_PAGE -eq 1 ]]; then rm -rf "${PAGES_DIR:?}/$NAME"; fi
}
publish() {
  mv "$STAGE/svc" "$SVC_DIR" || return 1
  mv "$STAGE/endpoint.yaml" "$ENDPOINT_FILE" || { undo; return 1; }
  mv "$STAGE/test.py" "$TEST_FILE" || { undo; return 1; }
  if [[ $KEEP_SPEC -eq 0 ]]; then
    mv "$STAGE/spec.md" "$SPEC_FILE" || { undo; return 1; }
  fi
  if [[ $MAKE_PAGE -eq 1 ]]; then
    { mkdir "$PAGES_DIR/$NAME" && mv "$STAGE/page.tsx" "$PAGE_FILE"; } || { undo; return 1; }
  fi
  if [[ -f "$STAGE/compose.yaml" ]]; then
    mv "$STAGE/compose.yaml" "$COMPOSE_FILE" || { undo; return 1; }
  fi
}
publish || die "falha ao publicar; nada foi mantido."

if [[ $KEEP_SPEC -eq 1 ]]; then SPEC_STATUS="preservado"; else SPEC_STATUS="novo"; fi
if [[ $MAKE_PAGE -eq 1 ]]; then PAGE_STATUS="nova: /${NAME} no menu"
elif [[ -d "$PAGES_DIR" ]]; then PAGE_STATUS="preservada"
else PAGE_STATUS="sem frontend"; fi
cat <<EOF
==> svc-${NAME} provisionado (módulo "${TITLE}").
    ${SPEC_FILE}  (${SPEC_STATUS})
    ${SVC_DIR}/{schemas,service,workflows,main}.py
    ${ENDPOINT_FILE}
    ${TEST_FILE}
    ${PAGE_FILE}  (${PAGE_STATUS})
    ${COMPOSE_FILE}  (${COMPOSE_STATUS})

Próximo passo: preencha ${SPEC_FILE} e peça à IA:
  "Implemente specs/${NAME}.md em ${SVC_DIR}/ seguindo o README."
Testes: PYTHONPATH=${SVC_DIR} uv run python -m pytest ${TEST_FILE}
Contratos do frontend (antes de abrir a tela): uv run python gateway/contracts.py
EOF
