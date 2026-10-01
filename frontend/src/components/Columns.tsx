import type { ReactNode } from "react";

const WIDTH = { sm: "lg:grid-cols-[minmax(0,1fr)_18rem]", md: "lg:grid-cols-[minmax(0,1fr)_22rem]", lg: "lg:grid-cols-[minmax(0,1fr)_28rem]" };

export interface ColumnsProps {
  /** Conteúdo principal, à esquerda (ocupa o espaço que sobra). */
  children: ReactNode;
  /** Coluna lateral, à direita em telas largas; abaixo do principal no celular. */
  aside: ReactNode;
  /** Largura da coluna lateral. Padrão: md. */
  asideWidth?: "sm" | "md" | "lg";
}

/**
 * Duas colunas: o principal e uma lateral fixa (ex.: conversa e o perfil sendo preenchido); no celular, uma abaixo da outra.
 *
 * @category Layout
 * @example
 * <Columns aside={<Card title="Perfil"><Text>Segmento: padaria</Text></Card>}>
 *   <Text>Conteúdo principal.</Text>
 * </Columns>
 */
export function Columns({ children, aside, asideWidth = "md" }: ColumnsProps) {
  return (
    <div className={`grid grid-cols-1 items-start gap-6 ${WIDTH[asideWidth]}`}>
      <div className="min-w-0">{children}</div>
      <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-20">{aside}</aside>
    </div>
  );
}
