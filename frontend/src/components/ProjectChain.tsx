import { Badge } from "./Badge";
import { Button } from "./Button";

/** Uma etapa do projeto: a execução de um processo na cadeia. */
export interface ProjectChainStep {
  /** Identificador estável (ex.: o id da execução). */
  key: string;
  /** O processo (ex.: "Gestão de contratos"). */
  title: string;
  /** andamento, concluida, incidente ou cancelada. */
  status: "andamento" | "concluida" | "incidente" | "cancelada";
  /** Onde está ou como terminou (ex.: "Esperando você: Aprovar o desconto", "Terminou: aceita"). */
  detail?: string;
  /** Quantos processos antes dela na cadeia: 0 para a que começou o projeto. */
  level?: number;
  /** Rota da execução. */
  to?: string;
}

export interface ProjectChainProps {
  /** Nome do projeto (o processo que começou a cadeia). */
  title: string;
  /** O que começou o projeto (ex.: "Proposta para Padaria Pão Quente"). */
  description?: string;
  /** andamento, concluido ou atencao (alguma etapa com incidente). */
  status: "andamento" | "concluido" | "atencao";
  /** As etapas na ordem em que começaram. */
  steps: ProjectChainStep[];
}

const PROJETO = {
  andamento: { label: "Em andamento", tone: "accent" },
  concluido: { label: "Concluído", tone: "success" },
  atencao: { label: "Precisa de atenção", tone: "danger" },
} as const;

const RECUO = ["", "pl-6", "pl-12", "pl-18", "pl-24"]; // um degrau por processo antes na cadeia

const ETAPA = {
  andamento: { label: "Em andamento", tone: "accent", mark: "…" },
  concluida: { label: "Concluída", tone: "success", mark: "✓" },
  incidente: { label: "Incidente", tone: "danger", mark: "!" },
  cancelada: { label: "Cancelada", tone: "neutral", mark: "×" },
} as const;

/**
 * Projeto: a cadeia de processos que um começou (uma proposta aceita inicia o contrato e o faturamento), com cada
 * execução, o que ela espera e o caminho para abri-la.
 *
 * @category Dados
 * @example
 * <ProjectChain
 *   title="Proposta comercial"
 *   description="Proposta para Padaria Pão Quente"
 *   status="andamento"
 *   steps={[
 *     { key: "e1", title: "Proposta comercial", status: "concluida", detail: "Terminou: aceita", to: "/processos/execucoes/e1" },
 *     { key: "e2", title: "Gestão de contratos", status: "andamento", detail: "Com o staff: Coletar as assinaturas", level: 1 },
 *     { key: "e3", title: "Faturamento e cobrança", status: "andamento", detail: "Aguardando o pagamento", level: 1 },
 *   ]}
 * />
 */
export function ProjectChain({ title, description, status, steps }: ProjectChainProps) {
  const projeto = PROJETO[status];
  return (
    <section aria-label={`Projeto ${title}`} className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{title}</span>
        <Badge tone={projeto.tone}>{projeto.label}</Badge>
      </div>
      {description && <span className="text-sm text-muted-foreground">{description}</span>}
      <ol className="flex flex-col gap-2">
        {steps.map((step) => {
          const etapa = ETAPA[step.status];
          const nivel = Math.min(step.level ?? 0, 4);
          return (
            <li key={step.key} className={`flex items-start gap-3 ${RECUO[nivel]}`}>
              <span
                aria-hidden
                className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  step.status === "concluida"
                    ? "bg-success/15 text-success"
                    : step.status === "incidente"
                      ? "bg-destructive/15 text-destructive"
                      : step.status === "andamento"
                        ? "bg-primary/15 text-primary"
                        : "bg-muted text-muted-foreground"
                }`}
              >
                {nivel > 0 ? "↳" : etapa.mark}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{step.title}</span>
                  <Badge tone={etapa.tone}>{etapa.label}</Badge>
                </div>
                {step.detail && <span className="text-sm text-muted-foreground">{step.detail}</span>}
              </div>
              {step.to && (
                <Button to={step.to} variant="ghost" size="sm">
                  Abrir
                </Button>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
