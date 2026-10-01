import { type ReactNode, useState } from "react";
import { ActionForm, type ActionFormProps } from "./ActionForm";
import { Button } from "./Button";
import { Grid } from "./Grid";
import { Page } from "./Page";
import { QueryTable, type QueryTableProps } from "./QueryTable";
import { SidePanel } from "./SidePanel";
import { Stat } from "./Stat";

export interface ResourcePageProps<T, B> {
  /** Título da tela. */
  title: string;
  /** Uma linha explicando a tela. */
  description?: string;
  /** Estado de useQuery(...) da lista (resposta é um array). */
  query: QueryTableProps<T>["query"];
  /** Colunas da lista: { key, header, render? }. */
  columns: QueryTableProps<T>["columns"];
  /** Identificador estável de cada linha (ex.: f => f.id). */
  rowKey: (row: T) => string;
  /** Título quando a lista vem vazia. */
  empty?: string;
  /** Indicadores acima da lista, calculados a partir dos itens carregados. */
  stats?: (rows: T[]) => { label: string; value: ReactNode; hint?: string }[];
  /** Criação: botão no topo que abre um painel lateral com o formulário. Na ação, use onSuccess: query.reload. */
  create?: {
    /** Texto do botão e título do painel (ex.: "Nova fatura"). */
    label: string;
    action: ActionFormProps<B>["action"];
    fields: ActionFormProps<B>["fields"];
    /** Linha de ajuda no painel. */
    description?: string;
  };
}

/**
 * Receita de tela de cadastro: título, indicadores, lista com todos os estados e criação em painel lateral.
 *
 * @category Receitas
 * @example
 * <ResourcePage
 *   title="Faturas"
 *   query={faturas}
 *   rowKey={(f) => f.id}
 *   stats={(rows) => [{ label: "Faturas", value: rows.length }]}
 *   columns={[
 *     { key: "cliente", header: "Cliente" },
 *     { key: "valor", header: "Valor", render: (f) => <Money value={f.valor} /> },
 *   ]}
 *   create={{ label: "Nova fatura", action: criar, fields: [{ name: "cliente", label: "Cliente", required: true }] }}
 * />
 */
export function ResourcePage<T, B>({ title, description, query, columns, rowKey, empty, stats, create }: ResourcePageProps<T, B>) {
  const [open, setOpen] = useState(false);
  const cards = stats && query.data ? stats(query.data) : [];

  return (
    <Page title={title} description={description} actions={create && <Button onClick={() => setOpen(true)}>{create.label}</Button>}>
      {cards.length > 0 && (
        <Grid cols={cards.length >= 4 ? 4 : cards.length === 1 ? 1 : (cards.length as 2 | 3)}>
          {cards.map((card) => (
            <Stat key={card.label} label={card.label} value={card.value} hint={card.hint} />
          ))}
        </Grid>
      )}
      <QueryTable query={query} columns={columns} rowKey={rowKey} empty={empty} caption={title} />
      {create && (
        <SidePanel open={open} onClose={() => setOpen(false)} title={create.label} description={create.description}>
          <ActionForm action={create.action} fields={create.fields} submitLabel="Criar" onDone={() => setOpen(false)} />
        </SidePanel>
      )}
    </Page>
  );
}
