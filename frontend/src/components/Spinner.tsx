import { Spinner as UiSpinner } from "@/components/ui/spinner";

export interface SpinnerProps {
  /** Texto para leitores de tela e exibido ao lado. Padrão: "Carregando". */
  label?: string;
}

/** Indicador de carregamento acessível, com texto. */
export function Spinner({ label = "Carregando" }: SpinnerProps) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted-foreground">
      <UiSpinner aria-hidden="true" role="presentation" aria-label={undefined} />
      {label}
    </span>
  );
}
