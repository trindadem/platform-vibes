import type { ReactNode } from "react";
import { NavLink } from "react-router";

export interface AppShellProps {
  /** Nome exibido no topo. */
  brand: string;
  /** Itens do menu: { to: "/rota", label: "Texto" }. */
  nav: { to: string; label: string }[];
  /** Conteúdo à direita do topo (ex.: SessionStatus). */
  aside?: ReactNode;
  children: ReactNode;
}

/** Moldura da aplicação: topo com marca, menu de navegação e área de conteúdo centralizada. */
export function AppShell({ brand, nav, aside, children }: AppShellProps) {
  return (
    <div className="min-h-dvh bg-surface font-sans text-ink">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="font-semibold tracking-tight">{brand}</span>
          <nav aria-label="Principal" className="flex flex-1 flex-wrap gap-1">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-control px-3 py-1.5 text-sm outline-accent focus-visible:outline-2 ${
                    isActive ? "bg-accent/10 font-medium text-accent" : "text-muted hover:bg-line/60 hover:text-ink"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          {aside}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
