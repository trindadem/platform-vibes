// Tela do módulo administrativo: os colaboradores e as admissões. Fonte da verdade: specs/administrativo.md.
import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Button } from "@/components/Button";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { SidePanel } from "@/components/SidePanel";
import { useAction, useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { administrativo } from "@/core/contracts";

export const meta: PageMeta = { title: "Administrativo", module: "administrativo" };

export default function Colaboradores() {
  const colaboradores = useResource(administrativo.colaboradores);
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const [admitindo, setAdmitindo] = useState(false);
  const admitir = useAction(administrativo.admitir, { onSuccess: colaboradores.list.reload });
  return (
    <Page
      title="Colaboradores"
      description="A equipe da empresa. Uma admissão registrada aqui inicia o processo: documentos, eSocial, contrato, exame e acessos."
      actions={pode && <Button onClick={() => setAdmitindo(true)}>Nova admissão</Button>}
    >
      <ResourceList resource={colaboradores} noun="colaborador" readOnly={!pode} />
      <SidePanel open={admitindo} onClose={() => setAdmitindo(false)} title="Nova admissão" description="A contratação foi aprovada: o processo de admissão começa na hora.">
        {admitindo && (
          <ActionForm
            action={admitir}
            submitLabel="Iniciar a admissão"
            onDone={() => setAdmitindo(false)}
            fields={[
              { name: "nome", label: "Nome", required: true },
              { name: "email", label: "E-mail", kind: "email", required: true, hint: "Para onde vai o pedido de documentos." },
              { name: "cargo", label: "Cargo", required: true },
              { name: "salario", label: "Salário (R$)", kind: "number" },
              { name: "inicio", label: "Primeiro dia", kind: "date" },
            ]}
          />
        )}
      </SidePanel>
    </Page>
  );
}
