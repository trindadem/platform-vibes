# Spec: financeiro

## 1. Objetivo Operacional
O pacote de ações financeiras do BPO (briefing.md §4): o que os processos de contas a pagar, conciliação, faturamento
e fechamento chamam. Neste bloco (N3) ele declara as ações do contas a pagar, com entrada, saída, risco e exemplo,
para o desenho e a simulação; a execução delas pelo motor entra no N4.

## 2. Contrato de Entrada e Saída
Ações declaradas (`processes.declare`, core/processes.py), cada uma com a saída que as condições do fluxo usam:
- `financeiro.conferir_pedido` (leitura): `Documento {fornecedor, cnpj, valor, vencimento, linha_digitavel}` → `Conferencia {divergente, diferenca, pedido, fornecedor_novo}`.
- `financeiro.classificar` (escrita): `Documento` → `Classificacao {conta, centro_custo}`.
- `financeiro.agendar_pagamento` (irreversível, conexão Banco): `Pagamento {valor, vencimento, linha_digitavel}` → `Agendamento {pagamento_id, data}`.
- `financeiro.conciliar` (escrita, conexão Banco): `Comprovante {pagamento_id}` → `Conciliacao {conciliado, diferenca}`.
Sem manifesto no gateway neste bloco (nenhuma rota pública): o pacote só declara as ações.

## 3. Fluxo de Execução
1. No boot, declara o módulo (plano) e as ações (evento `events.processos.catalogo`, o svc-processos guarda o catálogo).
2. Sem tabelas, eventos nem activities neste bloco.

## 4. Casos de Borda e Erros Mapeados
- Exemplo de saída que não confere com o modelo de saída impede o boot (core/processes.py).
- Ação chamada pelo motor antes do N4: não há worker; o processo publicado espera (o job fica pendente no Camunda).
