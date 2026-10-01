import type { ReactNode } from "react";

const GAP = { sm: "gap-2", md: "gap-4", lg: "gap-8" };
const ALIGN = { start: "items-start", center: "items-center", end: "items-end", baseline: "items-baseline" };
const JUSTIFY = { start: "justify-start", between: "justify-between", end: "justify-end" };

export interface RowProps {
  /** Espaço entre os itens. Padrão: md. */
  gap?: "sm" | "md" | "lg";
  /** Alinhamento vertical. Padrão: center. */
  align?: "start" | "center" | "end" | "baseline";
  /** Distribuição horizontal. Padrão: start. */
  justify?: "start" | "between" | "end";
  /** Quebra linha quando não cabe. Padrão: true. */
  wrap?: boolean;
  children: ReactNode;
}

/** Coloca itens lado a lado, com alinhamento e quebra de linha controlados. */
export function Row({ gap = "md", align = "center", justify = "start", wrap = true, children }: RowProps) {
  return <div className={`flex ${wrap ? "flex-wrap" : ""} ${GAP[gap]} ${ALIGN[align]} ${JUSTIFY[justify]}`}>{children}</div>;
}
