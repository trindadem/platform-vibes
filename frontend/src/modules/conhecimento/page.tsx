import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DateTime } from "@/components/DateTime";
import { EmptyState } from "@/components/EmptyState";
import { FileField } from "@/components/FileField";
import { Form } from "@/components/Form";
import { Grid } from "@/components/Grid";
import { ListView } from "@/components/ListView";
import { Page } from "@/components/Page";
import { Quantity } from "@/components/Quantity";
import { QueryView } from "@/components/QueryView";
import { ResourceList } from "@/components/ResourceList";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextField } from "@/components/TextField";
import { useAction, useListQuery, useLive, useQuery, useResource, useUpload } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { conhecimento } from "@/core/contracts";

export const meta: PageMeta = { title: "Conhecimento", order: 2, module: "conhecimento" };

const FONTE = { briefing: "Briefing", site: "Site", documento: "Documento", manual: "Manual" };
const LEITURA = { lendo: "Lendo", pronta: "Pronta", falhou: "Falhou" };
const LEITURA_TONS = { lendo: "warning", pronta: "success", falhou: "danger" } as const;
const TIPOS = ".pdf,.docx,.txt,.md,.csv,application/pdf,text/plain,text/markdown,text/csv";

export default function Conhecimento() {
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  return (
    <Page title="Conhecimento" description="O que a plataforma sabe da sua empresa e que os agentes consultam. Corrija ou apague o que estiver errado.">
      <Tabs
        tabs={[
          { id: "itens", label: "Itens", content: <Itens pode={pode} /> },
          { id: "fontes", label: "Site e documentos", content: <Fontes pode={pode} /> },
          { id: "busca", label: "Testar a busca", content: <Busca /> },
        ]}
      />
    </Page>
  );
}

function Itens({ pode }: { pode: boolean }) {
  const itens = useResource(conhecimento.itens);
  return <ResourceList resource={itens} noun="item" readOnly={!pode} />;
}

function Fontes({ pode }: { pode: boolean }) {
  const leituras = useListQuery(conhecimento.leituras);
  useLive("conhecimento.leituras", () => leituras.reload());
  const site = useAction(conhecimento.lerSite, { onSuccess: leituras.reload });
  const documento = useUpload(conhecimento.documentoUpload, conhecimento.lerDocumento, { onSuccess: leituras.reload });
  const remover = useAction(conhecimento.removerLeitura, { onSuccess: leituras.reload });
  return (
    <Stack>
      {pode && (
        <Grid cols={2}>
          <Card title="Ler o site" description="A página inicial e até 7 páginas que ela cita, em segundo plano.">
            <ActionForm action={site} submitLabel="Ler o site" fields={[{ name: "url", label: "Endereço do site", placeholder: "www.suaempresa.com.br", required: true }]} />
          </Card>
          <Card title="Enviar um documento" description="Contratos, tabela de preços, manuais, políticas.">
            <FileField label="Documento" upload={documento} accept={TIPOS} hint="PDF, Word (DOCX), TXT, Markdown ou CSV, até 10 MB. PDF escaneado (imagem) não tem texto para ler." />
          </Card>
        </Grid>
      )}
      {remover.error && <Alert tone="danger">{remover.error.message}</Alert>}
      <ListView
        list={leituras}
        rowKey={(l) => l.id}
        caption="Leituras de site e documentos"
        noun="leituras"
        empty="Nenhum site ou documento lido ainda."
        filters={[
          { name: "tipo", label: "Tipo", options: [{ value: "site", label: "Site" }, { value: "documento", label: "Documento" }] },
          { name: "status", label: "Status", options: Object.entries(LEITURA).map(([value, label]) => ({ value, label })) },
        ]}
        columns={[
          { key: "origem", header: "Origem", sort: "origem" },
          { key: "tipo", header: "Tipo", render: (l) => <Badge>{l.tipo === "site" ? "Site" : "Documento"}</Badge> },
          {
            key: "status",
            header: "Status",
            render: (l) => (
              <Stack gap="sm">
                <StatusBadge value={l.status} labels={LEITURA} tones={LEITURA_TONS} />
                {l.erro && (
                  <Text tone="danger" size="sm">
                    {l.erro}
                  </Text>
                )}
              </Stack>
            ),
          },
          { key: "itens", header: "Itens", render: (l) => <Quantity value={l.itens} /> },
          { key: "created_at", header: "Quando", sort: "created_at", render: (l) => (l.created_at ? <DateTime value={l.created_at} /> : "—") },
          {
            key: "acoes",
            header: "",
            render: (l) =>
              pode && (
                <ConfirmButton size="sm" confirmLabel="Apagar leitura e itens" loading={remover.running} onConfirm={() => void remover.run({ id: l.id })}>
                  Remover
                </ConfirmButton>
              ),
          },
        ]}
      />
    </Stack>
  );
}

function Busca() {
  const [texto, setTexto] = useState("");
  const [consulta, setConsulta] = useState("");
  return (
    <Stack>
      <Text tone="muted">Veja o que os agentes encontram no conhecimento com estas palavras, em qualquer ordem.</Text>
      <Form onSubmit={() => setConsulta(texto.trim())}>
        <Row align="end">
          <TextField label="Palavras" value={texto} onChange={setTexto} placeholder="como pagamos fornecedores" />
          <Button type="submit" disabled={texto.trim().length < 2}>
            Buscar
          </Button>
        </Row>
      </Form>
      {consulta && <Achados q={consulta} />}
    </Stack>
  );
}

function Achados({ q }: { q: string }) {
  const achados = useQuery(conhecimento.busca, { q });
  return (
    <QueryView query={achados}>
      {(r) =>
        r.itens.length === 0 ? (
          <EmptyState title="Nada encontrado" description="Tente outras palavras, ou acrescente o assunto ao conhecimento." />
        ) : (
          <Stack>
            {r.itens.map((a) => (
              <Card key={a.id} title={a.titulo} description={`${FONTE[a.fonte]}${a.origem ? ` · ${a.origem}` : ""}`}>
                <Text>{a.trecho}</Text>
              </Card>
            ))}
          </Stack>
        )
      }
    </QueryView>
  );
}
