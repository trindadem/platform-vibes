import type { ReactNode } from "react";
import { Badge } from "./Badge";
import { Card } from "./Card";
import { KeyValue } from "./KeyValue";
import { type MonthlyBarsItem, MonthlyBars } from "./MonthlyBars";

export interface ResultsCardProps {
  /** O que se acompanha (ex.: o processo). */
  title: string;
  /** Uma linha abaixo do título (ex.: "Versão 3 publicada"). */
  description?: string;
  /** Selos ao lado (ex.: "Pausado"). */
  badges?: string[];
  /** A taxa mês a mês (ex.: autonomia), com as marcas. */
  months: MonthlyBarsItem[];
  /** Rótulo do gráfico. */
  monthsLabel: string;
  /** Números do mês (ex.: concluídas, canceladas). */
  counts: { label: string; value: ReactNode }[];
  /** Como as execuções do mês terminaram (fim → quantas). */
  ends: { label: string; value: number }[];
  /** Os indicadores de negócio do mês, já formatados. */
  indicators: { label: string; value: ReactNode }[];
}

/**
 * Os resultados de um processo num mês: a taxa mês a mês com as marcas, os números do mês, como terminaram e os indicadores.
 * Os números e os indicadores ficam lado a lado quando o cartão é largo (pela largura dele, não da tela: cabe num painel).
 *
 * @category Dados
 * @example
 * <ResultsCard
 *   title="Contas a pagar"
 *   description="Versão 2 publicada"
 *   badges={["Pausado"]}
 *   monthsLabel="Autonomia por mês"
 *   months={[{ label: "set/26", value: 0.5 }, { label: "out/26", value: 0.8, marker: "v2" }]}
 *   counts={[{ label: "Concluídas", value: 10 }, { label: "Em andamento", value: 2 }]}
 *   ends={[{ label: "pago", value: 9 }, { label: "recusado", value: 1 }]}
 *   indicators={[{ label: "Valor pago", value: "R$ 42.000,00" }]}
 * />
 */
export function ResultsCard({ title, description, badges = [], months, monthsLabel, counts, ends, indicators }: ResultsCardProps) {
  return (
    <Card title={title} description={description}>
      <div className="@container flex flex-col gap-5">
        {badges.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {badges.map((badge) => (
              <Badge key={badge} tone="warning">
                {badge}
              </Badge>
            ))}
          </div>
        )}
        <MonthlyBars label={monthsLabel} items={months} />
        <div className="grid gap-5 @md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-foreground">No mês</span>
            <KeyValue items={counts} />
            {ends.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {ends.map((end) => (
                  <Badge key={end.label}>
                    {end.label}: {end.value}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-foreground">Indicadores do mês</span>
            {indicators.length > 0 ? (
              <KeyValue items={indicators} stacked />
            ) : (
              <span className="text-sm text-muted-foreground">Este processo não declara indicadores (é só da empresa).</span>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
