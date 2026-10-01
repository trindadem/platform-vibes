import type { ReactNode } from "react";

export interface HeadingProps {
  /** Nível do título. O h1 é do Page. Padrão: 2. */
  level?: 2 | 3;
  children: ReactNode;
}

/**
 * Título de seção dentro de uma tela (h2 ou h3).
 *
 * @category Texto
 * @example
 * <Heading level={3}>Itens da fatura</Heading>
 */
export function Heading({ level = 2, children }: HeadingProps) {
  return level === 2 ? (
    <h2 className="font-heading text-xl font-semibold tracking-tight">{children}</h2>
  ) : (
    <h3 className="font-heading text-base font-semibold">{children}</h3>
  );
}
