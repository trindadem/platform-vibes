import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { Tabs as TabsRoot, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface TabsProps {
  /** Abas na ordem: { id, label, content }. O id vira o fragmento da URL (/tela#id); só a aba aberta fica montada. */
  tabs: { id: string; label: string; content: ReactNode }[];
}

/**
 * Abas que dividem uma tela em partes do mesmo assunto. A aba aberta fica no fragmento da URL (/tela#modelos):
 * link direto e recarregar mantêm a aba, e os parâmetros de lista (?q=, ?page=) ficam só para as listas.
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
export function Tabs({ tabs }: TabsProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const requested = decodeURIComponent(location.hash.slice(1));
  const current = tabs.some((tab) => tab.id === requested) ? requested : tabs[0]?.id;
  const open = (id: string) => navigate({ pathname: location.pathname, search: location.search, hash: id }, { replace: true });

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
