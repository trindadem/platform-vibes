import { useState } from "react";
import { useParams } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { BpmnDiagram } from "@/components/BpmnDiagram";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { type ChatMessage, type ChatProgress, ChatThread } from "@/components/ChatThread";
import { Columns } from "@/components/Columns";
import { ConfirmButton } from "@/components/ConfirmButton";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { TextArea } from "@/components/TextArea";
import { TextLink } from "@/components/TextLink";
import { useAction, useLiveQuery, useQuery, useStream } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { identity, type ProcessosDesenho, type ProcessosPassoAgente, type ProcessosSimulacao, processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Desenho do processo" };

const STATUS = { rascunho: "Rascunho", revisao: "Em revisão", publicada: "Publicada", arquivada: "Arquivada" };
const TONS = { rascunho: "warning", revisao: "warning", publicada: "success", arquivada: "neutral" } as const;
const REGRA = { avaliando: "Em avaliação", ativa: "Ativa", reprovada: "Reprovada", desativada: "Desativada" };
const TONS_REGRA = { avaliando: "warning", ativa: "success", reprovada: "danger", desativada: "neutral" } as const;

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

/** O gatilho em uma frase: evento, agenda (em UTC; Brasília é UTC−3), à mão ou outro processo que termina. */
function gatilho(t: ProcessosDesenho["versao"]["fluxo"]["gatilho"]): string {
  const descricao = t.descricao ? `${t.descricao} · ` : "";
  if (t.tipo === "evento") return `${descricao}evento ${t.evento ?? "?"}`;
  if (t.tipo === "agenda") return `${descricao}agenda ${t.agenda ?? "?"} (UTC)`;
  if (t.tipo === "processo") return `${descricao}quando o processo ${t.processo ?? "?"} termina${t.resultado ? ` como ${t.resultado}` : ""}`;
  return `${descricao}iniciado à mão`;
}

export default function DesenhoDoProcesso() {
  const { id = "" } = useParams();
  const desenho = useLiveQuery("processos.desenho", processos.abrirDesenho, { processo: id });
  return <QueryView query={desenho}>{(d) => <Desenho desenho={d} reload={desenho.reload} />}</QueryView>;
}

function Desenho({ desenho: consultado, reload }: { desenho: ProcessosDesenho; reload: () => void }) {
  const session = useSession();
  const empresa = hasAnyRole(session, "owner", "admin");
  const papel = useQuery(processos.resumo); // na própria Cogniventure, o dono e o admin fazem o papel do staff
  const operador = hasAnyRole(session, "operador") || Boolean(papel.data?.staff); // o staff da Cogniventure, na organização do cliente
  const pode = empresa || operador;
  const id = consultado.processo.id;
  const membros = useQuery(identity.members);
  const regras = useLiveQuery("processos.regras", processos.regras, { processo: id });
  const resposta = useStream(processos.mensagemDesenho);
  const [pendente, setPendente] = useState<string | null>(null);
  const [simulacao, setSimulacao] = useState<ProcessosSimulacao | null>(null);
  const [nota, setNota] = useState("");
  const [motivo, setMotivo] = useState("");
  const [ajuda, setAjuda] = useState("");
  const limpar = () => { setNota(""); setMotivo(""); setAjuda(""); reload(); };
  const simular = useAction(processos.simular, { onSuccess: setSimulacao });
  const desfazer = useAction(processos.desfazer, { onSuccess: reload });
  const publicar = useAction(processos.publicar, { onSuccess: () => { setSimulacao(null); reload(); } });
  const ajustar = useAction(processos.ajustar, { onSuccess: reload });
  const descartar = useAction(processos.descartar, { onSuccess: reload });
  const pedirRevisao = useAction(processos.pedirRevisao, { onSuccess: limpar });
  const aprovar = useAction(processos.aprovarRevisao, { onSuccess: () => { setSimulacao(null); limpar(); } });
  const devolver = useAction(processos.devolver, { onSuccess: limpar });
  const pedirAjuda = useAction(processos.pedirAjuda, { onSuccess: limpar });
  const concluirAjuda = useAction(processos.concluirAjuda, { onSuccess: reload });
  const desativar = useAction(processos.desativarRegra, { onSuccess: regras.reload });
  const pausar = useAction(processos.pausar, { onSuccess: reload });
  const retomar = useAction(processos.retomar, { onSuccess: reload });
  const voltar = useAction(processos.voltar, { onSuccess: () => { setSimulacao(null); reload(); } });

  const final = resposta.result;
  const desenho = final && final.mensagens.length > consultado.mensagens.length ? final : consultado;
  const { versao, problemas } = desenho;
  const rascunho = versao.status === "rascunho";
  const emRevisao = versao.status === "revisao";
  const revisar = rascunho && desenho.exige_revisao && !operador; // a empresa pede; o staff publica direto
  const erros = problemas.filter((p) => p.nivel === "erro");
  const avisos = problemas.filter((p) => p.nivel === "aviso");
  const publicada = desenho.versoes.find((v) => v.status === "publicada");
  const pedido = desenho.processo.ajuda;
  const falha = [simular, desfazer, publicar, ajustar, descartar, pedirRevisao, aprovar, devolver, pedirAjuda, concluirAjuda, desativar, pausar, retomar, voltar]
    .map((a) => a.error)
    .find(Boolean);

  const nome = (pessoa: string | null | undefined) => membros.data?.items.find((m) => m.id === pessoa)?.name;
  const enviar = async (texto: string) => {
    setPendente(texto);
    setSimulacao(null);
    await resposta.start({ processo: id, texto });
    setPendente(null);
    reload();
  };
  // Na conversa entram o cliente, o staff da Cogniventure (quando ajuda no setup) e o agente.
  const mensagens: ChatMessage[] = desenho.mensagens.map((m) => ({
    id: m.id,
    role: m.papel === "agente" ? "assistant" : "user",
    author:
      m.papel === "staff"
        ? `Staff da Cogniventure${nome(m.autor) ? ` · ${nome(m.autor)}` : ""}`
        : m.papel === "cliente" && m.autor && m.autor !== session?.user.id
          ? (nome(m.autor) ?? "Cliente")
          : undefined,
    text: m.texto,
    steps: m.passos,
  }));
  if (pendente && !desenho.mensagens.some((m) => m.papel !== "agente" && m.texto === pendente)) mensagens.push({ id: "pendente", role: "user", text: pendente, steps: [] });
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
            {revisar ? (
              <Button loading={pedirRevisao.running} disabled={erros.length > 0} onClick={() => void pedirRevisao.run({ processo: id, mensagem: nota.trim() || null })}>
                Pedir revisão
              </Button>
            ) : rascunho ? (
              <Button loading={publicar.running} disabled={erros.length > 0} onClick={() => void publicar.run({ processo: id })}>
                Publicar
              </Button>
            ) : emRevisao ? (
              operador && (
                <Button loading={aprovar.running} onClick={() => void aprovar.run({ processo: id })}>
                  Aprovar e publicar
                </Button>
              )
            ) : (
              <Button loading={ajustar.running} onClick={() => void ajustar.run({ processo: id })}>
                Ajustar
              </Button>
            )}
            {publicada && (desenho.processo.pausado ? (
              <Button variant="secondary" loading={retomar.running} onClick={() => void retomar.run({ id })}>
                Retomar
              </Button>
            ) : (
              <ConfirmButton confirmLabel="Pausar o processo" loading={pausar.running} onConfirm={() => void pausar.run({ id })}>
                Pausar
              </ConfirmButton>
            ))}
          </>
        )
      }
    >
      <Text tone="muted">
        <TextLink to="/processos">Processos</TextLink> · {desenho.processo.descricao}
      </Text>
      {falha && <Alert tone="danger">{falha.message}</Alert>}
      {desenho.processo.pausado && (
        <Alert tone="warning" title="Processo pausado">
          O gatilho não inicia execuções novas; as que já estão em andamento terminam. Retome quando quiser voltar a rodar.
        </Alert>
      )}
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
            placeholder={
              rascunho ? "Ex.: acima de 3 mil, eu aprovo antes do pagamento" : emRevisao ? "Em revisão: a conversa volta quando o staff aprovar ou devolver" : "Clique em Ajustar para mudar o fluxo"
            }
            disabled={!pode || !rascunho}
          />
        }
      >
        <Stack>
          {emRevisao &&
            (operador ? (
              <Card title="Revisão pedida" description="Confira o que muda (abaixo), as ações irreversíveis e as conexões novas no diagrama, e simule antes de aprovar.">
                <TextArea label="Por que devolver (se for o caso)" value={motivo} onChange={setMotivo} rows={2} />
                <Row>
                  <Button variant="secondary" loading={devolver.running} disabled={motivo.trim().length < 3} onClick={() => void devolver.run({ processo: id, motivo: motivo.trim() })}>
                    Devolver para ajuste
                  </Button>
                </Row>
              </Card>
            ) : (
              <Alert title="Em revisão pelo staff da Cogniventure">
                A versão {versao.numero} espera a revisão. Quando o staff aprovar, ela é publicada; se devolver, a conversa volta com o motivo.
              </Alert>
            ))}
          {revisar && (
            <Card title="Esta versão passa pela revisão do staff" description="Ela tem ação irreversível (como pagar) ou conexão com sistemas que a versão publicada não tinha.">
              <TextArea label="O que o staff deve olhar (opcional)" value={nota} onChange={setNota} rows={2} />
            </Card>
          )}
          {pedido ? (
            <Alert tone="warning" title="Pedido de ajuda aberto">
              <Stack gap="sm">
                <Text size="sm">{pedido.texto}</Text>
                {operador ? (
                  <Row>
                    <Button size="sm" variant="secondary" loading={concluirAjuda.running} onClick={() => void concluirAjuda.run({ processo: id })}>
                      Concluir a ajuda
                    </Button>
                  </Row>
                ) : (
                  <Text size="sm" tone="muted">O staff da Cogniventure entra nesta conversa para ajustar o fluxo com você.</Text>
                )}
              </Stack>
            </Alert>
          ) : (
            empresa &&
            !operador &&
            !emRevisao && (
              <Card title="Precisa de ajuda?" description="Alguém do staff da Cogniventure entra nesta conversa e ajusta o fluxo com você.">
                <TextArea label="O que você quer ajustar" value={ajuda} onChange={setAjuda} rows={2} />
                <Row>
                  <Button variant="secondary" loading={pedirAjuda.running} disabled={ajuda.trim().length < 3} onClick={() => void pedirAjuda.run({ processo: id, texto: ajuda.trim() })}>
                    Pedir ajuda ao staff
                  </Button>
                </Row>
              </Card>
            )
          )}
          {(rascunho || emRevisao) && desenho.mudancas.length > 0 && (
            <Card title={publicada ? "O que muda em relação à versão publicada" : "O que muda no fluxo de partida"}>
              {desenho.mudancas.map((m) => (
                <Text key={m} size="sm">
                  {m}
                </Text>
              ))}
            </Card>
          )}
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
          <Card title="Quando começa" description={gatilho(versao.fluxo.gatilho)}>
            {desenho.inicia.length > 0 && (
              <Stack gap="sm">
                <Text size="sm" tone="muted">
                  Ao terminar, inicia (a cadeia aparece no workspace como um projeto):
                </Text>
                {desenho.inicia.map((p) => (
                  <Row key={p.id} gap="sm">
                    <TextLink to={`/processos/${p.id}`}>{p.titulo}</TextLink>
                    {p.resultado && <Badge>quando termina como {p.resultado}</Badge>}
                    {!p.publicada && <Badge tone="warning">ainda não publicado</Badge>}
                  </Row>
                ))}
              </Stack>
            )}
          </Card>
          <Card title="Versões" description={pode && publicada ? "Voltar a uma versão anterior a publica de novo, como a próxima versão (com a revisão do staff quando a regra pedir)." : undefined}>
            {desenho.versoes.map((v) => (
              <Row key={v.numero} justify="between" wrap={false}>
                <Text>
                  Versão {v.numero}
                  {v.motor_versao ? ` (motor v${v.motor_versao})` : ""}
                </Text>
                <Row gap="sm" wrap={false}>
                  {pode && v.status === "arquivada" && !rascunho && !emRevisao && (
                    <ConfirmButton confirmLabel={`Voltar à versão ${v.numero}`} loading={voltar.running} onConfirm={() => void voltar.run({ processo: id, numero: v.numero })}>
                      Voltar a esta
                    </ConfirmButton>
                  )}
                  <StatusBadge value={v.status} labels={STATUS} tones={TONS} />
                </Row>
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
          {(regras.data?.itens.length ?? 0) > 0 && (
            <Card title="O que o staff ensinou" description="Regras que nasceram de exceções resolvidas: entram no agente do passo depois de passar na avaliação.">
              {regras.data?.itens.map((r) => (
                <Stack key={r.id} gap="sm">
                  <Row justify="between" wrap={false}>
                    <Text size="sm">
                      {r.passo_nome}: {r.texto}
                    </Text>
                    <Row gap="sm" wrap={false}>
                      <StatusBadge value={r.status} labels={REGRA} tones={TONS_REGRA} />
                      {operador && r.status === "ativa" && (
                        <ConfirmButton size="sm" confirmLabel="Desativar a regra" loading={desativar.running} onConfirm={() => void desativar.run({ id: r.id })}>
                          Desativar
                        </ConfirmButton>
                      )}
                    </Row>
                  </Row>
                  {r.avaliacao && !r.avaliacao.ok && (
                    <Text size="sm" tone="muted">
                      {r.avaliacao.detalhes.join(" ")}
                    </Text>
                  )}
                </Stack>
              ))}
            </Card>
          )}
        </Stack>
      </Columns>
    </Page>
  );
}
