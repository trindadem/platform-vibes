import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { administrativo } from "@/core/contracts";

export const meta: PageMeta = { title: "Fornecedores de compras" };

export default function FornecedoresDeCompras() {
  const fornecedores = useResource(administrativo.fornecedores);
  const session = useSession();
  return (
    <Page title="Fornecedores de compras" description="Quem recebe os pedidos de cotação e de compra, por categoria (sem categoria na requisição, todos recebem).">
      <ResourceList resource={fornecedores} noun="fornecedor" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
