import type { ReactNode } from "react";

const TONE = { default: "text-ink", success: "text-success", danger: "text-danger" };

export interface StatProps {
  /** O que o número mede. */
  label: string;
  /** O valor em destaque. */
  value: ReactNode;
  /** Contexto curto abaixo do valor. */
  hint?: string;
  /** Cor do valor. Padrão: default. */
  tone?: "default" | "success" | "danger";
}

/** Indicador em destaque: rótulo, valor grande e contexto. Use dentro de Grid. */
export function Stat({ label, value, hint, tone = "default" }: StatProps) {
  return (
    <div className="flex flex-col gap-1 rounded-card border border-line bg-panel p-5">
      <span className="text-sm text-muted">{label}</span>
      <span className={`text-2xl font-semibold tabular-nums ${TONE[tone]}`}>{value}</span>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}
