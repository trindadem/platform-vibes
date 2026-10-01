import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Code } from "@/components/Code";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DataTable } from "@/components/DataTable";
import { Grid } from "@/components/Grid";
import { ListView } from "@/components/ListView";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { Quantity } from "@/components/Quantity";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { Stat } from "@/components/Stat";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { Toggle } from "@/components/Toggle";
import { type ListState, type QueryState, useAction, useListQuery, useLiveQuery, useQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type AiModel, type AiProviderList, type AiUsageSummary, ai } from "@/core/contracts";

export const meta: PageMeta = { title: "IA", order: 4, module: "ai" };

const ORIGEM = { organization: "Sua organização", platform: "Plataforma" };
const TIPO = { chat: "Conversa", embedding: "Vetores" };

/** "2026-10" → "outubro de 2026" (o mês do resumo é em UTC). */
const mesPorExtenso = (mes: string) => new Date(`${mes}-15T12:00:00Z`).toLocaleDateString("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" });

export default function Ia() {
  const session = useSession();
  return hasAnyRole(session, "owner", "admin") ? <Gestao /> : <Disponiveis />;
}

/** Membros: só veem os modelos liberados (o serviço garante), com o nome que os serviços usam. */
function Disponiveis() {
  const modelos = useListQuery(ai.models);
  return (
    <Page title="IA" description="Modelos que os serviços da sua organização podem usar.">
      <Alert>Só donos e administradores cadastram provedores e liberam modelos.</Alert>
      <ListView
        list={modelos}
        rowKey={(m) => m.id}
        search="claude, gpt, llama…"
        caption="Modelos liberados"
        empty="Nenhum modelo liberado ainda."
        noun="modelos"
        columns={[
          { key: "name", header: "Nome", sort: "model_id", render: (m) => <Code>{m.name}</Code> },
          { key: "kind", header: "Tipo", render: (m) => <Badge>{TIPO[m.kind]}</Badge> },
          { key: "scope", header: "Origem", render: (m) => ORIGEM[m.scope] },
        ]}
      />
    </Page>
  );
}

/** Donos e administradores: uso do mês, curadoria de modelos e provedores. */
function Gestao() {
  const uso = useLiveQuery("ai.uso", ai.usage); // cada chamada de IA da organização atualiza a aba sozinha
  const provedores = useQuery(ai.providers);
  const modelos = useListQuery(ai.models); // página, busca e filtros ficam na URL (?q=claude&enabled=true); a aba, no #
  return (
    <Page title="IA" description="Provedores compatíveis com a API da OpenAI, modelos liberados e o uso do mês.">
      <Tabs
        tabs={[
          { id: "uso", label: "Uso do mês", content: <Uso uso={uso} /> },
          { id: "modelos", label: "Modelos", content: <Modelos modelos={modelos} provedores={provedores} /> },
          { id: "provedores", label: "Provedores", content: <Provedores provedores={provedores} modelos={modelos} /> },
        ]}
      />
    </Page>
  );
}

function Uso({ uso }: { uso: QueryState<AiUsageSummary> }) {
  return (
    <QueryView query={uso}>
      {(resumo) => (
        <>
          <Grid cols={4}>
            <Stat label="Custo" value={<Money value={resumo.cost} currency="USD" digits={4} />} hint={`em ${mesPorExtenso(resumo.month)}`} />
            <Stat label="Chamadas" value={<Quantity value={resumo.calls} />} />
            <Stat label="Tokens de entrada" value={<Quantity value={resumo.input_tokens} compact />} />
            <Stat label="Tokens de saída" value={<Quantity value={resumo.output_tokens} compact />} />
          </Grid>
          <DataTable
            rows={resumo.items}
            rowKey={(i) => `${i.model}|${i.service}`}
            caption="Uso por modelo e serviço"
            empty="Nenhuma chamada de IA neste mês."
            columns={[
              { key: "model", header: "Modelo", render: (i) => <Code>{i.model}</Code> },
              { key: "service", header: "Serviço" },
              { key: "calls", header: "Chamadas", render: (i) => <Quantity value={i.calls} /> },
              { key: "input_tokens", header: "Entrada", render: (i) => <Quantity value={i.input_tokens} compact /> },
              { key: "output_tokens", header: "Saída", render: (i) => <Quantity value={i.output_tokens} compact /> },
              { key: "cost", header: "Custo", render: (i) => <Money value={i.cost} currency="USD" digits={4} /> },
            ]}
          />
          <Text tone="muted" size="sm">
            Custo em dólar, pelo preço informado em cada modelo no momento da chamada. Modelo sem preço conta os tokens com custo zero.
          </Text>
        </>
      )}
    </QueryView>
  );
}

function Modelos({ modelos, provedores }: { modelos: ListState<AiModel>; provedores: QueryState<AiProviderList> }) {
  const [editando, setEditando] = useState<AiModel | null>(null);
  const [cadastrando, setCadastrando] = useState(false);
  const gerePlataforma = provedores.data?.manages_platform ?? false;
  const editavel = (m: AiModel) => m.scope === "organization" || gerePlataforma;

  const alternar = useAction(ai.updateModel, { onSuccess: modelos.reload });
  const salvar = useAction(
    (v: { alias?: string; kind?: "chat" | "embedding"; price_input?: number; price_output?: number }) =>
      ai.updateModel({ ...v, id: editando?.id ?? "", alias: v.alias ?? "" }), // apelido apagado volta vazio: remove
    { onSuccess: modelos.reload },
  );
  const cadastrar = useAction(ai.addModel, { onSuccess: modelos.reload });
  const meusProvedores = (provedores.data?.items ?? []).filter((p) => p.scope === "organization" || gerePlataforma);

  return (
    <>
      {alternar.error && <Alert tone="danger">{alternar.error.message}</Alert>}
      <ListView
        list={modelos}
        rowKey={(m) => m.id}
        search="claude, gpt, llama…"
        caption="Modelos"
        noun="modelos"
        empty="Nenhum modelo ainda. Cadastre um provedor e use Buscar modelos."
        filters={[
          {
            name: "enabled",
            label: "Mostrar",
            options: [
              { value: "true", label: "Liberados" },
              { value: "false", label: "Não liberados" },
            ],
          },
          {
            name: "kind",
            label: "Tipo",
            options: [
              { value: "chat", label: TIPO.chat },
              { value: "embedding", label: TIPO.embedding },
            ],
          },
        ]}
        actions={
          <Button variant="secondary" onClick={() => setCadastrando(true)} disabled={meusProvedores.length === 0}>
            Cadastrar à mão
          </Button>
        }
        columns={[
          { key: "name", header: "Nome nos serviços", sort: "model_id", render: (m) => <Code>{m.name}</Code> },
          { key: "kind", header: "Tipo", render: (m) => <Badge>{TIPO[m.kind]}</Badge> },
          { key: "scope", header: "Origem", render: (m) => <Badge tone={m.scope === "platform" ? "accent" : "neutral"}>{ORIGEM[m.scope]}</Badge> },
          {
            key: "price",
            header: "US$ / 1 mi tokens",
            render: (m) => (
              <Row gap="sm">
                <Money value={m.price_input} currency="USD" digits={4} />
                <Text tone="muted" size="sm">
                  ·
                </Text>
                <Money value={m.price_output} currency="USD" digits={4} />
              </Row>
            ),
          },
          {
            key: "enabled",
            header: "Liberado",
            render: (m) => (
              <Toggle
                label={`Liberar ${m.name}`}
                hideLabel
                checked={m.enabled}
                disabled={!editavel(m) || alternar.running}
                onChange={(ligado) => void alternar.run({ id: m.id, enabled: ligado })}
              />
            ),
          },
          {
            key: "acoes",
            header: "",
            render: (m) =>
              editavel(m) ? (
                <Button variant="ghost" size="sm" onClick={() => setEditando(m)}>
                  Editar
                </Button>
              ) : null,
          },
        ]}
      />

      <SidePanel
        open={editando !== null}
        onClose={() => setEditando(null)}
        title={editando ? `Editar ${editando.name}` : "Editar modelo"}
        description="O apelido muda o nome que os serviços usam; os preços valem para as próximas chamadas."
      >
        {editando && (
          <ActionForm
            key={editando.id}
            action={salvar}
            submitLabel="Salvar"
            onDone={() => setEditando(null)}
            initial={{
              alias: editando.alias ?? "",
              kind: editando.kind,
              price_input: String(editando.price_input),
              price_output: String(editando.price_output),
            }}
            fields={[
              { name: "alias", label: "Apelido", hint: `Vazio: os serviços chamam pelo id (${editando.model_id}).` },
              {
                name: "kind",
                label: "Tipo",
                kind: "select",
                required: true,
                options: [
                  { value: "chat", label: "Conversa (llm.ask, llm.stream)" },
                  { value: "embedding", label: "Vetores (llm.embed)" },
                ],
              },
              { name: "price_input", label: "Preço de entrada (US$ por 1 milhão de tokens)", kind: "number" },
              { name: "price_output", label: "Preço de saída (US$ por 1 milhão de tokens)", kind: "number" },
            ]}
          />
        )}
      </SidePanel>

      <SidePanel
        open={cadastrando}
        onClose={() => setCadastrando(false)}
        title="Cadastrar modelo à mão"
        description="Para provedor que não lista modelos. O modelo já nasce liberado."
      >
        <ActionForm
          action={cadastrar}
          submitLabel="Cadastrar"
          onDone={() => setCadastrando(false)}
          initial={{ kind: "chat", provider: meusProvedores[0]?.id ?? "" }}
          fields={[
            {
              name: "provider",
              label: "Provedor",
              kind: "select",
              required: true,
              options: meusProvedores.map((p) => ({ value: p.id, label: `${p.name} (${p.slug})` })),
            },
            { name: "model_id", label: "Id do modelo no provedor", required: true, placeholder: "llama3.2" },
            {
              name: "kind",
              label: "Tipo",
              kind: "select",
              required: true,
              options: [
                { value: "chat", label: "Conversa" },
                { value: "embedding", label: "Vetores" },
              ],
            },
          ]}
        />
      </SidePanel>
    </>
  );
}

function Provedores({ provedores, modelos }: { provedores: QueryState<AiProviderList>; modelos: ListState<AiModel> }) {
  const [criando, setCriando] = useState(false);
  const criar = useAction(ai.createProvider, { onSuccess: provedores.reload });
  const buscar = useAction(ai.discoverModels, { onSuccess: modelos.reload });
  const remover = useAction(ai.removeProvider, {
    onSuccess: () => {
      provedores.reload();
      modelos.reload();
    },
  });
  const gerePlataforma = provedores.data?.manages_platform ?? false;

  return (
    <>
      <Row justify="between">
        <Text tone="muted">Qualquer API compatível com a da OpenAI. Um provedor da sua organização tem prioridade sobre o da plataforma com o mesmo apelido.</Text>
        <Button onClick={() => setCriando(true)}>Novo provedor</Button>
      </Row>
      {gerePlataforma && (
        <Alert title="Sua organização administra a plataforma">Provedores com origem Plataforma valem para todas as organizações.</Alert>
      )}
      {buscar.result && (
        <Alert tone="success" title={`O provedor listou ${buscar.result.found} ${buscar.result.found === 1 ? "modelo" : "modelos"}`}>
          {buscar.result.added === 0
            ? "Nenhum modelo novo desde a última busca."
            : `${buscar.result.added} ${buscar.result.added === 1 ? "novo aguarda" : "novos aguardam"} liberação.`}{" "}
          Veja em <TextLink to="/ia?enabled=false#modelos">Modelos</TextLink>.
        </Alert>
      )}
      {buscar.error && <Alert tone="danger">{buscar.error.message}</Alert>}
      {remover.error && <Alert tone="danger">{remover.error.message}</Alert>}
      <QueryView query={provedores}>
        {(lista) => (
          <DataTable
            rows={lista.items}
            rowKey={(p) => p.id}
            caption="Provedores de IA"
            empty="Nenhum provedor ainda. Cadastre o primeiro em Novo provedor."
            columns={[
              { key: "name", header: "Nome" },
              { key: "slug", header: "Apelido", render: (p) => <Code>{p.slug}</Code> },
              {
                key: "base_url",
                header: "Endereço",
                render: (p) => (p.base_url ? <Code>{p.base_url}</Code> : <Text tone="muted" size="sm">gerido pela plataforma</Text>),
              },
              { key: "key_hint", header: "Chave", render: (p) => (p.key_hint ? <Code>{p.key_hint}</Code> : p.base_url ? "sem chave" : "—") },
              { key: "scope", header: "Origem", render: (p) => <Badge tone={p.scope === "platform" ? "accent" : "neutral"}>{ORIGEM[p.scope]}</Badge> },
              {
                key: "acoes",
                header: "",
                render: (p) =>
                  p.scope === "organization" || gerePlataforma ? (
                    <Row gap="sm" wrap={false}>
                      <Button variant="secondary" size="sm" loading={buscar.running} onClick={() => void buscar.run({ id: p.id })}>
                        Buscar modelos
                      </Button>
                      <ConfirmButton confirmLabel="Remover com os modelos" loading={remover.running} onConfirm={() => void remover.run({ id: p.id })}>
                        Remover
                      </ConfirmButton>
                    </Row>
                  ) : null,
              },
            ]}
          />
        )}
      </QueryView>

      <SidePanel
        open={criando}
        onClose={() => setCriando(false)}
        title="Novo provedor"
        description="Depois de salvar, use Buscar modelos e libere os que os serviços vão usar."
      >
        <ActionForm
          action={criar}
          submitLabel="Salvar provedor"
          onDone={() => setCriando(false)}
          initial={{ scope: "organization" }}
          fields={[
            { name: "name", label: "Nome", required: true, placeholder: "OpenRouter" },
            { name: "slug", label: "Apelido", required: true, placeholder: "openrouter", hint: "Minúsculas, números e hífen. Vira o começo do nome do modelo: openrouter/claude." },
            {
              name: "base_url",
              label: "Endereço base",
              required: true,
              placeholder: "https://openrouter.ai/api/v1",
              hint: "Ex.: https://api.openai.com/v1 · https://openrouter.ai/api/v1 · https://api.groq.com/openai/v1",
            },
            { name: "api_key", label: "Chave", kind: "password", autoComplete: "off", hint: "Guardada criptografada; depois só aparecem os 4 últimos caracteres." },
            ...(gerePlataforma
              ? [
                  {
                    name: "scope" as const,
                    label: "Vale para",
                    kind: "select" as const,
                    required: true,
                    options: [
                      { value: "organization", label: "Só a sua organização" },
                      { value: "platform", label: "Todas as organizações (plataforma)" },
                    ],
                  },
                ]
              : []),
          ]}
        />
      </SidePanel>
    </>
  );
}
