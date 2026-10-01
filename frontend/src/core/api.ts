/**
 * Única porta para o backend (README §6): toda requisição passa pelo gateway por aqui.
 *
 * - Desembrulha o envelope: sucesso devolve `data`; erro vira ApiError com o código do backend.
 * - Envia o token da sessão; resposta 401 encerra a sessão local.
 * - Timeout de 30 s. Gatilhos assíncronos (rotas NATS) aceitam Idempotency-Key: newIdempotencyKey().
 */
import { useCallback, useEffect, useState } from "react";
import { getToken, signOut } from "./auth";

export interface ApiErrorDetail {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly details: ApiErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  idempotencyKey?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface Envelope<T> {
  ok: boolean;
  service: string;
  data: T | null;
  error: { code: string; message: string; status: number; details: ApiErrorDetail[] } | null;
}

export async function request<T>(method: Method, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  if (!path.startsWith("/api/") && path !== "/health") {
    throw new ApiError("ERRO_FRONT_INVALID_PATH", `Caminho fora do gateway: ${path}`, 0);
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  const timeout = AbortSignal.timeout(options.timeoutMs ?? 30_000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      credentials: "omit",
    });
  } catch (cause) {
    if (options.signal?.aborted) throw cause;
    throw timeout.aborted
      ? new ApiError("ERRO_FRONT_TIMEOUT", "O servidor não respondeu a tempo.", 0)
      : new ApiError("ERRO_FRONT_NETWORK", "Sem conexão com o servidor.", 0);
  }

  if (response.status === 401) signOut();
  const envelope = (await response.json().catch(() => null)) as Envelope<T> | null;
  if (!envelope || typeof envelope.ok !== "boolean") {
    throw new ApiError("ERRO_FRONT_INVALID_RESPONSE", "Resposta fora do envelope.", response.status);
  }
  if (!envelope.ok || !response.ok) {
    const error = envelope.error;
    throw new ApiError(error?.code ?? `ERRO_HTTP_${response.status}`, error?.message ?? "Falha na requisição.", response.status, error?.details ?? []);
  }
  return envelope.data as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, undefined, options),
  post: <T>(path: string, body: unknown, options?: RequestOptions) => request<T>("POST", path, body, options),
  put: <T>(path: string, body: unknown, options?: RequestOptions) => request<T>("PUT", path, body, options),
  patch: <T>(path: string, body: unknown, options?: RequestOptions) => request<T>("PATCH", path, body, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, undefined, options),
};

/** Chave para repetir um gatilho com segurança: a mesma chave nunca dispara dois workflows. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Hook: GET ao montar a tela (path null = não carrega). Uso: const { data, error, loading } = useApi<T>("/api/v1/..."). */
export function useApi<T>(path: string | null): ApiState<T> {
  const [state, setState] = useState<Omit<ApiState<T>, "reload">>({ data: null, error: null, loading: path !== null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: null }));
    api
      .get<T>(path, { signal: controller.signal })
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = error instanceof ApiError ? error : new ApiError("ERRO_FRONT_UNKNOWN", String(error), 0);
        setState({ data: null, error: apiError, loading: false });
      });
    return () => controller.abort();
  }, [path, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}
