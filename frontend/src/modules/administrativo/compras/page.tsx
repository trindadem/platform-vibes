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
import { type AdministrativoNovaCotacao, type AdministrativoRequisicao, administrativo } from "@/core/contracts";

export const meta: PageMeta = { title: "Compras" };

const STATUS = { aberta: "Aberta", cotando: "Cotando", pedido: "Pedido emitido", cancelada: "Cancelada" };
const TONS = { aberta: "neutral", cotando: "accent", pedido: "success", cancelada: "neutral" } as const;

export default function Compras() {
  const lista = useListQuery(administrativo.requisicoes, { live: "administrativo.requisicoes" });
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const [nova, setNova] = useState(false);
  const [cotando, setCotando] = useState<AdministrativoRequisicao | null>(null);
  const requisitar = useAction(administrativo.requisitar, { onSuccess: lista.reload });
  const cotar = useAction((body: Omit<AdministrativoNovaCotacao, "requisicao">) => administrativo.registrarCotacao({ ...body, requisicao: cotando?.id ?? "" }), {
    onSuccess: lista.reload,
  });
  return (
    <Page
      title="Compras"
      description="Cada requisição inicia o processo de compras: as cotações saem por e-mail aos fornecedores da categoria, a melhor vai para a sua aprovação e o pedido sai para o fornecedor."
      actions={pode && <Button onClick={() => setNova(true)}>Nova requisição</Button>}
    >
      <ListView
        list={lista}
        rowKey={(r) => r.id}
        noun="requisições"
        search="item ou categoria"
        empty="Nenhuma requisição ainda."
        filters={[{ name: "status", label: "Status", options: Object.entries(STATUS).map(([value, label]) => ({ value, label })) }]}
        columns={[
          { key: "item", header: "Item", sort: "item", render: (r) => `${r.quantidade} × ${r.item}` },
          { key: "categoria", header: "Categoria", render: (r) => r.categoria ?? "—" },
          { key: "cotacoes", header: "Cotações", render: (r) => String(r.cotacoes.length) },
          { key: "melhor_fornecedor", header: "Melhor cotação", render: (r) => r.melhor_fornecedor ?? "—" },
          { key: "melhor_valor", header: "Valor", render: (r) => (r.melhor_valor ? <Money value={r.melhor_valor} /> : "—") },
          { key: "status", header: "Status", render: (r) => <StatusBadge value={r.status} labels={STATUS} tones={TONS} /> },
          { key: "pedido_numero", header: "Pedido", render: (r) => r.pedido_numero ?? "—" },
          { key: "created_at", header: "Pedida", sort: "created_at", render: (r) => (r.created_at ? <DateTime value={r.created_at} /> : "—") },
          {
            key: "acao",
            header: "",
            render: (r) =>
              pode && (r.status === "aberta" || r.status === "cotando") ? (
                <Button size="sm" variant="secondary" onClick={() => setCotando(r)}>
                  Registrar cotação
                </Button>
              ) : null,
          },
        ]}
      />
      <SidePanel open={nova} onClose={() => setNova(false)} title="Nova requisição" description="O processo de compras e cotação começa na hora.">
        {nova && (
          <ActionForm
            action={requisitar}
            submitLabel="Requisitar"
            onDone={() => setNova(false)}
            fields={[
              { name: "item", label: "O que comprar", required: true },
              { name: "quantidade", label: "Quantidade", kind: "number", required: true },
              { name: "categoria", label: "Categoria", hint: "Escolhe os fornecedores que recebem o pedido de cotação." },
              { name: "observacao", label: "Observação", kind: "textarea" },
            ]}
          />
        )}
      </SidePanel>
      <SidePanel open={cotando !== null} onClose={() => setCotando(null)} title="Registrar cotação" description={cotando ? `${cotando.quantidade} × ${cotando.item}` : undefined}>
        {cotando && (
          <ActionForm
            action={cotar}
            submitLabel="Registrar"
            onDone={() => setCotando(null)}
            fields={[
              { name: "fornecedor", label: "Fornecedor", required: true },
              { name: "valor", label: "Valor total (R$)", kind: "number", required: true },
              { name: "prazo_dias", label: "Prazo de entrega (dias)", kind: "number" },
            ]}
          />
        )}
      </SidePanel>
    </Page>
  );
}
