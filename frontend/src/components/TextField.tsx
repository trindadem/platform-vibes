import { useId } from "react";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

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
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>
        {label}
        {required && <span className="text-destructive">*</span>}
      </FieldLabel>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        placeholder={placeholder}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={help}
      />
      {error ? <FieldError id={help}>{error}</FieldError> : hint && <FieldDescription id={help}>{hint}</FieldDescription>}
    </Field>
  );
}
