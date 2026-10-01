import type { ReactNode } from "react";

const TONE = { default: "text-ink", muted: "text-muted", danger: "text-danger", success: "text-success" };
const SIZE = { sm: "text-sm", md: "text-base" };

export interface TextProps {
  /** Cor semântica. Padrão: default. */
  tone?: "default" | "muted" | "danger" | "success";
  /** Tamanho. Padrão: md. */
  size?: "sm" | "md";
  children: ReactNode;
}

/** Parágrafo de texto com tom e tamanho padronizados. */
export function Text({ tone = "default", size = "md", children }: TextProps) {
  return <p className={`${TONE[tone]} ${SIZE[size]} leading-relaxed`}>{children}</p>;
}
