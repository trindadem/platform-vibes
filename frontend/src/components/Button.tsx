import type { ReactNode } from "react";
import { Button as UiButton } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

const VARIANT = { primary: "default", secondary: "outline", ghost: "ghost", danger: "destructive" } as const;
const SIZE = { sm: "sm", md: "default" } as const;

export interface ButtonProps {
  /** Estilo visual. Padrão: primary. */
  variant?: "primary" | "secondary" | "ghost" | "danger";
  /** Altura. Padrão: md. */
  size?: "sm" | "md";
  /** submit dentro de Form. Padrão: button. */
  type?: "button" | "submit";
  /** Mostra que a ação está em andamento e bloqueia novos cliques. */
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
}

/**
 * Botão de ação com variantes, tamanhos e estado de carregamento.
 *
 * @category Formulários
 * @example
 * <Button variant="secondary" onClick={salvar}>Cancelar</Button>
 */
export function Button({ variant = "primary", size = "md", type = "button", loading = false, disabled = false, onClick, children }: ButtonProps) {
  return (
    <UiButton type={type} variant={VARIANT[variant]} size={SIZE[size]} onClick={onClick} disabled={disabled || loading} aria-busy={loading}>
      {loading && <Spinner aria-hidden="true" role="presentation" aria-label={undefined} />}
      {children}
    </UiButton>
  );
}
