import type { ReactNode } from "react";

const TONE = {
  neutral: "bg-line/60 text-ink",
  accent: "bg-accent/10 text-accent",
  success: "bg-success/10 text-success",
  warning: "bg-warning/15 text-warning",
  danger: "bg-danger/10 text-danger",
};

export interface BadgeProps {
  /** Cor semântica. Padrão: neutral. */
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
  children: ReactNode;
}

/** Etiqueta curta para status, papéis ou categorias. */
export function Badge({ tone = "neutral", children }: BadgeProps) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>{children}</span>;
}
