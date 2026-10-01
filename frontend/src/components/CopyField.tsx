import { CheckIcon, CopyIcon } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Button as UiButton } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

export interface CopyFieldProps {
  /** Rótulo visível. */
  label: string;
  /** Texto a copiar (ex.: um link de convite). */
  value: string;
  /** Ajuda abaixo do campo. */
  hint?: string;
}

/**
 * Texto somente leitura com botão de copiar, para links e códigos que a pessoa vai repassar.
 *
 * @category Formulários
 * @example
 * <CopyField label="Link do convite" value="https://app.exemplo.com/convite?codigo=abc" hint="Vale por 7 dias e para uma pessoa." />
 */
export function CopyField({ label, value, hint }: CopyFieldProps) {
  const id = useId();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
  };

  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div className="flex gap-2">
        <Input id={id} value={value} readOnly onFocus={(event) => event.target.select()} className="font-mono text-xs" />
        <UiButton type="button" variant="outline" onClick={copy} aria-live="polite">
          {copied ? <CheckIcon /> : <CopyIcon />}
          {copied ? "Copiado" : "Copiar"}
        </UiButton>
      </div>
      {hint && <FieldDescription>{hint}</FieldDescription>}
    </Field>
  );
}
