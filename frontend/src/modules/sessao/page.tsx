import { useState } from "react";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Code } from "@/components/Code";
import { Form } from "@/components/Form";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { Row } from "@/components/Row";
import { TextArea } from "@/components/TextArea";
import { signIn, signOut, useSession } from "@/core/auth";

export const meta: PageMeta = { title: "Sessão", order: 2 };

export default function Sessao() {
  const session = useSession();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (session) {
    return (
      <Page title="Sessão" description="Quem está usando a plataforma neste navegador.">
        <Card
          title="Sessão ativa"
          footer={
            <Button variant="secondary" onClick={signOut}>
              Sair
            </Button>
          }
        >
          <KeyValue
            items={[
              { label: "Usuário", value: session.sub },
              {
                label: "Papéis",
                value: session.roles.length ? (
                  <Row gap="sm">
                    {session.roles.map((role) => (
                      <Badge key={role} tone="accent">
                        {role}
                      </Badge>
                    ))}
                  </Row>
                ) : (
                  "nenhum"
                ),
              },
              { label: "Organização", value: session.tenant ?? "—" },
              { label: "Expira em", value: session.expiresAt.toLocaleString("pt-BR") },
            ]}
          />
        </Card>
        <Alert tone="info">Estes dados são só para exibição: o backend verifica a assinatura do token em toda requisição.</Alert>
      </Page>
    );
  }

  const enter = () => {
    try {
      signIn(token);
      setToken("");
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <Page title="Sessão" description="Entre colando um token (ambiente de desenvolvimento).">
      <Card title="Entrar com token" description="Enquanto não existe um serviço de login, gere um token de teste na raiz do projeto:">
        <Code block>{"uv run python -m core.security token <usuario> --tenant <organizacao> [papel ...]"}</Code>
        <Form onSubmit={enter}>
          <TextArea label="Token" value={token} onChange={setToken} rows={5} monospace required error={error ?? undefined} placeholder="eyJ..." />
          <Row>
            <Button type="submit">Entrar</Button>
          </Row>
        </Form>
      </Card>
    </Page>
  );
}
