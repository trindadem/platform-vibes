import { useNavigate, useSearchParams } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Text } from "@/components/Text";
import { useAction, useQuery } from "@/core/api";
import { acceptInvite, useSession } from "@/core/auth";
import { identity } from "@/core/contracts";

export const meta: PageMeta = { title: "Convite", access: "public" };

const PAPEL = { owner: "dono", admin: "administrador", member: "membro", operador: "operador" };

export default function Convite() {
  const [params] = useSearchParams();
  const codigo = params.get("codigo");
  if (!codigo) {
    return <EmptyState title="Convite incompleto" description="Abra o link do convite exatamente como você recebeu." />;
  }
  return <Detalhe codigo={codigo} />;
}

function Detalhe({ codigo }: { codigo: string }) {
  const session = useSession();
  const navigate = useNavigate();
  const convite = useQuery(identity.inviteInfo, { code: codigo });
  const aceitar = useAction(() => acceptInvite(codigo), { onSuccess: () => navigate("/") });
  const aqui = `/convite?codigo=${encodeURIComponent(codigo)}`;
  return (
    <Page title="Convite" description="Você foi convidado para uma organização.">
      <QueryView query={convite}>
        {(info) => (
          <Card
            title={info.tenant_name}
            description={`Você vai entrar como ${PAPEL[info.role]}.`}
            footer={
              session ? (
                <Button onClick={() => void aceitar.run()} loading={aceitar.running}>
                  Entrar em {info.tenant_name}
                </Button>
              ) : (
                <Row>
                  <Button to={`/cadastro?convite=${encodeURIComponent(codigo)}`}>Criar conta</Button>
                  <Button variant="secondary" to={`/entrar?next=${encodeURIComponent(aqui)}`}>
                    Já tenho conta
                  </Button>
                </Row>
              )
            }
          >
            {session && <Text tone="muted">Você está conectado como {session.user.email}.</Text>}
            {aceitar.error && <Alert tone="danger">{aceitar.error.message}</Alert>}
          </Card>
        )}
      </QueryView>
    </Page>
  );
}
