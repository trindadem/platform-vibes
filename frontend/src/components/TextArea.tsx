import { useId } from "react";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";

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
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>
        {label}
        {required && <span className="text-destructive">*</span>}
      </FieldLabel>
      <Textarea
        id={id}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        placeholder={placeholder}
        spellCheck={!monospace}
        aria-invalid={error ? true : undefined}
        aria-describedby={help}
        className={monospace ? "font-mono text-xs break-all" : undefined}
      />
      {error ? <FieldError id={help}>{error}</FieldError> : hint && <FieldDescription id={help}>{hint}</FieldDescription>}
    </Field>
  );
}
