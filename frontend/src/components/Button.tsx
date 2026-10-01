import type { ReactNode } from "react";

const VARIANT = {
  primary: "bg-accent text-accent-ink hover:bg-accent/90",
  secondary: "border border-line bg-panel text-ink hover:bg-line/50",
  ghost: "text-ink hover:bg-line/60",
  danger: "bg-danger text-accent-ink hover:bg-danger/90",
};
const SIZE = { sm: "h-8 px-3 text-sm", md: "h-10 px-4 text-sm" };

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

/** Botão de ação com variantes, tamanhos e estado de carregamento. */
export function Button({ variant = "primary", size = "md", type = "button", loading = false, disabled = false, onClick, children }: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      aria-busy={loading}
      className={`inline-flex items-center justify-center gap-2 rounded-control font-medium transition-colors outline-accent focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]}`}
    >
      {loading && <span aria-hidden="true" className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}
