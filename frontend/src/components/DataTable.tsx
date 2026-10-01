import type { ReactNode } from "react";

export interface DataTableProps<T> {
  /** Colunas: header é o título; render formata a célula (padrão: String(row[key])). */
  columns: { key: string; header: string; render?: (row: T) => ReactNode }[];
  rows: T[];
  /** Identificador estável de cada linha (ex.: row => row.id). */
  rowKey: (row: T) => string;
  /** Exibido quando não há linhas. Padrão: "Nada por aqui ainda." */
  empty?: ReactNode;
  /** Legenda acessível que descreve a tabela. */
  caption?: string;
}

/** Tabela de dados tipada, com colunas declarativas e estado vazio. Rola na horizontal em telas estreitas. */
export function DataTable<T>({ columns, rows, rowKey, empty = "Nada por aqui ainda.", caption }: DataTableProps<T>) {
  if (rows.length === 0) {
    return <p className="rounded-card border border-dashed border-line px-4 py-8 text-center text-sm text-muted">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-card border border-line bg-panel">
      <table className="w-full text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="border-b border-line text-muted">
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className="px-4 py-3 font-medium">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-line last:border-0">
              {columns.map((column) => (
                <td key={column.key} className="px-4 py-3">
                  {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
