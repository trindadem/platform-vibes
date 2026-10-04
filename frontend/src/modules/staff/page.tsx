// Área do staff da Cogniventure: só compõe o catálogo (src/components/CATALOG.md, README §6). Fonte da verdade:
// specs/staff.md. A fila e a carteira ficam na organização da Cogniventure; exceção, revisão e pedido de ajuda se
// resolvem no próprio cartão, sem trocar de organização (a conversa de desenho abre no cliente).
import { useState } from "react";
import { useNavigate } from "react-router";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ChatThread } from "@/components/ChatThread";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DataTable } from "@/components/DataTable";
import { DateTime } from "@/components/DateTime";
import { EmptyState } from "@/components/EmptyState";
import { Grid } from "@/components/Grid";
import { KeyValue } from "@/components/KeyValue";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { ProcessResults } from "@/components/ProcessResults";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SelectField } from "@/components/SelectField";
import { SidePanel } from "@/components/SidePanel";
import { Stack } from "@/components/Stack";
import { Stat } from "@/components/Stat";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextArea } from "@/components/TextArea";
import { Toggle } from "@/components/Toggle";
import { useAction, useLiveQuery, useQuery } from "@/core/api";
import { switchTenant, useSession } from "@/core/auth";
import { identity, plans, type StaffCliente, type StaffItemFila, type StaffResumo, staff } from "@/core/contracts";

export const meta: PageMeta = { title: "Staff", module: "staff" };

const TIPOS = { excecao: "Exceção", revisao: "Revisão", ajuda: "Ajuda no desenho", pedido: "Pedido de ajuda" };
const TONS = { excecao: "warning", revisao: "accent", ajuda: "accent", pedido: "accent" } as const;
const PERIODOS = [
  { value: "7", label: "Últimos 7 dias" },
  { value: "30", label: "Últimos 30 dias" },
  { value: "90", label: "Últimos 90 dias" },
];

/** Minutos em texto curto: 45 min, 3 h 10 min. */
const duracao = (min: number | null) =>
  min === null ? "—" : min < 1 ? "menos de 1 min" : min < 60 ? `${Math.round(min)} min` : `${Math.floor(min / 60)} h ${Math.round(min % 60)} min`;
const PASSOS = { convite: "Convite pendente", briefing: "Briefing", descoberta: "Descoberta", desenho: "Desenho", acompanhamento: "Acompanhamento" };
const TONS_PASSO = { convite: "warning", briefing: "neutral", descoberta: "neutral", desenho: "accent", acompanhamento: "success" } as const;
const SITUACAO = { ativa: "Ativa", suspensa: "Suspensa", encerrada: "Encerrada" };
const TONS_SITUACAO = { ativa: "success", suspensa: "warning", encerrada: "danger" } as const;

/** A situação da conta numa palavra, com o encerramento marcado (no fim do mês pago). */
function situacao(c: StaffCliente) {
  if (!c.conta) return "—";
  return (
    <Stack gap="sm">
      <StatusBadge value={c.conta.situacao} labels={SITUACAO} tones={TONS_SITUACAO} />
      {c.conta.cancelamento && c.conta.situacao !== "encerrada" && (
        <Text size="sm" tone="muted">Encerra em <DateTime value={c.conta.cancelamento.efetivo_em} format="date" /></Text>
      )}
    </Stack>
  );
}

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
        <Stat label="Pedidos de ajuda" value={resumo.pedidos + resumo.ajudas} hint={`${resumo.ajudas} no desenho dos processos`} />
        <Stat label={resumo.gestor ? "Escaladas" : "Clientes"} value={resumo.gestor ? resumo.escaladas : resumo.organizacoes} hint={resumo.gestor ? "passaram do prazo sem dono" : "na sua carteira"} tone={resumo.gestor && resumo.escaladas ? "danger" : "default"} />
      </Grid>
      <Tabs
        tabs={[
          { id: "fila", label: "Fila", content: <Fila gestor={resumo.gestor} /> },
          { id: "carteira", label: "Carteira", content: <Carteira /> },
          ...(resumo.gestor
            ? [
                { id: "clientes", label: "Clientes", content: <Clientes /> },
                { id: "numeros", label: "Números", content: <NumerosDoStaff /> },
                { id: "gestao", label: "Gestão das carteiras", content: <Gestao /> },
              ]
            : []),
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
  const [resolvendo, setResolvendo] = useState(false);
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
            {item.tipo === "ajuda" ? (
              <Button size="sm" loading={entrar.running} onClick={() => void entrar.run(item.organizacao, item.link)}>
                Abrir no cliente
              </Button>
            ) : (
              <>
                <Button size="sm" variant="secondary" loading={entrar.running} onClick={() => void entrar.run(item.organizacao, item.link)}>
                  Abrir no cliente
                </Button>
                <Button size="sm" onClick={() => setResolvendo(!resolvendo)}>
                  {resolvendo ? "Fechar" : "Resolver aqui"}
                </Button>
              </>
            )}
          </Row>
        </Row>
      }
    >
      {falha && <Alert tone="danger">{falha.message}</Alert>}
      {resolvendo && <Resolucao item={item} onDone={onDone} />}
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

/** Resolver no cartão: o serviço do item responde pela organização do cliente, com quem do staff resolveu. */
function Resolucao({ item, onDone }: { item: StaffItemFila; onDone: () => void }) {
  const detalhe = useQuery(staff.detalhe, { id: item.id });
  const [comentario, setComentario] = useState("");
  const [regra, setRegra] = useState("");
  const [motivo, setMotivo] = useState("");
  const resolver = useAction(staff.resolver, { onSuccess: onDone });
  const decidir = useAction(staff.decidir, { onSuccess: onDone });
  const responder = useAction(staff.responder, { onSuccess: onDone });
  return (
    <QueryView query={detalhe}>
      {(d) => {
        if (d.tarefa) {
          const t = d.tarefa;
          const enviar = {
            ...resolver,
            run: (dados: Record<string, string | number | boolean | null>) =>
              resolver.run({ id: item.id, dados, comentario: comentario || null, regra: regra || null }),
          };
          return (
            <Stack>
              {t.motivo && <Alert tone="warning" title="Por que parou">{t.motivo}</Alert>}
              {t.contexto.length > 0 && <KeyValue items={t.contexto.map((i) => ({ label: i.rotulo, value: i.valor }))} />}
              <TextArea label="O que você fez (opcional)" value={comentario} onChange={setComentario} rows={2} />
              {t.aprende && (
                <TextArea
                  label="Ensinar ao agente (opcional)"
                  value={regra}
                  onChange={setRegra}
                  rows={2}
                  hint="Vira regra do passo: o agente refaz este caso com ela e, se chegar ao que você preencheu, passa a segui-la."
                />
              )}
              {t.campos.some((c) => c.tipo === "documento") && (
                <Alert tone="info" title="Esta exceção pede um arquivo">
                  {t.campos.filter((c) => c.tipo === "documento").map((c) => c.rotulo).join(", ")}: para anexar, resolva pela tela de tarefas do cliente
                  (o arquivo fica com ele). Sem o arquivo, o processo segue sem o anexo.
                </Alert>
              )}
              <ActionForm
                action={enviar}
                submitLabel="Resolver e seguir o processo"
                initial={Object.fromEntries(t.campos.filter((c) => c.tipo !== "documento").map((c) => [c.nome, c.valor === null || c.valor === undefined ? "" : String(c.valor)]))}
                fields={t.campos
                  .filter((c) => c.tipo !== "documento")
                  .map((c) => ({ name: c.nome, label: c.rotulo, kind: c.tipo === "numero" ? "number" : c.tipo === "sim_nao" ? "boolean" : "text" }))}
              />
            </Stack>
          );
        }
        if (d.revisao) {
          const r = d.revisao;
          return (
            <Stack>
              <Text>Versão {r.numero} de {r.titulo}. O que muda em relação à publicada:</Text>
              {r.mudancas.length ? (
                <KeyValue items={r.mudancas.map((m, i) => ({ label: `${i + 1}.`, value: m }))} />
              ) : (
                <Text size="sm" tone="muted">Nenhuma mudança listada.</Text>
              )}
              {decidir.error && <Alert tone="danger">{decidir.error.message}</Alert>}
              <Row>
                <Button loading={decidir.running} onClick={() => void decidir.run({ id: item.id, aprovar: true })}>
                  Aprovar e publicar
                </Button>
              </Row>
              <TextArea label="Para devolver: o que precisa mudar" value={motivo} onChange={setMotivo} rows={2} />
              <Row>
                <Button variant="secondary" disabled={motivo.trim().length < 3} loading={decidir.running} onClick={() => void decidir.run({ id: item.id, aprovar: false, motivo })}>
                  Devolver para a empresa
                </Button>
              </Row>
            </Stack>
          );
        }
        if (d.pedido) {
          return (
            <ChatThread
              messages={d.pedido.mensagens.map((m, i) => ({
                id: String(i),
                role: m.papel === "staff" ? "assistant" : "user",
                author: m.papel === "staff" ? `Cogniventure · ${m.autor_nome ?? "staff"}` : (m.autor_nome ?? undefined),
                text: m.texto,
              }))}
              onSend={(texto) => void responder.run({ id: item.id, texto })}
              sending={responder.running}
              error={responder.error?.message}
              assistant="Staff da Cogniventure"
              placeholder="Responder ao cliente"
            />
          );
        }
        return <Text tone="muted">Este item se resolve na tela do cliente.</Text>;
      }}
    </QueryView>
  );
}

/** Para o gestor equilibrar as carteiras: por pessoa e por cliente, resolvidos, no prazo e tempo médio. */
function NumerosDoStaff() {
  const [dias, setDias] = useState("30");
  const numeros = useLiveQuery("staff.fila", staff.numeros, { dias: Number(dias) });
  const membros = useQuery(identity.members);
  const nome = (id: string) => membros.data?.items.find((m) => m.id === id)?.name ?? "alguém do staff";
  const prazo = (r: { resolvidos: number; no_prazo: number }) => (r.resolvidos ? `${Math.round((100 * r.no_prazo) / r.resolvidos)}%` : "—");
  return (
    <Stack>
      <Row>
        <SelectField label="Período" value={dias} onChange={setDias} options={PERIODOS} />
      </Row>
      <QueryView query={numeros}>
        {(n) => (
          <Stack>
            <DataTable
              rows={n.pessoas}
              rowKey={(r) => r.chave}
              caption="Por pessoa do staff"
              empty="Ninguém resolveu nada no período."
              columns={[
                { key: "chave", header: "Pessoa", render: (r) => nome(r.chave) },
                { key: "resolvidos", header: "Resolvidos" },
                { key: "no_prazo", header: "No prazo", render: prazo },
                { key: "tempo_medio_min", header: "Tempo médio", render: (r) => duracao(r.tempo_medio_min ?? null) },
              ]}
            />
            <DataTable
              rows={n.clientes}
              rowKey={(r) => r.chave}
              caption="Por cliente"
              empty="Nenhum item no período."
              columns={[
                { key: "nome", header: "Cliente", render: (r) => r.nome ?? r.chave },
                { key: "abertos", header: "Abertos agora" },
                { key: "resolvidos", header: "Resolvidos" },
                { key: "no_prazo", header: "No prazo", render: prazo },
                { key: "tempo_medio_min", header: "Tempo médio", render: (r) => duracao(r.tempo_medio_min ?? null) },
              ]}
            />
          </Stack>
        )}
      </QueryView>
    </Stack>
  );
}

function Carteira() {
  const carteira = useLiveQuery("staff.carteiras", staff.carteira);
  const entrar = useEntrar();
  const [resultados, setResultados] = useState<{ organizacao: string; nome: string } | null>(null);
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
                        {s.pedidos > 0 && <Badge tone="accent">{s.pedidos} pedido{s.pedidos === 1 ? "" : "s"}</Badge>}
                      </Row>
                      <Row gap="sm">
                        <Button size="sm" variant="ghost" onClick={() => setResultados({ organizacao: s.organizacao, nome: s.nome })}>
                          Resultados
                        </Button>
                        <Button size="sm" variant="secondary" loading={entrar.running} onClick={() => void entrar.run(s.organizacao, "/workspace")}>
                          Entrar
                        </Button>
                      </Row>
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
      <SidePanel
        open={resultados !== null}
        onClose={() => setResultados(null)}
        title={`Resultados: ${resultados?.nome ?? ""}`}
        description="Os mesmos números que o cliente vê na tela Resultados, no mês atual."
      >
        {resultados && <ResultadosDoCliente organizacao={resultados.organizacao} />}
      </SidePanel>
    </Stack>
  );
}

function ResultadosDoCliente({ organizacao }: { organizacao: string }) {
  const resultados = useQuery(staff.resultadosCliente, { organizacao });
  return (
    <QueryView query={resultados}>
      {(r) => (
        <Stack>
          <KeyValue
            items={[
              { label: "Concluídas no mês", value: r.concluidas },
              { label: "Rodaram sozinhas", value: r.autonomia === null ? "—" : `${Math.round(r.autonomia * 100)}%` },
            ]}
          />
          <ProcessResults processes={r.processos} empty="Este cliente ainda não tem processo publicado." />
        </Stack>
      )}
    </QueryView>
  );
}

/** O gestor abre clientes (organização, convite do dono, plano e carteira) e acompanha cada um pela jornada. */
function Clientes() {
  const clientes = useLiveQuery("staff.carteiras", staff.clientes);
  const planos = useQuery(plans.list);
  const membros = useQuery(identity.members);
  const [abrindo, setAbrindo] = useState(false);
  const [conta, setConta] = useState<string | null>(null);
  const novo = useAction(staff.novoCliente, { onSuccess: clientes.reload });
  const convidar = useAction(staff.convidarDono, { onSuccess: clientes.reload });
  const nome = (id: string) => membros.data?.items.find((m) => m.id === id)?.name ?? "alguém do staff";
  const dono = (c: StaffCliente) =>
    c.dono ? (
      `${c.dono.name} (${c.dono.email})`
    ) : c.convite ? (
      <Row gap="sm">
        <Text size="sm" tone="muted">Convite para {c.convite.email ?? "o dono"}, vale até <DateTime value={c.convite.expires_at} format="date" /></Text>
        <Button size="sm" variant="secondary" loading={convidar.running} onClick={() => void convidar.run({ organizacao: c.organizacao })}>
          Reenviar
        </Button>
      </Row>
    ) : (
      <Button size="sm" variant="secondary" loading={convidar.running} onClick={() => void convidar.run({ organizacao: c.organizacao })}>
        Convidar de novo
      </Button>
    );
  return (
    <Stack>
      <Row justify="between">
        <Text tone="muted">Cada cliente nasce aqui: a organização dele, o plano, quem do staff cuida e o convite do dono por e-mail.</Text>
        <Button onClick={() => setAbrindo(true)}>Novo cliente</Button>
      </Row>
      {convidar.error && <Alert tone="danger">{convidar.error.message}</Alert>}
      <QueryView query={clientes}>
        {(c) => (
          <DataTable
            rows={c.itens}
            rowKey={(r) => r.organizacao}
            caption="Clientes da Cogniventure"
            empty="Nenhum cliente ainda: abra o primeiro em Novo cliente."
            columns={[
              { key: "nome", header: "Cliente" },
              { key: "plano", header: "Plano", render: (r) => r.plano ?? "Sem plano" },
              { key: "responsaveis", header: "Com quem", render: (r) => (r.responsaveis.length ? r.responsaveis.map(nome).join(", ") : "Ninguém") },
              { key: "passo", header: "Jornada", render: (r) => (r.passo ? <StatusBadge value={r.passo} labels={PASSOS} tones={TONS_PASSO} /> : "—") },
              { key: "ultimo_acesso", header: "Último acesso", render: (r) => (r.ultimo_acesso ? <DateTime value={r.ultimo_acesso} format="relative" /> : "Nunca") },
              { key: "dono", header: "Dono", render: dono },
              { key: "conta", header: "Mensalidade", render: (r) => (r.conta ? <Text size="sm">{r.conta.valor ? <Money value={r.conta.valor} currency="BRL" /> : "Sem cobrança"} · dia {r.conta.vencimento}</Text> : "—") },
              { key: "situacao", header: "Conta", render: situacao },
              { key: "acoes", header: "", render: (r) => <Button size="sm" variant="ghost" onClick={() => setConta(r.organizacao)}>Conta</Button> },
            ]}
          />
        )}
      </QueryView>
      <SidePanel open={conta !== null} onClose={() => setConta(null)} title="Conta do cliente"
        description="A mensalidade e o vencimento que o fechamento do mês cobra; suspender o cliente em atraso; encerrar a conta.">
        {conta && clientes.data && <ContaDoCliente cliente={clientes.data.itens.find((c) => c.organizacao === conta)} onChange={clientes.reload} />}
      </SidePanel>
      <SidePanel open={abrindo} onClose={() => setAbrindo(false)} title="Novo cliente" description="A organização nasce sem ninguém da Cogniventure dentro; o dono recebe o convite por e-mail e quem cuida dele ganha o papel operador.">
        {abrindo && (
          <ActionForm
            action={novo}
            submitLabel="Abrir o cliente"
            onDone={() => setAbrindo(false)}
            fields={[
              { name: "empresa", label: "Empresa", required: true },
              { name: "email", label: "E-mail do dono", kind: "email", required: true, hint: "Recebe o convite para criar a senha e começar pelo briefing." },
              { name: "plano", label: "Plano", kind: "select", required: true, options: (planos.data?.items ?? []).map((p) => ({ value: p.slug, label: p.name })) },
              { name: "pessoa", label: "Quem do staff cuida", kind: "select", required: true, options: (membros.data?.items ?? []).map((m) => ({ value: m.id, label: `${m.name} (${m.email})` })) },
              { name: "valor", label: "Mensalidade combinada (R$)", kind: "number", hint: "Vazio: o preço do plano." },
              { name: "vencimento", label: "Dia do vencimento", kind: "number", hint: "De 1 a 28 (vazio: dia 10)." },
            ]}
          />
        )}
      </SidePanel>
    </Stack>
  );
}

/** A conta de um cliente: o que o fechamento cobra, suspender e reativar, encerrar e desfazer. */
function ContaDoCliente({ cliente, onChange }: { cliente: StaffCliente | undefined; onChange: () => void }) {
  const organizacao = cliente?.organizacao ?? "";
  const cobranca = useAction((v: { valor?: number | null; vencimento?: number | null }) => staff.cobranca({ organizacao, ...v }), { onSuccess: onChange });
  const suspender = useAction((v: { motivo: string }) => staff.situacaoCliente({ organizacao, acao: "suspender", motivo: v.motivo }), { onSuccess: onChange });
  const encerrar = useAction((v: { motivo?: string | null }) => staff.situacaoCliente({ organizacao, acao: "encerrar", motivo: v.motivo ?? null }), { onSuccess: onChange });
  const mudar = useAction((acao: "reativar" | "desfazer") => staff.situacaoCliente({ organizacao, acao }), { onSuccess: onChange });
  const c = cliente?.conta;
  if (!cliente || !c) return <Alert tone="warning">A conta deste cliente não respondeu agora. Tente de novo em instantes.</Alert>;
  return (
    <Stack>
      <KeyValue items={[
        { label: "Cliente", value: cliente.nome },
        { label: "Situação", value: situacao(cliente) },
        ...(c.motivo ? [{ label: "Motivo da suspensão", value: c.motivo }] : []),
        ...(c.cancelamento ? [{ label: "Encerramento", value: `${c.cancelamento.origem === "cliente" ? "Pedido pelo cliente" : "Pela Cogniventure"}${c.cancelamento.motivo ? `: ${c.cancelamento.motivo}` : ""}` }] : []),
        ...(c.exclusao_em ? [{ label: "Os dados saem de vez em", value: <DateTime value={c.exclusao_em} format="date" /> }] : []),
      ]} />
      {mudar.error && <Alert tone="danger">{mudar.error.message}</Alert>}
      <Card title="Cobrança" description="O fechamento do dia 1 inicia o Faturamento e cobrança na organização da Cogniventure com este valor e este vencimento.">
        <ActionForm
          action={cobranca}
          submitLabel="Salvar"
          successMessage="Cobrança atualizada."
          initial={{ valor: String(c.valor), vencimento: String(c.vencimento) }}
          fields={[
            { name: "valor", label: "Mensalidade (R$)", kind: "number", required: true },
            { name: "vencimento", label: "Dia do vencimento", kind: "number", required: true, hint: "De 1 a 28." },
          ]}
        />
      </Card>
      {c.situacao === "ativa" && (
        <Card title="Suspender" description="Para o cliente em atraso: nenhuma execução nova começa (as em andamento terminam) e ele vê o aviso no workspace.">
          <ActionForm action={suspender} submitLabel="Suspender" fields={[{ name: "motivo", label: "Motivo (o cliente vê)", kind: "textarea", required: true }]} />
        </Card>
      )}
      {c.situacao === "suspensa" && (
        <Row>
          <Button loading={mudar.running} onClick={() => void mudar.run("reativar")}>Reativar (o pagamento entrou)</Button>
        </Row>
      )}
      {(c.cancelamento || c.situacao === "encerrada") ? (
        <Row>
          <Button variant="secondary" loading={mudar.running} onClick={() => void mudar.run("desfazer")}>
            {c.situacao === "encerrada" ? "Reativar a conta encerrada" : "Desfazer o encerramento"}
          </Button>
        </Row>
      ) : (
        <Card title="Encerrar a conta" description={c.situacao === "suspensa"
          ? "Suspenso por atraso: encerra na hora. Os dados ficam 30 dias para o cliente baixar e depois saem de vez."
          : "Encerra no fim do mês pago. Depois, os dados ficam 30 dias para o cliente baixar e saem de vez."}>
          <ActionForm action={encerrar} submitLabel="Encerrar a conta" fields={[{ name: "motivo", label: "Motivo", kind: "textarea" }]} />
        </Card>
      )}
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
