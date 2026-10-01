import type { ReactNode } from "react";

export interface EmptyStateProps {
  /** O que está vazio ou ausente. */
  title: string;
  /** Como sair desse estado. */
  description?: string;
  /** Ação principal (ex.: Button). */
  action?: ReactNode;
}

/** Espaço reservado para lista vazia, página inexistente ou recurso indisponível. */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-line px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted">{description}</p>}
      {action}
    </div>
  );
}
