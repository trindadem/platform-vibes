# Catálogo de componentes

> Gerado por `vite.config.ts` a partir de `src/components/*.tsx` em todo `npm run dev` e `npm run build`. Não edite.
> Antes de compor uma tela, procure aqui. Faltou peça? Crie `src/components/<Nome>.tsx` com JSDoc e `<Nome>Props`.

29 componentes: [ActionForm](#actionform) · [Alert](#alert) · [AppShell](#appshell) · [Badge](#badge) · [Button](#button) · [Card](#card) · [Code](#code) · [DataTable](#datatable) · [DateTime](#datetime) · [EmptyState](#emptystate) · [Form](#form) · [Grid](#grid) · [Heading](#heading) · [KeyValue](#keyvalue) · [Money](#money) · [Page](#page) · [QueryTable](#querytable) · [QueryView](#queryview) · [ResourcePage](#resourcepage) · [Row](#row) · [SelectField](#selectfield) · [SessionStatus](#sessionstatus) · [Spinner](#spinner) · [Stack](#stack) · [Stat](#stat) · [StatusBadge](#statusbadge) · [Text](#text) · [TextArea](#textarea) · [TextField](#textfield)

## ActionForm

Receita de formulário: campos a partir de uma lista, envio pela ação, erro do servidor no campo certo.

- `action`: `{ run: (body: B) => Promise<unknown>; running: boolean; error: { message: string; details?: { loc?: (string | number)[]; msg?: string; type?: string }[] } | null; }` — Estado de useAction(...) (src/core/api.ts): o formulário chama action.run(valores).
- `fields`: `{ name: keyof B & string; label: string; kind?: "text" | "email" | "password" | "number" | "textarea" | "select"; required?: boolean; placeholder?: string; hint?: string; options?: { value: string; label: string }[]; }[]` — Campos na ordem. name é a chave do corpo da ação (o TypeScript confere); kind padrão text; number vira número; select usa options.
- `submitLabel?`: `string` — Texto do botão de envio. Padrão: "Salvar".
- `successMessage?`: `string` — Mensagem exibida após sucesso (o formulário é limpo).
- `initial?`: `Partial<Record<keyof B & string, string>>` — Valores iniciais por campo.
- `onDone?`: `() => void` — Chamado após sucesso (ex.: fechar o painel).

## Alert

Mensagem de destaque para resultado, aviso ou erro, com ícone conforme a gravidade.

- `tone?`: `"info" | "success" | "warning" | "danger"` — Gravidade. danger é anunciado imediatamente por leitores de tela. Padrão: info.
- `title?`: `string` — Resumo em negrito.
- `children?`: `ReactNode`

## AppShell

Moldura da aplicação: menu lateral (gaveta no celular), barra superior com a tela atual e conteúdo centralizado.

- `brand`: `string` — Nome exibido no topo do menu lateral.
- `nav`: `{ to: string; label: string }[]` — Itens do menu: { to: "/rota", label: "Texto" }.
- `aside?`: `ReactNode` — Conteúdo no pé do menu lateral (ex.: SessionStatus).
- `children`: `ReactNode`

## Badge

Etiqueta curta para status, papéis ou categorias.

- `tone?`: `"neutral" | "accent" | "success" | "warning" | "danger"` — Cor semântica. Padrão: neutral.
- `children`: `ReactNode`

## Button

Botão de ação com variantes, tamanhos e estado de carregamento.

- `variant?`: `"primary" | "secondary" | "ghost" | "danger"` — Estilo visual. Padrão: primary.
- `size?`: `"sm" | "md"` — Altura. Padrão: md.
- `type?`: `"button" | "submit"` — submit dentro de Form. Padrão: button.
- `loading?`: `boolean` — Mostra que a ação está em andamento e bloqueia novos cliques.
- `disabled?`: `boolean`
- `onClick?`: `() => void`
- `children`: `ReactNode`

## Card

Superfície que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais.

- `title?`: `string` — Título do cartão.
- `description?`: `string` — Uma linha abaixo do título.
- `footer?`: `ReactNode` — Rodapé (ex.: ações).
- `children?`: `ReactNode`

## Code

Trecho de código, comando ou identificador em fonte monoespaçada.

- `children`: `string` — Texto exibido em fonte monoespaçada.
- `block?`: `boolean` — Bloco próprio (quebra linhas longas) em vez de trecho no meio do texto. Padrão: false.

## DataTable

Tabela de dados tipada. Em espaço estreito, cada linha vira um cartão com rótulo e valor.

- `columns`: `{ key: string; header: string; render?: (row: T) => ReactNode }[]` — Colunas: header é o título; render formata a célula (padrão: String(row[key])).
- `rows`: `T[]`
- `rowKey`: `(row: T) => string` — Identificador estável de cada linha (ex.: row => row.id).
- `empty?`: `ReactNode` — Exibido quando não há linhas. Padrão: "Nada por aqui ainda."
- `caption?`: `string` — Legenda acessível que descreve a tabela.

## DateTime

Data e hora em pt-BR; a data completa aparece ao passar o mouse.

- `value`: `string | Date | null | undefined` — Data ISO (como vem do backend) ou Date; vazia ou inválida vira "—".
- `format?`: `"date" | "datetime" | "time" | "relative"` — date (01/10/2026), datetime (01/10/2026 14:30), time (14:30) ou relative (há 5 minutos). Padrão: datetime.

## EmptyState

Espaço reservado para lista vazia, página inexistente ou recurso indisponível.

- `title`: `string` — O que está vazio ou ausente.
- `description?`: `string` — Como sair desse estado.
- `action?`: `ReactNode` — Ação principal (ex.: Button).

## Form

Formulário com campos espaçados de forma uniforme e envio sem recarregar a página.

- `onSubmit`: `() => void | Promise<void>` — Chamado no envio (Enter ou Button type="submit"); o recarregamento da página já é evitado.
- `busy?`: `boolean` — Marca o formulário como ocupado para tecnologias assistivas.
- `children`: `ReactNode`

## Grid

Grade responsiva para cartões e indicadores: 1 coluna no celular, até 4 em telas largas.

- `cols?`: `1 | 2 | 3 | 4` — Colunas em telas largas; no celular é sempre 1. Padrão: 3.
- `children`: `ReactNode`

## Heading

Título de seção dentro de uma tela (h2 ou h3).

- `level?`: `2 | 3` — Nível do título. O h1 é do Page. Padrão: 2.
- `children`: `ReactNode`

## KeyValue

Lista de pares rótulo/valor para detalhes de um registro.

- `items`: `{ label: string; value: ReactNode }[]` — Pares rótulo/valor, na ordem de exibição.

## Money

Valor monetário em pt-BR (R$ 1.234,56), com algarismos alinhados em tabelas.

- `value`: `number | null | undefined` — Valor numérico; null ou undefined vira "—".
- `currency?`: `"BRL" | "USD" | "EUR"` — Moeda ISO. Padrão: BRL.

## Page

Estrutura de uma tela: título, descrição, ações e conteúdo com o espaçamento padrão.

- `title`: `string` — Título da tela: vira o h1 e o título da aba.
- `description?`: `string` — Uma linha explicando para que serve a tela.
- `actions?`: `ReactNode` — Ações à direita do título (ex.: Button).
- `children`: `ReactNode`

## QueryTable

Receita de lista: consulta + tabela, com carregamento, erro, vazio e cartões em espaço estreito.

- `query`: `QueryViewProps<T[]>["query"]` — Estado de useQuery(...) cuja resposta é uma lista.
- `columns`: `DataTableProps<T>["columns"]` — Colunas como em DataTable: { key, header, render? }.
- `rowKey`: `(row: T) => string` — Identificador estável de cada linha (ex.: f => f.id).
- `empty?`: `string` — Título quando a lista vem vazia. Padrão: "Nada por aqui ainda."
- `caption?`: `string` — Legenda acessível da tabela.

## QueryView

Receita de consulta: mostra esqueleto ao carregar, erro com "Tentar de novo", vazio ou os dados.

- `query`: `{ data: T | null; loading: boolean; error: { message: string } | null; reload: () => void }` — Estado devolvido por useQuery(...) (src/core/api.ts).
- `children`: `(data: T) => ReactNode` — Desenha os dados quando chegam: (dados) => <KeyValue ... />.
- `empty?`: `string` — Título quando o resultado é vazio (lista sem itens). Padrão: "Nada por aqui ainda."

## ResourcePage

Receita de tela de cadastro: título, indicadores, lista com todos os estados e criação em painel lateral.

- `title`: `string` — Título da tela.
- `description?`: `string` — Uma linha explicando a tela.
- `query`: `QueryTableProps<T>["query"]` — Estado de useQuery(...) da lista (resposta é um array).
- `columns`: `QueryTableProps<T>["columns"]` — Colunas da lista: { key, header, render? }.
- `rowKey`: `(row: T) => string` — Identificador estável de cada linha (ex.: f => f.id).
- `empty?`: `string` — Título quando a lista vem vazia.
- `stats?`: `(rows: T[]) => { label: string; value: ReactNode; hint?: string }[]` — Indicadores acima da lista, calculados a partir dos itens carregados.
- `create?`: `{ /** Texto do botão e título do painel (ex.: "Nova fatura"). */ label: string; action: ActionFormProps<B>["action"]; fields: ActionFormProps<B>["fields"]; /** Linha de ajuda no painel. */ description?: string; }` — Criação: botão no topo que abre um painel lateral com o formulário. Na ação, use onSuccess: query.reload.

## Row

Coloca itens lado a lado, com alinhamento e quebra de linha controlados.

- `gap?`: `"sm" | "md" | "lg"` — Espaço entre os itens. Padrão: md.
- `align?`: `"start" | "center" | "end" | "baseline"` — Alinhamento vertical. Padrão: center.
- `justify?`: `"start" | "between" | "end"` — Distribuição horizontal. Padrão: start.
- `wrap?`: `boolean` — Quebra linha quando não cabe. Padrão: true.
- `children`: `ReactNode`

## SelectField

Lista de opções com rótulo, ajuda e erro ligados para acessibilidade.

- `label`: `string` — Rótulo visível (também é o nome acessível).
- `value`: `string`
- `onChange`: `(value: string) => void` — Recebe o valor escolhido.
- `options`: `{ value: string; label: string }[]` — Opções: { value: "BRL", label: "Real" }.
- `placeholder?`: `string` — Texto quando nada foi escolhido. Padrão: "Selecione".
- `hint?`: `string` — Ajuda abaixo do campo.
- `error?`: `string` — Mensagem de erro: marca o campo como inválido.
- `required?`: `boolean`

## SessionStatus

Sessão no pé do menu: avatar com iniciais e menu para sair, ou aviso de que não há sessão.

- `user`: `string | null` — Usuário da sessão; null quando não há sessão.
- `onSignOut`: `() => void` — Encerra a sessão.

## Spinner

Indicador de carregamento acessível, com texto.

- `label?`: `string` — Texto para leitores de tela e exibido ao lado. Padrão: "Carregando".

## Stack

Empilha itens na vertical com espaçamento uniforme.

- `gap?`: `"sm" | "md" | "lg"` — Espaço entre os itens. Padrão: md.
- `children`: `ReactNode`

## Stat

Indicador em destaque: rótulo, valor grande e contexto. Use dentro de Grid.

- `label`: `string` — O que o número mede.
- `value`: `ReactNode` — O valor em destaque.
- `hint?`: `string` — Contexto curto abaixo do valor.
- `tone?`: `"default" | "success" | "danger"` — Cor do valor. Padrão: default.

## StatusBadge

Status como etiqueta colorida, com cor automática para valores comuns (pago, pendente, erro...).

- `value`: `string` — Valor do status como vem do backend (ex.: "paga", "SUCCESS").
- `tones?`: `Record<string, Tone>` — Cor por valor: { paga: "success", aberta: "warning" }. Sem mapa, status comuns ganham cor automaticamente.
- `labels?`: `Record<string, string>` — Texto exibido por valor: { paga: "Paga" }. Padrão: o próprio valor.

## Text

Parágrafo de texto com tom e tamanho padronizados.

- `tone?`: `"default" | "muted" | "danger" | "success"` — Cor semântica. Padrão: default.
- `size?`: `"sm" | "md"` — Tamanho. Padrão: md.
- `children`: `ReactNode`

## TextArea

Campo de texto de várias linhas com rótulo, ajuda e erro ligados para acessibilidade.

- `label`: `string` — Rótulo visível (também é o nome acessível).
- `value`: `string`
- `onChange`: `(value: string) => void` — Recebe o novo texto, não o evento.
- `rows?`: `number` — Linhas visíveis. Padrão: 4.
- `hint?`: `string` — Ajuda abaixo do campo.
- `error?`: `string` — Mensagem de erro: marca o campo como inválido.
- `required?`: `boolean`
- `placeholder?`: `string`
- `monospace?`: `boolean` — Fonte monoespaçada (tokens, JSON, código). Padrão: false.

## TextField

Campo de texto de uma linha com rótulo, ajuda e erro ligados para acessibilidade.

- `label`: `string` — Rótulo visível (também é o nome acessível).
- `value`: `string`
- `onChange`: `(value: string) => void` — Recebe o novo texto, não o evento.
- `type?`: `"text" | "email" | "password" | "number" | "search" | "url"` — Padrão: text.
- `hint?`: `string` — Ajuda abaixo do campo.
- `error?`: `string` — Mensagem de erro: marca o campo como inválido.
- `required?`: `boolean`
- `placeholder?`: `string`
- `autoComplete?`: `string` — Dica para o preenchimento automático do navegador (ex.: "email", "current-password").
