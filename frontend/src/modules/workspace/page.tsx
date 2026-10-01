import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Grid } from "@/components/Grid";
import { type JourneyStep, JourneySteps } from "@/components/JourneySteps";
import { Page } from "@/components/Page";
import { Quantity } from "@/components/Quantity";
import { Spinner } from "@/components/Spinner";
import { Stat } from "@/components/Stat";
import { useLive, useLiveQuery } from "@/core/api";
import { useSession } from "@/core/auth";
import { type ConhecimentoResumo, conhecimento } from "@/core/contracts";

export const meta: PageMeta = { title: "Workspace", order: 0 };

const FONTES: Record<string, string> = { briefing: "do briefing", site: "do site", documento: "de documentos", manual: "manuais" };

/** A jornada do cliente (briefing.md §3): cada passo aparece aqui conforme os blocos chegam. */
function passos(r: ConhecimentoResumo | null): JourneyStep[] {
  const feito = Boolean(r?.concluido_em);
  const comecou = (r?.topicos_feitos ?? 0) > 0;
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
      status: feito ? "current" : "todo",
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
      status: "later",
    },
    { title: "Desenho dos processos", description: "Cada processo é desenhado numa conversa, com o fluxo aparecendo ao lado.", status: "later" },
    { title: "Acompanhamento", description: "Os processos rodando, o que espera por você e quanto cada um roda sozinho.", status: "later" },
  ];
}

export default function Workspace() {
  const session = useSession();
  const resumo = useLiveQuery("conhecimento.briefing", conhecimento.resumo);
  useLive("conhecimento.leituras", () => resumo.reload());
  useLive("conhecimento.itens", () => resumo.reload());
  const r = resumo.data;
  return (
    <Page title="Workspace" description={`A jornada da ${session?.tenant?.name ?? "sua empresa"} na Cogniventure, passo a passo.`}>
      {resumo.error && <Alert tone="warning">Não foi possível carregar o andamento: {resumo.error.message}</Alert>}
      <Grid cols={3}>
        <Stat label="Briefing" value={r ? `${r.topicos_feitos} de ${r.topicos_total}` : "—"} hint={r?.concluido_em ? "Concluído" : "tópicos feitos"} tone={r?.concluido_em ? "success" : "default"} />
        <Stat label="Conhecimento" value={r ? <Quantity value={r.itens} /> : "—"} hint="itens que os agentes consultam" />
        <Stat label="Leituras em andamento" value={r ? <Quantity value={r.leituras_lendo} /> : "—"} hint="site e documentos" />
      </Grid>
      {resumo.loading && !r ? <Spinner label="Carregando a jornada" /> : <JourneySteps steps={passos(r)} />}
    </Page>
  );
}
