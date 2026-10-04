// Tela do "Falar com a Cogniventure": os pedidos de ajuda ao staff e a conversa de cada um. Só compõe o catálogo
// (src/components/CATALOG.md, README §6). Fonte da verdade: specs/atendimento.md.
import { useState } from "react";
import { useSearchParams } from "react-router";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ChatThread } from "@/components/ChatThread";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DateTime } from "@/components/DateTime";
import { ListView } from "@/components/ListView";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { useAction, useListQuery, useLiveQuery, useQuery } from "@/core/api";
import { atendimento } from "@/core/contracts";

export const meta: PageMeta = { title: "Pedidos de ajuda", module: "atendimento" };

const STATUS = { aberto: "Esperando a Cogniventure", respondido: "Respondido", encerrado: "Encerrado" };
const TONS = { aberto: "warning", respondido: "success", encerrado: "neutral" } as const;

export default function PedidosDeAjuda() {
  const [params, setParams] = useSearchParams();
  const aberto = params.get("pedido");
  const lista = useListQuery(atendimento.pedidos, { live: "atendimento.pedidos" });
  const resumo = useQuery(atendimento.resumo);
  const [novo, setNovo] = useState(false);
  const abrir = useAction(atendimento.abrir, { onSuccess: (p) => { lista.reload(); setParams({ pedido: p.id }); } });
  return (
    <Page
      title="Pedidos de ajuda"
      description="O que a sua empresa pediu ao staff da Cogniventure e as respostas. Cada pedido é respondido em até 4 horas."
      actions={resumo.data?.pode_pedir && <Button onClick={() => setNovo(true)}>Novo pedido</Button>}
    >
      {aberto && <Conversa id={aberto} onClose={() => setParams({})} />}
      <ListView
        list={lista}
        rowKey={(p) => p.id}
        noun="pedidos"
        search="assunto"
        empty="Nenhum pedido ainda. Precisando de algo, use Falar com a Cogniventure, no alto de qualquer tela."
        filters={[{ name: "status", label: "Situação", options: Object.entries(STATUS).map(([value, label]) => ({ value, label })) }]}
        columns={[
          { key: "assunto", header: "Pedido" },
          { key: "autor_nome", header: "Quem pediu", render: (p) => p.autor_nome ?? "—" },
          { key: "status", header: "Situação", render: (p) => <StatusBadge value={p.status} labels={STATUS} tones={TONS} /> },
          { key: "updated_at", header: "Última mensagem", sort: "updated_at", render: (p) => (p.updated_at ? <DateTime value={p.updated_at} format="relative" /> : "—") },
          {
            key: "abrir",
            header: "",
            render: (p) => (
              <Button size="sm" variant="secondary" onClick={() => setParams({ pedido: p.id })}>
                Abrir
              </Button>
            ),
          },
        ]}
      />
      <SidePanel open={novo} onClose={() => setNovo(false)} title="Falar com a Cogniventure" description="Conte o que precisa: o staff responde em até 4 horas.">
        {novo && (
          <ActionForm
            action={abrir}
            submitLabel="Enviar pedido"
            onDone={() => setNovo(false)}
            fields={[{ name: "texto", label: "Como podemos ajudar?", kind: "textarea", required: true, placeholder: "O boleto da Leite Bom não entrou no contas a pagar..." }]}
          />
        )}
      </SidePanel>
    </Page>
  );
}

/** A conversa de um pedido: as mensagens, responder e encerrar. */
function Conversa({ id, onClose }: { id: string; onClose: () => void }) {
  const pedido = useLiveQuery("atendimento.pedidos", atendimento.pedido, { id });
  const escrever = useAction(atendimento.escrever, { onSuccess: pedido.reload });
  const encerrar = useAction(atendimento.encerrar, { onSuccess: pedido.reload });
  return (
    <QueryView query={pedido}>
      {(p) => (
        <Card
          title={p.assunto}
          description={p.autor_nome ? `Pedido de ${p.autor_nome}` : undefined}
          footer={
            <Row justify="between">
              <Row gap="sm">
                <StatusBadge value={p.status} labels={STATUS} tones={TONS} />
                {p.status === "aberto" && p.prazo && (
                  <Text size="sm" tone="muted">
                    Resposta até <DateTime value={p.prazo} />
                  </Text>
                )}
              </Row>
              <Row gap="sm">
                {p.status !== "encerrado" && (
                  <ConfirmButton size="sm" confirmLabel="Encerrar o pedido" loading={encerrar.running} onConfirm={() => void encerrar.run({ id: p.id })}>
                    Encerrar
                  </ConfirmButton>
                )}
                <Button size="sm" variant="secondary" onClick={onClose}>
                  Fechar
                </Button>
              </Row>
            </Row>
          }
        >
          <ChatThread
            messages={p.mensagens.map((m, i) => ({
              id: String(i),
              role: m.papel === "staff" ? "assistant" : "user",
              author: m.papel === "staff" ? `Cogniventure · ${m.autor_nome ?? "staff"}` : (m.autor_nome ?? undefined),
              text: m.texto,
            }))}
            onSend={(texto) => void escrever.run({ id: p.id, texto })}
            sending={escrever.running}
            error={escrever.error?.message ?? encerrar.error?.message}
            assistant="Staff da Cogniventure"
            placeholder="Escreva para o staff"
            disabled={p.status === "encerrado"}
          />
        </Card>
      )}
    </QueryView>
  );
}
