import { BellIcon } from "lucide-react";
import { NavLink } from "react-router";
import { Button } from "@/components/ui/button";

export interface NotificationBellProps {
  /** Avisos não lidos; 0 esconde o número. */
  count: number;
  /** Rota da lista de avisos. Padrão: /notificacoes. */
  to?: string;
}

/**
 * Sino da barra superior com a quantidade de avisos não lidos; leva à lista de avisos.
 *
 * @category Aplicação
 * @example
 * <NotificationBell count={3} />
 */
export function NotificationBell({ count, to = "/notificacoes" }: NotificationBellProps) {
  const label = count ? `Notificações: ${count} não ${count === 1 ? "lida" : "lidas"}` : "Notificações";
  return (
    <Button variant="ghost" size="icon" className="relative" asChild>
      <NavLink to={to} aria-label={label} title={label}>
        <BellIcon />
        {count > 0 && (
          <span
            aria-hidden="true"
            className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-none font-semibold text-primary-foreground tabular-nums"
          >
            {count > 99 ? "99+" : count}
          </span>
        )}
      </NavLink>
    </Button>
  );
}
