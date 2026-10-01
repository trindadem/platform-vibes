import type { ReactNode } from "react";

export interface CardProps {
  /** Título do cartão. */
  title?: string;
  /** Uma linha abaixo do título. */
  description?: string;
  /** Rodapé (ex.: ações). */
  footer?: ReactNode;
  children?: ReactNode;
}

/** Superfície elevada que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais. */
export function Card({ title, description, footer, children }: CardProps) {
  return (
    <section className="flex flex-col gap-4 rounded-card border border-line bg-panel p-5 shadow-sm">
      {(title || description) && (
        <header className="flex flex-col gap-1">
          {title && <h2 className="text-base font-semibold">{title}</h2>}
          {description && <p className="text-sm text-muted">{description}</p>}
        </header>
      )}
      {children}
      {footer && <footer className="flex flex-wrap gap-2 border-t border-line pt-4">{footer}</footer>}
    </section>
  );
}
