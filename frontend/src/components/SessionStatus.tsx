import { ChevronsUpDownIcon, LogOutIcon } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface SessionStatusProps {
  /** Usuário da sessão; null quando não há sessão. */
  user: string | null;
  /** Linha abaixo do nome (ex.: o e-mail). */
  detail?: string;
  /** Encerra a sessão. */
  onSignOut: () => void;
}

/**
 * Sessão no pé do menu: avatar com iniciais e menu para sair, ou aviso de que não há sessão.
 *
 * @category Aplicação
 * @example
 * <SessionStatus user={usuario} onSignOut={sair} />
 */
export function SessionStatus({ user, detail, onSignOut }: SessionStatusProps) {
  if (!user) {
    return <p className="px-2 py-1.5 text-sm text-muted-foreground">Sem sessão</p>;
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-12 w-full justify-start gap-2 px-2" aria-label={`Conta de ${user}`}>
          <Avatar className="size-8 rounded-lg">
            <AvatarFallback className="rounded-lg">{user.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <span className="flex min-w-0 flex-1 flex-col text-left leading-tight">
            <span className="truncate text-sm font-medium">{user}</span>
            {detail && <span className="truncate text-xs text-muted-foreground">{detail}</span>}
          </span>
          <ChevronsUpDownIcon className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-(--radix-dropdown-menu-trigger-width) min-w-48">
        <DropdownMenuLabel className="truncate">{detail ?? user}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>
          <LogOutIcon />
          Sair
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
