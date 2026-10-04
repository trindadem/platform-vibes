// Agentes da empresa: só compõe o catálogo (src/components/CATALOG.md, README §6). Fonte da verdade: specs/agentes.md.
import { useState } from "react";
import { useNavigate } from "react-router";
import type { PageMeta } from "@/App";
import { ActionForm } from "@/components/ActionForm";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Grid } from "@/components/Grid";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SidePanel } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Text } from "@/components/Text";
import { useAction, useLiveQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { agentes } from "@/core/contracts";

export const meta: PageMeta = { title: "Agentes", module: "agentes" };

const STATUS = { rascunho: "Rascunho", verificado: "Verificado", confiavel: "Confiável" };
const TONS = { rascunho: "warning", verificado: "success", confiavel: "accent" } as const;

export default function Agentes() {
  const lista = useLiveQuery("agentes.agentes", agentes.lista);
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const navigate = useNavigate();
  const [novo, setNovo] = useState(false);
  const criar = useAction(agentes.criar, { onSuccess: (agente) => navigate(`/agentes/${agente.id}`) });
  return (
    <Page
      title="Agentes"
      description="Agentes da empresa: instrução, ferramentas do catálogo (inclusive as dos sistemas conectados por MCP), o que pede aprovação e a suíte que prova que ele funciona."
      actions={pode && <Button onClick={() => setNovo(true)}>Novo agente</Button>}
    >
      <QueryView query={lista}>
        {(dados) =>
          dados.itens.length ? (
            <Grid cols={2}>
              {dados.itens.map((a) => (
                <Card
                  key={a.id}
                  title={a.nome}
                  description={a.descricao || "Sem descrição."}
                  footer={
                    <Row justify="between">
                      <Row gap="sm">
                        <StatusBadge value={a.avaliando ? "avaliando" : a.status} labels={{ ...STATUS, avaliando: "Rodando a suíte" }} tones={{ ...TONS, avaliando: "neutral" }} />
                        <Text size="sm" tone="muted">
                          {a.ferramentas.length} ferramenta{a.ferramentas.length === 1 ? "" : "s"} · {a.casos.length} caso{a.casos.length === 1 ? "" : "s"} na suíte
                        </Text>
                      </Row>
                      <Button size="sm" variant="secondary" to={`/agentes/${a.id}`}>
                        Abrir
                      </Button>
                    </Row>
                  }
                />
              ))}
            </Grid>
          ) : (
            <EmptyState
              title="Nenhum agente ainda"
              description="Um agente nasce rascunho; passa a verificado quando a suíte de casos passa e só então entra num passo de processo."
            />
          )
        }
      </QueryView>
      <SidePanel open={novo} onClose={() => setNovo(false)} title="Novo agente" description="Depois de criar, escolha as ferramentas e escreva a suíte.">
        <ActionForm
          action={criar}
          submitLabel="Criar o agente"
          fields={[
            { name: "nome", label: "Nome", required: true, placeholder: "Ex.: Conferente de pedidos" },
            { name: "descricao", label: "O que ele faz", placeholder: "Ex.: Confere o boleto com o pedido de compra no ERP" },
            { name: "instrucao", label: "Instrução", kind: "textarea", required: true, hint: "Como ele trabalha: o que consultar, como decidir, quando pedir ajuda." },
          ]}
        />
      </SidePanel>
    </Page>
  );
}
