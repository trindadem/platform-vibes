import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Alert } from "@/components/Alert";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DataTable } from "@/components/DataTable";
import { FileField } from "@/components/FileField";
import { Page } from "@/components/Page";
import { Picture } from "@/components/Picture";
import { useAction, useQuery, useUpload } from "@/core/api";
import { createTenant, switchTenant, useSession } from "@/core/auth";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Organizações", order: 4 };

const PAPEL = { owner: "Dono", admin: "Administrador", member: "Membro" };

export default function Organizacoes() {
  const session = useSession();
  const criar = useAction(createTenant);
  const trocar = useAction(switchTenant);
  const org = useQuery(identity.organization);
  const enviar = useUpload(identity.logoUpload, identity.setLogo, { onSuccess: org.reload });
  const remover = useAction(() => identity.removeLogo({}), { onSuccess: org.reload });
  const logoUrl = org.data?.logo_url;

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
      <Card title="Logo da organização">
        {logoUrl && <Picture src={logoUrl} alt="Logo atual" />}
        <FileField label="Enviar logo" upload={enviar} accept="image/png,image/jpeg,image/webp,image/gif" hint="PNG, JPEG, WebP ou GIF, até 2 MB." />
        {logoUrl && (
          <ConfirmButton onConfirm={() => void remover.run()} confirmLabel="Remover agora" loading={remover.running}>
            Remover logo
          </ConfirmButton>
        )}
        {remover.error && <Alert tone="danger">{remover.error.message}</Alert>}
      </Card>
    </Page>
  );
}
