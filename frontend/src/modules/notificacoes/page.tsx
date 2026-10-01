import { useNavigate } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DateTime } from "@/components/DateTime";
import { ListView } from "@/components/ListView";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { Text } from "@/components/Text";
import { Toggle } from "@/components/Toggle";
import { refresh, useAction, useListQuery, useQuery } from "@/core/api";
import { notify, type NotifyNotification } from "@/core/contracts";

export const meta: PageMeta = { title: "Notificações", order: 90 };

export default function Notificacoes() {
  const navigate = useNavigate();
  const lista = useListQuery(notify.items, { live: "notify.nova" }); // aviso novo aparece sozinho
  const atualizar = () => {
    lista.reload();
    refresh(notify.unread); // o sino da barra superior conta de novo
  };
  const ler = useAction(notify.read, { onSuccess: atualizar });
  const lerTodos = useAction(() => notify.readAll({}), { onSuccess: atualizar });
  const preferencias = useQuery(notify.preferences);
  const salvar = useAction(notify.setPreferences, { onSuccess: preferencias.reload });

  const abrir = async (aviso: NotifyNotification) => {
    if (!aviso.read) await ler.run({ ids: [aviso.id] });
    if (aviso.link) navigate(aviso.link);
  };

  return (
    <Page title="Notificações" description="Avisos para você nesta organização.">
      {(ler.error ?? lerTodos.error) && <Alert tone="danger">{(ler.error ?? lerTodos.error)?.message}</Alert>}
      <ListView
        list={lista}
        rowKey={(aviso) => aviso.id}
        noun="avisos"
        empty="Nenhum aviso por aqui."
        caption="Seus avisos"
        filters={[{ name: "read", label: "Mostrar", options: [{ value: "false", label: "Não lidos" }, { value: "true", label: "Lidos" }] }]}
        actions={
          <Button variant="secondary" onClick={() => void lerTodos.run()} loading={lerTodos.running}>
            Marcar todos como lidos
          </Button>
        }
        columns={[
          {
            key: "title",
            header: "Aviso",
            render: (aviso) => (
              <Stack gap="sm">
                <Row gap="sm">
                  {!aviso.read && <Badge tone="accent">Novo</Badge>}
                  <Text>{aviso.title}</Text>
                </Row>
                {aviso.body && (
                  <Text tone="muted" size="sm">
                    {aviso.body}
                  </Text>
                )}
              </Stack>
            ),
          },
          { key: "created_at", header: "Quando", sort: "created_at", render: (aviso) => <DateTime value={aviso.created_at} format="relative" /> },
          {
            key: "acoes",
            header: "",
            render: (aviso) =>
              aviso.link ? (
                <Button size="sm" variant="secondary" onClick={() => void abrir(aviso)}>
                  {aviso.action ?? "Abrir"}
                </Button>
              ) : !aviso.read ? (
                <Button size="sm" variant="ghost" onClick={() => void ler.run({ ids: [aviso.id] })}>
                  Marcar como lido
                </Button>
              ) : null,
          },
        ]}
      />
      <Card title="Preferências">
        <QueryView query={preferencias}>
          {(atual) => (
            <Toggle
              label="Receber os avisos também por e-mail"
              checked={atual.email}
              onChange={(email) => void salvar.run({ email })}
              hint="E-mails de segurança (senha e convites) sempre chegam."
              disabled={salvar.running}
            />
          )}
        </QueryView>
      </Card>
    </Page>
  );
}
