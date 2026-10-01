import { useState } from "react";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Form } from "./Form";
import { Row } from "./Row";
import { SelectField } from "./SelectField";
import { TextArea } from "./TextArea";
import { TextField } from "./TextField";

type Values = Record<string, string>;

const YES_NO = [
  { value: "true", label: "Sim" },
  { value: "false", label: "Não" },
];

export interface ActionFormProps<B> {
  /** Estado de useAction(...) (src/core/api.ts): o formulário chama action.run(valores). */
  action: {
    run: (body: B) => Promise<unknown>;
    running: boolean;
    error: { message: string; details?: { loc?: (string | number)[]; msg?: string; type?: string }[] } | null;
  };
  /** Campos na ordem. name é a chave do corpo da ação (o TypeScript confere); kind padrão text; number vira número; select usa options; boolean vira true/false (Sim/Não); color dá #rrggbb; date e datetime dão a data no formato ISO. */
  fields: {
    name: keyof B & string;
    label: string;
    kind?: "text" | "email" | "password" | "number" | "textarea" | "select" | "boolean" | "color" | "tel" | "date" | "datetime";
    required?: boolean;
    placeholder?: string;
    hint?: string;
    options?: { value: string; label: string }[];
    /** Dica de preenchimento automático (ex.: "email", "current-password", "new-password"). */
    autoComplete?: string;
  }[];
  /** Texto do botão de envio. Padrão: "Salvar". */
  submitLabel?: string;
  /** Mensagem exibida após sucesso (o formulário é limpo). */
  successMessage?: string;
  /** Valores iniciais por campo (edição). Campo opcional que tinha valor e foi esvaziado vai como null: apaga. */
  initial?: Partial<Record<keyof B & string, string>>;
  /** Chamado após sucesso (ex.: fechar o painel). */
  onDone?: () => void;
}

/**
 * Receita de formulário: campos a partir de uma lista, envio pela ação, erro do servidor no campo certo.
 *
 * @category Receitas
 * @example
 * <ActionForm
 *   action={criar}
 *   submitLabel="Emitir"
 *   successMessage="Fatura emitida."
 *   fields={[
 *     { name: "cliente", label: "Cliente", required: true },
 *     { name: "valor", label: "Valor (R$)", kind: "number", required: true },
 *     { name: "status", label: "Status", kind: "select", options: [{ value: "aberta", label: "Aberta" }, { value: "paga", label: "Paga" }] },
 *   ]}
 * />
 */
export function ActionForm<B>({ action, fields, submitLabel = "Salvar", successMessage, initial, onDone }: ActionFormProps<B>) {
  const start = (): Values => Object.fromEntries(fields.map((f) => [f.name, initial?.[f.name] ?? ""]));
  const [values, setValues] = useState<Values>(start);
  const [done, setDone] = useState(false);
  // Campo editado depois do envio não mostra mais o erro antigo do servidor.
  const [edited, setEdited] = useState<ReadonlySet<string>>(new Set());
  const set = (name: string) => (value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
    setEdited((current) => new Set(current).add(name));
  };

  // 422 do backend: cada detalhe aponta o campo pelo último trecho de loc (ex.: ["body", "cliente"]).
  const fieldErrors: Record<string, string> = {};
  for (const detail of action.error?.details ?? []) {
    const name = [...(detail.loc ?? [])].reverse().find((part) => fields.some((f) => f.name === part));
    if (typeof name === "string" && !edited.has(name)) fieldErrors[name] = detail.msg ?? "Valor inválido.";
  }
  const pointsToFields = (action.error?.details ?? []).some((d) => d.loc?.some((part) => fields.some((f) => f.name === part)));
  const generalError = action.error && !pointsToFields ? action.error.message : null;

  const submit = async () => {
    setDone(false);
    setEdited(new Set());
    const body: Record<string, string | number | boolean | null> = {};
    for (const field of fields) {
      const raw = values[field.name] ?? "";
      if (raw === "" && !field.required) {
        if (initial?.[field.name]) body[field.name] = null; // tinha valor e foi apagado: vai null, e o backend apaga
        continue;
      }
      body[field.name] = field.kind === "number" ? Number(raw.replace(",", ".")) : field.kind === "boolean" ? raw === "true" : raw;
    }
    const result = await action.run(body as B);
    if (result !== undefined) {
      setValues(start());
      setDone(true);
      onDone?.();
    }
  };

  return (
    <Form onSubmit={submit} busy={action.running}>
      {generalError && <Alert tone="danger" title="Não foi possível concluir">{generalError}</Alert>}
      {done && successMessage && <Alert tone="success">{successMessage}</Alert>}
      {fields.map((field) => {
        const common = {
          label: field.label,
          value: values[field.name] ?? "",
          onChange: set(field.name),
          required: field.required,
          placeholder: field.placeholder,
          hint: field.hint,
          error: fieldErrors[field.name],
        };
        if (field.kind === "textarea") return <TextArea key={field.name} {...common} />;
        if (field.kind === "select") return <SelectField key={field.name} {...common} options={field.options ?? []} />;
        if (field.kind === "boolean") return <SelectField key={field.name} {...common} options={field.options ?? YES_NO} />;
        const type = field.kind === "datetime" ? "datetime-local" : (field.kind ?? "text");
        return <TextField key={field.name} {...common} type={type} autoComplete={field.autoComplete} />;
      })}
      <Row>
        <Button type="submit" loading={action.running}>
          {submitLabel}
        </Button>
      </Row>
    </Form>
  );
}
