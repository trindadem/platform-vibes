# Spec: staff

## 1. Objetivo Operacional
A área da equipe da Cogniventure (briefing.md §5.5): cada pessoa do staff cuida de uma carteira de clientes e vê, numa
fila só, o que espera por ela em cada um deles (exceções dos processos, revisões de versão, pedidos de ajuda no
desenho, pedidos de ajuda do Falar com a Cogniventure), por prazo. Exceção ou pedido que passa do prazo sem ninguém
assumir sobe para o gestor. O staff resolve exceção, revisão e pedido no próprio cartão da fila, sem trocar de
organização; a conversa de desenho abre no cliente, com o papel `operador`, que a carteira dá e tira sozinha. O gestor
abre os clientes (organização, convite do dono, plano e carteira) e vê os números do atendimento.
Módulo (schemas.MODULE): "Staff", categoria Cogniventure, desligado por padrão: o plano da organização da plataforma
(`PLATFORM_TENANT`) o liga. Tela em /staff.

## 2. Contrato de Entrada e Saída
Staff é quem está na organização da Cogniventure (`PLATFORM_TENANT`, sessão nela); gestor é dono ou admin dela. Fora
disso, toda rota responde 403 (menos `/resumo`, que responde `staff: false`).
- `GET /resumo` → `Resumo {staff, gestor, excecoes, atrasadas, escaladas, revisoes, ajudas, organizacoes}`: a fila
  aberta de quem pergunta (o gestor vê todas).
- Clientes (só gestor):
  - `GET /clientes` → `Clientes {itens[Cliente {organizacao, nome, created_at, plano, responsaveis[], dono {name, email},
    convite {email, expires_at}, passo: convite|briefing|descoberta|desenho|acompanhamento, ultimo_acesso, andamento,
    autonomia}]}`: cada cliente com o plano, quem do staff cuida, o dono (ou o convite pendente), onde está na jornada e
    o último acesso de alguém dele (o staff não conta). Passo em branco: o cliente não respondeu agora.
  - `POST /clientes {empresa, email, plano, pessoa}` → `Cliente`: abre a organização sem ninguém da Cogniventure dentro,
    com o convite de dono por e-mail; atribui o plano; põe na carteira da pessoa (que vira operador).
  - `POST /clientes/convite {organizacao}` → `Cliente`: o convite do dono de novo (o anterior deixa de valer).
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
  - Resolver no cartão (quem tem a organização na carteira; o gestor, todas): `GET /fila/detalhe?id` →
    `FilaDetalhe {item, tarefa?, revisao?, pedido?}` (a exceção com campos e contexto, a versão em revisão com o que
    muda, ou o pedido com a conversa); `POST /fila/resolver {id, dados, comentario?, regra?}` (exceção),
    `POST /fila/revisao {id, aprovar, motivo?}` (aprovar publica; devolver exige o motivo) e
    `POST /fila/responder {id, texto}` (pedido de ajuda) → `ItemFila` concluído, com `resolvida_por`.
- `GET /numeros?dias=30` → `Numeros {desde, pessoas[NumeroLinha], clientes[NumeroLinha]}` com `NumeroLinha {chave,
  nome, resolvidos, no_prazo, tempo_medio_min, abertos}`: por pessoa e por cliente no período. Só gestor.
- Entra: eventos `events.processos.staff` (svc-processos) e `events.atendimento.staff` (svc-atendimento), ambos
  `ItemStaff {tipo: excecao|revisao|ajuda|pedido, ref, titulo, detalhe, prazo, status, link, em, por}`, publicados
  como a organização do cliente (`por`: quem resolveu); `events.identity.member-left {tenant, user}`.
- Chama, agindo na organização da Cogniventure: `rpc.identity.organizacoes`, `rpc.identity.operador {user, tenant,
  ativo}`, `rpc.identity.cliente {empresa, email}`, `rpc.identity.convite_dono {tenant}` e `rpc.identity.contacts`.
  Agindo na organização do cliente: `rpc.processos.acompanhamento`, `rpc.conhecimento.contexto`, `rpc.plans.assign`
  e `rpc.plans.limits` (core), `rpc.processos.fila_tarefa|fila_resolver|fila_revisao|fila_decidir` e
  `rpc.atendimento.pedido|responder` (com `por` = quem do staff resolve).
- Ao vivo: `staff.carteiras {id, action: atribuida|removida}` e `staff.fila {id, action: chegou|mudou|escalada}`.

## 3. Fluxo de Execução
1. SurrealDB, na organização da Cogniventure: `staff_carteiras` (pessoa + organização únicos) e `staff_fila` (chave
   `organização:tipo:ref` única).
2. Carteira: atribuir confere a organização no svc-identity e pede o papel `operador` para a pessoa (o svc-identity
   recusa quem não é da Cogniventure); remover tira o papel.
3. Fila: cada item aberto cria o item (ou o reabre: volta sem dono e sem escalada); concluído fecha, com a hora e quem
   resolveu. A mesma entrega duas vezes não duplica. O svc-processos publica: exceção para o staff aberta (com o prazo
   da tarefa, 4 h) e resolvida; revisão pedida e resolvida (aprovada ou devolvida); ajuda pedida e resolvida. O
   svc-atendimento publica o pedido de ajuda aberto (4 h), respondido e encerrado.
4. Escalonamento: o agendamento `escalar-excecoes` (a cada minuto, `EscalarWorkflow` → `staff.escalar`) marca como
   escalada a exceção ou o pedido aberto que passou do prazo sem ninguém assumir e avisa os gestores, uma vez por item.
5. Resolver no cartão: confere a carteira, pede ao serviço do item na organização do cliente (com quem do staff
   resolve) e fecha o item na hora; o aviso do serviço chega depois e confirma.
6. Clientes: o svc-identity cria a organização com o convite de dono; o plano vem do core (`plans.assign` como tarefa
   da plataforma); a carteira dá o papel operador. O passo da jornada: convite (sem dono), briefing (não concluído),
   descoberta (nenhum processo aceito), desenho (nenhum publicado), acompanhamento.
7. Saída do staff: quem sai da Cogniventure (`events.identity.member-left` da organização da plataforma) sai de todas
   as carteiras e perde o papel operador nos clientes; os itens que estavam com a pessoa voltam sem dono.
8. Ciclo de vida (README §5.13): o agendamento acima; migrações (service.MIGRATIONS): nenhuma ainda.

## 4. Casos de Borda e Erros Mapeados
- Quem não é da Cogniventure (ou está na sessão de um cliente) → 403 `ERRO_STAFF_FORBIDDEN`; montar carteira,
  ver todas e atribuir são só do gestor (403 para o resto do staff); assumir item de organização fora da carteira → 403.
- Organização inexistente ou a própria Cogniventure → 404 `ERRO_STAFF_ORGANIZACAO`; pessoa que não é do staff →
  404 `ERRO_STAFF_PESSOA`; mesma organização de novo na carteira da pessoa → 409 `ERRO_STAFF_JA_NA_CARTEIRA`.
- Carteira ou item inexistente → 404 `ERRO_STAFF_NAO_ENCONTRADO`.
- Resolver no cartão: item de outro tipo → 409 `ERRO_STAFF_TIPO`; já resolvido → 409 `ERRO_STAFF_RESOLVIDO`; devolver
  revisão sem motivo → 422 `ERRO_STAFF_MOTIVO`; serviço do item fora do ar → 503 `ERRO_STAFF_CLIENTE`; o erro de
  negócio do serviço do item volta como veio (ex.: 422 `ERRO_PROCESSOS_RESPOSTA`).
- Novo cliente com responsável que não é do staff → 404 `ERRO_STAFF_PESSOA`, sem criar nada; plano inexistente → 404
  `ERRO_PLANS_NOT_FOUND` (a organização fica criada, sem plano: ele é atribuído em Plano).
- svc-identity fora do ar → 503 `ERRO_STAFF_IDENTIDADE`; svc-processos fora do ar → a saúde daquele cliente vem com
  `disponivel: false` (o resto da carteira aparece).
- Sem `PLATFORM_TENANT` configurado: ninguém é staff, os eventos são ignorados e o escalonamento não faz nada.
