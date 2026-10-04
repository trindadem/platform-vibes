# Cogniventure Core Architecture (CV-Frame)

> **Status: INTOCÁVEL / ESPECIFICAÇÃO NORMATIVA.**
> Proibida qualquer alteração de topologia, violação de contratos ou criação de arquivos fora destas regras.
> Este README só muda com aprovação explícita do dono do projeto.

## Princípios

1. **Localidade cognitiva** — cada coisa tem um único lugar previsível. Um nome de serviço leva a exatamente quatro destinos, e todo arquivo aponta para o spec que o governa.
2. **Trilhos rígidos** — estrutura não é sugestão: o scaffolder gera, o código valida, o desvio interrompe.
3. **Metaprogramação** — o boilerplate se monta a partir do código vizinho: escreve-se a lógica em `service.py`; activities e registro derivam dela.
4. **Composição** — o frontend monta peças existentes; não inventa estrutura.

## 1. Topologia do Monorepo

```text
cogniventure/
├── README.md                    # Esta especificação
├── briefing.md                  # Camada de negócios da Cogniventure BPO: o quê e por quê (processos, áreas, ordem)
├── LICENSE                      # MIT: uso livre, mantendo o aviso de copyright
├── sprint.md                    # Log de bloqueios e revisões de contrato (seção 8)
├── service.sh                   # Scaffolder determinístico canônico (seção 3)
├── pyproject.toml               # Dependências Python únicas: core, gateway e serviços
├── uv.lock                      # Versões exatas das dependências Python (gerado pelo uv, versionado)
├── vendor/                      # Pacotes da casa fora de índice público, como wheel (AgentExo: exovision-agent)
├── compose.yaml                 # Ambiente local: Traefik, NATS, Temporal, Camunda, SurrealDB, RustFS, Mailpit, Grafana, gateway e serviços
├── compose.prod.yaml            # Produção num host só, sobre o compose.yaml: HTTPS, frontend, NATS com senha (seção 9)
├── .github/workflows/ci.yml     # CI: testes, trilhos, contratos e scaffolder em todo push (seção 7)
│
├── bench/                       # Banco de provas da meta layer: quanto um modelo de código acerta nos trilhos (seção 7)
│   ├── run.py                   # Roda as tarefas num modelo (ou nas referências) e escreve o relatório
│   ├── tasks/<id>.yaml          # 1 tarefa = spec de um módulo + prova de aceitação (+ solução de referência)
│   └── results/                 # Relatórios de cada rodada (.md e .json)
│
├── specs/                       # Micro-PRDs (estritamente 1 arquivo .md por serviço)
│   └── <service_name>.md
│
├── tests/                       # Testes (estritamente 1 arquivo .py por serviço, mais core.py e gateway.py)
│   ├── core.py
│   ├── gateway.py
│   └── <service_name>.py
│
├── core/                        # Recursos compartilhados (estritamente 1 arquivo .py por recurso)
│   ├── envelope.py              # Envelope canônico de I/O, resposta em pedaços (SSE) e handlers de erro
│   ├── security.py              # Autenticação, autorização, quem age (contexto), senhas, cabeçalhos, SSRF (seção 5.7)
│   ├── surreal.py               # Conexão multiplexada, queries parametrizadas e isolamento por organização (seção 5.9)
│   ├── nats_bus.py              # Eventos duráveis (JetStream), RPC e avisos ao vivo para a tela
│   ├── temporal_runner.py       # Cliente, worker base e auto-registro de activities (@activities)
│   ├── http_client.py           # Client HTTPX para chamadas externas, protegido contra SSRF
│   ├── llm.py                   # IA: qualquer API compatível com a da OpenAI, chaves no svc-ai, agentes (seção 5.11)
│   ├── storage.py               # Arquivos: S3 compatível, envio direto por link assinado, isolado por organização (seção 5.14)
│   ├── notify.py                # Avisos na tela e por e-mail, entregues pelo svc-notify (seção 5.15)
│   ├── webhooks.py              # Webhooks: eventos para os sistemas das organizações e conferência dos que chegam (seção 5.16)
│   ├── plans.py                 # Módulos, planos e limites: o que cada organização usa, conferido pelo core (seção 5.17)
│   ├── resources.py             # Cadastros declarados: CRUD, rotas, contrato e tela saem do schemas.py (seção 5.19)
│   ├── processes.py             # Processos: ações dos pacotes, fluxo tipado, BPMN e o motor Camunda 8 (seção 5.20)
│   ├── testing.py               # Kit de testes: o main.py do serviço em memória, pelas rotas (seção 5.5)
│   └── telemetry.py             # Observabilidade: logs estruturados, trace ponta a ponta, métricas e /health (seção 5.18)
│
├── gateway/                     # Ponto único de entrada HTTP (atrás do Traefik)
│   ├── endpoints/               # 1 manifesto YAML declarativo por serviço
│   │   └── <service_name>.yaml
│   ├── interpreter.py           # Lê os YAML, monta as rotas e despacha (HTTP ou NATS)
│   ├── contracts.py             # Gera frontend/src/core/contracts.ts (cliente tipado da API)
│   ├── schemas.py               # Schemas de rota e contratos de payload
│   └── main.py                  # Entrypoint FastAPI
│
├── services/                    # Microsserviços de negócio
│   ├── Dockerfile               # Único Dockerfile (serviços e gateway): SERVICE=<service_name> ou APP_DIR=gateway
│   └── svc-<service_name>/      # Regra estrita de 4 arquivos (seção 5.1)
│       ├── schemas.py
│       ├── service.py
│       ├── workflows.py
│       └── main.py
│
└── frontend/                    # Vite + React + TypeScript + Tailwind (composição pura)
    ├── Dockerfile               # Produção: build do Vite servido por nginx sem root, com CSP (seção 9)
    ├── index.html               # Entrada do Vite
    ├── components.json          # Configuração do shadcn/ui (preset radix-nova; primitivos em src/components/ui)
    ├── package.json
    ├── package-lock.json        # Versões exatas das dependências (gerado pelo npm, versionado)
    ├── tsconfig.json
    ├── vite.config.ts           # Build, proxy para o gateway, trilhos e gerador do catálogo (seção 6)
    └── src/
        ├── components/          # Catálogo: 1 <Nome>.tsx por componente, construído sobre o shadcn/ui
        │   ├── CATALOG.md       # Gerado a partir dos componentes: o que existe para compor
        │   └── ui/              # Primitivos do shadcn/ui (npx shadcn add <nome>), código de origem preservado
        ├── modules/             # Domínios de negócio isolados (as telas de cada módulo)
        │   └── <module_name>/
        │       ├── page.tsx     # A tela do módulo: vira a rota /<module_name> e o item do menu
        │       ├── <parte>/page.tsx  # Telas a mais (até 2 níveis): /<module_name>/<parte>, subitem no menu
        │       └── [id]/page.tsx     # Tela com parâmetro: /<module_name>/:id, fora do menu (useParams)
        ├── core/                # 1 arquivo por recurso: api.ts, auth.ts, contracts.ts (gerado), theme.css
        ├── App.tsx              # Router montado a partir de src/modules, menu por módulo e moldura da organização
        └── main.tsx             # Entrypoint DOM
```

Artefatos gerados por ferramentas (`__pycache__/`, `node_modules/`, `dist/`) não contam como violação de topologia e não são versionados.

## 2. Convenção de Nomes

Um serviço tem um único nome, em kebab-case: `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, até 40 caracteres, sem o prefixo `svc-`. Todas as outras grafias são derivadas pelo `service.sh` e nunca digitadas à mão.

Exemplo para `user-auth`:

| Recurso | Valor | Grafia |
|---|---|---|
| Spec, rota, teste | `specs/user-auth.md`, `gateway/endpoints/user-auth.yaml`, `tests/user-auth.py` | kebab |
| Pasta, container e host | `services/svc-user-auth/`, `svc-user-auth` | kebab |
| Rota pública | `/api/v1/user-auth` | kebab |
| Eventos NATS (duráveis) | `events.user-auth.trigger`, `events.user-auth.processed` | kebab |
| RPC NATS (request/reply) | `rpc.user-auth.<método>` | kebab |
| Tópicos ao vivo (`bus.live`) | `user-auth.<evento>` | kebab |
| Módulo (plano e menu) e tela | `user-auth`, `frontend/src/modules/user-auth/page.tsx` (`/user-auth`) | kebab |
| Cliente no frontend | `userAuth.<função>` (`core/contracts.ts`) | camel |
| Task queue e activities | `user-auth-queue`, `user-auth.<método>` | kebab |
| Tabela SurrealDB | `user_auth_records` | snake |
| Classes Python | `UserAuthService`, `UserAuthWorkflow` | Pascal |
| Códigos de erro | `ERRO_USER_AUTH_*` | UPPER |

Os nomes de runtime ficam como literais no topo do `schemas.py` de cada serviço: um `grep` pelo subject encontra spec, YAML e Python.

## 3. Scaffolding Determinístico (`service.sh`)

Todo serviço nasce obrigatoriamente de:

```bash
./service.sh <service_name>
```

O código vive somente em `service.sh` (este README não o duplica). O script:

- valida o nome (seção 2) e aborta sem tocar em nada se o serviço ou a rota já existirem;
- cria `specs/<service_name>.md` com o template de 4 tópicos — **ou preserva o spec, se já existir** (spec-first);
- cria `services/svc-<service_name>/` com os 4 arquivos já amarrados (activities, workflow, ingress HTTP + NATS, worker), um cadastro declarado (`registros`, seção 5.19: lista com busca, criação, edição e remoção sem código) e as listas vazias `SCHEDULES` e `MIGRATIONS` já ligadas (seção 5.13);
- declara o serviço como módulo (`MODULE` no `schemas.py`, `plans.declare` no boot, seção 5.17) e cria a tela `frontend/src/modules/<service_name>/page.tsx` (lista com busca e criação, já com `meta.module`), ou preserva a que já existir;
- cria `gateway/endpoints/<service_name>.yaml` e `tests/<service_name>.py` (no SurrealDB embutido), e registra o serviço no fim do `compose.yaml`;
- gera tudo numa área temporária, verifica a sintaxe e só então publica (tudo ou nada).

Arquivo de serviço criado à mão, fora do `service.sh`, é violação de contrato.

## 4. Invariante dos Micro-PRDs (`specs/`)

É proibido criar PRDs monolíticos ou globais. Toda unidade de negócio tem seu Micro-PRD de 1 página **antes** de qualquer código, exclusivamente em `specs/<service_name>.md`, com apenas e exatamente estes 4 tópicos:

```markdown
# Spec: <service_name>

## 1. Objetivo Operacional
2 a 3 linhas: a dor que resolve e o resultado de negócio esperado.

## 2. Contrato de Entrada e Saída
Campos exatos do payload (Request) e do retorno (data no envelope).

## 3. Fluxo de Execução
1. Persistência em SurrealDB (tabela e campos).
2. Eventos emitidos no NATS (subject e payload).
3. Activities orquestradas no Temporal (passos, retry e timeout).

## 4. Casos de Borda e Erros Mapeados
Falhas esperadas, limites de validação e códigos de erro (ERRO_<UPPER>_*).
```

O spec é a fonte da verdade: todo arquivo gerado declara no cabeçalho `Fonte da verdade: specs/<service_name>.md §N`.

## 5. Invariantes do Backend

### 5.1 Regra dos 4 arquivos

Cada `services/svc-<service_name>/` contém apenas e unicamente:

| Arquivo | Conteúdo | Trilho |
|---|---|---|
| `schemas.py` | Nomes canônicos (literais), DTOs Pydantic, enums, `BaseSettings` do serviço | Nenhuma lógica |
| `service.py` | `<Pascal>Service` decorada com `@activities("<service_name>")`: lógica pura, SurrealQL, helpers `_privados` | Todo método público é `async def m(self, data: Modelo) -> Modelo`, ou um gerador de pedaços para streaming (seção 5.10) |
| `workflows.py` | `<Pascal>Workflow`: encadeia `workflow.execute_activity_method(<Pascal>Service.m, ...)` | Sem I/O; imports dentro de `workflow.unsafe.imports_passed_through()` |
| `main.py` | FastAPI + assinatura NATS + worker Temporal no mesmo loop | Só ingress; nenhuma regra de negócio |

### 5.2 Metaprogramação de activities

- `@activities("<service_name>")`, de `core/temporal_runner.py`, transforma cada método público do service na activity `<service_name>.<método>`. Nada é registrado à mão.
- Métodos iniciados por `_` nunca viram activities.
- Assinatura fora do trilho impede o serviço de subir, com uma mensagem que diz como corrigir.
- O workflow referencia o método real (`<Pascal>Service.m`), nunca uma string: erro de digitação quebra no import, não em produção.

Novo passo de negócio = novo método público em `service.py` + uma chamada em `workflows.py`.

Serviço que ainda não tem activities nem workflows (um pacote que só declara ações, seção 5.20) sobe sem worker: `runner.worker` conecta o cliente e sincroniza as agendas, e mais nada.

### 5.3 Ingress duplo

| Entrada | Caminho | Natureza |
|---|---|---|
| HTTP `POST /execute` | Chama o service diretamente; exige token (seção 5.7) | Síncrona |
| NATS `events.<service_name>.trigger` | Inicia `<Pascal>Workflow` no Temporal | Assíncrona, durável e idempotente |

- **Durável:** eventos `events.*` vivem no stream JetStream `EVENTS` (7 dias). Mensagem publicada com o serviço fora do ar é entregue quando ele voltar. Réplicas do mesmo serviço dividem o trabalho; serviços diferentes recebem cada um a sua cópia.
- **Idempotente:** a entrega é at-least-once. O workflow nasce com `id=bus.message_id()`, o mesmo em toda reentrega, então uma mensagem nunca inicia duas execuções. Quem publica passa `msg_id=` para o JetStream descartar duplicatas.
- **Falhas:** mensagem inválida é descartada sem reentrega; handler que falha é re-tentado até 5 vezes, com espera crescente.
- **Quem age viaja junto:** usuário, organização e papéis seguem no cabeçalho da mensagem e do workflow; o handler e cada activity rodam em nome de quem disparou (seção 5.9).

### 5.4 Execução isolada

Cada serviço roda de dentro da própria pasta, com imports irmãos (`from schemas import ...`). A partir da raiz:

```bash
uv run python -m uvicorn --app-dir services/svc-<service_name> main:app --port 8100 --env-file .env
uv run python -m uvicorn --app-dir gateway main:app --port 8090 --env-file .env
```

No host, use portas a partir de 8100: a 8000 é do SurrealDB no compose (seção 7).

Motivo: o sandbox do Temporal reimporta o workflow pelo nome do módulo, e `svc-<service_name>`, com hífen, não é importável como pacote. Consequência desejada: um `import` de outro serviço falha na hora.

### 5.5 Regras gerais

- **Sem acoplamento lateral:** um serviço importa apenas `core.*` e seus três arquivos irmãos. Nunca `services.*`, nunca `importlib` apontando para outro serviço. Serviços conversam por NATS ou pelo Gateway.
- **Core canônico:** cada recurso compartilhado vive em um único arquivo de `core/` (seção 5.6).
- **Gateway declarativo:** zero rotas de negócio no código do Gateway. Toda rota pública vive em `gateway/endpoints/<service_name>.yaml` (seção 5.8). Rotas nascem com `auth: client_jwt`; `auth: public` só quando o spec §2 declarar.
- **Envelope obrigatório:** toda resposta HTTP, de sucesso **e de erro**, sai no modelo de `core/envelope.py`.
- **Dependências:** únicas, no `pyproject.toml` da raiz, com as versões exatas travadas no `uv.lock`. Serviço não declara dependência própria. Dependência nova: `uv add <pacote>` (atualiza os dois arquivos juntos). Pacote da casa que não está num índice público entra como wheel em `vendor/` (`uv add ./vendor/<arquivo>.whl`); a imagem copia `vendor/` antes de instalar. Todo comando Python roda com `uv run`, que na primeira vez cria o `.venv` com as versões do lock.
- **Imagem:** serviços e gateway usam `services/Dockerfile` (`SERVICE=<service_name>` ou `APP_DIR=gateway`); a imagem instala exatamente o `uv.lock` (lock defasado derruba o build), já com o bytecode compilado (o container sobe sem recompilar as bibliotecas), copia apenas `core/` e a pasta do app e roda sem root. O frontend tem a sua, `frontend/Dockerfile` (seção 9).
- **Testes:** em `tests/<service_name>.py`, um serviço por processo, sem infraestrutura: o NATS vira dublê e o SurrealDB roda embutido em memória (`AsyncSurreal("mem://")`, do próprio SDK), com as tabelas e os índices do boot, executando a SurrealQL de verdade. O motor embutido é o 2.x e o servidor é o 3.x: o core cuida das diferenças conhecidas (seção 5.12). Para testar pelas rotas, `core/testing.py` sobe o `main.py` de verdade em memória: `service_app(cenario)` roda o lifespan inteiro e dá clientes HTTP com token (`app.user("ana", "acme", "owner")`), o que foi publicado (`app.published`, `app.live`), os handlers assinados (`app.handlers`), respostas falsas de RPC (`app.respond`), o motor de processos em memória (`app.motor`: implantados, iniciados, mensagens, tarefas concluídas) e `app.job(tipo, ...)`, que passa um job do motor pelo worker de verdade e devolve como ele termina.

  ```bash
  PYTHONPATH=services/svc-<service_name> uv run python -m pytest tests/<service_name>.py
  uv run python -m pytest tests/core.py
  PYTHONPATH=gateway uv run python -m pytest tests/gateway.py
  ```

### 5.6 Contrato do core

Importar o core nunca conecta em nada nem exige variáveis: a configuração é lida e validada no boot (lifespan).

| Arquivo | Expõe |
|---|---|
| `envelope.py` | `ResponseEnvelope.success(data, service)`, `ServiceError(code, message, status)`, `install_envelope(app, service)`, `stream_response(gerador, service, final=Modelo)` |
| `security.py` | `install_security(app, service, public)`, `principal`, `require(*papéis)`, `current()`, `current_tenant()`, `acting_as(principal)`, `system(service, tenant)`, `issue_token`, `verify_token`, `hash_password`, `verify_password`, `assert_public_url`, `redact`, `new_secret`, `same`, `add_gate` (só para o core) |
| `nats_bus.py` | `bus.connected(service)`, `bus.publish(subject, model, msg_id)`, `bus.subscribe(subject, handler, model)`, `bus.message_id()`, `bus.request(...)`, `bus.respond(...)`, `bus.live(tópico, model, user=None)`, `bus.live_feed(principal)` |
| `temporal_runner.py` | `@activities(prefixo)`, `runner.worker(task_queue, workflows, service, schedules)`, `runner.start_workflow(run, arg, task_queue, id)`, `Schedule` |
| `surreal.py` | `db.connected(tables=[TABLE], shared=[...], unique={...}, search={...}, migrations=[...], service=SERVICE)`, `db.query(sql, **params)`, `db.query_shared(...)`, `db.page(TABLE, query, ModeloPage)`, `db.create`, `db.select`, `db.merge`, `db.delete`, `db.tenants(TABLE)`, `ListQuery`, `Page`, `Migration` |
| `http_client.py` | `http.get`, `http.post`, `http.request` (com `max_bytes=` para parar de ler respostas grandes) — só para APIs externas; nunca guarda cookie entre chamadas |
| `llm.py` | `llm.ask(modelo, prompt, instructions, output, tools, images)`, `llm.stream(...)`, `llm.embed(modelo, textos)`, `llm.run_agent(modelo, tarefa, instructions, tools, context, on_step, max_turns)`, `SchemaTool`, `AgentStep`, `AgentResult`, `llm.agent(...)`, `Image` — o único jeito de chamar IA (seção 5.11) |
| `storage.py` | `storage.connected(service)`, `storage.upload(pedido, accept, max_bytes, folder)`, `storage.keep(key)`, `storage.url(key, ttl, filename, content_type)`, `storage.read(key, max_bytes)`, `storage.save(dados, filename, content_type, max_bytes)`, `storage.delete(key)`, `UploadRequest`, `Upload`, `KeepRequest`, `StoredFile`, `IMAGES` (seção 5.14) |
| `notify.py` | `notify.user(sub, title, body, link, action, send_email, key)`, `notify.roles(*papéis, title=...)`, `notify.email(endereço, title, body, link, action, key)` — o único jeito de avisar alguém (seção 5.15) |
| `webhooks.py` | `WebhookEvent(nome, descrição, Modelo)`, `webhooks.declare(lista)`, `webhooks.emit(nome, modelo, key)`, `webhooks.verify(segredo, cabeçalhos, corpo)`, `sign`, `new_secret` (seção 5.16) |
| `plans.py` | `Module(título, descrição, category, limits, requires, core, default)`, `Limit(nome, descrição, default, monthly, unit, currency)`, `plans.declare(MODULE)`, `plans.check(nome, used=)`, `plans.use(nome, quantidade, key)`, `plans.count(nome, total)`, `plans.enabled(módulo)`, `plans.limits()`, `plans.assign(plano, modules=)` (seção 5.17) |
| `telemetry.py` | `install_telemetry(app, service, edge, health)`, `telemetry.counter(nome, descrição)`, `telemetry.histogram(nome, descrição)` (seção 5.18) |
| `resources.py` | `Resource(SERVICE, nome, Campos, título, search, sort, filters, unique, columns, limit, write)`, `Fields`, `Money`, `Email`, `Phone`, `Text`, `resources.mount(app, RESOURCES)`, `resources.list/get/create/update/remove(recurso, ...)` (seção 5.19) |
| `processes.py` | `Action(nome, título, descrição, Entrada, Saída, risk, example, connections)`, `ProcessModel(modelo, fluxo)`, `processes.declare(ACTIONS, MODELS)`, `processes.worker(SERVICE, ACTIONS, svc, jobs=)`, `processes.emit(nome, dados, chave, key)`, `Handoff(motivo)`, `Job`, `Fluxo`, `Step`, `Flow`, `Condition`, `Trigger`, `process_id(org, processo)`, `to_bpmn(fluxo, process_id, name, actions)`, `camunda.deploy/start/message/complete_task/path` (seção 5.20) |
| `testing.py` | `service_app(cenario)`: o `main.py` em memória, com `app.user(...)`, `app.published`, `app.live`, `app.handlers`, `app.respond(subject, função)` (seção 5.5) |

Erro de negócio do spec §4: `raise ServiceError("ERRO_<UPPER>_<CASO>", "mensagem", status=409)`. Ele sai no envelope pelo HTTP e, com status < 500, nunca é re-tentado pelo Temporal.

Erros de validação (422) saem com mensagens em pt-BR e os limites do próprio modelo ("Mínimo de 2 caracteres.", "Deve ser maior que 0."), e cada detalhe aponta o campo em `loc`. As tabelas declaradas em `db.connected(...)` são garantidas no boot (no SurrealDB 3, consultar tabela inexistente é erro; assim a primeira listagem devolve `[]`); tabela não declarada é erro. Valor repetido num índice `unique` sai como 409 `ERRO_RECORD_DUPLICATE`, sem ecoar o valor. Consulta com vários comandos devolve o resultado do primeiro, mas o core confere todos: o erro de qualquer um chega ao serviço (o SDK só conferia o primeiro).

### 5.7 Segurança (`core/security.py`)

Segurança não se implementa por serviço: importa-se do core. Proibido reimplementar autenticação, hash de senha, verificação de token ou proteção de URL.

- **Nega por padrão:** `install_security(app, service=SERVICE)` exige token válido em **toda** rota, inclusive as que a IA criar depois. Abrir é explícito e só se o spec §2 declarar: `public=("/rota",)`. A única exceção é `/health` (seção 5.18), que só diz se as dependências respondem. Papéis: `Depends(require("admin"))`.
- **Identidade vem do token:** quem chama é o `Principal` (usuário, organização ativa e papéis nela; `Depends(principal)` ou `current()`), nunca um campo do payload.
- **Conferências do core:** depois da autenticação, toda chamada de uma pessoa numa organização (requisição HTTP, evento NATS e RPC) passa pelas conferências que o core registra (`add_gate`); hoje, uma só: o módulo do serviço fora do plano da organização recusa com 402 `ERRO_PLAN_MODULE` (seção 5.17). Tarefa da plataforma (`system`) e rota pública passam. Serviço não registra conferência.
- **Tokens:** JWT com chave assimétrica. EdDSA com chaves próprias ou JWKS de um provedor (Auth0, Clerk, Keycloak…). `none` e HS256 são recusados; `iss`, `aud`, `exp` e `sub` são obrigatórios. Só o serviço que faz login tem a chave privada.
- **Login e sessão:** o `svc-identity` (`specs/identity.md`) é o único emissor de tokens e o único container com `AUTH_PRIVATE_KEY`: cadastro, login, senha esquecida (link por e-mail de 30 min, uso único, que derruba as sessões), organizações, convites e membros. Token de acesso de 15 min; refresh de 30 dias só no cookie `cv_refresh` (HttpOnly, SameSite=Strict, `Path=/api/v1/identity`, Secure em produção), nunca no corpo, trocado a cada uso; um refresh antigo que reaparece derruba a sessão inteira.
- **Senhas:** só `hash_password` / `verify_password` (Argon2id, fora do event loop). Nunca md5, sha ou hash próprio.
- **Payload:** modelos de entrada usam `extra="forbid"` (campo não declarado é recusado); erro de validação nunca ecoa o valor recebido.
- **Banco:** só `core.surreal`, com parâmetros (`$nome`) e nunca f-string; login como usuário do banco, nunca root.
- **Rede:** URL externa só por `core.http_client` (bloqueia SSRF e não segue redirects). Rede interna (`allow_private=True`) só com `ENVIRONMENT=development`: em produção o próprio core recusa. NATS em produção com credencial (`NATS_USER`/`NATS_PASSWORD` ou `NATS_CREDS`) e permissões por subject: o gateway só publica gatilhos e lê avisos ao vivo (seção 9).
- **Temporal:** em produção, todo payload (entradas, resultados e cabeçalhos de workflows e activities) vai cifrado com AES-256-GCM (`TEMPORAL_PAYLOAD_KEY`): o histórico não guarda e-mail, link de senha nem conteúdo de aviso em claro.
- **IA:** chave de provedor só no `svc-ai`, criptografada; o serviço chama modelo só pelo `core/llm.py`, sem ver a chave (seção 5.11).
- **Respostas:** cabeçalhos de segurança em toda resposta (HSTS e CSP em produção), `cache-control: no-store`, erro 500 sem detalhe interno, CORS só com origens listadas (`*` é recusado).
- **Segredos e logs:** segredos só no `.env` (fora do Git). Antes de logar dados, `redact(...)`.
- **Configuração insegura não sobe:** falta de chave, CORS `*`, JWKS sem https ou par de chaves trocado impedem o boot; em produção, também NATS sem credencial e Temporal sem `TEMPORAL_PAYLOAD_KEY`.

Variáveis de ambiente (no `.env`; nenhum segredo tem valor padrão):

| Variável | Uso |
|---|---|
| `ENVIRONMENT` | `production` (padrão) ou `development` (libera `/docs`, sem HSTS/CSP) |
| `AUTH_ISSUER`, `AUTH_AUDIENCE` | Obrigatórias: quem emite e para quem são os tokens |
| `AUTH_PUBLIC_KEY` / `AUTH_PRIVATE_KEY` | Chaves próprias. A privada só no serviço que emite tokens |
| `AUTH_JWKS_URL` | Alternativa às chaves próprias: provedor externo (https) |
| `AUTH_TOKEN_TTL_SECONDS`, `AUTH_ROLES_CLAIM`, `AUTH_TENANT_CLAIM`, `CORS_ORIGINS` | Opcionais (900, `roles`, `tenant`, nenhuma) |
| `SURREAL_URL`, `SURREAL_NAMESPACE`, `SURREAL_DATABASE`, `SURREAL_USER`, `SURREAL_PASSWORD` | Banco; só a URL tem padrão |
| `SURREAL_ROOT_PASSWORD`, `GATEWAY_PORT` | Só no compose: senha root do SurrealDB (nenhum serviço a recebe) e porta local da API (8088) |
| `NATS_URL`, `NATS_USER`, `NATS_PASSWORD`, `NATS_CREDS` | Mensageria; credencial obrigatória em produção (no compose, vem de `NATS_SERVICES_PASSWORD` e `NATS_GATEWAY_PASSWORD`, seção 9) |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY`, `TEMPORAL_PAYLOAD_KEY` | Orquestração; a API key liga TLS (Temporal Cloud); a chave cifra os payloads e é obrigatória em produção |
| `DOMAIN`, `ACME_EMAIL` | Só no `compose.prod.yaml`: o domínio (a tela em `DOMAIN`, os arquivos em `files.DOMAIN`) e o e-mail do certificado (seção 9) |
| `AI_SECRETS_KEY`, `PLATFORM_TENANT` | A chave que criptografa as chaves dos provedores (o `keygen` gera; só no `svc-ai`) e a organização que administra a plataforma: provedores de IA para todas (`svc-ai`, seção 5.11) e os planos (`svc-plans`, seção 5.17); opcional |
| `SMTP_URL`, `MAIL_FROM`, `APP_URL`, `APP_NAME` | Só no `svc-notify`: servidor de e-mail (`smtps://` ou `smtp://` com STARTTLS; sem TLS só em development), remetente, endereço da tela (base dos links) e nome nos e-mails (seção 5.15) |
| `WEBHOOKS_SECRETS_KEY` | Só no `svc-webhooks`: a chave que criptografa os segredos de assinatura dos endereços (o `keygen` gera; seção 5.16) |
| `LOG_LEVEL`, `LOG_FORMAT`, `OTEL_EXPORTER_OTLP_ENDPOINT` | Observabilidade (seção 5.18): nível (`INFO`), formato (`json`; `text` é o padrão em development) e para onde vão traces, métricas e logs (OTLP/HTTP; sem ela, nada sai do processo). Valem também as variáveis padrão do OpenTelemetry (`OTEL_TRACES_SAMPLER`, `OTEL_RESOURCE_ATTRIBUTES`...) |
O `keygen` cria o `.env` com chaves e senhas aleatórias (nunca sobrescreve um existente); o `token` emite um token de teste com essas chaves.

```bash
uv run python -m core.security keygen
uv run python -m core.security token <sub> [--tenant <organização>] [papel ...]
```

### 5.8 Gateway (`gateway/`)

O gateway verifica o token, aplica os manifestos e despacha. Não contém regra de negócio: cada rota nasce de `gateway/endpoints/<service_name>.yaml`, validado por `gateway/schemas.py`. Manifesto fora do trilho impede o boot.

```yaml
service: billing
base_path: /api/v1/billing          # sempre /api/v1/<service>
endpoints:
  - path: /faturas/{fatura_id}
    name: detalhe                   # opcional: nome da função no frontend (padrão: último trecho fixo do path)
    method: GET                     # GET | POST | PUT | PATCH | DELETE
    auth: client_jwt                # client_jwt | public
    roles: [financeiro]             # opcional: papéis exigidos no token (todos os listados; "um ou outro" é regra do serviço)
    response: Fatura                # modelo do schemas.py devolvido em data (GET/DELETE não têm request)
    target_type: http               # http | nats
    target_url: http://svc-billing:8000/faturas/{fatura_id}
    timeout: 30                     # segundos, até 120
    cookies: false                  # opcional: true só em rota de sessão (HTTP POST)
  - path: /trigger
    method: POST                    # NATS só aceita POST
    auth: client_jwt
    request: FaturaIn               # modelo do schemas.py esperado no corpo; NATS responde { message_id }
    target_type: nats
    nats_subject: events.billing.trigger  # sempre o gatilho do serviço
  - path: /faturas
    name: listar
    method: GET
    auth: client_jwt
    query: FaturaQuery              # parâmetros da URL tipados (lista paginada, seção 5.12); só em GET
    response: FaturaPage
    target_type: http
    target_url: http://svc-billing:8000/faturas
  - path: /resumo
    method: POST
    auth: client_jwt
    stream: true                    # resposta em pedaços (SSE, seção 5.10); exige delta
    request: ResumoIn
    delta: Trecho                   # modelo de cada pedaço; response é o resultado final
    response: Resumo
    target_type: http
    target_url: http://svc-billing:8000/resumo
live:                               # eventos ao vivo que o serviço emite (bus.live): billing.<topic>
  - topic: fatura-paga
    model: Fatura
```

- **Trilhos do manifesto:** `target_url` só aponta para `http://svc-<service>:8000/` e `nats_subject` só para `events.<service>.trigger` (o gatilho do serviço; mais de uma ação vai num campo do payload), ou seja, nunca para outro serviço ou para fora. O nome do arquivo é igual ao `service`. Rota pública não tem `roles` nem parâmetros no caminho. Campo desconhecido é erro.
- **HTTP:** repassa corpo (byte a byte), query string e só os cabeçalhos `authorization`, `content-type`, `accept` e `x-request-id`; `headers: [stripe-signature]` libera outros numa rota HTTP POST (a assinatura de um webhook que chega, seção 5.16), nunca os de sessão ou roteamento (`cookie`, `host`, `x-forwarded-*`...). O serviço verifica o token de novo e continua o trace do gateway (`traceparent`, seção 5.18). Parâmetros de caminho são codificados (`../` não atravessa). Serviço fora do ar → 502; lento → 504.
- **NATS:** o corpo precisa ser um objeto JSON; a resposta é `202` com o `message_id`. O cabeçalho `Idempotency-Key` faz a mesma requisição repetida virar a mesma mensagem e o mesmo workflow, com a chave isolada por usuário.
- **Limites:** corpo acima de 1 MiB → 413, no gateway (que lê o corpo em pedaços). O Traefik não usa o middleware `buffering`, que seguraria a resposta inteira e quebraria o streaming. Rate limit por IP no Traefik (50 req/s, rajada de 100; login, cadastro e senha esquecida: 20 por minuto). O nome de serviço `live` é reservado: `/api/v1/live` é do gateway.
- **Rota pública:** `auth: public` no YAML **e** `public=("/rota",)` no `install_security` do serviço. As duas declarações precisam bater.
- **Cookies:** só rotas com `cookies: true` recebem o `Cookie` do navegador e devolvem o `Set-Cookie` do serviço; nas outras, cookie nunca passa. O gateway não guarda cookie entre requisições.
- **Novo serviço:** o gateway lê os manifestos no boot; rebuild do gateway publica as rotas novas.
- **Contratos tipados:** `uv run python gateway/contracts.py` junta manifestos e `schemas.py` e gera `frontend/src/core/contracts.ts`: tipos TypeScript (com as descrições dos campos) e uma função por rota, como `billing.execute(body)` e `loja.detalhe({ fatura_id })`. Modelo citado e inexistente é erro. Arquivo desatualizado falha em `tests/gateway.py` (e em `--check`). Rode sempre que mudar um manifesto ou um `schemas.py`.

### 5.9 Multi-tenancy (`core/surreal.py`)

Cada cliente da plataforma é uma organização (`tenant`). Um usuário pode pertencer a várias; o token vale para uma, a organização ativa. O serviço não escreve código de tenant: o core descobre, grava, filtra e propaga.

- **De onde vem:** do token (claim `tenant`), nunca do corpo. Durante a requisição, o evento NATS ou a activity, `current()` diz quem age e `current_tenant()` de qual organização (sem organização → 403 `ERRO_TENANT_REQUIRED`). Testes e tarefas internas usam `with acting_as(Principal(sub=..., tenant=...))`.
- **Tabelas por organização (padrão):** `db.connected(tables=[TABLE])` cria no banco o campo `tenant`, indexado e `READONLY`. `db.create` grava a organização atual; `db.select`, `db.merge` e `db.delete` só enxergam registros dela (de outra organização, o registro não existe). Gravar `tenant` à mão é erro.
- **Query:** `db.query` recebe `$tenant` sozinho e recusa SQL que não o cita:

  ```python
  await db.query("SELECT * FROM faturas WHERE tenant = $tenant AND status = $status", status="pago")
  ```

- **Únicos:** `unique={"faturas": ["numero"]}` vale dentro de cada organização (o `tenant` entra no índice sozinho).
- **Conflito entre transações:** duas escritas simultâneas no mesmo registro ou índice (ex.: duas abas abrindo a mesma tela) dão conflito no SurrealDB; o core repete a operação até 3 vezes antes de devolver o erro.
- **Listas:** `db.page` (seção 5.12) filtra a organização sozinho, como `create` e `select`.
- **Tabelas globais:** `shared=[...]` e `db.query_shared(...)`, sem filtro de organização. Só os serviços de plataforma as usam: o de identidade (usuários, organizações, sessões), o de IA (provedores e modelos, com o dono no campo `owner`), o de avisos (registro de e-mails e preferências de cada pessoa), o de webhooks (catálogo de eventos), o de processos (catálogo de ações e fluxos de partida que os pacotes declaram, seção 5.20) e o de planos (catálogo de limites, planos e o plano de cada organização, no campo `org`).
- **Assíncrono:** quem age viaja no cabeçalho do evento NATS e do workflow Temporal; o handler e cada activity rodam em nome de quem disparou. O cabeçalho é confiável porque só a plataforma publica no NATS (`NATS_CREDS` em produção).

### 5.10 Tempo real e streaming

Dois casos, ambos por SSE (servidor → tela, sobre HTTP); o caminho tela → servidor continua sendo POST.

- **Resposta em pedaços** (tokens de IA, progresso de uma tarefa longa): o método do service é um gerador, `async def m(self, data: Modelo) -> AsyncIterator[Pedaco | Final]` (não vira activity), e a rota devolve `stream_response(svc.m(data), SERVICE, final=Final)`. Sai `event: delta` a cada pedaço, `event: done` com o envelope do resultado e `event: error` com o envelope do erro (mesmas regras de sempre), com batimento a cada 15 s. Quem fecha a tela cancela o gerador. No manifesto: `stream: true` e `delta: <Modelo>`; o gateway repassa sem juntar, com `timeout` valendo entre um pedaço e outro.
- **Avisos ao vivo** (listas e painéis que atualizam sozinhos): `await bus.live("<service>.<evento>", modelo)` avisa a organização inteira; `user=<sub>` avisa só uma pessoa. A organização vem sempre do contexto: não há como avisar outra. Só o próprio serviço emite seus tópicos, que ficam declarados em `live:` no manifesto. É efêmero (NATS simples): quem estava fora do ar busca de novo no banco.
- **Conexão:** `GET /api/v1/live` (gateway) entrega a quem chama só os avisos da organização do token e os endereçados a essa pessoa. Fecha quando o token vence; o frontend reabre com o token renovado e ao trocar de organização.
- **Frontend:** uma conexão por aba, compartilhada. `useStream(fn)` acumula os pedaços (`deltas`, `result`, `cancel`); `useLiveQuery("tópico", fn, ...args)` é um `useQuery` que recarrega quando o aviso chega e quando a conexão volta; `useLive("tópico", fn)` reage a cada aviso. Os tópicos e seus modelos vêm tipados de `contracts.ts` (`LiveTopics`).

### 5.11 IA (`core/llm.py` e `svc-ai`)

Qualquer API compatível com a da OpenAI: OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Gemini e modelos locais (Ollama, vLLM, LM Studio). O serviço nunca vê chave nem monta cliente de provedor: pede o modelo pelo nome `<provedor>/<modelo>`, e o core resolve o resto.

```python
from core.llm import Image, llm

texto   = await llm.ask("openrouter/claude", "Resuma: ...", instructions="Seja breve.")
fatura  = await llm.ask("local/llama", texto, output=Fatura)             # saída estruturada (modelo Pydantic)
legenda = await llm.ask("openai/gpt", "O que há na foto?", images=[Image(url="https://...")])
texto   = await llm.ask("openai/gpt", pergunta, tools=[buscar_cliente])  # ferramentas: funções async com docstring
async for pedaco in llm.stream("openrouter/claude", pergunta): ...       # dentro do gerador de stream_response
vetores = await llm.embed("openai/vetores", ["a", "b"])
agente  = await llm.agent("openrouter/claude", tools=[...])              # Agent do Agno, para casos avançados
feito   = await llm.run_agent("cv/agente", tarefa, instructions=INSTRUCAO, tools=[registrar, buscar],
                              context=historico, on_step=passos.put_nowait)   # agente com ferramentas (AgentExo)
```

- **Provedores e chaves** (`svc-ai`, `specs/ai.md`): donos e admins cadastram o endereço base e a chave. A chave é guardada criptografada (AES-256-GCM com `AI_SECRETS_KEY`, que só o `svc-ai` recebe) e nunca volta inteira: a tela mostra só `…abcd`. Os provedores da plataforma valem para todas as organizações e são geridos pela organização cujo id está em `PLATFORM_TENANT`; sem ela, cada organização traz a sua chave.
- **Prioridade:** o provedor da organização esconde o da plataforma com o mesmo apelido, sem misturar chaves nem custos.
- **Modelos:** a busca lê `GET {base_url}/models`, e o modelo descoberto nasce desativado. Quem administra ativa, dá apelido (`openrouter/claude`), marca o tipo (chat ou embedding) e informa o preço por milhão de tokens. Provedor sem `/models` aceita cadastro manual.
- **Resolução:** o core pergunta ao `svc-ai` (`rpc.ai.resolve`), na organização de quem age, e guarda a resposta por 60 s: troca de chave ou de modelo vale em até 1 min. Modelo inexistente, desativado ou de outro tipo → 404 `ERRO_AI_MODEL_UNAVAILABLE`.
- **Rede:** provedor de organização só em `https` com IP público, conferido ao salvar e a cada uso; rede interna (Ollama, vLLM) só nos provedores da plataforma. Sem redirect e sem cookie.
- **Uso e custo:** toda chamada publica `events.ai.usage` (tokens, modelo, serviço); o `svc-ai` grava por organização com o preço do momento, sem contar duas vezes a mesma mensagem, e soma no plano (`ai.custo` em US$ e `ai.tokens`, seção 5.17). `GET /api/v1/ai/usage` resume o mês.
- **Limite do plano:** antes de cada chamada, o core confere o mês da organização; quem já chegou ao limite recebe 402 `ERRO_PLAN_LIMIT` sem que o provedor seja chamado.
- **Erros do provedor** saem no envelope sem ecoar a mensagem dele: 401/403 → `ERRO_AI_PROVIDER_AUTH`, 429 → `ERRO_AI_RATE_LIMITED`, o resto → `ERRO_AI_PROVIDER`.
- **Tela `/ia`:** donos e admins têm as abas Uso do mês (atualiza ao vivo pelo aviso `ai.uso`), Modelos (buscar, liberar, apelido, tipo e preço) e Provedores; membros veem só os modelos liberados. O provedor da plataforma aparece às outras organizações sem endereço e sem chave.
- **Agno por baixo** (`ask`, `stream`, `agent`): telemetria, banco, memória e conhecimento do Agno ficam desligados, porque não respeitam a organização. Histórico de conversa e documentos ficam em tabelas do serviço, pelo `core.surreal`.
- **Agentes (`run_agent`):** o laço é o do AgentExo (`exovision-agent`, o SDK agêntico da casa, em `vendor/`), síncrono, numa thread; o que toca a plataforma continua no core. Cada volta passa pelo mesmo cliente HTTP (sem redirect, sem cookie, endereço conferido), confere o plano e publica o uso. Ferramentas são funções async do serviço, com docstring (a descrição que o modelo lê) e parâmetros tipados (o schema, validado pelo Pydantic antes da chamada); um único parâmetro que é modelo Pydantic tem os campos dele como argumentos. Ferramenta só conhecida em tempo de execução (a de um servidor MCP) entra como `SchemaTool(nome, descrição, JSON schema, call)`: o schema vai ao modelo como veio e `call` recebe o dict de argumentos. Elas rodam no loop do serviço, em nome de quem age. Argumento inválido e `ServiceError` voltam ao modelo como erro, para ele corrigir; outra exceção vira "falha interna", sem detalhe. `context=` entra antes da tarefa (histórico, estado); `on_step=` recebe cada ferramenta que começa e termina (`AgentStep`), para a tela. Erro do provedor ou do plano sobe como nas outras chamadas.
- **Busca semântica:** cada trecho é gravado com o seu vetor (`db.create(TRECHOS, {"texto": ..., "vetor": ...})`) numa tabela por organização, e a busca é exata, com o filtro de sempre. Serve até dezenas de milhares de trechos por organização:

  ```python
  q = (await llm.embed("openai/vetores", [pergunta]))[0]
  achados = await db.query(
      "SELECT texto, vector::similarity::cosine(vetor, $q) AS nota FROM trechos "
      "WHERE tenant = $tenant ORDER BY nota DESC LIMIT 5", q=q)
  ```

### 5.12 Listas e busca (`db.page`)

Toda lista que pode crescer é paginada no servidor, com filtros, ordem e busca por palavras declarados no `schemas.py`. Uma linha no service:

```python
class FaturaQuery(ListQuery):                      # schemas.py: parâmetros da URL (page, size, sort, q + filtros)
    sortable: ClassVar[tuple[str, ...]] = ("cliente", "valor")
    default_sort: ClassVar[str | None] = "-valor"
    status: Literal["aberta", "paga"] | None = None     # status = $status
    valor_from: float | None = None                     # valor >= $valor_from (e valor_to: <=)
    cliente: list[str] | None = None                    # cliente IN $cliente

class FaturaPage(Page[Fatura]):                    # { items, total, page, size, pages }
    pass

async def listar(self, data: FaturaQuery) -> FaturaPage:     # service.py
    return await db.page(FATURAS, data, FaturaPage)
```

- **Rota:** `async def listar(data: Annotated[FaturaQuery, Query()])` no `main.py` e `query: FaturaQuery` no manifesto (seção 5.8). No `contracts.ts`, `loja.listar(query?)` com os parâmetros tipados; `sort` aceita só `"cliente" | "-cliente" | "valor" | "-valor"`.
- **Trilhos:** página de até 100 itens; ordem só pelos campos de `sortable` (outro → 422 no campo `sort`); `default_sort` precisa estar em `sortable`; nomes de filtro e de ordem são validados ao importar. Parâmetro desconhecido na URL é ignorado. Valores sempre como parâmetros, nunca no texto da SurrealQL.
- **Organização:** tabela por organização ganha o filtro de `tenant` sozinha. Tabela global exige `where=` dizendo quem enxerga o quê (ex.: `where="owner = $org", org=...`); `select=` acrescenta campos calculados.
- **Busca (`q`):** por início de palavra, sem diferença de maiúscula nem de acento ("pad" acha "Padaria", "joao" acha "João"); com várias palavras, todas precisam aparecer. Os campos são declarados no boot, `db.connected(..., search={"faturas": ["cliente", "descricao"]})`; sem eles, `q` → 422 `ERRO_SEARCH_UNAVAILABLE`. Sem `sort`, a busca ordena pela relevância.
- **Ordem estável:** `sort` > relevância > `default_sort` > id, sempre com o id desempatando: a mesma página volta igual.
- **Motores:** o índice de busca se chama `FULLTEXT` no SurrealDB 3 e `SEARCH` no 2.x embutido dos testes; o core escolhe pela versão. O total é contado a partir da subconsulta, porque o motor 2.x soma índices num `count()` direto.
- **Tela:** `useListQuery(loja.listar)` + `ListView` (seção 6). Página, busca, filtros e ordem ficam na URL da tela.

### 5.13 Ciclo de vida dos dados

**Carimbos.** Toda tabela declarada ganha `created_at`, `created_by`, `updated_at` e `updated_by`, preenchidos pelo próprio banco, inclusive na SurrealQL crua do serviço. `created_*` entra uma vez e o banco recusa trocá-lo depois; `updated_*` muda a cada gravação. Quem age vai como `$cv_actor` em toda consulta do core: o `sub` da pessoa, ou `system:svc-<serviço>` nas tarefas da plataforma. Gravar um carimbo à mão é erro. Para listar do mais novo ao mais velho: `default_sort = "-created_at"` (o template já nasce assim).

**Tarefas recorrentes.** Declaradas no `workflows.py` e mantidas no Temporal pelo runner a cada boot: o que entrou na lista é criado, o que mudou é atualizado, o que saiu é removido (id `<task_queue>/<id>`). Execução sobreposta é pulada; com o Temporal fora do ar, só a última execução perdida (até 10 min) é recuperada.

```python
SCHEDULES = [Schedule("limpeza", "0 4 * * *", LimpezaWorkflow.run, Empty())]           # workflows.py: todo dia às 4h UTC
runner.worker(TASK_QUEUE, workflows=[LimpezaWorkflow], service=svc, schedules=SCHEDULES)  # main.py
```

Sem pessoa por trás, a activity roda como `system("svc-<serviço>")`. Para trabalhar em tabela por organização, percorra as organizações que têm dados: `for org in await db.tenants(TABELA): with acting_as(system(SERVICE, org)): ...`. Só tarefas da plataforma listam organizações; uma pessoa nunca. Token nenhum carrega um `sub` começando com `system:`.

**Migrações.** Mudanças de dados versionadas no `service.py`, rodadas no boot, em ordem e uma vez por banco:

```python
MIGRATIONS = [
    Migration(1, "status padrão nas faturas antigas", sql="UPDATE faturas SET status = 'aberta' WHERE status = NONE"),
    Migration(2, "recalcula totais", run=_recalcula_totais),     # função async sem argumentos
]
db.connected(tables=[TABLE], migrations=MIGRATIONS, service=SERVICE)   # main.py
```

- Versões 1, 2, 3… sem buracos. Nunca edite uma migração publicada: crie a próxima.
- A SQL roda numa transação e **sem filtro de organização**: é a mudança dos dados de todas, revisada no PR. A função roda como `system(<serviço>)`.
- O registro fica em `cv_migrations`. Uma réplica roda e as outras esperam. Se falhar, o serviço não sobe, e a próxima subida tenta de novo depois da correção. Se ficar mais de 10 min "em andamento" (a réplica caiu), outra assume.
- Índice `unique` que mudou de campos é um índice novo, criado no boot; o antigo sai por migração (`REMOVE INDEX ...`).

**A organização que sai.** O cliente que cancela baixa os dados e, 30 dias depois do encerramento, nada dele fica (alinhamento pós-N7, item 13). Sem código no serviço: com `db.connected(..., service=SERVICE)` e o bus conectado, o core atende sozinho, só para o `svc-plans`:

- `rpc.<serviço>.dados` (`DataRequest { table?, start }` → `DataPage { service, tables, table, rows, next }`): as tabelas por organização do serviço e as linhas da organização de quem pede, em páginas que cabem numa mensagem do NATS. Vetores de busca ficam de fora; texto muito longo vem cortado (o arquivo original vai no pacote).
- `events.plans.exclusao` (`PurgeRequest { tenant }`, publicado como a organização que sai): apaga as linhas dela de todas as tabelas por organização do serviço. O que mais for dela, numa tabela global ou na organização da Cogniventure, sai pelo `on_purge`: `db.connected(..., on_purge=apagar)`, uma função async sem argumentos que roda como a organização que sai (o `svc-identity` apaga vínculos, convites e a organização; o `svc-staff`, a fila e as carteiras dela).

O `svc-plans` monta o pacote (JSON e CSV de cada tabela, mais os arquivos) e, na exclusão, também apaga os arquivos (`storage.purge`). O que a lei obriga a guardar (as notas que a Cogniventure emitiu ao cliente) fica na organização da Cogniventure, não na dele.

### 5.14 Arquivos (`core/storage.py`)

O arquivo nunca passa pelo gateway nem pelo serviço: a tela envia direto ao armazenamento (RustFS no ambiente local; S3, R2, B2… em produção), por um link assinado que o serviço emite.

```python
await storage.connected(SERVICE)                                         # main.py, no lifespan
pedido = await storage.upload(data, accept=IMAGES, max_bytes=2_000_000)  # 1. link de envio (10 min)
                                                                         # 2. a tela envia (useUpload)
arquivo = await storage.keep(data.key)                                   # 3. confirma: sai da área temporária
await db.merge(registro, {"logo": arquivo.key})                          #    e o serviço guarda a chave
link = storage.url(arquivo.key)                                          # 4. link de download (5 min)
await storage.delete(arquivo.key)                                        # 5. ao apagar o registro
```

- **Chave por organização.** O envio cai em `tmp/<org>/<serviço>/…` e, confirmado, vai para `t/<org>/<serviço>/…`. Ninguém escolhe a chave. Chave de outra organização é, para quem pede, inexistente (404 `ERRO_FILE_NOT_FOUND`).
- **Tamanho e tipo na assinatura.** O serviço diz o que aceita (`accept=` tipos ou prefixos como `"image/"`) e o máximo (`max_bytes`). Fora disso sai 422 (`ERRO_FILE_TYPE`, `ERRO_FILE_TOO_LARGE`) antes de assinar, e o armazenamento recusa outro tamanho ou tipo no envio.
- **Envio não confirmado some sozinho em 1 dia.** Regra de ciclo de vida da área `tmp/`, aplicada no boot junto com o CORS (`STORAGE_CORS_ORIGINS`). Se a infraestrutura de produção não der essa permissão, o core avisa e segue.
- **Download seguro.** Imagens comuns e PDF abrem na tela. O resto, inclusive SVG e HTML, que podem trazer script, sai como anexo. O nome original vai só no `Content-Disposition`, nunca na chave.
- **A organização inteira** (seção 5.13; só tarefas da plataforma): `storage.keys()` lista as chaves dela, de todos os serviços; `storage.info(key)` dá nome, tipo e tamanho; `storage.save_file(caminho, ...)` guarda do disco, em partes e sem limite (o pacote da exportação); `storage.purge()` apaga tudo dela, guardado e temporário.
- Variáveis: `STORAGE_URL` (interno), `STORAGE_PUBLIC_URL` (o que o navegador alcança), `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_REGION`. O `keygen` cria as credenciais locais.

Exemplo pronto: o logo da organização no `svc-identity` (`/organization/logo/upload` → envio → `/organization/logo`).

### 5.15 Avisos e e-mail (`core/notify.py` e `svc-notify`)

O serviço avisa pessoas sem falar com servidor de e-mail: chama o core, e o `svc-notify` (`specs/notify.md`), o único com as credenciais SMTP, grava, mostra na tela e envia.

```python
await notify.user(sub, "Fatura paga", "A fatura 123 foi paga.", link="/faturas?id=123", action="Ver fatura")
await notify.roles("owner", "admin", title="Limite de IA perto do fim", link="/ia")       # por papel
await notify.email("pessoa@x.com", "Convite para Acme", "...", link="/convite?codigo=...")  # quem ainda não tem conta
```

- **Quem recebe:** `notify.user` e `notify.roles` avisam pessoas da organização atual (o `svc-notify` confere com o `svc-identity`, por `rpc.identity.contacts`; quem não é membro é ignorado). Não há como avisar outra organização. `notify.email` é para endereço solto: convite e senha.
- **Onde chega:** na tela, com o sino da barra superior contando os não lidos ao vivo (`notify.nova`, só para a pessoa) e a tela `notificacoes`; e por e-mail, se a pessoa não desligou na mesma tela (`send_email=False` desliga só para um aviso). `notify.email` sempre sai: é segurança.
- **Conteúdo:** texto puro (`title` até 120, `body` até 2000; parágrafos separados por linha em branco). O e-mail sai em HTML, com tudo escapado, e em texto puro. `link` é só caminho da aplicação (`/faturas?id=1`): o `svc-notify` monta `APP_URL + link`, então um aviso nunca leva a outro site.
- **Entrega:** `events.notify.send` é durável (o `svc-notify` fora do ar recebe quando voltar) e cada mensagem vira um workflow: o aviso é gravado uma vez por pessoa, mesmo com reentrega, e cada e-mail tem até 8 tentativas com espera crescente (cerca de 30 min). Servidor de e-mail fora do ar não perde aviso; endereço recusado (5xx) não insiste. Mesma `key=` = mesma intenção: não avisa duas vezes.
- **Privacidade:** depois de enviado, o conteúdo do e-mail sai do banco (links de senha e de convite não ficam guardados); fica quem, quando e o resultado, por 30 dias. Avisos lidos somem depois de 90 dias.
- **SMTP:** `SMTP_URL=smtps://usuário:senha@host:465` (TLS direto) ou `smtp://...:587` com STARTTLS, exigido em produção; serve qualquer provedor (SES, Postmark, Resend, Mailgun). No ambiente local, o Mailpit recebe tudo e nada sai para a internet.

### 5.16 Webhooks (`core/webhooks.py` e `svc-webhooks`)

**Saída:** cada organização cadastra endereços e escolhe eventos; a plataforma avisa os sistemas dela quando algo acontece. O serviço só declara e emite; quem chama o endereço é o `svc-webhooks` (`specs/webhooks.md`).

```python
WEBHOOKS = [WebhookEvent("fatura-paga", "Uma fatura foi paga.", FaturaPaga)]          # schemas.py
await webhooks.declare(WEBHOOKS)                                                       # main.py, no lifespan (depois do bus)
await webhooks.emit("fatura-paga", FaturaPaga(id=..., valor=...), key=f"paga-{id}")   # service.py
```

- **Catálogo:** o evento se chama `<serviço>.<nome>` (`faturas.fatura-paga`) e só o próprio serviço o emite. Emitir evento não declarado é erro. O `declare` publica, no boot, o nome, a descrição e o JSON Schema do modelo: a tela mostra a cada organização o que existe e o formato do `data`. Evento que sai da lista sai do catálogo.
- **Quem recebe:** só os endereços ativos da organização atual inscritos no evento (ou em todos, `*`). `data` é o modelo declarado, nunca um dict solto: não ponha nele segredo nem dado que a organização não deva ver.
- **Padrão Standard Webhooks:** POST com `{ "type", "timestamp", "data" }` e os cabeçalhos `webhook-id` (o mesmo em toda tentativa e em todo endereço: quem recebe usa para não processar duas vezes), `webhook-timestamp` e `webhook-signature` (`v1,` + HMAC-SHA256 em base64 de `{id}.{timestamp}.{corpo}`). O segredo (`whsec_...`) é de cada endereço, aparece só ao criar ou trocar e fica criptografado (`WEBHOOKS_SECRETS_KEY`, só no `svc-webhooks`). Qualquer biblioteca do padrão confere do outro lado.
- **Entrega:** durável (`events.webhooks.emit`) e com até 10 tentativas, de 5 s a 5 h entre elas (cerca de 15 h). 2xx é entregue; `410 Gone` desativa o endereço; o resto (inclusive redirect, que não é seguido, e 15 s sem resposta) tenta de novo. 20 entregas seguidas sem sucesso desativam o endereço e avisam donos e administradores (seção 5.15). O corpo da resposta não é guardado; o registro de cada entrega fica 30 dias. Sem garantia de ordem: o `timestamp` diz quando aconteceu.
- **Endereço:** `https` público, conferido ao salvar e a cada envio (SSRF, sem redirect). `http` e rede interna só com `ENVIRONMENT=development`, para testar com um receptor local.
- **Limite:** endereços por organização vêm do plano (`webhooks.enderecos`; sem plano, 20).
- **Tela `webhooks`** (donos e administradores): Endereços (cadastrar, escolher eventos, testar na hora, ativar, trocar o segredo, remover), Entregas (lista ao vivo, filtros, reenviar com o mesmo id e corpo) e Eventos (catálogo, campos e como conferir a assinatura).

**Entrada:** um sistema de fora (pagamentos, assinatura eletrônica...) avisa um serviço. A rota é pública e libera o cabeçalho da assinatura; o corpo chega ao serviço byte a byte. Se o remetente segue o mesmo padrão (Svix, Resend, Clerk...), o core confere:

```yaml
  - path: /hooks/pagamentos         # gateway/endpoints/<serviço>.yaml
    method: POST
    auth: public
    headers: [webhook-id, webhook-timestamp, webhook-signature]
    target_type: http
    target_url: http://svc-<serviço>:8000/hooks/pagamentos
```

```python
@app.post("/hooks/pagamentos")                                   # main.py, com public=("/hooks/pagamentos",)
async def pagamentos(request: Request) -> ResponseEnvelope:
    webhooks.verify(settings.segredo_pagamentos, request.headers, await request.body())   # 401 se não bate
```

Provedor com esquema próprio (`stripe-signature`, `x-hub-signature-256`) se confere com `hmac` e `core.security.same` (comparação em tempo constante). A organização dona do evento vem do conteúdo (a conta no provedor), nunca de um parâmetro da URL.

### 5.17 Módulos, planos e limites (`core/plans.py` e `svc-plans`)

Todo serviço é um **módulo** da plataforma: a organização o tem ou não pelo plano, e o menu mostra só os que ela tem. Uma plataforma (de um cliente, ou a compartilhada) é a composição dos módulos. O serviço declara o módulo e o que ele limita em um lugar só; quem guarda planos, consumo e avisos é o `svc-plans` (`specs/plans.md`).

```python
MODULE = Module(
    "Webhooks", "Eventos para os sistemas da organização", category="Integrações",
    limits=[
        Limit("enderecos", "Endereços de webhook", default=20, unit="endereços"),       # total do que existe agora
        Limit("custo", "Gasto com IA no mês", monthly=True, currency="USD"),             # consumo somado no mês
    ],
)                                                                                     # schemas.py
await plans.declare(MODULE)                         # main.py, no lifespan (depois do bus)
await plans.check("enderecos", used=total)          # antes de criar: 402 ERRO_PLAN_LIMIT se já chegou ao limite
await plans.count("enderecos", total)               # depois de criar ou remover: a tela mostra "3 de 20"
await plans.check("custo")                          # antes de gastar: quem já passou do limite do mês para aqui
await plans.use("custo", 0.0123, key=message_id)    # depois de gastar: soma no mês
await plans.enabled("crm")                          # outro módulo está ligado? (integração opcional)
```

- **Módulo:** o nome é o do serviço (sem `svc-`); `title`, `description` e `category` aparecem no menu (o grupo é a categoria), no plano e na comparação. `requires=("crm",)`: só funciona com esses ligados. `core=True`: módulo da plataforma, sempre ligado (identidade, avisos, plano, IA, webhooks). `default`: ligado quando o plano não diz nada (e para quem não tem plano); `default=False` para o que só entra quando o plano incluir.
- **Ligado ou não:** o ajuste da organização, senão o plano, senão o `default`; e só com os `requires` ligados (requisito não instalado desliga quem depende dele). Desligado: o core recusa as chamadas das pessoas da organização antes do serviço, com 402 `ERRO_PLAN_MODULE` (HTTP, evento sem reentrega e RPC); tarefa da plataforma passa. O serviço não escreve nada para isso.
- **Limite:** `<serviço>.<limite>` (`webhooks.enderecos`). Só o próprio serviço declara, conta e soma os seus; conferir vale também com o nome completo de outro serviço (o `core/llm.py` confere `ai.custo` em quem chama a IA). Limite não declarado é erro.
- **Valor:** o do plano da organização atual. O que o plano não cita, ou organização sem plano, vale o `default` declarado. `None`: sem limite; `0`: o recurso não está no plano.
- **Total × mensal:** no total, quem conta é o serviço, dono dos dados (`used=`), antes de criar; duas criações ao mesmo tempo podem passar do limite em uma. No mensal, o `svc-plans` soma o mês (UTC), uma vez por mensagem; a chamada que cruza o limite termina e as seguintes param. Em 80% e em 100%, donos e administradores recebem um aviso (seção 5.15), uma vez por mês e por patamar.
- **Resolução guardada 60 s** por processo: trocar de plano, ligar um módulo ou mudar um limite vale em até 1 min. Com o `svc-plans` fora do ar, vale a última resposta e, sem ela, nenhum limite e todo módulo ligado: plano é regra comercial, não de segurança.
- **Planos:** quem administra a plataforma (`owner` ou `admin` da organização `PLATFORM_TENANT`) cria os planos na tela, com preço (informativo), módulos incluídos, limites e se aparecem na comparação; um deles pode ser o padrão, que vale para quem não tem plano atribuído. Plano padrão ou em uso não sai. Ligar um módulo sem os `requires` (ou desligar um requisito de um ligado) é recusado.
- **Plano de uma organização:** pela tela (aba Gerenciar, com o código que a organização vê na aba Uso), com o plano e o ajuste de módulos só dela (um módulo a mais ou a menos que o plano), ou pelo serviço de pagamentos do produto, depois de confirmar o pagamento, como tarefa da plataforma: `with acting_as(system(SERVICE, org)): await plans.assign("pro", modules={"juridico": True})`. A cobrança fica no produto.
- **Situação da conta:** ativa, suspensa (atraso) ou encerrada (cancelada), com o `aviso` que a organização vê no workspace; vem em `rpc.plans.limits`. Quem inicia execuções confere antes com `await plans.situacao()` (perguntada na hora, sem os 60 s): suspensa ou encerrada, nada novo começa sozinho; o resto funciona. A mensalidade, o vencimento, a suspensão e o cancelamento são do `svc-plans` (`specs/plans.md`): o gestor muda pela aba Clientes do `/staff`, e o dono cancela e baixa os dados em Plano → Conta.
- **Limites da plataforma:** `identity.membros` (pessoas na organização), `webhooks.enderecos` (sem plano, 20), `ai.custo` (US$, a moeda dos provedores, sem conversão) e `ai.tokens`.
- **Tela `plano`:** Uso (plano, preço e uma barra por limite, ao vivo pelo aviso `plans.uso`), Conta (situação, mensalidade e vencimento; o dono pede o cancelamento, desfaz e baixa o pacote dos dados), Módulos (por categoria, o que está no plano), Planos (comparação dos públicos e do atual, com módulos e limites) e, para quem administra a plataforma, Gerenciar (planos e o plano de cada organização).
- **No frontend:** o `MODULE` de cada serviço vira `appModules` e o tipo `ModuleName` no `contracts.ts` (manifesto sem `MODULE` não gera o contrato); a tela diz o seu em `meta.module` (seção 6).

### 5.18 Observabilidade (`core/telemetry.py`)

Logs, traces e métricas saem do core, sem código no serviço. Uma linha no `main.py` (o `service.sh` já gera):

```python
install_telemetry(app, service=SERVICE)                            # depois de install_envelope e install_security
pagas = telemetry.counter("faturas_pagas", "Faturas pagas")        # métrica do serviço: cv.<serviço>.faturas_pagas
pagas.add(1, {"forma": "pix"})                                     # atributo de baixa cardinalidade; nunca a organização
```

- **Logs:** uma linha JSON por evento em stdout (em development, texto legível), com `service`, `trace_id`, `span_id`, `tenant` e `user` (o `sub`; nunca nome, e-mail, corpo nem segredo). Campos em `extra=` entram mascarados por `redact`. Toda requisição gera uma linha com método, rota (o molde `/itens/{id}`, não o id), status, duração, organização e pessoa; o log de acesso do uvicorn sai.
- **Trace ponta a ponta (OpenTelemetry):** a requisição HTTP, as chamadas HTTP de saída, cada mensagem NATS (publicar e processar, RPC), cada workflow e activity do Temporal e cada consulta ao SurrealDB (o texto da SurrealQL, nunca os valores) entram no mesmo trace: gateway → serviço → NATS → Temporal → banco. O trace começa no gateway: `traceparent` vindo de fora é ignorado, e não há baggage.
- **Id para o suporte:** toda resposta leva `x-trace-id`; o erro 500 informa esse mesmo id. Com ele se acha o trace e todos os logs da requisição, em todos os serviços.
- **Métricas:** duração das requisições HTTP (servidor e cliente, no padrão estável), das mensagens NATS com o resultado (`cv.nats.processed`: ok, retry, dropped, invalid, refused) e das consultas (`db.client.operation.duration`). Organização e pessoa nunca viram atributo de métrica (cardinalidade): ficam no trace e no log.
- **Exportação:** OTLP/HTTP para `OTEL_EXPORTER_OTLP_ENDPOINT` (Grafana Cloud, Tempo, Jaeger, Honeycomb, Datadog...). Sem a variável, nada sai do processo e os ids continuam nos logs. No ambiente local, o Grafana (`grafana/otel-lgtm`) recebe tudo e mostra traces (Tempo), métricas (Prometheus) e logs (Loki) em `http://localhost:3000`.
- **Saúde:** `GET /health` em cada serviço e no gateway confere NATS, SurrealDB e Temporal do processo (`200` ou `503` dizendo qual caiu, sem detalhe interno). É aberto, não gera trace nem log e serve ao `healthcheck` do compose e ao orquestrador de produção.

### 5.19 Cadastros declarados (`core/resources.py`)

Cadastro não se programa: declara-se no `schemas.py`, e o core faz o resto. É o primeiro nível da meta layer: a decisão que se repete vira campo de declaração, e o agente só escreve regra de negócio.

```python
class Cliente(Fields):                                             # schemas.py: os campos de quem preenche
    nome: str = Field(..., min_length=2, max_length=120, title="Nome ou razão social")
    email: Email | None = Field(None, title="E-mail")
    status: Literal["ativo", "inativo"] = Field("ativo", title="Status")
    limite: Money = Field(0, title="Limite de crédito")

CLIENTES = Resource(SERVICE, "clientes", Cliente, "Clientes", search=("nome", "email"), sort=("nome", "limite"),
                    filters=("status",), unique=("nome",), limit="clientes", write=("owner", "admin"))
RESOURCES = [CLIENTES]

db.connected(resources=RESOURCES, ...)       # main.py, no lifespan: tabela, busca e índice
resources.mount(app, RESOURCES)              # main.py, depois de install_telemetry: as 5 rotas
resources: [clientes]                        # gateway/endpoints/<serviço>.yaml: publica as rotas e o aviso ao vivo
const clientes = useResource(vendas.clientes);          // a tela: lista ao vivo, criar, editar e remover
<ResourceList resource={clientes} noun="cliente" />
```

- **O que sai da declaração:** a tabela `<serviço>_<cadastro>` (por organização, com carimbos), as rotas `GET /clientes` (página, busca, filtros e ordem pela URL), `GET /clientes/item?id=`, `POST /clientes`, `POST /clientes/update` (muda só o que veio) e `POST /clientes/remove`, o cliente tipado `vendas.clientes.{list, get, create, update, remove, meta}` no `contracts.ts` e o aviso ao vivo `vendas.clientes`. O id na API é a chave curta do registro.
- **Campos:** herdam de `Fields` (campo não declarado é recusado); `title=` é o rótulo e `description=` a ajuda na tela; numa escolha (`Literal`), `json_schema_extra={"labels": {"politica": "Política"}}` dá o rótulo de cada opção. Tipos com tela pronta: `Money`, `Email`, `Phone`, `Text` (área de texto) e os do Python (`str`, `int`, `float`, `bool`, `date`, `datetime`, `Literal[...]`, que vira escolha). `id`, `tenant` e carimbos são do banco.
- **Opções:** `search` (busca por palavras), `sort` (`created_at` sempre entra), `filters` (só campos `Literal`, `Enum` ou `bool`), `unique` (campos obrigatórios que não se repetem na organização: 409 `ERRO_RECORD_DUPLICATE`), `columns` (colunas da lista; padrão: os 5 primeiros campos que não são texto longo), `limit` (um `Limit` total do `MODULE`, conferido antes de criar e contado depois, seção 5.17) e `write` (papéis que criam, editam e removem; ler é de todo membro: 403 `ERRO_<SERVIÇO>_FORBIDDEN`).
- **Regra de negócio:** em `service.py`, com as mesmas operações do core: `await resources.get(CLIENTES, ResourceRef(id=...))`, `resources.update(CLIENTES, CLIENTES.update(id=..., status="inativo"))`, `resources.create(CLIENTES, Cliente(...))`, `resources.list(CLIENTES, CLIENTES.query(status="ativo"))`. Os modelos derivados têm o nome do modelo de campos: `ClienteItem` (o registro), `ClienteUpdate`, `ClienteQuery` e `ClientePage`, acessíveis por `CLIENTES.item`, `.update`, `.query` e `.page`. Ação nova (ex.: `POST /aprovar`) é uma rota comum: modelo de entrada em `schemas.py`, método em `service.py`, rota em `main.py` e no manifesto (`response: ClienteItem`). Para usar um modelo derivado como tipo (retorno do método, `response:` do manifesto), dê nome a ele no `schemas.py`: `ClienteItem = CLIENTES.item`.
- **Tela:** `useResource` (`core/api.ts`) junta lista e ações; `ResourceList` (catálogo, Receitas) monta a lista com busca, filtros, ordem e páginas, a criação e a edição em painel lateral e a remoção com confirmação, tudo a partir de `meta`. Colunas próprias por `columns=`; ações por linha por `rowActions=`.

### 5.20 Processos (`core/processes.py` e `svc-processos`)

O processo do cliente BPO (briefing.md §5) é um fluxo tipado que o agente de desenho edita numa conversa; o core gera o BPMN e implanta no Camunda 8, que executa. Os pacotes (`svc-financeiro`, ...) executam as ações pelos workers do core. Ninguém escreve BPMN nem FEEL.

```python
ACTIONS = [Action("conferir_pedido", "Conferir com o pedido", "Compara o documento com o pedido ou o contrato",
                  Documento, Conferencia, risk="leitura", example=Conferencia(divergente=False))]
MODELS = [ProcessModel("contas-a-pagar", Fluxo(gatilho=..., passos=[...], ligacoes=[...]))]   # schemas.py do pacote

async def conferir_pedido(self, data: Documento) -> Conferencia:   # service.py do pacote: a ação é o método de mesmo nome
    if data.valor is None:
        raise Handoff("O documento não trouxe o valor.")             # vai para a exceção do staff, com o motivo
    ...

async with processes.worker(SERVICE, ACTIONS, svc):                 # main.py, no lifespan: os jobs financeiro.<ação>
    await processes.declare(ACTIONS, MODELS)                        # ações e modelos vão ao svc-processos (desenho)
await processes.emit("pedido_proposta", dados, key=pedido.id)       # service.py: vendas.pedido_proposta inicia os processos

xml = to_bpmn(fluxo, process_id=process_id(org, pid), name="Contas a pagar", actions=catalogo)  # só o svc-processos
await camunda.deploy(xml, motor_id)                                 # implanta, inicia e entrega mensagens
await camunda.start(motor_id, {"gatilho": dados})
```

- **Ações:** cada pacote declara o que oferece: `<serviço>.<nome>`, entrada, saída, risco (`leitura`, `escrita`, `externa`, `irreversivel`), exemplo de saída (conferido contra a saída na declaração; a simulação usa) e conexões que exige. O catálogo vai por `events.processos.catalogo` e o svc-processos guarda numa tabela compartilhada; o agente só usa o que está nele. Ação que depende de integração ainda não escolhida (NFS-e, assinatura, eSocial, tribunais: briefing.md §14, decisão 6) levanta `Handoff` dizendo o que o staff faz e informa.
- **Modelos:** o pacote da área declara também o fluxo de partida de cada modelo da biblioteca que executa (`ProcessModel(<id do modelo>, Fluxo)`): o desenho de cada organização começa dali (sem ele, um agente faz o processo). Ação do próprio pacote citada num modelo e não declarada impede o boot. A biblioteca (o que a Cogniventure vende, para a descoberta) fica no svc-processos; modelo fora dela é ignorado.
- **Eventos de pacote:** `processes.emit(nome, dados, chave=, key=)` publica `<pacote>.<nome>` em `events.processos.evento`, como a organização de quem age: inicia os processos publicados com esse gatilho e, com chave, acorda a execução que espera (o mesmo caminho dos eventos do svc-integracoes). `key`: o mesmo pedido não inicia duas vezes.
- **Worker:** `processes.worker` confere no boot que cada ação tem o método `async <nome>(self, data: Entrada) -> Saída` e pega os jobs no motor (espera longa, um laço por tipo). O job age como a organização do processo (o id no motor é `p_<organização>_<processo>`, e só o svc-processos implanta). A entrada vem dos passos anteriores pelo nome do campo (o mais perto antes da ação; sem nenhum, do gatilho) e é validada; a saída vai para `<passo>`. `Handoff` ou erro de negócio (`ServiceError` < 500): com caminho de exceção no passo, vira a tarefa do staff; sem ele, incidente no motor. Erro de infraestrutura volta ao motor para nova tentativa. Módulo fora do plano vira handoff. O que cada passo fez sai em `events.processos.passo`.
- **Fluxo:** gatilho (evento, agenda em cron de 5 campos em UTC, manual, ou outro processo da organização que termina com um resultado) e passos `acao`, `agente` (sempre com exceção para o staff), `tarefa` (pessoa decide: cliente ou staff), `decisao` (caminhos com condição e exatamente um padrão), `espera` (mensagem com chave e prazo, ou horas), `paralelo` (com vários caminhos saindo abre ramos ao mesmo tempo; com vários chegando espera todos; cada ramo chega na junção sem passar por um fim) e `fim`. Cada passo grava a saída sob o próprio id (`ler_documento.valor`); condição compara um campo ou um parâmetro (`parametros.limite_aprovacao`) com um valor ou outro parâmetro, e `ou` junta alternativas num caminho só. A entrada de uma ação vem do passo mais perto antes dela com o campo; senão, do parâmetro de mesmo nome; senão, do gatilho.
- **BPMN:** `to_bpmn` gera o XML com as extensões do Camunda e o desenho (BPMN DI): a agenda vira o cron do Spring que o motor lê (com os segundos), o paralelo um `parallelGateway`, tipo do job `<serviço>.<ação>` ou `agentes.executar`, mapeamento de entrada e saída, tarefas de usuário com grupo candidato e prazo, erro `handoff` e prazo da espera que levam à tarefa do staff (prazo de 4 h), espera de mensagem como `receiveTask` com chave de correlação, e os ouvintes que avisam o svc-processos (começo, tarefa criada, espera, fim). Os parâmetros vão na saída do início: mudar um limite é uma versão nova, e cada execução usa os valores da versão em que começou. Mensagens levam a organização no nome (`<org>.banco.pago`): uma organização nunca acorda a execução de outra.
- **Versões (svc-processos):** rascunho → (revisão) → publicada → arquivada. Publicar implanta e arquiva a anterior; publicar o mesmo BPMN de novo é recusado (a impressão do BPMN fica na versão). Rascunho com ação irreversível ou conexão que a publicada não tinha passa pela revisão: a empresa pede (a conversa trava), e o staff (`operador`) aprova, o que publica, ou devolve com o motivo; o staff publica direto. O desenho lista em frases o que o rascunho muda na publicada (ou no fluxo de partida): é o que a revisão confere, porque o agente às vezes muda mais do que foi pedido. Ajustar abre um rascunho novo copiado da publicada; execuções em andamento terminam na versão em que começaram (é o Camunda). A multi-tenancy do Camunda fica desligada no ambiente local.
- **Execução (svc-processos):** evento de fora (`events.integracoes.evento`) ou de um pacote (`events.processos.evento`) inicia pela API os processos publicados daquele gatilho (uma vez por evento, mesmo com reentrega) e, com chave, entrega a mensagem à execução que espera. Quando uma execução termina, os processos publicados cujo gatilho é aquele processo (pelo modelo ou pelo id) com aquele resultado começam, com as saídas dela no gatilho (uma vez por processo; a cadeia para em 5): a primeira execução da cadeia é o projeto, que o workspace acompanha (`GET /projetos`). Cada execução tem linha do tempo, saídas dos passos, onde está e quantas exceções teve; tarefas de pessoas (aprovação do cliente: dono ou admin; exceção: `operador`, o staff na organização) com contexto, documento e prazo. Autonomia = execuções concluídas sem exceção ÷ concluídas, por processo e por versão.
- **Agente de passo:** o job `agentes.executar` roda no svc-processos: objetivo e saídas do passo, ferramentas para ler o documento do gatilho e consultar o conhecimento, `concluir` com as saídas e `pedir_ajuda` (vira handoff). Saída que faltou também vira handoff. Passo de leitura (`Step.leitura`): cada saída vem com o trecho do documento de onde saiu (ou `regra`), e o serviço confere que o trecho está no que o agente leu e traz o valor; sem isso, handoff, porque o modelo preenche o que não está lá. `Handoff(motivo, parcial=...)` leva o que o passo já tinha lido: a exceção do staff começa daí.
- **Agente de desenho:** só mexe no rascunho por operações tipadas (`adicionar_passo`, `alterar_passo`, `remover_passo`, `ligar`, `desligar`, `definir_gatilho`, `definir_parametro`, `simular`); cada uma devolve os problemas do fluxo, e `ligar` recusa na hora o que viraria erro. Se o agente diz que mudou sem chamar operação, ou deixa erros novos, o serviço pede de novo uma vez com o que faltou; se ainda faltar, a resposta diz a verdade. Até 20 alterações se desfazem.
- **Staff (`svc-staff`, módulo da Cogniventure):** staff é quem é membro da organização `PLATFORM_TENANT`; dono e admin dela são os gestores. A carteira (pessoa × organização cliente) dá o papel `operador` na organização do cliente e tira ao sair (só o svc-staff chama `rpc.identity.operador` e `rpc.identity.organizacoes`). O svc-processos avisa por `events.processos.staff` (como a organização do cliente) o que espera o staff: exceção (com o prazo da tarefa), revisão pedida e pedido de ajuda no desenho, e quando cada um termina; o svc-staff espelha numa fila por prazo, na organização da Cogniventure. Exceção que passa do prazo sem ninguém assumir sobe para os gestores (agendamento a cada minuto). Na ajuda, o staff entra na conversa de desenho do cliente e escreve como `staff`: o agente trata o pedido dele como o do cliente. A fila resolve exceção, revisão e pedido de ajuda no próprio cartão, sem trocar de organização: o svc-staff confere a carteira e chama o serviço do item na organização do cliente (`rpc.processos.fila_*`, `rpc.atendimento.*`) com quem resolve. O gestor abre os clientes (`rpc.identity.cliente`: a organização sem ninguém da Cogniventure dentro, com o convite de dono; o plano pelo `plans.assign`; a carteira) e vê os números do atendimento. Quem sai da Cogniventure (`events.identity.member-left`) sai das carteiras e perde o papel `operador` nos clientes.
- **Falar com a Cogniventure (`svc-atendimento`, da plataforma):** qualquer pessoa de um cliente pede ajuda de qualquer tela; o pedido vai para a fila do staff (`events.atendimento.staff`, o contrato da fila) com prazo de 4 horas, os operadores são avisados, e a resposta chega no sino e no histórico (`/atendimento`).
- **Servidores MCP (`svc-integracoes`):** a empresa conecta um sistema dela (ERP, CRM...) que fala MCP (Streamable HTTP) com a credencial, que fica cifrada (`INTEGRACOES_SECRETS_KEY`) e só este serviço abre. As ferramentas são listadas, sanitizadas e pinadas (impressão de nome, descrição e schema), com risco de piso externa; definição que muda vai para quarentena até alguém atualizar o servidor. Cada chamada passa pelo cliente MCP do AgentExo com as requisições pelo `core/http_client.py` (SSRF a cada uma; rede interna só no ambiente local, como o ERP de exemplo do compose, `tests/mcp_erp.py`). Os agentes chamam por `rpc.integracoes.mcp_chamar`: a credencial nunca sai daqui.
- **Agentes da empresa (`svc-agentes`):** instrução, modelo do svc-ai, ferramentas do catálogo (ler o documento, buscar no conhecimento e as MCP) com a política de cada uma (usar sozinho ou pedir aprovação: o Ask do AgentExo vira a exceção do staff) e a suíte de casos com a resposta esperada. Nasce rascunho; a suíte passando (workflow) o deixa verificado; confiável é decisão do staff; mudar o que ele faz volta a rascunho. No desenho, `usar_agente` põe um verificado num passo; no lugar de uma ação, ele cumpre o contrato dela (as saídas obrigatórias; as outras com o padrão). O passo roda por `rpc.agentes.executar`, com a mesma conferência do agente da Cogniventure; a primeira vez num processo passa pela revisão do staff.
- **Regras aprendidas:** ao resolver a exceção de um passo de agente, o staff pode ensinar o que fazer da próxima vez. A regra nasce em avaliação: um workflow refaz o caso guardado na tarefa com ela, e só se o agente chegar à saída que o staff preencheu (números a um centavo; texto normalizado) ela fica ativa e entra no contexto do agente daquele passo nas execuções seguintes; senão, reprovada com o que divergiu. O staff desativa uma regra a qualquer hora.
- **Simulação e validação:** no próprio modelo (sem motor): o caminho percorrido com os exemplos das ações e um cenário (valores, exceções, recusas), e os problemas em `erro` (impede publicar) ou `aviso` (ex.: ação irreversível sem aprovação do cliente antes em todo caminho). Condição que o motor não avalia (`verdadeiro` num campo que não é sim/não, `>` num que não é número, número comparado com texto; pelos tipos do catálogo e dos exemplos), ou dois caminhos da mesma decisão com a mesma condição, é erro: viraria incidente (ou um caminho morto) no meio da execução.
- **Motor:** o Camunda 8 roda no compose (perfil `processos`), com a API REST v2 só na rede interna (`CAMUNDA_URL`, no svc-processos e em cada pacote). Em produção o Camunda 8 Self-Managed exige licença Enterprise: decisão antes do primeiro cliente (briefing.md §5.2).

## 6. Invariantes do Frontend (A Regra do LEGO)

Telas nascem da composição de componentes existentes; a IA não inventa estrutura. As regras abaixo não dependem de boa vontade: o `vite.config.ts` as verifica em todo `npm run dev` (tela de erro na hora) e em todo `npm run build` (o build falha), dizendo o arquivo e o que corrigir.

- **Páginas apenas compõem:** `src/modules/<module_name>/page.tsx` não usa tag HTML (`<div>`, `<p>`…), nem `className`, nem `style`. Só instancia componentes de `src/components/`. Faltou peça? Cria-se um componente. Navegação e parâmetros da URL vêm do `react-router` (`useSearchParams`, `useNavigate`, `useParams`); links, por `TextLink` ou `Button to=`.
- **Rotas se montam sozinhas:** cada `page.tsx` exporta a tela (`export default`) e `export const meta: PageMeta = { title, order, access, module }`. `<module_name>/page.tsx` vira `/<module_name>`; telas a mais do módulo ficam em subpastas, até 2 níveis: `<parte>/page.tsx` vira `/<module_name>/<parte>` (subitem no menu, abaixo da tela do módulo) e `[id]/page.tsx` vira `/<module_name>/:id` (fora do menu; o valor vem de `useParams`). Nenhum registro manual. `access` diz quem vê: `"private"` (padrão: exige sessão e aparece no menu; sem sessão, vai para `/entrar?next=`), `"public"` (aberta, fora do menu, ex.: `/convite`) ou `"guest"` (só sem sessão, ex.: `/entrar` e `/cadastro`). Uma pasta de módulo só tem `page.tsx` (nela e nas subpastas) e não importa outro módulo.
- **Menu por módulo:** `module` é o módulo (serviço) da tela, tipado pelo `contracts.ts` (seção 5.17); as subtelas herdam o da tela do módulo. O menu agrupa as telas pela categoria do módulo e esconde as de módulo fora do plano da organização; aberta pelo endereço, a tela mostra o aviso de fora do plano com o caminho para `/plano`. Tela sem `module` aparece sempre, no topo.
- **Marca da organização:** a moldura usa o nome, o logo e a cor da organização ativa (tela `organizacoes`); a cor vira o token `--primary` da tela inteira.
- **Componentes têm formato único:** `src/components/<Nome>.tsx` exporta `function <Nome>` (export nomeado, nunca default) e `<Nome>Props` com cada prop documentada. O JSDoc da função começa com uma frase dizendo o que ele é e traz `@category` (uma das categorias do `vite.config.ts`: Receitas, Layout, Dados, Formatação, Formulários, Feedback, Texto, Aplicação) e `@example`: uma expressão JSX que usa o próprio componente e segue as regras de página. Componente só apresenta: recebe dados por props e não importa `core/`, `modules/` nem `App`.
- **shadcn/ui é o substrato:** os primitivos vivem em `src/components/ui/` e entram só por `npx shadcn add <nome>` (dentro de `frontend/`), sem edição à mão, para seguirem o original. Componentes do catálogo os usam; página nunca importa de `ui/`. Peça nova = `shadcn add` do primitivo + um componente do catálogo que o envolve com props simples.
- **Catálogo antes de compor:** `src/components/CATALOG.md` é gerado do próprio código. Começa por um **índice por categoria** (uma linha por componente: o que é e as props, obrigatórias primeiro) e segue com o detalhe de cada um (exemplo pronto para copiar e props tipadas). Ler o índice, abrir só o detalhe do que vai usar e copiar o exemplo; nunca editar o catálogo à mão. Cada `@example` é compilado pelo TypeScript em `npm run check` (arquivo gerado `.cv/catalog-examples.tsx`): exemplo que mente sobre as props quebra o check.
- **Consumo isolado:** toda requisição passa por `src/core/api.ts`, sempre para o gateway. Página chama serviço só pelas funções geradas em `src/core/contracts.ts`, através dos hooks `useQuery` (ler) e `useAction` (escrever); importar `request` numa página é erro. Rota, corpo e resposta são tipados; nunca se digita caminho à mão. `fetch`, `XMLHttpRequest`, `WebSocket` e `EventSource` fora dele são erro. Gatilhos assíncronos usam `newIdempotencyKey()`.
- **Receitas antes de peças:** o hook busca, o componente apresenta. Cadastro declarado no backend (seção 5.19): `useResource(modulo.cadastro)` + `ResourceList`, e a tela está pronta. `QueryView` e `QueryTable` cuidam de carregamento, erro com "Tentar de novo", vazio e dados; `ActionForm` monta o formulário a partir de uma lista de campos (conferidos contra o contrato) e mostra o erro do servidor no campo certo; `ResourcePage` é a tela de cadastro inteira (indicadores, lista e criação em painel lateral). Tempo real: `useLiveQuery` no lugar de `useQuery` para a lista se atualizar sozinha, e `useStream` para resposta em pedaços (seção 5.10). Uma ação que muda o que outra parte da tela mostra chama `refresh(contrato.funcao)`: toda consulta aberta com essa função busca de novo (ex.: marcar como lido atualiza o sino). `Money` (com `digits` para frações de centavo), `Quantity`, `DateTime` e `StatusBadge` formatam em pt-BR; `UsageMeter` mostra quanto foi usado de um limite. Tela com várias partes usa `Tabs` (a aba aberta fica no fragmento da URL, `#modelos`), e edição sem sair da tela usa `SidePanel`. Lista que pode crescer usa `useListQuery` + `ListView` (seção 5.12): busca com espera de 300 ms, filtros, ordenação no cabeçalho (seletor no celular), páginas e os estados de carregando, erro e vazio, com tudo na URL (`?q=&status=&sort=&page=`); `QueryTable` e `ResourcePage` ficam para listas curtas. Arquivo: `useUpload(contrato.xUpload, contrato.setX)` + `FileField` (envia ao escolher e mostra o erro no campo); `Picture` exibe a imagem pelo link assinado (seção 5.14). Peça avulsa só quando a receita não serve.

```tsx
export const meta: PageMeta = { title: "Faturas", order: 3 };

export default function Faturas() {
  const faturas = useQuery(loja.listar);
  const criar = useAction(loja.criar, { onSuccess: faturas.reload });
  return (
    <ResourcePage
      title="Faturas"
      query={faturas}
      rowKey={(f) => f.id}
      columns={[
        { key: "cliente", header: "Cliente" },
        { key: "valor", header: "Valor", render: (f) => <Money value={f.valor} /> },
        { key: "status", header: "Status", render: (f) => <StatusBadge value={f.status} /> },
      ]}
      create={{ label: "Nova fatura", action: criar, fields: [
        { name: "cliente", label: "Cliente", required: true },
        { name: "valor", label: "Valor (R$)", kind: "number", required: true },
      ] }}
    />
  );
}
```

- **Sessão:** `src/core/auth.ts`, sobre o `svc-identity`: `useSession` (pessoa, organização ativa, organizações e papéis) e as ações `login`, `signup`, `logout`, `switchTenant`, `createTenant`, `acceptInvite`, usadas com `useAction`; `hasRoles`/`hasAnyRole` só para exibir. O token de acesso fica só em memória: ao abrir a página a sessão volta pelo cookie de refresh, é renovada sozinha antes de expirar (e num 401) e vale para todas as abas. Quem decide o acesso é o backend. Telas prontas da plataforma: `entrar`, `cadastro`, `esqueci-senha`, `redefinir-senha`, `convite`, `membros`, `organizacoes`, `notificacoes`, `ia`, `webhooks` e `plano`, mais o sino de avisos na barra superior (seção 5.15). A tela inicial é o `workspace`: a jornada do cliente (briefing.md §3), que cada módulo de negócio completa.
- **Apenas TSX/TS:** 100% Tailwind inline nos componentes, só com os tokens semânticos do shadcn (`bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`, `border-border`, `bg-primary`, `text-destructive`) e os extras `text-success`, `text-warning`, `text-info`. O único `.css` é `src/core/theme.css` (Tailwind, base do shadcn/ui, fonte Geist, tokens claro/escuro e o CSS de bibliotecas de desenho, como o do bpmn-js, importado nele), importado por `main.tsx`. A cor da marca é o token `--primary`.

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, com /api e /health encaminhados ao gateway (GATEWAY_URL, padrão :8088)
npm run check    # build com os trilhos (regenera CATALOG.md e os exemplos) + TypeScript, inclusive nos exemplos
```

## 7. Fluxo de Trabalho

1. `./service.sh <service_name>`
2. Preencher `specs/<service_name>.md` (ou escrevê-lo antes: o scaffolder preserva).
3. Pedir à IA: *"Implemente specs/<service_name>.md em services/svc-<service_name>/ seguindo o README."*
4. Rodar `tests/<service_name>.py` (seção 5.5) e `uv run python gateway/contracts.py` (atualiza os tipos do frontend).
5. Tela: o `service.sh` já criou `src/modules/<service_name>/page.tsx`. Para adaptá-la ou criar outras, pedir à IA *"Ajuste src/modules/<module_name>/page.tsx (ou crie <module_name>/<parte>/page.tsx) com as receitas do CATALOG.md (ListView, ResourcePage, ActionForm) e as funções de core/contracts.ts, seguindo o README."*
6. Subir e testar de verdade (abaixo).
7. Conflito com o contrato → seção 8.

**Banco de provas (meta layer).** `bench/` mede quanto um modelo de código barato acerta, de primeira, dentro dos trilhos. Cada tarefa (`bench/tasks/<id>.yaml`) é um módulo de negócio: o spec e uma prova de aceitação que o modelo não vê (pelo `core/testing.py`), mais uma solução de referência. Numa cópia do repositório, o `service.sh` gera o esqueleto, o modelo recebe um pacote de contexto (trechos deste README, docstrings do core, índice do catálogo e os arquivos do serviço) e devolve só os arquivos do serviço; os trilhos conferem contrato, testes, aceitação e `npm run check`, e os erros voltam ao modelo por até 3 tentativas. Toda falha que se repete vira trilho, padrão do gerador ou receita, e o banco roda de novo.

```bash
set -a; . <arquivo fora do repositório com AWS_BEARER_TOKEN_BEDROCK>; set +a
uv run python bench/run.py --model qwen-30b          # relatório em bench/results/<data>-qwen-30b.md e .json
uv run python bench/run.py --reference               # as tarefas passam com as referências (o CI roda isto)
```

Em todo push, o CI (`.github/workflows/ci.yml`) repete o que roda à mão: testes do core, do gateway e de cada serviço, `contracts.ts` em dia, `npm run check` com o `CATALOG.md` versionado igual ao gerado, um serviço novo nascendo do `service.sh` e passando nos próprios testes, no contrato, no compose e no frontend, as tarefas do banco de provas passando com as referências, e a produção (seção 9): `compose.prod.yaml` válido, só as portas 80 e 443 abertas e a imagem do frontend construída. Vermelho no GitHub = algo quebrou o contrato.

### Ambiente local (`compose.yaml`)

Pré-requisitos: `uv` (instala o Python e as dependências sozinho), Node e Docker.

```bash
uv run python -m core.security keygen   # uma vez: cria o .env
docker compose up --build -d            # sobe Traefik, gateway, NATS, SurrealDB, Temporal, RustFS, Mailpit, Grafana e os serviços
TOKEN=$(uv run python -m core.security token ana --tenant acme)
curl -X POST localhost:8088/api/v1/<service_name>/execute -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" -d '{"payload": {}}'
docker compose down                     # para tudo (com -v, apaga também os dados)
```

O `token` da linha de comando serve para testes rápidos. Conta de verdade: `POST /api/v1/identity/signup` com `{ name, email, password, organization }` cria a pessoa e a organização e devolve o token de acesso (o refresh vai no cookie).

| Endereço | O quê |
|---|---|
| `http://localhost:5173` | Frontend (`npm run dev` em `frontend/`); crie a conta e a organização em `/cadastro` |
| `http://localhost:8088` | API, pelo Traefik (`GATEWAY_PORT`) |
| `http://localhost:8233` | Temporal UI: workflows, activities e histórico |
| `localhost:4222`, `localhost:8000`, `localhost:7233` | NATS, SurrealDB e Temporal, para serviços rodando no host |
| `localhost:9000` | Armazenamento de arquivos (RustFS, compatível com S3); o navegador envia e baixa daqui por link assinado |
| `http://localhost:8025` | Mailpit: todo e-mail que a plataforma envia no ambiente local (convites, senha, avisos) |
| `http://localhost:3000` | Grafana: traces, métricas e logs de todos os serviços (busque pelo `x-trace-id` de uma resposta) |

Toda porta é publicada só em `127.0.0.1`. O SurrealDB ganha no boot o usuário de banco dos serviços (`surreal-init`); a senha root fica só com ele.

## 8. Cláusula de Interrupção & `sprint.md` (Circuit Breaker)

Se qualquer solicitação de usuário, dependência técnica ou implementação exigir:

- criar arquivo ou pasta fora da topologia da seção 1 — inclusive um 5º arquivo ou uma subpasta em `services/svc-<service_name>/`;
- importar código de outro serviço;
- implementar autenticação, autorização, hash de senha, verificação de token ou acesso de rede fora de `core/` (seção 5.7);
- abrir uma rota (`public=`) que o spec não declara pública;
- ler ou gravar dados sem o filtro de organização: `db.query_shared` fora dos serviços de plataforma (seção 5.9), ou organização vinda do corpo (a única exceção são as migrações versionadas, seção 5.13);
- chamar provedor de IA, montar cliente `openai` ou Agno, ou guardar chave de provedor fora de `core/llm.py` e do `svc-ai` (a exceção é o banco de provas, `bench/`: ferramenta de desenvolvimento que roda com a chave de quem a usa e que nenhum serviço importa);
- alterar o envelope padrão de I/O;
- violar ou desviar do que está declarado em `specs/<service_name>.md`;

**a IA deve interromper a ordem imediatamente.** Não adaptar, não tentar "resolver sozinha", não criar arquivos provisórios.

A IA apenas registra o bloqueio em `sprint.md`, com no máximo 400 caracteres, sem saudações, introduções ou rodeios, estritamente neste formato:

```text
- [YYYY-MM-DD HH:MM] [TARGET]: <conflito contratual direto + proposta mínima de solução técnica para aprovação>
```

## 9. Produção

Um host com Docker e um domínio bastam: o `compose.prod.yaml` se sobrepõe ao `compose.yaml` e muda só a estrutura. As diferenças de ambiente chegam a todos os serviços, inclusive aos que o `service.sh` criar depois, pelo `.env`.

```bash
uv run python -m core.security keygen --production app.minhaempresa.com   # .env de produção (chaves e senhas novas)
# preencher SMTP_URL no .env; apontar o DNS de app.minhaempresa.com e files.app.minhaempresa.com para o host
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

- **Borda:** HTTPS com certificado do Let's Encrypt (renovação automática), HTTP redireciona, HTTP/2 e só as portas 80 e 443 abertas. O Traefik descobre as rotas por um proxy do Docker somente leitura, sem receber o socket. A tela fica em `DOMAIN` e os arquivos em `files.DOMAIN` (link assinado, seção 5.14).
- **Frontend:** `frontend/Dockerfile` faz o build com os trilhos e serve o `dist/` por um nginx sem root, com CSP (só scripts do próprio site; imagem e envio só do próprio site e do armazenamento), HSTS, `X-Frame-Options`, cache longo nos arquivos com hash e o `index.html` conferido a cada visita.
- **NATS:** sem acesso anônimo. Os serviços usam o usuário `services`; o gateway, que fala com a internet, tem um usuário restrito: publica só `events.<serviço>.trigger` e lê os avisos ao vivo. Ele não chama RPC (como o `rpc.ai.resolve`, que devolve chave de IA) nem publica evento de outro serviço.
- **Dados:** payloads do Temporal cifrados (`TEMPORAL_PAYLOAD_KEY`; trocar a chave torna ilegíveis os workflows em andamento), SurrealDB sem root, `ENVIRONMENT=production` em tudo (HSTS e CSP na API, cookie de sessão `Secure`, SMTP com TLS, sem `/docs`, sem rede interna para webhooks e IA). Toda porta de infraestrutura fica só na rede interna.
- **Fora do host:** e-mail pelo `SMTP_URL` (SES, Postmark, Resend...); observabilidade pelo `OTEL_EXPORTER_OTLP_ENDPOINT` (vazio: só logs em stdout). Mailpit e Grafana local não sobem.
- **Por conta da operação:** backup dos volumes (`surreal-data`, `storage-data`, `temporal-data`) e dos segredos do `.env`. O Temporal e o armazenamento do compose servem a um host; para alta disponibilidade, Temporal Cloud (`TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY`) e um S3 (`STORAGE_URL`, `STORAGE_PUBLIC_URL` e credenciais) entram pelo `.env`, sem mudar código.
- **Conferido no CI:** a configuração de produção (`docker compose ... config`) e o build da imagem do frontend, em todo push.
- **Instalação dedicada (um cliente, Enterprise):** o mesmo código e as mesmas imagens, só com os módulos de negócio do cliente. `keygen --production <domínio> --modules crm,vendas` grava `MODULES` e `COMPOSE_PROFILES` no `.env`: o compose sobe a plataforma e só esses serviços (cada serviço de negócio tem `profiles: [modules, <nome>]`, que o `service.sh` gera), o gateway publica só as rotas deles e da plataforma, o `svc-plans` só os lista nos planos e o menu esconde o que não está instalado. Sem `--modules`, `MODULES` fica vazio e `COMPOSE_PROFILES=modules`: todos os módulos (instalação compartilhada, onde o plano de cada organização liga o que ela usa, seção 5.17).
- **Primeira implantação da Cogniventure (roteiro, em ordem):**
  1. Subir como acima (`keygen --production`, `SMTP_URL`, `up -d`).
  2. O fundador cria a conta e a organização Cogniventure em `/cadastro`; o código dela aparece em Plano → Uso.
  3. `PLATFORM_TENANT=<código>` no `.env` e `up -d` de novo: os serviços o leem na subida (quem é dela é staff).
  4. Em Plano → Gerenciar: um plano não público com o módulo Staff e sem limite de pessoas, atribuído à própria Cogniventure (sem ele, fica no plano padrão, sem a área `/staff`).
  5. Em `/ia`: o provedor da plataforma `cv` com os apelidos `agente` e `desenho` (seção 5.11). Guarde a `AI_SECRETS_KEY` com o backup: sem ela, as chaves cadastradas não abrem.
  6. Em `/membros`: convidar o staff (admin = gestor das carteiras).
  7. Em `/staff` → Clientes: abrir o primeiro cliente (organização, plano, quem cuida, a mensalidade e o vencimento combinados e o convite do dono por e-mail).
  8. A cobrança dos clientes roda na própria Cogniventure: em `/integracoes`, a caixa de entrada (as cobranças saem dela) e o banco; em `/processos`, adicionar o Faturamento e cobrança da biblioteca e publicar (na Cogniventure, o dono e o admin fazem o papel do staff). No dia 1, o fechamento inicia uma execução por cliente pagante (ou na hora: `POST /api/v1/plans/fechamento`); a nota fiscal vai ao staff até a integração de NFS-e; a vencida há 7 dias chega ao gestor, que suspende o cliente na aba Clientes. Atualizou o pacote financeiro? Ajuste e publique o Faturamento de novo, para o BPMN levar as entradas novas.
