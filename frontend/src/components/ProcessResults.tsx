import { EmptyState } from "./EmptyState";
import { Money } from "./Money";
import { Quantity } from "./Quantity";
import { ResultsCard } from "./ResultsCard";

/** Um indicador de negócio do mês, como GET /processos/resultados devolve. */
export interface ProcessResultsIndicator {
  titulo: string;
  unidade: "numero" | "moeda" | "percentual" | "dias" | "horas";
  /** null: sem dado no mês. */
  valor: number | null;
  descricao?: string;
}

/** Os resultados de um processo num mês, como GET /processos/resultados (e a carteira do staff) devolve. */
export interface ProcessResultsItem {
  processo: string;
  titulo: string;
  publicada: number | null;
  pausado: boolean;
  /** Do mais antigo ao mês pedido: AAAA-MM, concluídas e autonomia (0 a 1, ou null). */
  meses: { mes: string; concluidas: number; autonomia: number | null }[];
  /** As versões publicadas no período (a marca no mês em que entraram). */
  versoes: { numero: number; mes: string }[];
  iniciadas: number;
  concluidas: number;
  canceladas: number;
  em_andamento: number;
  fins: { resultado: string; quantidade: number }[];
  indicadores: ProcessResultsIndicator[];
}

export interface ProcessResultsProps {
  /** Os processos, na ordem em que aparecem. */
  processes: ProcessResultsItem[];
  /** O que mostrar sem nenhum processo publicado. */
  empty?: string;
}

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const DECIMAL = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

/** "2026-10" → "out/26". */
function rotulo(mes: string): string {
  const [ano = "", numero = ""] = mes.split("-");
  return `${MESES[Number(numero) - 1] ?? numero}/${ano.slice(2)}`;
}

function valor(indicador: ProcessResultsIndicator) {
  const v = indicador.valor;
  if (v === null) return "—";
  switch (indicador.unidade) {
    case "moeda":
      return <Money value={v} />;
    case "percentual":
      return `${DECIMAL.format(v)}%`;
    case "dias":
      return `${DECIMAL.format(v)} ${Math.abs(v) === 1 ? "dia" : "dias"}`;
    case "horas":
      return `${DECIMAL.format(v)} h`;
    default:
      return <Quantity value={v} />;
  }
}

/**
 * Receita de resultados de processos: um cartão por processo com a autonomia mês a mês (a versão publicada marcada no
 * mês em que entrou), os números do mês, como as execuções terminaram e os indicadores de negócio, cada um na unidade
 * dele (R$, %, dias, horas). Dois cartões por linha quando há largura (pela largura de onde está: num painel, um).
 *
 * @category Receitas
 * @example
 * <ProcessResults
 *   processes={[{
 *     processo: "p1", titulo: "Contas a pagar", publicada: 2, pausado: false,
 *     meses: [{ mes: "2026-09", concluidas: 4, autonomia: 0.5 }, { mes: "2026-10", concluidas: 10, autonomia: 0.8 }],
 *     versoes: [{ numero: 2, mes: "2026-10" }],
 *     iniciadas: 11, concluidas: 10, canceladas: 0, em_andamento: 1,
 *     fins: [{ resultado: "pago", quantidade: 9 }, { resultado: "recusado", quantidade: 1 }],
 *     indicadores: [{ titulo: "Valor pago", unidade: "moeda", valor: 42000 }, { titulo: "Pagos em atraso", unidade: "numero", valor: 1 }],
 *   }]}
 * />
 */
export function ProcessResults({ processes, empty = "Nenhum processo publicado ainda: os resultados aparecem quando o primeiro rodar." }: ProcessResultsProps) {
  if (processes.length === 0) {
    return <EmptyState title="Sem resultados ainda" description={empty} />;
  }
  return (
    <div className="@container">
      <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2">
        {processes.map((p) => {
          const marcas = new Map(p.versoes.map((v) => [v.mes, `v${v.numero}`]));
          return (
            <ResultsCard
              key={p.processo}
              title={p.titulo}
              description={p.publicada ? `Versão ${p.publicada} publicada` : undefined}
              badges={p.pausado ? ["Pausado"] : []}
              monthsLabel="Rodaram sozinhas, por mês"
              months={p.meses.map((m) => ({
                label: rotulo(m.mes),
                value: m.autonomia,
                detail: `${m.concluidas} concluída${m.concluidas === 1 ? "" : "s"}`,
                marker: marcas.get(m.mes),
              }))}
              counts={[
                { label: "Iniciadas", value: p.iniciadas },
                { label: "Concluídas", value: p.concluidas },
                { label: "Em andamento agora", value: p.em_andamento },
                ...(p.canceladas ? [{ label: "Canceladas", value: p.canceladas }] : []),
              ]}
              ends={p.fins.map((f) => ({ label: f.resultado, value: f.quantidade }))}
              indicators={p.indicadores.map((i) => ({ label: i.titulo, value: valor(i) }))}
            />
          );
        })}
      </div>
    </div>
  );
}
