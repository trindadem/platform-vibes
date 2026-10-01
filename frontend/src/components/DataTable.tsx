import type { ReactNode } from "react";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

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

/** Tabela de dados tipada. Em espaço estreito, cada linha vira um cartão com rótulo e valor. */
export function DataTable<T>({ columns, rows, rowKey, empty = "Nada por aqui ainda.", caption }: DataTableProps<T>) {
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
              {columns.map((column) => (
                <TableHead key={column.key}>{column.header}</TableHead>
              ))}
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
                <span className="min-w-0 truncate text-right font-medium">{cell(row, column)}</span>
              </div>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}
