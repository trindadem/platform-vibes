/**
 * Router plano (README §6): cada src/modules/<modulo>/page.tsx vira a rota /<modulo>.
 * Nada é registrado à mão: criar a pasta com page.tsx publica a tela.
 *
 * meta.access decide quem vê:
 * - "private" (padrão): exige sessão, aparece no menu, dentro do AppShell. Sem sessão → /entrar?next=<rota>.
 * - "public": aberta com ou sem sessão (ex.: /convite), fora do menu, dentro do AuthShell.
 * - "guest": só sem sessão (ex.: /entrar, /cadastro). Com sessão, segue para ?next= ou para o início.
 */
import type { ComponentType, ReactNode } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router";
import { AppShell } from "@/components/AppShell";
import { AuthShell } from "@/components/AuthShell";
import { EmptyState } from "@/components/EmptyState";
import { SessionStatus } from "@/components/SessionStatus";
import { Spinner } from "@/components/Spinner";
import { TenantSwitcher } from "@/components/TenantSwitcher";
import { logout, switchTenant, useAuthState } from "@/core/auth";

const BRAND = "CV-Frame";
const LOGIN = "/entrar";
const NEW_TENANT = "/organizacoes";

/** O que cada page.tsx exporta como `meta`: o texto do menu, a posição e quem pode ver. */
export interface PageMeta {
  title: string;
  order?: number;
  access?: "private" | "public" | "guest";
}

const found = import.meta.glob<{ default: ComponentType; meta: PageMeta }>("./modules/*/page.tsx", { eager: true });

const pages = Object.entries(found)
  .map(([file, module]) => ({ path: `/${file.split("/")[2]}`, Page: module.default, meta: module.meta }))
  .sort((a, b) => (a.meta.order ?? 100) - (b.meta.order ?? 100) || a.meta.title.localeCompare(b.meta.title));
const privatePages = pages.filter((p) => (p.meta.access ?? "private") === "private");
const openPages = pages.filter((p) => p.meta.access === "public" || p.meta.access === "guest");
const home = privatePages[0]?.path ?? "/";

export function App() {
  const { ready } = useAuthState();
  return (
    <BrowserRouter>
      {ready ? (
        <Routes>
          {openPages.map(({ path, Page, meta }) => (
            <Route
              key={path}
              path={path}
              element={
                <AuthShell brand={BRAND}>
                  {meta.access === "guest" ? (
                    <GuestOnly>
                      <Page />
                    </GuestOnly>
                  ) : (
                    <Page />
                  )}
                </AuthShell>
              }
            />
          ))}
          <Route element={<PrivateShell />}>
            {privatePages.map(({ path, Page }) => (
              <Route key={path} path={path} element={<Page />} />
            ))}
            <Route path="/" element={<Navigate to={home} replace />} />
            <Route
              path="*"
              element={<EmptyState title="Página não encontrada" description="Confira o endereço ou volte pelo menu." />}
            />
          </Route>
        </Routes>
      ) : (
        <AuthShell brand={BRAND}>
          <Spinner label="Abrindo sua sessão" />
        </AuthShell>
      )}
    </BrowserRouter>
  );
}

/** Telas privadas: sem sessão, vai para o login lembrando a rota; com sessão, menu, organização e conta. */
function PrivateShell() {
  const { session } = useAuthState();
  const location = useLocation();
  const navigate = useNavigate();
  if (!session) {
    const next = location.pathname === "/" ? "" : `?next=${encodeURIComponent(location.pathname + location.search)}`;
    return <Navigate to={LOGIN + next} replace />;
  }
  return (
    <AppShell
      brand={BRAND}
      nav={privatePages.map(({ path, meta }) => ({ to: path, label: meta.title }))}
      switcher={
        <TenantSwitcher
          tenants={session.tenants}
          current={session.tenant?.id ?? null}
          onSwitch={(id) => void switchTenant(id).then(() => navigate(home))}
          onCreate={() => navigate(NEW_TENANT)}
        />
      }
      aside={<SessionStatus user={session.user.name} detail={session.user.email} onSignOut={() => void logout()} />}
    >
      <Outlet />
    </AppShell>
  );
}

/** Login e cadastro só fazem sentido sem sessão: quem já entrou segue para ?next= (só rotas internas) ou o início. */
function GuestOnly({ children }: { children: ReactNode }) {
  const { session } = useAuthState();
  const [params] = useSearchParams();
  if (!session) return children;
  const next = params.get("next");
  return <Navigate to={next?.startsWith("/") && !next.startsWith("//") ? next : home} replace />;
}
