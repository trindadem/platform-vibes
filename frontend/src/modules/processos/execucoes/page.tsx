import type { PageMeta } from "@/App";
import { Badge } from "@/components/Badge";
import { DateTime } from "@/components/DateTime";
import { ListView } from "@/components/ListView";
import { Page } from "@/components/Page";
import { StatusBadge } from "@/components/StatusBadge";
import { TextLink } from "@/components/TextLink";
import { useListQuery } from "@/core/api";
import { processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Execuções", order: 1 };

const STATUS_EXECUCAO = { andamento: "Em andamento", concluida: "Concluída", incidente: "Incidente", cancelada: "Cancelada" };
const TONS_EXECUCAO = { andamento: "accent", concluida: "success", incidente: "danger", cancelada: "neutral" } as const;
const AGUARDANDO = { cliente: "Esperando a empresa", staff: "Com o staff", evento: "Esperando um evento" };

export default function Execucoes() {
  const lista = useListQuery(processos.execucoes, { live: "processos.execucoes" });
  return (
    <Page title="Execuções" description="Cada vez que um processo roda: o que o iniciou, onde está agora e como terminou.">
      <ListView
        list={lista}
        rowKey={(e) => e.id}
        noun="execuções"
        empty="Nenhuma execução ainda: publique um processo e o gatilho dele começa a rodar."
        filters={[{ name: "status", label: "Status", options: Object.entries(STATUS_EXECUCAO).map(([value, label]) => ({ value, label })) }]}
        columns={[
          { key: "titulo", header: "Processo", render: (e) => <TextLink to={`/processos/execucoes/${e.id}`}>{e.titulo}</TextLink> },
          { key: "resumo", header: "Iniciada por", render: (e) => e.resumo ?? (e.origem === "agenda" ? "Agenda" : "—") },
          { key: "status", header: "Status", render: (e) => <StatusBadge value={e.status} labels={STATUS_EXECUCAO} tones={TONS_EXECUCAO} /> },
          {
            key: "passo_nome",
            header: "Agora",
            render: (e) => (e.status === "concluida" ? (e.resultado ?? "—") : e.aguardando ? AGUARDANDO[e.aguardando] : (e.passo_nome ?? "Rodando")),
          },
          { key: "versao", header: "Versão", render: (e) => <Badge>v{e.versao ?? e.motor_versao}</Badge> },
          { key: "handoffs", header: "Exceções", render: (e) => String(e.handoffs) },
          { key: "created_at", header: "Início", sort: "created_at", render: (e) => (e.created_at ? <DateTime value={e.created_at} /> : "—") },
        ]}
      />
    </Page>
  );
}
