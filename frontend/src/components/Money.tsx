const FORMATS = new Map<string, Intl.NumberFormat>();

export interface MoneyProps {
  /** Valor numérico; null ou undefined vira "—". */
  value: number | null | undefined;
  /** Moeda ISO. Padrão: BRL. */
  currency?: "BRL" | "USD" | "EUR";
  /** Casas decimais máximas, para valores abaixo de um centavo (ex.: custo de IA: 4). Padrão: 2. */
  digits?: number;
}

/**
 * Valor monetário em pt-BR (R$ 1.234,56), com algarismos alinhados em tabelas.
 *
 * @category Formatação
 * @example
 * <Money value={1439.9} />
 */
export function Money({ value, currency = "BRL", digits = 2 }: MoneyProps) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  const key = `${currency}:${digits}`;
  let format = FORMATS.get(key);
  if (!format) {
    format = new Intl.NumberFormat("pt-BR", { style: "currency", currency, minimumFractionDigits: Math.min(2, digits), maximumFractionDigits: digits });
    FORMATS.set(key, format);
  }
  return <span className="tabular-nums">{format.format(value)}</span>;
}
