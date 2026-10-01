import { useId } from "react";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface SelectFieldProps {
  /** Rótulo visível (também é o nome acessível). */
  label: string;
  value: string;
  /** Recebe o valor escolhido. */
  onChange: (value: string) => void;
  /** Opções: { value: "BRL", label: "Real" }. */
  options: { value: string; label: string }[];
  /** Texto quando nada foi escolhido. Padrão: "Selecione". */
  placeholder?: string;
  /** Ajuda abaixo do campo. */
  hint?: string;
  /** Mensagem de erro: marca o campo como inválido. */
  error?: string;
  required?: boolean;
}

/** Lista de opções com rótulo, ajuda e erro ligados para acessibilidade. */
export function SelectField({ label, value, onChange, options, placeholder = "Selecione", hint, error, required }: SelectFieldProps) {
  const id = useId();
  const help = error ? `${id}-erro` : hint ? `${id}-ajuda` : undefined;
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>
        {label}
        {required && <span className="text-destructive">*</span>}
      </FieldLabel>
      <Select value={value} onValueChange={onChange} required={required}>
        <SelectTrigger id={id} className="w-full" aria-invalid={error ? true : undefined} aria-describedby={help}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error ? <FieldError id={help}>{error}</FieldError> : hint && <FieldDescription id={help}>{hint}</FieldDescription>}
    </Field>
  );
}
