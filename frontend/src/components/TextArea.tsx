import { useId } from "react";

export interface TextAreaProps {
  /** Rótulo visível (também é o nome acessível). */
  label: string;
  value: string;
  /** Recebe o novo texto, não o evento. */
  onChange: (value: string) => void;
  /** Linhas visíveis. Padrão: 4. */
  rows?: number;
  /** Ajuda abaixo do campo. */
  hint?: string;
  /** Mensagem de erro: marca o campo como inválido. */
  error?: string;
  required?: boolean;
  placeholder?: string;
  /** Fonte monoespaçada (tokens, JSON, código). Padrão: false. */
  monospace?: boolean;
}

/** Campo de texto de várias linhas com rótulo, ajuda e erro ligados para acessibilidade. */
export function TextArea({ label, value, onChange, rows = 4, hint, error, required, placeholder, monospace = false }: TextAreaProps) {
  const id = useId();
  const help = error ? `${id}-erro` : hint ? `${id}-ajuda` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {required && <span className="text-danger"> *</span>}
      </label>
      <textarea
        id={id}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        placeholder={placeholder}
        spellCheck={!monospace}
        aria-invalid={error ? true : undefined}
        aria-describedby={help}
        className={`rounded-control border bg-panel px-3 py-2 text-sm outline-accent placeholder:text-muted focus-visible:outline-2 ${monospace ? "font-mono break-all" : ""} ${error ? "border-danger" : "border-line"}`}
      />
      {error ? (
        <p id={help} className="text-sm text-danger">{error}</p>
      ) : (
        hint && <p id={help} className="text-sm text-muted">{hint}</p>
      )}
    </div>
  );
}
