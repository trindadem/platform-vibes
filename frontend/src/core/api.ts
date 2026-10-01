/**
 * Única porta para o backend (README §6): toda requisição passa pelo gateway por aqui.
 *
 * - Desembrulha o envelope: sucesso devolve `data`; erro vira ApiError com o código do backend.
 * - Envia o token da sessão; resposta 401 encerra a sessão local.
 * - Timeout de 30 s. Gatilhos assíncronos (rotas NATS) aceitam Idempotency-Key: newIdempotencyKey().
 *
 * Páginas nunca chamam request: usam as funções geradas em contracts.ts através dos hooks
 *   const faturas = useQuery(loja.listar);                        // GET ao abrir a tela
 *   const fatura  = useQuery(loja.detalhe, { fatura_id });        // com parâmetros
 *   const criar   = useAction(loja.criar, { onSuccess: faturas.reload });
 * e entregam o estado aos componentes de receita (QueryTable, QueryView, ActionForm, ResourcePage).
 */
import { useCallback, useEffect, useRef, useState } from "react";
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

/** Chave para repetir um gatilho com segurança: a mesma chave nunca dispara dois workflows. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

/** Estado de uma consulta: o que QueryView, QueryTable e ResourcePage recebem. */
export interface QueryState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** Busca de novo (ex.: depois de criar um item). */
  reload: () => void;
}

/**
 * Hook: chama uma função de contracts.ts ao montar a tela e quando os argumentos mudam.
 * Uso: useQuery(gateway.health) ou useQuery(loja.detalhe, { fatura_id }). Tipos inferidos do contrato.
 */
export function useQuery<T, A extends unknown[]>(fn: (...args: [...A, RequestOptions?]) => Promise<T>, ...args: A): QueryState<T> {
  const [state, setState] = useState<Omit<QueryState<T>, "reload">>({ data: null, error: null, loading: true });
  const [version, setVersion] = useState(0);
  // A busca depende só dos argumentos: função criada na hora (useQuery(() => ...)) não vira loop de requisições.
  const key = JSON.stringify(args);
  const latest = useRef({ fn, args });
  latest.current = { fn, args };

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: null }));
    latest.current
      .fn(...latest.current.args, { signal: controller.signal })
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ data: null, error: toApiError(error), loading: false });
      });
    return () => controller.abort();
  }, [key, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}

/** Estado de uma ação: o que ActionForm e ResourcePage recebem. */
export interface ActionState<A extends unknown[], T> {
  /** Executa a ação; ignora cliques enquanto a anterior não termina. Devolve o resultado ou undefined se falhou. */
  run: (...args: A) => Promise<T | undefined>;
  running: boolean;
  error: ApiError | null;
  result: T | null;
  reset: () => void;
}

/**
 * Hook: prepara uma ação (POST/PUT/PATCH/DELETE) de contracts.ts com estado de envio, erro e resultado.
 * Uso: const criar = useAction(loja.criar, { onSuccess: faturas.reload }); depois criar.run(corpo).
 * Para adaptar o formulário ao contrato: useAction((v: { valor: number }) => billing.execute({ ... })).
 */
export function useAction<A extends unknown[], T>(fn: (...args: A) => Promise<T>, options: { onSuccess?: (result: T) => void } = {}): ActionState<A, T> {
  const [state, setState] = useState<{ running: boolean; error: ApiError | null; result: T | null }>({ running: false, error: null, result: null });
  const running = useRef(false);
  const latest = useRef({ fn, onSuccess: options.onSuccess });
  latest.current = { fn, onSuccess: options.onSuccess };

  const run = useCallback(async (...args: A) => {
    if (running.current) return undefined;
    running.current = true;
    setState((previous) => ({ ...previous, running: true, error: null }));
    try {
      const result = await latest.current.fn(...args);
      setState({ running: false, error: null, result });
      latest.current.onSuccess?.(result);
      return result;
    } catch (error) {
      setState((previous) => ({ ...previous, running: false, error: toApiError(error) }));
      return undefined;
    } finally {
      running.current = false;
    }
  }, []);

  const reset = useCallback(() => setState({ running: false, error: null, result: null }), []);
  return { ...state, run, reset };
}

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("ERRO_FRONT_UNKNOWN", String(error), 0);
}
