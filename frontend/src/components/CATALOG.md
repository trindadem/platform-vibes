# Catálogo de componentes

> Gerado por `vite.config.ts` a partir de `src/components/*.tsx` em todo `npm run dev` e `npm run build`. Não edite.
> Como usar: leia o índice, escolha as peças (receitas primeiro) e copie o exemplo da seção de cada uma.
> Dados vêm de `useQuery`/`useAction` com as funções de `src/core/contracts.ts`. Faltou peça? Crie
> `src/components/<Nome>.tsx` com JSDoc (frase, `@category`, `@example`) e `<Nome>Props` documentado.
> Os exemplos usam dados fictícios (`faturas`, `lista`, `fatura`, `criar`, `nome`...) e o TypeScript confere cada um.

## Índice (53)

**Receitas**: telas e dados prontos: comece por aqui

- [ActionForm](#actionform): Receita de formulário: campos a partir de uma lista, envio pela ação, erro do servidor no campo certo. `action, fields, submitLabel?, successMessage?, initial?, onDone?`
- [ChatThread](#chatthread): Receita de conversa com um agente: mensagens em balões, passos do agente enquanto responde, erro e campo de envio. `messages, onSend, sending?, progress?, error?, assistant?, placeholder?, disabled?`
- [ListView](#listview): Receita de lista paginada no servidor: busca por texto, filtros, ordenação no cabeçalho, páginas e todos os estados. `list, columns, rowKey, search?, filters?, empty?, noun?, caption?, actions?`
- [ProcessResults](#processresults): Receita de resultados de processos: um cartão por processo com a autonomia mês a mês (a versão publicada marcada no mês em que entrou), os números do mês, como as execuções terminaram e os indicadores de negócio, cada um na unidade dele (R$, %, dias, horas). `processes, empty?`
- [QueryTable](#querytable): Receita de lista: consulta + tabela, com carregamento, erro, vazio e cartões em espaço estreito. `query, columns, rowKey, empty?, caption?`
- [QueryView](#queryview): Receita de consulta: mostra esqueleto ao carregar, erro com "Tentar de novo", vazio ou os dados. `query, children, empty?`
- [ResourceList](#resourcelist): Receita de cadastro inteiro: lista com busca, filtros, ordem e páginas, criação e edição em painel lateral e remoção com confirmação, tudo a partir dos campos declarados no backend (core/resources.py). `resource, columns?, rowActions?, noun?, readOnly?`
- [ResourcePage](#resourcepage): Receita de tela de cadastro: título, indicadores, lista com todos os estados e criação em painel lateral. `title, query, columns, rowKey, description?, empty?, stats?, create?`

**Layout**: estrutura da tela

- [Card](#card): Superfície que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais. `title?, description?, footer?, children?`
- [Columns](#columns): Duas colunas: o principal e uma lateral fixa (ex.: conversa e o perfil sendo preenchido); no celular, uma abaixo da outra. `children, aside, asideWidth?`
- [Grid](#grid): Grade responsiva para cartões e indicadores: 1 coluna no celular, até 4 em telas largas. `children, cols?`
- [Page](#page): Estrutura de uma tela: título, descrição, ações e conteúdo com o espaçamento padrão. `title, children, description?, actions?`
- [Row](#row): Coloca itens lado a lado, com alinhamento e quebra de linha controlados. `children, gap?, align?, justify?, wrap?`
- [SidePanel](#sidepanel): Painel que desliza da direita sobre a tela, para editar ou criar sem sair dela (ocupa a tela no celular). `open, onClose, title, children, description?`
- [Stack](#stack): Empilha itens na vertical com espaçamento uniforme. `children, gap?`
- [Tabs](#tabs): Abas que dividem uma tela em partes do mesmo assunto. `tabs`

**Dados**: registros e números

- [BpmnDiagram](#bpmndiagram): Diagrama BPMN somente leitura (bpmn-js), com zoom e arrasto, o caminho percorrido em destaque e os passos com problema. `xml, label, highlight?, problems?`
- [DataTable](#datatable): Tabela de dados tipada. `columns, rows, rowKey, empty?, caption?, sort?, onSort?`
- [JourneySteps](#journeysteps): Jornada em passos numerados: o que já foi feito, o passo de agora em destaque e os próximos, com o caminho de cada um. `steps`
- [KeyValue](#keyvalue): Lista de pares rótulo/valor para detalhes de um registro. `items, stacked?`
- [MonthlyBars](#monthlybars): Barras de uma taxa mês a mês (0 a 100%), com a marca do que mudou em cada mês, como a versão publicada. `label, items`
- [Pagination](#pagination): Rodapé de lista paginada: quais itens estão na tela, de quantos, e os botões de página anterior e seguinte. `page, pages, total, size, onPage, noun?`
- [Picture](#picture): Imagem quadrada que se ajusta ao espaço sem distorcer (logo, foto de perfil, miniatura). `src, alt, size?`
- [ProjectChain](#projectchain): Projeto: a cadeia de processos que um começou (uma proposta aceita inicia o contrato e o faturamento), com cada execução, o que ela espera e o caminho para abri-la. `title, status, steps, description?`
- [ResultsCard](#resultscard): Os resultados de um processo num mês: a taxa mês a mês com as marcas, os números do mês, como terminaram e os indicadores. `title, months, monthsLabel, counts, ends, indicators, description?, badges?`
- [Stat](#stat): Indicador em destaque: rótulo, valor grande e contexto. `label, value, hint?, tone?`
- [UsageMeter](#usagemeter): Barra de uso de um limite: quanto foi usado de quanto é permitido, em alerta a partir de 80% e cheia em 100%. `label, used, limit, format?, hint?`

**Formatação**: dinheiro, datas, status e códigos

- [Badge](#badge): Etiqueta curta para status, papéis ou categorias. `children, tone?`
- [Code](#code): Trecho de código, comando ou identificador em fonte monoespaçada. `children, block?`
- [DateTime](#datetime): Data e hora em pt-BR; a data completa aparece ao passar o mouse. `value, format?`
- [Money](#money): Valor monetário em pt-BR (R$ 1.234,56), com algarismos alinhados em tabelas. `value, currency?, digits?`
- [Quantity](#quantity): Quantidade em pt-BR com separador de milhar (1.234.567) ou curta (1,2 mi), alinhada em tabelas. `value, compact?, unit?`
- [StatusBadge](#statusbadge): Status como etiqueta colorida, com cor automática para valores comuns (pago, pendente, erro...). `value, tones?, labels?`

**Formulários**: campos e ações

- [Button](#button): Botão de ação com variantes, tamanhos e estado de carregamento. `children, variant?, size?, type?, loading?, disabled?, onClick?, to?`
- [ConfirmButton](#confirmbutton): Botão para ação destrutiva que pede um segundo clique de confirmação (volta sozinho em 4 s). `children, onConfirm, confirmLabel?, loading?, size?`
- [CopyField](#copyfield): Texto somente leitura com botão de copiar, para links e códigos que a pessoa vai repassar. `label, value, hint?`
- [FileField](#filefield): Escolha de um arquivo que é enviado na hora, direto ao armazenamento, com erro e estado de envio. `label, upload, accept?, hint?`
- [Form](#form): Formulário com campos espaçados de forma uniforme e envio sem recarregar a página. `onSubmit, children, busy?`
- [SelectField](#selectfield): Lista de opções com rótulo, ajuda e erro ligados para acessibilidade. `label, value, onChange, options, placeholder?, hint?, error?, required?`
- [TextArea](#textarea): Campo de texto de várias linhas com rótulo, ajuda e erro ligados para acessibilidade. `label, value, onChange, rows?, hint?, error?, required?, placeholder?, monospace?`
- [TextField](#textfield): Campo de texto de uma linha com rótulo, ajuda e erro ligados para acessibilidade. `label, value, onChange, type?, hint?, error?, required?, placeholder?, autoComplete?`
- [Toggle](#toggle): Interruptor liga/desliga com efeito imediato (ativar um recurso, um modelo, uma notificação). `label, checked, onChange, hideLabel?, hint?, disabled?`

**Feedback**: avisos, carregamento e vazio

- [Alert](#alert): Mensagem de destaque para resultado, aviso ou erro, com ícone conforme a gravidade. `tone?, title?, children?`
- [EmptyState](#emptystate): Espaço reservado para lista vazia, página inexistente ou recurso indisponível. `title, description?, action?`
- [Spinner](#spinner): Indicador de carregamento acessível, com texto. `label?`

**Texto**: títulos e parágrafos

- [Heading](#heading): Título de seção dentro de uma tela (h2 ou h3). `children, level?`
- [Text](#text): Parágrafo de texto com tom e tamanho padronizados. `children, tone?, size?`
- [TextLink](#textlink): Link no meio do texto para outra tela da aplicação. `to, children`

**Aplicação**: moldura e sessão (usados pelo App.tsx, não pelas páginas)

- [AppShell](#appshell): Moldura da aplicação: menu lateral em grupos (gaveta no celular), marca com logo e cor, barra superior com a tela atual e conteúdo centralizado. `brand, nav, children, logo?, color?, aside?, switcher?, actions?`
- [AuthShell](#authshell): Moldura das telas abertas (entrar, cadastro, convite): marca no topo e conteúdo numa coluna estreita e centralizada. `brand, children`
- [NotificationBell](#notificationbell): Sino da barra superior com a quantidade de avisos não lidos; leva à lista de avisos. `count, to?`
- [SessionStatus](#sessionstatus): Sessão no pé do menu: avatar com iniciais e menu para sair, ou aviso de que não há sessão. `user, onSignOut, detail?`
- [TenantSwitcher](#tenantswitcher): Seletor da organização ativa no topo do menu lateral, com a opção de criar outra. `tenants, current, onSwitch, onCreate?`

---

## ActionForm

Receita de formulário: campos a partir de uma lista, envio pela ação, erro do servidor no campo certo. _(Receitas)_

```tsx
<ActionForm
  action={criar}
  submitLabel="Emitir"
  successMessage="Fatura emitida."
  fields={[
    { name: "cliente", label: "Cliente", required: true },
    { name: "valor", label: "Valor (R$)", kind: "number", required: true },
    { name: "status", label: "Status", kind: "select", options: [{ value: "aberta", label: "Aberta" }, { value: "paga", label: "Paga" }] },
  ]}
/>
```

- `action`: `{ run: (body: B) => Promise<unknown>; running: boolean; error: { message: string; details?: { loc?: (string | number)[]; msg?: string; type?: string }[] } | null; }`: Estado de useAction(...) (src/core/api.ts): o formulário chama action.run(valores).
- `fields`: `{ name: keyof B & string; label: string; kind?: "text" | "email" | "password" | "number" | "textarea" | "select" | "boolean" | "color" | "tel" | "date" | "datetime"; required?: boolean; placeholder?: string; hint?: string; options?: { value: string; label: string }[]; /** Dica de preenchimento automático (ex.: "email", "current-password", "new-password"). */ autoComplete?: string; }[]`: Campos na ordem. name é a chave do corpo da ação (o TypeScript confere); kind padrão text; number vira número; select usa options; boolean vira true/false (Sim/Não); color dá #rrggbb; date e datetime dão a data no formato ISO.
- `submitLabel?`: `string`: Texto do botão de envio. Padrão: "Salvar".
- `successMessage?`: `string`: Mensagem exibida após sucesso (o formulário é limpo).
- `initial?`: `Partial<Record<keyof B & string, string>>`: Valores iniciais por campo (edição). Campo opcional que tinha valor e foi esvaziado vai como null: apaga.
- `onDone?`: `() => void`: Chamado após sucesso (ex.: fechar o painel).

---

## ChatThread

Receita de conversa com um agente: mensagens em balões, passos do agente enquanto responde, erro e campo de envio. _(Receitas)_

```tsx
<ChatThread
  messages={[
    { id: "1", role: "assistant", text: "Olá! O que a sua empresa faz?" },
    { id: "2", role: "user", text: "Somos uma padaria." },
    { id: "3", role: "user", author: "Staff da Cogniventure · Otto", text: "Ajustei o limite para 3 mil." },
  ]}
  onSend={(texto) => setNome(texto)}
  sending={false}
  progress={[{ label: "Anotando no perfil", status: "done" }]}
  assistant="Agente de briefing"
/>
```

- `messages`: `ChatMessage[]`: Mensagens na ordem, a mais antiga primeiro.
- `onSend`: `(text: string) => void`: Envia o texto digitado (Enter envia; Shift+Enter quebra a linha).
- `sending?`: `boolean`: Resposta em andamento: trava o envio e mostra os passos.
- `progress?`: `ChatProgress[]`: Passos da resposta em andamento, na ordem em que chegaram.
- `error?`: `string | null`: Erro da última resposta.
- `assistant?`: `string`: Nome de quem responde, para leitores de tela e para o indicador de resposta (ex.: "Agente de briefing").
- `placeholder?`: `string`: Texto de exemplo no campo.
- `disabled?`: `boolean`: Desliga o campo (ex.: para quem só pode ler).

---

## ListView

Receita de lista paginada no servidor: busca por texto, filtros, ordenação no cabeçalho, páginas e todos os estados. Os parâmetros ficam na URL: voltar, recarregar e compartilhar o link mantêm o que a pessoa escolheu. _(Receitas)_

```tsx
<ListView
  list={lista}
  rowKey={(f) => f.id}
  search="cliente"
  filters={[{ name: "status", label: "Status", options: [{ value: "aberta", label: "Aberta" }, { value: "paga", label: "Paga" }] }]}
  columns={[
    { key: "cliente", header: "Cliente", sort: "cliente" },
    { key: "valor", header: "Valor", sort: "valor", render: (f) => <Money value={f.valor} /> },
  ]}
  noun="faturas"
/>
```

- `list`: `{ data: { items: T[]; total: number; page: number; size: number; pages: number } | null; loading: boolean; error: { message: string } | null; reload: () => void; params: Record<string, string>; set: (changes: Record<string, string | number | null | undefined>) => void; }`: Estado de useListQuery(...) (src/core/api.ts): página carregada e parâmetros da URL.
- `columns`: `DataTableProps<T>["columns"]`: Colunas como em DataTable; sort é o campo que ordena a coluna (precisa estar no sortable do backend).
- `rowKey`: `(row: T) => string`: Identificador estável de cada linha (ex.: f => f.id).
- `search?`: `string`: Liga a busca por texto e mostra este exemplo no campo (ex.: "cliente ou descrição").
- `filters?`: `{ name: string; label: string; options: { value: string; label: string }[] }[]`: Filtros de escolha única: name é o parâmetro da lista no backend (ex.: status).
- `empty?`: `string`: Título quando ainda não há nenhum item. Padrão: "Nada por aqui ainda."
- `noun?`: `string`: Nome dos itens no plural, para o rodapé (ex.: "faturas"). Padrão: "itens".
- `caption?`: `string`: Legenda acessível da tabela.
- `actions?`: `ReactNode`: Ações ao lado da busca (ex.: botão de criar).

---

## ProcessResults

Receita de resultados de processos: um cartão por processo com a autonomia mês a mês (a versão publicada marcada no mês em que entrou), os números do mês, como as execuções terminaram e os indicadores de negócio, cada um na unidade dele (R$, %, dias, horas). Dois cartões por linha quando há largura (pela largura de onde está: num painel, um). _(Receitas)_

```tsx
<ProcessResults
  processes={[{
    processo: "p1", titulo: "Contas a pagar", publicada: 2, pausado: false,
    meses: [{ mes: "2026-09", concluidas: 4, autonomia: 0.5 }, { mes: "2026-10", concluidas: 10, autonomia: 0.8 }],
    versoes: [{ numero: 2, mes: "2026-10" }],
    iniciadas: 11, concluidas: 10, canceladas: 0, em_andamento: 1,
    fins: [{ resultado: "pago", quantidade: 9 }, { resultado: "recusado", quantidade: 1 }],
    indicadores: [{ titulo: "Valor pago", unidade: "moeda", valor: 42000 }, { titulo: "Pagos em atraso", unidade: "numero", valor: 1 }],
  }]}
/>
```

- `processes`: `ProcessResultsItem[]`: Os processos, na ordem em que aparecem.
- `empty?`: `string`: O que mostrar sem nenhum processo publicado.

---

## QueryTable

Receita de lista: consulta + tabela, com carregamento, erro, vazio e cartões em espaço estreito. _(Receitas)_

```tsx
<QueryTable
  query={faturas}
  rowKey={(f) => f.id}
  columns={[
    { key: "cliente", header: "Cliente" },
    { key: "status", header: "Status", render: (f) => <StatusBadge value={f.status} /> },
  ]}
/>
```

- `query`: `QueryViewProps<T[]>["query"]`: Estado de useQuery(...) cuja resposta é uma lista.
- `columns`: `DataTableProps<T>["columns"]`: Colunas como em DataTable: { key, header, render? }.
- `rowKey`: `(row: T) => string`: Identificador estável de cada linha (ex.: f => f.id).
- `empty?`: `string`: Título quando a lista vem vazia. Padrão: "Nada por aqui ainda."
- `caption?`: `string`: Legenda acessível da tabela.

---

## QueryView

Receita de consulta: mostra esqueleto ao carregar, erro com "Tentar de novo", vazio ou os dados. _(Receitas)_

```tsx
<QueryView query={fatura}>
  {(f) => <KeyValue items={[{ label: "Cliente", value: f.cliente }, { label: "Valor", value: <Money value={f.valor} /> }]} />}
</QueryView>
```

- `query`: `{ data: T | null; loading: boolean; error: { message: string } | null; reload: () => void }`: Estado devolvido por useQuery(...) (src/core/api.ts).
- `children`: `(data: T) => ReactNode`: Desenha os dados quando chegam: (dados) => <KeyValue ... />.
- `empty?`: `string`: Título quando o resultado é vazio (lista sem itens). Padrão: "Nada por aqui ainda."

---

## ResourceList

Receita de cadastro inteiro: lista com busca, filtros, ordem e páginas, criação e edição em painel lateral e remoção com confirmação, tudo a partir dos campos declarados no backend (core/resources.py). _(Receitas)_

```tsx
<ResourceList resource={cadastro} noun="fatura" />
```

- `resource`: `{ list: ListViewProps<T>["list"]; create: Action<never>; update: Action<never>; remove: Action<{ id: string }>; meta: { title: string; fields: Field[]; columns: { key: string; header: string; kind: Kind; sort?: string }[]; filters: { name: string; label: string; options: { value: string; label: string }[] }[]; search: string | null; }; }`: Estado de useResource(modulo.cadastro) (src/core/api.ts): lista, ações e os campos que o backend declarou.
- `columns?`: `DataTableProps<T>["columns"]`: Colunas no lugar das declaradas (ex.: com uma coluna calculada).
- `rowActions?`: `(row: T) => ReactNode`: Ações a mais em cada linha (ex.: um Button que abre a tela do registro).
- `noun?`: `string`: Nome de um item, para os botões e painéis (ex.: "cliente"). Padrão: "registro".
- `readOnly?`: `boolean`: Só a lista: sem criar, editar e remover (ex.: para quem não tem o papel de escrita).

---

## ResourcePage

Receita de tela de cadastro: título, indicadores, lista com todos os estados e criação em painel lateral. _(Receitas)_

```tsx
<ResourcePage
  title="Faturas"
  query={faturas}
  rowKey={(f) => f.id}
  stats={(rows) => [{ label: "Faturas", value: rows.length }]}
  columns={[
    { key: "cliente", header: "Cliente" },
    { key: "valor", header: "Valor", render: (f) => <Money value={f.valor} /> },
  ]}
  create={{ label: "Nova fatura", action: criar, fields: [{ name: "cliente", label: "Cliente", required: true }] }}
/>
```

- `title`: `string`: Título da tela.
- `description?`: `string`: Uma linha explicando a tela.
- `query`: `QueryTableProps<T>["query"]`: Estado de useQuery(...) da lista (resposta é um array).
- `columns`: `QueryTableProps<T>["columns"]`: Colunas da lista: { key, header, render? }.
- `rowKey`: `(row: T) => string`: Identificador estável de cada linha (ex.: f => f.id).
- `empty?`: `string`: Título quando a lista vem vazia.
- `stats?`: `(rows: T[]) => { label: string; value: ReactNode; hint?: string }[]`: Indicadores acima da lista, calculados a partir dos itens carregados.
- `create?`: `{ /** Texto do botão e título do painel (ex.: "Nova fatura"). */ label: string; action: ActionFormProps<B>["action"]; fields: ActionFormProps<B>["fields"]; /** Linha de ajuda no painel. */ description?: string; }`: Criação: botão no topo que abre um painel lateral com o formulário. Na ação, use onSuccess: query.reload.

---

## Card

Superfície que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais. _(Layout)_

```tsx
<Card title="Resumo" description="Últimos 30 dias" footer={<Button variant="secondary" onClick={salvar}>Ver tudo</Button>}>
  <Text>12 faturas emitidas.</Text>
</Card>
```

- `title?`: `string`: Título do cartão.
- `description?`: `string`: Uma linha abaixo do título.
- `footer?`: `ReactNode`: Rodapé (ex.: ações).
- `children?`: `ReactNode`

---

## Columns

Duas colunas: o principal e uma lateral fixa (ex.: conversa e o perfil sendo preenchido); no celular, uma abaixo da outra. _(Layout)_

```tsx
<Columns aside={<Card title="Perfil"><Text>Segmento: padaria</Text></Card>}>
  <Text>Conteúdo principal.</Text>
</Columns>
```

- `children`: `ReactNode`: Conteúdo principal, à esquerda (ocupa o espaço que sobra).
- `aside`: `ReactNode`: Coluna lateral, à direita em telas largas; abaixo do principal no celular.
- `asideWidth?`: `"sm" | "md" | "lg"`: Largura da coluna lateral. Padrão: md.

---

## Grid

Grade responsiva para cartões e indicadores: 1 coluna no celular, até 4 em telas largas. _(Layout)_

```tsx
<Grid cols={3}>
  <Stat label="Faturas" value={12} />
  <Stat label="Total" value={<Money value={1439.9} />} />
  <Stat label="Em aberto" value={3} />
</Grid>
```

- `cols?`: `1 | 2 | 3 | 4`: Colunas em telas largas; no celular é sempre 1. Padrão: 3.
- `children`: `ReactNode`

---

## Page

Estrutura de uma tela: título, descrição, ações e conteúdo com o espaçamento padrão. _(Layout)_

```tsx
<Page title="Faturas" description="Emitidas este mês." actions={<Button onClick={salvar}>Nova fatura</Button>}>
  <Text>Conteúdo da tela.</Text>
</Page>
```

- `title`: `string`: Título da tela: vira o h1 e o título da aba.
- `description?`: `string`: Uma linha explicando para que serve a tela.
- `actions?`: `ReactNode`: Ações à direita do título (ex.: Button).
- `children`: `ReactNode`

---

## Row

Coloca itens lado a lado, com alinhamento e quebra de linha controlados. _(Layout)_

```tsx
<Row justify="between">
  <Heading>Itens</Heading>
  <Button variant="secondary" onClick={salvar}>Exportar</Button>
</Row>
```

- `gap?`: `"sm" | "md" | "lg"`: Espaço entre os itens. Padrão: md.
- `align?`: `"start" | "center" | "end" | "baseline"`: Alinhamento vertical. Padrão: center.
- `justify?`: `"start" | "between" | "end"`: Distribuição horizontal. Padrão: start.
- `wrap?`: `boolean`: Quebra linha quando não cabe. Padrão: true.
- `children`: `ReactNode`

---

## SidePanel

Painel que desliza da direita sobre a tela, para editar ou criar sem sair dela (ocupa a tela no celular). _(Layout)_

```tsx
<SidePanel open={true} onClose={sair} title="Editar fatura" description="As mudanças valem na hora.">
  <Text>Formulário da fatura.</Text>
</SidePanel>
```

- `open`: `boolean`: Aberto ou fechado (estado da página).
- `onClose`: `() => void`: Chamado ao fechar (X, Esc ou clique fora).
- `title`: `string`: Título do painel.
- `description?`: `string`: Linha de ajuda abaixo do título.
- `children`: `ReactNode`

---

## Stack

Empilha itens na vertical com espaçamento uniforme. _(Layout)_

```tsx
<Stack gap="sm">
  <Heading>Resumo</Heading>
  <Text tone="muted">Últimos 30 dias.</Text>
</Stack>
```

- `gap?`: `"sm" | "md" | "lg"`: Espaço entre os itens. Padrão: md.
- `children`: `ReactNode`

---

## Tabs

Abas que dividem uma tela em partes do mesmo assunto. A aba aberta fica no fragmento da URL (/tela#modelos): link direto e recarregar mantêm a aba, e os parâmetros de lista (?q=, ?page=) ficam só para as listas. _(Layout)_

```tsx
<Tabs
  tabs={[
    { id: "resumo", label: "Resumo", content: <Text>12 faturas emitidas.</Text> },
    { id: "itens", label: "Itens", content: <Text>Itens da fatura.</Text> },
  ]}
/>
```

- `tabs`: `{ id: string; label: string; content: ReactNode }[]`: Abas na ordem: { id, label, content }. O id vira o fragmento da URL (/tela#id); só a aba aberta fica montada, e trocar de aba limpa os parâmetros da lista (?page=&q=...).

---

## BpmnDiagram

Diagrama BPMN somente leitura (bpmn-js), com zoom e arrasto, o caminho percorrido em destaque e os passos com problema. Fluxo comprido abre legível no começo; o resto se vê arrastando ou com a roda do mouse. _(Dados)_

```tsx
<BpmnDiagram xml={nome} highlight={["inicio", "ler_documento"]} problems={["conferir"]} label="Fluxo do processo" />
```

- `xml`: `string`: O BPMN 2.0 com o desenho (BPMN DI), como o backend devolve.
- `highlight?`: `string[]`: Ids dos elementos percorridos (passos e ligações), pintados com a cor da marca (ex.: o caminho da simulação).
- `problems?`: `string[]`: Ids dos elementos com problema, contornados em vermelho.
- `label`: `string`: Nome acessível do diagrama (ex.: "Fluxo do processo Contas a pagar").

---

## DataTable

Tabela de dados tipada. Em espaço estreito, cada linha vira um cartão com rótulo e valor. Com onSort, as colunas que têm sort viram botões de ordenação no cabeçalho. _(Dados)_

```tsx
<DataTable
  rows={[{ id: "f1", cliente: "Padaria Aurora", valor: 150 }]}
  rowKey={(r) => r.id}
  columns={[
    { key: "cliente", header: "Cliente" },
    { key: "valor", header: "Valor", render: (r) => <Money value={r.valor} /> },
  ]}
/>
```

- `columns`: `{ key: string; header: string; render?: (row: T) => ReactNode; sort?: string }[]`: Colunas: header é o título; render formata a célula (padrão: String(row[key])); sort é o campo que ordena a coluna.
- `rows`: `T[]`
- `rowKey`: `(row: T) => string`: Identificador estável de cada linha (ex.: row => row.id).
- `empty?`: `ReactNode`: Exibido quando não há linhas. Padrão: "Nada por aqui ainda."
- `caption?`: `string`: Legenda acessível que descreve a tabela.
- `sort?`: `string | null`: Ordem atual: "campo" (crescente) ou "-campo" (decrescente).
- `onSort?`: `(sort: string | null) => void`: Clique no título de uma coluna com sort: crescente → decrescente → ordem padrão (null).

---

## JourneySteps

Jornada em passos numerados: o que já foi feito, o passo de agora em destaque e os próximos, com o caminho de cada um. _(Dados)_

```tsx
<JourneySteps
  steps={[
    { title: "Briefing", description: "Conte como a empresa funciona.", status: "done", detail: "6 de 6 tópicos", to: "/briefing" },
    { title: "Conhecimento", description: "Site e documentos.", status: "current", to: "/conhecimento", action: "Enviar documentos" },
    { title: "Processos", description: "O que vamos executar.", status: "later" },
  ]}
/>
```

- `steps`: `JourneyStep[]`: Passos na ordem da jornada.

---

## KeyValue

Lista de pares rótulo/valor para detalhes de um registro. _(Dados)_

```tsx
<KeyValue
  items={[
    { label: "Cliente", value: "Padaria Aurora" },
    { label: "Status", value: <StatusBadge value="paga" /> },
  ]}
/>
```

- `items`: `{ label: string; value: ReactNode }[]`: Pares rótulo/valor, na ordem de exibição.
- `stacked?`: `boolean`: Rótulo acima do valor, para colunas estreitas (ex.: a lateral de Columns). Padrão: lado a lado em telas largas.

---

## MonthlyBars

Barras de uma taxa mês a mês (0 a 100%), com a marca do que mudou em cada mês, como a versão publicada. Sem largura para todos os meses (um painel lateral, o celular), rola de lado e começa no mês mais novo. _(Dados)_

```tsx
<MonthlyBars
  label="Autonomia por mês"
  items={[
    { label: "set/26", value: 0.5, detail: "4 concluídas" },
    { label: "out/26", value: 0.8, detail: "10 concluídas", marker: "v2" },
    { label: "nov/26", value: null, detail: "nada concluído" },
  ]}
/>
```

- `label`: `string`: O que as barras medem (leitor de tela e título).
- `items`: `MonthlyBarsItem[]`: Os meses, do mais antigo ao mais novo.

---

## Pagination

Rodapé de lista paginada: quais itens estão na tela, de quantos, e os botões de página anterior e seguinte. _(Dados)_

```tsx
<Pagination page={2} pages={7} total={134} size={20} onPage={salvar} noun="faturas" />
```

- `page`: `number`: Página atual, a partir de 1.
- `pages`: `number`: Total de páginas (0 quando não há itens).
- `total`: `number`: Itens que atendem ao filtro, somando todas as páginas.
- `size`: `number`: Itens por página.
- `onPage`: `(page: number) => void`: Vai para a página pedida.
- `noun?`: `string`: Nome dos itens no plural, para o texto (ex.: "faturas"). Padrão: "itens".

---

## Picture

Imagem quadrada que se ajusta ao espaço sem distorcer (logo, foto de perfil, miniatura). _(Dados)_

```tsx
<Picture src="https://exemplo.com/logo.png" alt="Logo da empresa" size={48} />
```

- `src`: `string`: Endereço da imagem (ex.: link assinado devolvido pelo serviço).
- `alt`: `string`: Descrição para leitores de tela (obrigatória).
- `size?`: `number`: Lado do quadrado em que a imagem cabe, em pixels, sem cortar. Padrão: 64.

---

## ProjectChain

Projeto: a cadeia de processos que um começou (uma proposta aceita inicia o contrato e o faturamento), com cada execução, o que ela espera e o caminho para abri-la. _(Dados)_

```tsx
<ProjectChain
  title="Proposta comercial"
  description="Proposta para Padaria Pão Quente"
  status="andamento"
  steps={[
    { key: "e1", title: "Proposta comercial", status: "concluida", detail: "Terminou: aceita", to: "/processos/execucoes/e1" },
    { key: "e2", title: "Gestão de contratos", status: "andamento", detail: "Com o staff: Coletar as assinaturas", level: 1 },
    { key: "e3", title: "Faturamento e cobrança", status: "andamento", detail: "Aguardando o pagamento", level: 1 },
  ]}
/>
```

- `title`: `string`: Nome do projeto (o processo que começou a cadeia).
- `description?`: `string`: O que começou o projeto (ex.: "Proposta para Padaria Pão Quente").
- `status`: `"andamento" | "concluido" | "atencao"`: andamento, concluido ou atencao (alguma etapa com incidente).
- `steps`: `ProjectChainStep[]`: As etapas na ordem em que começaram.

---

## ResultsCard

Os resultados de um processo num mês: a taxa mês a mês com as marcas, os números do mês, como terminaram e os indicadores. Os números e os indicadores ficam lado a lado quando o cartão é largo (pela largura dele, não da tela: cabe num painel). _(Dados)_

```tsx
<ResultsCard
  title="Contas a pagar"
  description="Versão 2 publicada"
  badges={["Pausado"]}
  monthsLabel="Autonomia por mês"
  months={[{ label: "set/26", value: 0.5 }, { label: "out/26", value: 0.8, marker: "v2" }]}
  counts={[{ label: "Concluídas", value: 10 }, { label: "Em andamento", value: 2 }]}
  ends={[{ label: "pago", value: 9 }, { label: "recusado", value: 1 }]}
  indicators={[{ label: "Valor pago", value: "R$ 42.000,00" }]}
/>
```

- `title`: `string`: O que se acompanha (ex.: o processo).
- `description?`: `string`: Uma linha abaixo do título (ex.: "Versão 3 publicada").
- `badges?`: `string[]`: Selos ao lado (ex.: "Pausado").
- `months`: `MonthlyBarsItem[]`: A taxa mês a mês (ex.: autonomia), com as marcas.
- `monthsLabel`: `string`: Rótulo do gráfico.
- `counts`: `{ label: string; value: ReactNode }[]`: Números do mês (ex.: concluídas, canceladas).
- `ends`: `{ label: string; value: number }[]`: Como as execuções do mês terminaram (fim → quantas).
- `indicators`: `{ label: string; value: ReactNode }[]`: Os indicadores de negócio do mês, já formatados.

---

## Stat

Indicador em destaque: rótulo, valor grande e contexto. Use dentro de Grid. _(Dados)_

```tsx
<Stat label="Total" value={<Money value={1439.9} />} hint="nesta semana" tone="success" />
```

- `label`: `string`: O que o número mede.
- `value`: `ReactNode`: O valor em destaque.
- `hint?`: `string`: Contexto curto abaixo do valor.
- `tone?`: `"default" | "success" | "danger"`: Cor do valor. Padrão: default.

---

## UsageMeter

Barra de uso de um limite: quanto foi usado de quanto é permitido, em alerta a partir de 80% e cheia em 100%. _(Dados)_

```tsx
<UsageMeter label="Pessoas na organização" used={4} limit={5} hint="no plano Pro" />
```

- `label`: `string`: O que se mede (ex.: "Pessoas na organização").
- `used`: `number`: Quanto já foi usado.
- `limit`: `number | null`: O máximo permitido; null: sem limite (sem barra); 0: não incluído.
- `format?`: `(value: number) => ReactNode`: Como mostrar um valor (padrão: número em pt-BR). Ex.: (v) => <Money value={v} currency="USD" />.
- `hint?`: `string`: Contexto curto abaixo da barra (ex.: "neste mês").

---

## Badge

Etiqueta curta para status, papéis ou categorias. _(Formatação)_

```tsx
<Badge tone="accent">financeiro</Badge>
```

- `tone?`: `"neutral" | "accent" | "success" | "warning" | "danger"`: Cor semântica. Padrão: neutral.
- `children`: `ReactNode`

---

## Code

Trecho de código, comando ou identificador em fonte monoespaçada. _(Formatação)_

```tsx
<Code>{"uv run python gateway/contracts.py"}</Code>
```

- `children`: `string`: Texto exibido em fonte monoespaçada.
- `block?`: `boolean`: Bloco próprio (quebra linhas longas) em vez de trecho no meio do texto. Padrão: false.

---

## DateTime

Data e hora em pt-BR; a data completa aparece ao passar o mouse. _(Formatação)_

```tsx
<DateTime value="2026-10-01T14:30:00Z" format="relative" />
```

- `value`: `string | Date | null | undefined`: Data ISO (como vem do backend) ou Date; vazia ou inválida vira "—". Só a data (2026-10-01) é o dia no fuso de quem vê.
- `format?`: `"date" | "datetime" | "time" | "relative"`: date (01/10/2026), datetime (01/10/2026 14:30), time (14:30) ou relative (há 5 minutos). Padrão: datetime.

---

## Money

Valor monetário em pt-BR (R$ 1.234,56), com algarismos alinhados em tabelas. _(Formatação)_

```tsx
<Money value={1439.9} />
```

- `value`: `number | null | undefined`: Valor numérico; null ou undefined vira "—".
- `currency?`: `"BRL" | "USD" | "EUR"`: Moeda ISO. Padrão: BRL.
- `digits?`: `number`: Casas decimais máximas, para valores abaixo de um centavo (ex.: custo de IA: 4). Padrão: 2.

---

## Quantity

Quantidade em pt-BR com separador de milhar (1.234.567) ou curta (1,2 mi), alinhada em tabelas. _(Formatação)_

```tsx
<Quantity value={1234567} compact unit="tokens" />
```

- `value`: `number | null | undefined`: Quantidade; null ou undefined vira "—".
- `compact?`: `boolean`: Forma curta para números grandes: 1,2 mil, 3,4 mi. Padrão: false (1.234.567).
- `unit?`: `string`: Unidade depois do número (ex.: "tokens").

---

## StatusBadge

Status como etiqueta colorida, com cor automática para valores comuns (pago, pendente, erro...). _(Formatação)_

```tsx
<StatusBadge value="aberta" labels={{ aberta: "Em aberto" }} />
```

- `value`: `string`: Valor do status como vem do backend (ex.: "paga", "SUCCESS").
- `tones?`: `Record<string, Tone>`: Cor por valor: { paga: "success", aberta: "warning" }. Sem mapa, status comuns ganham cor automaticamente.
- `labels?`: `Record<string, string>`: Texto exibido por valor: { paga: "Paga" }. Padrão: o próprio valor.

---

## Button

Botão de ação com variantes, tamanhos e estado de carregamento. _(Formulários)_

```tsx
<Button variant="secondary" onClick={salvar}>Cancelar</Button>
```

- `variant?`: `"primary" | "secondary" | "ghost" | "danger"`: Estilo visual. Padrão: primary.
- `size?`: `"sm" | "md"`: Altura. Padrão: md.
- `type?`: `"button" | "submit"`: submit dentro de Form. Padrão: button.
- `loading?`: `boolean`: Mostra que a ação está em andamento e bloqueia novos cliques.
- `disabled?`: `boolean`
- `onClick?`: `() => void`
- `to?`: `string`: Navega para esta rota da aplicação em vez de executar onClick (ex.: "/cadastro").
- `children`: `ReactNode`

---

## ConfirmButton

Botão para ação destrutiva que pede um segundo clique de confirmação (volta sozinho em 4 s). _(Formulários)_

```tsx
<ConfirmButton onConfirm={salvar} confirmLabel="Remover agora">Remover</ConfirmButton>
```

- `children`: `ReactNode`: Texto do botão antes de confirmar (ex.: "Remover").
- `onConfirm`: `() => void`: Executa a ação depois da confirmação.
- `confirmLabel?`: `string`: Texto do botão de confirmação. Padrão: "Confirmar".
- `loading?`: `boolean`: Ação em andamento.
- `size?`: `"sm" | "md"`: Altura. Padrão: sm.

---

## CopyField

Texto somente leitura com botão de copiar, para links e códigos que a pessoa vai repassar. _(Formulários)_

```tsx
<CopyField label="Link do convite" value="https://app.exemplo.com/convite?codigo=abc" hint="Vale por 7 dias e para uma pessoa." />
```

- `label`: `string`: Rótulo visível.
- `value`: `string`: Texto a copiar (ex.: um link de convite).
- `hint?`: `string`: Ajuda abaixo do campo.

---

## FileField

Escolha de um arquivo que é enviado na hora, direto ao armazenamento, com erro e estado de envio. _(Formulários)_

```tsx
<FileField label="Logo" upload={logo} accept="image/*" hint="Até 2 MB." />
```

- `label`: `string`: Rótulo visível (também é o nome acessível).
- `upload`: `{ run: (file: File) => Promise<unknown>; running: boolean; error: { message: string } | null }`: Estado de useUpload(...) (src/core/api.ts): o campo chama upload.run(arquivo) assim que o arquivo é escolhido.
- `accept?`: `string`: Tipos aceitos no seletor (ex.: "image/png,image/jpeg"). A validação de verdade é do serviço.
- `hint?`: `string`: Ajuda abaixo do campo (tipos e tamanho máximo).

---

## Form

Formulário com campos espaçados de forma uniforme e envio sem recarregar a página. _(Formulários)_

```tsx
<Form onSubmit={salvar}>
  <TextField label="Nome" value={nome} onChange={setNome} required />
  <Button type="submit">Salvar</Button>
</Form>
```

- `onSubmit`: `() => void | Promise<void>`: Chamado no envio (Enter ou Button type="submit"); o recarregamento da página já é evitado.
- `busy?`: `boolean`: Marca o formulário como ocupado para tecnologias assistivas.
- `children`: `ReactNode`

---

## SelectField

Lista de opções com rótulo, ajuda e erro ligados para acessibilidade. _(Formulários)_

```tsx
<SelectField
  label="Status"
  value={nome}
  onChange={setNome}
  options={[{ value: "aberta", label: "Aberta" }, { value: "paga", label: "Paga" }]}
/>
```

- `label`: `string`: Rótulo visível (também é o nome acessível).
- `value`: `string`
- `onChange`: `(value: string) => void`: Recebe o valor escolhido.
- `options`: `{ value: string; label: string }[]`: Opções: { value: "BRL", label: "Real" }.
- `placeholder?`: `string`: Texto quando nada foi escolhido. Padrão: "Selecione".
- `hint?`: `string`: Ajuda abaixo do campo.
- `error?`: `string`: Mensagem de erro: marca o campo como inválido.
- `required?`: `boolean`

---

## TextArea

Campo de texto de várias linhas com rótulo, ajuda e erro ligados para acessibilidade. _(Formulários)_

```tsx
<TextArea label="Observações" value={nome} onChange={setNome} rows={3} />
```

- `label`: `string`: Rótulo visível (também é o nome acessível).
- `value`: `string`
- `onChange`: `(value: string) => void`: Recebe o novo texto, não o evento.
- `rows?`: `number`: Linhas visíveis. Padrão: 4.
- `hint?`: `string`: Ajuda abaixo do campo.
- `error?`: `string`: Mensagem de erro: marca o campo como inválido.
- `required?`: `boolean`
- `placeholder?`: `string`
- `monospace?`: `boolean`: Fonte monoespaçada (tokens, JSON, código). Padrão: false.

---

## TextField

Campo de texto de uma linha com rótulo, ajuda e erro ligados para acessibilidade. _(Formulários)_

```tsx
<TextField label="E-mail" type="email" value={nome} onChange={setNome} required hint="Usado no login." />
```

- `label`: `string`: Rótulo visível (também é o nome acessível).
- `value`: `string`
- `onChange`: `(value: string) => void`: Recebe o novo texto, não o evento.
- `type?`: `"text" | "email" | "password" | "number" | "search" | "url" | "color" | "tel" | "date" | "datetime-local"`: Padrão: text. color: seletor de cor (#rrggbb); date: AAAA-MM-DD; datetime-local: AAAA-MM-DDTHH:MM.
- `hint?`: `string`: Ajuda abaixo do campo.
- `error?`: `string`: Mensagem de erro: marca o campo como inválido.
- `required?`: `boolean`
- `placeholder?`: `string`
- `autoComplete?`: `string`: Dica para o preenchimento automático do navegador (ex.: "email", "current-password").

---

## Toggle

Interruptor liga/desliga com efeito imediato (ativar um recurso, um modelo, uma notificação). _(Formulários)_

```tsx
<Toggle label="Ativo" checked={true} onChange={salvar} hint="Desligado, ninguém usa." />
```

- `label`: `string`: Rótulo (também é o nome acessível).
- `checked`: `boolean`
- `onChange`: `(checked: boolean) => void`: Recebe o novo estado (true = ligado).
- `hideLabel?`: `boolean`: Esconde o rótulo na tela (ex.: dentro de uma tabela); leitores de tela continuam lendo.
- `hint?`: `string`: Ajuda ao lado do rótulo.
- `disabled?`: `boolean`

---

## Alert

Mensagem de destaque para resultado, aviso ou erro, com ícone conforme a gravidade. _(Feedback)_

```tsx
<Alert tone="warning" title="Fatura vencida">Regularize até sexta-feira.</Alert>
```

- `tone?`: `"info" | "success" | "warning" | "danger"`: Gravidade. danger é anunciado imediatamente por leitores de tela. Padrão: info.
- `title?`: `string`: Resumo em negrito.
- `children?`: `ReactNode`

---

## EmptyState

Espaço reservado para lista vazia, página inexistente ou recurso indisponível. _(Feedback)_

```tsx
<EmptyState
  title="Nenhuma fatura"
  description="Emita a primeira pelo botão Nova fatura."
  action={<Button onClick={salvar}>Nova fatura</Button>}
/>
```

- `title`: `string`: O que está vazio ou ausente.
- `description?`: `string`: Como sair desse estado.
- `action?`: `ReactNode`: Ação principal (ex.: Button).

---

## Spinner

Indicador de carregamento acessível, com texto. _(Feedback)_

```tsx
<Spinner label="Carregando faturas" />
```

- `label?`: `string`: Texto para leitores de tela e exibido ao lado. Padrão: "Carregando".

---

## Heading

Título de seção dentro de uma tela (h2 ou h3). _(Texto)_

```tsx
<Heading level={3}>Itens da fatura</Heading>
```

- `level?`: `2 | 3`: Nível do título. O h1 é do Page. Padrão: 2.
- `children`: `ReactNode`

---

## Text

Parágrafo de texto com tom e tamanho padronizados. _(Texto)_

```tsx
<Text tone="muted" size="sm">Atualizado há 5 minutos.</Text>
```

- `tone?`: `"default" | "muted" | "danger" | "success"`: Cor semântica. Padrão: default.
- `size?`: `"sm" | "md"`: Tamanho. Padrão: md.
- `children`: `ReactNode`

---

## TextLink

Link no meio do texto para outra tela da aplicação. _(Texto)_

```tsx
<Text>Não tem conta? <TextLink to="/cadastro">Criar conta</TextLink></Text>
```

- `to`: `string`: Rota de destino dentro da aplicação (ex.: "/cadastro").
- `children`: `ReactNode`

---

## AppShell

Moldura da aplicação: menu lateral em grupos (gaveta no celular), marca com logo e cor, barra superior com a tela atual e conteúdo centralizado. _(Aplicação)_

```tsx
<AppShell
  brand="Acme"
  color="#1e40af"
  nav={[{ to: "/inicio", label: "Início" }, { to: "/faturas", label: "Faturas", group: "Financeiro", items: [{ to: "/faturas/recorrentes", label: "Recorrentes" }] }]}
  aside={<SessionStatus user={usuario} onSignOut={sair} />}
>
  <Text>Conteúdo</Text>
</AppShell>
```

- `brand`: `string`: Nome exibido no topo do menu lateral (ex.: o da organização).
- `logo?`: `string | null`: Link da imagem do logo; sem ele, as iniciais do nome.
- `color?`: `string | null`: Cor da marca (#RRGGBB): vira a cor principal da tela inteira (botões, foco, menu); sem ela, a do tema.
- `nav`: `NavItem[]`: Itens do menu, já na ordem: os sem grupo no topo; os grupos na ordem em que aparecem.
- `aside?`: `ReactNode`: Conteúdo no pé do menu lateral (ex.: SessionStatus).
- `switcher?`: `ReactNode`: Seletor no topo do menu, abaixo da marca (ex.: TenantSwitcher).
- `actions?`: `ReactNode`: Ações à direita da barra superior (ex.: NotificationBell).
- `children`: `ReactNode`

---

## AuthShell

Moldura das telas abertas (entrar, cadastro, convite): marca no topo e conteúdo numa coluna estreita e centralizada. _(Aplicação)_

```tsx
<AuthShell brand="CV-Frame">
  <Text>Conteúdo</Text>
</AuthShell>
```

- `brand`: `string`: Nome exibido acima do conteúdo.
- `children`: `ReactNode`

---

## NotificationBell

Sino da barra superior com a quantidade de avisos não lidos; leva à lista de avisos. _(Aplicação)_

```tsx
<NotificationBell count={3} />
```

- `count`: `number`: Avisos não lidos; 0 esconde o número.
- `to?`: `string`: Rota da lista de avisos. Padrão: /notificacoes.

---

## SessionStatus

Sessão no pé do menu: avatar com iniciais e menu para sair, ou aviso de que não há sessão. _(Aplicação)_

```tsx
<SessionStatus user={usuario} onSignOut={sair} />
```

- `user`: `string | null`: Usuário da sessão; null quando não há sessão.
- `detail?`: `string`: Linha abaixo do nome (ex.: o e-mail).
- `onSignOut`: `() => void`: Encerra a sessão.

---

## TenantSwitcher

Seletor da organização ativa no topo do menu lateral, com a opção de criar outra. _(Aplicação)_

```tsx
<TenantSwitcher tenants={[{ id: "acme", name: "Acme" }, { id: "beta", name: "Beta" }]} current="acme" onSwitch={setNome} onCreate={salvar} />
```

- `tenants`: `{ id: string; name: string }[]`: Organizações da pessoa: { id, name }.
- `current`: `string | null`: Id da organização ativa (null se nenhuma).
- `onSwitch`: `(id: string) => void`: Troca a organização ativa.
- `onCreate?`: `() => void`: Abre a criação de uma organização nova.
