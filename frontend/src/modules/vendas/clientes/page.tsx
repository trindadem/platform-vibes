import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { vendas } from "@/core/contracts";

export const meta: PageMeta = { title: "Clientes" };

export default function Clientes() {
  const clientes = useResource(vendas.clientes);
  const session = useSession();
  return (
    <Page title="Clientes" description="A carteira: a última compra de cada um. Quem passa dos dias sem comprar entra na campanha de reativação.">
      <ResourceList resource={clientes} noun="cliente" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
