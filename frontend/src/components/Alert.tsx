import { CircleAlertIcon, CircleCheckIcon, InfoIcon, TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import { AlertDescription, AlertTitle, Alert as UiAlert } from "@/components/ui/alert";

const ICON = { info: InfoIcon, success: CircleCheckIcon, warning: TriangleAlertIcon, danger: CircleAlertIcon };
const ICON_TONE = { info: "text-info", success: "text-success", warning: "text-warning", danger: "" };

export interface AlertProps {
  /** Gravidade. danger é anunciado imediatamente por leitores de tela. Padrão: info. */
  tone?: "info" | "success" | "warning" | "danger";
  /** Resumo em negrito. */
  title?: string;
  children?: ReactNode;
}

/** Mensagem de destaque para resultado, aviso ou erro, com ícone conforme a gravidade. */
export function Alert({ tone = "info", title, children }: AlertProps) {
  const Icon = ICON[tone];
  return (
    <UiAlert variant={tone === "danger" ? "destructive" : "default"} role={tone === "danger" ? "alert" : "status"}>
      <Icon className={ICON_TONE[tone]} />
      {title && <AlertTitle>{title}</AlertTitle>}
      {children && <AlertDescription>{children}</AlertDescription>}
    </UiAlert>
  );
}
