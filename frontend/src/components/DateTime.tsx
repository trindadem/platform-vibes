const ABSOLUTE = {
  date: new Intl.DateTimeFormat("pt-BR", { dateStyle: "short" }),
  datetime: new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }),
  time: new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }),
};
const FULL = new Intl.DateTimeFormat("pt-BR", { dateStyle: "full", timeStyle: "medium" });
const RELATIVE = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 30],
  ["month", 12],
  ["year", Number.POSITIVE_INFINITY],
];

export interface DateTimeProps {
  /** Data ISO (como vem do backend) ou Date; vazia ou inválida vira "—". */
  value: string | Date | null | undefined;
  /** date (01/10/2026), datetime (01/10/2026 14:30), time (14:30) ou relative (há 5 minutos). Padrão: datetime. */
  format?: "date" | "datetime" | "time" | "relative";
}

/**
 * Data e hora em pt-BR; a data completa aparece ao passar o mouse.
 *
 * @category Formatação
 * @example
 * <DateTime value="2026-10-01T14:30:00Z" format="relative" />
 */
export function DateTime({ value, format = "datetime" }: DateTimeProps) {
  const date = value instanceof Date ? value : value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return <span className="text-muted-foreground">—</span>;
  return (
    <time dateTime={date.toISOString()} title={FULL.format(date)} className="tabular-nums">
      {format === "relative" ? relative(date) : ABSOLUTE[format].format(date)}
    </time>
  );
}

function relative(date: Date): string {
  let amount = (date.getTime() - Date.now()) / 1000;
  for (const [unit, size] of STEPS) {
    if (Math.abs(amount) < size) return RELATIVE.format(Math.round(amount), unit);
    amount /= size;
  }
  return RELATIVE.format(Math.round(amount), "year");
}
