import { useSearchParams } from "react-router";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useAction, useQuery } from "@/core/api";
import { signup } from "@/core/auth";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Criar conta", access: "guest" };

const PAPEL = { owner: "dono", admin: "administrador", member: "membro" };

export default function Cadastro() {
  const [params] = useSearchParams();
  const convite = params.get("convite");
  return (
    <Page
      title="Criar conta"
      description={convite ? "Crie sua conta para entrar na organização que te convidou." : "Crie sua conta e a sua organização."}
    >
      <Card>{convite ? <ComConvite codigo={convite} /> : <NovaOrganizacao />}</Card>
      <Text tone="muted">
        Já tem conta? <TextLink to={convite ? `/entrar?next=${encodeURIComponent(`/convite?codigo=${convite}`)}` : "/entrar"}>Entrar</TextLink>
      </Text>
    </Page>
  );
}

function NovaOrganizacao() {
  const criar = useAction(signup);
  return (
    <ActionForm
      action={criar}
      submitLabel="Criar conta"
      fields={[
        { name: "name", label: "Seu nome", required: true, autoComplete: "name" },
        { name: "email", label: "E-mail", kind: "email", required: true, autoComplete: "email" },
        { name: "password", label: "Senha", kind: "password", required: true, autoComplete: "new-password", hint: "Mínimo de 8 caracteres." },
        { name: "organization", label: "Nome da organização", required: true, hint: "Você será o dono. Depois pode convidar outras pessoas." },
      ]}
    />
  );
}

function ComConvite({ codigo }: { codigo: string }) {
  const convite = useQuery(identity.inviteInfo, { code: codigo });
  const criar = useAction((dados: { name: string; email: string; password: string }) => signup({ ...dados, invite: codigo }));
  return (
    <QueryView query={convite}>
      {(info) => (
        <>
          <Alert tone="info" title={`Convite para ${info.tenant_name}`}>
            Você vai entrar como {PAPEL[info.role]}.
          </Alert>
          <ActionForm
            action={criar}
            submitLabel="Criar conta e entrar"
            fields={[
              { name: "name", label: "Seu nome", required: true, autoComplete: "name" },
              { name: "email", label: "E-mail", kind: "email", required: true, autoComplete: "email" },
              { name: "password", label: "Senha", kind: "password", required: true, autoComplete: "new-password", hint: "Mínimo de 8 caracteres." },
            ]}
          />
        </>
      )}
    </QueryView>
  );
}
