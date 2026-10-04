import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DateTime } from "@/components/DateTime";
import { EmptyState } from "@/components/EmptyState";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextArea } from "@/components/TextArea";
import { TextLink } from "@/components/TextLink";
import { useAction, useLiveQuery, useQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { identity, integracoes, type ProcessosTarefa, processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Tarefas", order: 2 };

const TIPOS = { aprovacao: "Aprovação", excecao: "Exceção" };

export default function Tarefas() {
  const session = useSession();
  const resumo = useQuery(processos.resumo); // na própria Cogniventure, o dono e o admin fazem o papel do staff
  const operador = hasAnyRole(session, "operador") || Boolean(resumo.data?.staff);
  const cliente = <Fila responsavel="cliente" vazio="Nada esperando por você agora." />;
  const staff = <Fila responsavel="staff" vazio="Nenhuma exceção aberta para o staff." />;
  return (
    <Page title="Tarefas" description="O que os processos esperam de uma pessoa: aprovações da empresa e exceções que o staff da Cogniventure resolve.">
      <Tabs
        tabs={
          operador
            ? [
                { id: "staff", label: "Exceções (staff)", content: staff },
                { id: "cliente", label: "Aprovações da empresa", content: cliente },
              ]
            : [
                { id: "cliente", label: "Para você", content: cliente },
                { id: "staff", label: "Com o staff", content: staff },
              ]
        }
      />
    </Page>
  );
}

function Fila({ responsavel, vazio }: { responsavel: "cliente" | "staff"; vazio: string }) {
  const abertas = useLiveQuery("processos.tarefas", processos.tarefas, { responsavel, status: "aberta" as const, size: 50 });
  const feitas = useLiveQuery("processos.tarefas", processos.tarefas, { responsavel, status: "concluida" as const, sort: "-created_at" as const, size: 10 });
  const membros = useQuery(identity.members);
  const nome = (id: string | null | undefined) => membros.data?.items.find((m) => m.id === id)?.name ?? "alguém da equipe";
  return (
    <Stack>
      <QueryView query={abertas}>
        {(pagina) =>
          pagina.items.length ? (
            <Stack>
              {pagina.items.map((t) => (
                <TarefaAberta key={t.id} tarefa={t} onDone={() => { abertas.reload(); feitas.reload(); }} />
              ))}
            </Stack>
          ) : (
            <EmptyState title={vazio} description="Quando um processo precisar de alguém, a tarefa aparece aqui com o prazo." />
          )
        }
      </QueryView>
      <QueryView query={feitas}>
        {(pagina) =>
          pagina.items.length > 0 && (
            <Card title="Resolvidas por último">
              {pagina.items.map((t) => (
                <Row key={t.id} justify="between" wrap={false}>
                  <Text size="sm">
                    {t.titulo}: {t.nome}
                  </Text>
                  <Text size="sm" tone="muted">
                    {t.tipo === "aprovacao" ? (t.resposta.aprovado ? "Aprovado" : "Recusado") : "Resolvida"} por {nome(t.concluida_por)}
                  </Text>
                </Row>
              ))}
            </Card>
          )
        }
      </QueryView>
    </Stack>
  );
}

function TarefaAberta({ tarefa, onDone }: { tarefa: ProcessosTarefa; onDone: () => void }) {
  const session = useSession();
  const resumo = useQuery(processos.resumo);
  const pode = tarefa.responsavel === "cliente" ? hasAnyRole(session, "owner", "admin") : hasAnyRole(session, "operador") || Boolean(resumo.data?.staff);
  const [comentario, setComentario] = useState("");
  const [regra, setRegra] = useState("");
  const responder = useAction(processos.responder, { onSuccess: onDone });
  const documento = useAction(integracoes.arquivo, { onSuccess: (link) => window.open(link.url, "_blank", "noopener") });
  const atrasada = tarefa.prazo ? new Date(tarefa.prazo).getTime() < Date.now() : false;
  // A resolução da exceção é a saída do passo que parou: os campos vêm do backend, com o que o agente chegou a ver.
  const resolver = {
    run: (valores: Record<string, unknown>) =>
      responder.run({ id: tarefa.id, dados: valores as Record<string, string | number | boolean | null>, comentario: comentario || null, regra: regra.trim() || null }),
    running: responder.running,
    error: responder.error,
  };
  return (
    <Card
      title={`${tarefa.titulo}: ${tarefa.nome}`}
      description={tarefa.pergunta}
      footer={
        <Row justify="between">
          <Row gap="sm">
            <StatusBadge value={tarefa.tipo} labels={TIPOS} tones={{ aprovacao: "accent", excecao: "warning" }} />
            {tarefa.prazo && (
              <Text size="sm" tone={atrasada ? "danger" : "muted"}>
                {atrasada ? "Atrasada desde " : "Prazo: "}
                <DateTime value={tarefa.prazo} />
              </Text>
            )}
          </Row>
          <TextLink to={`/processos/execucoes/${tarefa.execucao}`}>Ver a execução</TextLink>
        </Row>
      }
    >
      <Stack>
        {tarefa.motivo && <Alert tone="warning" title="Por que parou">{tarefa.motivo}</Alert>}
        {tarefa.contexto.length > 0 && <KeyValue items={tarefa.contexto.map((i) => ({ label: i.rotulo, value: i.valor }))} />}
        {tarefa.documento_id && (
          <Row>
            <Button variant="secondary" size="sm" loading={documento.running} onClick={() => void documento.run({ id: tarefa.documento_id ?? "" })}>
              Abrir o documento
            </Button>
          </Row>
        )}
        {!pode ? (
          <Text tone="muted" size="sm">
            {tarefa.responsavel === "cliente" ? "Quem aprova é o dono ou um administrador da empresa." : "O staff da Cogniventure está resolvendo esta exceção."}
          </Text>
        ) : tarefa.tipo === "aprovacao" ? (
          <Stack>
            <TextArea label="Comentário (opcional)" value={comentario} onChange={setComentario} rows={2} />
            {responder.error && <Alert tone="danger">{responder.error.message}</Alert>}
            <Row>
              <Button loading={responder.running} onClick={() => void responder.run({ id: tarefa.id, aprovado: true, comentario: comentario || null })}>
                Aprovar
              </Button>
              <Button variant="secondary" loading={responder.running} onClick={() => void responder.run({ id: tarefa.id, aprovado: false, comentario: comentario || null })}>
                Recusar
              </Button>
            </Row>
          </Stack>
        ) : (
          <Stack>
            <TextArea label="O que você fez (opcional)" value={comentario} onChange={setComentario} rows={2} />
            {tarefa.aprende && (
              <TextArea
                label="Ensinar ao agente (opcional)"
                value={regra}
                onChange={setRegra}
                rows={2}
                placeholder="Ex.: a Leite Bom não põe vencimento no boleto: é o dia 15 do mês seguinte ao da referência."
                hint="Vira regra do passo: o agente refaz este caso com ela e, se chegar ao que você preencheu, passa a segui-la nas próximas execuções."
              />
            )}
            <ActionForm
              action={resolver}
              submitLabel="Resolver e seguir o processo"
              initial={Object.fromEntries(tarefa.campos.map((c) => [c.nome, c.valor === null || c.valor === undefined ? "" : String(c.valor)]))}
              fields={tarefa.campos.map((c) => ({ name: c.nome, label: c.rotulo, kind: c.tipo === "numero" ? "number" : c.tipo === "sim_nao" ? "boolean" : "text" }))}
            />
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
