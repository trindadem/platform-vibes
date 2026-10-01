import type { ReactNode } from "react";

export interface KeyValueProps {
  /** Pares rótulo/valor, na ordem de exibição. */
  items: { label: string; value: ReactNode }[];
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
export function KeyValue({ items }: KeyValueProps) {
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-[max-content_1fr]">
      {items.map((item) => (
        <div key={item.label} className="contents">
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd className="font-medium break-all">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
