export interface MonthlyBarsItem {
  /** Rótulo do mês (ex.: "out/26"). */
  label: string;
  /** A taxa do mês, de 0 a 1; null: nada no mês (sem barra). */
  value: number | null;
  /** Texto curto sob o rótulo (ex.: "12 concluídas"). */
  detail?: string;
  /** Marca no topo da coluna (ex.: "v3": a versão publicada no mês). */
  marker?: string;
}

export interface MonthlyBarsProps {
  /** O que as barras medem (leitor de tela e título). */
  label: string;
  /** Os meses, do mais antigo ao mais novo. */
  items: MonthlyBarsItem[];
}

/**
 * Barras de uma taxa mês a mês (0 a 100%), com a marca do que mudou em cada mês, como a versão publicada.
 *
 * @category Dados
 * @example
 * <MonthlyBars
 *   label="Autonomia por mês"
 *   items={[
 *     { label: "set/26", value: 0.5, detail: "4 concluídas" },
 *     { label: "out/26", value: 0.8, detail: "10 concluídas", marker: "v2" },
 *     { label: "nov/26", value: null, detail: "nada concluído" },
 *   ]}
 * />
 */
export function MonthlyBars({ label, items }: MonthlyBarsProps) {
  return (
    <figure aria-label={label} className="flex flex-col gap-2">
      <figcaption className="text-sm font-medium text-foreground">{label}</figcaption>
      <div className="flex items-end gap-2 overflow-x-auto pb-1">
        {items.map((item) => {
          const percent = item.value === null ? null : Math.round(Math.max(0, Math.min(1, item.value)) * 100);
          return (
            <div key={item.label} className="flex min-w-14 flex-1 flex-col items-center gap-1">
              <span className="h-5 text-xs font-medium text-primary">{item.marker ?? ""}</span>
              <span className="text-xs tabular-nums text-muted-foreground">{percent === null ? "—" : `${percent}%`}</span>
              <div
                className={`flex h-24 w-full items-end rounded-md bg-muted ${item.marker ? "ring-2 ring-primary/40" : ""}`}
                role="img"
                aria-label={`${item.label}: ${percent === null ? "sem dados" : `${percent}%`}${item.marker ? `, ${item.marker}` : ""}`}
              >
                {percent !== null && <div className="w-full rounded-md bg-primary" style={{ height: `${Math.max(percent, 2)}%` }} />}
              </div>
              <span className="text-xs font-medium text-foreground">{item.label}</span>
              {item.detail && <span className="text-center text-xs text-muted-foreground">{item.detail}</span>}
            </div>
          );
        })}
      </div>
    </figure>
  );
}
