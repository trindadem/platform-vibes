import type { PageMeta } from "@/App";
import { DateTime } from "@/components/DateTime";
import { ListView } from "@/components/ListView";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { StatusBadge } from "@/components/StatusBadge";
import { useListQuery } from "@/core/api";
import { financeiro } from "@/core/contracts";

export const meta: PageMeta = { title: "Contas a receber" };

const STATUS = { aberta: "Aberta", cobrada: "Cobrada", paga: "Recebida" };
const TONS = { aberta: "neutral", cobrada: "accent", paga: "success" } as const;

export default function ContasAReceber() {
  const lista = useListQuery(financeiro.faturas, { live: "financeiro.faturas" });
  return (
    <Page
      title="Contas a receber"
      description="O que o faturamento e cobrança faturou: a nota, o boleto, os lembretes da régua (3 dias antes, 1 e 7 dias depois do vencimento) e o recebimento."
    >
      <ListView
        list={lista}
        rowKey={(f) => f.id}
        noun="faturas"
        empty="Nenhuma fatura ainda: uma proposta aceita (ou um pedido entregue) inicia o faturamento."
        filters={[{ name: "status", label: "Status", options: Object.entries(STATUS).map(([value, label]) => ({ value, label })) }]}
        columns={[
          { key: "cliente", header: "Cliente" },
          { key: "descricao", header: "O quê", render: (f) => f.descricao ?? "—" },
          { key: "valor", header: "Valor", sort: "valor", render: (f) => <Money value={f.valor} /> },
          { key: "vencimento", header: "Vencimento", sort: "vencimento", render: (f) => <DateTime value={f.vencimento} format="date" /> },
          { key: "nota_numero", header: "Nota fiscal", render: (f) => f.nota_numero ?? "—" },
          { key: "regua", header: "Lembretes", render: (f) => (f.regua.length ? f.regua.join(", ") : "—") },
          { key: "status", header: "Status", render: (f) => <StatusBadge value={f.status} labels={STATUS} tones={TONS} /> },
        ]}
      />
    </Page>
  );
}
