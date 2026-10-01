import { type ReactNode, useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Code } from "@/components/Code";
import { ConfirmButton } from "@/components/ConfirmButton";
import { CopyField } from "@/components/CopyField";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Grid } from "@/components/Grid";
import { Heading } from "@/components/Heading";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { Quantity } from "@/components/Quantity";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { Stack } from "@/components/Stack";
import { Stat } from "@/components/Stat";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextField } from "@/components/TextField";
import { UsageMeter } from "@/components/UsageMeter";
import { type QueryState, refresh, useAction, useLiveQuery, useQuery } from "@/core/api";
import {
  type PlansAccount,
  type PlansCatalog,
  type PlansCatalogLimit,
  type PlansCatalogModule,
  type PlansCurrent,
  type PlansModuleState,
  type PlansPlan,
  type PlansPlanList,
  plans,
} from "@/core/contracts";

export const meta: PageMeta = { title: "Plano", order: 6, module: "plans" };

const MOEDAS = ["BRL", "USD", "EUR"] as const;
type Moeda = (typeof MOEDAS)[number];
type Valores = Record<string, string | number>;

const moeda = (codigo: string | null | undefined): Moeda | null => MOEDAS.find((m) => m === codigo) ?? null;

/** "2026-10" → "outubro de 2026" (o mês dos consumos é em UTC). */
const mesPorExtenso = (mes: string) => new Date(`${mes}-15T12:00:00Z`).toLocaleDateString("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" });

/** Um valor de limite: dinheiro na moeda declarada, ou quantidade (curta quando é grande, como tokens). */
function valor(limite: Pick<PlansCatalogLimit, "currency" | "unit">, v: number): ReactNode {
  const dinheiro = moeda(limite.currency);
  if (dinheiro) return <Money value={v} currency={dinheiro} digits={v < 1 ? 4 : 2} />;
  return <Quantity value={v} compact={v >= 100_000} unit={limite.currency ?? undefined} />;
}

/** O que um plano permite num limite: o valor citado ou o default do serviço. */
function permitido(limite: PlansCatalogLimit, plano: PlansPlan): ReactNode {
  const v = limite.name in plano.limits ? plano.limits[limite.name] : limite.default;
  if (v === null || v === undefined) return "Sem limite";
  if (v === 0) return <Text tone="muted" size="sm">Não incluído</Text>;
  return (
    <Row gap="sm" wrap={false}>
      {valor(limite, v)}
      {limite.unit && !limite.currency && <Text tone="muted" size="sm">{limite.unit}</Text>}
    </Row>
  );
}

const preco = (plano: PlansPlan) => (plano.price ? <Money value={plano.price} currency={plano.currency} /> : "Grátis");

/** Módulos que o plano pode ligar ou desligar (os da plataforma estão sempre ligados). */
const opcionais = (modulos: PlansCatalogModule[]) => modulos.filter((m) => !m.core);

/** O plano inclui o módulo? O que o plano não cita vale o default do módulo. */
const incluido = (modulo: PlansCatalogModule, plano: PlansPlan) => plano.modules[modulo.name] ?? modulo.default;

/** Módulos agrupados pela categoria (a mesma do menu), na ordem do catálogo. */
function porCategoria<M extends PlansCatalogModule>(modulos: M[]): [string, M[]][] {
  const grupos = new Map<string, M[]>();
  for (const m of modulos) grupos.set(m.category, [...(grupos.get(m.category) ?? []), m]);
  return [...grupos];
}

export default function Plano() {
  const atual = useLiveQuery("plans.uso", plans.current); // cada consumo ou total que muda atualiza a tela
  const lista = useQuery(plans.list);
  const catalogo = useQuery(plans.catalog);
  const gere = lista.data?.manages_platform ?? false;
  return (
    <Page title="Plano" description="O que a sua organização pode usar e quanto já usou.">
      <Tabs
        tabs={[
          { id: "uso", label: "Uso", content: <Uso atual={atual} /> },
          { id: "modulos", label: "Módulos", content: <Modulos atual={atual} /> },
          { id: "planos", label: "Planos", content: <Comparacao lista={lista} catalogo={catalogo} /> },
          ...(gere ? [{ id: "gerenciar", label: "Gerenciar", content: <Gerenciar lista={lista} catalogo={catalogo} /> }] : []),
        ]}
      />
    </Page>
  );
}

function Uso({ atual }: { atual: QueryState<PlansCurrent> }) {
  return (
    <QueryView query={atual}>
      {(a) => (
        <>
          <Grid cols={3}>
            <Stat label="Plano" value={a.plan?.name ?? "Sem plano"} hint={a.plan ? a.plan.description || undefined : "Valem os limites padrão da plataforma."} />
            <Stat label="Preço por mês" value={a.plan ? preco(a.plan) : "—"} />
            <Stat label="Mês dos consumos" value={mesPorExtenso(a.month)} hint="Os limites mensais recomeçam no dia 1º (UTC)." />
          </Grid>
          {a.limits.length === 0 ? (
            <EmptyState title="Nenhum limite declarado" description="Os serviços ainda não declararam o que limitam." />
          ) : (
            <Grid cols={2}>
              {a.limits.map((l) => (
                <UsageMeter
                  key={l.name}
                  label={l.description}
                  used={l.used}
                  limit={l.limit}
                  format={(v) => valor(l, v)}
                  hint={l.monthly ? "neste mês" : "agora"}
                />
              ))}
            </Grid>
          )}
          <CopyField label="Código da organização" value={a.tenant} hint="Para trocar de plano, informe este código ao suporte." />
        </>
      )}
    </QueryView>
  );
}

/** Os módulos da plataforma, por categoria, e se cada um está no plano da organização. */
function Modulos({ atual }: { atual: QueryState<PlansCurrent> }) {
  return (
    <QueryView query={atual}>
      {(a) =>
        porCategoria<PlansModuleState>(a.modules).map(([categoria, modulos]) => (
          <Stack key={categoria} gap="sm">
            <Heading level={3}>{categoria}</Heading>
            <Grid cols={3}>
              {modulos.map((m) => (
                <Card key={m.name} title={m.title} description={m.description}>
                  <Row gap="sm">
                    {m.core ? <Badge>Da plataforma</Badge> : m.enabled ? <Badge tone="success">No seu plano</Badge> : <Badge>Fora do plano</Badge>}
                  </Row>
                </Card>
              ))}
            </Grid>
          </Stack>
        ))
      }
    </QueryView>
  );
}

function Comparacao({ lista, catalogo }: { lista: QueryState<PlansPlanList>; catalogo: QueryState<PlansCatalog> }) {
  return (
    <QueryView query={lista}>
      {(planos) => (
        <QueryView query={catalogo}>
          {(c) =>
            planos.items.length === 0 ? (
              <EmptyState title="Nenhum plano publicado" description="Enquanto não houver planos, valem os limites padrão da plataforma." />
            ) : (
              <DataTable
                caption="Comparação de planos"
                rowKey={(linha) => linha.id}
                rows={[
                  { id: "preco", rotulo: "Preço por mês", celula: (p: PlansPlan) => preco(p) },
                  ...opcionais(c.modules).map((m) => ({
                    id: `modulo:${m.name}`,
                    rotulo: m.title,
                    celula: (p: PlansPlan) => (incluido(m, p) ? <Badge tone="success">Incluído</Badge> : <Text tone="muted" size="sm">—</Text>),
                  })),
                  ...c.limits.map((l) => ({ id: l.name, rotulo: l.description, celula: (p: PlansPlan) => permitido(l, p) })),
                ]}
                columns={[
                  { key: "rotulo", header: "" },
                  ...planos.items.map((p) => ({
                    key: p.slug,
                    header: p.slug === planos.current ? `${p.name} (atual)` : p.name,
                    render: (linha: { celula: (p: PlansPlan) => ReactNode }) => linha.celula(p),
                  })),
                ]}
              />
            )
          }
        </QueryView>
      )}
    </QueryView>
  );
}

const SIM_NAO = [
  { value: "true", label: "Incluído" },
  { value: "false", label: "Não incluído" },
];

/** Campos do formulário de plano: os fixos, um por módulo opcional e um por limite (vazio: sem limite; 0: não incluído). */
function campos(c: PlansCatalog, novo: boolean) {
  return [
    ...(novo ? [{ name: "slug", label: "Identificador", required: true, placeholder: "pro", hint: "Minúsculas e hífen; não muda depois." }] : []),
    { name: "name", label: "Nome", required: true, placeholder: "Pro" },
    { name: "description", label: "Descrição", placeholder: "Para equipes que crescem" },
    { name: "price", label: "Preço por mês", kind: "number" as const, hint: "Informativo: a cobrança é do produto." },
    { name: "currency", label: "Moeda", kind: "select" as const, required: true, options: MOEDAS.map((m) => ({ value: m, label: m })) },
    { name: "public", label: "Aparece na comparação", kind: "select" as const, required: true, options: [{ value: "true", label: "Sim" }, { value: "false", label: "Não (sob medida)" }] },
    { name: "default", label: "Plano padrão", kind: "select" as const, required: true, options: [{ value: "false", label: "Não" }, { value: "true", label: "Sim: vale para quem não tem plano" }] },
    ...opcionais(c.modules).map((m) => ({
      name: `modulo:${m.name}`,
      label: `Módulo ${m.title}`,
      kind: "select" as const,
      required: true,
      options: SIM_NAO,
      hint: m.requires.length ? `Precisa de: ${m.requires.map((r) => c.modules.find((x) => x.name === r)?.title ?? r).join(", ")}.` : undefined,
    })),
    ...c.limits.map((l) => ({
      name: l.name,
      label: `${l.description}${l.currency ? ` (${l.currency})` : l.unit ? ` (${l.unit})` : ""}`,
      kind: "number" as const,
      hint: `Vazio: sem limite. 0: não incluído. Sem plano: ${l.default ?? "sem limite"}.`,
    })),
  ];
}

/** Valores do formulário → corpo da rota. */
function corpo(v: Valores, c: PlansCatalog) {
  return {
    name: String(v.name),
    description: String(v.description ?? ""),
    price: Number(v.price ?? 0),
    currency: moeda(String(v.currency)) ?? "BRL",
    public: v.public !== "false",
    default: v.default === "true",
    limits: Object.fromEntries(c.limits.map((l) => [l.name, v[l.name] === undefined || v[l.name] === "" ? null : Number(v[l.name])])),
    modules: Object.fromEntries(opcionais(c.modules).map((m) => [m.name, v[`modulo:${m.name}`] !== "false"])),
  };
}

/** Valores iniciais de um plano novo: os módulos como o default de cada um. */
function novos(c: PlansCatalog): Record<string, string> {
  return {
    currency: "BRL",
    public: "true",
    default: "false",
    price: "0",
    ...Object.fromEntries(opcionais(c.modules).map((m) => [`modulo:${m.name}`, String(m.default)])),
  };
}

function iniciais(plano: PlansPlan, c: PlansCatalog): Record<string, string> {
  const texto = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
  return {
    name: plano.name,
    description: plano.description,
    price: String(plano.price),
    currency: plano.currency,
    public: String(plano.public),
    default: String(plano.default),
    ...Object.fromEntries(c.limits.map((l) => [l.name, texto(l.name in plano.limits ? plano.limits[l.name] : l.default)])),
    ...Object.fromEntries(opcionais(c.modules).map((m) => [`modulo:${m.name}`, String(incluido(m, plano))])),
  };
}

const VAZIO: PlansCatalog = { modules: [], limits: [] };

function Gerenciar({ lista, catalogo }: { lista: QueryState<PlansPlanList>; catalogo: QueryState<PlansCatalog> }) {
  const [criando, setCriando] = useState(false);
  const [editando, setEditando] = useState<PlansPlan | null>(null);
  const [codigo, setCodigo] = useState("");
  const [conta, setConta] = useState<PlansAccount | null>(null);
  const c = catalogo.data ?? VAZIO;
  const atualizar = () => {
    lista.reload();
    refresh(plans.current);
    refresh(plans.modules); // o menu mostra ou esconde os módulos na hora
  };
  const criar = useAction((v: Valores) => plans.createPlan({ slug: String(v.slug), ...corpo(v, c) }), { onSuccess: atualizar });
  const salvar = useAction((v: Valores) => plans.updatePlan({ slug: editando?.slug ?? "", ...corpo(v, c) }), { onSuccess: atualizar });
  const remover = useAction(plans.removePlan, { onSuccess: atualizar });
  const abrir = useAction((tenant: string) => plans.account({ tenant }), { onSuccess: setConta });
  const atribuir = useAction(
    (v: Valores) =>
      plans.assign({
        tenant: conta?.tenant ?? "",
        plan: String(v.plan),
        modules: Object.fromEntries(
          opcionais(c.modules)
            .filter((m) => v[`modulo:${m.name}`] === "true" || v[`modulo:${m.name}`] === "false")
            .map((m) => [m.name, v[`modulo:${m.name}`] === "true"]),
        ),
      }),
    { onSuccess: atualizar },
  );

  return (
    <>
      <Row justify="between">
        <Text tone="muted">Planos valem para todas as organizações. Mudar um limite vale em até 1 minuto para todas nele.</Text>
        <Button onClick={() => setCriando(true)} disabled={!catalogo.data}>
          Novo plano
        </Button>
      </Row>
      {remover.error && <Alert tone="danger">{remover.error.message}</Alert>}
      <QueryView query={lista}>
        {(planos) => (
          <DataTable
            caption="Planos da plataforma"
            rows={planos.items}
            rowKey={(p) => p.slug}
            empty="Nenhum plano ainda: sem plano, valem os limites padrão que cada serviço declara."
            columns={[
              { key: "name", header: "Nome" },
              { key: "slug", header: "Identificador", render: (p) => <Code>{p.slug}</Code> },
              { key: "price", header: "Preço por mês", render: preco },
              {
                key: "flags",
                header: "",
                render: (p) => (
                  <Row gap="sm">
                    {p.default && <Badge tone="accent">Padrão</Badge>}
                    {!p.public && <Badge>Sob medida</Badge>}
                  </Row>
                ),
              },
              {
                key: "acoes",
                header: "",
                render: (p) => (
                  <Row gap="sm" wrap={false}>
                    <Button variant="ghost" size="sm" onClick={() => setEditando(p)}>
                      Editar
                    </Button>
                    <ConfirmButton confirmLabel="Remover o plano" loading={remover.running} onConfirm={() => void remover.run({ slug: p.slug })}>
                      Remover
                    </ConfirmButton>
                  </Row>
                ),
              },
            ]}
          />
        )}
      </QueryView>

      <Card title="Plano de uma organização" description="O código aparece para a organização na aba Uso desta tela.">
        {atribuir.result && (
          <Alert tone="success">
            {atribuir.result.tenant_name} está no plano {atribuir.result.plan_name}.
          </Alert>
        )}
        {abrir.error && <Alert tone="danger">{abrir.error.message}</Alert>}
        <Row align="end">
          <TextField label="Código da organização" value={codigo} onChange={setCodigo} />
          <Button onClick={() => void abrir.run(codigo.trim())} loading={abrir.running} disabled={!codigo.trim()}>
            Abrir
          </Button>
        </Row>
      </Card>

      <SidePanel open={criando} onClose={() => setCriando(false)} title="Novo plano" description="Os módulos e os limites vêm do que os serviços declaram.">
        <ActionForm action={criar} submitLabel="Criar plano" onDone={() => setCriando(false)} initial={novos(c)} fields={campos(c, true)} />
      </SidePanel>

      <SidePanel open={editando !== null} onClose={() => setEditando(null)} title={editando ? `Editar ${editando.name}` : "Editar plano"}>
        {editando && (
          <ActionForm key={editando.slug} action={salvar} submitLabel="Salvar" onDone={() => setEditando(null)} initial={iniciais(editando, c)} fields={campos(c, false)} />
        )}
      </SidePanel>

      <SidePanel
        open={conta !== null}
        onClose={() => setConta(null)}
        title={conta ? conta.tenant_name : "Organização"}
        description={conta ? (conta.assigned ? `No plano ${conta.plan_name}.` : `Sem plano atribuído: vale o padrão (${conta.plan_name}).`) : undefined}
      >
        {conta && (
          <ActionForm
            key={conta.tenant}
            action={atribuir}
            submitLabel="Salvar"
            onDone={() => setConta(null)}
            initial={{
              plan: conta.plan ?? "",
              ...Object.fromEntries(opcionais(c.modules).map((m) => [`modulo:${m.name}`, m.name in conta.modules ? String(conta.modules[m.name]) : "plano"])),
            }}
            fields={[
              { name: "plan", label: "Plano", kind: "select", required: true, options: (lista.data?.items ?? []).map((p) => ({ value: p.slug, label: p.name })) },
              ...opcionais(c.modules).map((m) => ({
                name: `modulo:${m.name}`,
                label: `Módulo ${m.title}`,
                kind: "select" as const,
                options: [
                  { value: "plano", label: "Como no plano" },
                  { value: "true", label: "Ligado para esta organização" },
                  { value: "false", label: "Desligado para esta organização" },
                ],
              })),
            ]}
          />
        )}
      </SidePanel>
    </>
  );
}
