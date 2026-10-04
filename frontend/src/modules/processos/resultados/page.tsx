// Resultados: a autonomia de cada processo mês a mês, como terminaram e os indicadores de negócio. Só compõe o catálogo
// (src/components/CATALOG.md, README §6). Fonte da verdade: specs/processos.md (GET /processos/resultados).
import { useSearchParams } from "react-router";
import type { PageMeta } from "@/App";
import { Grid } from "@/components/Grid";
import { Page } from "@/components/Page";
import { ProcessResults } from "@/components/ProcessResults";
import { QueryView } from "@/components/QueryView";
import { SelectField } from "@/components/SelectField";
import { Stack } from "@/components/Stack";
import { Stat } from "@/components/Stat";
import { useLiveQuery } from "@/core/api";
import { processos } from "@/core/contracts";

export const meta: PageMeta = { title: "Resultados" };

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

/** Os últimos 12 meses em Brasília, do atual para trás: { value: "2026-10", label: "outubro de 2026" }. */
function ultimosMeses(): { value: string; label: string }[] {
  const [ano = 2000, mes = 1] = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit" })
    .format(new Date())
    .split("-")
    .map(Number);
  return Array.from({ length: 12 }, (_, i) => {
    const total = ano * 12 + (mes - 1) - i;
    const a = Math.floor(total / 12);
    const m = (total % 12) + 1;
    return { value: `${a}-${String(m).padStart(2, "0")}`, label: `${MESES[m - 1]} de ${a}` };
  });
}

export default function Resultados() {
  const [params, setParams] = useSearchParams();
  const opcoes = ultimosMeses();
  const mes = params.get("mes") ?? opcoes[0]?.value ?? "";
  const resultados = useLiveQuery("processos.execucoes", processos.resultados, { mes, meses: 6 });
  return (
    <Page
      title="Resultados"
      description="Para cada processo publicado: quanto rodou sozinho mês a mês (a versão nova marcada no mês em que entrou), como as execuções terminaram e os indicadores de negócio do mês. O resumo do mês chega ao dono por e-mail no dia 1."
      actions={
        <SelectField
          label="Mês"
          value={mes}
          onChange={(valor) => setParams({ mes: valor })}
          options={opcoes.some((o) => o.value === mes) ? opcoes : [{ value: mes, label: mes }, ...opcoes]}
        />
      }
    >
      <QueryView query={resultados}>
        {(r) => (
          <Stack>
            <Grid cols={3}>
              <Stat label="Concluídas no mês" value={r.concluidas} hint={`${r.processos.length} processo${r.processos.length === 1 ? "" : "s"} publicado${r.processos.length === 1 ? "" : "s"}`} />
              <Stat
                label="Rodaram sozinhas"
                value={r.autonomia === null ? "—" : `${Math.round(r.autonomia * 100)}%`}
                hint="concluídas sem exceção para o staff"
                tone={r.autonomia !== null && r.autonomia >= 0.8 ? "success" : "default"}
              />
              <Stat label="Com exceção" value={r.concluidas - r.sem_handoff} hint="o staff resolveu algum passo" />
            </Grid>
            <ProcessResults processes={r.processos} />
          </Stack>
        )}
      </QueryView>
    </Page>
  );
}
