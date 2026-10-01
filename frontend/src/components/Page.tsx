import { type ReactNode, useEffect } from "react";

export interface PageProps {
  /** Título da tela: vira o h1 e o título da aba. */
  title: string;
  /** Uma linha explicando para que serve a tela. */
  description?: string;
  /** Ações à direita do título (ex.: Button). */
  actions?: ReactNode;
  children: ReactNode;
}

/** Estrutura de uma tela: título, descrição, ações e conteúdo com o espaçamento padrão. */
export function Page({ title, description, actions, children }: PageProps) {
  useEffect(() => {
    document.title = title;
  }, [title]);

  return (
    <section className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
