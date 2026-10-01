import { useSearchParams } from "react-router";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useAction } from "@/core/api";
import { login } from "@/core/auth";

export const meta: PageMeta = { title: "Entrar", access: "guest" };

export default function Entrar() {
  const entrar = useAction(login);
  const [params] = useSearchParams();
  return (
    <Page title="Entrar" description="Use o e-mail e a senha da sua conta.">
      {params.get("senha") === "nova" && <Alert tone="success">Senha alterada. Entre com a senha nova.</Alert>}
      <Card>
        <ActionForm
          action={entrar}
          submitLabel="Entrar"
          fields={[
            { name: "email", label: "E-mail", kind: "email", required: true, autoComplete: "email" },
            { name: "password", label: "Senha", kind: "password", required: true, autoComplete: "current-password" },
          ]}
        />
      </Card>
      <Text tone="muted">
        <TextLink to="/esqueci-senha">Esqueci minha senha</TextLink>
      </Text>
      <Text tone="muted">
        Ainda não tem conta? <TextLink to="/cadastro">Criar conta</TextLink>
      </Text>
    </Page>
  );
}
