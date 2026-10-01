import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { ConfirmButton } from "@/components/ConfirmButton";
import { CopyField } from "@/components/CopyField";
import { DataTable } from "@/components/DataTable";
import { DateTime } from "@/components/DateTime";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { useAction, useLiveQuery } from "@/core/api";
import { hasAnyRole, hasRoles, inviteLink, useSession } from "@/core/auth";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Membros", order: 3, module: "identity" };

const PAPEL = { owner: "Dono", admin: "Administrador", member: "Membro" };

export default function Membros() {
  const session = useSession();
  const membros = useLiveQuery("identity.membros", identity.members); // atualiza quando alguém entra ou sai
  const convidar = useAction(identity.createInvite);
  const remover = useAction(identity.removeMember, { onSuccess: membros.reload });
  const gerencia = hasAnyRole(session, "owner", "admin");
  // Espelha a regra do backend (só para exibir): ninguém se remove por aqui e só dono remove dono.
  const podeRemover = (m: { id: string; roles: string[] }) =>
    gerencia && m.id !== session?.user.id && (!m.roles.includes("owner") || hasRoles(session, "owner"));

  return (
    <Page title="Membros" description={`Quem participa de ${session?.tenant?.name ?? "sua organização"}.`}>
      {gerencia && (
        <Card title="Convidar" description="Gere um link para uma pessoa (vale por 7 dias). Com o e-mail, o convite já vai para a caixa dela.">
          <ActionForm
            action={convidar}
            submitLabel="Gerar link"
            initial={{ role: "member" }}
            fields={[
              { name: "email", label: "E-mail da pessoa", kind: "email", hint: "Opcional: sem ele, copie o link e envie você mesmo.", autoComplete: "off" },
              {
                name: "role",
                label: "Papel",
                kind: "select",
                required: true,
                options: [
                  { value: "member", label: "Membro" },
                  { value: "admin", label: "Administrador" },
                ],
              },
            ]}
          />
          {convidar.result?.email && <Alert tone="success">Convite enviado para {convidar.result.email}.</Alert>}
          {convidar.result && <CopyField label="Link do convite" value={inviteLink(convidar.result.code)} hint="Ele só aparece agora: copie antes de sair." />}
        </Card>
      )}
      {remover.error && <Alert tone="danger">{remover.error.message}</Alert>}
      <QueryView query={membros}>
        {(lista) => (
          <DataTable
            rows={lista.items}
            rowKey={(m) => m.id}
            caption="Membros da organização"
            columns={[
              { key: "name", header: "Nome" },
              { key: "email", header: "E-mail" },
              {
                key: "roles",
                header: "Papel",
                render: (m) => (
                  <Row gap="sm">
                    {m.roles.map((papel) => (
                      <Badge key={papel} tone={papel === "owner" ? "accent" : "neutral"}>
                        {PAPEL[papel]}
                      </Badge>
                    ))}
                  </Row>
                ),
              },
              { key: "joined_at", header: "Desde", render: (m) => <DateTime value={m.joined_at} format="date" /> },
              {
                key: "acoes",
                header: "",
                render: (m) =>
                  podeRemover(m) ? (
                    <ConfirmButton onConfirm={() => void remover.run({ user: m.id })} loading={remover.running}>
                      Remover
                    </ConfirmButton>
                  ) : null,
              },
            ]}
          />
        )}
      </QueryView>
    </Page>
  );
}
