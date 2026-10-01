import type { ReactNode } from "react";

const TONE = { default: "text-foreground", muted: "text-muted-foreground", danger: "text-destructive", success: "text-success" };
const SIZE = { sm: "text-sm leading-6", md: "text-base leading-7" };

export interface TextProps {
  /** Cor semântica. Padrão: default. */
  tone?: "default" | "muted" | "danger" | "success";
  /** Tamanho. Padrão: md. */
  size?: "sm" | "md";
  children: ReactNode;
}

/** Parágrafo de texto com tom e tamanho padronizados. */
export function Text({ tone = "default", size = "md", children }: TextProps) {
  return <p className={`${TONE[tone]} ${SIZE[size]}`}>{children}</p>;
}
