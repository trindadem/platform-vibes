# Catálogo de componentes

> Gerado por `vite.config.ts` a partir de `src/components/*.tsx` em todo `npm run dev` e `npm run build`. Não edite.
> Antes de compor uma tela, procure aqui. Faltou peça? Crie `src/components/<Nome>.tsx` com JSDoc e `<Nome>Props`.

21 componentes: [Alert](#alert) · [AppShell](#appshell) · [Badge](#badge) · [Button](#button) · [Card](#card) · [Code](#code) · [DataTable](#datatable) · [EmptyState](#emptystate) · [Form](#form) · [Grid](#grid) · [Heading](#heading) · [KeyValue](#keyvalue) · [Page](#page) · [Row](#row) · [SessionStatus](#sessionstatus) · [Spinner](#spinner) · [Stack](#stack) · [Stat](#stat) · [Text](#text) · [TextArea](#textarea) · [TextField](#textfield)

## Alert

Mensagem de destaque para resultado, aviso ou erro.

- `tone?`: `"info" | "success" | "warning" | "danger"` — Gravidade. danger é anunciado imediatamente por leitores de tela. Padrão: info.
- `title?`: `string` — Resumo em negrito.
- `children?`: `ReactNode`

## AppShell

Moldura da aplicação: topo com marca, menu de navegação e área de conteúdo centralizada.

- `brand`: `string` — Nome exibido no topo.
- `nav`: `{ to: string; label: string }[]` — Itens do menu: { to: "/rota", label: "Texto" }.
- `aside?`: `ReactNode` — Conteúdo à direita do topo (ex.: SessionStatus).
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

Superfície elevada que agrupa conteúdo relacionado, com título, descrição e rodapé opcionais.

- `title?`: `string` — Título do cartão.
- `description?`: `string` — Uma linha abaixo do título.
- `footer?`: `ReactNode` — Rodapé (ex.: ações).
- `children?`: `ReactNode`

## Code

Trecho de código, comando ou identificador em fonte monoespaçada.

- `children`: `string` — Texto exibido em fonte monoespaçada.
- `block?`: `boolean` — Bloco próprio (quebra linhas longas) em vez de trecho no meio do texto. Padrão: false.

## DataTable

Tabela de dados tipada, com colunas declarativas e estado vazio. Rola na horizontal em telas estreitas.

- `columns`: `{ key: string; header: string; render?: (row: T) => ReactNode }[]` — Colunas: header é o título; render formata a célula (padrão: String(row[key])).
- `rows`: `T[]`
- `rowKey`: `(row: T) => string` — Identificador estável de cada linha (ex.: row => row.id).
- `empty?`: `ReactNode` — Exibido quando não há linhas. Padrão: "Nada por aqui ainda."
- `caption?`: `string` — Legenda acessível que descreve a tabela.

## EmptyState

Espaço reservado para lista vazia, página inexistente ou recurso indisponível.

- `title`: `string` — O que está vazio ou ausente.
- `description?`: `string` — Como sair desse estado.
- `action?`: `ReactNode` — Ação principal (ex.: Button).

## Form

Formulário com campos empilhados e envio sem recarregar a página.

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

## Page

Estrutura de uma tela: título, descrição, ações e conteúdo com o espaçamento padrão.

- `title`: `string` — Título da tela: vira o h1 e o título da aba.
- `description?`: `string` — Uma linha explicando para que serve a tela.
- `actions?`: `ReactNode` — Ações à direita do título (ex.: Button).
- `children`: `ReactNode`

## Row

Coloca itens lado a lado, com alinhamento e quebra de linha controlados.

- `gap?`: `"sm" | "md" | "lg"` — Espaço entre os itens. Padrão: md.
- `align?`: `"start" | "center" | "end" | "baseline"` — Alinhamento vertical. Padrão: center.
- `justify?`: `"start" | "between" | "end"` — Distribuição horizontal. Padrão: start.
- `wrap?`: `boolean` — Quebra linha quando não cabe. Padrão: true.
- `children`: `ReactNode`

## SessionStatus

Estado da sessão no topo: usuário e botão de sair, ou aviso de que não há sessão.

- `user`: `string | null` — Usuário da sessão; null quando não há sessão.
- `onSignOut`: `() => void` — Encerra a sessão.

## Spinner

Indicador de carregamento acessível.

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
