/**
 * Única porta para o backend (README §6): toda requisição passa pelo gateway por aqui.
 *
 * - Desembrulha o envelope: sucesso devolve `data`; erro vira ApiError com o código do backend.
 * - Envia o token da sessão (core/auth.ts se registra em configureSession). Resposta 401 de uma chamada com token
 *   renova a sessão pelo cookie uma vez e repete; se não der, encerra a sessão local.
 * - Timeout de 30 s. Gatilhos assíncronos (rotas NATS) aceitam Idempotency-Key: newIdempotencyKey().
 *
 * Páginas nunca chamam request: usam as funções geradas em contracts.ts através dos hooks
 *   const faturas = useQuery(loja.listar);                        // GET ao abrir a tela
 *   const fatura  = useQuery(loja.detalhe, { fatura_id });        // com parâmetros
 *   const criar   = useAction(loja.criar, { onSuccess: faturas.reload });
 * e entregam o estado aos componentes de receita (QueryTable, QueryView, ActionForm, ResourcePage).
 *
 * Listas paginadas (README §5.12): a rota GET com query: tem página, ordem, busca e filtros na URL da tela.
 *   const faturas = useListQuery(loja.listar);                    // ?page=2&q=padaria&status=paga
 *   const faturas = useListQuery(loja.listar, { live: "loja.criada" });  // e recarrega ao vivo
 * e entregam o estado ao ListView (busca, filtros, ordenação no cabeçalho e páginas).
 *
 * Tempo real (README §5.10):
 *   const resposta = useStream(assistente.responder);             // rota stream: pedaços tipados + resultado
 *   const lista = useLiveQuery("pedidos.criado", pedidos.listar);  // recarrega quando o evento chega
 *   useLive("pedidos.criado", (pedido) => ...);                    // reage a cada evento ao vivo
 * Uma conexão ao vivo por aba (GET /api/v1/live), aberta no primeiro uso e reaberta sozinha.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import type { LiveTopics } from "./contracts"; // só tipo: não cria ciclo de import em tempo de execução

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
  /** Sem token e sem renovação automática: só para as rotas de sessão (login, cadastro, refresh, logout). */
  anonymous?: boolean;
}

/** Como a sessão se liga às requisições. Registrado uma vez por core/auth.ts (api.ts não importa auth.ts). */
export interface SessionHooks {
  /** Token de acesso atual, ou null. */
  token: () => string | null;
  /** Renova a sessão (cookie de refresh). true se há um token novo. */
  renew: () => Promise<boolean>;
  /** A sessão acabou: limpa o estado local. */
  expired: () => void;
}

let session: SessionHooks = { token: () => null, renew: async () => false, expired: () => {} };

export function configureSession(hooks: SessionHooks): void {
  session = hooks;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface Envelope<T> {
  ok: boolean;
  service: string;
  data: T | null;
  error: { code: string; message: string; status: number; details: ApiErrorDetail[] } | null;
}

export async function request<T>(method: Method, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  return withSession(path, options, (token) => send<T>(method, path, body, options, token));
}

/** Opções de uma rota em pedaços: onDelta recebe cada pedaço; a promessa resolve com o resultado final. */
export interface StreamOptions<D> extends RequestOptions {
  onDelta?: (delta: D) => void;
}

/** Rota stream: true (SSE). Usada pelas funções geradas em contracts.ts; páginas usam useStream. */
export async function stream<D, T>(method: Method, path: string, body?: unknown, options: StreamOptions<D> = {}): Promise<T> {
  return withSession(path, options, (token) => sendStream<D, T>(method, path, body, options, token));
}

// Token vencido ou revogado: renova pelo cookie uma vez e repete com o token novo.
async function withSession<T>(path: string, options: RequestOptions, call: (token: string | null) => Promise<T>): Promise<T> {
  if (!path.startsWith("/api/") && path !== "/health") {
    throw new ApiError("ERRO_FRONT_INVALID_PATH", `Caminho fora do gateway: ${path}`, 0);
  }
  const token = options.anonymous ? null : session.token();
  try {
    return await call(token);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || !token) throw error;
    if (!(await session.renew())) {
      session.expired();
      throw error;
    }
    return call(session.token());
  }
}

function headersFor(token: string | null, body: unknown, options: RequestOptions, accept: string): Record<string, string> {
  const headers: Record<string, string> = { Accept: accept };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  return headers;
}

async function send<T>(method: Method, path: string, body: unknown, options: RequestOptions, token: string | null): Promise<T> {
  const headers = headersFor(token, body, options, "application/json");
  const timeout = AbortSignal.timeout(options.timeoutMs ?? 30_000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      credentials: "same-origin", // o cookie de refresh só existe em /api/v1/identity (Path do cookie)
    });
  } catch (cause) {
    if (options.signal?.aborted) throw cause;
    throw timeout.aborted
      ? new ApiError("ERRO_FRONT_TIMEOUT", "O servidor não respondeu a tempo.", 0)
      : new ApiError("ERRO_FRONT_NETWORK", "Sem conexão com o servidor.", 0);
  }
  return unwrap<T>(response.status, response.ok, await response.json().catch(() => null));
}

function unwrap<T>(status: number, ok: boolean, envelope: Envelope<T> | null): T {
  if (!envelope || typeof envelope.ok !== "boolean") {
    throw new ApiError("ERRO_FRONT_INVALID_RESPONSE", "Resposta fora do envelope.", status);
  }
  if (!envelope.ok || !ok) {
    const error = envelope.error;
    throw new ApiError(error?.code ?? `ERRO_HTTP_${status}`, error?.message ?? "Falha na requisição.", error?.status ?? status, error?.details ?? []);
  }
  return envelope.data as T;
}

async function sendStream<D, T>(method: Method, path: string, body: unknown, options: StreamOptions<D>, token: string | null): Promise<T> {
  // O tempo limite vale até a resposta começar; depois, quem vigia a pausa entre pedaços é o gateway.
  const opening = new AbortController();
  const timer = setTimeout(() => opening.abort(), options.timeoutMs ?? 30_000);
  const signal = options.signal ? AbortSignal.any([options.signal, opening.signal]) : opening.signal;
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: headersFor(token, body, options, "text/event-stream"),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      credentials: "same-origin",
    });
  } catch (cause) {
    if (options.signal?.aborted) throw cause;
    throw opening.signal.aborted
      ? new ApiError("ERRO_FRONT_TIMEOUT", "O servidor não respondeu a tempo.", 0)
      : new ApiError("ERRO_FRONT_NETWORK", "Sem conexão com o servidor.", 0);
  } finally {
    clearTimeout(timer);
  }
  if (!response.body || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
    return unwrap<T>(response.status, response.ok, await response.json().catch(() => null)); // erro antes de começar
  }
  try {
    for await (const { event, data } of readEvents(response.body)) {
      if (event === "delta") options.onDelta?.(JSON.parse(data) as D);
      else if (event === "done" || event === "error") return unwrap<T>(response.status, event === "done", JSON.parse(data));
    }
  } catch (cause) {
    if (cause instanceof ApiError || options.signal?.aborted) throw cause;
    throw new ApiError("ERRO_FRONT_NETWORK", "A conexão caiu no meio da resposta.", 0);
  }
  throw new ApiError("ERRO_FRONT_STREAM_INCOMPLETE", "A resposta terminou antes do fim.", 0);
}

/** Lê um corpo SSE: um evento por bloco separado por linha em branco; comentários (": ...") são ignorados. */
async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<{ event: string; data: string }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let event = "message";
        const data: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        if (data.length) yield { event, data: data.join("\n") };
        else if (event !== "message") yield { event, data: "{}" };
      }
    }
  } finally {
    reader.releaseLock();
  }
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
  useEffect(() => {
    const reloads = openQueries.get(fn) ?? new Set();
    reloads.add(reload);
    openQueries.set(fn, reloads);
    return () => {
      reloads.delete(reload);
      if (!reloads.size) openQueries.delete(fn);
    };
  }, [fn, reload]);
  return { ...state, reload };
}

const openQueries = new Map<unknown, Set<() => void>>();

/**
 * Busca de novo toda consulta aberta (useQuery, useListQuery, useLiveQuery) feita com esta função de contracts.ts,
 * em qualquer parte da tela. Uso: useAction(notify.readAll, { onSuccess: () => refresh(notify.unread) }).
 */
export function refresh(fn: (...args: never[]) => Promise<unknown>): void {
  openQueries.get(fn)?.forEach((reload) => reload());
}

/** Monta a query string de uma rota GET de lista: vazio, null e undefined ficam de fora; lista repete a chave. */
export function withQuery(path: string, query?: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item));
  }
  const text = search.toString();
  return text ? `${path}?${text}` : path;
}

/** Uma página de lista, como o Page[T] do backend devolve (core/surreal.py). */
export interface ListPage<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

/** Estado de useListQuery: o que o ListView recebe. */
export interface ListState<T> extends QueryState<ListPage<T>> {
  /** Parâmetros atuais da lista, como estão na URL (texto): page, size, sort, q e os filtros. */
  params: Record<string, string>;
  /** Muda parâmetros (vazio, null ou undefined remove). Mudança que não seja de página volta para a página 1. */
  set: (changes: Record<string, string | number | null | undefined>) => void;
}

/**
 * Receita de lista paginada: os parâmetros vivem na URL da tela (voltar, recarregar e compartilhar o link mantêm
 * página, busca e filtros) e vão para a rota como estão; o serviço ignora o que não declarou. Com live, recarrega
 * quando o tópico chega e quando a conexão ao vivo volta. Uso: useListQuery(loja.listar).
 */
export function useListQuery<Q extends object, T>(
  fn: (query?: Q, options?: RequestOptions) => Promise<ListPage<T>>,
  options: { live?: keyof LiveTopics } = {},
): ListState<T> {
  const location = useLocation();
  const navigate = useNavigate();
  const params = Object.fromEntries(new URLSearchParams(location.search));
  const query = useQuery(fn, params as Q); // a busca depende do texto dos parâmetros: objeto novo não refaz a requisição
  const { reload } = query;
  useEffect(() => {
    if (!options.live) return;
    const stopEvents = onLive(options.live, () => reload());
    const stopReconnects = onLiveReconnect(reload);
    return () => {
      stopEvents();
      stopReconnects();
    };
  }, [options.live, reload]);
  const latest = useRef({ location, navigate });
  latest.current = { location, navigate };
  // Identidade estável: quem depende de set num efeito (ex.: a busca com espera do ListView) não entra em laço.
  // Muda só a parte ?...: caminho e fragmento (#aba das Tabs) ficam como estão.
  const set = useCallback((changes: Record<string, string | number | null | undefined>) => {
    const { location: current, navigate: go } = latest.current;
    const next = new URLSearchParams(current.search);
    for (const [key, value] of Object.entries(changes)) {
      if (value === undefined || value === null || value === "") next.delete(key);
      else next.set(key, String(value));
    }
    if (!("page" in changes)) next.delete("page");
    const search = next.toString();
    go({ pathname: current.pathname, search: search ? `?${search}` : "", hash: current.hash }, { replace: true });
  }, []);
  return { ...query, params, set };
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

/** O que uploadFile precisa dos contratos: pedido do link de envio e o link devolvido (ex.: identity.logoUpload). */
export interface UploadTicket {
  key: string;
  url: string;
  headers: Record<string, string>;
}

/**
 * Envia um arquivo direto ao armazenamento (README §5.14): 1) pede o link assinado, 2) faz PUT do arquivo,
 * 3) confirma a key no serviço, que devolve o registro atualizado. O arquivo não passa pelo gateway.
 * Uso: await uploadFile(file, identity.logoUpload, identity.setLogo).
 */
export async function uploadFile<T>(
  file: File,
  sign: (body: { filename: string; content_type: string; size: number }) => Promise<UploadTicket>,
  confirm: (body: { key: string }) => Promise<T>,
): Promise<T> {
  const ticket = await sign({ filename: file.name, content_type: file.type || "application/octet-stream", size: file.size });
  let response: Response;
  try {
    response = await fetch(ticket.url, { method: "PUT", headers: ticket.headers, body: file });
  } catch {
    throw new ApiError("ERRO_FRONT_UPLOAD", "Não foi possível enviar o arquivo. Verifique a conexão e tente de novo.", 0);
  }
  if (!response.ok) throw new ApiError("ERRO_FRONT_UPLOAD", "O armazenamento recusou o arquivo.", response.status);
  return confirm({ key: ticket.key });
}

/** Hook: prepara o envio de um arquivo (ver uploadFile) com estado de envio e erro. Uso: const logo = useUpload(identity.logoUpload, identity.setLogo); logo.run(file). */
export function useUpload<T>(
  sign: Parameters<typeof uploadFile<T>>[1],
  confirm: Parameters<typeof uploadFile<T>>[2],
  options: { onSuccess?: (result: T) => void } = {},
): ActionState<[File], T> {
  return useAction((file: File) => uploadFile(file, sign, confirm), options);
}

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("ERRO_FRONT_UNKNOWN", String(error), 0);
}

/** Estado de uma rota em pedaços: o que a tela mostra enquanto a resposta chega. */
export interface StreamState<B, D, T> {
  /** Começa (ignora cliques enquanto a anterior não termina). Devolve o resultado final ou undefined. */
  start: (body: B) => Promise<T | undefined>;
  /** Pedaços recebidos até agora, na ordem. */
  deltas: D[];
  result: T | null;
  error: ApiError | null;
  running: boolean;
  /** Interrompe a resposta (o serviço para de gerar). */
  cancel: () => void;
}

/**
 * Hook: chama uma rota stream: true de contracts.ts e acumula os pedaços.
 * Uso: const resposta = useStream(assistente.responder); resposta.start({ pergunta }); resposta.deltas.map(...).
 */
export function useStream<B, D, T>(fn: (body: B, options?: StreamOptions<D>) => Promise<T>): StreamState<B, D, T> {
  const [state, setState] = useState<{ deltas: D[]; result: T | null; error: ApiError | null; running: boolean }>({
    deltas: [],
    result: null,
    error: null,
    running: false,
  });
  const controller = useRef<AbortController | null>(null);
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => () => controller.current?.abort(), []);

  const start = useCallback(async (body: B) => {
    if (controller.current) return undefined;
    const current = new AbortController();
    controller.current = current;
    setState({ deltas: [], result: null, error: null, running: true });
    try {
      const result = await latest.current(body, {
        signal: current.signal,
        onDelta: (delta) => setState((previous) => ({ ...previous, deltas: [...previous.deltas, delta] })),
      });
      setState((previous) => ({ ...previous, result, running: false }));
      return result;
    } catch (error) {
      const stopped = current.signal.aborted;
      setState((previous) => ({ ...previous, running: false, error: stopped ? null : toApiError(error) }));
      return undefined;
    } finally {
      controller.current = null;
    }
  }, []);

  const cancel = useCallback(() => controller.current?.abort(), []);
  return { ...state, start, cancel };
}

// ── Ao vivo: uma conexão por aba, compartilhada por todos os hooks ─────────────

const LIVE_PATH = "/api/v1/live";
const liveHandlers = new Map<string, Set<(event: unknown) => void>>();
const liveReconnects = new Set<() => void>();
let liveController: AbortController | null = null;
let liveRetry: ReturnType<typeof setTimeout> | undefined;
let liveFailures = 0;
let liveOpenedBefore = false;

/** Assina um tópico ao vivo fora de componente (core/auth.ts). Devolve a função que cancela. */
export function onLive<K extends keyof LiveTopics>(topic: K, handler: (event: LiveTopics[K]) => void): () => void {
  const key = topic as string;
  const handlers = liveHandlers.get(key) ?? new Set();
  const wrapped = handler as (event: unknown) => void;
  handlers.add(wrapped);
  liveHandlers.set(key, handlers);
  openLive();
  return () => {
    handlers.delete(wrapped);
    if (!handlers.size) liveHandlers.delete(key);
    if (!liveHandlers.size) closeLive();
  };
}

/** Chamado quando a conexão volta depois de cair: o que se perdeu fora do ar deve ser buscado de novo. */
export function onLiveReconnect(handler: () => void): () => void {
  liveReconnects.add(handler);
  return () => liveReconnects.delete(handler);
}

/** Reabre a conexão com a sessão atual. core/auth.ts chama ao entrar, trocar de organização ou sair. */
export function restartLive(): void {
  closeLive();
  liveOpenedBefore = false;
  openLive();
}

/** Hook: reage a cada evento ao vivo do tópico (tipado pelo LiveTopics de contracts.ts). */
export function useLive<K extends keyof LiveTopics>(topic: K, handler: (event: LiveTopics[K]) => void): void {
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => onLive(topic, (event) => latest.current(event)), [topic]);
}

/** Receita: useQuery que recarrega sozinho quando o tópico chega e quando a conexão ao vivo volta. */
export function useLiveQuery<K extends keyof LiveTopics, T, A extends unknown[]>(
  topic: K,
  fn: (...args: [...A, RequestOptions?]) => Promise<T>,
  ...args: A
): QueryState<T> {
  const query = useQuery(fn, ...args);
  const { reload } = query;
  useEffect(() => {
    const stopEvents = onLive(topic, () => reload());
    const stopReconnects = onLiveReconnect(reload);
    return () => {
      stopEvents();
      stopReconnects();
    };
  }, [topic, reload]);
  return query;
}

function openLive(): void {
  if (liveController || !liveHandlers.size) return;
  const token = session.token();
  if (!token) return; // sem sessão: restartLive() abre quando alguém entrar
  const controller = new AbortController();
  liveController = controller;
  clearTimeout(liveRetry);
  void runLive(controller, token);
}

function closeLive(): void {
  clearTimeout(liveRetry);
  liveController?.abort();
  liveController = null;
}

async function runLive(controller: AbortController, token: string): Promise<void> {
  let immediately = false;
  try {
    const response = await fetch(LIVE_PATH, {
      headers: { Accept: "text/event-stream", Authorization: `Bearer ${token}` },
      signal: controller.signal,
      credentials: "same-origin",
    });
    if (response.status === 401) {
      immediately = await session.renew();
      if (!immediately) session.expired();
    } else if (response.ok && response.body) {
      if (liveOpenedBefore) liveReconnects.forEach((handler) => handler());
      liveOpenedBefore = true;
      liveFailures = 0;
      for await (const { event, data } of readEvents(response.body)) {
        if (event === "expired") {
          immediately = true; // o token desta conexão venceu: reabre com o token já renovado
          break;
        }
        liveHandlers.get(event)?.forEach((handler) => handler(JSON.parse(data)));
      }
    }
  } catch {
    if (controller.signal.aborted) return;
  }
  if (liveController !== controller) return; // foi fechada ou substituída
  liveController = null;
  const wait = immediately ? 0 : Math.min(30_000, 1000 * 2 ** liveFailures++); // espera crescente até 30 s
  liveRetry = setTimeout(openLive, wait);
}
