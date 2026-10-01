import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { Page } from "@/components/Page";
import { useAction } from "@/core/api";
import { createTenant, switchTenant, useSession } from "@/core/auth";

export const meta: PageMeta = { title: "Organizações", order: 4 };

const PAPEL = { owner: "Dono", admin: "Administrador", member: "Membro" };

export default function Organizacoes() {
  const session = useSession();
  const criar = useAction(createTenant);
  const trocar = useAction(switchTenant);

  return (
    <Page title="Organizações" description="As organizações de que você participa. Os dados de cada uma ficam separados.">
      <DataTable
        rows={session?.tenants ?? []}
        rowKey={(t) => t.id}
        caption="Suas organizações"
        columns={[
          { key: "name", header: "Nome" },
          { key: "roles", header: "Seu papel", render: (t) => t.roles.map((papel) => PAPEL[papel]).join(", ") },
          {
            key: "ativa",
            header: "",
            render: (t) =>
              t.id === session?.tenant?.id ? (
                <Badge tone="success">Ativa</Badge>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => void trocar.run(t.id)} loading={trocar.running}>
                  Usar esta
                </Button>
              ),
          },
        ]}
      />
      <Card title="Nova organização" description="Você será o dono e ela passa a ser a organização ativa.">
        <ActionForm action={criar} submitLabel="Criar organização" successMessage="Organização criada." fields={[{ name: "name", label: "Nome", required: true }]} />
      </Card>
    </Page>
  );
}
