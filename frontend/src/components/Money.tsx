const FORMATS = new Map<string, Intl.NumberFormat>();

export interface MoneyProps {
  /** Valor numérico; null ou undefined vira "—". */
  value: number | null | undefined;
  /** Moeda ISO. Padrão: BRL. */
  currency?: "BRL" | "USD" | "EUR";
}

/**
 * Valor monetário em pt-BR (R$ 1.234,56), com algarismos alinhados em tabelas.
 *
 * @category Formatação
 * @example
 * <Money value={1439.9} />
 */
export function Money({ value, currency = "BRL" }: MoneyProps) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  let format = FORMATS.get(currency);
  if (!format) {
    format = new Intl.NumberFormat("pt-BR", { style: "currency", currency });
    FORMATS.set(currency, format);
  }
  return <span className="tabular-nums">{format.format(value)}</span>;
}
