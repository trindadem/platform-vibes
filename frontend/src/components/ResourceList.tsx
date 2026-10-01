import { type ReactNode, useState } from "react";
import { ActionForm, type ActionFormProps } from "./ActionForm";
import { Alert } from "./Alert";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { ConfirmButton } from "./ConfirmButton";
import type { DataTableProps } from "./DataTable";
import { DateTime } from "./DateTime";
import { ListView, type ListViewProps } from "./ListView";
import { Money } from "./Money";
import { Row } from "./Row";
import { SidePanel } from "./SidePanel";

type Kind = "text" | "textarea" | "email" | "phone" | "number" | "money" | "date" | "datetime" | "select" | "boolean";
type Field = { name: string; label: string; kind: Kind; required: boolean; options?: { value: string; label: string }[]; hint?: string };
type Action<B> = { run: (body: B) => Promise<unknown>; running: boolean; error: ActionFormProps<unknown>["action"]["error"] };

export interface ResourceListProps<T extends { id: string }> {
  /** Estado de useResource(modulo.cadastro) (src/core/api.ts): lista, ações e os campos que o backend declarou. */
  resource: {
    list: ListViewProps<T>["list"];
    create: Action<never>;
    update: Action<never>;
    remove: Action<{ id: string }>;
    meta: {
      title: string;
      fields: Field[];
      columns: { key: string; header: string; kind: Kind; sort?: string }[];
      filters: { name: string; label: string; options: { value: string; label: string }[] }[];
      search: string | null;
    };
  };
  /** Colunas no lugar das declaradas (ex.: com uma coluna calculada). */
  columns?: DataTableProps<T>["columns"];
  /** Ações a mais em cada linha (ex.: um Button que abre a tela do registro). */
  rowActions?: (row: T) => ReactNode;
  /** Nome de um item, para os botões e painéis (ex.: "cliente"). Padrão: "registro". */
  noun?: string;
  /** Só a lista: sem criar, editar e remover (ex.: para quem não tem o papel de escrita). */
  readOnly?: boolean;
}

/**
 * Receita de cadastro inteiro: lista com busca, filtros, ordem e páginas, criação e edição em painel lateral e remoção
 * com confirmação, tudo a partir dos campos declarados no backend (core/resources.py).
 *
 * @category Receitas
 * @example
 * <ResourceList resource={cadastro} noun="fatura" />
 */
export function ResourceList<T extends { id: string }>({ resource, columns, rowActions, noun = "registro", readOnly }: ResourceListProps<T>) {
  const { list, create, update, remove, meta } = resource;
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<T | null>(null);
  const fields = meta.fields.map(formField);
  const save: Action<Record<string, unknown>> = {
    ...update,
    run: (body) => update.run({ ...body, id: editing?.id } as never),
  };
  const shown: DataTableProps<T>["columns"] = columns ?? meta.columns.map((c) => ({ ...c, render: (row: T) => cell(c.kind, value(row, c.key), meta.fields.find((f) => f.name === c.key)) }));
  const actions = !readOnly || rowActions;
  return (
    <>
      {remove.error && <Alert tone="danger">{remove.error.message}</Alert>}
      <ListView
        list={list}
        rowKey={(row) => row.id}
        search={meta.search ?? undefined}
        filters={meta.filters}
        noun={meta.title.toLowerCase()}
        empty={`Nenhum ${noun} ainda.`}
        caption={meta.title}
        actions={!readOnly && <Button onClick={() => setCreating(true)}>Novo {noun}</Button>}
        columns={
          actions
            ? [
                ...shown,
                {
                  key: "acoes",
                  header: "",
                  render: (row: T) => (
                    <Row gap="sm" wrap={false} justify="end">
                      {rowActions?.(row)}
                      {!readOnly && (
                        <Button size="sm" variant="ghost" onClick={() => setEditing(row)}>
                          Editar
                        </Button>
                      )}
                      {!readOnly && (
                        <ConfirmButton confirmLabel="Remover agora" loading={remove.running} onConfirm={() => void remove.run({ id: row.id })}>
                          Remover
                        </ConfirmButton>
                      )}
                    </Row>
                  ),
                },
              ]
            : shown
        }
      />
      <SidePanel open={creating} onClose={() => setCreating(false)} title={`Novo ${noun}`} description={meta.title}>
        <ActionForm action={create as Action<Record<string, unknown>>} submitLabel="Criar" onDone={() => setCreating(false)} fields={fields} />
      </SidePanel>
      <SidePanel open={editing !== null} onClose={() => setEditing(null)} title={`Editar ${noun}`} description={meta.title}>
        {editing && <ActionForm key={editing.id} action={save} submitLabel="Salvar" onDone={() => setEditing(null)} initial={initial(editing, meta.fields)} fields={fields} />}
      </SidePanel>
    </>
  );
}

type FormField = ActionFormProps<Record<string, unknown>>["fields"][number];
const FORM_KIND: Record<Kind, NonNullable<FormField["kind"]>> = {
  text: "text",
  textarea: "textarea",
  email: "email",
  phone: "tel",
  number: "number",
  money: "number",
  date: "date",
  datetime: "datetime",
  select: "select",
  boolean: "boolean",
};

/** Campo do backend → campo do ActionForm. */
function formField(f: Field): FormField {
  return { name: f.name, label: f.label, kind: FORM_KIND[f.kind], required: f.required, hint: f.hint, options: f.options };
}

function value(row: unknown, key: string): unknown {
  return (row as Record<string, unknown>)[key];
}

/** Registro → valores iniciais do formulário de edição (texto, como o ActionForm guarda). */
function initial(row: unknown, fields: Field[]): Record<string, string> {
  return Object.fromEntries(
    fields.map((f) => {
      const v = value(row, f.name);
      if (v === null || v === undefined) return [f.name, ""];
      if (f.kind === "datetime") return [f.name, String(v).slice(0, 16)];
      return [f.name, String(v)];
    }),
  );
}

/** Célula formatada pelo tipo do campo. */
function cell(kind: Kind, v: unknown, field?: Field): ReactNode {
  if (v === null || v === undefined || v === "") return "—";
  if (kind === "money") return <Money value={Number(v)} />;
  if (kind === "date") return <DateTime value={String(v)} format="date" />;
  if (kind === "datetime") return <DateTime value={String(v)} />;
  if (kind === "boolean") return v ? "Sim" : "Não";
  if (kind === "select") return <Badge>{field?.options?.find((o) => o.value === String(v))?.label ?? String(v)}</Badge>;
  return String(v);
}
