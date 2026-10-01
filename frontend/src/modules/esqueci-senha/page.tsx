import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useAction } from "@/core/api";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Esqueci minha senha", access: "public" };

export default function EsqueciSenha() {
  const pedir = useAction(identity.forgotPassword);
  return (
    <Page title="Esqueci minha senha" description="Informe o e-mail da sua conta e enviaremos um link para criar uma senha nova.">
      <Card>
        <ActionForm
          action={pedir}
          submitLabel="Enviar link"
          successMessage="Se houver uma conta com esse e-mail, o link chega em instantes. Ele vale por 30 minutos."
          fields={[{ name: "email", label: "E-mail", kind: "email", required: true, autoComplete: "email" }]}
        />
      </Card>
      <Text tone="muted">
        Lembrou a senha? <TextLink to="/entrar">Entrar</TextLink>
      </Text>
    </Page>
  );
}
