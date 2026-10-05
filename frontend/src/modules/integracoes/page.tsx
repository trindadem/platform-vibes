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
import { FileField } from "@/components/FileField";
import { Grid } from "@/components/Grid";
import { ListView } from "@/components/ListView";
import { Money } from "@/components/Money";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SelectField } from "@/components/SelectField";
import { SidePanel } from "@/components/SidePanel";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextField } from "@/components/TextField";
import { Toggle } from "@/components/Toggle";
import { type QueryState, useAction, useListQuery, useLiveQuery, useQuery, useUpload } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import {
  type IntegracoesConexao,
  type IntegracoesDocumento,
  type IntegracoesGateway,
  type IntegracoesGateways,
  type IntegracoesServidorMcp,
  integracoes,
} from "@/core/contracts";

export const meta: PageMeta = { title: "Integrações", module: "integracoes" };

export default function Integracoes() {
  const gateways = useLiveQuery("integracoes.gateways", integracoes.gateways);
  return (
    <Page title="Integrações" description="Por onde os documentos chegam e os e-mails saem, o banco dos pagamentos e das cobranças e os sistemas da empresa que os agentes usam.">
      <Tabs
        tabs={[
          { id: "conexoes", label: "Conexões", content: <Conexoes gateways={gateways} /> },
          ...(gateways.data?.gerencia ? [{ id: "gateways", label: "Gateways", content: <GatewaysDaPlataforma gateways={gateways} /> }] : []),
          { id: "mcp", label: "Servidores MCP", content: <ServidoresMcp /> },
          { id: "documentos", label: "Documentos recebidos", content: <Documentos /> },
          { id: "pagamentos", label: "Pagamentos", content: <Pagamentos /> },
          { id: "cobrancas", label: "Cobranças", content: <Cobrancas /> },
          { id: "enviados", label: "E-mails enviados", content: <Enviados /> },
        ]}
      />
    </Page>
  );
}

const OPERACOES = { agendar: "Agendar", cobrar: "Cobrar", extrato: "Extrato" };

/** Quanto cada operação do gateway custa ao cliente (soma no plano), em etiquetas. */
function Custos({ gateway }: { gateway: IntegracoesGateway }) {
  const custos = Object.entries(gateway.custos).filter(([, valor]) => valor > 0);
  return custos.length ? (
    <Row gap="sm">
      {custos.map(([operacao, valor]) => (
        <Badge key={operacao}>
          {OPERACOES[operacao as keyof typeof OPERACOES] ?? operacao}: <Money value={valor} />
        </Badge>
      ))}
    </Row>
  ) : (
    <Text size="sm" tone="muted">
      Sem custo por operação.
    </Text>
  );
}

function Conexoes({ gateways }: { gateways: QueryState<IntegracoesGateways> }) {
  const conexoes = useLiveQuery("integracoes.conexoes", integracoes.conexoes);
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin");
  const [escolhido, setEscolhido] = useState("simulado");
  const conectar = useAction(integracoes.conectar, { onSuccess: conexoes.reload });
  const desconectar = useAction(integracoes.desconectar, { onSuccess: conexoes.reload });
  const disponiveis = (gateways.data?.itens ?? []).filter((g) => g.capacidade === "banco" && g.ativo);
  const gateway = disponiveis.find((g) => g.slug === escolhido);
  return (
    <QueryView query={conexoes}>
      {(dados) => {
        const por = (tipo: IntegracoesConexao["tipo"]) => dados.itens.find((c) => c.tipo === tipo);
        const caixa = por("caixa_entrada");
        const banco = por("banco");
        const doBanco = disponiveis.find((g) => g.slug === banco?.gateway);
        return (
          <Stack>
            {(conectar.error ?? desconectar.error) && <Alert tone="danger">{(conectar.error ?? desconectar.error)?.message}</Alert>}
            <Grid cols={2}>
              <Card
                title="Caixa de entrada"
                description="Encaminhe para este endereço os boletos e as notas dos fornecedores: cada anexo vira um documento e inicia o contas a pagar. Propostas, cobranças e pedidos saem dele."
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
                title="Banco"
                description="Pagamentos, cobranças e extrato passam pelo gateway que a Cogniventure contrata (o custo de cada operação entra no seu plano) ou pelo banco simulado, que confirma cada um alguns segundos depois."
                footer={
                  pode && (banco ? (
                    <ConfirmButton size="sm" confirmLabel="Desconectar o banco" loading={desconectar.running} onConfirm={() => void desconectar.run({ id: banco.id })}>
                      Desconectar
                    </ConfirmButton>
                  ) : (
                    <Button loading={conectar.running} disabled={!gateway} onClick={() => void conectar.run({ tipo: "banco", gateway: escolhido, confirmar_apos: 30 })}>
                      Conectar o banco
                    </Button>
                  ))
                }
              >
                {banco ? (
                  <Stack gap="sm">
                    <Text tone="success">
                      {`Conectado pelo ${banco.gateway_nome ?? banco.nome}`}
                      {banco.gateway === "simulado" ? `: confirma pagamentos e cobranças ${banco.confirmar_apos ?? 30} s depois de emitidos.` : "."}
                    </Text>
                    {doBanco ? <Custos gateway={doBanco} /> : banco.gateway !== "simulado" && <Alert tone="warning">Este gateway não está disponível agora: as operações do banco vão para o staff.</Alert>}
                  </Stack>
                ) : pode ? (
                  <Stack gap="sm">
                    <SelectField
                      label="Gateway"
                      value={escolhido}
                      onChange={setEscolhido}
                      options={disponiveis.map((g) => ({ value: g.slug, label: g.nome }))}
                      hint="O banco simulado não tem custo; os da Cogniventure somam cada operação no plano."
                    />
                    {gateway && <Custos gateway={gateway} />}
                  </Stack>
                ) : (
                  <Text tone="muted">Ainda não conectado.</Text>
                )}
              </Card>
            </Grid>
            <EmBreve />
          </Stack>
        );
      }}
    </QueryView>
  );
}

/** Os gateways que a Cogniventure contrata e repassa no plano: só quem a administra vê esta aba. */
function GatewaysDaPlataforma({ gateways }: { gateways: QueryState<IntegracoesGateways> }) {
  const [editando, setEditando] = useState<IntegracoesGateway | "novo" | null>(null);
  const editar = useAction(integracoes.editarGateway, { onSuccess: gateways.reload });
  const remover = useAction(integracoes.removerGateway, { onSuccess: gateways.reload });
  return (
    <QueryView query={gateways}>
      {(dados) => (
        <Stack>
          <Row justify="between">
            <Text tone="muted">
              A credencial fica cifrada neste serviço e nunca volta à tela. O custo de cada operação soma no limite do plano de cada cliente (Gasto com o banco no mês).
            </Text>
            <Button onClick={() => setEditando("novo")}>Novo gateway</Button>
          </Row>
          {(editar.error ?? remover.error) && <Alert tone="danger">{(editar.error ?? remover.error)?.message}</Alert>}
          <Grid cols={2}>
            {dados.itens.map((g) => (
              <Card
                key={g.slug}
                title={g.nome}
                description={g.embutido ? "Embutido: sempre disponível, sem custo e sem credencial." : `${g.provedor} · ${g.slug}`}
                footer={
                  !g.embutido && (
                    <Row justify="between">
                      <Toggle label="Ativo" checked={g.ativo} onChange={(ativo) => void editar.run({ id: g.id, ativo })} />
                      <Row gap="sm">
                        <Button size="sm" variant="secondary" onClick={() => setEditando(g)}>
                          Editar
                        </Button>
                        <ConfirmButton size="sm" confirmLabel="Remover o gateway" loading={remover.running} onConfirm={() => void remover.run({ id: g.id })}>
                          Remover
                        </ConfirmButton>
                      </Row>
                    </Row>
                  )
                }
              >
                <Stack gap="sm">
                  <Row gap="sm">
                    {g.operacoes.map((op) => (
                      <Badge key={op}>{OPERACOES[op]}</Badge>
                    ))}
                    {!g.ativo && <StatusBadge value="inativo" labels={{ inativo: "Inativo" }} tones={{ inativo: "warning" }} />}
                  </Row>
                  <Custos gateway={g} />
                  {g.credencial.length > 0 && (
                    <Text size="sm" tone="muted">
                      Credencial guardada: {g.credencial.join(", ")}
                    </Text>
                  )}
                </Stack>
              </Card>
            ))}
          </Grid>
          <SidePanel
            open={editando !== null}
            onClose={() => setEditando(null)}
            title={editando === "novo" ? "Novo gateway" : "Editar o gateway"}
            description="Custo em reais por chamada, repassado ao cliente. A credencial é trocada inteira."
          >
            {editando !== null && (
              <FormularioGateway
                key={editando === "novo" ? "novo" : editando.id}
                gateway={editando === "novo" ? null : editando}
                provedores={dados.provedores}
                onDone={() => {
                  setEditando(null);
                  gateways.reload();
                }}
              />
            )}
          </SidePanel>
        </Stack>
      )}
    </QueryView>
  );
}

function FormularioGateway({
  gateway,
  provedores,
  onDone,
}: {
  gateway: IntegracoesGateway | null;
  provedores: IntegracoesGateways["provedores"];
  onDone: () => void;
}) {
  const [slug, setSlug] = useState(gateway?.slug ?? "");
  const [nome, setNome] = useState(gateway?.nome ?? "");
  const [provedor, setProvedor] = useState(gateway?.provedor ?? provedores.find((p) => p.campos.length > 0)?.provedor ?? provedores[0]?.provedor ?? "");
  const [custos, setCustos] = useState<Record<string, string>>(Object.fromEntries(Object.entries(gateway?.custos ?? {}).map(([k, v]) => [k, String(v)])));
  const [credencial, setCredencial] = useState<Record<string, string>>({});
  const criar = useAction(integracoes.criarGateway, { onSuccess: onDone });
  const editar = useAction(integracoes.editarGateway, { onSuccess: onDone });
  const escolhido = provedores.find((p) => p.provedor === provedor);
  const valores = Object.fromEntries(Object.entries(custos).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, Number(v.replace(",", "."))]));
  const trocaCredencial = Object.values(credencial).some((v) => v.trim() !== "");
  const salvar = () =>
    gateway
      ? void editar.run({ id: gateway.id, nome, custos: valores, credencial: trocaCredencial ? credencial : null })
      : void criar.run({ slug, nome, provedor, custos: valores, credencial: escolhido?.campos.length ? credencial : null });
  const erro = criar.error ?? editar.error;
  return (
    <Stack>
      {!gateway && (
        <>
          <TextField label="Identificador" value={slug} onChange={setSlug} hint="Letras minúsculas, números e hífen (ex.: pluggy-producao). Não muda depois." required />
          <SelectField
            label="Provedor"
            value={provedor}
            onChange={setProvedor}
            options={provedores.map((p) => ({ value: p.provedor, label: p.nome }))}
            hint={escolhido ? `Faz: ${escolhido.operacoes.map((op) => OPERACOES[op]).join(", ")}.` : undefined}
          />
        </>
      )}
      <TextField label="Nome" value={nome} onChange={setNome} required />
      {(escolhido?.operacoes ?? []).map((op) => (
        <TextField
          key={op}
          label={`${OPERACOES[op]} (R$ por chamada)`}
          type="number"
          value={custos[op] ?? ""}
          onChange={(v) => setCustos((atual) => ({ ...atual, [op]: v }))}
          hint="Vazio ou 0: sem custo."
        />
      ))}
      {(escolhido?.campos ?? []).map((campo) => (
        <TextField
          key={campo}
          label={`Credencial: ${campo}`}
          type="password"
          autoComplete="off"
          value={credencial[campo] ?? ""}
          onChange={(v) => setCredencial((atual) => ({ ...atual, [campo]: v }))}
          hint={gateway ? "Em branco: mantém a guardada." : undefined}
          required={!gateway}
        />
      ))}
      {erro && <Alert tone="danger">{erro.message}</Alert>}
      <Row>
        <Button loading={criar.running || editar.running} onClick={salvar}>
          {gateway ? "Salvar" : "Criar o gateway"}
        </Button>
      </Row>
    </Stack>
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

const LEITURAS: Record<IntegracoesDocumento["leitura"], string> = {
  arquivo: "Texto do arquivo",
  modelo: "Lido pelo modelo",
  lendo: "Lendo…",
  sem_texto: "Sem texto legível",
};
const ACEITOS = "application/pdf,image/jpeg,image/png,image/webp,text/plain,text/xml,application/xml";

function Documentos() {
  const lista = useListQuery(integracoes.documentos, { live: "integracoes.documentos" });
  const abrir = useAction(integracoes.arquivo, { onSuccess: (link) => window.open(link.url, "_blank", "noopener") });
  const [enviado, setEnviado] = useState<IntegracoesDocumento | null>(null);
  const envio = useUpload(integracoes.documentoUpload, integracoes.enviarDocumento, { onSuccess: setEnviado });
  return (
    <Stack>
      <Card
        title="Enviar um documento"
        description="O boleto, a nota ou o recibo entra como se tivesse chegado à caixa de entrada e inicia os processos que esperam por ele. Foto e PDF escaneado passam antes pela leitura do modelo."
      >
        <Stack>
          <FileField label="Documento" upload={envio} accept={ACEITOS} hint="PDF, foto (JPG, PNG ou WebP), XML ou texto, até 10 MB." />
          {enviado && (
            <Alert tone="success" title={`${enviado.nome} recebido`}>
              {enviado.leitura === "lendo"
                ? "O modelo está lendo a foto; os processos começam assim que a leitura terminar."
                : "Os processos que esperam por documentos já começaram."}
            </Alert>
          )}
        </Stack>
      </Card>
      <ListView
        list={lista}
        rowKey={(d) => d.id}
        noun="documentos"
        search="nome, assunto ou remetente"
        empty="Nenhum documento recebido ainda."
        columns={[
          { key: "nome", header: "Documento" },
          { key: "origem", header: "Chegou por", render: (d) => (d.origem === "tela" ? "Tela" : "E-mail") },
          { key: "de", header: "De", render: (d) => d.de ?? "—" },
          { key: "assunto", header: "Assunto", render: (d) => d.assunto ?? "—" },
          {
            key: "leitura",
            header: "Leitura",
            render: (d) => <StatusBadge value={d.leitura} labels={LEITURAS} tones={{ arquivo: "neutral", modelo: "accent", lendo: "warning", sem_texto: "danger" }} />,
          },
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
    </Stack>
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

function Cobrancas() {
  const lista = useListQuery(integracoes.cobrancas, { live: "integracoes.cobrancas" });
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const confirmar = useAction(integracoes.confirmarCobranca, { onSuccess: lista.reload });
  return (
    <Stack>
      {confirmar.error && <Alert tone="danger">{confirmar.error.message}</Alert>}
      <ListView
        list={lista}
        rowKey={(c) => c.id}
        noun="cobranças"
        empty="Nenhuma cobrança emitida ainda."
        filters={[{ name: "status", label: "Status", options: [{ value: "aberta", label: "Aberta" }, { value: "recebida", label: "Recebida" }] }]}
        columns={[
          { key: "cobranca_id", header: "Cobrança" },
          { key: "pagador", header: "Pagador", render: (c) => c.pagador ?? "—" },
          { key: "valor", header: "Valor", sort: "valor", render: (c) => <Money value={c.valor} /> },
          { key: "vencimento", header: "Vencimento", sort: "vencimento" },
          { key: "status", header: "Status", render: (c) => <StatusBadge value={c.status} labels={{ aberta: "Aberta", recebida: "Recebida" }} /> },
          {
            key: "acao",
            header: "",
            render: (c) =>
              pode && c.status === "aberta" ? (
                <Row>
                  <Button size="sm" variant="secondary" loading={confirmar.running} onClick={() => void confirmar.run({ id: c.id })}>
                    Confirmar recebimento
                  </Button>
                </Row>
              ) : null,
          },
        ]}
      />
    </Stack>
  );
}

function Enviados() {
  const lista = useListQuery(integracoes.enviados, { live: "integracoes.enviados" });
  return (
    <ListView
      list={lista}
      rowKey={(e) => e.id}
      noun="e-mails"
      search="destinatário ou assunto"
      empty="Nenhum e-mail enviado ainda: propostas, cobranças, pedidos de cotação e campanhas saem pela caixa de entrada."
      columns={[
        { key: "para", header: "Para" },
        { key: "assunto", header: "Assunto" },
        { key: "de", header: "De" },
        { key: "anexos", header: "Anexos", render: (e) => (e.anexos.length ? e.anexos.join(", ") : "—") },
        { key: "created_at", header: "Enviado", sort: "created_at", render: (e) => (e.created_at ? <DateTime value={e.created_at} /> : "—") },
      ]}
    />
  );
}
