import { Badge } from "./Badge";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

// Cor automática para os status mais comuns; tones={{ ... }} sempre tem prioridade.
const DEFAULT_TONES: Record<string, Tone> = Object.fromEntries([
  ...["sucesso", "success", "pago", "paga", "paid", "ativo", "ativa", "active", "concluido", "concluído", "concluida", "concluída", "completed", "aprovado", "aprovada", "approved"].map((s) => [s, "success" as const]),
  ...["pendente", "pending", "aberto", "aberta", "open", "aguardando", "processando", "processing", "rascunho", "draft"].map((s) => [s, "warning" as const]),
  ...["erro", "error", "falha", "failed", "cancelado", "cancelada", "cancelled", "recusado", "recusada", "rejected", "vencido", "vencida", "overdue"].map((s) => [s, "danger" as const]),
]);

export interface StatusBadgeProps {
  /** Valor do status como vem do backend (ex.: "paga", "SUCCESS"). */
  value: string;
  /** Cor por valor: { paga: "success", aberta: "warning" }. Sem mapa, status comuns ganham cor automaticamente. */
  tones?: Record<string, Tone>;
  /** Texto exibido por valor: { paga: "Paga" }. Padrão: o próprio valor. */
  labels?: Record<string, string>;
}

/**
 * Status como etiqueta colorida, com cor automática para valores comuns (pago, pendente, erro...).
 *
 * @category Formatação
 * @example
 * <StatusBadge value="aberta" labels={{ aberta: "Em aberto" }} />
 */
export function StatusBadge({ value, tones, labels }: StatusBadgeProps) {
  const tone = tones?.[value] ?? DEFAULT_TONES[value.toLowerCase()] ?? "neutral";
  return <Badge tone={tone}>{labels?.[value] ?? value}</Badge>;
}
