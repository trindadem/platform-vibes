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
  /** Encerra a sessão. */
  onSignOut: () => void;
}

/** Sessão no pé do menu: avatar com iniciais e menu para sair, ou aviso de que não há sessão. */
export function SessionStatus({ user, onSignOut }: SessionStatusProps) {
  if (!user) {
    return <p className="px-2 py-1.5 text-sm text-muted-foreground">Sem sessão</p>;
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-12 w-full justify-start gap-2 px-2">
          <Avatar className="size-8 rounded-lg">
            <AvatarFallback className="rounded-lg">{user.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <span className="flex-1 truncate text-left text-sm font-medium">{user}</span>
          <ChevronsUpDownIcon className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-(--radix-dropdown-menu-trigger-width) min-w-48">
        <DropdownMenuLabel className="truncate">{user}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>
          <LogOutIcon />
          Sair
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
