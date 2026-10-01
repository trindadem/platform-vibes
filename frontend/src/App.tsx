/**
 * Router plano (README §6): cada src/modules/<modulo>/page.tsx vira a rota /<modulo> e um item do menu.
 * Nada é registrado à mão: criar a pasta com page.tsx publica a tela.
 */
import type { ComponentType } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/EmptyState";
import { SessionStatus } from "@/components/SessionStatus";
import { signOut, useSession } from "@/core/auth";

/** O que cada page.tsx exporta como `meta`: o texto do menu e a posição. */
export interface PageMeta {
  title: string;
  order?: number;
}

const found = import.meta.glob<{ default: ComponentType; meta: PageMeta }>("./modules/*/page.tsx", { eager: true });

const pages = Object.entries(found)
  .map(([file, module]) => ({ path: `/${file.split("/")[2]}`, Page: module.default, meta: module.meta }))
  .sort((a, b) => (a.meta.order ?? 100) - (b.meta.order ?? 100) || a.meta.title.localeCompare(b.meta.title));

export function App() {
  const session = useSession();
  const home = pages[0]?.path;
  return (
    <BrowserRouter>
      <AppShell
        brand="CV-Frame"
        nav={pages.map(({ path, meta }) => ({ to: path, label: meta.title }))}
        aside={<SessionStatus user={session?.sub ?? null} onSignOut={signOut} />}
      >
        <Routes>
          {pages.map(({ path, Page }) => (
            <Route key={path} path={path} element={<Page />} />
          ))}
          {home && <Route path="/" element={<Navigate to={home} replace />} />}
          <Route
            path="*"
            element={<EmptyState title="Página não encontrada" description="Confira o endereço ou volte pelo menu." />}
          />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
