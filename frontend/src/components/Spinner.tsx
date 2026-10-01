export interface SpinnerProps {
  /** Texto para leitores de tela e exibido ao lado. Padrão: "Carregando". */
  label?: string;
}

/** Indicador de carregamento acessível. */
export function Spinner({ label = "Carregando" }: SpinnerProps) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <span aria-hidden="true" className="size-4 animate-spin rounded-full border-2 border-line border-t-accent" />
      {label}
    </span>
  );
}
