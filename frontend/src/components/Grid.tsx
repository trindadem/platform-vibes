import type { ReactNode } from "react";

const COLS = { 1: "", 2: "sm:grid-cols-2", 3: "sm:grid-cols-2 lg:grid-cols-3", 4: "sm:grid-cols-2 lg:grid-cols-4" };

export interface GridProps {
  /** Colunas em telas largas; no celular é sempre 1. Padrão: 3. */
  cols?: 1 | 2 | 3 | 4;
  children: ReactNode;
}

/** Grade responsiva para cartões e indicadores: 1 coluna no celular, até 4 em telas largas. */
export function Grid({ cols = 3, children }: GridProps) {
  return <div className={`grid grid-cols-1 gap-4 ${COLS[cols]}`}>{children}</div>;
}
