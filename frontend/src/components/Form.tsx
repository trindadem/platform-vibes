import type { ReactNode } from "react";
import { FieldGroup } from "@/components/ui/field";

export interface FormProps {
  /** Chamado no envio (Enter ou Button type="submit"); o recarregamento da página já é evitado. */
  onSubmit: () => void | Promise<void>;
  /** Marca o formulário como ocupado para tecnologias assistivas. */
  busy?: boolean;
  children: ReactNode;
}

/**
 * Formulário com campos espaçados de forma uniforme e envio sem recarregar a página.
 *
 * @category Formulários
 * @example
 * <Form onSubmit={salvar}>
 *   <TextField label="Nome" value={nome} onChange={setNome} required />
 *   <Button type="submit">Salvar</Button>
 * </Form>
 */
export function Form({ onSubmit, busy = false, children }: FormProps) {
  return (
    <form
      aria-busy={busy}
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit();
      }}
    >
      <FieldGroup>{children}</FieldGroup>
    </form>
  );
}
