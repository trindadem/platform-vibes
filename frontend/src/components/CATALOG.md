# Catálogo de componentes

> Gerado por `vite.config.ts` a partir de `src/components/*.tsx` em todo `npm run dev` e `npm run build`. Não edite.
> Como usar: leia o índice, escolha as peças (receitas primeiro) e copie o exemplo da seção de cada uma.
> Dados vêm de `useQuery`/`useAction` com as funções de `src/core/contracts.ts`. Faltou peça? Crie
> `src/components/<Nome>.tsx` com JSDoc (frase, `@category`, `@example`) e `<Nome>Props` documentado.
> Os exemplos usam dados fictícios (`faturas`, `fatura`, `criar`, `nome`...) e o TypeScript confere cada um.

## Índice (38)

**Receitas**: telas e dados prontos: comece por aqui

- [ActionForm](#actionform): Receita de formulário: campos a partir de uma lista, envio pela ação, erro do servidor no campo certo. `action, fields, submitLabel?, successMessage?, initial?, onDone?`
- [QueryTable](#querytable): Receita de lista: consulta + tabela, com carregamento, erro, vazio e cartões em espaço estreito. `query, columns, rowKey, empty?, caption?`
- [QueryView](#queryview): Receita de consulta: mostra esqueleto ao carregar, erro com "Tentar de novo", vazio ou os dados. `query, children, empty?`
- [ResourcePage](#resourcepage): Receita de tela de cadastro: título, indicadores, lista com todos os estados e criação em painel lateral. `title, query, columns, rowKey, description?, empty?, stats?, create?`

**Layout**: estrutura da tela

- [Card](#card): Superfície que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais. `title?, description?, footer?, children?`
- [Grid](#grid): Grade responsiva para cartões e indicadores: 1 coluna no celular, até 4 em telas largas. `children, cols?`
- [Page](#page): Estrutura de uma tela: título, descrição, ações e conteúdo com o espaçamento padrão. `title, children, description?, actions?`
- [Row](#row): Coloca itens lado a lado, com alinhamento e quebra de linha controlados. `children, gap?, align?, justify?, wrap?`
- [SidePanel](#sidepanel): Painel que desliza da direita sobre a tela, para editar ou criar sem sair dela (ocupa a tela no celular). `open, onClose, title, children, description?`
- [Stack](#stack): Empilha itens na vertical com espaçamento uniforme. `children, gap?`
- [Tabs](#tabs): Abas que dividem uma tela em partes do mesmo assunto; a aba aberta fica na URL (?aba=...). `tabs, param?`

**Dados**: registros e números

- [DataTable](#datatable): Tabela de dados tipada. `columns, rows, rowKey, empty?, caption?`
- [KeyValue](#keyvalue): Lista de pares rótulo/valor para detalhes de um registro. `items`
- [Stat](#stat): Indicador em destaque: rótulo, valor grande e contexto. `label, value, hint?, tone?`

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

- [AppShell](#appshell): Moldura da aplicação: menu lateral (gaveta no celular), barra superior com a tela atual e conteúdo centralizado. `brand, nav, children, aside?, switcher?`
- [AuthShell](#authshell): Moldura das telas abertas (entrar, cadastro, convite): marca no topo e conteúdo numa coluna estreita e centralizada. `brand, children`
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
- `fields`: `{ name: keyof B & string; label: string; kind?: "text" | "email" | "password" | "number" | "textarea" | "select"; required?: boolean; placeholder?: string; hint?: string; options?: { value: string; label: string }[]; /** Dica de preenchimento automático (ex.: "email", "current-password", "new-password"). */ autoComplete?: string; }[]`: Campos na ordem. name é a chave do corpo da ação (o TypeScript confere); kind padrão text; number vira número; select usa options.
- `submitLabel?`: `string`: Texto do botão de envio. Padrão: "Salvar".
- `successMessage?`: `string`: Mensagem exibida após sucesso (o formulário é limpo).
- `initial?`: `Partial<Record<keyof B & string, string>>`: Valores iniciais por campo.
- `onDone?`: `() => void`: Chamado após sucesso (ex.: fechar o painel).

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

Abas que dividem uma tela em partes do mesmo assunto; a aba aberta fica na URL (?aba=...). _(Layout)_

```tsx
<Tabs
  tabs={[
    { id: "resumo", label: "Resumo", content: <Text>12 faturas emitidas.</Text> },
    { id: "itens", label: "Itens", content: <Text>Itens da fatura.</Text> },
  ]}
/>
```

- `tabs`: `{ id: string; label: string; content: ReactNode }[]`: Abas na ordem: { id, label, content }. Só o conteúdo da aba aberta fica montado.
- `param?`: `string`: Parâmetro da URL que guarda a aba aberta (link direto e recarregar mantêm a aba). Padrão: "aba".

---

## DataTable

Tabela de dados tipada. Em espaço estreito, cada linha vira um cartão com rótulo e valor. _(Dados)_

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

- `columns`: `{ key: string; header: string; render?: (row: T) => ReactNode }[]`: Colunas: header é o título; render formata a célula (padrão: String(row[key])).
- `rows`: `T[]`
- `rowKey`: `(row: T) => string`: Identificador estável de cada linha (ex.: row => row.id).
- `empty?`: `ReactNode`: Exibido quando não há linhas. Padrão: "Nada por aqui ainda."
- `caption?`: `string`: Legenda acessível que descreve a tabela.

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

- `value`: `string | Date | null | undefined`: Data ISO (como vem do backend) ou Date; vazia ou inválida vira "—".
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
- `type?`: `"text" | "email" | "password" | "number" | "search" | "url"`: Padrão: text.
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

Moldura da aplicação: menu lateral (gaveta no celular), barra superior com a tela atual e conteúdo centralizado. _(Aplicação)_

```tsx
<AppShell brand="CV-Frame" nav={[{ to: "/faturas", label: "Faturas" }]} aside={<SessionStatus user={usuario} onSignOut={sair} />}>
  <Text>Conteúdo</Text>
</AppShell>
```

- `brand`: `string`: Nome exibido no topo do menu lateral.
- `nav`: `{ to: string; label: string }[]`: Itens do menu: { to: "/rota", label: "Texto" }.
- `aside?`: `ReactNode`: Conteúdo no pé do menu lateral (ex.: SessionStatus).
- `switcher?`: `ReactNode`: Seletor no topo do menu, abaixo da marca (ex.: TenantSwitcher).
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
