// Tela do módulo juridico: os contratos que a empresa assinou. Fonte da verdade: specs/juridico.md.
import type { PageMeta } from "@/App";
import { Page } from "@/components/Page";
import { ResourceList } from "@/components/ResourceList";
import { useResource } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { juridico } from "@/core/contracts";

export const meta: PageMeta = { title: "Jurídico", module: "juridico" };

export default function Contratos() {
  const contratos = useResource(juridico.contratos);
  const session = useSession();
  return (
    <Page
      title="Contratos"
      description="Os contratos da empresa: os que a gestão de contratos arquivou (de uma proposta aceita ou de um contrato recebido) e os cadastrados à mão. A empresa é avisada 60 e 30 dias antes do fim e do reajuste."
    >
      <ResourceList resource={contratos} noun="contrato" readOnly={!hasAnyRole(session, "owner", "admin", "operador")} />
    </Page>
  );
}
