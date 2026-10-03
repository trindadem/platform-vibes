# Spec: staff

## 1. Objetivo Operacional
A área da equipe da Cogniventure (briefing.md §5.5): cada pessoa do staff cuida de uma carteira de clientes e vê, numa
fila só, o que espera por ela em cada um deles (exceções dos processos, revisões de versão, pedidos de ajuda no
desenho), por prazo. Exceção que passa do prazo sem ninguém assumir sobe para o gestor. O staff resolve dentro da
organização do cliente, com o papel `operador`, que a carteira dá e tira sozinha.
Módulo (schemas.MODULE): "Staff", categoria Cogniventure, desligado por padrão: o plano da organização da plataforma
(`PLATFORM_TENANT`) o liga. Tela em /staff.

## 2. Contrato de Entrada e Saída
Staff é quem está na organização da Cogniventure (`PLATFORM_TENANT`, sessão nela); gestor é dono ou admin dela. Fora
disso, toda rota responde 403 (menos `/resumo`, que responde `staff: false`).
- `GET /resumo` → `Resumo {staff, gestor, excecoes, atrasadas, escaladas, revisoes, ajudas, organizacoes}`: a fila
  aberta de quem pergunta (o gestor vê todas).
- Carteira:
  - `GET /organizacoes` → `Organizacoes {items[{id, name, created_at}]}`: as organizações clientes (sem a da
    Cogniventure). Só gestor.
  - `GET /carteiras` → `Carteiras {itens[Carteira {id, pessoa, organizacao, organizacao_nome, created_at}]}`: o
    gestor vê todas; cada pessoa, as suas.
  - `POST /carteiras {pessoa, organizacao}` → `Carteira`: a pessoa (do staff) ganha o papel `operador` na
    organização. Só gestor.
  - `POST /carteiras/remover {id}` → `Carteira`: a pessoa perde o papel `operador` (sem outro papel, sai da
    organização e perde as sessões nela). Só gestor.
  - `GET /carteira` → `MinhaCarteira {gestor, itens[Saude {organizacao, nome, andamento, concluidas, incidentes,
    autonomia, excecoes, revisoes, ajudas, disponivel}]}`: cada cliente da carteira de quem pede, com a saúde (do
    svc-processos) e o que está aberto na fila.
- Fila:
  - `GET /fila?page&size&sort=prazo|created_at&tipo&status&escalada&organizacao&todas` → `FilaPage` de
    `ItemFila {id, organizacao, organizacao_nome, tipo: excecao|revisao|ajuda, ref, titulo, detalhe, prazo, status:
    aberta|concluida, link, assumida_por, atribuida_a, escalada, created_at, updated_at}`. Só as organizações da
    carteira de quem pede; `todas=true` (só gestor) traz a fila inteira. `link` é a tela onde resolver, dentro da
    organização do cliente (troque de organização antes de abrir).
  - `POST /fila/assumir {id}` → `ItemFila`: quem assume responde pelo item (não sobe para o gestor). Precisa ter a
    organização na carteira (o gestor assume qualquer um).
  - `POST /fila/atribuir {id, pessoa}` → `ItemFila`: o gestor passa o item para alguém do staff, que é avisado.
- Entra: evento `events.processos.staff` (`ItemStaff {tipo, ref, titulo, detalhe, prazo, status, link, em}`),
  publicado pelo svc-processos como a organização do cliente.
- Chama: RPC `rpc.identity.organizacoes` e `rpc.identity.operador {user, tenant, ativo}` (só o svc-staff, agindo na
  organização da Cogniventure); RPC `rpc.processos.acompanhamento` agindo na organização do cliente.
- Ao vivo: `staff.carteiras {id, action: atribuida|removida}` e `staff.fila {id, action: chegou|mudou|escalada}`.

## 3. Fluxo de Execução
1. SurrealDB, na organização da Cogniventure: `staff_carteiras` (pessoa + organização únicos) e `staff_fila` (chave
   `organização:tipo:ref` única).
2. Carteira: atribuir confere a organização no svc-identity e pede o papel `operador` para a pessoa (o svc-identity
   recusa quem não é da Cogniventure); remover tira o papel.
3. Fila: cada `events.processos.staff` aberto cria o item (ou o reabre: volta sem dono e sem escalada); concluído
   fecha. A mesma entrega duas vezes não duplica. O svc-processos publica: exceção para o staff aberta (com o prazo da
   tarefa, 4 h) e resolvida; revisão pedida e resolvida (aprovada ou devolvida); ajuda pedida e resolvida.
4. Escalonamento: o agendamento `escalar-excecoes` (a cada minuto, `EscalarWorkflow` → `staff.escalar`) marca como
   escalada a exceção aberta que passou do prazo sem ninguém assumir e avisa os gestores, uma vez por item.
5. Ciclo de vida (README §5.13): o agendamento acima; migrações (service.MIGRATIONS): nenhuma ainda.

## 4. Casos de Borda e Erros Mapeados
- Quem não é da Cogniventure (ou está na sessão de um cliente) → 403 `ERRO_STAFF_FORBIDDEN`; montar carteira,
  ver todas e atribuir são só do gestor (403 para o resto do staff); assumir item de organização fora da carteira → 403.
- Organização inexistente ou a própria Cogniventure → 404 `ERRO_STAFF_ORGANIZACAO`; pessoa que não é do staff →
  404 `ERRO_STAFF_PESSOA`; mesma organização de novo na carteira da pessoa → 409 `ERRO_STAFF_JA_NA_CARTEIRA`.
- Carteira ou item inexistente → 404 `ERRO_STAFF_NAO_ENCONTRADO`.
- svc-identity fora do ar → 503 `ERRO_STAFF_IDENTIDADE`; svc-processos fora do ar → a saúde daquele cliente vem com
  `disponivel: false` (o resto da carteira aparece).
- Sem `PLATFORM_TENANT` configurado: ninguém é staff, os eventos são ignorados e o escalonamento não faz nada.
