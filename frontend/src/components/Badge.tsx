import type { ReactNode } from "react";
import { Badge as UiBadge } from "@/components/ui/badge";

const TONE = {
  neutral: { variant: "secondary", className: "" },
  accent: { variant: "default", className: "" },
  success: { variant: "outline", className: "border-transparent bg-success/10 text-success" },
  warning: { variant: "outline", className: "border-transparent bg-warning/15 text-warning" },
  danger: { variant: "destructive", className: "" },
} as const;

export interface BadgeProps {
  /** Cor semântica. Padrão: neutral. */
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
  children: ReactNode;
}

/** Etiqueta curta para status, papéis ou categorias. */
export function Badge({ tone = "neutral", children }: BadgeProps) {
  const { variant, className } = TONE[tone];
  return (
    <UiBadge variant={variant} className={className}>
      {children}
    </UiBadge>
  );
}
