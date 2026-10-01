import { type ReactNode, useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { DataTable, type DataTableProps } from "./DataTable";
import { EmptyState } from "./EmptyState";
import { Pagination } from "./Pagination";
import { QueryView } from "./QueryView";
import { SelectField } from "./SelectField";
import { Spinner } from "./Spinner";
import { TextField } from "./TextField";

const ALL = "__todos"; // o Select não aceita valor vazio: "Todos" usa este marcador e remove o filtro
const DEFAULT_SORT = "__padrao";
const WAIT_MS = 300; // espera entre a digitação e a busca

export interface ListViewProps<T> {
  /** Estado de useListQuery(...) (src/core/api.ts): página carregada e parâmetros da URL. */
  list: {
    data: { items: T[]; total: number; page: number; size: number; pages: number } | null;
    loading: boolean;
    error: { message: string } | null;
    reload: () => void;
    params: Record<string, string>;
    set: (changes: Record<string, string | number | null | undefined>) => void;
  };
  /** Colunas como em DataTable; sort é o campo que ordena a coluna (precisa estar no sortable do backend). */
  columns: DataTableProps<T>["columns"];
  /** Identificador estável de cada linha (ex.: f => f.id). */
  rowKey: (row: T) => string;
  /** Liga a busca por texto e mostra este exemplo no campo (ex.: "cliente ou descrição"). */
  search?: string;
  /** Filtros de escolha única: name é o parâmetro da lista no backend (ex.: status). */
  filters?: { name: string; label: string; options: { value: string; label: string }[] }[];
  /** Título quando ainda não há nenhum item. Padrão: "Nada por aqui ainda." */
  empty?: string;
  /** Nome dos itens no plural, para o rodapé (ex.: "faturas"). Padrão: "itens". */
  noun?: string;
  /** Legenda acessível da tabela. */
  caption?: string;
  /** Ações ao lado da busca (ex.: botão de criar). */
  actions?: ReactNode;
}

/**
 * Receita de lista paginada no servidor: busca por texto, filtros, ordenação no cabeçalho, páginas e todos os estados.
 * Os parâmetros ficam na URL: voltar, recarregar e compartilhar o link mantêm o que a pessoa escolheu.
 *
 * @category Receitas
 * @example
 * <ListView
 *   list={lista}
 *   rowKey={(f) => f.id}
 *   search="cliente"
 *   filters={[{ name: "status", label: "Status", options: [{ value: "aberta", label: "Aberta" }, { value: "paga", label: "Paga" }] }]}
 *   columns={[
 *     { key: "cliente", header: "Cliente", sort: "cliente" },
 *     { key: "valor", header: "Valor", sort: "valor", render: (f) => <Money value={f.valor} /> },
 *   ]}
 *   noun="faturas"
 * />
 */
export function ListView<T>({ list, columns, rowKey, search, filters = [], empty, noun, caption, actions }: ListViewProps<T>) {
  const { params, set } = list;
  const [text, setText] = useState(params.q ?? "");
  const typed = useRef(false);
  const latestSet = useRef(set);
  latestSet.current = set;
  useEffect(() => {
    if (!typed.current) return; // só busca depois que a pessoa digita (não ao abrir a tela)
    const timer = setTimeout(() => latestSet.current({ q: text.trim() }), WAIT_MS);
    return () => clearTimeout(timer);
  }, [text]);

  const narrowed = Boolean(params.q) || filters.some((f) => params[f.name]);
  const sortable = columns.filter((c) => c.sort);
  const clear = () => {
    typed.current = false;
    setText("");
    set({ q: null, ...Object.fromEntries(filters.map((f) => [f.name, null])) });
  };

  return (
    <div className="flex flex-col gap-4">
      {(search || filters.length > 0 || sortable.length > 0 || actions) && (
        <div className="flex flex-wrap items-end gap-3 *:min-w-40 *:flex-1 @container">
          {search && (
            <TextField
              label="Buscar"
              type="search"
              value={text}
              placeholder={search}
              onChange={(value) => {
                typed.current = true;
                setText(value);
              }}
            />
          )}
          {filters.map((filter) => (
            <SelectField
              key={filter.name}
              label={filter.label}
              value={params[filter.name] ?? ALL}
              onChange={(value) => set({ [filter.name]: value === ALL ? null : value })}
              options={[{ value: ALL, label: "Todos" }, ...filter.options]}
            />
          ))}
          {sortable.length > 0 && (
            <div className="lg:hidden">
              <SelectField
                label="Ordenar por"
                value={params.sort ?? DEFAULT_SORT}
                onChange={(value) => set({ sort: value === DEFAULT_SORT ? null : value })}
                options={[
                  { value: DEFAULT_SORT, label: "Padrão" },
                  ...sortable.flatMap((c) => [
                    { value: c.sort!, label: `${c.header} (crescente)` },
                    { value: `-${c.sort}`, label: `${c.header} (decrescente)` },
                  ]),
                ]}
              />
            </div>
          )}
          {actions && <div className="flex flex-none justify-end gap-2">{actions}</div>}
        </div>
      )}
      <QueryView query={list}>
        {(page) => (
          <div className="flex flex-col gap-3" aria-busy={list.loading}>
            {page.total === 0 ? (
              narrowed ? (
                <EmptyState
                  title="Nenhum resultado"
                  description="Nada atende à busca ou aos filtros escolhidos."
                  action={
                    <Button variant="secondary" onClick={clear}>
                      Limpar busca e filtros
                    </Button>
                  }
                />
              ) : (
                <EmptyState title={empty ?? "Nada por aqui ainda."} />
              )
            ) : (
              <DataTable
                rows={page.items}
                columns={columns}
                rowKey={rowKey}
                caption={caption}
                sort={params.sort ?? null}
                onSort={(sort) => set({ sort })}
              />
            )}
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Pagination page={page.page} pages={page.pages} total={page.total} size={page.size} noun={noun} onPage={(n) => set({ page: n })} />
              </div>
              {list.loading && <Spinner label="Atualizando" />}
            </div>
          </div>
        )}
      </QueryView>
    </div>
  );
}
