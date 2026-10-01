import type { ReactNode } from "react";

export interface FormProps {
  /** Chamado no envio (Enter ou Button type="submit"); o recarregamento da página já é evitado. */
  onSubmit: () => void | Promise<void>;
  /** Marca o formulário como ocupado para tecnologias assistivas. */
  busy?: boolean;
  children: ReactNode;
}

/** Formulário com campos empilhados e envio sem recarregar a página. */
export function Form({ onSubmit, busy = false, children }: FormProps) {
  return (
    <form
      aria-busy={busy}
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit();
      }}
    >
      {children}
    </form>
  );
}
