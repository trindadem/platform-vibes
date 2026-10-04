import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { administrativo } from "@/core/contracts";

export const meta: PageMeta = { title: "Vencimentos" };

export default function Vencimentos() {
  const vencimentos = useResource(administrativo.vencimentos);
  const session = useSession();
  return (
    <Page
      title="Vencimentos"
      description="Alvarás, licenças, AVCB, seguros e contratos de serviço. Todo dia o processo de vencimentos avisa o que vence em breve; renovar é mudar a data de vencimento."
    >
      <ResourceList resource={vencimentos} noun="vencimento" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
