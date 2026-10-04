// Tela do módulo integracoes: conexões da empresa com o mundo de fora. Fonte da verdade: specs/integracoes.md.
import { useState } from "react";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
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
import { TextField } from "@/components/TextField";
import { useAction, useListQuery, useLiveQuery, useQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type IntegracoesConexao, type IntegracoesServidorMcp, integracoes } from "@/core/contracts";

export const meta: PageMeta = { title: "Integrações", module: "integracoes" };

export default function Integracoes() {
  return (
    <Page title="Integrações" description="Por onde os documentos chegam, o banco onde os pagamentos são agendados e os sistemas da empresa que os agentes usam.">
      <Tabs
        tabs={[
          { id: "conexoes", label: "Conexões", content: <Conexoes /> },
          { id: "mcp", label: "Servidores MCP", content: <ServidoresMcp /> },
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
            <EmBreve />
          </Stack>
        );
      }}
    </QueryView>
  );
}

function EmBreve() {
  const catalogo = useQuery(integracoes.catalogo);
  const futuras = catalogo.data?.itens.filter((i) => !i.disponivel) ?? [];
  return futuras.length > 0 ? (
    <Card title="Em breve" description="Entram quando o fornecedor for escolhido com o cliente piloto.">
      {futuras.map((i) => (
        <Row key={i.tipo} gap="sm">
          <Badge>{i.nome}</Badge>
          <Text size="sm" tone="muted">
            {i.descricao}
          </Text>
        </Row>
      ))}
    </Card>
  ) : null;
}

const RISCOS = { leitura: "Leitura", escrita: "Escrita", externa: "Externa", irreversivel: "Irreversível" };
const TONS_RISCO = { leitura: "success", escrita: "warning", externa: "warning", irreversivel: "danger" } as const;

function ServidoresMcp() {
  const servidores = useLiveQuery("integracoes.servidores", integracoes.servidores);
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  const [nome, setNome] = useState("");
  const [url, setUrl] = useState("");
  const [cabecalho, setCabecalho] = useState("Authorization");
  const [segredo, setSegredo] = useState("");
  const conectar = useAction(integracoes.conectarServidor, {
    onSuccess: () => {
      setNome("");
      setUrl("");
      setSegredo("");
      servidores.reload();
    },
  });
  return (
    <Stack>
      {pode && (
        <Card
          title="Conectar um servidor MCP"
          description="Um sistema da empresa (ERP, CRM...) que fala MCP. As ferramentas dele ficam disponíveis para os agentes; a credencial fica guardada cifrada, só aqui."
        >
          <Grid cols={2}>
            <TextField label="Nome" value={nome} onChange={setNome} placeholder="Ex.: ERP da empresa" />
            <TextField label="Endereço MCP" value={url} onChange={setUrl} placeholder="https://erp.empresa.com.br/mcp" />
            <TextField label="Cabeçalho da credencial" value={cabecalho} onChange={setCabecalho} hint="Normalmente Authorization." />
            <TextField label="Credencial" type="password" value={segredo} onChange={setSegredo} placeholder="Bearer ..." autoComplete="off" />
          </Grid>
          {conectar.error && <Alert tone="danger">{conectar.error.message}</Alert>}
          <Row>
            <Button
              loading={conectar.running}
              disabled={nome.trim().length < 2 || url.trim().length < 8}
              onClick={() => void conectar.run({ nome: nome.trim(), url: url.trim(), cabecalho: cabecalho.trim() || null, segredo: segredo || null })}
            >
              Conectar e listar as ferramentas
            </Button>
          </Row>
        </Card>
      )}
      <QueryView query={servidores}>
        {(dados) =>
          dados.itens.length ? (
            <Stack>
              {dados.itens.map((s) => (
                <Servidor key={s.id} servidor={s} pode={pode} onDone={servidores.reload} />
              ))}
            </Stack>
          ) : (
            <Text tone="muted">Nenhum servidor MCP conectado ainda.</Text>
          )
        }
      </QueryView>
    </Stack>
  );
}

function Servidor({ servidor, pode, onDone }: { servidor: IntegracoesServidorMcp; pode: boolean; onDone: () => void }) {
  const atualizar = useAction(integracoes.atualizarServidor, { onSuccess: onDone });
  const remover = useAction(integracoes.removerServidor, { onSuccess: onDone });
  const quarentena = servidor.ferramentas.filter((f) => f.quarentena);
  return (
    <Card
      title={servidor.nome}
      description={`${servidor.url}${servidor.servidor ? ` · ${servidor.servidor}` : ""}${servidor.tem_segredo ? " · com credencial" : ""}`}
      footer={
        pode && (
          <Row justify="between">
            <Text size="sm" tone="muted">
              {servidor.atualizado_em ? (
                <>
                  Ferramentas conferidas em <DateTime value={servidor.atualizado_em} />
                </>
              ) : null}
            </Text>
            <Row gap="sm">
              <Button size="sm" variant="secondary" loading={atualizar.running} onClick={() => void atualizar.run({ id: servidor.id })}>
                Atualizar ferramentas
              </Button>
              <ConfirmButton size="sm" confirmLabel="Remover o servidor" loading={remover.running} onConfirm={() => void remover.run({ id: servidor.id })}>
                Remover
              </ConfirmButton>
            </Row>
          </Row>
        )
      }
    >
      <Stack>
        {(atualizar.error ?? remover.error) && <Alert tone="danger">{(atualizar.error ?? remover.error)?.message}</Alert>}
        {quarentena.length > 0 && (
          <Alert tone="warning" title="Ferramenta em quarentena">
            {quarentena.map((f) => `${f.nome}: ${f.quarentena}`).join(" ")} Os agentes não a usam até alguém conferir e atualizar.
          </Alert>
        )}
        {servidor.ferramentas.map((f) => (
          <Row key={f.nome} justify="between" wrap={false}>
            <Text size="sm">
              {f.titulo ?? f.nome}: {f.descricao}
            </Text>
            <StatusBadge value={f.quarentena ? "quarentena" : f.risco} labels={{ ...RISCOS, quarentena: "Quarentena" }} tones={{ ...TONS_RISCO, quarentena: "danger" }} />
          </Row>
        ))}
      </Stack>
    </Card>
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
