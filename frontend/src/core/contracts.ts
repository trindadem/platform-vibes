// Gerado por gateway/contracts.py a partir de gateway/endpoints/*.yaml e services/*/schemas.py. Não edite:
// depois de mudar um manifesto ou um schemas.py, rode (da raiz) `uv run python gateway/contracts.py`.
import { request, withQuery, type RequestOptions } from "./api";

/** Resposta de toda rota NATS: o id da mensagem publicada (o mesmo para a mesma Idempotency-Key). */
export interface Dispatched {
  message_id: string;
}

/** GET /health do gateway. */
export interface GatewayHealth {
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
}

export interface IdentityInvite {
  /** Código para o link de convite (mostrado uma única vez) */
  code: string;
  role: "owner" | "admin" | "member";
  expires_at: string;
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
  /** POST /api/v1/identity/organization/logo/remove · http · exige token */
  removeLogo: (body: unknown, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/logo/remove", body, options),
};

/** Eventos ao vivo (live: dos manifestos): tópico → o que o evento carrega. Use com useLive/useLiveQuery. */
export interface LiveTopics {
  /** svc-ai · bus.live("ai.uso", ...) */
  "ai.uso": AiRecorded;
  /** svc-identity · bus.live("identity.membros", ...) */
  "identity.membros": IdentityMembersChanged;
  /** svc-identity · bus.live("identity.acesso", ...) */
  "identity.acesso": IdentityAccessChanged;
}
