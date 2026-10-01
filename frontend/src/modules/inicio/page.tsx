import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Card } from "@/components/Card";
import { Code } from "@/components/Code";
import { Grid } from "@/components/Grid";
import { Page } from "@/components/Page";
import { Spinner } from "@/components/Spinner";
import { Stack } from "@/components/Stack";
import { Stat } from "@/components/Stat";
import { Text } from "@/components/Text";
import { useQuery } from "@/core/api";
import { gateway } from "@/core/contracts";
import { useSession } from "@/core/auth";

export const meta: PageMeta = { title: "Início", order: 1 };

export default function Inicio() {
  const health = useQuery(gateway.health);
  const session = useSession();
  const online = health.data !== null;

  return (
    <Page title="Início" description="Estado da plataforma e como criar uma tela nova.">
      <Grid cols={3}>
        <Stat
          label="Gateway"
          value={health.loading ? <Spinner label="Verificando" /> : online ? "Online" : "Fora do ar"}
          tone={health.loading ? "default" : online ? "success" : "danger"}
          hint={health.error?.message}
        />
        <Stat label="Rotas publicadas" value={health.data?.routes ?? "—"} hint="Uma por endpoint em gateway/endpoints/*.yaml" />
        <Stat
          label="Sessão"
          value={session?.sub ?? "Nenhuma"}
          hint={session ? `Expira às ${session.expiresAt.toLocaleTimeString("pt-BR")}` : "Entre pela tela Sessão"}
        />
      </Grid>

      {health.error && (
        <Alert tone="warning" title="Gateway indisponível">
          Suba a plataforma na raiz do projeto: <Code>{"docker compose up --build -d"}</Code>
        </Alert>
      )}

      <Card title="Criar uma tela" description="Toda tela nasce da composição dos componentes do catálogo.">
        <Stack gap="sm">
          <Text>
            1. Crie <Code>{"src/modules/<nome>/page.tsx"}</Code> exportando a tela (default) e <Code>{"meta"}</Code>. A rota{" "}
            <Code>{"/<nome>"}</Code> e o item do menu aparecem sozinhos.
          </Text>
          <Text>
            2. Monte a tela só com componentes de <Code>{"src/components/CATALOG.md"}</Code>. Faltou peça? Crie um componente: a
            página nunca usa tags HTML nem classes.
          </Text>
          <Text>
            3. Dados vêm do cliente tipado gerado do backend (<Code>{"src/core/contracts.ts"}</Code>), por exemplo{" "}
            <Code>{"billing.execute({ ... })"}</Code>: rota e campos errados não compilam.
          </Text>
        </Stack>
      </Card>
    </Page>
  );
}
