import type { ReactNode } from "react";

export interface AuthShellProps {
  /** Nome exibido acima do conteúdo. */
  brand: string;
  children: ReactNode;
}

/**
 * Moldura das telas abertas (entrar, cadastro, convite): marca no topo e conteúdo numa coluna estreita e centralizada.
 *
 * @category Aplicação
 * @example
 * <AuthShell brand="CV-Frame">
 *   <Text>Conteúdo</Text>
 * </AuthShell>
 */
export function AuthShell({ brand, children }: AuthShellProps) {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-6 bg-background p-4 md:p-8">
      <div className="flex items-center gap-2 font-semibold text-foreground">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-xs text-primary-foreground">
          {brand.slice(0, 2).toUpperCase()}
        </span>
        {brand}
      </div>
      <div className="w-full max-w-md">{children}</div>
    </main>
  );
}
