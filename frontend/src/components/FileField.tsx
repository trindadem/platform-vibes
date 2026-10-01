import { useId } from "react";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

export interface FileFieldProps {
  /** Rótulo visível (também é o nome acessível). */
  label: string;
  /** Estado de useUpload(...) (src/core/api.ts): o campo chama upload.run(arquivo) assim que o arquivo é escolhido. */
  upload: { run: (file: File) => Promise<unknown>; running: boolean; error: { message: string } | null };
  /** Tipos aceitos no seletor (ex.: "image/png,image/jpeg"). A validação de verdade é do serviço. */
  accept?: string;
  /** Ajuda abaixo do campo (tipos e tamanho máximo). */
  hint?: string;
}

/**
 * Escolha de um arquivo que é enviado na hora, direto ao armazenamento, com erro e estado de envio.
 *
 * @category Formulários
 * @example
 * <FileField label="Logo" upload={logo} accept="image/*" hint="Até 2 MB." />
 */
export function FileField({ label, upload, accept, hint }: FileFieldProps) {
  const id = useId();
  const help = upload.error ? `${id}-erro` : hint ? `${id}-ajuda` : undefined;
  return (
    <Field data-invalid={upload.error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type="file"
        accept={accept}
        disabled={upload.running}
        aria-busy={upload.running}
        aria-invalid={upload.error ? true : undefined}
        aria-describedby={help}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void upload.run(file);
        }}
      />
      {upload.error ? <FieldError id={help}>{upload.error.message}</FieldError> : hint && <FieldDescription id={help}>{hint}</FieldDescription>}
    </Field>
  );
}
