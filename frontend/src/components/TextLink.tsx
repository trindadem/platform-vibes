import type { ReactNode } from "react";
import { Link } from "react-router";

export interface TextLinkProps {
  /** Rota de destino dentro da aplicação (ex.: "/cadastro"). */
  to: string;
  children: ReactNode;
}

/**
 * Link no meio do texto para outra tela da aplicação.
 *
 * @category Texto
 * @example
 * <Text>Não tem conta? <TextLink to="/cadastro">Criar conta</TextLink></Text>
 */
export function TextLink({ to, children }: TextLinkProps) {
  return (
    <Link to={to} className="font-medium text-primary underline-offset-4 hover:underline">
      {children}
    </Link>
  );
}
