import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./Button";

export interface PaginationProps {
  /** Página atual, a partir de 1. */
  page: number;
  /** Total de páginas (0 quando não há itens). */
  pages: number;
  /** Itens que atendem ao filtro, somando todas as páginas. */
  total: number;
  /** Itens por página. */
  size: number;
  /** Vai para a página pedida. */
  onPage: (page: number) => void;
  /** Nome dos itens no plural, para o texto (ex.: "faturas"). Padrão: "itens". */
  noun?: string;
}

/**
 * Rodapé de lista paginada: quais itens estão na tela, de quantos, e os botões de página anterior e seguinte.
 *
 * @category Dados
 * @example
 * <Pagination page={2} pages={7} total={134} size={20} onPage={salvar} noun="faturas" />
 */
export function Pagination({ page, pages, total, size, onPage, noun = "itens" }: PaginationProps) {
  const first = total === 0 ? 0 : (page - 1) * size + 1;
  const last = Math.min(page * size, total);
  return (
    <nav aria-label="Páginas" className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
      <span aria-live="polite" className="tabular-nums">
        {total === 0 ? `Nenhum ${noun === "itens" ? "item" : "resultado"}` : `${first}–${last} de ${total.toLocaleString("pt-BR")} ${noun}`}
      </span>
      {pages > 1 && (
        <span className="flex items-center gap-2">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            <ChevronLeft aria-hidden className="size-4" />
            Anterior
          </Button>
          <span className="tabular-nums">
            {page} de {pages}
          </span>
          <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
            Próxima
            <ChevronRight aria-hidden className="size-4" />
          </Button>
        </span>
      )}
    </nav>
  );
}
