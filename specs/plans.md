# Spec: plans

## 1. Objetivo Operacional
Dizer o que cada organização pode usar: planos com limites (total do que existe e consumo do mês), o plano de cada
organização, o consumo do mês e aviso antes de acabar. Os serviços declaram e conferem pelo `core/plans.py`
(README §5.17); a cobrança fica no produto, que troca o plano com `plans.assign` depois de confirmar o pagamento.

## 2. Contrato de Entrada e Saída
Todas as rotas exigem token e valem para a organização ativa. Gerenciar planos e atribuir exige `owner` ou `admin` da
organização `PLATFORM_TENANT` (`manages_platform`).
- `GET /current` → `Current { tenant, plan: Plan | null, month, limits: LimitState[], manages_platform }`, para qualquer
  membro. `LimitState { name, service, description, default, monthly, unit, currency, limit, used }`: `limit` é o que o
  plano permite (`null`: sem limite); `used` é a soma do mês (mensal) ou o último total informado pelo serviço.
- `GET /plans` → `PlanList { items: Plan[], current, manages_platform }`: os planos públicos, do mais barato ao mais caro
  (quem administra a plataforma vê todos). `Plan { slug, name, description, price, currency, public, default, limits }`,
  com `limits: { "<serviço>.<limite>": número | null }` (`null`: sem limite; o que o plano não cita vale o default).
- `GET /limits` → `LimitList { items: CatalogLimit[] }`: o catálogo que os serviços declararam (`CatalogLimit { name,
  service, description, default, monthly, unit, currency }`).
- `POST /plans` (`PlanInput { slug, name, description?, price?, currency?, public?, default?, limits? }`) → `Plan`
- `POST /plans/update` (`PlanUpdate { slug, name?, description?, price?, currency?, public?, default?, limits? }`) →
  `Plan`; `limits` substitui a lista inteira
- `POST /plans/remove` (`PlanRef { slug }`) → `PlanList`
- `POST /assign` (`AssignInput { tenant, plan }`) → `Account { tenant, tenant_name, plan, plan_name }`
- Ao vivo (`bus.live`): `plans.uso` (`UsageChanged { name, used }`) para a organização quando um consumo ou um total muda.
- NATS, com os contratos em `core/plans.py`: `events.plans.catalog` (`LimitCatalog`), `events.plans.usage`
  (`UsageReport { name, amount, month }`) e `events.plans.count` (`CountReport { name, total, at }`); RPC
  `rpc.plans.limits` (`LimitsRequest` → `PlanLimits { plan, plan_name, month, limits }`) e `rpc.plans.assign`
  (`AssignRequest { plan }` → `Assigned { tenant, plan, plan_name }`, só tarefa da plataforma).

## 3. Fluxo de Execução
1. SurrealDB: `plan_limits` (global; o catálogo, um por nome), `plan_tiers` (global; os planos, únicos por `slug`, com
   `limits` como lista de `{ name, value }`), `plan_accounts` (global; o plano de cada organização, único por `org`:
   quem administra a plataforma confere se um plano está em uso), `plan_usage` (por
   organização; soma do mês, única por `name + month`, com o último aviso dado em `alerted`), `plan_usage_log` (por
   organização; uma linha por mensagem, única por `message`) e `plan_counts` (por organização; último total, único por
   `name`).
2. NATS: `events.plans.catalog` grava o catálogo que cada serviço declara no boot (o que saiu da lista sai do
   catálogo). `events.plans.usage` grava a linha da mensagem e soma no mês num bloco atômico (reentrega não soma duas
   vezes) e avisa ao vivo. `events.plans.count` grava o total se for mais novo que o guardado. Responde
   `rpc.plans.limits` (plano da organização + catálogo + consumo do mês) e `rpc.plans.assign`. Atribuir confere a
   organização e pega o nome dela no `svc-identity` (`rpc.identity.contacts`).
3. Avisos: ao cruzar 80% e 100% de um limite mensal, donos e administradores recebem um aviso (tela + e-mail) pelo
   `core/notify.py`, uma vez por mês e por patamar; trocar de plano recomeça os patamares do mês.
4. Temporal: `PlansCleanupWorkflow` → activity `plans.cleanup` (timeout 5 min, 3 tentativas), todo dia às 4h30 UTC
   (`workflows.SCHEDULES`): apaga as linhas de consumo com mais de 45 dias e as somas com mais de 13 meses.

## 4. Casos de Borda e Erros Mapeados
- `ERRO_PLAN_LIMIT` (402, do `core/plans.py`): limite atingido; a mensagem diz qual e quanto o plano permite.
- `ERRO_PLANS_FORBIDDEN` (403): gerenciar planos ou atribuir sem administrar a plataforma; `rpc.plans.assign` que não
  vem de uma tarefa da plataforma (`system:`).
- `ERRO_PLANS_NOT_FOUND` (404) · `ERRO_PLANS_TENANT_NOT_FOUND` (404) · `ERRO_PLANS_SLUG_TAKEN` (409) ·
  `ERRO_PLANS_IN_USE` (409: plano com organizações não sai; troque-as antes) · `ERRO_PLANS_UNKNOWN_LIMIT` (422: limite
  fora do catálogo).
- Um plano padrão ou nenhum: marcar um como padrão desmarca o anterior. Organização sem plano atribuído fica no padrão;
  sem padrão (ou sem `PLATFORM_TENANT`, quando ninguém gerencia planos), valem os defaults declarados pelos serviços.
- Mudar os limites de um plano vale para todas as organizações nele, em até 1 min (resolução guardada 60 s no core).
- Mensal: soma do mês em UTC; a chamada que cruza o limite termina e as seguintes param. Com a resolução guardada,
  o excesso fica limitado a cerca de 1 min de uso. Total: quem conta é o serviço (`used=`); duas criações ao mesmo
  tempo podem passar do limite em uma.
- Preço é informativo, na moeda do plano (a cobrança é do produto). Limite em dinheiro fica na moeda declarada pelo
  serviço (IA: US$, a moeda dos provedores), sem conversão.
- `svc-plans` fora do ar: o core usa a última resposta e, sem ela, nenhum limite (plano é regra comercial, não de
  segurança).
