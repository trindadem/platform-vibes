// Área do staff da Cogniventure: só compõe o catálogo (src/components/CATALOG.md, README §6). Fonte da verdade:
// specs/staff.md. A fila e a carteira ficam na organização da Cogniventure; para resolver, a pessoa entra na do cliente.
import { useState } from "react";
import { useNavigate } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DataTable } from "@/components/DataTable";
import { DateTime } from "@/components/DateTime";
import { EmptyState } from "@/components/EmptyState";
import { Grid } from "@/components/Grid";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SelectField } from "@/components/SelectField";
import { Stack } from "@/components/Stack";
import { Stat } from "@/components/Stat";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { Toggle } from "@/components/Toggle";
import { useAction, useLiveQuery, useQuery } from "@/core/api";
import { switchTenant, useSession } from "@/core/auth";
import { identity, type StaffItemFila, type StaffResumo, staff } from "@/core/contracts";

export const meta: PageMeta = { title: "Staff", module: "staff" };

const TIPOS = { excecao: "Exceção", revisao: "Revisão", ajuda: "Ajuda no desenho" };
const TONS = { excecao: "warning", revisao: "accent", ajuda: "accent" } as const;

export default function Staff() {
  const resumo = useLiveQuery("staff.fila", staff.resumo);
  return (
    <Page title="Staff" description="A sua carteira de clientes e o que espera por você em cada um: exceções, revisões e pedidos de ajuda.">
      <QueryView query={resumo}>
        {(r) =>
          r.staff ? (
            <Area resumo={r} />
          ) : (
            <EmptyState title="A área do staff é da equipe da Cogniventure" description="Entre na organização da Cogniventure pelo seletor de organização para ver a sua carteira." />
          )
        }
      </QueryView>
    </Page>
  );
}

function Area({ resumo }: { resumo: StaffResumo }) {
  return (
    <Stack>
      <Grid cols={4}>
        <Stat label="Exceções abertas" value={resumo.excecoes} hint={`${resumo.atrasadas} atrasada${resumo.atrasadas === 1 ? "" : "s"}`} tone={resumo.atrasadas ? "danger" : "default"} />
        <Stat label="Revisões" value={resumo.revisoes} hint="versões esperando aprovação" />
        <Stat label="Pedidos de ajuda" value={resumo.ajudas} hint="no desenho dos processos" />
        <Stat label={resumo.gestor ? "Escaladas" : "Clientes"} value={resumo.gestor ? resumo.escaladas : resumo.organizacoes} hint={resumo.gestor ? "passaram do prazo sem dono" : "na sua carteira"} tone={resumo.gestor && resumo.escaladas ? "danger" : "default"} />
      </Grid>
      <Tabs
        tabs={[
          { id: "fila", label: "Fila", content: <Fila gestor={resumo.gestor} /> },
          { id: "carteira", label: "Carteira", content: <Carteira /> },
          ...(resumo.gestor ? [{ id: "gestao", label: "Gestão das carteiras", content: <Gestao /> }] : []),
        ]}
      />
    </Stack>
  );
}

/** Entra na organização do cliente e abre a tela onde resolver. */
function useEntrar() {
  const navigate = useNavigate();
  return useAction(async (organizacao: string, link: string) => {
    await switchTenant(organizacao);
    navigate(link);
  });
}

function Fila({ gestor }: { gestor: boolean }) {
  const [todas, setTodas] = useState(false);
  const [escaladas, setEscaladas] = useState(false);
  const filtro = { status: "aberta" as const, size: 50, todas: gestor && todas ? true : null, escalada: escaladas ? true : null };
  const fila = useLiveQuery("staff.fila", staff.fila, filtro);
  const membros = useQuery(identity.members);
  const pessoas = (membros.data?.items ?? []).map((m) => ({ value: m.id, label: `${m.name} (${m.email})` }));
  const nome = (id: string | null | undefined) => membros.data?.items.find((m) => m.id === id)?.name ?? "alguém do staff";
  return (
    <Stack>
      {gestor && (
        <Row>
          <Toggle label="Todas as carteiras" checked={todas} onChange={setTodas} />
          <Toggle label="Só as escaladas" checked={escaladas} onChange={setEscaladas} />
        </Row>
      )}
      <QueryView query={fila}>
        {(pagina) =>
          pagina.items.length ? (
            <Stack>
              {pagina.items.map((item) => (
                <ItemDaFila key={item.id} item={item} gestor={gestor} pessoas={pessoas} nome={nome} onDone={fila.reload} />
              ))}
            </Stack>
          ) : (
            <EmptyState title="Nada esperando por você" description="Quando um cliente da sua carteira precisar do staff, o item aparece aqui pelo prazo." />
          )
        }
      </QueryView>
    </Stack>
  );
}

function ItemDaFila({ item, gestor, pessoas, nome, onDone }: {
  item: StaffItemFila;
  gestor: boolean;
  pessoas: { value: string; label: string }[];
  nome: (id: string | null | undefined) => string;
  onDone: () => void;
}) {
  const session = useSession();
  const [para, setPara] = useState("");
  const entrar = useEntrar();
  const assumir = useAction(staff.assumir, { onSuccess: onDone });
  const atribuir = useAction(staff.atribuir, { onSuccess: () => { setPara(""); onDone(); } });
  const atrasada = item.prazo ? new Date(item.prazo).getTime() < Date.now() : false;
  const minha = item.assumida_por === session?.user.id;
  const falha = entrar.error ?? assumir.error ?? atribuir.error;
  return (
    <Card
      title={item.titulo}
      description={`${item.organizacao_nome}${item.detalhe ? ` · ${item.detalhe}` : ""}`}
      footer={
        <Row justify="between">
          <Row gap="sm">
            <StatusBadge value={item.tipo} labels={TIPOS} tones={TONS} />
            {item.escalada && <Badge tone="danger">Escalada</Badge>}
            {item.prazo && (
              <Text size="sm" tone={atrasada ? "danger" : "muted"}>
                {atrasada ? "Atrasada desde " : "Prazo: "}
                <DateTime value={item.prazo} />
              </Text>
            )}
            {item.assumida_por && <Text size="sm" tone="muted">Com {minha ? "você" : nome(item.assumida_por)}</Text>}
          </Row>
          <Row gap="sm">
            {!minha && (
              <Button size="sm" variant="secondary" loading={assumir.running} onClick={() => void assumir.run({ id: item.id })}>
                Assumir
              </Button>
            )}
            <Button size="sm" loading={entrar.running} onClick={() => void entrar.run(item.organizacao, item.link)}>
              Abrir no cliente
            </Button>
          </Row>
        </Row>
      }
    >
      {falha && <Alert tone="danger">{falha.message}</Alert>}
      {gestor && (
        <Row align="end">
          <SelectField label="Passar para" value={para} onChange={setPara} options={pessoas} placeholder="Escolha alguém do staff" />
          <Button size="sm" variant="secondary" disabled={!para} loading={atribuir.running} onClick={() => void atribuir.run({ id: item.id, pessoa: para })}>
            Passar
          </Button>
        </Row>
      )}
    </Card>
  );
}

function Carteira() {
  const carteira = useLiveQuery("staff.carteiras", staff.carteira);
  const entrar = useEntrar();
  return (
    <Stack>
      {entrar.error && <Alert tone="danger">{entrar.error.message}</Alert>}
      <QueryView query={carteira}>
        {(c) =>
          c.itens.length ? (
            <Grid cols={2}>
              {c.itens.map((s) => (
                <Card
                  key={s.organizacao}
                  title={s.nome}
                  footer={
                    <Row justify="between">
                      <Row gap="sm">
                        {s.excecoes > 0 && <Badge tone="warning">{s.excecoes} exceç{s.excecoes === 1 ? "ão" : "ões"}</Badge>}
                        {s.revisoes > 0 && <Badge tone="accent">{s.revisoes} revis{s.revisoes === 1 ? "ão" : "ões"}</Badge>}
                        {s.ajudas > 0 && <Badge tone="accent">{s.ajudas} ajuda{s.ajudas === 1 ? "" : "s"}</Badge>}
                      </Row>
                      <Button size="sm" variant="secondary" loading={entrar.running} onClick={() => void entrar.run(s.organizacao, "/workspace")}>
                        Entrar
                      </Button>
                    </Row>
                  }
                >
                  {s.disponivel ? (
                    <KeyValue
                      items={[
                        { label: "Em andamento", value: s.andamento ?? 0 },
                        { label: "Concluídas", value: s.concluidas ?? 0 },
                        { label: "Incidentes", value: s.incidentes ?? 0 },
                        { label: "Autonomia", value: s.autonomia === null ? "—" : `${Math.round(s.autonomia * 100)}%` },
                      ]}
                    />
                  ) : (
                    <Text size="sm" tone="muted">Os números deste cliente não responderam agora.</Text>
                  )}
                </Card>
              ))}
            </Grid>
          ) : (
            <EmptyState title="Nenhum cliente na sua carteira" description="O gestor da carteira (dono ou admin da Cogniventure) adiciona os clientes de que você cuida." />
          )
        }
      </QueryView>
    </Stack>
  );
}

function Gestao() {
  const carteiras = useLiveQuery("staff.carteiras", staff.carteiras);
  const organizacoes = useQuery(staff.organizacoes);
  const membros = useQuery(identity.members);
  const [pessoa, setPessoa] = useState("");
  const [organizacao, setOrganizacao] = useState("");
  const atribuir = useAction(staff.atribuirCarteira, { onSuccess: () => { setOrganizacao(""); carteiras.reload(); } });
  const remover = useAction(staff.removerCarteira, { onSuccess: carteiras.reload });
  const pessoas = (membros.data?.items ?? []).map((m) => ({ value: m.id, label: `${m.name} (${m.email})` }));
  const nome = (id: string) => membros.data?.items.find((m) => m.id === id)?.name ?? id;
  const falha = atribuir.error ?? remover.error;
  return (
    <Stack>
      <Card title="Adicionar à carteira" description="A pessoa passa a cuidar do cliente: ganha o papel operador na organização dele (e perde ao sair da carteira).">
        <Row align="end">
          <SelectField label="Pessoa do staff" value={pessoa} onChange={setPessoa} options={pessoas} />
          <SelectField label="Cliente" value={organizacao} onChange={setOrganizacao} options={(organizacoes.data?.items ?? []).map((o) => ({ value: o.id, label: o.name }))} />
          <Button disabled={!pessoa || !organizacao} loading={atribuir.running} onClick={() => void atribuir.run({ pessoa, organizacao })}>
            Adicionar
          </Button>
        </Row>
        {falha && <Alert tone="danger">{falha.message}</Alert>}
      </Card>
      <QueryView query={carteiras}>
        {(c) => (
          <DataTable
            rows={c.itens}
            rowKey={(r) => r.id}
            caption="Carteiras do staff"
            empty="Nenhum cliente em carteira ainda."
            columns={[
              { key: "pessoa", header: "Pessoa", render: (r) => nome(r.pessoa) },
              { key: "organizacao_nome", header: "Cliente" },
              { key: "created_at", header: "Desde", render: (r) => (r.created_at ? <DateTime value={r.created_at} format="date" /> : "") },
              {
                key: "remover",
                header: "",
                render: (r) => (
                  <ConfirmButton size="sm" confirmLabel="Tirar da carteira" loading={remover.running} onConfirm={() => void remover.run({ id: r.id })}>
                    Tirar
                  </ConfirmButton>
                ),
              },
            ]}
          />
        )}
      </QueryView>
    </Stack>
  );
}
