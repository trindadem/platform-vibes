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
├── LICENSE                      # MIT: uso livre, mantendo o aviso de copyright
├── sprint.md                    # Log de bloqueios e revisões de contrato (seção 8)
├── service.sh                   # Scaffolder determinístico canônico (seção 3)
├── pyproject.toml               # Dependências Python únicas: core, gateway e serviços
├── uv.lock                      # Versões exatas das dependências Python (gerado pelo uv, versionado)
├── compose.yaml                 # Ambiente local: Traefik, NATS, Temporal, SurrealDB, RustFS, Mailpit, Grafana, gateway e serviços
├── .github/workflows/ci.yml     # CI: testes, trilhos, contratos e scaffolder em todo push (seção 7)
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
│   ├── llm.py                   # IA: qualquer API compatível com a da OpenAI, chaves no svc-ai (seção 5.11)
│   ├── storage.py               # Arquivos: S3 compatível, envio direto por link assinado, isolado por organização (seção 5.14)
│   ├── notify.py                # Avisos na tela e por e-mail, entregues pelo svc-notify (seção 5.15)
│   ├── webhooks.py              # Webhooks: eventos para os sistemas das organizações e conferência dos que chegam (seção 5.16)
│   ├── plans.py                 # Planos e limites: o que cada organização pode usar, conferido no serviço (seção 5.17)
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
        ├── modules/             # Domínios de negócio isolados
        │   └── <module_name>/
        │       └── page.tsx     # A tela: vira a rota /<module_name> e o item do menu
        ├── core/                # 1 arquivo por recurso: api.ts, auth.ts, contracts.ts (gerado), theme.css
        ├── App.tsx              # Router plano, montado a partir de src/modules
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
- cria `services/svc-<service_name>/` com os 4 arquivos já amarrados (activities, workflow, ingress HTTP + NATS, worker), uma lista paginada com busca (`GET /records`, seção 5.12) e as listas vazias `SCHEDULES` e `MIGRATIONS` já ligadas (seção 5.13);
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
- **Dependências:** únicas, no `pyproject.toml` da raiz, com as versões exatas travadas no `uv.lock`. Serviço não declara dependência própria. Dependência nova: `uv add <pacote>` (atualiza os dois arquivos juntos). Todo comando Python roda com `uv run`, que na primeira vez cria o `.venv` com as versões do lock.
- **Imagem:** serviços e gateway usam `services/Dockerfile` (`SERVICE=<service_name>` ou `APP_DIR=gateway`); a imagem instala exatamente o `uv.lock` (lock defasado derruba o build), já com o bytecode compilado (o container sobe sem recompilar as bibliotecas), copia apenas `core/` e a pasta do app e roda sem root.
- **Testes:** em `tests/<service_name>.py`, um serviço por processo, sem infraestrutura: o NATS vira dublê e o SurrealDB roda embutido em memória (`AsyncSurreal("mem://")`, do próprio SDK), com as tabelas e os índices do boot, executando a SurrealQL de verdade. O motor embutido é o 2.x e o servidor é o 3.x: o core cuida das diferenças conhecidas (seção 5.12).

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
| `security.py` | `install_security(app, service, public)`, `principal`, `require(*papéis)`, `current()`, `current_tenant()`, `acting_as(principal)`, `system(service, tenant)`, `issue_token`, `verify_token`, `hash_password`, `verify_password`, `assert_public_url`, `redact`, `new_secret`, `same` |
| `nats_bus.py` | `bus.connected(service)`, `bus.publish(subject, model, msg_id)`, `bus.subscribe(subject, handler, model)`, `bus.message_id()`, `bus.request(...)`, `bus.respond(...)`, `bus.live(tópico, model, user=None)`, `bus.live_feed(principal)` |
| `temporal_runner.py` | `@activities(prefixo)`, `runner.worker(task_queue, workflows, service, schedules)`, `runner.start_workflow(run, arg, task_queue, id)`, `Schedule` |
| `surreal.py` | `db.connected(tables=[TABLE], shared=[...], unique={...}, search={...}, migrations=[...], service=SERVICE)`, `db.query(sql, **params)`, `db.query_shared(...)`, `db.page(TABLE, query, ModeloPage)`, `db.create`, `db.select`, `db.merge`, `db.delete`, `db.tenants(TABLE)`, `ListQuery`, `Page`, `Migration` |
| `http_client.py` | `http.get`, `http.post`, `http.request` — só para APIs externas; nunca guarda cookie entre chamadas |
| `llm.py` | `llm.ask(modelo, prompt, instructions, output, tools, images)`, `llm.stream(...)`, `llm.embed(modelo, textos)`, `llm.agent(...)`, `Image` — o único jeito de chamar IA (seção 5.11) |
| `storage.py` | `storage.connected(service)`, `storage.upload(pedido, accept, max_bytes, folder)`, `storage.keep(key)`, `storage.url(key, ttl, filename, content_type)`, `storage.delete(key)`, `UploadRequest`, `Upload`, `KeepRequest`, `StoredFile`, `IMAGES` (seção 5.14) |
| `notify.py` | `notify.user(sub, title, body, link, action, send_email, key)`, `notify.roles(*papéis, title=...)`, `notify.email(endereço, title, body, link, action, key)` — o único jeito de avisar alguém (seção 5.15) |
| `webhooks.py` | `WebhookEvent(nome, descrição, Modelo)`, `webhooks.declare(lista)`, `webhooks.emit(nome, modelo, key)`, `webhooks.verify(segredo, cabeçalhos, corpo)`, `sign`, `new_secret` (seção 5.16) |
| `plans.py` | `Limit(nome, descrição, default, monthly, unit, currency)`, `plans.declare(lista)`, `plans.check(nome, used=)`, `plans.use(nome, quantidade, key)`, `plans.count(nome, total)`, `plans.limits()`, `plans.assign(plano)` (seção 5.17) |
| `telemetry.py` | `install_telemetry(app, service, edge, health)`, `telemetry.counter(nome, descrição)`, `telemetry.histogram(nome, descrição)` (seção 5.18) |

Erro de negócio do spec §4: `raise ServiceError("ERRO_<UPPER>_<CASO>", "mensagem", status=409)`. Ele sai no envelope pelo HTTP e, com status < 500, nunca é re-tentado pelo Temporal.

Erros de validação (422) saem com mensagens em pt-BR e os limites do próprio modelo ("Mínimo de 2 caracteres.", "Deve ser maior que 0."), e cada detalhe aponta o campo em `loc`. As tabelas declaradas em `db.connected(...)` são garantidas no boot (no SurrealDB 3, consultar tabela inexistente é erro; assim a primeira listagem devolve `[]`); tabela não declarada é erro. Valor repetido num índice `unique` sai como 409 `ERRO_RECORD_DUPLICATE`, sem ecoar o valor. Consulta com vários comandos devolve o resultado do primeiro, mas o core confere todos: o erro de qualquer um chega ao serviço (o SDK só conferia o primeiro).

### 5.7 Segurança (`core/security.py`)

Segurança não se implementa por serviço: importa-se do core. Proibido reimplementar autenticação, hash de senha, verificação de token ou proteção de URL.

- **Nega por padrão:** `install_security(app, service=SERVICE)` exige token válido em **toda** rota, inclusive as que a IA criar depois. Abrir é explícito e só se o spec §2 declarar: `public=("/rota",)`. A única exceção é `/health` (seção 5.18), que só diz se as dependências respondem. Papéis: `Depends(require("admin"))`.
- **Identidade vem do token:** quem chama é o `Principal` (usuário, organização ativa e papéis nela; `Depends(principal)` ou `current()`), nunca um campo do payload.
- **Tokens:** JWT com chave assimétrica. EdDSA com chaves próprias ou JWKS de um provedor (Auth0, Clerk, Keycloak…). `none` e HS256 são recusados; `iss`, `aud`, `exp` e `sub` são obrigatórios. Só o serviço que faz login tem a chave privada.
- **Login e sessão:** o `svc-identity` (`specs/identity.md`) é o único emissor de tokens e o único container com `AUTH_PRIVATE_KEY`: cadastro, login, senha esquecida (link por e-mail de 30 min, uso único, que derruba as sessões), organizações, convites e membros. Token de acesso de 15 min; refresh de 30 dias só no cookie `cv_refresh` (HttpOnly, SameSite=Strict, `Path=/api/v1/identity`, Secure em produção), nunca no corpo, trocado a cada uso; um refresh antigo que reaparece derruba a sessão inteira.
- **Senhas:** só `hash_password` / `verify_password` (Argon2id, fora do event loop). Nunca md5, sha ou hash próprio.
- **Payload:** modelos de entrada usam `extra="forbid"` (campo não declarado é recusado); erro de validação nunca ecoa o valor recebido.
- **Banco:** só `core.surreal`, com parâmetros (`$nome`) e nunca f-string; login como usuário do banco, nunca root.
- **Rede:** URL externa só por `core.http_client` (bloqueia SSRF e não segue redirects). Rede interna (`allow_private=True`) só com `ENVIRONMENT=development`: em produção o próprio core recusa. NATS em produção com `NATS_CREDS` e permissões por subject.
- **IA:** chave de provedor só no `svc-ai`, criptografada; o serviço chama modelo só pelo `core/llm.py`, sem ver a chave (seção 5.11).
- **Respostas:** cabeçalhos de segurança em toda resposta (HSTS e CSP em produção), `cache-control: no-store`, erro 500 sem detalhe interno, CORS só com origens listadas (`*` é recusado).
- **Segredos e logs:** segredos só no `.env` (fora do Git). Antes de logar dados, `redact(...)`.
- **Configuração insegura não sobe:** falta de chave, CORS `*`, JWKS sem https ou par de chaves trocado impedem o boot.

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
| `NATS_URL`, `NATS_CREDS` | Mensageria; `.creds` obrigatório em produção |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY` | Orquestração; a API key liga TLS (Temporal Cloud) |
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
    nats_subject: events.billing.trigger
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

- **Trilhos do manifesto:** `target_url` só aponta para `http://svc-<service>:8000/` e `nats_subject` só para `events.<service>.*`, ou seja, nunca para outro serviço ou para fora. O nome do arquivo é igual ao `service`. Rota pública não tem `roles` nem parâmetros no caminho. Campo desconhecido é erro.
- **HTTP:** repassa corpo (byte a byte), query string e só os cabeçalhos `authorization`, `content-type`, `accept` e `x-request-id`; `headers: [stripe-signature]` libera outros numa rota HTTP POST (a assinatura de um webhook que chega, seção 5.16), nunca os de sessão ou roteamento (`cookie`, `host`, `x-forwarded-*`...). O serviço verifica o token de novo e continua o trace do gateway (`traceparent`, seção 5.18). Parâmetros de caminho são codificados (`../` não atravessa). Serviço fora do ar → 502; lento → 504.
- **NATS:** o corpo precisa ser um objeto JSON; a resposta é `202` com o `message_id`. O cabeçalho `Idempotency-Key` faz a mesma requisição repetida virar a mesma mensagem e o mesmo workflow, com a chave isolada por usuário.
- **Limites:** corpo acima de 1 MiB → 413, no gateway (que lê o corpo em pedaços). O Traefik não usa o middleware `buffering`, que seguraria a resposta inteira e quebraria o streaming. Rate limit por IP no Traefik (50 req/s, rajada de 100). O nome de serviço `live` é reservado: `/api/v1/live` é do gateway.
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
- **Listas:** `db.page` (seção 5.12) filtra a organização sozinho, como `create` e `select`.
- **Tabelas globais:** `shared=[...]` e `db.query_shared(...)`, sem filtro de organização. Só os serviços de plataforma as usam: o de identidade (usuários, organizações, sessões), o de IA (provedores e modelos, com o dono no campo `owner`), o de avisos (registro de e-mails e preferências de cada pessoa), o de webhooks (catálogo de eventos) e o de planos (catálogo de limites, planos e o plano de cada organização, no campo `org`).
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
- **Agno por baixo:** telemetria, banco, memória e conhecimento do Agno ficam desligados, porque não respeitam a organização. Histórico de conversa e documentos ficam em tabelas do serviço, pelo `core.surreal`.
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

### 5.17 Planos e limites (`core/plans.py` e `svc-plans`)

Cada organização tem um plano, e o plano diz quanto ela pode usar. O serviço declara o que limita e confere com uma linha; quem guarda planos, consumo e avisos é o `svc-plans` (`specs/plans.md`).

```python
LIMITS = [
    Limit("enderecos", "Endereços de webhook", default=20, unit="endereços"),           # total do que existe agora
    Limit("custo", "Gasto com IA no mês", monthly=True, currency="USD"),                 # consumo somado no mês
]                                                                                         # schemas.py
await plans.declare(LIMITS)                         # main.py, no lifespan (depois do bus)
await plans.check("enderecos", used=total)          # antes de criar: 402 ERRO_PLAN_LIMIT se já chegou ao limite
await plans.count("enderecos", total)               # depois de criar ou remover: a tela mostra "3 de 20"
await plans.check("custo")                          # antes de gastar: quem já passou do limite do mês para aqui
await plans.use("custo", 0.0123, key=message_id)    # depois de gastar: soma no mês
```

- **Nome:** `<serviço>.<limite>` (`webhooks.enderecos`). Só o próprio serviço declara, conta e soma os seus; conferir vale também com o nome completo de outro serviço (o `core/llm.py` confere `ai.custo` em quem chama a IA). Limite não declarado é erro.
- **Valor:** o do plano da organização atual. O que o plano não cita, ou organização sem plano, vale o `default` declarado. `None`: sem limite; `0`: o recurso não está no plano.
- **Total × mensal:** no total, quem conta é o serviço, dono dos dados (`used=`), antes de criar; duas criações ao mesmo tempo podem passar do limite em uma. No mensal, o `svc-plans` soma o mês (UTC), uma vez por mensagem; a chamada que cruza o limite termina e as seguintes param. Em 80% e em 100%, donos e administradores recebem um aviso (seção 5.15), uma vez por mês e por patamar.
- **Resolução guardada 60 s** por processo: trocar de plano ou mudar um limite vale em até 1 min. Com o `svc-plans` fora do ar, vale a última resposta e, sem ela, nenhum limite: plano é regra comercial, não de segurança.
- **Planos:** quem administra a plataforma (`owner` ou `admin` da organização `PLATFORM_TENANT`) cria os planos na tela, com preço (informativo), limites e se aparecem na comparação; um deles pode ser o padrão, que vale para quem não tem plano atribuído. Plano padrão ou em uso não sai.
- **Troca de plano:** pela tela (aba Gerenciar, com o código que a organização vê na aba Uso) ou pelo serviço de pagamentos do produto, depois de confirmar o pagamento, como tarefa da plataforma: `with acting_as(system(SERVICE, org)): await plans.assign("pro")`. A cobrança fica no produto.
- **Limites da plataforma:** `identity.membros` (pessoas na organização), `webhooks.enderecos` (sem plano, 20), `ai.custo` (US$, a moeda dos provedores, sem conversão) e `ai.tokens`.
- **Tela `plano`:** Uso (plano, preço e uma barra por limite, ao vivo pelo aviso `plans.uso`), Planos (comparação dos públicos e do atual) e, para quem administra a plataforma, Gerenciar (planos e atribuição).

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
- **Métricas:** duração das requisições HTTP (servidor e cliente, no padrão estável), das mensagens NATS com o resultado (`cv.nats.processed`: ok, retry, dropped, invalid) e das consultas (`db.client.operation.duration`). Organização e pessoa nunca viram atributo de métrica (cardinalidade): ficam no trace e no log.
- **Exportação:** OTLP/HTTP para `OTEL_EXPORTER_OTLP_ENDPOINT` (Grafana Cloud, Tempo, Jaeger, Honeycomb, Datadog...). Sem a variável, nada sai do processo e os ids continuam nos logs. No ambiente local, o Grafana (`grafana/otel-lgtm`) recebe tudo e mostra traces (Tempo), métricas (Prometheus) e logs (Loki) em `http://localhost:3000`.
- **Saúde:** `GET /health` em cada serviço e no gateway confere NATS, SurrealDB e Temporal do processo (`200` ou `503` dizendo qual caiu, sem detalhe interno). É aberto, não gera trace nem log e serve ao `healthcheck` do compose e ao orquestrador de produção.

## 6. Invariantes do Frontend (A Regra do LEGO)

Telas nascem da composição de componentes existentes; a IA não inventa estrutura. As regras abaixo não dependem de boa vontade: o `vite.config.ts` as verifica em todo `npm run dev` (tela de erro na hora) e em todo `npm run build` (o build falha), dizendo o arquivo e o que corrigir.

- **Páginas apenas compõem:** `src/modules/<module_name>/page.tsx` não usa tag HTML (`<div>`, `<p>`…), nem `className`, nem `style`. Só instancia componentes de `src/components/`. Faltou peça? Cria-se um componente. Navegação e parâmetros da URL vêm do `react-router` (`useSearchParams`, `useNavigate`); links, por `TextLink` ou `Button to=`.
- **Rotas se montam sozinhas:** cada `page.tsx` exporta a tela (`export default`) e `export const meta: PageMeta = { title, order, access }`. Vira a rota `/<module_name>`, sem registro manual. `access` diz quem vê: `"private"` (padrão: exige sessão e aparece no menu; sem sessão, vai para `/entrar?next=`), `"public"` (aberta, fora do menu, ex.: `/convite`) ou `"guest"` (só sem sessão, ex.: `/entrar` e `/cadastro`). Um módulo tem só `page.tsx` e não importa outro módulo.
- **Componentes têm formato único:** `src/components/<Nome>.tsx` exporta `function <Nome>` (export nomeado, nunca default) e `<Nome>Props` com cada prop documentada. O JSDoc da função começa com uma frase dizendo o que ele é e traz `@category` (uma das categorias do `vite.config.ts`: Receitas, Layout, Dados, Formatação, Formulários, Feedback, Texto, Aplicação) e `@example`: uma expressão JSX que usa o próprio componente e segue as regras de página. Componente só apresenta: recebe dados por props e não importa `core/`, `modules/` nem `App`.
- **shadcn/ui é o substrato:** os primitivos vivem em `src/components/ui/` e entram só por `npx shadcn add <nome>` (dentro de `frontend/`), sem edição à mão, para seguirem o original. Componentes do catálogo os usam; página nunca importa de `ui/`. Peça nova = `shadcn add` do primitivo + um componente do catálogo que o envolve com props simples.
- **Catálogo antes de compor:** `src/components/CATALOG.md` é gerado do próprio código. Começa por um **índice por categoria** (uma linha por componente: o que é e as props, obrigatórias primeiro) e segue com o detalhe de cada um (exemplo pronto para copiar e props tipadas). Ler o índice, abrir só o detalhe do que vai usar e copiar o exemplo; nunca editar o catálogo à mão. Cada `@example` é compilado pelo TypeScript em `npm run check` (arquivo gerado `.cv/catalog-examples.tsx`): exemplo que mente sobre as props quebra o check.
- **Consumo isolado:** toda requisição passa por `src/core/api.ts`, sempre para o gateway. Página chama serviço só pelas funções geradas em `src/core/contracts.ts`, através dos hooks `useQuery` (ler) e `useAction` (escrever); importar `request` numa página é erro. Rota, corpo e resposta são tipados; nunca se digita caminho à mão. `fetch`, `XMLHttpRequest`, `WebSocket` e `EventSource` fora dele são erro. Gatilhos assíncronos usam `newIdempotencyKey()`.
- **Receitas antes de peças:** o hook busca, o componente apresenta. `QueryView` e `QueryTable` cuidam de carregamento, erro com "Tentar de novo", vazio e dados; `ActionForm` monta o formulário a partir de uma lista de campos (conferidos contra o contrato) e mostra o erro do servidor no campo certo; `ResourcePage` é a tela de cadastro inteira (indicadores, lista e criação em painel lateral). Tempo real: `useLiveQuery` no lugar de `useQuery` para a lista se atualizar sozinha, e `useStream` para resposta em pedaços (seção 5.10). Uma ação que muda o que outra parte da tela mostra chama `refresh(contrato.funcao)`: toda consulta aberta com essa função busca de novo (ex.: marcar como lido atualiza o sino). `Money` (com `digits` para frações de centavo), `Quantity`, `DateTime` e `StatusBadge` formatam em pt-BR; `UsageMeter` mostra quanto foi usado de um limite. Tela com várias partes usa `Tabs` (a aba aberta fica no fragmento da URL, `#modelos`), e edição sem sair da tela usa `SidePanel`. Lista que pode crescer usa `useListQuery` + `ListView` (seção 5.12): busca com espera de 300 ms, filtros, ordenação no cabeçalho (seletor no celular), páginas e os estados de carregando, erro e vazio, com tudo na URL (`?q=&status=&sort=&page=`); `QueryTable` e `ResourcePage` ficam para listas curtas. Arquivo: `useUpload(contrato.xUpload, contrato.setX)` + `FileField` (envia ao escolher e mostra o erro no campo); `Picture` exibe a imagem pelo link assinado (seção 5.14). Peça avulsa só quando a receita não serve.

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

- **Sessão:** `src/core/auth.ts`, sobre o `svc-identity`: `useSession` (pessoa, organização ativa, organizações e papéis) e as ações `login`, `signup`, `logout`, `switchTenant`, `createTenant`, `acceptInvite`, usadas com `useAction`; `hasRoles`/`hasAnyRole` só para exibir. O token de acesso fica só em memória: ao abrir a página a sessão volta pelo cookie de refresh, é renovada sozinha antes de expirar (e num 401) e vale para todas as abas. Quem decide o acesso é o backend. Telas prontas da plataforma: `entrar`, `cadastro`, `esqueci-senha`, `redefinir-senha`, `convite`, `membros`, `organizacoes`, `notificacoes`, `ia`, `webhooks` e `plano`, mais o sino de avisos na barra superior (seção 5.15).
- **Apenas TSX/TS:** 100% Tailwind inline nos componentes, só com os tokens semânticos do shadcn (`bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`, `border-border`, `bg-primary`, `text-destructive`) e os extras `text-success`, `text-warning`, `text-info`. O único `.css` é `src/core/theme.css` (Tailwind, base do shadcn/ui, fonte Geist e tokens claro/escuro), importado por `main.tsx`. A cor da marca é o token `--primary`.

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
5. Tela: pedir à IA *"Crie src/modules/<module_name>/page.tsx com as receitas do CATALOG.md (ResourcePage, QueryTable, ActionForm) e as funções de core/contracts.ts, seguindo o README."*
6. Subir e testar de verdade (abaixo).
7. Conflito com o contrato → seção 8.

Em todo push, o CI (`.github/workflows/ci.yml`) repete o que roda à mão: testes do core, do gateway e de cada serviço, `contracts.ts` em dia, `npm run check` com o `CATALOG.md` versionado igual ao gerado, e um serviço novo nascendo do `service.sh` e passando nos próprios testes, no contrato, no compose e no frontend. Vermelho no GitHub = algo quebrou o contrato.

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
- chamar provedor de IA, montar cliente `openai` ou Agno, ou guardar chave de provedor fora de `core/llm.py` e do `svc-ai`;
- alterar o envelope padrão de I/O;
- violar ou desviar do que está declarado em `specs/<service_name>.md`;

**a IA deve interromper a ordem imediatamente.** Não adaptar, não tentar "resolver sozinha", não criar arquivos provisórios.

A IA apenas registra o bloqueio em `sprint.md`, com no máximo 400 caracteres, sem saudações, introduções ou rodeios, estritamente neste formato:

```text
- [YYYY-MM-DD HH:MM] [TARGET]: <conflito contratual direto + proposta mínima de solução técnica para aprovação>
```
