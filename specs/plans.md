# Spec: plans

## 1. Objetivo Operacional
Dizer o que cada organização pode usar: os módulos (cada serviço é um) e os limites (total do que existe e consumo do
mês) de cada plano, o plano e o ajuste de módulos de cada organização, o consumo do mês e aviso antes de acabar. Os
serviços declaram o módulo e os limites, e o `core/plans.py` confere (README §5.17); a cobrança fica no produto, que
troca o plano com `plans.assign` depois de confirmar o pagamento.

## 2. Contrato de Entrada e Saída
Todas as rotas exigem token e valem para a organização ativa. Gerenciar planos e atribuir exige `owner` ou `admin` da
organização `PLATFORM_TENANT` (`manages_platform`).
- `GET /current` → `Current { tenant, plan: Plan | null, month, limits: LimitState[], modules: ModuleState[],
  manages_platform }`, para qualquer membro. `LimitState { name, service, description, default, monthly, unit,
  currency, limit, used }`: `limit` é o que o plano permite (`null`: sem limite); `used` é a soma do mês (mensal) ou o
  último total informado pelo serviço.
- `GET /modules` → `ModuleList { items: ModuleState[] }`, para qualquer membro (o menu da tela): `ModuleState { name,
  service, title, description, category, core, default, requires, enabled }`, por categoria e título.
- `GET /plans` → `PlanList { items: Plan[], current, manages_platform }`: os planos públicos, do mais barato ao mais caro
  (quem administra a plataforma vê todos). `Plan { slug, name, description, price, currency, public, default, limits,
  modules }`, com `limits: { "<serviço>.<limite>": número | null }` (`null`: sem limite) e `modules: { "<módulo>":
  bool }`; o que o plano não cita vale o default declarado.
- `GET /catalog` → `Catalog { modules: CatalogModule[], limits: CatalogLimit[] }`: o que os serviços declararam
  (`CatalogModule { name, service, title, description, category, core, default, requires }`, `CatalogLimit { name,
  service, description, default, monthly, unit, currency }`).
- `POST /plans` (`PlanInput { slug, name, description?, price?, currency?, public?, default?, limits?, modules? }`) →
  `Plan`
- `POST /plans/update` (`PlanUpdate { slug, name?, description?, price?, currency?, public?, default?, limits?,
  modules? }`) → `Plan`; `limits` e `modules` substituem a lista inteira
- `POST /plans/remove` (`PlanRef { slug }`) → `PlanList`
- `GET /account?tenant=` (`AccountRef`) → `Account { tenant, tenant_name, plan, plan_name, assigned, modules }`: o plano
  em vigor de uma organização e o ajuste de módulos só dela (`modules: { "<módulo>": bool }`)
- `POST /assign` (`AssignInput { tenant, plan, modules? }`) → `Account`; `modules` é o ajuste da organização além do
  plano (`null`: mantém o que havia; `{}`: só o plano)
- Ao vivo (`bus.live`): `plans.uso` (`UsageChanged { name, used }`) para a organização quando um consumo ou um total muda.
- NATS, com os contratos em `core/plans.py`: `events.plans.catalog` (`ModuleCatalog { service, module, limits }`),
  `events.plans.usage` (`UsageReport { name, amount, month }`) e `events.plans.count` (`CountReport { name, total, at
  }`); RPC `rpc.plans.limits` (`LimitsRequest` → `PlanLimits { plan, plan_name, month, limits, modules }`) e
  `rpc.plans.assign` (`AssignRequest { plan, modules? }` → `Assigned { tenant, plan, plan_name, modules }`, só tarefa da
  plataforma).
- O próprio serviço é o módulo `plans` ("Plano", categoria Organização), da plataforma.

## 3. Fluxo de Execução
1. SurrealDB: `plan_modules` e `plan_limits` (globais; o catálogo, um por nome), `plan_tiers` (global; os planos,
   únicos por `slug`, com `limits` como lista de `{ name, value }` e `modules` como lista de `{ name, enabled }`),
   `plan_accounts` (global; o plano e o ajuste de módulos de cada organização, único por `org`: quem administra a
   plataforma confere se um plano está em uso), `plan_usage` (por
   organização; soma do mês, única por `name + month`, com o último aviso dado em `alerted`), `plan_usage_log` (por
   organização; uma linha por mensagem, única por `message`) e `plan_counts` (por organização; último total, único por
   `name`).
2. NATS: `events.plans.catalog` grava o módulo e os limites que cada serviço declara no boot (o limite que saiu da lista
   sai do catálogo). `events.plans.usage` grava a linha da mensagem e soma no mês num bloco atômico (reentrega não soma duas
   vezes) e avisa ao vivo. `events.plans.count` grava o total se for mais novo que o guardado. Responde
   `rpc.plans.limits` (plano da organização + módulos ligados + limites + consumo do mês) e `rpc.plans.assign`.
   Atribuir confere a organização e pega o nome dela no `svc-identity` (`rpc.identity.contacts`).
   Módulo ligado: da plataforma (`core`), ou o ajuste da organização, senão o plano, senão o `default`; e só com os
   `requires` ligados (requisito fora do catálogo desliga quem depende dele; dependência circular, os dois).
3. Avisos: ao cruzar 80% e 100% de um limite mensal, donos e administradores recebem um aviso (tela + e-mail) pelo
   `core/notify.py`, uma vez por mês e por patamar; trocar de plano recomeça os patamares do mês.
4. Temporal: `PlansCleanupWorkflow` → activity `plans.cleanup` (timeout 5 min, 3 tentativas), todo dia às 4h30 UTC
   (`workflows.SCHEDULES`): apaga as linhas de consumo com mais de 45 dias e as somas com mais de 13 meses.

## 4. Casos de Borda e Erros Mapeados
- `ERRO_PLAN_LIMIT` (402, do `core/plans.py`): limite atingido; a mensagem diz qual e quanto o plano permite.
- `ERRO_PLAN_MODULE` (402, do `core/plans.py`, antes do serviço): o módulo chamado não está no plano da organização.
  Evento NATS de quem não tem o módulo é recusado sem reentrega; tarefa da plataforma passa.
- `ERRO_PLANS_FORBIDDEN` (403): gerenciar planos ou atribuir sem administrar a plataforma; `rpc.plans.assign` que não
  vem de uma tarefa da plataforma (`system:`).
- `ERRO_PLANS_NOT_FOUND` (404) · `ERRO_PLANS_TENANT_NOT_FOUND` (404) · `ERRO_PLANS_SLUG_TAKEN` (409) ·
  `ERRO_PLANS_IN_USE` (409: plano com organizações não sai; troque-as antes) · `ERRO_PLANS_UNKNOWN_LIMIT` (422: limite
  fora do catálogo) · `ERRO_PLANS_UNKNOWN_MODULE` (422: módulo fora do catálogo) · `ERRO_PLANS_CORE_MODULE` (422:
  desligar módulo da plataforma) · `ERRO_PLANS_MODULE_REQUIRES` (422: ligar um módulo sem os requisitos, ou desligar o
  requisito de um ligado).
- Um plano padrão ou nenhum: marcar um como padrão desmarca o anterior. Organização sem plano atribuído fica no padrão;
  sem padrão (ou sem `PLATFORM_TENANT`, quando ninguém gerencia planos), valem os defaults declarados pelos serviços.
- Mudar os limites ou os módulos de um plano vale para todas as organizações nele, em até 1 min (resolução guardada 60 s
  no core). Mudar o plano de uma organização mantém o ajuste de módulos dela, a menos que venha outro.
- Módulo de um serviço que saiu da plataforma fica no catálogo (a tela ainda o lista); sem o serviço, nada o atende.
- Mensal: soma do mês em UTC; a chamada que cruza o limite termina e as seguintes param. Com a resolução guardada,
  o excesso fica limitado a cerca de 1 min de uso. Total: quem conta é o serviço (`used=`); duas criações ao mesmo
  tempo podem passar do limite em uma.
- Preço é informativo, na moeda do plano (a cobrança é do produto). Limite em dinheiro fica na moeda declarada pelo
  serviço (IA: US$, a moeda dos provedores), sem conversão.
- `svc-plans` fora do ar: o core usa a última resposta e, sem ela, nenhum limite e todo módulo ligado (plano é regra
  comercial, não de segurança).
