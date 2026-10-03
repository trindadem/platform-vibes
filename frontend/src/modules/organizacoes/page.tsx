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
import { refresh, useAction, useQuery, useUpload } from "@/core/api";
import { createTenant, switchTenant, useSession } from "@/core/auth";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Organizações", order: 4, module: "identity" };

const PAPEL = { owner: "Dono", admin: "Administrador", member: "Membro", operador: "Operador" };

export default function Organizacoes() {
  const session = useSession();
  const criar = useAction(createTenant);
  const trocar = useAction(switchTenant);
  const org = useQuery(identity.organization);
  const marca = () => refresh(identity.organization); // esta tela e a moldura (nome, logo e cor) atualizam juntas
  const enviar = useUpload(identity.logoUpload, identity.setLogo, { onSuccess: marca });
  const remover = useAction(() => identity.removeLogo({}), { onSuccess: marca });
  const colorir = useAction((v: { color: string }) => identity.setColor({ color: v.color }), { onSuccess: marca });
  const descolorir = useAction(() => identity.setColor({ color: null }), { onSuccess: marca });
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
      <Card title="Cor da marca" description="A cor principal da tela para todos da organização: botões, foco e menu.">
        {org.data && (
          <ActionForm
            key={org.data.color ?? "padrao"}
            action={colorir}
            submitLabel="Usar esta cor"
            initial={{ color: org.data.color ?? "#2563eb" }}
            fields={[{ name: "color", label: "Cor principal", kind: "color", required: true }]}
          />
        )}
        {org.data?.color && (
          <Button variant="secondary" onClick={() => void descolorir.run()} loading={descolorir.running}>
            Voltar à cor da plataforma
          </Button>
        )}
        {descolorir.error && <Alert tone="danger">{descolorir.error.message}</Alert>}
      </Card>
    </Page>
  );
}
