# Spec: financeiro

## 1. Objetivo Operacional
O pacote de ações financeiras do BPO (briefing.md §4 e §10): o que os processos de contas a pagar, conciliação
bancária, faturamento e cobrança e fechamento do mês chamam, e o fluxo de partida de cada um. Executa as ações pelo
worker do motor (core/processes.py), guarda fornecedores, títulos (contas a pagar) e faturas (contas a receber), roda
a régua de cobrança e mostra o que os processos agendaram e faturaram.

## 2. Contrato de Entrada e Saída
Ações (`processes.declare` e `processes.worker`), cada uma o método de mesmo nome no service.py:
- `financeiro.conferir_pedido` (leitura): `Documento {fornecedor, cnpj, valor, vencimento, linha_digitavel}` → `Conferencia {divergente, diferenca, pedido, fornecedor_novo}`.
- `financeiro.classificar` (escrita): `Documento` → `Classificacao {conta, centro_custo}`.
- `financeiro.agendar_pagamento` (irreversível, conexão Banco): `Pagamento {valor, vencimento, fornecedor, linha_digitavel}` → `Agendamento {pagamento_id, data}`.
- `financeiro.conciliar` (escrita, conexão Banco): `Comprovante {pagamento_id}` → `Conciliacao {conciliado, diferenca}`.
- `financeiro.conciliar_extrato` (escrita, conexão Banco): `Janela {dias}` → `ConciliacaoDia {lancamentos, conciliados, sem_par, valor_sem_par}`.
- `financeiro.faturar` (escrita): `Faturamento {cliente, cnpj, email, descricao, valor, prazo_pagamento, proposta_id}` → `FaturaAberta {fatura_id, vencimento}`.
- `financeiro.emitir_nota` (externa, conexão NFS-e): `NotaIn {fatura_id}` → `Nota {nota_numero}`.
- `financeiro.cobrar` (externa, conexões Banco e Caixa de entrada): `CobrancaIn {fatura_id, nota_numero}` → `Cobranca {cobranca_id, linha_digitavel, vencimento, enviada}`.
- `financeiro.baixar` (escrita): `Recebimento {cobranca_id}` → `Baixa {recebido, valor}`.
- `financeiro.pendencias_do_mes` (leitura): `Mes {referencia}` → `Pendencias {referencia, pendencias, resumo}`.
- `financeiro.enviar_ao_contador` (externa, conexão Caixa de entrada): `EnvioContador {email_contador, referencia}` → `Envio {enviado_em}`.
- `financeiro.apurar_das` (escrita): `Apuracao {referencia, aliquota}` → `Das {valor, vencimento, fornecedor, linha_digitavel}`.
- `financeiro.montar_dre` (escrita): `Mes` → `Dre {referencia, receita, despesas, resultado, resumo}`.
Modelos (`processes.declare`): `contas-a-pagar` (evento `documento.recebido`), `conciliacao-bancaria` (todo dia, 8h em
Brasília), `faturamento-cobranca` (gatilho: a proposta comercial que termina aceita) e `fechamento-mes` (dia 1).
Rotas:
- Cadastro declarado `fornecedores` (README §5.19): `Fornecedor {nome (único), cnpj, conta (padrão 2.1.01 Fornecedores), centro_custo, valor_contrato}`; escrevem dono, admin e operador.
- `GET /titulos?page&size&sort&status` → `TituloPage` de `Titulo {id, fornecedor, valor, vencimento, data, pagamento_id, status: agendado|pago, conciliado, created_at}`.
- `GET /faturas?page&size&sort&status` → `FaturaPage` de `Fatura {id, cliente, cnpj, email, descricao, valor, vencimento, nota_numero, cobranca_id, linha_digitavel, status: aberta|cobrada|paga, regua[], recebido_em, conciliada, proposta_id, created_at}`.
- Ao vivo: `financeiro.fornecedores`, `financeiro.titulos {id, action: agendado|pago|conciliado}` e `financeiro.faturas {id, action: aberta|cobrada|paga|lembrete}`.
- Consome os RPCs `rpc.integracoes.banco_agendar`, `rpc.integracoes.banco_cobrar`, `rpc.integracoes.banco_extrato` e `rpc.integracoes.enviar_email` (contratos repetidos no schemas.py).

## 3. Fluxo de Execução
1. No boot, declara o módulo, as ações e os modelos (catálogo no svc-processos) e sobe o worker dos jobs `financeiro.<ação>` no Camunda.
2. SurrealDB, por organização: `financeiro_fornecedores` (cadastro), `financeiro_titulos` (pagamento_id único) e `financeiro_faturas`.
3. Conferir: acha o fornecedor pelo CNPJ (só os dígitos) e, sem ele, pelo nome; sem cadastro é fornecedor novo. Com valor de contrato, diverge quando a diferença passa de 1% (mínimo R$ 1). Sem valor no documento → handoff.
4. Classificar: a conta e o centro de custo do fornecedor; fornecedor novo entra no cadastro com a conta padrão (a nota seguinte dele já não é nova).
5. Agendar: pede ao banco conectado e grava o título agendado. Conciliar: o título com aquele pagamento fica pago.
6. Conciliar o extrato: pede o extrato desde ontem (ou `dias`); cada pagamento casa com um título (pago e conciliado) e cada recebimento com uma fatura (conciliada) pelo id; o resto é sem par, somado.
7. Faturar: a fatura nasce aberta com o `vencimento` que veio (a data combinada, como a mensalidade do plano que o fechamento da Cogniventure fatura) ou, sem ele, hoje + `prazo_pagamento` (padrão 15). Emitir nota: sem integração de NFS-e, o staff emite e informa o número (handoff). Cobrar: emite o boleto no banco e o envia por e-mail ao cliente (sem e-mail ou sem caixa de entrada, `enviada` falso). Baixar: confere no extrato se a cobrança foi recebida e marca a fatura paga.
8. Fechamento: pendências do mês (títulos sem comprovante, faturas sem nota); o resumo e os lançamentos por e-mail ao contador; DAS = receita do mês (faturas) × alíquota (padrão 6%), vencendo no dia 20 do mês seguinte; a DRE gerencial (receitas − despesas) vai como aviso a dono e administrador.
9. Agendamento diário (`ReguaWorkflow`, 9h em Brasília): fatura cobrada e não paga recebe por e-mail o lembrete D-3 (até 3 dias antes), D+1 e D+7, cada um uma vez (`regua`). No D+7, dono e admin da organização também são avisados (tela + e-mail): a vencida além do prazo chega ao gestor (na Cogniventure, ele suspende o cliente pela aba Clientes).

## 4. Casos de Borda e Erros Mapeados
- Entrada que falta campo obrigatório (ex.: sem vencimento) → handoff "Faltam dados para ..." (core/processes.py); faturar sem cliente ou valor → handoff.
- Sem banco ou sem caixa de entrada conectados → o 409 do svc-integracoes vira handoff com a mensagem; svc-integracoes fora do ar → 503 `ERRO_FINANCEIRO_INTEGRACOES_FORA` (o motor tenta de novo).
- NFS-e sem integração → handoff com o cliente e o valor; enviar ao contador sem `email_contador` → handoff.
- Comprovante ou cobrança que não está nos títulos ou nas faturas → handoff. Fornecedor com o mesmo nome cadastrado ao mesmo tempo por outro processo: segue com a conta padrão.
- Exemplo de saída que não confere com o modelo de saída, ação sem método no service.py ou modelo que cita ação não declarada: o serviço não sobe.
