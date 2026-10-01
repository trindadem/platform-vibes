import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";

export interface AppShellProps {
  /** Nome exibido no topo do menu lateral. */
  brand: string;
  /** Itens do menu: { to: "/rota", label: "Texto" }. */
  nav: { to: string; label: string }[];
  /** Conteúdo no pé do menu lateral (ex.: SessionStatus). */
  aside?: ReactNode;
  /** Seletor no topo do menu, abaixo da marca (ex.: TenantSwitcher). */
  switcher?: ReactNode;
  /** Ações à direita da barra superior (ex.: NotificationBell). */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Moldura da aplicação: menu lateral (gaveta no celular), barra superior com a tela atual e conteúdo centralizado.
 *
 * @category Aplicação
 * @example
 * <AppShell brand="CV-Frame" nav={[{ to: "/faturas", label: "Faturas" }]} aside={<SessionStatus user={usuario} onSignOut={sair} />}>
 *   <Text>Conteúdo</Text>
 * </AppShell>
 */
export function AppShell({ brand, nav, aside, switcher, actions, children }: AppShellProps) {
  const { pathname } = useLocation();
  const current = nav.find((item) => pathname.startsWith(item.to));
  return (
    <SidebarProvider>
      <Sidebar variant="inset">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild>
                <NavLink to="/">
                  <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-xs font-semibold text-primary-foreground">
                    {brand.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="truncate font-semibold">{brand}</span>
                </NavLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          {switcher}
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <NavItems nav={nav} pathname={pathname} />
            </SidebarGroupContent>
          </SidebarGroup>
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

function NavItems({ nav, pathname }: { nav: AppShellProps["nav"]; pathname: string }) {
  const { setOpenMobile } = useSidebar();
  return (
    <SidebarMenu>
      {nav.map((item) => (
        <SidebarMenuItem key={item.to}>
          <SidebarMenuButton asChild isActive={pathname.startsWith(item.to)}>
            <NavLink to={item.to} onClick={() => setOpenMobile(false)}>
              {item.label}
            </NavLink>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  );
}
