import { Badge } from "./Badge";
import { Button } from "./Button";

/** Um passo da jornada. */
export interface JourneyStep {
  title: string;
  /** Uma frase sobre o que acontece no passo. */
  description: string;
  /** done: feito; current: o passo de agora; todo: ainda não começou; later: ainda não disponível. */
  status: "done" | "current" | "todo" | "later";
  /** Onde está o passo agora (ex.: "4 de 6 tópicos"). */
  detail?: string;
  /** Rota da tela do passo (o botão some quando o passo é later). */
  to?: string;
  /** Texto do botão. Padrão: Abrir. */
  action?: string;
}

export interface JourneyStepsProps {
  /** Passos na ordem da jornada. */
  steps: JourneyStep[];
}

const STATUS = {
  done: { label: "Feito", tone: "success" },
  current: { label: "Agora", tone: "accent" },
  todo: { label: "Depois", tone: "neutral" },
  later: { label: "Em breve", tone: "neutral" },
} as const;

/**
 * Jornada em passos numerados: o que já foi feito, o passo de agora em destaque e os próximos, com o caminho de cada um.
 *
 * @category Dados
 * @example
 * <JourneySteps
 *   steps={[
 *     { title: "Briefing", description: "Conte como a empresa funciona.", status: "done", detail: "6 de 6 tópicos", to: "/briefing" },
 *     { title: "Conhecimento", description: "Site e documentos.", status: "current", to: "/conhecimento", action: "Enviar documentos" },
 *     { title: "Processos", description: "O que vamos executar.", status: "later" },
 *   ]}
 * />
 */
export function JourneySteps({ steps }: JourneyStepsProps) {
  return (
    <ol className="flex flex-col gap-3">
      {steps.map((step, i) => {
        const status = STATUS[step.status];
        const current = step.status === "current";
        return (
          <li
            key={step.title}
            aria-current={current ? "step" : undefined}
            className={`flex items-start gap-4 rounded-xl border p-4 ${current ? "border-primary bg-primary/5" : "border-border bg-card"} ${
              step.status === "later" ? "opacity-70" : ""
            }`}
          >
            <span
              aria-hidden
              className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                step.status === "done" ? "bg-success/15 text-success" : current ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
              }`}
            >
              {step.status === "done" ? "✓" : i + 1}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{step.title}</span>
                <Badge tone={status.tone}>{status.label}</Badge>
              </div>
              <span className="text-sm text-muted-foreground">{step.description}</span>
              {step.detail && <span className="text-sm">{step.detail}</span>}
            </div>
            {step.to && step.status !== "later" && (
              <Button to={step.to} variant={current ? "primary" : "secondary"} size="sm">
                {step.action ?? "Abrir"}
              </Button>
            )}
          </li>
        );
      })}
    </ol>
  );
}
