import type { ReactNode } from "react";

export interface KeyValueProps {
  /** Pares rótulo/valor, na ordem de exibição. */
  items: { label: string; value: ReactNode }[];
}

/** Lista de pares rótulo/valor para detalhes de um registro. */
export function KeyValue({ items }: KeyValueProps) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]">
      {items.map((item) => (
        <div key={item.label} className="contents">
          <dt className="text-sm text-muted">{item.label}</dt>
          <dd className="text-sm break-all">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
