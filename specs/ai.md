# Spec: ai

## 1. Objetivo Operacional
Deixar qualquer serviço usar IA de qualquer provedor compatível com a API da OpenAI sem tocar em chave: guarda
provedores (endereço + chave criptografada) da plataforma e de cada organização, o catálogo curado de modelos e o
uso com custo por organização. Os serviços chamam pelo `core/llm.py` (README §5.11).
Módulo `ai` ("IA", categoria Integrações), da plataforma: sempre ligado; os limites dele são `ai.custo` e
`ai.tokens` (README §5.17).

## 2. Contrato de Entrada e Saída
Todas as rotas exigem token; gerenciar exige `owner` ou `admin` (provedor da plataforma: `owner`/`admin` da
organização `PLATFORM_TENANT`).
- `GET /providers` → `ProviderList { items: Provider[] }` · `Provider { id, name, slug, base_url, key_hint, scope }`
  (`scope`: `organization` | `platform`; a chave nunca volta, só `…abcd` em `key_hint`)
- `POST /providers` (`ProviderInput { name, slug, base_url, api_key?, scope }`) → `Provider`
- `POST /providers/remove` (`ProviderRef { id }`) → `ProviderList`
- `POST /providers/discover` (`ProviderRef { id }`) → `Discovered { found, added }`
- `GET /models?q=&enabled=&kind=&sort=&page=&size=` (`ModelQuery`, lista paginada, README §5.12) → `ModelPage`
  com `Model { id, name, provider, model_id, alias, kind, enabled, price_input, price_output, scope }`
  (`name` = `<slug>/<alias ou model_id>`, o que se passa ao `llm.*`). Busca por id ou apelido; membro só recebe
  os liberados.
- `POST /models` (`ModelInput { provider, model_id, kind }`) → `Model` (cadastro manual, para provedor sem `/models`)
- `POST /models/update` (`ModelUpdate { id, enabled?, alias?, kind?, price_input?, price_output? }`) → `Model`
- `GET /usage` → `UsageSummary { month, calls, input_tokens, output_tokens, cost, items }` (mês corrente, UTC)
- `GET /providers` também diz `manages_platform`: se quem pede administra os provedores da plataforma. Para as
  outras organizações, o provedor da plataforma vem sem `base_url` e sem `key_hint` (endereço interno e chave).
- Ao vivo (`bus.live`): `ai.uso` (`Recorded { id, model, service, cost, at }`) para a organização a cada uso gravado.
- RPC `rpc.ai.resolve` (`ResolveRequest { model, kind }`) → `Resolved { provider, scope, model, base_url, api_key,
  price_input, price_output }`, na organização de quem pede (contratos em `core/llm.py`).

## 3. Fluxo de Execução
1. SurrealDB: `ai_providers` e `ai_models` (globais, com `owner` = id da organização ou `platform`; únicos por
   `owner + slug` e `owner + provider + model_id`); `ai_usage` (por organização). Chave criptografada com AES-GCM
   (`AI_SECRETS_KEY`, só este serviço a recebe), presa ao `owner` e ao `slug` do provedor.
2. NATS: consome `events.ai.usage` (durável, publicado pelo `core/llm.py`) e grava tokens e custo; responde
   `rpc.ai.resolve`. `events.ai.trigger` (`ProviderRef`) dispara a busca de modelos em segundo plano.
   `events.plans.encerrada` e a exclusão da organização (README §5.13) apagam os provedores próprios dela, com as chaves
   e os modelos.
3. Temporal: `AiWorkflow` → activity `ai.discover_models` (chama `GET {base_url}/models`; timeout 1 min, 3
   tentativas).

## 4. Casos de Borda e Erros Mapeados
- `ERRO_AI_FORBIDDEN` (403): gerenciar sem ser owner/admin, ou provedor da plataforma fora de `PLATFORM_TENANT`.
- `ERRO_AI_UNSAFE_URL` (422): endereço de provedor da organização que não é `https` público (rede interna só nos
  provedores da plataforma: Ollama, vLLM, LM Studio).
- `ERRO_AI_SLUG_TAKEN` (409) · `ERRO_AI_PROVIDER_NOT_FOUND` (404) · `ERRO_AI_MODEL_NOT_FOUND` (404).
- `ERRO_AI_MODEL_UNAVAILABLE` (404): modelo pedido inexistente, desativado ou de outro tipo (chat × embedding).
  O provedor da organização esconde o da plataforma com o mesmo apelido: a resolução usa só o dela, e um modelo que
  só a plataforma tem fica indisponível para essa organização (sem misturar chaves nem custos).
- `ERRO_AI_DISCOVERY_FAILED` (502): o provedor não respondeu ao `/models` (chave errada, fora do ar).
- Modelo descoberto nasce desativado; quem administra ativa, dá apelido e preço (por milhão de tokens).
- Custo = tokens × preço do momento da chamada. Sem preço informado, custo zero (tokens continuam contados).
  Preços e custos em dólar (US$), a moeda em que os provedores cobram.
- Plano (README §5.17): cada uso gravado soma `ai.custo` (US$) e `ai.tokens` no mês da organização, com key fixa por
  mensagem (a reentrega soma uma vez). Quem já chegou ao limite do mês recebe `ERRO_PLAN_LIMIT` (402) do
  `core/llm.py` antes de o provedor ser chamado.
