import type { ReactNode } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";

export interface SidePanelProps {
  /** Aberto ou fechado (estado da página). */
  open: boolean;
  /** Chamado ao fechar (X, Esc ou clique fora). */
  onClose: () => void;
  /** Título do painel. */
  title: string;
  /** Linha de ajuda abaixo do título. */
  description?: string;
  children: ReactNode;
}

/**
 * Painel que desliza da direita sobre a tela, para editar ou criar sem sair dela (ocupa a tela no celular).
 *
 * @category Layout
 * @example
 * <SidePanel open={true} onClose={sair} title="Editar fatura" description="As mudanças valem na hora.">
 *   <Text>Formulário da fatura.</Text>
 * </SidePanel>
 */
export function SidePanel({ open, onClose, title, description, children }: SidePanelProps) {
  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="w-full sm:max-w-md" {...(description ? {} : { "aria-describedby": undefined })}>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description && <SheetDescription>{description}</SheetDescription>}
        </SheetHeader>
        <div className="flex flex-col gap-4 overflow-y-auto px-4 pb-4">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
