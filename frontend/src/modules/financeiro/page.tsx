// Tela do módulo financeiro: as contas que os processos agendaram. Fonte da verdade: specs/financeiro.md.
import type { PageMeta } from "@/App";
import { DateTime } from "@/components/DateTime";
import { ListView } from "@/components/ListView";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { StatusBadge } from "@/components/StatusBadge";
import { useListQuery } from "@/core/api";
import { financeiro } from "@/core/contracts";

export const meta: PageMeta = { title: "Financeiro", module: "financeiro" };

export default function ContasAPagar() {
  const lista = useListQuery(financeiro.titulos, { live: "financeiro.titulos" });
  return (
    <Page title="Contas a pagar" description="O que o processo de contas a pagar agendou no banco, do agendamento à conciliação.">
      <ListView
        list={lista}
        rowKey={(t) => t.id}
        noun="contas"
        empty="Nenhuma conta agendada ainda: os boletos que chegam pela caixa de entrada aparecem aqui depois de aprovados."
        filters={[{ name: "status", label: "Status", options: [{ value: "agendado", label: "Agendada" }, { value: "pago", label: "Paga" }] }]}
        columns={[
          { key: "fornecedor", header: "Fornecedor", render: (t) => t.fornecedor ?? "—" },
          { key: "valor", header: "Valor", sort: "valor", render: (t) => <Money value={t.valor} /> },
          { key: "vencimento", header: "Vencimento", render: (t) => <DateTime value={t.vencimento} format="date" /> },
          { key: "data", header: "Agendada para", sort: "data" },
          { key: "pagamento_id", header: "Pagamento" },
          { key: "status", header: "Status", render: (t) => <StatusBadge value={t.status} labels={{ agendado: "Agendada", pago: "Paga" }} /> },
          { key: "conciliado", header: "Extrato", render: (t) => (t.conciliado ? "Conciliada" : "—") },
          { key: "created_at", header: "Desde", sort: "created_at", render: (t) => (t.created_at ? <DateTime value={t.created_at} /> : "—") },
        ]}
      />
    </Page>
  );
}
