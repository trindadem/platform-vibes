import { type ReactNode, useEffect, useState } from "react";
import { Button } from "./Button";

export interface ConfirmButtonProps {
  /** Texto do botão antes de confirmar (ex.: "Remover"). */
  children: ReactNode;
  /** Executa a ação depois da confirmação. */
  onConfirm: () => void;
  /** Texto do botão de confirmação. Padrão: "Confirmar". */
  confirmLabel?: string;
  /** Ação em andamento. */
  loading?: boolean;
  /** Altura. Padrão: sm. */
  size?: "sm" | "md";
}

/**
 * Botão para ação destrutiva que pede um segundo clique de confirmação (volta sozinho em 4 s).
 *
 * @category Formulários
 * @example
 * <ConfirmButton onConfirm={salvar} confirmLabel="Remover agora">Remover</ConfirmButton>
 */
export function ConfirmButton({ children, onConfirm, confirmLabel = "Confirmar", loading = false, size = "sm" }: ConfirmButtonProps) {
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    if (!asking) return;
    const timer = setTimeout(() => setAsking(false), 4000);
    return () => clearTimeout(timer);
  }, [asking]);

  if (!asking) {
    return (
      <Button variant="ghost" size={size} loading={loading} onClick={() => setAsking(true)}>
        {children}
      </Button>
    );
  }
  return (
    <span className="inline-flex gap-1">
      <Button
        variant="danger"
        size={size}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button variant="ghost" size={size} onClick={() => setAsking(false)}>
        Cancelar
      </Button>
    </span>
  );
}
