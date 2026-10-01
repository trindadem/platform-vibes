import { Button } from "./Button";

export interface SessionStatusProps {
  /** Usuário da sessão; null quando não há sessão. */
  user: string | null;
  /** Encerra a sessão. */
  onSignOut: () => void;
}

/** Estado da sessão no topo: usuário e botão de sair, ou aviso de que não há sessão. */
export function SessionStatus({ user, onSignOut }: SessionStatusProps) {
  if (!user) return <span className="text-sm text-muted">Sem sessão</span>;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="font-medium">{user}</span>
      <Button variant="ghost" size="sm" onClick={onSignOut}>
        Sair
      </Button>
    </div>
  );
}
