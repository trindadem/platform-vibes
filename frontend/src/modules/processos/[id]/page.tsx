import { useState } from "react";
import { useParams } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { BpmnDiagram } from "@/components/BpmnDiagram";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { type ChatProgress, ChatThread } from "@/components/ChatThread";
import { Columns } from "@/components/Columns";
import { ConfirmButton } from "@/components/ConfirmButton";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useAction, useLiveQuery, useStream } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type ProcessosDesenho, type ProcessosPassoAgente, type ProcessosSimulacao, processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Desenho do processo" };

const STATUS = { rascunho: "Rascunho", revisao: "Em revisão", publicada: "Publicada", arquivada: "Arquivada" };
const TONS = { rascunho: "warning", revisao: "warning", publicada: "success", arquivada: "neutral" } as const;

/** Passos do agente em andamento: um por ferramenta, com o status mais recente. */
function andamento(deltas: ProcessosPassoAgente[]): ChatProgress[] {
  const passos: ChatProgress[] = [];
  for (const d of deltas) {
    const aberto = passos.findLast((p) => p.label === d.texto && p.status === "running");
    if (aberto && d.status !== "running") aberto.status = d.status;
    else passos.push({ label: d.texto, status: d.status });
  }
  return passos;
}

export default function DesenhoDoProcesso() {
  const { id = "" } = useParams();
  const desenho = useLiveQuery("processos.desenho", processos.abrirDesenho, { processo: id });
  return <QueryView query={desenho}>{(d) => <Desenho desenho={d} reload={desenho.reload} />}</QueryView>;
}

function Desenho({ desenho: consultado, reload }: { desenho: ProcessosDesenho; reload: () => void }) {
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  const id = consultado.processo.id;
  const resposta = useStream(processos.mensagemDesenho);
  const [pendente, setPendente] = useState<string | null>(null);
  const [simulacao, setSimulacao] = useState<ProcessosSimulacao | null>(null);
  const simular = useAction(processos.simular, { onSuccess: setSimulacao });
  const desfazer = useAction(processos.desfazer, { onSuccess: reload });
  const publicar = useAction(processos.publicar, { onSuccess: () => { setSimulacao(null); reload(); } });
  const ajustar = useAction(processos.ajustar, { onSuccess: reload });
  const descartar = useAction(processos.descartar, { onSuccess: reload });

  const final = resposta.result;
  const desenho = final && final.mensagens.length > consultado.mensagens.length ? final : consultado;
  const { versao, problemas } = desenho;
  const rascunho = versao.status === "rascunho";
  const erros = problemas.filter((p) => p.nivel === "erro");
  const avisos = problemas.filter((p) => p.nivel === "aviso");
  const publicada = desenho.versoes.find((v) => v.status === "publicada");
  const falha = [simular, desfazer, publicar, ajustar, descartar].map((a) => a.error).find(Boolean);

  const enviar = async (texto: string) => {
    setPendente(texto);
    setSimulacao(null);
    await resposta.start({ processo: id, texto });
    setPendente(null);
    reload();
  };
  const mensagens = desenho.mensagens.map((m) => ({ id: m.id, role: m.papel === "cliente" ? ("user" as const) : ("assistant" as const), text: m.texto, steps: m.passos }));
  if (pendente && !desenho.mensagens.some((m) => m.papel === "cliente" && m.texto === pendente)) mensagens.push({ id: "pendente", role: "user", text: pendente, steps: [] });
  if (!mensagens.length) {
    mensagens.push({
      id: "abertura",
      role: "assistant",
      text: rascunho
        ? `Este é o fluxo de partida de ${desenho.processo.titulo}. Me diga o que muda na sua empresa: quem aprova, a partir de que valor, prazos, o que fazer quando algo não bate.`
        : "Esta versão está publicada. Para mudar o fluxo, clique em Ajustar: abro um rascunho novo e as execuções em andamento seguem na versão delas.",
      steps: [],
    });
  }

  return (
    <Page
      title={desenho.processo.titulo}
      description={`Versão ${versao.numero} · ${STATUS[versao.status]}${versao.motor ? ` · no motor como versão ${versao.motor.versao}` : ""}`}
      actions={
        pode && (
          <>
            <Button variant="secondary" loading={simular.running} onClick={() => void simular.run({ processo: id })}>
              Simular
            </Button>
            {rascunho && versao.pode_desfazer && (
              <Button variant="ghost" loading={desfazer.running} onClick={() => void desfazer.run({ processo: id })}>
                Desfazer
              </Button>
            )}
            {rascunho && publicada && (
              <ConfirmButton confirmLabel="Descartar o rascunho" loading={descartar.running} onConfirm={() => void descartar.run({ processo: id })}>
                Descartar
              </ConfirmButton>
            )}
            {rascunho ? (
              <Button loading={publicar.running} disabled={erros.length > 0} onClick={() => void publicar.run({ processo: id })}>
                Publicar
              </Button>
            ) : (
              <Button loading={ajustar.running} onClick={() => void ajustar.run({ processo: id })}>
                Ajustar
              </Button>
            )}
          </>
        )
      }
    >
      <Text tone="muted">
        <TextLink to="/processos">Processos</TextLink> · {desenho.processo.descricao}
      </Text>
      {falha && <Alert tone="danger">{falha.message}</Alert>}
      <Columns
        asideWidth="lg"
        aside={
          <ChatThread
            messages={mensagens}
            onSend={(texto) => void enviar(texto)}
            sending={resposta.running}
            progress={andamento(resposta.deltas)}
            error={resposta.error?.message}
            assistant="Agente de desenho"
            placeholder={rascunho ? "Ex.: acima de 3 mil, eu aprovo antes do pagamento" : "Clique em Ajustar para mudar o fluxo"}
            disabled={!pode || !rascunho}
          />
        }
      >
        <Stack>
          <BpmnDiagram
            xml={desenho.bpmn}
            highlight={simulacao?.caminho ?? []}
            problems={erros.map((p) => p.passo).filter((p): p is string => Boolean(p))}
            label={`Fluxo do processo ${desenho.processo.titulo}`}
          />
          {simulacao && (
            <Card title="Simulação" description={simulacao.fim ? `Terminou em: ${simulacao.fim}` : "Parou antes do fim"}>
              {simulacao.passos.map((p, i) => (
                <Text key={`${p.id}-${i}`} size="sm">
                  {i + 1}. {p.nome}
                  {p.nota ? ` — ${p.nota}` : ""}
                </Text>
              ))}
              {simulacao.problemas.map((p) => (
                <Text key={p} size="sm" tone="danger">
                  {p}
                </Text>
              ))}
            </Card>
          )}
          {erros.length > 0 && (
            <Alert tone="danger" title="Falta resolver para publicar">
              {erros.map((p) => p.texto).join(" ")}
            </Alert>
          )}
          {avisos.length > 0 && (
            <Alert tone="warning" title="Atenção">
              {avisos.map((p) => p.texto).join(" ")}
            </Alert>
          )}
          {desenho.exige_revisao && rascunho && (
            <Alert>Esta versão tem ação irreversível ou conexão com sistemas: a revisão pelo staff da Cogniventure entra com a área do staff.</Alert>
          )}
          <Card title="Versões">
            {desenho.versoes.map((v) => (
              <Row key={v.numero} justify="between" wrap={false}>
                <Text>
                  Versão {v.numero}
                  {v.motor_versao ? ` (motor v${v.motor_versao})` : ""}
                </Text>
                <StatusBadge value={v.status} labels={STATUS} tones={TONS} />
              </Row>
            ))}
            {Object.keys(versao.fluxo.parametros).length > 0 && (
              <Row gap="sm">
                {Object.entries(versao.fluxo.parametros).map(([k, v]) => (
                  <Badge key={k}>
                    {k.replaceAll("_", " ")}: {String(v)}
                  </Badge>
                ))}
              </Row>
            )}
          </Card>
        </Stack>
      </Columns>
    </Page>
  );
}
