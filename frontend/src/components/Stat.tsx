import type { ReactNode } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const TONE = { default: "", success: "text-success", danger: "text-destructive" };

export interface StatProps {
  /** O que o número mede. */
  label: string;
  /** O valor em destaque. */
  value: ReactNode;
  /** Contexto curto abaixo do valor. */
  hint?: string;
  /** Cor do valor. Padrão: default. */
  tone?: "default" | "success" | "danger";
}

/**
 * Indicador em destaque: rótulo, valor grande e contexto. Use dentro de Grid.
 *
 * @category Dados
 * @example
 * <Stat label="Total" value={<Money value={1439.9} />} hint="nesta semana" tone="success" />
 */
export function Stat({ label, value, hint, tone = "default" }: StatProps) {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`font-heading text-2xl font-semibold tabular-nums @[250px]/card:text-3xl ${TONE[tone]}`}>{value}</CardTitle>
      </CardHeader>
      {hint && <CardContent className="text-sm text-muted-foreground">{hint}</CardContent>}
    </Card>
  );
}
