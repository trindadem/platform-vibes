import type { ReactNode } from "react";

export interface KeyValueProps {
  /** Pares rótulo/valor, na ordem de exibição. */
  items: { label: string; value: ReactNode }[];
  /** Rótulo acima do valor, para colunas estreitas (ex.: a lateral de Columns). Padrão: lado a lado em telas largas. */
  stacked?: boolean;
}

/**
 * Lista de pares rótulo/valor para detalhes de um registro.
 *
 * @category Dados
 * @example
 * <KeyValue
 *   items={[
 *     { label: "Cliente", value: "Padaria Aurora" },
 *     { label: "Status", value: <StatusBadge value="paga" /> },
 *   ]}
 * />
 */
export function KeyValue({ items, stacked = false }: KeyValueProps) {
  if (stacked) {
    return (
      <dl className="flex flex-col gap-3 text-sm">
        {items.map((item) => (
          <div key={item.label} className="flex flex-col gap-0.5">
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className="font-medium wrap-anywhere">{item.value}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-[max-content_1fr]">
      {items.map((item) => (
        <div key={item.label} className="contents">
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd className="min-w-0 font-medium wrap-anywhere">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
