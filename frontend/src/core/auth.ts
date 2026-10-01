/**
 * Sessão no navegador (README §6), sobre o svc-identity.
 *
 * - O token de acesso fica só em memória (nunca em localStorage/sessionStorage). O refresh mora num cookie HttpOnly
 *   que o JavaScript não lê: ao abrir a página, restoreSession() renova pelo cookie e a sessão volta.
 * - O token é renovado sozinho um minuto antes de expirar; 401 numa chamada também renova (core/api.ts).
 * - Abas do mesmo navegador compartilham a sessão: entrar, trocar de organização ou sair numa aba vale para todas.
 * - Removida de uma organização, a pessoa recebe identity.acesso ao vivo e a sessão é renovada na hora.
 * - Páginas usam useSession() para exibir e as ações (login, signup, logout, switchTenant, createTenant,
 *   acceptInvite) com useAction. Quem decide o acesso é sempre o backend.
 */
import { useSyncExternalStore } from "react";
import { ApiError, configureSession, onLive, restartLive } from "./api";
import { identity, type IdentityAuthResult, type IdentityLoginInput, type IdentitySignupInput, type IdentityTenant } from "./contracts";

export type Tenant = IdentityTenant;

export interface Session {
  /** Token de acesso (memória). */
  token: string;
  expiresAt: Date;
  user: { id: string; name: string; email: string };
  /** Organização ativa: o token vale para ela. */
  tenant: Tenant | null;
  /** Todas as organizações da pessoa. */
  tenants: Tenant[];
  /** Papéis na organização ativa (owner, admin, member). */
  roles: string[];
}

export interface AuthState {
  /** false enquanto a sessão é restaurada pelo cookie ao abrir a página. */
  ready: boolean;
  session: Session | null;
}

const ANONYMOUS = { anonymous: true } as const;
const listeners = new Set<() => void>();
const tabs = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("cv-frame.session");
let state: AuthState = { ready: false, session: null };
let timer: ReturnType<typeof setTimeout> | undefined;
let renewing: Promise<boolean> | null = null;

configureSession({ token: () => state.session?.token ?? null, renew, expired: () => clear(true) });

tabs?.addEventListener("message", (event: MessageEvent<"changed" | "signed-out">) => {
  if (event.data === "signed-out") clear(false);
  else void renew(); // outra aba entrou ou trocou de organização: pega a sessão nova pelo cookie
});

// Perdeu o acesso à organização ativa: a renovação devolve a sessão em outra organização (ou nenhuma).
onLive("identity.acesso", () => void renew());

/** Chamado uma vez em main.tsx: tenta voltar à sessão pelo cookie. */
export async function restoreSession(): Promise<void> {
  await renew();
  update({ ready: true });
}

export function login(body: IdentityLoginInput): Promise<Session> {
  return open(identity.login(body, ANONYMOUS));
}

export function signup(body: IdentitySignupInput): Promise<Session> {
  return open(identity.signup(body, ANONYMOUS));
}

export async function logout(): Promise<void> {
  try {
    await identity.logout({}, ANONYMOUS);
  } finally {
    clear(true);
  }
}

export function switchTenant(tenant: string): Promise<Session> {
  return open(identity.switchTenant({ tenant }));
}

export function createTenant(body: { name: string }): Promise<Session> {
  return open(identity.createTenant(body));
}

export function acceptInvite(code: string): Promise<Session> {
  return open(identity.join({ code }));
}

/** Link que o convidado abre (tela /convite). */
export function inviteLink(code: string): string {
  return `${window.location.origin}/convite?codigo=${encodeURIComponent(code)}`;
}

/** Hook: sessão atual (null sem sessão), re-renderizando quando muda. */
export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, () => state.session, () => null);
}

/** Hook do App.tsx: sessão + se a restauração inicial já terminou. */
export function useAuthState(): AuthState {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export function hasRoles(session: Session | null, ...roles: string[]): boolean {
  return session !== null && roles.every((role) => session.roles.includes(role));
}

/** Um dos papéis basta (ex.: hasAnyRole(sessao, "owner", "admin")). */
export function hasAnyRole(session: Session | null, ...roles: string[]): boolean {
  return session !== null && roles.some((role) => session.roles.includes(role));
}

async function open(call: Promise<IdentityAuthResult>): Promise<Session> {
  const session = apply(await call);
  tabs?.postMessage("changed");
  return session;
}

/** Renova pelo cookie. Várias chamadas ao mesmo tempo viram uma só. */
function renew(): Promise<boolean> {
  renewing ??= (async () => {
    try {
      for (const wait of [0, 600]) {
        if (wait) await new Promise((resolve) => setTimeout(resolve, wait));
        try {
          apply(await identity.refresh({}, ANONYMOUS));
          return true;
        } catch (error) {
          // Outra aba girou o mesmo refresh há pouco: o cookie já é o novo, tenta de novo uma vez.
          if (!(error instanceof ApiError) || error.code !== "ERRO_IDENTITY_SESSION_ROTATED") break;
        }
      }
      clear(false);
      return false;
    } finally {
      renewing = null;
    }
  })();
  return renewing;
}

function apply(auth: IdentityAuthResult): Session {
  const session: Session = {
    token: auth.access_token,
    expiresAt: new Date(Date.now() + auth.expires_in * 1000),
    user: auth.user,
    tenant: auth.tenant,
    tenants: auth.tenants,
    roles: auth.tenant?.roles ?? [],
  };
  clearTimeout(timer);
  timer = setTimeout(() => void renew(), Math.max(5_000, (auth.expires_in - 60) * 1000));
  const before = state.session;
  update({ ready: true, session });
  if (before?.user.id !== session.user.id || before?.tenant?.id !== session.tenant?.id) restartLive();
  return session;
}

function clear(broadcast: boolean): void {
  clearTimeout(timer);
  if (state.session && broadcast) tabs?.postMessage("signed-out");
  update({ session: null });
  restartLive(); // sem sessão, a conexão ao vivo fica fechada
}

function update(changes: Partial<AuthState>): void {
  state = { ...state, ...changes };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
