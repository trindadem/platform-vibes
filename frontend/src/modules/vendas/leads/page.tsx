import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Button } from "@/components/Button";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { SidePanel } from "@/components/SidePanel";
import { useAction, useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { vendas } from "@/core/contracts";

export const meta: PageMeta = { title: "Leads" };

const ORIGENS = [
  { value: "site", label: "Site" },
  { value: "instagram", label: "Instagram" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "indicacao", label: "Indicação" },
  { value: "outro", label: "Outro" },
];

export default function Leads() {
  const leads = useResource(vendas.leads);
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const [recebendo, setRecebendo] = useState(false);
  const receber = useAction(vendas.receberLead, { onSuccess: leads.list.reload });
  return (
    <Page
      title="Leads"
      description="Quem procurou a empresa. Um lead recebido aqui inicia a qualificação: o agente lê o pedido, marca a reunião ou leva para a nutrição."
      actions={pode && <Button onClick={() => setRecebendo(true)}>Receber lead</Button>}
    >
      <ResourceList resource={leads} noun="lead" readOnly={!pode} />
      <SidePanel open={recebendo} onClose={() => setRecebendo(false)} title="Receber lead" description="A qualificação começa na hora.">
        {recebendo && (
          <ActionForm
            action={receber}
            submitLabel="Receber"
            onDone={() => setRecebendo(false)}
            fields={[
              { name: "nome", label: "Nome", required: true },
              { name: "email", label: "E-mail", kind: "email" },
              { name: "telefone", label: "Telefone", kind: "tel" },
              { name: "origem", label: "Por onde chegou", kind: "select", options: ORIGENS },
              { name: "interesse", label: "O que ele escreveu", kind: "textarea" },
            ]}
          />
        )}
      </SidePanel>
    </Page>
  );
}
