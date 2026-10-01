import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Grid } from "@/components/Grid";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { SidePanel } from "@/components/SidePanel";
import { Spinner } from "@/components/Spinner";
import { Stack } from "@/components/Stack";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { useAction, useLiveQuery, useQuery, useStream } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type ProcessosPassoAgente, type ProcessosProcesso, processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Processos", order: 3, module: "processos" };

const AREA = { financeiro: "Financeiro", juridico: "Jurídico", administrativo: "Administrativo", vendas: "Vendas" };
const PRIORIDADE = { alta: "Prioridade alta", media: "Prioridade média", baixa: "Prioridade baixa" };
const TOM = { alta: "warning", media: "neutral", baixa: "neutral" } as const;
const ORDEM = { alta: 0, media: 1, baixa: 2 };

/** Prioridade alta primeiro; na mesma prioridade, na ordem em que o agente sugeriu. */
const emOrdem = (itens: ProcessosProcesso[]) =>
  [...itens].sort((a, b) => ORDEM[a.prioridade] - ORDEM[b.prioridade] || (a.created_at ?? "").localeCompare(b.created_at ?? ""));

export default function Processos() {
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  const lista = useLiveQuery("processos.processos", processos.listar, { size: 100 });
  const descoberta = useStream(processos.descoberta);
  const [descrevendo, setDescrevendo] = useState(false);
  const descrever = useAction(processos.descrever, { onSuccess: lista.reload });
  const descobrir = async () => {
    await descoberta.start({});
    lista.reload();
  };
  return (
    <Page
      title="Processos"
      description="O que a Cogniventure pode executar para a sua empresa. Aceite o que faz sentido: os aceitos seguem para o desenho."
      actions={
        pode && (
          <>
            <Button variant="secondary" onClick={() => setDescrevendo(true)}>
              Descrever um processo
            </Button>
            <Button loading={descoberta.running} onClick={() => void descobrir()}>
              Sugerir processos
            </Button>
          </>
        )
      }
    >
      {descoberta.running && <Andamento passos={descoberta.deltas} />}
      {descoberta.error && <Alert tone="danger">{descoberta.error.message}</Alert>}
      {descoberta.result && !descoberta.running && (
        <Alert tone="success" title="Sugestões do agente">
          {descoberta.result.texto}
        </Alert>
      )}
      <QueryView query={lista}>
        {(pagina) => {
          const por = (status: ProcessosProcesso["status"]) => pagina.items.filter((p) => p.status === status);
          return (
            <Tabs
              tabs={[
                { id: "sugeridos", label: `Sugeridos (${por("sugerido").length})`, content: <Lista itens={por("sugerido")} pode={pode} vazio="Nenhuma sugestão pendente. Clique em Sugerir processos depois do briefing." /> },
                { id: "aceitos", label: `Aceitos (${por("aceito").length})`, content: <Lista itens={por("aceito")} pode={pode} vazio="Nenhum processo aceito ainda." /> },
                { id: "recusados", label: `Recusados (${por("recusado").length})`, content: <Lista itens={por("recusado")} pode={pode} vazio="Nenhum processo recusado." /> },
                { id: "biblioteca", label: "Biblioteca", content: <BibliotecaCompleta /> },
              ]}
            />
          );
        }}
      </QueryView>
      <SidePanel open={descrevendo} onClose={() => setDescrevendo(false)} title="Descrever um processo" description="Conte como funciona hoje: o que dispara, o que acontece, quem participa e quando dá problema.">
        {descrevendo && (
          <ActionForm
            action={descrever}
            submitLabel="Registrar processo"
            onDone={() => setDescrevendo(false)}
            fields={[{ name: "texto", label: "Como funciona", kind: "textarea", required: true, placeholder: "Quando um funcionário gasta do próprio bolso, ele manda o recibo pelo WhatsApp..." }]}
          />
        )}
      </SidePanel>
    </Page>
  );
}

function Andamento({ passos }: { passos: ProcessosPassoAgente[] }) {
  const feitos = passos.filter((p) => p.status !== "running");
  return (
    <Card title="O agente está analisando o briefing" description="Ele lê o perfil e o conhecimento da empresa e escolhe na biblioteca.">
      <Spinner label="Descobrindo processos" />
      {feitos.map((p, i) => (
        <Text key={`${p.ferramenta}-${i}`} size="sm" tone={p.status === "failed" ? "danger" : "muted"}>
          {p.status === "failed" ? "✗" : "✓"} {p.texto}
        </Text>
      ))}
    </Card>
  );
}

function Lista({ itens, pode, vazio }: { itens: ProcessosProcesso[]; pode: boolean; vazio: string }) {
  const aceitar = useAction(processos.aceitar);
  const recusar = useAction(processos.recusar);
  if (!itens.length) return <EmptyState title={vazio} />;
  return (
    <Stack>
      {(aceitar.error || recusar.error) && <Alert tone="danger">{(aceitar.error ?? recusar.error)?.message}</Alert>}
      <Grid cols={2}>
        {emOrdem(itens).map((p) => (
          <Card
            key={p.id}
            title={p.titulo}
            description={`${AREA[p.area]} · ${p.origem === "cliente" ? "descrito por você" : "sugerido pelo agente"}`}
            footer={
              pode && (
                <>
                  {p.status !== "aceito" && (
                    <Button size="sm" loading={aceitar.running} onClick={() => void aceitar.run({ id: p.id })}>
                      {p.status === "recusado" ? "Reconsiderar" : "Aceitar"}
                    </Button>
                  )}
                  {p.status === "sugerido" && (
                    <Button size="sm" variant="ghost" loading={recusar.running} onClick={() => void recusar.run({ id: p.id })}>
                      Recusar
                    </Button>
                  )}
                  {p.status === "aceito" && <Badge>Desenho em breve</Badge>}
                </>
              )
            }
          >
            {p.status === "sugerido" && <Badge tone={TOM[p.prioridade]}>{PRIORIDADE[p.prioridade]}</Badge>}
            {p.motivo && <Text>{p.motivo}</Text>}
            <Text tone="muted" size="sm">
              {p.descricao}
            </Text>
          </Card>
        ))}
      </Grid>
    </Stack>
  );
}

function BibliotecaCompleta() {
  const biblioteca = useQuery(processos.biblioteca);
  return (
    <QueryView query={biblioteca}>
      {(b) => (
        <Grid cols={2}>
          {b.itens.map((m) => (
            <Card key={m.id} title={m.titulo} description={`${AREA[m.area]} · ${m.resumo}`}>
              <KeyValue
                stacked
                items={[
                  { label: "Quando começa", value: m.gatilho },
                  { label: "O que roda sozinho", value: m.roda_sozinho },
                  { label: "Quando uma pessoa entra", value: m.handoff },
                  ...(m.integracoes.length ? [{ label: "Conexões", value: m.integracoes.join(", ") }] : []),
                ]}
              />
            </Card>
          ))}
        </Grid>
      )}
    </QueryView>
  );
}
