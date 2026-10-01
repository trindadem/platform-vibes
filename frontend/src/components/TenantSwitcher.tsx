import { CheckIcon, ChevronsUpDownIcon, PlusIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";

export interface TenantSwitcherProps {
  /** Organizações da pessoa: { id, name }. */
  tenants: { id: string; name: string }[];
  /** Id da organização ativa (null se nenhuma). */
  current: string | null;
  /** Troca a organização ativa. */
  onSwitch: (id: string) => void;
  /** Abre a criação de uma organização nova. */
  onCreate?: () => void;
}

/**
 * Seletor da organização ativa no topo do menu lateral, com a opção de criar outra.
 *
 * @category Aplicação
 * @example
 * <TenantSwitcher tenants={[{ id: "acme", name: "Acme" }, { id: "beta", name: "Beta" }]} current="acme" onSwitch={setNome} onCreate={salvar} />
 */
export function TenantSwitcher({ tenants, current, onSwitch, onCreate }: TenantSwitcherProps) {
  const active = tenants.find((tenant) => tenant.id === current);
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" aria-label="Trocar de organização">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border text-xs font-semibold">
                {(active?.name ?? "?").slice(0, 2).toUpperCase()}
              </span>
              <span className="flex min-w-0 flex-1 flex-col text-left leading-tight">
                <span className="truncate text-xs text-muted-foreground">Organização</span>
                <span className="truncate font-medium">{active?.name ?? "Nenhuma"}</span>
              </span>
              <ChevronsUpDownIcon className="text-muted-foreground" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-(--radix-dropdown-menu-trigger-width) min-w-56">
            <DropdownMenuLabel className="text-xs text-muted-foreground">Organizações</DropdownMenuLabel>
            {tenants.map((tenant) => (
              <DropdownMenuItem key={tenant.id} onSelect={() => tenant.id !== current && onSwitch(tenant.id)}>
                <span className="flex-1 truncate">{tenant.name}</span>
                {tenant.id === current && <CheckIcon />}
              </DropdownMenuItem>
            ))}
            {onCreate && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={onCreate}>
                  <PlusIcon />
                  Nova organização
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
