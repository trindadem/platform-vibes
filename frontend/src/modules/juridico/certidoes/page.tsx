import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { juridico } from "@/core/contracts";

export const meta: PageMeta = { title: "Certidões" };

export default function Certidoes() {
  const certidoes = useResource(juridico.certidoes);
  const session = useSession();
  return (
    <Page title="Certidões" description="As certidões negativas de cada mês, com a validade mais próxima: a empresa é avisada 15 dias antes de vencer.">
      <ResourceList resource={certidoes} noun="certidão" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
