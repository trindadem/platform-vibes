// Gerado por gateway/contracts.py a partir de gateway/endpoints/*.yaml e services/*/schemas.py. Não edite:
// depois de mudar um manifesto ou um schemas.py, rode (da raiz) `uv run python gateway/contracts.py`.
import { request, type RequestOptions } from "./api";

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
};

/** Eventos ao vivo (live: dos manifestos): tópico → o que o evento carrega. Use com useLive/useLiveQuery. */
export interface LiveTopics {
  /** svc-identity · bus.live("identity.membros", ...) */
  "identity.membros": IdentityMembersChanged;
  /** svc-identity · bus.live("identity.acesso", ...) */
  "identity.acesso": IdentityAccessChanged;
}
