import type { ReactNode } from "react";

const GAP = { sm: "gap-2", md: "gap-4", lg: "gap-8" };

export interface StackProps {
  /** Espaço entre os itens. Padrão: md. */
  gap?: "sm" | "md" | "lg";
  children: ReactNode;
}

/** Empilha itens na vertical com espaçamento uniforme. */
export function Stack({ gap = "md", children }: StackProps) {
  return <div className={`flex flex-col ${GAP[gap]}`}>{children}</div>;
}
