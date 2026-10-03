import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { financeiro } from "@/core/contracts";

export const meta: PageMeta = { title: "Fornecedores" };

export default function Fornecedores() {
  const fornecedores = useResource(financeiro.fornecedores);
  const session = useSession();
  return (
    <Page
      title="Fornecedores"
      description="Quem a empresa paga: a conta do plano de contas e o valor do contrato. Fornecedor que ainda não está aqui é tratado como novo (pede aprovação)."
    >
      <ResourceList resource={fornecedores} noun="fornecedor" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
