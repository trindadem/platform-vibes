import { useState } from "react";
import { useParams } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { BpmnDiagram } from "@/components/BpmnDiagram";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Columns } from "@/components/Columns";
import { DateTime } from "@/components/DateTime";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { ProjectChain, type ProjectChainStep } from "@/components/ProjectChain";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { TextArea } from "@/components/TextArea";
import { TextLink } from "@/components/TextLink";
import { useAction, useLiveQuery, useQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { identity, type ProcessosEtapaProjeto, type ProcessosExecucaoDetalhe, processos } from "@/core/contracts";

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
  cancelada: "Cancelada",
};
const TONS_MARCOS = { handoff: "warning", incidente: "danger", tentando: "warning", tarefa: "accent", fim: "success", cancelada: "neutral" } as const;

const ESPERA = { cliente: "Esperando a empresa", staff: "Com o staff", evento: "Aguardando" };

/** O projeto (a cadeia de processos) de que esta execução faz parte: quem iniciou quem e onde cada uma está. */
function etapas(itens: ProcessosEtapaProjeto[], atual: string): ProjectChainStep[] {
  const nivel: Record<string, number> = {};
  return itens.map((e) => {
    nivel[e.id] = e.pai ? (nivel[e.pai] ?? 0) + 1 : 0;
    const onde = e.aguardando ? `${ESPERA[e.aguardando]}: ${e.passo_nome ?? "próximo passo"}` : (e.passo_nome ?? "Rodando");
    const detail = e.status === "concluida" ? `Terminou: ${e.resultado ?? "concluída"}` : e.status === "incidente" ? "Incidente" : onde;
    return { key: e.id, title: e.id === atual ? `${e.titulo} (esta)` : e.titulo, status: e.status, detail, level: nivel[e.id],
             to: e.id === atual ? undefined : `/processos/execucoes/${e.id}` };
  });
}

export default function ExecucaoDoProcesso() {
  const { id = "" } = useParams();
  const detalhe = useLiveQuery("processos.execucoes", processos.execucao, { id });
  return <QueryView query={detalhe}>{(d) => <Execucao detalhe={d} reload={detalhe.reload} />}</QueryView>;
}

/** Cancelar com o motivo (fica na linha do tempo), dizendo antes o que já aconteceu fora e não se desfaz. */
function Cancelar({ detalhe, reload }: { detalhe: ProcessosExecucaoDetalhe; reload: () => void }) {
  const [aberto, setAberto] = useState(false);
  const [motivo, setMotivo] = useState("");
  const cancelar = useAction(processos.cancelar, { onSuccess: () => { setAberto(false); reload(); } });
  if (!aberto) {
    return <Button variant="secondary" onClick={() => setAberto(true)}>Cancelar a execução</Button>;
  }
  return (
    <Card title="Cancelar a execução" description="Ela para agora e não segue para os próximos passos; as tarefas abertas dela fecham.">
      <Stack gap="sm">
        {detalhe.efeitos.length > 0 && (
          <Alert tone="warning" title="Cancelar não desfaz o que já aconteceu">
            Já feito fora da plataforma: {detalhe.efeitos.join(", ")}. Se precisar desfazer (um pagamento agendado, uma cobrança enviada),
            faça no banco ou peça ao staff.
          </Alert>
        )}
        <TextArea label="Motivo (fica na linha do tempo)" value={motivo} onChange={setMotivo} placeholder="Ex.: boleto duplicado, já pago por outro caminho." />
        {cancelar.error && <Alert tone="danger">{cancelar.error.message}</Alert>}
        <Row>
          <Button variant="danger" loading={cancelar.running} disabled={motivo.trim().length < 3} onClick={() => void cancelar.run({ id: detalhe.execucao.id, motivo: motivo.trim() })}>
            Cancelar agora
          </Button>
          <Button variant="ghost" onClick={() => setAberto(false)}>Voltar</Button>
        </Row>
      </Stack>
    </Card>
  );
}

function Execucao({ detalhe, reload }: { detalhe: ProcessosExecucaoDetalhe; reload: () => void }) {
  const e = detalhe.execucao;
  const podeCancelar = hasAnyRole(useSession(), "owner", "admin", "operador") && (e.status === "andamento" || e.status === "incidente");
  const membros = useQuery(identity.members); // quem resolveu: o nome, não o id (o operador do staff é membro)
  const nome = (id: string) => membros.data?.items.find((m) => m.id === id)?.name ?? "alguém da equipe";
  const saidas = Object.entries(e.saidas);
  const primeira = detalhe.cadeia[0]; // a execução que começou o projeto
  return (
    <Page
      title={e.titulo}
      description={`${e.resumo ?? "Execução"} · versão ${e.versao ?? e.motor_versao} do processo`}
      actions={<StatusBadge value={e.status} labels={STATUS} tones={TONS} />}
    >
      <Text tone="muted">
        <TextLink to="/processos/execucoes">Execuções</TextLink> ·{" "}
        {e.status === "concluida" ? `Terminou em: ${e.resultado}` : e.status === "cancelada" ? "Cancelada" : (e.passo_nome ?? "Rodando")}
      </Text>
      {primeira && detalhe.cadeia.length > 1 && (
        <ProjectChain
          title={`Projeto: ${primeira.titulo}`}
          description={primeira.resumo ?? undefined}
          status={detalhe.cadeia.some((x) => x.status === "incidente") ? "atencao" : detalhe.cadeia.some((x) => x.status === "andamento") ? "andamento" : "concluido"}
          steps={etapas(detalhe.cadeia, e.id)}
        />
      )}
      {e.status === "cancelada" && (
        <Alert tone="info" title="Cancelada">
          {e.marcos.findLast((m) => m.status === "cancelada")?.motivo ?? "A execução foi cancelada."}
        </Alert>
      )}
      {podeCancelar && <Cancelar detalhe={detalhe} reload={reload} />}
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
