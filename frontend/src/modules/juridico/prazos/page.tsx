// Prazos processuais: o processo de publicações guarda aqui cada prazo calculado. Fonte da verdade: specs/juridico.md.
import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { juridico } from "@/core/contracts";

export const meta: PageMeta = { title: "Prazos processuais" };

export default function Prazos() {
  const prazos = useResource(juridico.prazos);
  const session = useSession();
  return (
    <Page
      title="Prazos processuais"
      description="Cada intimação encontrada pelo processo de publicações vira um prazo, contado em dias úteis. Marque como cumprido quando o advogado atender."
    >
      <ResourceList resource={prazos} noun="prazo" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
