import type { ReactNode } from "react";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";

export interface EmptyStateProps {
  /** O que está vazio ou ausente. */
  title: string;
  /** Como sair desse estado. */
  description?: string;
  /** Ação principal (ex.: Button). */
  action?: ReactNode;
}

/**
 * Espaço reservado para lista vazia, página inexistente ou recurso indisponível.
 *
 * @category Feedback
 * @example
 * <EmptyState
 *   title="Nenhuma fatura"
 *   description="Emita a primeira pelo botão Nova fatura."
 *   action={<Button onClick={salvar}>Nova fatura</Button>}
 * />
 */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <Empty className="border border-dashed">
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
      {action && <EmptyContent>{action}</EmptyContent>}
    </Empty>
  );
}
