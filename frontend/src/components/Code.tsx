export interface CodeProps {
  /** Texto exibido em fonte monoespaçada. */
  children: string;
  /** Bloco próprio (quebra linhas longas) em vez de trecho no meio do texto. Padrão: false. */
  block?: boolean;
}

/** Trecho de código, comando ou identificador em fonte monoespaçada. */
export function Code({ children, block = false }: CodeProps) {
  if (block) {
    return <pre className="overflow-x-auto rounded-control border border-line bg-surface p-3 font-mono text-sm break-all whitespace-pre-wrap">{children}</pre>;
  }
  return <code className="rounded bg-line/60 px-1.5 py-0.5 font-mono text-[0.9em]">{children}</code>;
}
