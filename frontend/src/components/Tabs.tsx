import type { ReactNode } from "react";
import { useSearchParams } from "react-router";
import { Tabs as TabsRoot, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface TabsProps {
  /** Abas na ordem: { id, label, content }. Só o conteúdo da aba aberta fica montado. */
  tabs: { id: string; label: string; content: ReactNode }[];
  /** Parâmetro da URL que guarda a aba aberta (link direto e recarregar mantêm a aba). Padrão: "aba". */
  param?: string;
}

/**
 * Abas que dividem uma tela em partes do mesmo assunto; a aba aberta fica na URL (?aba=...).
 *
 * @category Layout
 * @example
 * <Tabs
 *   tabs={[
 *     { id: "resumo", label: "Resumo", content: <Text>12 faturas emitidas.</Text> },
 *     { id: "itens", label: "Itens", content: <Text>Itens da fatura.</Text> },
 *   ]}
 * />
 */
export function Tabs({ tabs, param = "aba" }: TabsProps) {
  const [search, setSearch] = useSearchParams();
  const requested = search.get(param);
  const current = tabs.some((tab) => tab.id === requested) ? requested! : tabs[0]?.id;
  const open = (id: string) =>
    setSearch(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set(param, id);
        return next;
      },
      { replace: true },
    );

  return (
    <TabsRoot value={current} onValueChange={open} className="gap-4">
      <TabsList className="max-w-full overflow-x-auto overflow-y-hidden">
        {tabs.map((tab) => (
          <TabsTrigger key={tab.id} value={tab.id}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent key={tab.id} value={tab.id} className="flex flex-col gap-4">
          {tab.content}
        </TabsContent>
      ))}
    </TabsRoot>
  );
}
