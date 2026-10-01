export interface CodeProps {
  /** Texto exibido em fonte monoespaçada. */
  children: string;
  /** Bloco próprio (quebra linhas longas) em vez de trecho no meio do texto. Padrão: false. */
  block?: boolean;
}

/**
 * Trecho de código, comando ou identificador em fonte monoespaçada.
 *
 * @category Formatação
 * @example
 * <Code>{"python gateway/contracts.py"}</Code>
 */
export function Code({ children, block = false }: CodeProps) {
  if (block) {
    return <pre className="overflow-x-auto rounded-lg border bg-muted/50 px-4 py-3 font-mono text-xs break-all whitespace-pre-wrap">{children}</pre>;
  }
  return <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">{children}</code>;
}
