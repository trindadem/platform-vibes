import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Alert } from "./Alert";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Spinner } from "./Spinner";
import { Textarea } from "@/components/ui/textarea";

/** Uma mensagem da conversa. */
export interface ChatMessage {
  id: string;
  /** assistant: quem responde (o agente); user: a pessoa. */
  role: "assistant" | "user";
  text: string;
  /** Quem escreveu, quando há mais de uma pessoa na conversa (ex.: "Staff da Cogniventure · Otto"), acima do balão. */
  author?: string;
  /** O que o agente fez para responder (ex.: "Anotando no perfil"), mostrado abaixo da mensagem. */
  steps?: string[];
}

/** Um passo da resposta em andamento. */
export interface ChatProgress {
  label: string;
  status: "running" | "done" | "failed";
}

export interface ChatThreadProps {
  /** Mensagens na ordem, a mais antiga primeiro. */
  messages: ChatMessage[];
  /** Envia o texto digitado (Enter envia; Shift+Enter quebra a linha). */
  onSend: (text: string) => void;
  /** Resposta em andamento: trava o envio e mostra os passos. */
  sending?: boolean;
  /** Passos da resposta em andamento, na ordem em que chegaram. */
  progress?: ChatProgress[];
  /** Erro da última resposta. */
  error?: string | null;
  /** Nome de quem responde, para leitores de tela e para o indicador de resposta (ex.: "Agente de briefing"). */
  assistant?: string;
  /** Texto de exemplo no campo. */
  placeholder?: string;
  /** Desliga o campo (ex.: para quem só pode ler). */
  disabled?: boolean;
}

const MARK = { running: "…", done: "✓", failed: "✗" };

/**
 * Receita de conversa com um agente: mensagens em balões, passos do agente enquanto responde, erro e campo de envio.
 *
 * @category Receitas
 * @example
 * <ChatThread
 *   messages={[
 *     { id: "1", role: "assistant", text: "Olá! O que a sua empresa faz?" },
 *     { id: "2", role: "user", text: "Somos uma padaria." },
 *     { id: "3", role: "user", author: "Staff da Cogniventure · Otto", text: "Ajustei o limite para 3 mil." },
 *   ]}
 *   onSend={(texto) => setNome(texto)}
 *   sending={false}
 *   progress={[{ label: "Anotando no perfil", status: "done" }]}
 *   assistant="Agente de briefing"
 * />
 */
export function ChatThread({ messages, onSend, sending = false, progress = [], error, assistant = "Agente", placeholder = "Escreva sua mensagem", disabled = false }: ChatThreadProps) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end", behavior: "smooth" }), [messages.length, progress.length, sending]);

  const send = () => {
    const value = text.trim();
    if (!value || sending || disabled) return;
    onSend(value);
    setText("");
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  return (
    <section aria-label={`Conversa com ${assistant}`} className="flex flex-col overflow-hidden rounded-xl border border-border bg-card">
      <div role="log" aria-live="polite" className="flex max-h-[60vh] min-h-72 flex-col gap-3 overflow-y-auto p-4">
        {messages.map((m) => (
          <div key={m.id} className={`flex flex-col gap-1 ${m.role === "user" ? "items-end" : "items-start"}`}>
            {m.author ? (
              <span className="px-1 text-xs text-muted-foreground">{m.author}</span>
            ) : (
              <span className="sr-only">{m.role === "user" ? "Você" : assistant}:</span>
            )}
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                m.role === "user" ? "rounded-br-sm bg-primary text-primary-foreground" : "rounded-bl-sm bg-muted text-foreground"
              }`}
            >
              {m.text}
            </div>
            {m.steps && m.steps.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {m.steps.map((step) => (
                  <Badge key={step}>✓ {step}</Badge>
                ))}
              </div>
            )}
          </div>
        ))}
        {sending && (
          <div className="flex flex-col items-start gap-1">
            <div className="rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2">
              <Spinner label={`${assistant} está respondendo`} />
            </div>
            {progress.length > 0 && (
              <ul className="flex flex-col gap-0.5 pl-1 text-xs text-muted-foreground">
                {progress.map((p, i) => (
                  <li key={`${p.label}-${i}`} className={p.status === "failed" ? "text-destructive" : undefined}>
                    {MARK[p.status]} {p.label}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div ref={end} />
      </div>
      {error && (
        <div className="px-4 pb-2">
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      <div className="flex items-end gap-2 border-t border-border p-3">
        <Textarea
          aria-label="Mensagem"
          value={text}
          placeholder={placeholder}
          rows={2}
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKey}
          className="max-h-40 min-h-11 resize-none"
        />
        <Button onClick={send} loading={sending} disabled={disabled || !text.trim()}>
          Enviar
        </Button>
      </div>
    </section>
  );
}
