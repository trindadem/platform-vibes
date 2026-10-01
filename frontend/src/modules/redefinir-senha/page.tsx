import { useNavigate, useSearchParams } from "react-router";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useAction } from "@/core/api";
import { logout } from "@/core/auth";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Redefinir senha", access: "public" };

export default function RedefinirSenha() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const codigo = params.get("codigo");
  // A troca encerra todas as sessões da conta no servidor: este navegador também sai e entra com a senha nova.
  const trocar = useAction((valores: { password: string }) => identity.resetPassword({ code: codigo ?? "", password: valores.password }), {
    onSuccess: () => void logout().then(() => navigate("/entrar?senha=nova")),
  });
  if (!codigo) {
    return (
      <EmptyState
        title="Link incompleto"
        description="Abra o link exatamente como chegou no e-mail, ou peça outro."
        action={<Button to="/esqueci-senha">Pedir outro link</Button>}
      />
    );
  }
  return (
    <Page title="Criar senha nova" description="Use pelo menos 8 caracteres. As sessões abertas da sua conta serão encerradas.">
      <Card>
        <ActionForm
          action={trocar}
          submitLabel="Salvar senha"
          fields={[{ name: "password", label: "Senha nova", kind: "password", required: true, autoComplete: "new-password" }]}
        />
      </Card>
      <Text tone="muted">
        O link venceu ou já foi usado? <TextLink to="/esqueci-senha">Pedir outro</TextLink>
      </Text>
    </Page>
  );
}
