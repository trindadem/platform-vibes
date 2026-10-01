import type { ReactNode } from "react";

const TONE = {
  info: "border-info/30 bg-info/10 text-info",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
};

export interface AlertProps {
  /** Gravidade. danger é anunciado imediatamente por leitores de tela. Padrão: info. */
  tone?: "info" | "success" | "warning" | "danger";
  /** Resumo em negrito. */
  title?: string;
  children?: ReactNode;
}

/** Mensagem de destaque para resultado, aviso ou erro. */
export function Alert({ tone = "info", title, children }: AlertProps) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`flex flex-col gap-1 rounded-control border px-4 py-3 text-sm ${TONE[tone]}`}>
      {title && <strong className="font-semibold">{title}</strong>}
      {children && <div className="text-ink">{children}</div>}
    </div>
  );
}
