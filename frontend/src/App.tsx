/**
 * Router montado a partir de src/modules (README §6): cada page.tsx vira uma rota, sem registro manual.
 * - modules/<modulo>/page.tsx          → /<modulo>         (item do menu)
 * - modules/<modulo>/<parte>/page.tsx  → /<modulo>/<parte> (subitem, abaixo do item do módulo)
 * - modules/<modulo>/[id]/page.tsx     → /<modulo>/:id     (fora do menu; o valor vem de useParams)
 *
 * meta.access decide quem vê:
 * - "private" (padrão): exige sessão, aparece no menu, dentro do AppShell. Sem sessão → /entrar?next=<rota>.
 * - "public": aberta com ou sem sessão (ex.: /convite), fora do menu, dentro do AuthShell.
 * - "guest": só sem sessão (ex.: /entrar, /cadastro). Com sessão, segue para ?next= ou para o início.
 *
 * meta.module diz de que módulo (serviço) é a tela (README §5.17): o menu a agrupa pela categoria do módulo e a
 * esconde quando o plano da organização não inclui o módulo ou quando ele não está instalado (fora do catálogo, como
 * numa instalação dedicada, README §9); aberta pelo endereço, mostra o aviso de fora do plano. As subtelas herdam o
 * módulo da tela do módulo. Sem resposta do svc-plans, tudo aparece (o serviço confere de novo).
 *
 * A moldura usa o nome, o logo e a cor da organização ativa (svc-identity).
 */
import { type ComponentType, createContext, type ReactNode, useContext, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router";
import { ActionForm } from "@/components/ActionForm";
import { AppShell, type NavItem } from "@/components/AppShell";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { NotificationBell } from "@/components/NotificationBell";
import { Row } from "@/components/Row";
import { SessionStatus } from "@/components/SessionStatus";
import { SidePanel } from "@/components/SidePanel";
import { Spinner } from "@/components/Spinner";
import { TenantSwitcher } from "@/components/TenantSwitcher";
import { useAction, useLiveQuery, useQuery } from "@/core/api";
import { logout, type Session, switchTenant, useAuthState } from "@/core/auth";
import { appModules, atendimento, identity, type ModuleName, notify, plans } from "@/core/contracts";

const BRAND = "CV-Frame";
const LOGIN = "/entrar";
const NEW_TENANT = "/organizacoes";
const PLAN = "/plano";

/** O que cada page.tsx exporta como `meta`: o texto do menu, a posição, quem pode ver e de que módulo é. */
export interface PageMeta {
  title: string;
  order?: number;
  access?: "private" | "public" | "guest";
  /** Módulo (serviço, sem svc-) da tela: agrupa no menu e some quando o plano não o inclui. Subtela herda o do módulo. */
  module?: ModuleName;
}

interface Screen {
  path: string;
  /** Rota da tela do módulo (/<modulo>), de quem as subtelas herdam o módulo. */
  root: string;
  Page: ComponentType;
  meta: PageMeta;
  module?: ModuleName;
  /** No menu: telas privadas sem parâmetro na rota. */
  listed: boolean;
}

const found = import.meta.glob<{ default: ComponentType; meta: PageMeta }>("./modules/**/page.tsx", { eager: true });

const screens: Screen[] = Object.entries(found)
  .map(([file, page]) => {
    const dirs = file.split("/").slice(2, -1); // ./modules/<modulo>/.../page.tsx
    const path = `/${dirs.map((dir) => (dir.startsWith("[") ? `:${dir.slice(1, -1)}` : dir)).join("/")}`;
    const access = page.meta.access ?? "private";
    return { path, root: `/${dirs[0]}`, Page: page.default, meta: page.meta, listed: access === "private" && !path.includes(":") };
  })
  .map((screen, _, all) => ({ ...screen, module: screen.meta.module ?? all.find((s) => s.path === screen.root)?.meta.module }))
  .sort((a, b) => (a.meta.order ?? 100) - (b.meta.order ?? 100) || a.meta.title.localeCompare(b.meta.title));
const privatePages = screens.filter((s) => (s.meta.access ?? "private") === "private");
const openPages = screens.filter((s) => s.meta.access === "public" || s.meta.access === "guest");
/** Início: a primeira tela do menu que todo plano tem (sem módulo ou de módulo da plataforma). */
const home = privatePages.find((s) => s.listed && always(s.module))?.path ?? "/";

function always(module?: ModuleName): boolean {
  return module === undefined || appModules[module].core;
}

/** Módulo ligado para a organização ativa? null enquanto o svc-plans não respondeu. */
type Included = (module?: ModuleName) => boolean | null;
const ModulesContext = createContext<Included>(() => true);

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
            {privatePages.map(({ path, Page, module }) => (
              <Route
                key={path}
                path={path}
                element={
                  <ModuleGate module={module}>
                    <Page />
                  </ModuleGate>
                }
              />
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

/** Telas privadas: sem sessão, vai para o login lembrando a rota; com sessão, a moldura da organização ativa. */
function PrivateShell() {
  const { session } = useAuthState();
  const location = useLocation();
  if (!session) {
    const next = location.pathname === "/" ? "" : `?next=${encodeURIComponent(location.pathname + location.search)}`;
    return <Navigate to={LOGIN + next} replace />;
  }
  // Trocar de organização monta a moldura de novo: módulos, marca e avisos são de cada organização.
  return <TenantShell key={session.tenant?.id ?? ""} session={session} />;
}

/** Menu com os módulos que o plano inclui, marca da organização (nome, logo e cor), seletor e conta. */
function TenantShell({ session }: { session: Session }) {
  const navigate = useNavigate();
  const tenant = session.tenant;
  const modules = useQuery(plans.modules); // sem organização ativa, as duas respondem erro: tudo aparece, marca padrão
  const organization = useQuery(identity.organization);
  const included: Included = (module) => {
    if (always(module) || modules.error) return true; // sem resposta do svc-plans, tudo aparece
    if (!modules.data) return null;
    return modules.data.items.find((m) => m.name === module)?.enabled ?? false; // fora do catálogo: não instalado
  };
  return (
    <ModulesContext.Provider value={included}>
      <AppShell
        actions={
          tenant && (
            <Row gap="sm">
              <BackToQueue session={session} />
              <HelpButton />
              <UnreadBell />
            </Row>
          )
        }
        brand={organization.data?.name ?? tenant?.name ?? BRAND}
        logo={organization.data?.logo_url}
        color={organization.data?.color}
        nav={menu(included)}
        switcher={
          <TenantSwitcher
            tenants={session.tenants}
            current={tenant?.id ?? null}
            onSwitch={(id) => void switchTenant(id).then(() => navigate(home))}
            onCreate={() => navigate(NEW_TENANT)}
          />
        }
        aside={<SessionStatus user={session.user.name} detail={session.user.email} onSignOut={() => void logout()} />}
      >
        <Outlet />
      </AppShell>
    </ModulesContext.Provider>
  );
}

/** Itens do menu: telas listadas dos módulos incluídos; subtelas abaixo da tela do módulo; grupo = categoria. */
function menu(included: Included): NavItem[] {
  const shown = privatePages.filter((s) => s.listed && included(s.module) === true);
  const roots = new Set(shown.filter((s) => s.path === s.root).map((s) => s.path));
  return shown
    .filter((s) => s.path === s.root || !roots.has(s.root))
    .map((s) => ({
      to: s.path,
      label: s.meta.title,
      group: s.module ? appModules[s.module].category : undefined,
      items: shown.filter((sub) => sub.root === s.path && sub.path !== s.path).map((sub) => ({ to: sub.path, label: sub.meta.title })),
    }));
}

/** Tela de módulo fora do plano, aberta pelo endereço: diz por quê e leva ao plano. */
function ModuleGate({ module, children }: { module?: ModuleName; children: ReactNode }) {
  const included = useContext(ModulesContext)(module);
  const navigate = useNavigate();
  if (included === null) return <Spinner label="Conferindo o plano" />;
  if (included || !module) return children;
  return (
    <EmptyState
      title={`${appModules[module].title} não está no seu plano`}
      description={appModules[module].description}
      action={<Button onClick={() => navigate(PLAN)}>Ver plano</Button>}
    />
  );
}

/** Sino com os avisos não lidos da organização ativa: conta de novo a cada aviso ao vivo (notify.nova). */
function UnreadBell() {
  const unread = useLiveQuery("notify.nova", notify.unread);
  return <NotificationBell count={unread.data?.count ?? 0} />;
}

/** O staff dentro de um cliente (só operador ali) volta à fila da Cogniventure com um clique (specs/staff.md). */
function BackToQueue({ session }: { session: Session }) {
  const navigate = useNavigate();
  const roles = session.tenant?.roles ?? [];
  const casa = session.tenants.find((t) => t.roles.some((r) => r !== "operador"));
  if (!casa || roles.length !== 1 || roles[0] !== "operador") return null;
  return (
    <Button size="sm" variant="secondary" onClick={() => void switchTenant(casa.id).then(() => navigate("/staff"))}>
      Voltar à fila do staff
    </Button>
  );
}

/** Falar com a Cogniventure, de qualquer tela (specs/atendimento.md): o pedido leva a tela de onde a pessoa pediu. */
function HelpButton() {
  const resumo = useQuery(atendimento.resumo);
  const location = useLocation();
  const navigate = useNavigate();
  const [aberto, setAberto] = useState(false);
  const abrir = useAction(atendimento.abrir, { onSuccess: (pedido) => navigate(`/atendimento?pedido=${pedido.id}`) });
  if (!resumo.data?.pode_pedir) return null;
  const enviar = { ...abrir, run: (body: { texto: string }) => abrir.run({ ...body, pagina: location.pathname }) };
  return (
    <Row gap="sm">
      <Button size="sm" variant="secondary" onClick={() => setAberto(true)}>
        Falar com a Cogniventure
      </Button>
      <SidePanel open={aberto} onClose={() => setAberto(false)} title="Falar com a Cogniventure" description="Conte o que precisa: o staff responde em até 4 horas, e a resposta chega no sino.">
        {aberto && (
          <ActionForm
            action={enviar}
            submitLabel="Enviar pedido"
            onDone={() => setAberto(false)}
            fields={[{ name: "texto", label: "Como podemos ajudar?", kind: "textarea", required: true, placeholder: "O boleto da Leite Bom não entrou no contas a pagar..." }]}
          />
        )}
      </SidePanel>
    </Row>
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
