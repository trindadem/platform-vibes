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
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { Quantity } from "@/components/Quantity";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { Stat } from "@/components/Stat";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { UsageMeter } from "@/components/UsageMeter";
import { type QueryState, refresh, useAction, useLiveQuery, useQuery } from "@/core/api";
import { type PlansCatalogLimit, type PlansCurrent, type PlansLimitList, type PlansPlan, type PlansPlanList, plans } from "@/core/contracts";

export const meta: PageMeta = { title: "Plano", order: 6 };

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

export default function Plano() {
  const atual = useLiveQuery("plans.uso", plans.current); // cada consumo ou total que muda atualiza a tela
  const lista = useQuery(plans.list);
  const catalogo = useQuery(plans.limits);
  const gere = lista.data?.manages_platform ?? false;
  return (
    <Page title="Plano" description="O que a sua organização pode usar e quanto já usou.">
      <Tabs
        tabs={[
          { id: "uso", label: "Uso", content: <Uso atual={atual} /> },
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

function Comparacao({ lista, catalogo }: { lista: QueryState<PlansPlanList>; catalogo: QueryState<PlansLimitList> }) {
  return (
    <QueryView query={lista}>
      {(planos) => (
        <QueryView query={catalogo}>
          {(limites) =>
            planos.items.length === 0 ? (
              <EmptyState title="Nenhum plano publicado" description="Enquanto não houver planos, valem os limites padrão da plataforma." />
            ) : (
              <DataTable
                caption="Comparação de planos"
                rowKey={(linha) => linha.id}
                rows={[
                  { id: "preco", rotulo: "Preço por mês", celula: (p: PlansPlan) => preco(p) },
                  ...limites.items.map((l) => ({ id: l.name, rotulo: l.description, celula: (p: PlansPlan) => permitido(l, p) })),
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

/** Campos do formulário de plano: os fixos e um por limite do catálogo (vazio: sem limite; 0: não incluído). */
function campos(limites: PlansCatalogLimit[], novo: boolean) {
  return [
    ...(novo ? [{ name: "slug", label: "Identificador", required: true, placeholder: "pro", hint: "Minúsculas e hífen; não muda depois." }] : []),
    { name: "name", label: "Nome", required: true, placeholder: "Pro" },
    { name: "description", label: "Descrição", placeholder: "Para equipes que crescem" },
    { name: "price", label: "Preço por mês", kind: "number" as const, hint: "Informativo: a cobrança é do produto." },
    { name: "currency", label: "Moeda", kind: "select" as const, required: true, options: MOEDAS.map((m) => ({ value: m, label: m })) },
    { name: "public", label: "Aparece na comparação", kind: "select" as const, required: true, options: [{ value: "true", label: "Sim" }, { value: "false", label: "Não (sob medida)" }] },
    { name: "default", label: "Plano padrão", kind: "select" as const, required: true, options: [{ value: "false", label: "Não" }, { value: "true", label: "Sim: vale para quem não tem plano" }] },
    ...limites.map((l) => ({
      name: l.name,
      label: `${l.description}${l.currency ? ` (${l.currency})` : l.unit ? ` (${l.unit})` : ""}`,
      kind: "number" as const,
      hint: `Vazio: sem limite. 0: não incluído. Sem plano: ${l.default ?? "sem limite"}.`,
    })),
  ];
}

/** Valores do formulário → corpo da rota. */
function corpo(v: Valores, limites: PlansCatalogLimit[]) {
  return {
    name: String(v.name),
    description: String(v.description ?? ""),
    price: Number(v.price ?? 0),
    currency: moeda(String(v.currency)) ?? "BRL",
    public: v.public !== "false",
    default: v.default === "true",
    limits: Object.fromEntries(limites.map((l) => [l.name, v[l.name] === undefined ? null : Number(v[l.name])])),
  };
}

function iniciais(plano: PlansPlan, limites: PlansCatalogLimit[]): Record<string, string> {
  const texto = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
  return {
    name: plano.name,
    description: plano.description,
    price: String(plano.price),
    currency: plano.currency,
    public: String(plano.public),
    default: String(plano.default),
    ...Object.fromEntries(limites.map((l) => [l.name, texto(l.name in plano.limits ? plano.limits[l.name] : l.default)])),
  };
}

function Gerenciar({ lista, catalogo }: { lista: QueryState<PlansPlanList>; catalogo: QueryState<PlansLimitList> }) {
  const [criando, setCriando] = useState(false);
  const [editando, setEditando] = useState<PlansPlan | null>(null);
  const limites = catalogo.data?.items ?? [];
  const atualizar = () => {
    lista.reload();
    refresh(plans.current);
  };
  const criar = useAction((v: Valores) => plans.createPlan({ slug: String(v.slug), ...corpo(v, limites) }), { onSuccess: atualizar });
  const salvar = useAction((v: Valores) => plans.updatePlan({ slug: editando?.slug ?? "", ...corpo(v, limites) }), { onSuccess: atualizar });
  const remover = useAction(plans.removePlan, { onSuccess: atualizar });
  const atribuir = useAction(plans.assign, { onSuccess: atualizar });

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

      <Card title="Atribuir plano a uma organização" description="O código aparece para a organização na aba Uso desta tela.">
        {atribuir.result && (
          <Alert tone="success">
            {atribuir.result.tenant_name} está no plano {atribuir.result.plan_name}.
          </Alert>
        )}
        <ActionForm
          action={atribuir}
          submitLabel="Atribuir"
          fields={[
            { name: "tenant", label: "Código da organização", required: true },
            { name: "plan", label: "Plano", kind: "select", required: true, options: (lista.data?.items ?? []).map((p) => ({ value: p.slug, label: p.name })) },
          ]}
        />
      </Card>

      <SidePanel open={criando} onClose={() => setCriando(false)} title="Novo plano" description="Os limites vêm do que os serviços declaram.">
        <ActionForm
          action={criar}
          submitLabel="Criar plano"
          onDone={() => setCriando(false)}
          initial={{ currency: "BRL", public: "true", default: "false", price: "0" }}
          fields={campos(limites, true)}
        />
      </SidePanel>

      <SidePanel open={editando !== null} onClose={() => setEditando(null)} title={editando ? `Editar ${editando.name}` : "Editar plano"}>
        {editando && (
          <ActionForm key={editando.slug} action={salvar} submitLabel="Salvar" onDone={() => setEditando(null)} initial={iniciais(editando, limites)} fields={campos(limites, false)} />
        )}
      </SidePanel>
    </>
  );
}
