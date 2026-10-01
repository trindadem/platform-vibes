/**
 * Sessão no navegador (README §6).
 *
 * O token fica em memória e no sessionStorage (some ao fechar a aba). O conteúdo decodificado
 * (usuário, papéis, expiração) serve só para a interface: quem decide o acesso é o backend, que
 * verifica a assinatura em toda requisição. Produção: login por um serviço de auth com refresh em
 * cookie httpOnly (sprint.md).
 */
import { useSyncExternalStore } from "react";

export interface Session {
  token: string;
  sub: string;
  roles: string[];
  /** Organização ativa (claim tenant); null se o token não tem organização. */
  tenant: string | null;
  expiresAt: Date;
}

const STORAGE_KEY = "cv-frame.token";
const listeners = new Set<() => void>();
let current: Session | null = restore();

/** Abre a sessão com um token. Token malformado ou expirado é recusado. */
export function signIn(token: string): Session {
  const session = decode(token.trim());
  if (!session) throw new Error("Token inválido ou expirado.");
  sessionStorage.setItem(STORAGE_KEY, session.token);
  update(session);
  return session;
}

export function signOut(): void {
  sessionStorage.removeItem(STORAGE_KEY);
  update(null);
}

/** Token para o header Authorization (null se não há sessão ou se expirou). */
export function getToken(): string | null {
  if (current && current.expiresAt.getTime() <= Date.now()) signOut();
  return current?.token ?? null;
}

/** Hook: a sessão atual, re-renderizando quando ela muda. */
export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}

export function hasRoles(session: Session | null, ...roles: string[]): boolean {
  return session !== null && roles.every((role) => session.roles.includes(role));
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function update(session: Session | null): void {
  current = session;
  listeners.forEach((listener) => listener());
}

function restore(): Session | null {
  const token = sessionStorage.getItem(STORAGE_KEY);
  return token ? decode(token) : null;
}

function decode(token: string): Session | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const bytes = Uint8Array.from(atob(payload.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
    const claims = JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
    const expiresAt = new Date(Number(claims.exp) * 1000);
    if (typeof claims.sub !== "string" || !(expiresAt.getTime() > Date.now())) return null;
    const roles = Array.isArray(claims.roles) ? claims.roles.filter((r): r is string => typeof r === "string") : [];
    const tenant = typeof claims.tenant === "string" ? claims.tenant : null;
    return { token, sub: claims.sub, roles, tenant, expiresAt };
  } catch {
    return null;
  }
}
