import { useState } from "react";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Code } from "@/components/Code";
import { ConfirmButton } from "@/components/ConfirmButton";
import { CopyField } from "@/components/CopyField";
import { DataTable } from "@/components/DataTable";
import { DateTime } from "@/components/DateTime";
import { Form } from "@/components/Form";
import { ListView } from "@/components/ListView";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextField } from "@/components/TextField";
import { Toggle } from "@/components/Toggle";
import { type ApiError, type ListState, type QueryState, refresh, useAction, useListQuery, useQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import {
  type WebhooksDelivery,
  type WebhooksEndpoint,
  type WebhooksEndpointInput,
  type WebhooksEndpointList,
  type WebhooksEventList,
  webhooks,
} from "@/core/contracts";

export const meta: PageMeta = { title: "Webhooks", order: 5 };

const STATUS = { pending: "Tentando", sent: "Entregue", failed: "Falhou", skipped: "Pulada" };
const TOM = { pending: "warning", sent: "success", failed: "danger", skipped: "neutral" } as const;

/** Mensagem do servidor; num 422, o que cada campo recusou. */
const mensagem = (erro: ApiError) => erro.details.map((d) => d.msg).filter(Boolean).join(" ") || erro.message;

export default function Webhooks() {
  const session = useSession();
  if (!hasAnyRole(session, "owner", "admin")) {
    return (
      <Page title="Webhooks" description="Avisos automáticos para os sistemas da organização.">
        <Alert>Só donos e administradores cadastram e acompanham webhooks.</Alert>
      </Page>
    );
  }
  return <Gestao />;
}

function Gestao() {
  const enderecos = useQuery(webhooks.endpoints);
  const eventos = useQuery(webhooks.events);
  const entregas = useListQuery(webhooks.deliveries, { live: "webhooks.entrega" }); // cada tentativa atualiza a lista
  return (
    <Page
      title="Webhooks"
      description="Avise os sistemas da sua organização quando algo acontece aqui. Cada evento sai assinado e, se o endereço falhar, é enviado de novo por até 15 horas."
    >
      <Tabs
        tabs={[
          { id: "enderecos", label: "Endereços", content: <Enderecos enderecos={enderecos} eventos={eventos} /> },
          { id: "entregas", label: "Entregas", content: <Entregas entregas={entregas} enderecos={enderecos} /> },
          { id: "eventos", label: "Eventos", content: <Eventos eventos={eventos} /> },
        ]}
      />
    </Page>
  );
}

function Enderecos({ enderecos, eventos }: { enderecos: QueryState<WebhooksEndpointList>; eventos: QueryState<WebhooksEventList> }) {
  const [criando, setCriando] = useState(false);
  const [editando, setEditando] = useState<WebhooksEndpoint | null>(null);
  const [segredo, setSegredo] = useState<{ url: string; secret: string } | null>(null);
  const [teste, setTeste] = useState<WebhooksDelivery | null>(null);
  const mostrarSegredo = (r: { endpoint: WebhooksEndpoint; secret: string }) => setSegredo({ url: r.endpoint.url, secret: r.secret });

  const criar = useAction(webhooks.createEndpoint, {
    onSuccess: (r) => {
      mostrarSegredo(r);
      setCriando(false);
      enderecos.reload();
    },
  });
  const salvar = useAction(webhooks.updateEndpoint, {
    onSuccess: () => {
      setEditando(null);
      enderecos.reload();
    },
  });
  const alternar = useAction(webhooks.updateEndpoint, { onSuccess: enderecos.reload });
  const trocar = useAction(webhooks.rotateSecret, { onSuccess: mostrarSegredo });
  const remover = useAction(webhooks.removeEndpoint, { onSuccess: enderecos.reload });
  const testar = useAction(webhooks.testEndpoint, {
    onSuccess: (entrega) => {
      setTeste(entrega);
      refresh(webhooks.deliveries); // a aba Entregas mostra o teste
    },
  });
  const erro = alternar.error ?? trocar.error ?? remover.error ?? testar.error;
  const todos = eventos.data?.items ?? [];

  return (
    <Stack>
      {segredo && (
        <Card title="Segredo de assinatura" description={segredo.url} footer={<Button onClick={() => setSegredo(null)}>Já guardei</Button>}>
          <CopyField
            label="Segredo"
            value={segredo.secret}
            hint="Aparece só agora. Guarde no sistema que recebe: com ele, o sistema confere que cada entrega veio daqui."
          />
        </Card>
      )}
      {teste && (
        <Alert tone={teste.status === "sent" ? "success" : "danger"} title={teste.status === "sent" ? "Teste entregue" : "O teste não foi aceito"}>
          {teste.url}: {teste.response_status ? `resposta ${teste.response_status}` : (teste.error ?? "sem resposta")}
          {teste.duration_ms !== null && teste.duration_ms !== undefined ? ` em ${teste.duration_ms} ms.` : "."}
        </Alert>
      )}
      {erro && <Alert tone="danger">{mensagem(erro)}</Alert>}
      <Row justify="end">
        <Button onClick={() => setCriando(true)}>Novo endereço</Button>
      </Row>
      <QueryView query={enderecos}>
        {(lista) => (
          <DataTable
            rows={lista.items}
            rowKey={(e) => e.id}
            caption="Endereços que recebem eventos"
            empty="Nenhum endereço ainda. Cadastre um para começar a receber eventos."
            columns={[
              {
                key: "url",
                header: "Endereço",
                render: (e) => (
                  <Stack gap="sm">
                    <Code>{e.url}</Code>
                    {e.description && (
                      <Text tone="muted" size="sm">
                        {e.description}
                      </Text>
                    )}
                    {e.disabled_reason && (
                      <Text tone="danger" size="sm">
                        {e.disabled_reason}
                      </Text>
                    )}
                  </Stack>
                ),
              },
              {
                key: "events",
                header: "Eventos",
                render: (e) =>
                  e.events.includes("*") ? (
                    <Badge tone="accent">Todos</Badge>
                  ) : (
                    <Row gap="sm" wrap>
                      {e.events.map((nome) => (
                        <Badge key={nome}>{nome}</Badge>
                      ))}
                    </Row>
                  ),
              },
              {
                key: "enabled",
                header: "Ativo",
                render: (e) => (
                  <Toggle
                    label={`Ativo: ${e.url}`}
                    hideLabel
                    checked={e.enabled}
                    disabled={alternar.running}
                    onChange={(enabled) => void alternar.run({ id: e.id, enabled })}
                    hint={e.failures ? `${e.failures} falhas seguidas` : undefined}
                  />
                ),
              },
              {
                key: "acoes",
                header: "",
                render: (e) => (
                  <Row gap="sm" wrap>
                    <Button size="sm" variant="secondary" onClick={() => void testar.run({ id: e.id })} loading={testar.running} disabled={!e.enabled}>
                      Testar
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditando(e)}>
                      Editar
                    </Button>
                    <ConfirmButton onConfirm={() => void trocar.run({ id: e.id })} confirmLabel="Trocar agora" loading={trocar.running}>
                      Trocar segredo
                    </ConfirmButton>
                    <ConfirmButton onConfirm={() => void remover.run({ id: e.id })} confirmLabel="Remover agora" loading={remover.running}>
                      Remover
                    </ConfirmButton>
                  </Row>
                ),
              },
            ]}
          />
        )}
      </QueryView>
      <SidePanel open={criando} onClose={() => setCriando(false)} title="Novo endereço" description="O segredo de assinatura aparece logo depois de salvar.">
        <FormularioEndereco eventos={todos} rotulo="Cadastrar" salvando={criar.running} erro={criar.error} onSalvar={(corpo) => void criar.run(corpo)} />
      </SidePanel>
      <SidePanel open={editando !== null} onClose={() => setEditando(null)} title="Editar endereço" description={editando?.url}>
        {editando && (
          <FormularioEndereco
            key={editando.id}
            inicial={editando}
            eventos={todos}
            rotulo="Salvar"
            salvando={salvar.running}
            erro={salvar.error}
            onSalvar={(corpo) => void salvar.run({ id: editando.id, ...corpo })}
          />
        )}
      </SidePanel>
    </Stack>
  );
}

function FormularioEndereco(props: {
  inicial?: WebhooksEndpoint;
  eventos: { name: string; description: string }[];
  rotulo: string;
  salvando: boolean;
  erro: ApiError | null;
  onSalvar: (corpo: WebhooksEndpointInput) => void;
}) {
  const { inicial, eventos, rotulo, salvando, erro, onSalvar } = props;
  const [url, setUrl] = useState(inicial?.url ?? "");
  const [descricao, setDescricao] = useState(inicial?.description ?? "");
  const [escolhidos, setEscolhidos] = useState<string[]>(inicial?.events ?? ["*"]);
  const todos = escolhidos.includes("*");
  const marcar = (nome: string, ligado: boolean) => setEscolhidos((atuais) => (ligado ? [...atuais, nome] : atuais.filter((n) => n !== nome)));
  return (
    <Form onSubmit={() => onSalvar({ url, description: descricao, events: todos ? ["*"] : escolhidos })} busy={salvando}>
      <TextField
        label="Endereço (URL)"
        type="url"
        value={url}
        onChange={setUrl}
        required
        placeholder="https://sistema.exemplo.com/webhooks"
        hint="Precisa ser https e aceitar POST com JSON. Responda 2xx para confirmar o recebimento."
      />
      <TextField label="Descrição" value={descricao} onChange={setDescricao} hint="Opcional: para que sistema vão os eventos." />
      <Toggle label="Todos os eventos" checked={todos} onChange={(ligado) => setEscolhidos(ligado ? ["*"] : [])} hint="Inclui os que surgirem depois." />
      {!todos && eventos.map((e) => <Toggle key={e.name} label={e.name} hint={e.description} checked={escolhidos.includes(e.name)} onChange={(ligado) => marcar(e.name, ligado)} />)}
      {!todos && !escolhidos.length && <Text tone="muted">Escolha ao menos um evento.</Text>}
      {erro && <Alert tone="danger">{mensagem(erro)}</Alert>}
      <Button type="submit" loading={salvando} disabled={!todos && !escolhidos.length}>
        {rotulo}
      </Button>
    </Form>
  );
}

function Entregas({ entregas, enderecos }: { entregas: ListState<WebhooksDelivery>; enderecos: QueryState<WebhooksEndpointList> }) {
  const reenviar = useAction(webhooks.retryDelivery, { onSuccess: entregas.reload });
  return (
    <Stack>
      {reenviar.error && <Alert tone="danger">{reenviar.error.message}</Alert>}
      <ListView
        list={entregas}
        rowKey={(d) => d.id}
        noun="entregas"
        caption="Entregas de eventos"
        empty="Nenhuma entrega ainda. Use Testar num endereço para ver a primeira."
        filters={[
          { name: "status", label: "Situação", options: Object.entries(STATUS).map(([value, label]) => ({ value, label })) },
          { name: "endpoint", label: "Endereço", options: (enderecos.data?.items ?? []).map((e) => ({ value: e.id, label: e.url })) },
        ]}
        columns={[
          { key: "event", header: "Evento", render: (d) => <Code>{d.event}</Code> },
          { key: "url", header: "Endereço", render: (d) => <Text size="sm">{d.url}</Text> },
          { key: "status", header: "Situação", render: (d) => <StatusBadge value={d.status} labels={STATUS} tones={TOM} /> },
          {
            key: "resposta",
            header: "Resposta",
            render: (d) => `${d.response_status ?? d.error ?? "—"} · ${d.attempts} ${d.attempts === 1 ? "tentativa" : "tentativas"}`,
          },
          { key: "created_at", header: "Quando", sort: "created_at", render: (d) => <DateTime value={d.created_at} format="relative" /> },
          {
            key: "acoes",
            header: "",
            render: (d) =>
              d.status === "pending" ? null : (
                <Button size="sm" variant="ghost" onClick={() => void reenviar.run({ id: d.id })} loading={reenviar.running}>
                  Reenviar
                </Button>
              ),
          },
        ]}
      />
    </Stack>
  );
}

function Eventos({ eventos }: { eventos: QueryState<WebhooksEventList> }) {
  return (
    <Stack>
      <Card title="Como conferir a assinatura">
        <Stack gap="sm">
          <Text>
            Cada entrega é um POST com o corpo {"{ type, timestamp, data }"} e três cabeçalhos do padrão Standard Webhooks:
            webhook-id (o mesmo em toda tentativa: use para não processar duas vezes), webhook-timestamp e webhook-signature.
          </Text>
          <Code block>{'webhook-signature = "v1," + base64(HMAC-SHA256(segredo sem "whsec_" em base64, "{webhook-id}.{webhook-timestamp}.{corpo}"))'}</Code>
          <Text tone="muted" size="sm">
            Qualquer biblioteca do padrão (standardwebhooks, svix) confere com o segredo do endereço. Recuse assinaturas com mais de 5 minutos.
          </Text>
        </Stack>
      </Card>
      <QueryView query={eventos}>
        {(lista) => (
          <Stack>
            {lista.items.map((evento) => (
              <Card key={evento.name} title={evento.name} description={evento.description}>
                <DataTable
                  rows={Object.entries((evento.payload_schema.properties ?? {}) as Record<string, { type?: string; description?: string }>)}
                  rowKey={([campo]) => campo}
                  caption={`Campos de data em ${evento.name}`}
                  columns={[
                    { key: "campo", header: "Campo em data", render: ([campo]) => <Code>{campo}</Code> },
                    { key: "tipo", header: "Tipo", render: ([, info]) => info.type ?? "—" },
                    { key: "descricao", header: "Descrição", render: ([, info]) => info.description ?? "" },
                  ]}
                />
              </Card>
            ))}
          </Stack>
        )}
      </QueryView>
    </Stack>
  );
}
