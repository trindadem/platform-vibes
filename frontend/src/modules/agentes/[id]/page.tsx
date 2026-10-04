// Um agente da empresa: configuração, suíte e teste. Só compõe o catálogo (README §6). Fonte da verdade: specs/agentes.md.
import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import type { PageMeta } from "@/App";
import { Alert } from "@/components/Alert";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DateTime } from "@/components/DateTime";
import { KeyValue } from "@/components/KeyValue";
import { Page } from "@/components/Page";
import { QueryView } from "@/components/QueryView";
import { Row } from "@/components/Row";
import { SelectField } from "@/components/SelectField";
import { Stack } from "@/components/Stack";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Text } from "@/components/Text";
import { TextArea } from "@/components/TextArea";
import { TextField } from "@/components/TextField";
import { TextLink } from "@/components/TextLink";
import { Toggle } from "@/components/Toggle";
import { useAction, useLiveQuery, useQuery } from "@/core/api";
import { hasAnyRole, useSession } from "@/core/auth";
import { type AgentesAgente, type AgentesCaso, type AgentesExecucao, type AgentesFerramentaAgente, agentes } from "@/core/contracts";

export const meta: PageMeta = { title: "Agente" };

const STATUS = { rascunho: "Rascunho", verificado: "Verificado", confiavel: "Confiável", avaliando: "Rodando a suíte" };
const TONS = { rascunho: "warning", verificado: "success", confiavel: "accent", avaliando: "neutral" } as const;
const RISCOS = { leitura: "Leitura", escrita: "Escrita", externa: "Externa", irreversivel: "Irreversível" };
const TONS_RISCO = { leitura: "success", escrita: "warning", externa: "warning", irreversivel: "danger" } as const;

export default function AgentePage() {
  const { id = "" } = useParams();
  const agente = useLiveQuery("agentes.agentes", agentes.agente, { id });
  return <QueryView query={agente}>{(a) => <Detalhe agente={a} reload={agente.reload} />}</QueryView>;
}

function Detalhe({ agente, reload }: { agente: AgentesAgente; reload: () => void }) {
  const session = useSession();
  const pode = hasAnyRole(session, "owner", "admin", "operador");
  const staff = hasAnyRole(session, "operador");
  const navigate = useNavigate();
  const avaliar = useAction(agentes.avaliar, { onSuccess: reload });
  const confiar = useAction(agentes.confiar, { onSuccess: reload });
  const remover = useAction(agentes.remover, { onSuccess: () => navigate("/agentes") });
  const falha = avaliar.error ?? confiar.error ?? remover.error;
  return (
    <Page
      title={agente.nome}
      description={`${agente.descricao || "Sem descrição"} · versão ${agente.versao}`}
      actions={
        pode && (
          <>
            {staff && agente.status === "verificado" && (
              <Button variant="secondary" loading={confiar.running} onClick={() => void confiar.run({ id: agente.id })}>
                Marcar como confiável
              </Button>
            )}
            <Button loading={avaliar.running || agente.avaliando} disabled={!agente.casos.length} onClick={() => void avaliar.run({ id: agente.id })}>
              Rodar a suíte
            </Button>
            <ConfirmButton confirmLabel="Remover o agente" loading={remover.running} onConfirm={() => void remover.run({ id: agente.id })}>
              Remover
            </ConfirmButton>
          </>
        )
      }
    >
      <Row gap="sm">
        <TextLink to="/agentes">Agentes</TextLink>
        <StatusBadge value={agente.avaliando ? "avaliando" : agente.status} labels={STATUS} tones={TONS} />
        <Text size="sm" tone="muted">
          {agente.status === "rascunho"
            ? "Ainda não entra em processo: precisa passar na suíte."
            : agente.status === "verificado"
              ? "Passou na suíte: pode fazer um passo de processo."
              : "Confiável: o staff da Cogniventure confirmou."}
        </Text>
      </Row>
      {falha && <Alert tone="danger">{falha.message}</Alert>}
      <Tabs
        tabs={[
          { id: "configuracao", label: "Configuração", content: <Configuracao agente={agente} pode={pode} onDone={reload} /> },
          { id: "suite", label: "Suíte", content: <Suite agente={agente} pode={pode} onDone={reload} /> },
          { id: "testar", label: "Testar", content: <Testar agente={agente} /> },
        ]}
      />
    </Page>
  );
}

function Configuracao({ agente, pode, onDone }: { agente: AgentesAgente; pode: boolean; onDone: () => void }) {
  const catalogo = useQuery(agentes.ferramentas);
  const [nome, setNome] = useState(agente.nome);
  const [descricao, setDescricao] = useState(agente.descricao);
  const [instrucao, setInstrucao] = useState(agente.instrucao);
  const [modelo, setModelo] = useState(agente.modelo);
  const [ferramentas, setFerramentas] = useState<AgentesFerramentaAgente[]>(agente.ferramentas);
  const salvar = useAction(agentes.editar, { onSuccess: onDone });
  // Irreversível (agendar um pagamento, assinar) nunca roda sozinho: entra pedindo aprovação, sem escolha.
  const irreversiveis = new Set((catalogo.data?.itens ?? []).filter((i) => i.risco === "irreversivel").map((i) => i.ref));
  const usar = (ref: string, ligado: boolean) =>
    setFerramentas((atual) =>
      ligado ? [...atual, { ref, modo: irreversiveis.has(ref) ? "perguntar" : "permitir" }] : atual.filter((f) => f.ref !== ref),
    );
  const modo = (ref: string, valor: string) =>
    setFerramentas((atual) => atual.map((f) => (f.ref === ref ? { ...f, modo: valor === "perguntar" ? "perguntar" : "permitir" } : f)));
  return (
    <Stack>
      <Card title="O agente">
        <TextField label="Nome" value={nome} onChange={setNome} />
        <TextField label="O que ele faz" value={descricao} onChange={setDescricao} />
        <TextArea label="Instrução" value={instrucao} onChange={setInstrucao} rows={5} hint="Como ele trabalha: o que consultar, como decidir, quando pedir ajuda." />
        <TextField label="Modelo" value={modelo} onChange={setModelo} hint="Como cadastrado em IA (provedor/modelo). Padrão: cv/agente." />
      </Card>
      <Card
        title="Ferramentas"
        description="Do catálogo: as da plataforma, as ações dos pacotes do seu plano e as dos servidores MCP conectados em Integrações. Pedir aprovação: ele não usa sozinho; o passo vai para uma pessoa. O que é irreversível sempre pede."
      >
        <QueryView query={catalogo}>
          {(c) => (
            <Stack>
              {!c.processos && <Alert tone="warning">Os processos não responderam agora: as ações dos pacotes não aparecem.</Alert>}
              {!c.integracoes && <Alert tone="warning">As integrações não responderam agora: as ferramentas dos servidores MCP não aparecem.</Alert>}
              {c.itens.map((item) => {
                const escolhida = ferramentas.find((f) => f.ref === item.ref);
                return (
                  <Row key={item.ref} justify="between">
                    <Stack gap="sm">
                      <Row gap="sm">
                        <Toggle label={item.nome} checked={Boolean(escolhida)} onChange={(ligado) => usar(item.ref, ligado)} disabled={!pode} />
                        {item.origem === "pacote" && item.pacote && <Badge>{`Pacote ${item.pacote}`}</Badge>}
                        {item.servidor_nome && <Badge>{item.servidor_nome}</Badge>}
                        <StatusBadge value={item.risco} labels={RISCOS} tones={TONS_RISCO} />
                      </Row>
                      <Text size="sm" tone="muted">
                        {item.descricao}
                      </Text>
                    </Stack>
                    {escolhida && item.risco === "irreversivel" && (
                      <Text size="sm" tone="muted">
                        Sempre pede aprovação
                      </Text>
                    )}
                    {escolhida && item.risco !== "leitura" && item.risco !== "irreversivel" && (
                      <SelectField
                        label="Política"
                        value={escolhida.modo}
                        onChange={(v) => modo(item.ref, v)}
                        options={[
                          { value: "permitir", label: "Usar sozinho" },
                          { value: "perguntar", label: "Pedir aprovação" },
                        ]}
                      />
                    )}
                  </Row>
                );
              })}
            </Stack>
          )}
        </QueryView>
      </Card>
      {salvar.error && <Alert tone="danger">{salvar.error.message}</Alert>}
      {pode && (
        <Row>
          <Button
            loading={salvar.running}
            onClick={() =>
              void salvar.run({
                id: agente.id,
                nome,
                descricao,
                instrucao,
                modelo,
                ferramentas: ferramentas.map((f) => (irreversiveis.has(f.ref) ? { ...f, modo: "perguntar" } : f)),
              })
            }
          >
            Salvar
          </Button>
          <Text size="sm" tone="muted">
            Mudar instrução, modelo ou ferramentas volta o agente a rascunho: rode a suíte de novo.
          </Text>
        </Row>
      )}
    </Stack>
  );
}

interface CasoEditado {
  id: string;
  nome: string;
  tarefa: string;
  dados: string;
  esperado: string;
}

const paraEdicao = (c: AgentesCaso): CasoEditado => ({
  id: c.id,
  nome: c.nome,
  tarefa: c.tarefa,
  dados: JSON.stringify(c.dados, null, 2),
  esperado: JSON.stringify(c.esperado, null, 2),
});

function Suite({ agente, pode, onDone }: { agente: AgentesAgente; pode: boolean; onDone: () => void }) {
  const [casos, setCasos] = useState<CasoEditado[]>(agente.casos.map(paraEdicao));
  const [erro, setErro] = useState<string | null>(null);
  const salvar = useAction(agentes.editar, { onSuccess: onDone });
  const muda = (i: number, campo: keyof CasoEditado, valor: string) => setCasos((atual) => atual.map((c, j) => (j === i ? { ...c, [campo]: valor } : c)));
  const enviar = () => {
    try {
      const prontos = casos.map((c) => ({ id: c.id, nome: c.nome, tarefa: c.tarefa, dados: JSON.parse(c.dados || "{}"), esperado: JSON.parse(c.esperado || "{}") }));
      setErro(null);
      void salvar.run({ id: agente.id, casos: prontos });
    } catch {
      setErro("Dados e esperado precisam ser JSON (ex.: {\"divergente\": false, \"diferenca\": 0}).");
    }
  };
  const resultados = agente.avaliacao?.resultados ?? [];
  return (
    <Stack>
      {agente.avaliacao && (
        <Alert tone={agente.avaliacao.ok ? "success" : "warning"} title={agente.avaliacao.ok ? "A suíte passou" : "A suíte não passou"}>
          Versão {agente.avaliacao.versao}, em <DateTime value={agente.avaliacao.em} />
          {agente.avaliacao.versao !== agente.versao ? " (o agente mudou depois: rode de novo)." : "."}
        </Alert>
      )}
      {casos.map((c, i) => {
        const resultado = resultados.find((r) => r.caso === c.id);
        return (
          <Card
            key={c.id}
            title={c.nome || `Caso ${i + 1}`}
            footer={
              <Row justify="between">
                {resultado ? (
                  <Row gap="sm">
                    <StatusBadge value={resultado.ok ? "passou" : "falhou"} labels={{ passou: "Passou", falhou: "Falhou" }} tones={{ passou: "success", falhou: "danger" }} />
                    <Text size="sm" tone="muted">
                      {resultado.ferramentas.length ? `Usou: ${resultado.ferramentas.join(", ")}` : "Não usou ferramentas"}
                    </Text>
                  </Row>
                ) : (
                  <Text size="sm" tone="muted">Ainda não rodou.</Text>
                )}
                {pode && (
                  <Button size="sm" variant="ghost" onClick={() => setCasos((atual) => atual.filter((_, j) => j !== i))}>
                    Tirar o caso
                  </Button>
                )}
              </Row>
            }
          >
            <TextField label="Nome do caso" value={c.nome} onChange={(v) => muda(i, "nome", v)} />
            <TextArea label="Tarefa" value={c.tarefa} onChange={(v) => muda(i, "tarefa", v)} rows={2} />
            <TextArea label="Dados que ele tem à mão (JSON)" value={c.dados} onChange={(v) => muda(i, "dados", v)} rows={4} monospace />
            <TextArea label="O que ele precisa devolver (JSON)" value={c.esperado} onChange={(v) => muda(i, "esperado", v)} rows={3} monospace />
            {resultado && resultado.detalhes.length > 0 && (
              <Alert tone="warning" title="O que divergiu">
                {resultado.detalhes.join(" ")}
              </Alert>
            )}
          </Card>
        );
      })}
      {(erro ?? salvar.error?.message) && <Alert tone="danger">{erro ?? salvar.error?.message}</Alert>}
      {pode && (
        <Row>
          <Button
            variant="secondary"
            onClick={() => setCasos((atual) => [...atual, { id: `caso-${Date.now().toString(36)}`, nome: "", tarefa: "", dados: "{}", esperado: "{}" }])}
          >
            Novo caso
          </Button>
          <Button loading={salvar.running} onClick={enviar}>
            Salvar a suíte
          </Button>
        </Row>
      )}
    </Stack>
  );
}

function Testar({ agente }: { agente: AgentesAgente }) {
  const primeiro = agente.casos[0];
  const [tarefa, setTarefa] = useState(primeiro?.tarefa ?? "");
  const [dados, setDados] = useState(primeiro ? JSON.stringify(primeiro.dados, null, 2) : "{}");
  const [saidas, setSaidas] = useState(
    primeiro ? JSON.stringify(Object.fromEntries(Object.entries(primeiro.esperado).map(([k, v]) => [k, typeof v === "boolean" ? "sim_nao" : typeof v === "number" ? "numero" : "texto"])), null, 2) : '{"resultado": "texto"}',
  );
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<AgentesExecucao | null>(null);
  const testar = useAction(agentes.testar, { onSuccess: setResultado });
  const rodar = () => {
    try {
      const corpo = { id: agente.id, tarefa, dados: JSON.parse(dados || "{}"), saidas: JSON.parse(saidas) };
      setErro(null);
      void testar.run(corpo);
    } catch {
      setErro("Dados e saídas precisam ser JSON. Saídas: campo → texto, numero ou sim_nao.");
    }
  };
  return (
    <Stack>
      <Card title="Experimentar" description="Roda o agente de verdade (modelo e ferramentas), sem mudar o status dele.">
        <TextArea label="Tarefa" value={tarefa} onChange={setTarefa} rows={2} />
        <TextArea label="Dados (JSON)" value={dados} onChange={setDados} rows={4} monospace />
        <TextArea label="Saídas (JSON: campo → texto, numero ou sim_nao)" value={saidas} onChange={setSaidas} rows={3} monospace />
        {(erro ?? testar.error?.message) && <Alert tone="danger">{erro ?? testar.error?.message}</Alert>}
        <Row>
          <Button loading={testar.running} disabled={tarefa.trim().length < 3} onClick={rodar}>
            Rodar
          </Button>
        </Row>
      </Card>
      {resultado && (
        <Card title="Resultado">
          {resultado.aprovacao && <Alert tone="warning" title="Pediria aprovação">{resultado.aprovacao}</Alert>}
          {resultado.ajuda && <Alert tone="warning" title="Pediu ajuda">{resultado.ajuda}</Alert>}
          <KeyValue items={Object.entries(resultado.saidas).map(([k, v]) => ({ label: k, value: JSON.stringify(v) }))} />
          <Text size="sm" tone="muted">
            {resultado.ferramentas.length ? `Usou: ${resultado.ferramentas.join(", ")}` : "Não usou ferramentas."} {resultado.texto}
          </Text>
        </Card>
      )}
    </Stack>
  );
}
