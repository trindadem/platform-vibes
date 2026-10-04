// Tela do módulo vendas: as propostas comerciais, do pedido à resposta. Fonte da verdade: specs/vendas.md.
import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Button } from "@/components/Button";
import { DateTime } from "@/components/DateTime";
import { ListView } from "@/components/ListView";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { SidePanel } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { useAction, useListQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { vendas } from "@/core/contracts";

export const meta: PageMeta = { title: "Vendas", module: "vendas" };

const STATUS = { pedida: "Pedida", montada: "Montada", enviada: "Enviada", aceita: "Aceita", recusada: "Recusada" };
const TONS = { pedida: "neutral", montada: "accent", enviada: "accent", aceita: "success", recusada: "danger" } as const;

export default function Propostas() {
  const lista = useListQuery(vendas.propostas, { live: "vendas.propostas" });
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const [pedindo, setPedindo] = useState(false);
  const pedir = useAction(vendas.pedirProposta, { onSuccess: lista.reload });
  return (
    <Page
      title="Propostas"
      description="Cada pedido de proposta inicia o processo de proposta comercial: o agente monta com a tabela, envia e acompanha. A aceita inicia o contrato e o faturamento."
      actions={pode && <Button onClick={() => setPedindo(true)}>Pedir proposta</Button>}
    >
      <ListView
        list={lista}
        rowKey={(p) => p.id}
        noun="propostas"
        search="cliente ou pedido"
        empty="Nenhuma proposta ainda: registre o pedido de um cliente para o processo montar a proposta."
        filters={[{ name: "status", label: "Status", options: Object.entries(STATUS).map(([value, label]) => ({ value, label })) }]}
        columns={[
          { key: "cliente", header: "Cliente" },
          { key: "descricao", header: "Proposta", render: (p) => p.descricao ?? p.pedido },
          { key: "valor", header: "Valor", sort: "valor", render: (p) => (p.valor === null ? "—" : <Money value={p.valor} />) },
          { key: "desconto", header: "Desconto", render: (p) => (p.desconto ? `${p.desconto}%` : "—") },
          { key: "status", header: "Status", render: (p) => <StatusBadge value={p.status} labels={STATUS} tones={TONS} /> },
          { key: "created_at", header: "Pedida", sort: "created_at", render: (p) => (p.created_at ? <DateTime value={p.created_at} /> : "—") },
        ]}
      />
      <SidePanel open={pedindo} onClose={() => setPedindo(false)} title="Pedir proposta" description="O processo de proposta comercial começa na hora.">
        {pedindo && (
          <ActionForm
            action={pedir}
            submitLabel="Pedir proposta"
            onDone={() => setPedindo(false)}
            fields={[
              { name: "cliente", label: "Cliente", required: true },
              { name: "email", label: "E-mail do cliente", kind: "email", hint: "Para onde a proposta vai." },
              { name: "pedido", label: "O que ele pediu", kind: "textarea", required: true, placeholder: "40 kg de pão francês por semana, por 3 meses..." },
            ]}
          />
        )}
      </SidePanel>
    </Page>
  );
}
