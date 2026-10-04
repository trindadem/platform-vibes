# Spec: atendimento

## 1. Objetivo Operacional
O "Falar com a Cogniventure": qualquer pessoa de um cliente pede ajuda de qualquer tela (uma execução parada, um
documento, a conexão do banco, a cobrança), e o pedido chega à fila do staff com prazo de 4 horas. O operador da
carteira responde, o cliente recebe o aviso e vê o histórico dos pedidos. Alinhamento pós-N7, item 5. A ajuda no
desenho de um processo continua no svc-processos.
Módulo (schemas.MODULE): "Falar com a Cogniventure", categoria Organização, da plataforma (sempre ligado).

## 2. Contrato de Entrada e Saída
Todas as rotas exigem token e valem para a organização ativa.
- `GET /resumo` → `Resumo {pode_pedir, abertos, respondidos}`: `pode_pedir` é falso na organização da Cogniventure
  (`PLATFORM_TENANT`) e para quem só é operador ali (o staff não pede ajuda a si mesmo).
- `GET /pedidos?page&size&sort&status` → `PedidoPage` de `Pedido {id, assunto, status: aberto|respondido|encerrado,
  pagina, autor, autor_nome, mensagens[{papel: cliente|staff, autor, autor_nome, texto, em}], prazo, respondido_em,
  created_at, updated_at}`. Dono, admin e operador veem os da organização; membro, os seus.
- `POST /pedidos {texto: 3..2000, pagina?}` → `Pedido`: abre o pedido (o assunto são as primeiras palavras do texto;
  `pagina` é a tela de onde a pessoa pediu). Não vale para quem não pode pedir (403).
- `POST /pedidos/mensagem {id, texto}` → `Pedido`: a pessoa do cliente acrescenta (o pedido volta a aberto, com prazo
  novo de 4 h); o operador responde (fica respondido e quem pediu é avisado).
- `POST /pedidos/encerrar {id}` → `Pedido`: quem pediu, dono ou admin encerram.
- RPC do staff (só o svc-staff, agindo na organização do cliente; a fila responde sem trocar de organização):
  `rpc.atendimento.pedido {id}` → `Pedido` e `rpc.atendimento.responder {id, texto, por, por_nome}` → `Pedido`.
- Publica `events.atendimento.staff` (`ItemStaff {tipo: pedido, ref, titulo, detalhe, prazo, status:
  aberta|concluida, link, em}`, o contrato do svc-processos) para a fila do svc-staff.
- Ao vivo: `atendimento.pedidos {id, action: aberto|respondido|encerrado}`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `atendimento_pedidos` (busca no assunto).
2. Abrir: grava o pedido com a primeira mensagem e o prazo (agora + 4 h), publica o item aberto para a fila do staff
   e avisa os operadores da organização (tela e e-mail).
3. Responder (operador na tela do cliente, ou o staff pela fila via RPC): a mensagem entra com papel staff, o pedido
   fica respondido, o item da fila fecha e quem pediu é avisado. Mensagem nova do cliente reabre com prazo novo.
4. Encerrar: fecha o item da fila, se ainda aberto. O nome de quem escreve vem do svc-identity (rpc.identity.contacts).
5. Ciclo de vida (README §5.13): agendamentos e migrações, nenhum ainda. O escalonamento por prazo é o do svc-staff.

## 4. Casos de Borda e Erros Mapeados
- Pedido de outra organização ou inexistente → 404 `ERRO_ATENDIMENTO_NAO_ENCONTRADO`; membro vendo ou escrevendo no
  pedido de outra pessoa → 404 (não revela que existe).
- Quem não pode pedir (Cogniventure, só operador) abrindo pedido → 403 `ERRO_ATENDIMENTO_FORBIDDEN`; encerrar pedido
  de outra pessoa sem ser dono ou admin → 403.
- Mensagem em pedido encerrado → 409 `ERRO_ATENDIMENTO_ENCERRADO`.
- RPC do staff chamada por outro serviço → 403 `ERRO_ATENDIMENTO_FORBIDDEN`.
- svc-identity fora do ar: o nome fica em branco (a mensagem entra assim mesmo).
