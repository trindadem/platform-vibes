import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface DataTableProps<T> {
  /** Colunas: header é o título; render formata a célula (padrão: String(row[key])); sort é o campo que ordena a coluna. */
  columns: { key: string; header: string; render?: (row: T) => ReactNode; sort?: string }[];
  rows: T[];
  /** Identificador estável de cada linha (ex.: row => row.id). */
  rowKey: (row: T) => string;
  /** Exibido quando não há linhas. Padrão: "Nada por aqui ainda." */
  empty?: ReactNode;
  /** Legenda acessível que descreve a tabela. */
  caption?: string;
  /** Ordem atual: "campo" (crescente) ou "-campo" (decrescente). */
  sort?: string | null;
  /** Clique no título de uma coluna com sort: crescente → decrescente → ordem padrão (null). */
  onSort?: (sort: string | null) => void;
}

/**
 * Tabela de dados tipada. Em espaço estreito, cada linha vira um cartão com rótulo e valor.
 * Com onSort, as colunas que têm sort viram botões de ordenação no cabeçalho.
 *
 * @category Dados
 * @example
 * <DataTable
 *   rows={[{ id: "f1", cliente: "Padaria Aurora", valor: 150 }]}
 *   rowKey={(r) => r.id}
 *   columns={[
 *     { key: "cliente", header: "Cliente" },
 *     { key: "valor", header: "Valor", render: (r) => <Money value={r.valor} /> },
 *   ]}
 * />
 */
export function DataTable<T>({ columns, rows, rowKey, empty = "Nada por aqui ainda.", caption, sort, onSort }: DataTableProps<T>) {
  if (rows.length === 0) {
    return <p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">{empty}</p>;
  }
  const cell = (row: T, column: DataTableProps<T>["columns"][number]) =>
    column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? "");

  return (
    <div className="@container">
      <div className="hidden overflow-hidden rounded-lg border @lg:block">
        <Table>
          {caption && <TableCaption className="sr-only">{caption}</TableCaption>}
          <TableHeader className="bg-muted/50">
            <TableRow>
              {columns.map((column) => {
                if (!column.sort || !onSort) return <TableHead key={column.key}>{column.header}</TableHead>;
                const direction = sort === column.sort ? "ascending" : sort === `-${column.sort}` ? "descending" : "none";
                const next = direction === "none" ? column.sort : direction === "ascending" ? `-${column.sort}` : null;
                const Icon = direction === "ascending" ? ArrowUp : direction === "descending" ? ArrowDown : ArrowUpDown;
                return (
                  <TableHead key={column.key} aria-sort={direction}>
                    <button
                      type="button"
                      onClick={() => onSort(next)}
                      className="-ml-2 inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                      {column.header}
                      <Icon aria-hidden className={direction === "none" ? "size-3.5 opacity-40" : "size-3.5"} />
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={rowKey(row)}>
                {columns.map((column) => (
                  <TableCell key={column.key}>{cell(row, column)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul aria-label={caption} className="divide-y rounded-lg border @lg:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)} className="flex flex-col gap-1.5 p-3 text-sm">
            {columns.map((column) => (
              <div key={column.key} className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">{column.header}</span>
                {/* Valor simples corta com reticências; conteúdo montado (render) quebra a linha para não sumir. */}
                <span className={`min-w-0 text-right font-medium ${column.render ? "break-words" : "truncate"}`}>{cell(row, column)}</span>
              </div>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}
