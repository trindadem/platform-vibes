import { useId } from "react";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";

export interface ToggleProps {
  /** Rótulo (também é o nome acessível). */
  label: string;
  checked: boolean;
  /** Recebe o novo estado (true = ligado). */
  onChange: (checked: boolean) => void;
  /** Esconde o rótulo na tela (ex.: dentro de uma tabela); leitores de tela continuam lendo. */
  hideLabel?: boolean;
  /** Ajuda ao lado do rótulo. */
  hint?: string;
  disabled?: boolean;
}

/**
 * Interruptor liga/desliga com efeito imediato (ativar um recurso, um modelo, uma notificação).
 *
 * @category Formulários
 * @example
 * <Toggle label="Ativo" checked={true} onChange={salvar} hint="Desligado, ninguém usa." />
 */
export function Toggle({ label, checked, onChange, hideLabel, hint, disabled }: ToggleProps) {
  const id = useId();
  return (
    <Field orientation="horizontal" className="w-auto">
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-label={hideLabel ? label : undefined}
        aria-describedby={hint ? `${id}-ajuda` : undefined}
      />
      {!hideLabel && (
        <FieldContent>
          <FieldLabel htmlFor={id}>{label}</FieldLabel>
          {hint && <FieldDescription id={`${id}-ajuda`}>{hint}</FieldDescription>}
        </FieldContent>
      )}
    </Field>
  );
}
