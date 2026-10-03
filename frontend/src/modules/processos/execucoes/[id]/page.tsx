import { useParams } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { BpmnDiagram } from "@/components/BpmnDiagram";
import { Card } from "@/components/Card";
import { Columns } from "@/components/Columns";
import { DateTime } from "@/components/DateTime";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useLiveQuery, useQuery } from "@/core/api";
import { identity, type ProcessosExecucaoDetalhe, processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Execução" };

const STATUS = { andamento: "Em andamento", concluida: "Concluída", incidente: "Incidente", cancelada: "Cancelada" };
const TONS = { andamento: "accent", concluida: "success", incidente: "danger", cancelada: "neutral" } as const;
const MARCOS = {
  iniciada: "Começou",
  concluido: "Feito",
  handoff: "Foi para o staff",
  incidente: "Incidente",
  tentando: "Tentando de novo",
  tarefa: "Esperando uma pessoa",
  resolvido: "Resolvido",
  aguardando: "Esperando",
  fim: "Terminou",
};
const TONS_MARCOS = { handoff: "warning", incidente: "danger", tentando: "warning", tarefa: "accent", fim: "success" } as const;

export default function ExecucaoDoProcesso() {
  const { id = "" } = useParams();
  const detalhe = useLiveQuery("processos.execucoes", processos.execucao, { id });
  return <QueryView query={detalhe}>{(d) => <Execucao detalhe={d} />}</QueryView>;
}

function Execucao({ detalhe }: { detalhe: ProcessosExecucaoDetalhe }) {
  const e = detalhe.execucao;
  const membros = useQuery(identity.members); // quem resolveu: o nome, não o id (o operador do staff é membro)
  const nome = (id: string) => membros.data?.items.find((m) => m.id === id)?.name ?? "alguém da equipe";
  const saidas = Object.entries(e.saidas);
  return (
    <Page
      title={e.titulo}
      description={`${e.resumo ?? "Execução"} · versão ${e.versao ?? e.motor_versao} do processo`}
      actions={<StatusBadge value={e.status} labels={STATUS} tones={TONS} />}
    >
      <Text tone="muted">
        <TextLink to="/processos/execucoes">Execuções</TextLink> · {e.status === "concluida" ? `Terminou em: ${e.resultado}` : (e.passo_nome ?? "Rodando")}
      </Text>
      {e.status === "incidente" && (
        <Alert tone="danger" title="Parou com incidente">
          Um passo falhou sem caminho de exceção. O staff da Cogniventure vê o incidente no motor e retoma a execução.
        </Alert>
      )}
      <Columns
        asideWidth="lg"
        aside={
          <Card title="Linha do tempo">
            <Stack gap="sm">
              {e.marcos.map((m, i) => (
                <Stack key={`${m.passo}-${i}`} gap="sm">
                  <Row justify="between" wrap={false}>
                    <Text size="sm">{m.nome}</Text>
                    <StatusBadge value={m.status} labels={MARCOS} tones={TONS_MARCOS} />
                  </Row>
                  <Text size="sm" tone="muted">
                    <DateTime value={m.em} />
                    {m.por ? ` · por ${nome(m.por)}` : ""}
                    {m.motivo ? ` · ${m.motivo}` : ""}
                  </Text>
                </Stack>
              ))}
            </Stack>
          </Card>
        }
      >
        <Stack>
          <BpmnDiagram xml={detalhe.bpmn} highlight={detalhe.caminho} problems={e.status === "incidente" ? detalhe.atuais : []} label={`Execução de ${e.titulo}`} />
          <KeyValue
            items={[
              { label: "Começou", value: e.created_at ? <DateTime value={e.created_at} /> : "—" },
              { label: "Terminou", value: e.concluida_em ? <DateTime value={e.concluida_em} /> : "—" },
              { label: "Exceções para o staff", value: String(e.handoffs) },
              { label: "Versão no motor", value: `v${e.motor_versao}` },
            ]}
          />
          {saidas.map(([passo, dados]) => (
            <Card key={passo} title={e.marcos.find((m) => m.passo === passo)?.nome ?? passo}>
              <KeyValue items={Object.entries(dados).map(([campo, valor]) => ({ label: campo.replaceAll("_", " "), value: valor === null || valor === undefined ? "—" : String(valor) }))} />
            </Card>
          ))}
        </Stack>
      </Columns>
    </Page>
  );
}
