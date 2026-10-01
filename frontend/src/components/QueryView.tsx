import type { ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

export interface QueryViewProps<T> {
  /** Estado devolvido por useQuery(...) (src/core/api.ts). */
  query: { data: T | null; loading: boolean; error: { message: string } | null; reload: () => void };
  /** Desenha os dados quando chegam: (dados) => <KeyValue ... />. */
  children: (data: T) => ReactNode;
  /** Título quando o resultado é vazio (lista sem itens). Padrão: "Nada por aqui ainda." */
  empty?: string;
}

/**
 * Receita de consulta: mostra esqueleto ao carregar, erro com "Tentar de novo", vazio ou os dados.
 *
 * @category Receitas
 * @example
 * <QueryView query={fatura}>
 *   {(f) => <KeyValue items={[{ label: "Cliente", value: f.cliente }, { label: "Valor", value: <Money value={f.valor} /> }]} />}
 * </QueryView>
 */
export function QueryView<T>({ query, children, empty = "Nada por aqui ainda." }: QueryViewProps<T>) {
  if (query.loading && query.data === null) {
    return (
      <div role="status" aria-label="Carregando" className="flex flex-col gap-3">
        <Skeleton className="h-5 w-2/5" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-4/5" />
      </div>
    );
  }
  if (query.error) {
    return (
      <Alert tone="danger" title="Não foi possível carregar">
        <span className="flex flex-wrap items-center justify-between gap-3">
          {query.error.message}
          <Button size="sm" variant="secondary" onClick={query.reload}>
            Tentar de novo
          </Button>
        </span>
      </Alert>
    );
  }
  if (query.data === null || (Array.isArray(query.data) && query.data.length === 0)) {
    return <EmptyState title={empty} />;
  }
  return <>{children(query.data)}</>;
}
