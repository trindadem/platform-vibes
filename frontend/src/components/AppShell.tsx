import { type ReactNode, useEffect } from "react";
import { NavLink, useLocation } from "react-router";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";

/** Um item do menu. */
export interface NavItem {
  /** Rota do item (ex.: "/faturas"). */
  to: string;
  /** Texto do item. */
  label: string;
  /** Grupo no menu (ex.: a categoria do módulo, "Comercial"); sem grupo, o item fica no topo. */
  group?: string;
  /** Subtelas, abaixo do item (ex.: { to: "/faturas/recorrentes", label: "Recorrentes" }). */
  items?: { to: string; label: string }[];
}

export interface AppShellProps {
  /** Nome exibido no topo do menu lateral (ex.: o da organização). */
  brand: string;
  /** Link da imagem do logo; sem ele, as iniciais do nome. */
  logo?: string | null;
  /** Cor da marca (#RRGGBB): vira a cor principal da tela inteira (botões, foco, menu); sem ela, a do tema. */
  color?: string | null;
  /** Itens do menu, já na ordem: os sem grupo no topo; os grupos na ordem em que aparecem. */
  nav: NavItem[];
  /** Conteúdo no pé do menu lateral (ex.: SessionStatus). */
  aside?: ReactNode;
  /** Seletor no topo do menu, abaixo da marca (ex.: TenantSwitcher). */
  switcher?: ReactNode;
  /** Ações à direita da barra superior (ex.: NotificationBell). */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Moldura da aplicação: menu lateral em grupos (gaveta no celular), marca com logo e cor, barra superior com a tela
 * atual e conteúdo centralizado.
 *
 * @category Aplicação
 * @example
 * <AppShell
 *   brand="Acme"
 *   color="#1e40af"
 *   nav={[{ to: "/inicio", label: "Início" }, { to: "/faturas", label: "Faturas", group: "Financeiro", items: [{ to: "/faturas/recorrentes", label: "Recorrentes" }] }]}
 *   aside={<SessionStatus user={usuario} onSignOut={sair} />}
 * >
 *   <Text>Conteúdo</Text>
 * </AppShell>
 */
export function AppShell({ brand, logo, color, nav, aside, switcher, actions, children }: AppShellProps) {
  const { pathname } = useLocation();
  useBrandColor(color);
  const current = nav
    .flatMap((item) => [item, ...(item.items ?? [])])
    .filter((item) => inside(pathname, item.to))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return (
    <SidebarProvider>
      <Sidebar variant="inset">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild>
                <NavLink to="/">
                  {logo ? (
                    <img src={logo} alt="" className="size-8 shrink-0 rounded-lg bg-background object-contain" />
                  ) : (
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-xs font-semibold text-primary-foreground">
                      {brand.slice(0, 2).toUpperCase()}
                    </span>
                  )}
                  <span className="truncate font-semibold">{brand}</span>
                </NavLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          {switcher}
        </SidebarHeader>
        <SidebarContent>
          {groups(nav).map(({ group, items }) => (
            <SidebarGroup key={group ?? ""}>
              {group && <SidebarGroupLabel>{group}</SidebarGroupLabel>}
              <SidebarGroupContent>
                <NavItems items={items} pathname={pathname} current={current?.to} />
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>
        {aside && <SidebarFooter>{aside}</SidebarFooter>}
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4 lg:px-6">
          <SidebarTrigger className="-ml-1" aria-label="Abrir ou fechar o menu" />
          <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-4" />
          <span className="truncate text-sm font-medium">{current?.label ?? brand}</span>
          {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
        </header>
        <div className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}

function NavItems({ items, pathname, current }: { items: NavItem[]; pathname: string; current?: string }) {
  const { setOpenMobile } = useSidebar();
  const close = () => setOpenMobile(false);
  return (
    <SidebarMenu>
      {items.map((item) => (
        <SidebarMenuItem key={item.to}>
          <SidebarMenuButton asChild isActive={item.to === current}>
            <NavLink to={item.to} onClick={close}>
              {item.label}
            </NavLink>
          </SidebarMenuButton>
          {item.items?.length && inside(pathname, item.to) ? (
            <SidebarMenuSub>
              {item.items.map((sub) => (
                <SidebarMenuSubItem key={sub.to}>
                  <SidebarMenuSubButton asChild isActive={sub.to === current}>
                    <NavLink to={sub.to} onClick={close}>
                      {sub.label}
                    </NavLink>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
              ))}
            </SidebarMenuSub>
          ) : null}
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  );
}

/** Os itens sem grupo primeiro; depois cada grupo, na ordem em que aparece. */
function groups(nav: NavItem[]): { group?: string; items: NavItem[] }[] {
  const order = [undefined, ...new Set(nav.map((item) => item.group).filter((group) => group !== undefined))];
  return order.map((group) => ({ group, items: nav.filter((item) => item.group === group) })).filter(({ items }) => items.length);
}

/** A rota atual está em `to` ou abaixo dela (/faturas vale para /faturas/12, não para /faturas-antigas). */
function inside(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}

/** A cor da marca vira a cor principal do documento inteiro (também nos painéis e menus que abrem por cima). */
function useBrandColor(color?: string | null) {
  useEffect(() => {
    if (!color || !/^#[0-9a-fA-F]{6}$/.test(color)) return;
    const text = readableOn(color);
    const tokens: Record<string, string> = {
      "--primary": color,
      "--primary-foreground": text,
      "--ring": color,
      "--sidebar-primary": color,
      "--sidebar-primary-foreground": text,
      "--sidebar-ring": color,
    };
    const style = document.documentElement.style;
    for (const [token, value] of Object.entries(tokens)) style.setProperty(token, value);
    return () => {
      for (const token of Object.keys(tokens)) style.removeProperty(token);
    };
  }, [color]);
}

/** Texto legível sobre a cor: escuro em cor clara, branco em cor escura. */
function readableOn(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
  return (r! * 299 + g! * 587 + b! * 114) / 1000 >= 150 ? "#0a0a0a" : "#ffffff";
}
