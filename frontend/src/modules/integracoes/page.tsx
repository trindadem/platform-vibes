// Tela do módulo integracoes: conexões da empresa com o mundo de fora. Fonte da verdade: specs/integracoes.md.
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ConfirmButton } from "@/components/ConfirmButton";
import { CopyField } from "@/components/CopyField";
import { DateTime } from "@/components/DateTime";
import { Grid } from "@/components/Grid";
import { ListView } from "@/components/ListView";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { useAction, useListQuery, useLiveQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type IntegracoesConexao, integracoes } from "@/core/contracts";

export const meta: PageMeta = { title: "Integrações", module: "integracoes" };

export default function Integracoes() {
  return (
    <Page title="Integrações" description="Por onde os documentos chegam e o banco onde os pagamentos são agendados.">
      <Tabs
        tabs={[
          { id: "conexoes", label: "Conexões", content: <Conexoes /> },
          { id: "documentos", label: "Documentos recebidos", content: <Documentos /> },
          { id: "pagamentos", label: "Pagamentos", content: <Pagamentos /> },
        ]}
      />
    </Page>
  );
}

function Conexoes() {
  const conexoes = useLiveQuery("integracoes.conexoes", integracoes.conexoes);
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  const conectar = useAction(integracoes.conectar, { onSuccess: conexoes.reload });
  const desconectar = useAction(integracoes.desconectar, { onSuccess: conexoes.reload });
  return (
    <QueryView query={conexoes}>
      {(dados) => {
        const por = (tipo: IntegracoesConexao["tipo"]) => dados.itens.find((c) => c.tipo === tipo);
        const caixa = por("caixa_entrada");
        const banco = por("banco_simulado");
        return (
          <Stack>
            {(conectar.error ?? desconectar.error) && <Alert tone="danger">{(conectar.error ?? desconectar.error)?.message}</Alert>}
            <Grid cols={2}>
              <Card
                title="Caixa de entrada"
                description="Encaminhe para este endereço os boletos e as notas dos fornecedores: cada anexo vira um documento e inicia o contas a pagar."
                footer={
                  pode && (caixa ? (
                    <ConfirmButton size="sm" confirmLabel="Desconectar a caixa" loading={desconectar.running} onConfirm={() => void desconectar.run({ id: caixa.id })}>
                      Desconectar
                    </ConfirmButton>
                  ) : (
                    <Button loading={conectar.running} onClick={() => void conectar.run({ tipo: "caixa_entrada" })}>
                      Criar o endereço
                    </Button>
                  ))
                }
              >
                {caixa?.endereco ? (
                  <CopyField label="Endereço da caixa de entrada" value={caixa.endereco} hint="PDF, imagem, XML ou texto, até 10 MB por anexo." />
                ) : (
                  <Text tone="muted">Ainda não conectada.</Text>
                )}
              </Card>
              <Card
                title="Banco (simulado)"
                description="Até escolhermos o banco da empresa, os pagamentos são agendados num banco de simulação, que confirma cada um alguns segundos depois."
                footer={
                  pode && (banco ? (
                    <ConfirmButton size="sm" confirmLabel="Desconectar o banco" loading={desconectar.running} onConfirm={() => void desconectar.run({ id: banco.id })}>
                      Desconectar
                    </ConfirmButton>
                  ) : (
                    <Button loading={conectar.running} onClick={() => void conectar.run({ tipo: "banco_simulado", confirmar_apos: 30 })}>
                      Conectar o banco simulado
                    </Button>
                  ))
                }
              >
                <Text tone={banco ? "success" : "muted"}>
                  {banco ? `Conectado: confirma os pagamentos ${banco.confirmar_apos ?? 30} s depois de agendados.` : "Ainda não conectado."}
                </Text>
              </Card>
            </Grid>
          </Stack>
        );
      }}
    </QueryView>
  );
}

function Documentos() {
  const lista = useListQuery(integracoes.documentos, { live: "integracoes.documentos" });
  const abrir = useAction(integracoes.arquivo, { onSuccess: (link) => window.open(link.url, "_blank", "noopener") });
  return (
    <ListView
      list={lista}
      rowKey={(d) => d.id}
      noun="documentos"
      search="nome, assunto ou remetente"
      empty="Nenhum documento recebido ainda."
      columns={[
        { key: "nome", header: "Documento" },
        { key: "de", header: "De", render: (d) => d.de ?? "—" },
        { key: "assunto", header: "Assunto", render: (d) => d.assunto ?? "—" },
        { key: "tem_texto", header: "Legível", render: (d) => (d.tem_texto ? "Sim" : "Sem texto (imagem)") },
        { key: "created_at", header: "Chegou", sort: "created_at", render: (d) => (d.created_at ? <DateTime value={d.created_at} /> : "—") },
        {
          key: "abrir",
          header: "",
          render: (d) => (
            <Button size="sm" variant="ghost" onClick={() => void abrir.run({ id: d.id })}>
              Abrir
            </Button>
          ),
        },
      ]}
    />
  );
}

function Pagamentos() {
  const lista = useListQuery(integracoes.pagamentos, { live: "integracoes.pagamentos" });
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const confirmar = useAction(integracoes.confirmarPagamento, { onSuccess: lista.reload });
  return (
    <Stack>
      {confirmar.error && <Alert tone="danger">{confirmar.error.message}</Alert>}
      <ListView
        list={lista}
        rowKey={(p) => p.id}
        noun="pagamentos"
        empty="Nenhum pagamento agendado ainda."
        filters={[{ name: "status", label: "Status", options: [{ value: "agendado", label: "Agendado" }, { value: "pago", label: "Pago" }] }]}
        columns={[
          { key: "pagamento_id", header: "Pagamento" },
          { key: "fornecedor", header: "Fornecedor", render: (p) => p.fornecedor ?? "—" },
          { key: "valor", header: "Valor", sort: "valor", render: (p) => <Money value={p.valor} /> },
          { key: "data", header: "Data", sort: "data" },
          { key: "status", header: "Status", render: (p) => <StatusBadge value={p.status} labels={{ agendado: "Agendado", pago: "Pago" }} /> },
          {
            key: "acao",
            header: "",
            render: (p) =>
              pode && p.status === "agendado" ? (
                <Row>
                  <Button size="sm" variant="secondary" loading={confirmar.running} onClick={() => void confirmar.run({ id: p.id })}>
                    Confirmar agora
                  </Button>
                </Row>
              ) : null,
          },
        ]}
      />
    </Stack>
  );
}
