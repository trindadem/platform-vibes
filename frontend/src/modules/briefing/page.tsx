import { useState } from "react";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Alert } from "@/components/Alert";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { type ChatMessage, type ChatProgress, ChatThread } from "@/components/ChatThread";
import { Columns } from "@/components/Columns";
import { DateTime } from "@/components/DateTime";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { TextLink } from "@/components/TextLink";
import { useAction, useLiveQuery, useStream } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type ConhecimentoBriefing, type ConhecimentoPasso, type ConhecimentoPerfil, conhecimento } from "@/core/contracts";

export const meta: PageMeta = { title: "Briefing", order: 1, module: "conhecimento" };

const STATUS = { feito: "Feito", em_andamento: "Em andamento", a_fazer: "A fazer" };
const TONS = { feito: "success", em_andamento: "warning", a_fazer: "neutral" } as const;
const PORTE = [
  { value: "mei", label: "MEI" },
  { value: "micro", label: "Microempresa" },
  { value: "pequena", label: "Pequena" },
  { value: "media", label: "Média" },
  { value: "grande", label: "Grande" },
];
const REGIME = [
  { value: "mei", label: "MEI" },
  { value: "simples", label: "Simples Nacional" },
  { value: "presumido", label: "Lucro presumido" },
  { value: "real", label: "Lucro real" },
  { value: "nao_sei", label: "Não sei" },
];

/** Os campos do perfil, na ordem dos tópicos (rótulos iguais aos do backend). */
const CAMPOS: { name: keyof ConhecimentoPerfil & string; label: string; kind?: "textarea" | "select" | "number"; options?: { value: string; label: string }[] }[] = [
  { name: "atividade", label: "O que a empresa faz", kind: "textarea" },
  { name: "segmento", label: "Segmento" },
  { name: "porte", label: "Porte", kind: "select", options: PORTE },
  { name: "cidade", label: "Cidade" },
  { name: "uf", label: "UF" },
  { name: "site", label: "Site" },
  { name: "produtos", label: "Produtos e serviços", kind: "textarea" },
  { name: "clientes", label: "Quem são os clientes", kind: "textarea" },
  { name: "canais_venda", label: "Canais de venda", kind: "textarea" },
  { name: "bancos", label: "Bancos" },
  { name: "recebimentos", label: "Como recebe", kind: "textarea" },
  { name: "pagamentos", label: "Como paga fornecedores e contas", kind: "textarea" },
  { name: "contabilidade", label: "Contabilidade" },
  { name: "regime_tributario", label: "Regime tributário", kind: "select", options: REGIME },
  { name: "sistemas", label: "Sistemas e planilhas que usa", kind: "textarea" },
  { name: "documentos", label: "Por onde chegam documentos", kind: "textarea" },
  { name: "colaboradores", label: "Colaboradores", kind: "number" },
  { name: "equipe", label: "Quem cuida do quê", kind: "textarea" },
  { name: "dores", label: "O que mais toma tempo ou dá problema", kind: "textarea" },
  { name: "objetivos", label: "O que espera da Cogniventure", kind: "textarea" },
];

function rotulo(campo: (typeof CAMPOS)[number], valor: unknown): string {
  return campo.options?.find((o) => o.value === valor)?.label ?? String(valor);
}

/** Passos do agente em andamento: um por ferramenta, com o status mais recente. */
function andamento(deltas: ConhecimentoPasso[]): ChatProgress[] {
  const passos: ChatProgress[] = [];
  for (const d of deltas) {
    const aberto = passos.findLast((p) => p.label === d.texto && p.status === "running");
    if (aberto && d.status !== "running") aberto.status = d.status;
    else passos.push({ label: d.texto, status: d.status });
  }
  return passos;
}

export default function Briefing() {
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  const briefing = useLiveQuery("conhecimento.briefing", conhecimento.briefing);
  return (
    <Page title="Briefing" description="Uma conversa para conhecermos a sua empresa. O perfil ao lado vai sendo preenchido; corrija o que quiser.">
      {!pode && <Alert>Só donos e administradores conversam com o agente e mudam o perfil. Você pode acompanhar.</Alert>}
      <QueryView query={briefing}>{(b) => <Conversa briefing={b} pode={pode} reload={briefing.reload} />}</QueryView>
    </Page>
  );
}

function Conversa({ briefing: consultado, pode, reload }: { briefing: ConhecimentoBriefing; pode: boolean; reload: () => void }) {
  const resposta = useStream(conhecimento.mensagem);
  const [pendente, setPendente] = useState<string | null>(null);
  const enviar = async (texto: string) => {
    setPendente(texto);
    await resposta.start({ texto });
    setPendente(null);
    reload();
  };
  // O fim da resposta já traz o briefing atualizado: vale ele até a consulta (recarregada) alcançá-lo.
  const final = resposta.result;
  const briefing = final && final.mensagens.length > consultado.mensagens.length ? final : consultado;
  const mensagens: ChatMessage[] = briefing.mensagens.map((m) => ({
    id: m.id,
    role: m.papel === "cliente" ? "user" : "assistant",
    text: m.texto,
    steps: m.passos,
  }));
  const gravada = briefing.mensagens.some((m) => m.papel === "cliente" && m.texto === pendente);
  if (pendente && !gravada) mensagens.push({ id: "pendente", role: "user", text: pendente });
  return (
    <Columns aside={<Perfil briefing={briefing} pode={pode} reload={reload} />} asideWidth="lg">
      <ChatThread
        messages={mensagens}
        onSend={(texto) => void enviar(texto)}
        sending={resposta.running}
        progress={andamento(resposta.deltas)}
        error={resposta.error?.message}
        assistant="Agente de briefing"
        placeholder="Conte sobre a sua empresa (Enter envia, Shift+Enter quebra a linha)"
        disabled={!pode}
      />
    </Columns>
  );
}

function Perfil({ briefing, pode, reload }: { briefing: ConhecimentoBriefing; pode: boolean; reload: () => void }) {
  const [editando, setEditando] = useState(false);
  const salvar = useAction(conhecimento.salvarPerfil, { onSuccess: reload });
  const concluir = useAction(conhecimento.concluir, { onSuccess: reload });
  const reabrir = useAction(conhecimento.reabrir, { onSuccess: reload });
  const perfil = briefing.perfil;
  const preenchidos = CAMPOS.filter((c) => perfil[c.name] !== null && perfil[c.name] !== undefined && perfil[c.name] !== "");
  const feitos = briefing.topicos.filter((t) => t.status === "feito").length;
  const inicial = Object.fromEntries(CAMPOS.map((c) => [c.name, perfil[c.name] == null ? "" : String(perfil[c.name])]));
  return (
    <>
      {briefing.concluido_em && (
        <Alert tone="success" title="Briefing concluído">
          Concluído em <DateTime value={briefing.concluido_em} />. Confira o que entrou no <TextLink to="/conhecimento">conhecimento</TextLink>; a
          descoberta de processos é o próximo passo.
        </Alert>
      )}
      <Card
        title="Perfil da empresa"
        description={`${feitos} de ${briefing.topicos.length} tópicos feitos`}
        footer={
          pode && (
            <>
              <Button variant="secondary" onClick={() => setEditando(true)}>
                Editar perfil
              </Button>
              {briefing.concluido_em ? (
                <Button variant="ghost" loading={reabrir.running} onClick={() => void reabrir.run({})}>
                  Reabrir
                </Button>
              ) : (
                <Button loading={concluir.running} disabled={!briefing.pode_concluir} onClick={() => void concluir.run({})}>
                  Concluir briefing
                </Button>
              )}
            </>
          )
        }
      >
        <Stack gap="md">
          {briefing.topicos.map((t) => (
            <Stack key={t.id} gap="sm">
              <Row justify="between" wrap={false}>
                <Text>{t.titulo}</Text>
                <StatusBadge value={t.status} labels={STATUS} tones={TONS} />
              </Row>
              {t.faltam.length > 0 && t.status !== "a_fazer" && (
                <Text tone="muted" size="sm">
                  Falta: {t.faltam.join(", ")}
                </Text>
              )}
            </Stack>
          ))}
        </Stack>
        {(concluir.error || reabrir.error) && <Alert tone="danger">{(concluir.error ?? reabrir.error)?.message}</Alert>}
        {preenchidos.length > 0 && <KeyValue stacked items={preenchidos.map((c) => ({ label: c.label, value: rotulo(c, perfil[c.name]) }))} />}
      </Card>
      <SidePanel open={editando} onClose={() => setEditando(false)} title="Editar perfil" description="Só o que você mudar é salvo; apagar um campo o deixa em branco.">
        {editando && <ActionForm action={salvar} submitLabel="Salvar perfil" initial={inicial} onDone={() => setEditando(false)} fields={CAMPOS} />}
      </SidePanel>
    </>
  );
}
