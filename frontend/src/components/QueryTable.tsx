import { DataTable, type DataTableProps } from "./DataTable";
import { QueryView, type QueryViewProps } from "./QueryView";

export interface QueryTableProps<T> {
  /** Estado de useQuery(...) cuja resposta é uma lista. */
  query: QueryViewProps<T[]>["query"];
  /** Colunas como em DataTable: { key, header, render? }. */
  columns: DataTableProps<T>["columns"];
  /** Identificador estável de cada linha (ex.: f => f.id). */
  rowKey: (row: T) => string;
  /** Título quando a lista vem vazia. Padrão: "Nada por aqui ainda." */
  empty?: string;
  /** Legenda acessível da tabela. */
  caption?: string;
}

/**
 * Receita de lista: consulta + tabela, com carregamento, erro, vazio e cartões em espaço estreito.
 *
 * @category Receitas
 * @example
 * <QueryTable
 *   query={faturas}
 *   rowKey={(f) => f.id}
 *   columns={[
 *     { key: "cliente", header: "Cliente" },
 *     { key: "status", header: "Status", render: (f) => <StatusBadge value={f.status} /> },
 *   ]}
 * />
 */
export function QueryTable<T>({ query, columns, rowKey, empty, caption }: QueryTableProps<T>) {
  return (
    <QueryView query={query} empty={empty}>
      {(rows) => <DataTable rows={rows} columns={columns} rowKey={rowKey} caption={caption} />}
    </QueryView>
  );
}
