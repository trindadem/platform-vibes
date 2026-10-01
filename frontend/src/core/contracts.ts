// Gerado por gateway/contracts.py a partir de gateway/endpoints/*.yaml e services/*/schemas.py. Não edite:
// depois de mudar um manifesto ou um schemas.py, rode (da raiz) `uv run python gateway/contracts.py`.
import { request, withQuery, type RequestOptions } from "./api";

/** Resposta de toda rota NATS: o id da mensagem publicada (o mesmo para a mesma Idempotency-Key). */
export interface Dispatched {
  message_id: string;
}

/** Um registro de cadastro pelo id (core/resources.py). */
export interface ResourceRef {
  id: string;
}

/** Resposta da remoção de um registro de cadastro. */
export interface ResourceRemoved {
  id: string;
}

/** Aviso ao vivo de um cadastro (<serviço>.<cadastro>): a lista aberta busca de novo. */
export interface ResourceChanged {
  id: string;
  action: "created" | "updated" | "removed";
}

/** GET /health do gateway (README §5.18). */
export interface GatewayHealth {
  /** "ok" quando tudo responde (senão, a resposta é um erro 503). */
  status: string;
  /** Cada dependência do gateway e se respondeu ("ok"). */
  checks: Record<string, string>;
  /** Quantas rotas os manifestos publicam. */
  routes: number;
}

/** Rotas do próprio gateway. */
export const gateway = {
  /** GET /health · pública */
  health: (options?: RequestOptions) => request<GatewayHealth>("GET", "/health", undefined, options),
};

export interface AiProvider {
  id: string;
  name: string;
  slug: string;
  /** Vazio no provedor da plataforma visto por outra organização */
  base_url: string;
  /** Só os últimos 4 caracteres da chave (vazio no provedor da plataforma visto de fora) */
  key_hint: string;
  scope: "organization" | "platform";
}

export interface AiProviderList {
  items: AiProvider[];
  /** Quem pede administra os provedores da plataforma */
  manages_platform: boolean;
}

export interface AiProviderInput {
  /** Nome para exibir */
  name: string;
  /** Apelido usado no nome do modelo (ex.: openrouter → openrouter/claude) */
  slug: string;
  /** Endereço base da API compatível com OpenAI (ex.: https://openrouter.ai/api/v1) */
  base_url: string;
  /** Chave do provedor (vazia para provedores locais sem chave) */
  api_key?: string;
  /** organization (só a sua organização) ou platform (todas) */
  scope?: "organization" | "platform";
}

export interface AiProviderRef {
  id: string;
}

export interface AiDiscovered {
  /** Modelos que o provedor listou */
  found: number;
  /** Novos no catálogo (nascem não liberados) */
  added: number;
}

export interface AiModel {
  id: string;
  /** O que se passa ao llm.*: <provedor>/<apelido ou id> */
  name: string;
  provider: string;
  model_id: string;
  alias: string | null;
  kind: "chat" | "embedding";
  enabled: boolean;
  price_input: number;
  price_output: number;
  scope: "organization" | "platform";
}

export interface AiModelPage {
  items: AiModel[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** Lista de modelos: busca por id ou apelido, filtros de liberado e tipo. Membro só recebe os liberados. */
export interface AiModelQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "model_id" | "-model_id" | "alias" | "-alias" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  /** Só liberados (true) ou só não liberados (false) */
  enabled?: boolean | null;
  kind?: "chat" | "embedding" | null;
}

export interface AiModelInput {
  /** Id do provedor */
  provider: string;
  model_id: string;
  kind?: "chat" | "embedding";
}

export interface AiModelUpdate {
  id: string;
  enabled?: boolean | null;
  /** Nome curto (ex.: claude → openrouter/claude); vazio remove o apelido */
  alias?: string | null;
  kind?: "chat" | "embedding" | null;
  /** Preço por milhão de tokens de entrada */
  price_input?: number | null;
  /** Preço por milhão de tokens de saída */
  price_output?: number | null;
}

export interface AiUsageItem {
  model: string;
  service: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
}

export interface AiUsageSummary {
  /** AAAA-MM, em UTC */
  month: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  items: AiUsageItem[];
}

/** Uso gravado (também vai ao vivo para a tela da organização). */
export interface AiRecorded {
  id: string;
  model: string;
  service: string;
  cost: number;
  at: string;
}

/** svc-ai · /api/v1/ai */
export const ai = {
  /** GET /api/v1/ai/providers · http · exige token */
  providers: (options?: RequestOptions) =>
    request<AiProviderList>("GET", "/api/v1/ai/providers", undefined, options),
  /** POST /api/v1/ai/providers · http · exige token */
  createProvider: (body: AiProviderInput, options?: RequestOptions) =>
    request<AiProvider>("POST", "/api/v1/ai/providers", body, options),
  /** POST /api/v1/ai/providers/remove · http · exige token */
  removeProvider: (body: AiProviderRef, options?: RequestOptions) =>
    request<AiProviderList>("POST", "/api/v1/ai/providers/remove", body, options),
  /** POST /api/v1/ai/providers/discover · http · exige token */
  discoverModels: (body: AiProviderRef, options?: RequestOptions) =>
    request<AiDiscovered>("POST", "/api/v1/ai/providers/discover", body, options),
  /** GET /api/v1/ai/models · http · exige token */
  models: (query?: AiModelQuery, options?: RequestOptions) =>
    request<AiModelPage>("GET", withQuery("/api/v1/ai/models", query), undefined, options),
  /** POST /api/v1/ai/models · http · exige token */
  addModel: (body: AiModelInput, options?: RequestOptions) =>
    request<AiModel>("POST", "/api/v1/ai/models", body, options),
  /** POST /api/v1/ai/models/update · http · exige token */
  updateModel: (body: AiModelUpdate, options?: RequestOptions) =>
    request<AiModel>("POST", "/api/v1/ai/models/update", body, options),
  /** GET /api/v1/ai/usage · http · exige token */
  usage: (options?: RequestOptions) =>
    request<AiUsageSummary>("GET", "/api/v1/ai/usage", undefined, options),
};

export interface IdentitySignupInput {
  /** Nome da pessoa */
  name: string;
  /** E-mail de acesso */
  email: string;
  /** Senha (mínimo de 8 caracteres) */
  password: string;
  /** Nome da organização nova (quem cadastra vira dono) */
  organization?: string | null;
  /** Código de convite (entra numa organização existente) */
  invite?: string | null;
}

export interface IdentityTenant {
  id: string;
  name: string;
  roles: ("owner" | "admin" | "member")[];
}

export interface IdentityUser {
  id: string;
  name: string;
  email: string;
}

export interface IdentityAuthResult {
  /** Token de acesso (Authorization: Bearer) */
  access_token: string;
  /** Segundos até o token de acesso expirar */
  expires_in: number;
  user: IdentityUser;
  /** Organização ativa */
  tenant: IdentityTenant | null;
  /** Todas as organizações do usuário */
  tenants: IdentityTenant[];
}

export interface IdentityLoginInput {
  email: string;
  password: string;
  /** Organização para entrar (padrão: a última usada) */
  tenant?: string | null;
}

export interface IdentityEmpty {
}

export interface IdentityInviteCode {
  /** Código do convite */
  code: string;
}

export interface IdentityInviteInfo {
  tenant_name: string;
  role: "owner" | "admin" | "member";
  expires_at: string;
}

export interface IdentityForgotInput {
  /** E-mail da conta */
  email: string;
}

export interface IdentityResetInput {
  /** Código do link recebido por e-mail */
  code: string;
  /** Senha nova (mínimo de 8 caracteres) */
  password: string;
}

export interface IdentityMe {
  user: IdentityUser;
  tenant: string | null;
  tenants: IdentityTenant[];
}

export interface IdentitySwitchInput {
  /** Organização que passa a ser a ativa */
  tenant: string;
}

export interface IdentityTenantInput {
  /** Nome da organização */
  name: string;
}

export interface IdentityInviteInput {
  /** Papel de quem aceitar o convite */
  role?: "admin" | "member";
  /** Se informado, o convite também vai por e-mail para este endereço */
  email?: string | null;
}

export interface IdentityInvite {
  /** Código para o link de convite (mostrado uma única vez) */
  code: string;
  role: "owner" | "admin" | "member";
  expires_at: string;
  /** Para quem o convite foi enviado por e-mail */
  email: string | null;
}

export interface IdentityMember {
  id: string;
  name: string;
  email: string;
  roles: ("owner" | "admin" | "member")[];
  joined_at: string;
}

export interface IdentityMemberList {
  items: IdentityMember[];
}

export interface IdentityMemberRef {
  /** Id do usuário */
  user: string;
}

export interface IdentityOrganization {
  id: string;
  name: string;
  /** Link assinado da imagem do logo (vale 1 h) */
  logo_url: string | null;
  /** Cor da marca (#RRGGBB): a tela a usa como cor principal; null: a da plataforma */
  color: string | null;
}

/** O que a tela diz antes de enviar: nome, tipo e tamanho do arquivo (o envio só vale para esse tamanho e tipo). */
export interface IdentityUploadRequest {
  filename: string;
  content_type: string;
  /** Tamanho em bytes */
  size: number;
}

/** Link de envio: a tela faz PUT do arquivo em url com estes cabeçalhos e depois confirma a key no serviço. */
export interface IdentityUpload {
  key: string;
  url: string;
  /** Cabeçalhos que o PUT precisa levar exatamente assim */
  headers: Record<string, string>;
  expires_at: string;
}

export interface IdentityKeepRequest {
  /** A key devolvida em Upload */
  key: string;
}

export interface IdentityColorInput {
  /** #RRGGBB; null volta à cor da plataforma */
  color: string | null;
}

export interface IdentityMembersChanged {
  /** Id de quem entrou ou saiu */
  user: string;
  change: "joined" | "removed";
}

export interface IdentityAccessChanged {
  /** Organização que a pessoa deixou de acessar */
  tenant: string;
  change: "removed";
}

/** svc-identity · /api/v1/identity */
export const identity = {
  /** POST /api/v1/identity/signup · http · pública · sessão em cookie */
  signup: (body: IdentitySignupInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/signup", body, options),
  /** POST /api/v1/identity/login · http · pública · sessão em cookie */
  login: (body: IdentityLoginInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/login", body, options),
  /** POST /api/v1/identity/refresh · http · pública · sessão em cookie */
  refresh: (body: IdentityEmpty, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/refresh", body, options),
  /** POST /api/v1/identity/logout · http · pública · sessão em cookie */
  logout: (body: IdentityEmpty, options?: RequestOptions) =>
    request<IdentityEmpty>("POST", "/api/v1/identity/logout", body, options),
  /** POST /api/v1/identity/invite-info · http · pública */
  inviteInfo: (body: IdentityInviteCode, options?: RequestOptions) =>
    request<IdentityInviteInfo>("POST", "/api/v1/identity/invite-info", body, options),
  /** POST /api/v1/identity/password/forgot · http · pública */
  forgotPassword: (body: IdentityForgotInput, options?: RequestOptions) =>
    request<IdentityEmpty>("POST", "/api/v1/identity/password/forgot", body, options),
  /** POST /api/v1/identity/password/reset · http · pública */
  resetPassword: (body: IdentityResetInput, options?: RequestOptions) =>
    request<IdentityEmpty>("POST", "/api/v1/identity/password/reset", body, options),
  /** GET /api/v1/identity/me · http · exige token */
  me: (options?: RequestOptions) =>
    request<IdentityMe>("GET", "/api/v1/identity/me", undefined, options),
  /** POST /api/v1/identity/switch · http · exige token · sessão em cookie */
  switchTenant: (body: IdentitySwitchInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/switch", body, options),
  /** POST /api/v1/identity/tenants · http · exige token · sessão em cookie */
  createTenant: (body: IdentityTenantInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/tenants", body, options),
  /** POST /api/v1/identity/join · http · exige token · sessão em cookie */
  join: (body: IdentityInviteCode, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/join", body, options),
  /** POST /api/v1/identity/invites · http · exige token */
  createInvite: (body: IdentityInviteInput, options?: RequestOptions) =>
    request<IdentityInvite>("POST", "/api/v1/identity/invites", body, options),
  /** GET /api/v1/identity/members · http · exige token */
  members: (options?: RequestOptions) =>
    request<IdentityMemberList>("GET", "/api/v1/identity/members", undefined, options),
  /** POST /api/v1/identity/members/remove · http · exige token */
  removeMember: (body: IdentityMemberRef, options?: RequestOptions) =>
    request<IdentityMemberList>("POST", "/api/v1/identity/members/remove", body, options),
  /** GET /api/v1/identity/organization · http · exige token */
  organization: (options?: RequestOptions) =>
    request<IdentityOrganization>("GET", "/api/v1/identity/organization", undefined, options),
  /** POST /api/v1/identity/organization/logo/upload · http · exige token */
  logoUpload: (body: IdentityUploadRequest, options?: RequestOptions) =>
    request<IdentityUpload>("POST", "/api/v1/identity/organization/logo/upload", body, options),
  /** POST /api/v1/identity/organization/logo · http · exige token */
  setLogo: (body: IdentityKeepRequest, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/logo", body, options),
  /** POST /api/v1/identity/organization/color · http · exige token */
  setColor: (body: IdentityColorInput, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/color", body, options),
  /** POST /api/v1/identity/organization/logo/remove · http · exige token */
  removeLogo: (body: unknown, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/logo/remove", body, options),
};

export interface NotifyNotification {
  id: string;
  title: string;
  body: string;
  link: string | null;
  action: string | null;
  /** Serviço que avisou (svc-...) */
  service: string;
  read: boolean;
  created_at: string;
}

export interface NotifyNotificationPage {
  items: NotifyNotification[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface NotifyNotificationQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  /** false: só os não lidos */
  read?: boolean | null;
}

export interface NotifyUnread {
  count: number;
}

export interface NotifyReadRequest {
  ids: string[];
}

export interface NotifyPreferences {
  /** Receber os avisos também por e-mail (os de segurança sempre chegam) */
  email: boolean;
}

/** svc-notify · /api/v1/notify */
export const notify = {
  /** GET /api/v1/notify/items · http · exige token */
  items: (query?: NotifyNotificationQuery, options?: RequestOptions) =>
    request<NotifyNotificationPage>("GET", withQuery("/api/v1/notify/items", query), undefined, options),
  /** GET /api/v1/notify/unread · http · exige token */
  unread: (options?: RequestOptions) =>
    request<NotifyUnread>("GET", "/api/v1/notify/unread", undefined, options),
  /** POST /api/v1/notify/read · http · exige token */
  read: (body: NotifyReadRequest, options?: RequestOptions) =>
    request<NotifyUnread>("POST", "/api/v1/notify/read", body, options),
  /** POST /api/v1/notify/read-all · http · exige token */
  readAll: (body: unknown, options?: RequestOptions) =>
    request<NotifyUnread>("POST", "/api/v1/notify/read-all", body, options),
  /** GET /api/v1/notify/preferences · http · exige token */
  preferences: (options?: RequestOptions) =>
    request<NotifyPreferences>("GET", "/api/v1/notify/preferences", undefined, options),
  /** POST /api/v1/notify/preferences · http · exige token */
  setPreferences: (body: NotifyPreferences, options?: RequestOptions) =>
    request<NotifyPreferences>("POST", "/api/v1/notify/preferences", body, options),
};

export interface PlansLimitState {
  /** Nome completo: <serviço>.<limite> */
  name: string;
  service: string;
  description: string;
  /** Valor sem plano (ou que o plano não cita); null: sem limite */
  default: number | null;
  /** Consumo somado no mês (true) ou total do que existe agora (false) */
  monthly: boolean;
  unit: string;
  currency: string | null;
  /** O que o plano permite (ou o default); null: sem limite */
  limit: number | null;
  /** Mensal: soma do mês. Total: o último total que o serviço informou */
  used: number;
}

export interface PlansModuleState {
  /** Nome do serviço, sem svc- (o mesmo de /api/v1/<nome>) */
  name: string;
  service: string;
  title: string;
  description: string;
  /** Grupo no menu */
  category: string;
  /** Módulo da plataforma: sempre ligado */
  core: boolean;
  /** Ligado quando o plano não diz nada (e para quem não tem plano) */
  default: boolean;
  /** Módulos sem os quais este não funciona */
  requires: string[];
  /** Ligado para a organização: ajuste dela, plano ou default, com os requires ligados */
  enabled: boolean;
}

export interface PlansPlan {
  slug: string;
  name: string;
  description: string;
  /** Preço por mês, informativo (a cobrança é do produto) */
  price: number;
  /** Moeda do preço */
  currency: "BRL" | "USD" | "EUR";
  /** Aparece para as organizações na comparação de planos */
  public: boolean;
  /** Plano de quem ainda não tem um atribuído */
  default: boolean;
  /** Limite → valor (null: sem limite); o que falta vale o default */
  limits: Record<string, number | null>;
  /** Módulo → incluído; o que falta vale o default do módulo */
  modules: Record<string, boolean>;
}

export interface PlansCurrent {
  /** Id da organização: quem administra a plataforma atribui o plano por ele */
  tenant: string;
  /** Plano em vigor (atribuído ou o padrão); null: sem plano */
  plan: PlansPlan | null;
  /** AAAA-MM, em UTC: o mês dos consumos */
  month: string;
  limits: PlansLimitState[];
  modules: PlansModuleState[];
  manages_platform: boolean;
}

export interface PlansPlanList {
  items: PlansPlan[];
  /** Slug do plano da organização ativa (null: sem plano) */
  current: string | null;
  /** Quem pede administra os planos da plataforma */
  manages_platform: boolean;
}

/** Os módulos da plataforma e se cada um está ligado para a organização ativa (o menu esconde os desligados). */
export interface PlansModuleList {
  items: PlansModuleState[];
}

export interface PlansCatalogLimit {
  /** Nome completo: <serviço>.<limite> */
  name: string;
  service: string;
  description: string;
  /** Valor sem plano (ou que o plano não cita); null: sem limite */
  default: number | null;
  /** Consumo somado no mês (true) ou total do que existe agora (false) */
  monthly: boolean;
  unit: string;
  currency: string | null;
}

export interface PlansCatalogModule {
  /** Nome do serviço, sem svc- (o mesmo de /api/v1/<nome>) */
  name: string;
  service: string;
  title: string;
  description: string;
  /** Grupo no menu */
  category: string;
  /** Módulo da plataforma: sempre ligado */
  core: boolean;
  /** Ligado quando o plano não diz nada (e para quem não tem plano) */
  default: boolean;
  /** Módulos sem os quais este não funciona */
  requires: string[];
}

/** O que os serviços declararam: os módulos (por categoria) e os limites. */
export interface PlansCatalog {
  modules: PlansCatalogModule[];
  limits: PlansCatalogLimit[];
}

export interface PlansPlanInput {
  /** Identificador curto e permanente (ex.: gratis, pro) */
  slug: string;
  name: string;
  description?: string;
  /** Preço por mês, informativo */
  price?: number;
  currency?: "BRL" | "USD" | "EUR";
  public?: boolean;
  default?: boolean;
  /** Limite → valor (null: sem limite) */
  limits?: Record<string, number | null>;
  /** Módulo → incluído (o que falta vale o default) */
  modules?: Record<string, boolean>;
}

export interface PlansPlanUpdate {
  slug: string;
  name?: string | null;
  description?: string | null;
  price?: number | null;
  currency?: "BRL" | "USD" | "EUR" | null;
  public?: boolean | null;
  default?: boolean | null;
  /** Substitui a lista inteira */
  limits?: Record<string, number | null> | null;
  /** Substitui a lista inteira */
  modules?: Record<string, boolean> | null;
}

export interface PlansPlanRef {
  slug: string;
}

export interface PlansAccount {
  tenant: string;
  tenant_name: string;
  /** Plano em vigor (atribuído ou o padrão); null: sem plano */
  plan: string | null;
  plan_name: string;
  /** O plano foi atribuído (false: vale o padrão) */
  assigned: boolean;
  /** Ajuste da organização além do plano: módulo → ligado */
  modules: Record<string, boolean>;
}

export interface PlansAccountRef {
  tenant: string;
}

export interface PlansAssignInput {
  /** Id da organização (aparece para ela na tela Plano) */
  tenant: string;
  plan: string;
  /** Ajuste da organização: módulo → ligado, além do plano. null: mantém o ajuste; {}: só o plano */
  modules?: Record<string, boolean> | null;
}

/** Consumo ou total que mudou (também vai ao vivo para a tela da organização). */
export interface PlansUsageChanged {
  name: string;
  used: number;
}

/** svc-plans · /api/v1/plans */
export const plans = {
  /** GET /api/v1/plans/current · http · exige token */
  current: (options?: RequestOptions) =>
    request<PlansCurrent>("GET", "/api/v1/plans/current", undefined, options),
  /** GET /api/v1/plans/plans · http · exige token */
  list: (options?: RequestOptions) =>
    request<PlansPlanList>("GET", "/api/v1/plans/plans", undefined, options),
  /** GET /api/v1/plans/modules · http · exige token */
  modules: (options?: RequestOptions) =>
    request<PlansModuleList>("GET", "/api/v1/plans/modules", undefined, options),
  /** GET /api/v1/plans/catalog · http · exige token */
  catalog: (options?: RequestOptions) =>
    request<PlansCatalog>("GET", "/api/v1/plans/catalog", undefined, options),
  /** POST /api/v1/plans/plans · http · exige token */
  createPlan: (body: PlansPlanInput, options?: RequestOptions) =>
    request<PlansPlan>("POST", "/api/v1/plans/plans", body, options),
  /** POST /api/v1/plans/plans/update · http · exige token */
  updatePlan: (body: PlansPlanUpdate, options?: RequestOptions) =>
    request<PlansPlan>("POST", "/api/v1/plans/plans/update", body, options),
  /** POST /api/v1/plans/plans/remove · http · exige token */
  removePlan: (body: PlansPlanRef, options?: RequestOptions) =>
    request<PlansPlanList>("POST", "/api/v1/plans/plans/remove", body, options),
  /** GET /api/v1/plans/account · http · exige token */
  account: (query?: PlansAccountRef, options?: RequestOptions) =>
    request<PlansAccount>("GET", withQuery("/api/v1/plans/account", query), undefined, options),
  /** POST /api/v1/plans/assign · http · exige token */
  assign: (body: PlansAssignInput, options?: RequestOptions) =>
    request<PlansAccount>("POST", "/api/v1/plans/assign", body, options),
};

export interface WebhooksEndpoint {
  id: string;
  url: string;
  description: string;
  /** Eventos inscritos; ["*"] para todos */
  events: string[];
  enabled: boolean;
  /** Entregas seguidas sem sucesso */
  failures: number;
  disabled_reason: string | null;
  created_at: string;
}

export interface WebhooksEndpointList {
  items: WebhooksEndpoint[];
}

export interface WebhooksEndpointInput {
  /** Endereço que recebe os eventos (https) */
  url: string;
  description?: string;
  /** Eventos, ou ["*"] para todos */
  events: string[];
}

export interface WebhooksEndpointSecret {
  endpoint: WebhooksEndpoint;
  /** Segredo de assinatura (whsec_...): aparece só agora */
  secret: string;
}

export interface WebhooksEndpointUpdate {
  id: string;
  url?: string | null;
  description?: string | null;
  events?: string[] | null;
  enabled?: boolean | null;
}

export interface WebhooksEndpointRef {
  id: string;
}

export interface WebhooksDelivery {
  id: string;
  endpoint: string;
  url: string;
  event: string;
  status: "pending" | "sent" | "failed" | "skipped";
  attempts: number;
  /** Código HTTP da última resposta */
  response_status: number | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
  delivered_at: string | null;
}

export interface WebhooksDeliveryPage {
  items: WebhooksDelivery[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface WebhooksDeliveryQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  endpoint?: string | null;
  status?: "pending" | "sent" | "failed" | "skipped" | null;
  event?: string | null;
}

export interface WebhooksDeliveryRef {
  id: string;
}

export interface WebhooksCatalogEvent {
  /** Nome completo: <serviço>.<evento> */
  name: string;
  service: string;
  description: string;
  /** JSON Schema do data */
  payload_schema: Record<string, unknown>;
}

export interface WebhooksEventList {
  items: WebhooksCatalogEvent[];
}

export interface WebhooksDeliveryChanged {
  id: string;
  status: "pending" | "sent" | "failed" | "skipped";
}

/** svc-webhooks · /api/v1/webhooks */
export const webhooks = {
  /** GET /api/v1/webhooks/endpoints · http · exige token */
  endpoints: (options?: RequestOptions) =>
    request<WebhooksEndpointList>("GET", "/api/v1/webhooks/endpoints", undefined, options),
  /** POST /api/v1/webhooks/endpoints · http · exige token */
  createEndpoint: (body: WebhooksEndpointInput, options?: RequestOptions) =>
    request<WebhooksEndpointSecret>("POST", "/api/v1/webhooks/endpoints", body, options),
  /** POST /api/v1/webhooks/endpoints/update · http · exige token */
  updateEndpoint: (body: WebhooksEndpointUpdate, options?: RequestOptions) =>
    request<WebhooksEndpoint>("POST", "/api/v1/webhooks/endpoints/update", body, options),
  /** POST /api/v1/webhooks/endpoints/remove · http · exige token */
  removeEndpoint: (body: WebhooksEndpointRef, options?: RequestOptions) =>
    request<WebhooksEndpointList>("POST", "/api/v1/webhooks/endpoints/remove", body, options),
  /** POST /api/v1/webhooks/endpoints/rotate · http · exige token */
  rotateSecret: (body: WebhooksEndpointRef, options?: RequestOptions) =>
    request<WebhooksEndpointSecret>("POST", "/api/v1/webhooks/endpoints/rotate", body, options),
  /** POST /api/v1/webhooks/endpoints/test · http · exige token */
  testEndpoint: (body: WebhooksEndpointRef, options?: RequestOptions) =>
    request<WebhooksDelivery>("POST", "/api/v1/webhooks/endpoints/test", body, options),
  /** GET /api/v1/webhooks/deliveries · http · exige token */
  deliveries: (query?: WebhooksDeliveryQuery, options?: RequestOptions) =>
    request<WebhooksDeliveryPage>("GET", withQuery("/api/v1/webhooks/deliveries", query), undefined, options),
  /** POST /api/v1/webhooks/deliveries/retry · http · exige token */
  retryDelivery: (body: WebhooksDeliveryRef, options?: RequestOptions) =>
    request<WebhooksDelivery>("POST", "/api/v1/webhooks/deliveries/retry", body, options),
  /** GET /api/v1/webhooks/events · http · exige token */
  events: (options?: RequestOptions) =>
    request<WebhooksEventList>("GET", "/api/v1/webhooks/events", undefined, options),
};

/** Eventos ao vivo (live: dos manifestos): tópico → o que o evento carrega. Use com useLive/useLiveQuery. */
export interface LiveTopics {
  /** svc-ai · bus.live("ai.uso", ...) */
  "ai.uso": AiRecorded;
  /** svc-identity · bus.live("identity.membros", ...) */
  "identity.membros": IdentityMembersChanged;
  /** svc-identity · bus.live("identity.acesso", ...) */
  "identity.acesso": IdentityAccessChanged;
  /** svc-notify · bus.live("notify.nova", ...) */
  "notify.nova": NotifyNotification;
  /** svc-plans · bus.live("plans.uso", ...) */
  "plans.uso": PlansUsageChanged;
  /** svc-webhooks · bus.live("webhooks.entrega", ...) */
  "webhooks.entrega": WebhooksDeliveryChanged;
}

/** Módulos (o MODULE de cada services/svc-<nome>/schemas.py): o meta.module das telas e os grupos do menu. */
export const appModules = {
  ai: { title: "IA", description: "Modelos de IA, chaves e consumo", category: "Integrações", core: true },
  identity: { title: "Pessoas e acesso", description: "Contas, organizações, membros e convites", category: "Organização", core: true },
  notify: { title: "Avisos", description: "Avisos na tela e por e-mail", category: "Organização", core: true },
  plans: { title: "Plano", description: "Plano, módulos e consumo da organização", category: "Organização", core: true },
  webhooks: { title: "Webhooks", description: "Eventos para os sistemas da organização", category: "Integrações", core: true },
} as const;

/** Nome de um módulo: o do serviço, sem svc-. */
export type ModuleName = keyof typeof appModules;
