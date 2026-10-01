import type { ReactNode } from "react";
import { CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Card as UiCard } from "@/components/ui/card";

export interface CardProps {
  /** Título do cartão. */
  title?: string;
  /** Uma linha abaixo do título. */
  description?: string;
  /** Rodapé (ex.: ações). */
  footer?: ReactNode;
  children?: ReactNode;
}

/** Superfície que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais. */
export function Card({ title, description, footer, children }: CardProps) {
  return (
    <UiCard>
      {(title || description) && (
        <CardHeader>
          {title && <CardTitle>{title}</CardTitle>}
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
      )}
      {children && <CardContent className="flex flex-col gap-4">{children}</CardContent>}
      {footer && <CardFooter className="flex flex-wrap gap-2">{footer}</CardFooter>}
    </UiCard>
  );
}
