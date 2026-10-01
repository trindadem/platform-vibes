import type { ReactNode } from "react";

const NUMBER = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

export interface UsageMeterProps {
  /** O que se mede (ex.: "Pessoas na organização"). */
  label: string;
  /** Quanto já foi usado. */
  used: number;
  /** O máximo permitido; null: sem limite (sem barra); 0: não incluído. */
  limit: number | null;
  /** Como mostrar um valor (padrão: número em pt-BR). Ex.: (v) => <Money value={v} currency="USD" />. */
  format?: (value: number) => ReactNode;
  /** Contexto curto abaixo da barra (ex.: "neste mês"). */
  hint?: string;
}

/**
 * Barra de uso de um limite: quanto foi usado de quanto é permitido, em alerta a partir de 80% e cheia em 100%.
 *
 * @category Dados
 * @example
 * <UsageMeter label="Pessoas na organização" used={4} limit={5} hint="no plano Pro" />
 */
export function UsageMeter({ label, used, limit, format = (value) => NUMBER.format(value), hint }: UsageMeterProps) {
  const percent = limit ? Math.min(100, (used / limit) * 100) : 0;
  const full = limit !== null && used >= limit;
  const bar = full ? "bg-destructive" : percent >= 80 ? "bg-warning" : "bg-primary";
  const status = limit === 0 ? "Não incluído no plano" : full ? "Limite atingido" : percent >= 80 ? "Perto do limite" : null;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-sm tabular-nums text-muted-foreground">
          <span className="font-medium text-foreground">{format(used)}</span>
          {limit === null ? " · sem limite" : <> de {format(limit)}</>}
        </span>
      </div>
      {limit !== null && limit > 0 && (
        <div
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(percent)}
          className="h-2 w-full overflow-hidden rounded-full bg-muted"
        >
          <div className={`h-full rounded-full transition-[width] ${bar}`} style={{ width: `${percent}%` }} />
        </div>
      )}
      {(status || hint) && (
        <span className={`text-xs ${full || limit === 0 ? "text-destructive" : percent >= 80 ? "text-warning" : "text-muted-foreground"}`}>
          {[status, hint].filter(Boolean).join(" · ")}
        </span>
      )}
    </div>
  );
}
