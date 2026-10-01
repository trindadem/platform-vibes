const FORMATS = new Map<string, Intl.NumberFormat>();

export interface QuantityProps {
  /** Quantidade; null ou undefined vira "—". */
  value: number | null | undefined;
  /** Forma curta para números grandes: 1,2 mil, 3,4 mi. Padrão: false (1.234.567). */
  compact?: boolean;
  /** Unidade depois do número (ex.: "tokens"). */
  unit?: string;
}

/**
 * Quantidade em pt-BR com separador de milhar (1.234.567) ou curta (1,2 mi), alinhada em tabelas.
 *
 * @category Formatação
 * @example
 * <Quantity value={1234567} compact unit="tokens" />
 */
export function Quantity({ value, compact = false, unit }: QuantityProps) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  const key = compact ? "compact" : "full";
  let format = FORMATS.get(key);
  if (!format) {
    format = new Intl.NumberFormat("pt-BR", compact ? { notation: "compact", maximumFractionDigits: 1 } : {});
    FORMATS.set(key, format);
  }
  const text = format.format(value);
  return (
    <span className="tabular-nums" title={compact ? value.toLocaleString("pt-BR") : undefined}>
      {unit ? `${text} ${unit}` : text}
    </span>
  );
}
