import { useId } from "react";

export interface TextFieldProps {
  /** Rótulo visível (também é o nome acessível). */
  label: string;
  value: string;
  /** Recebe o novo texto, não o evento. */
  onChange: (value: string) => void;
  /** Padrão: text. */
  type?: "text" | "email" | "password" | "number" | "search" | "url";
  /** Ajuda abaixo do campo. */
  hint?: string;
  /** Mensagem de erro: marca o campo como inválido. */
  error?: string;
  required?: boolean;
  placeholder?: string;
  /** Dica para o preenchimento automático do navegador (ex.: "email", "current-password"). */
  autoComplete?: string;
}

/** Campo de texto de uma linha com rótulo, ajuda e erro ligados para acessibilidade. */
export function TextField({ label, value, onChange, type = "text", hint, error, required, placeholder, autoComplete }: TextFieldProps) {
  const id = useId();
  const help = error ? `${id}-erro` : hint ? `${id}-ajuda` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {required && <span className="text-danger"> *</span>}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        placeholder={placeholder}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={help}
        className={`h-10 rounded-control border bg-panel px-3 text-sm outline-accent placeholder:text-muted focus-visible:outline-2 ${error ? "border-danger" : "border-line"}`}
      />
      {error ? (
        <p id={help} className="text-sm text-danger">{error}</p>
      ) : (
        hint && <p id={help} className="text-sm text-muted">{hint}</p>
      )}
    </div>
  );
}
