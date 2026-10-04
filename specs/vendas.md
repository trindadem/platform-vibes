# Spec: vendas

## 1. Objetivo Operacional
O pacote de ações de vendas do BPO (briefing.md §4 e §10): o que os processos de qualificação de leads, proposta
comercial e reativação de carteira chamam. Guarda leads, clientes e propostas; marca reuniões, envia propostas,
follow-ups e campanhas pela caixa de entrada da empresa. Uma proposta aceita registra o cliente e, pelo gatilho de
processo, inicia o contrato e o faturamento (briefing.md §5.8): é o começo de um projeto no workspace.

## 2. Contrato de Entrada e Saída
Ações (`processes.declare` e `processes.worker`), cada uma o método de mesmo nome no service.py:
- `vendas.registrar_lead` (escrita): `LeadIn {lead_id, nome, email, telefone, origem, interesse}` → `LeadRegistrado {lead_id, novo}`.
- `vendas.agendar_reuniao` (externa, conexão Caixa de entrada): `LeadRef {lead_id, resumo}` → `Reuniao {reuniao_em}`.
- `vendas.nutrir` (escrita): `LeadRef` → `Nutricao {status}`.
- `vendas.registrar_proposta` (escrita): `PropostaIn {proposta_id, cliente, email, descricao, valor, desconto}` → `PropostaMontada {proposta_id, validade}`.
- `vendas.enviar_proposta` (externa, conexão Caixa de entrada): `PropostaRef {proposta_id}` → `PropostaEnviada {enviada_em}`.
- `vendas.registrar_resposta` (escrita): `RespostaIn {proposta_id, aprovado}` → `Desfecho {status: aceita|recusada, aceita}`.
- `vendas.selecionar_inativos` (leitura): `Inatividade {dias_sem_comprar}` → `Inativos {clientes, nomes}`.
- `vendas.enviar_campanha` (externa, conexão Caixa de entrada): `Campanha {mensagem, dias_sem_comprar}` → `CampanhaEnviada {enviados}`.
Modelos: `qualificacao-leads` (evento `vendas.lead`), `proposta-comercial` (evento `vendas.pedido_proposta`; termina
`aceita`, `recusada` ou `nao_enviada`) e `reativacao-carteira` (segundas, 9h).
Indicadores do mês (alinhamento pós-N7, item 7): leads: recebidos (iniciados no mês), qualificados (%, dos
encaminhados) e tempo até a primeira resposta (horas, da chegada ao encaminhamento); propostas: enviadas e taxa de
aceite (pacote) e valor aceito (soma das aceitas); reativação: clientes contatados (soma) e voltaram a comprar
(pacote). RPC `rpc.vendas.indicadores` (`IndicatorRequest` → `IndicatorValues`): enviadas = propostas com `enviada_em`
no mês; aceite = aceitas ÷ respondidas no mês (sem resposta: sem dado); voltaram = clientes com campanha e a última
compra no mês, depois dela. Oportunidade no CRM ainda não existe: a compra depois da campanha é o que se mede.
Rotas:
- Cadastros declarados (README §5.19), escrevem dono, admin e operador: `leads` (`Lead {nome, email, telefone, origem: site|instagram|whatsapp|indicacao|outro, interesse, status: novo|qualificado|reuniao|nutricao|atendimento|cliente, reuniao_em}`) e `clientes` (`Cliente {nome, email, telefone, ultima_compra, campanha_em}`).
- `POST /leads/receber {nome, email?, telefone?, origem, interesse}` → `LeadItem`: o lead entra (novo) e emite `vendas.lead`.
- `GET /propostas?page&size&sort&status&q` → `PropostaPage` de `Proposta {id, cliente, email, pedido, descricao, valor, desconto, validade, status: pedida|montada|enviada|aceita|recusada, enviada_em, follow_ups[], respondida_em, created_at}`.
- `POST /propostas {cliente, email?, pedido}` → `Proposta`: o pedido de proposta entra e emite `vendas.pedido_proposta`. Dono, admin e operador.
- Ao vivo: `vendas.leads`, `vendas.clientes` e `vendas.propostas {id, action}`.
- Consome `rpc.integracoes.enviar_email` (contrato repetido no schemas.py); emite `events.processos.evento` por `processes.emit`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `vendas_leads`, `vendas_clientes` (cadastros declarados) e `vendas_propostas` (busca em
   cliente e pedido).
2. Lead: com `lead_id` o lead já existe; sem, entra (o mesmo e-mail não duplica). Reunião no próximo horário livre (dia
   útil, das 10h às 16h, uma por hora), com convite por e-mail ao lead e aviso a dono e administrador. Nutrição só
   muda o status (a campanha de reativação alcança quem está nela).
3. Proposta: montada pelo agente do processo (descrição, valor, desconto) e registrada com validade de 15 dias;
   enviada por e-mail ao cliente; a resposta (tarefa da empresa) fecha como aceita ou recusada, e a aceita registra o
   cliente com a compra de hoje.
4. Agendamento diário (`FollowUpWorkflow`, 10h em Brasília): proposta enviada e sem resposta há 3 e há 7 dias recebe
   um follow-up por e-mail, cada um uma vez.
5. Reativação: clientes com a última compra há mais de `dias_sem_comprar` (padrão 90) e sem campanha nesse período
   recebem a mensagem por e-mail; cada envio grava `campanha_em`.

## 4. Casos de Borda e Erros Mapeados
- Sem caixa de entrada conectada (ou sem provedor de envio) → o 409 do svc-integracoes vira handoff; fora do ar → 503 `ERRO_VENDAS_INTEGRACOES_FORA`.
- Lead ou proposta inexistente, proposta sem e-mail do cliente, lead sem nome → handoff; registrar resposta sem saber
  se foi aceita → handoff.
- Membro pedindo proposta ou recebendo lead → 403 `ERRO_VENDAS_FORBIDDEN`.
- Exemplo de saída que não confere, ação sem método ou modelo com ação não declarada: o serviço não sobe.
- Indicadores: mês inválido ou que ainda não começou, ou nome que o pacote não calcula → null (sem dado no mês); a
  tela mostra "—". Indicador "pacote" declarado sem `indicators=` no `processes.declare`: o serviço não sobe.
