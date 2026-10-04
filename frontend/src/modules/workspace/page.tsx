import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Grid } from "@/components/Grid";
import { Heading } from "@/components/Heading";
import { type JourneyStep, JourneySteps } from "@/components/JourneySteps";
import { Page } from "@/components/Page";
import { ProjectChain, type ProjectChainStep } from "@/components/ProjectChain";
import { Quantity } from "@/components/Quantity";
import { Spinner } from "@/components/Spinner";
import { Stack } from "@/components/Stack";
import { Stat } from "@/components/Stat";
import { Text } from "@/components/Text";
import { useLive, useLiveQuery } from "@/core/api";
import { useSession } from "@/core/auth";
import {
  type ConhecimentoResumo,
  conhecimento,
  type ProcessosAcompanhamento,
  type ProcessosEtapaProjeto,
  type ProcessosResumo,
  processos,
} from "@/core/contracts";

export const meta: PageMeta = { title: "Workspace", order: 0 };

const FONTES: Record<string, string> = { briefing: "do briefing", site: "do site", documento: "de documentos", manual: "manuais" };

/** A jornada do cliente (briefing.md §3): cada passo aparece aqui conforme os blocos chegam. */
function passos(r: ConhecimentoResumo | null, p: ProcessosResumo | null, a: ProcessosAcompanhamento | null): JourneyStep[] {
  const feito = Boolean(r?.concluido_em);
  const comecou = (r?.topicos_feitos ?? 0) > 0;
  const aceitos = p?.aceitos ?? 0;
  return [
    {
      title: "Briefing",
      description: "Uma conversa com o agente sobre como a empresa funciona: negócio, clientes, financeiro, sistemas, equipe e objetivos.",
      status: feito ? "done" : "current",
      detail: r ? `${r.topicos_feitos} de ${r.topicos_total} tópicos${feito ? " · concluído" : ""}` : undefined,
      to: "/briefing",
      action: feito ? "Revisar" : comecou ? "Continuar" : "Começar",
    },
    {
      title: "Conhecimento",
      description: "O site, os documentos e o que você contou viram a base que os agentes consultam. Você vê, corrige e apaga.",
      status: feito ? ((r?.itens ?? 0) > 0 ? "done" : "current") : "todo",
      detail: r
        ? [`${r.itens} ${r.itens === 1 ? "item" : "itens"}`, ...Object.entries(r.por_fonte).map(([fonte, n]) => `${n} ${FONTES[fonte] ?? fonte}`), r.leituras_lendo ? `${r.leituras_lendo} lendo agora` : ""]
            .filter(Boolean)
            .join(" · ")
        : undefined,
      to: "/conhecimento",
      action: "Abrir",
    },
    {
      title: "Descoberta de processos",
      description: "A partir do briefing, sugerimos os processos que podemos executar para você, e você descreve os seus.",
      status: !feito ? "todo" : aceitos > 0 ? "done" : "current",
      detail: p ? `${p.sugeridos} sugeridos · ${aceitos} aceitos${p.recusados ? ` · ${p.recusados} recusados` : ""}` : undefined,
      to: "/processos",
      action: p?.sugeridos ? "Ver sugestões" : aceitos ? "Abrir" : "Descobrir",
    },
    {
      title: "Desenho dos processos",
      description: "Cada processo aceito é desenhado numa conversa, com o fluxo aparecendo ao lado, e publicado no motor.",
      status: aceitos === 0 ? "todo" : (p?.publicados ?? 0) > 0 ? "done" : "current",
      detail: p && aceitos ? `${p.publicados} de ${aceitos} publicados` : undefined,
      to: "/processos#aceitos",
      action: "Desenhar",
    },
    {
      title: "Acompanhamento",
      description: "Os processos rodando, o que espera por você e quanto cada um roda sozinho.",
      status: (p?.publicados ?? 0) === 0 ? "todo" : "current",
      detail: a
        ? [
            `${a.andamento} em andamento`,
            `${a.concluidas} concluídas`,
            a.tarefas_cliente ? `${a.tarefas_cliente} esperando você` : "",
            a.atrasadas ? `${a.atrasadas} atrasadas` : "",
            a.autonomia !== null ? `${Math.round(a.autonomia * 100)}% sozinhas` : "",
          ]
            .filter(Boolean)
            .join(" · ")
        : undefined,
      to: a?.tarefas_cliente ? "/processos/tarefas" : "/processos/execucoes",
      action: a?.tarefas_cliente ? "Ver tarefas" : "Acompanhar",
    },
  ];
}

const ESPERA = { cliente: "Esperando você", staff: "Com o staff", evento: "Aguardando" };

/** As execuções de um projeto como etapas da cadeia: quem iniciou quem, onde cada uma está ou como terminou. */
function etapas(itens: ProcessosEtapaProjeto[]): ProjectChainStep[] {
  const nivel: Record<string, number> = {};
  return itens.map((e) => {
    nivel[e.id] = e.pai ? (nivel[e.pai] ?? 0) + 1 : 0;
    const onde = e.aguardando ? `${ESPERA[e.aguardando]}: ${e.passo_nome ?? "próximo passo"}` : e.passo_nome ? `Em: ${e.passo_nome}` : "Começando";
    const detail = e.status === "concluida" ? `Terminou: ${e.resultado ?? "concluída"}` : e.status === "incidente" ? "Incidente: o staff está vendo" : onde;
    return { key: e.id, title: e.titulo, status: e.status, detail, level: nivel[e.id], to: `/processos/execucoes/${e.id}` };
  });
}

export default function Workspace() {
  const session = useSession();
  const resumo = useLiveQuery("conhecimento.briefing", conhecimento.resumo);
  useLive("conhecimento.leituras", () => resumo.reload());
  useLive("conhecimento.itens", () => resumo.reload());
  const descoberta = useLiveQuery("processos.processos", processos.resumo);
  const acompanhamento = useLiveQuery("processos.execucoes", processos.acompanhamento);
  const projetos = useLiveQuery("processos.execucoes", processos.projetos, { size: 3 });
  useLive("processos.tarefas", () => acompanhamento.reload());
  const r = resumo.data;
  const a = acompanhamento.data;
  const publicados = (descoberta.data?.publicados ?? 0) > 0;
  return (
    <Page title="Workspace" description={`A jornada da ${session?.tenant?.name ?? "sua empresa"} na Cogniventure, passo a passo.`}>
      {resumo.error && <Alert tone="warning">Não foi possível carregar o andamento: {resumo.error.message}</Alert>}
      {publicados && a ? (
        <Grid cols={4}>
          <Stat label="Em andamento" value={<Quantity value={a.andamento} />} hint={`${a.concluidas} concluídas`} />
          <Stat label="Esperando você" value={<Quantity value={a.tarefas_cliente} />} hint={a.atrasadas ? `${a.atrasadas} atrasadas` : "aprovações"} tone={a.atrasadas ? "danger" : "default"} />
          <Stat label="Com o staff" value={<Quantity value={a.tarefas_staff} />} hint="exceções sendo resolvidas" />
          <Stat
            label="Autonomia"
            value={a.autonomia === null ? "—" : `${Math.round(a.autonomia * 100)}%`}
            hint="concluídas sem exceção para o staff"
            tone={a.autonomia !== null && a.autonomia >= 0.8 ? "success" : "default"}
          />
        </Grid>
      ) : (
        <Grid cols={3}>
          <Stat label="Briefing" value={r ? `${r.topicos_feitos} de ${r.topicos_total}` : "—"} hint={r?.concluido_em ? "Concluído" : "tópicos feitos"} tone={r?.concluido_em ? "success" : "default"} />
          <Stat label="Conhecimento" value={r ? <Quantity value={r.itens} /> : "—"} hint="itens que os agentes consultam" />
          <Stat label="Processos aceitos" value={descoberta.data ? <Quantity value={descoberta.data.aceitos} /> : "—"} hint={descoberta.data?.sugeridos ? `${descoberta.data.sugeridos} sugestões esperando você` : "seguem para o desenho"} />
        </Grid>
      )}
      {projetos.data && projetos.data.items.length > 0 && (
        <Stack>
          <Heading>Projetos</Heading>
          <Text tone="muted">Quando um processo termina e inicia outros (uma proposta aceita abre o contrato e o faturamento), a cadeia é acompanhada como um projeto.</Text>
          {projetos.data.items.map((p) => (
            <ProjectChain key={p.id} title={p.titulo} description={p.resumo ?? undefined} status={p.status} steps={etapas(p.etapas)} />
          ))}
        </Stack>
      )}
      {resumo.loading && !r ? <Spinner label="Carregando a jornada" /> : <JourneySteps steps={passos(r, descoberta.data, a)} />}
    </Page>
  );
}
