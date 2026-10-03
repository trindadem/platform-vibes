# Spec: financeiro

## 1. Objetivo Operacional
O pacote de ações financeiras do BPO (briefing.md §4): o que os processos de contas a pagar, conciliação, faturamento
e fechamento chamam. Desde o N4 ele executa as ações do contas a pagar pelo worker do motor (core/processes.py), com
o cadastro de fornecedores que a conferência e a classificação usam, e mostra as contas que agendou.

## 2. Contrato de Entrada e Saída
Ações (`processes.declare` e `processes.worker`), cada uma o método de mesmo nome no service.py:
- `financeiro.conferir_pedido` (leitura): `Documento {fornecedor, cnpj, valor, vencimento, linha_digitavel}` → `Conferencia {divergente, diferenca, pedido, fornecedor_novo}`.
- `financeiro.classificar` (escrita): `Documento` → `Classificacao {conta, centro_custo}`.
- `financeiro.agendar_pagamento` (irreversível, conexão Banco): `Pagamento {valor, vencimento, fornecedor, linha_digitavel}` → `Agendamento {pagamento_id, data}`.
- `financeiro.conciliar` (escrita, conexão Banco): `Comprovante {pagamento_id}` → `Conciliacao {conciliado, diferenca}`.
Rotas:
- Cadastro declarado `fornecedores` (README §5.19): `Fornecedor {nome (único), cnpj, conta (padrão 2.1.01 Fornecedores), centro_custo, valor_contrato}`; escrevem dono, admin e operador.
- `GET /titulos?page&size&sort&status` → `TituloPage` de `Titulo {id, fornecedor, valor, vencimento, data, pagamento_id, status: agendado|pago, created_at}`.
- Ao vivo: `financeiro.fornecedores` e `financeiro.titulos {id, action: agendado|pago}`.
- Consome o RPC `rpc.integracoes.banco_agendar` (contrato repetido no schemas.py).

## 3. Fluxo de Execução
1. No boot, declara o módulo e as ações (catálogo no svc-processos) e sobe o worker dos jobs `financeiro.<ação>` no Camunda.
2. Conferir: acha o fornecedor pelo CNPJ (só os dígitos) e, sem ele, pelo nome; sem cadastro é fornecedor novo. Com valor de contrato, diverge quando a diferença passa de 1% (mínimo R$ 1). Sem valor no documento → handoff.
3. Classificar: a conta e o centro de custo do fornecedor; fornecedor novo entra no cadastro com a conta padrão (a nota seguinte dele já não é nova).
4. Agendar: pede ao banco conectado (svc-integracoes) e grava o título agendado em `financeiro_titulos`. Conciliar: o título com aquele pagamento fica pago.

## 4. Casos de Borda e Erros Mapeados
- Entrada que falta campo obrigatório (ex.: sem vencimento) → handoff "Faltam dados para ..." (core/processes.py).
- Sem banco conectado → o 409 do svc-integracoes vira handoff com a mensagem; svc-integracoes fora do ar → 503 `ERRO_FINANCEIRO_BANCO_FORA` (o motor tenta de novo).
- Comprovante de pagamento que não está nos títulos → handoff. Fornecedor com o mesmo nome cadastrado ao mesmo tempo por outro processo: segue com a conta padrão.
- Exemplo de saída que não confere com o modelo de saída, ou ação sem método no service.py: o serviço não sobe.
