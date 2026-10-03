# Spec: integracoes

## 1. Objetivo Operacional
As conexões da empresa com o mundo de fora, que os processos usam (briefing.md §5.6). Neste bloco (N4): a caixa de
entrada, um endereço da organização para onde os fornecedores (ou a própria empresa) encaminham boletos e notas, e o
banco simulado, onde o contas a pagar agenda pagamentos até o banco de verdade ser escolhido (briefing.md §14,
decisão 6). O que chega vira evento para o svc-processos iniciar execuções e acordar as que esperam.

## 2. Contrato de Entrada e Saída
- `GET /conexoes` → `Conexoes {itens[Conexao {id, tipo: caixa_entrada|banco_simulado, nome, endereco, confirmar_apos, created_at}]}`.
- `POST /conexoes {tipo, nome?, confirmar_apos: 5..86400 (banco_simulado; padrão 30)}` → `Conexao`. Uma de cada tipo por organização; a caixa de entrada nasce com o endereço `<organização>.<código>@<INTEGRACOES_DOMINIO>`. Dono e admin.
- `POST /conexoes/remover {id}` → `Conexao`. Dono e admin.
- `GET /resumo` → `Resumo {caixa_entrada, banco, documentos, agendados}`.
- `GET /documentos?page&size&sort&q` → `DocumentoPage` de `Documento {id, origem: email, de, assunto, nome, tipo, tamanho, tem_texto, created_at}`; `GET /documentos/arquivo?id` → `Link {url (5 min), nome, tipo}`.
- `GET /pagamentos?page&size&sort&status` → `PagamentoPage` de `Pagamento {id, pagamento_id, valor, data, fornecedor, linha_digitavel, status: agendado|pago, pago_em}`; `POST /pagamentos/confirmar {id}` → `Pagamento` (o banco simulado pagou agora; dono, admin ou operador).
- `POST /entrada/mailpit {ID}` → `Recebidos {documentos}`: rota pública só na rede interna e só no ambiente local (sem `INTEGRACOES_MAILPIT_URL`, 404): o Mailpit avisa que chegou um e-mail. Fora do manifesto do gateway.
- RPC `rpc.integracoes.documento {id}` → `DocumentoTexto {id, nome, tipo, de, assunto, texto}` (agentes do svc-processos); `rpc.integracoes.banco_agendar {valor, vencimento?, fornecedor?, linha_digitavel?}` → `PagamentoAgendado {pagamento_id, data}` (ação do svc-financeiro). Na organização de quem pede.
- Evento `events.integracoes.evento {nome: documento.recebido|banco.pago, chave?, dados}`: `documento.recebido` com `{documento_id, origem, de, assunto, nome}`; `banco.pago` com chave = id do pagamento e `{pagamento_id, valor, pago_em}`.
- Ao vivo: `integracoes.conexoes`, `integracoes.documentos {id, action: recebido}`, `integracoes.pagamentos {id, action: agendado|pago}`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `integracoes_conexoes` (tipo único), `integracoes_documentos` (origem_id único, busca em nome, assunto e remetente; o arquivo no armazenamento, o texto extraído no registro) e `integracoes_pagamentos` (pagamento_id único).
2. Caixa de entrada: a mensagem RFC 822 é lida (no ambiente local, do Mailpit, que avisa por webhook); cada destinatário `<organização>.<código>@<domínio>` com caixa conectada recebe, como a organização dele, cada anexo aceito (PDF, imagem, XML, texto; até 10 MB) como documento (sem anexo, o corpo do e-mail). Texto de PDF e XML é extraído (sem OCR: imagem fica sem texto). O mesmo aviso de novo não duplica. Cada documento novo publica `documento.recebido`.
3. Em produção, o provedor de entrada (SES, Mailgun, Postmark...) chama o serviço com a mensagem crua; fica para quando o provedor for escolhido (briefing.md §14, decisão 6).
4. Banco simulado: agendar grava o pagamento (data = vencimento, ou hoje se vencido) e inicia um workflow durável que espera `confirmar_apos` segundos e confirma; confirmar (sozinho ou à mão) marca pago e publica `banco.pago` uma vez só.

## 4. Casos de Borda e Erros Mapeados
- Membro mexendo em conexão → 403 `ERRO_INTEGRACOES_FORBIDDEN`; confirmar pagamento é de dono, admin ou operador (403 para os outros).
- Conexão do mesmo tipo de novo → 409 `ERRO_INTEGRACOES_JA_CONECTADA`. Conexão, documento ou pagamento de outra organização ou inexistente → 404 `ERRO_INTEGRACOES_NAO_ENCONTRADA`/`ERRO_INTEGRACOES_NAO_ENCONTRADO`.
- Agendar sem banco conectado → 409 `ERRO_INTEGRACOES_SEM_BANCO` (no processo, o passo vai para a exceção do staff).
- Aviso do Mailpit sem provedor configurado → 404 `ERRO_INTEGRACOES_SEM_PROVEDOR`; e-mail avisado que não existe → 404 `ERRO_INTEGRACOES_EMAIL`. Destinatário sem caixa conectada, código errado, anexo de tipo não aceito ou grande demais: ignorado.
- Arquivo sem texto ou corrompido: o documento fica sem texto (`tem_texto` falso); o agente que o lê pede ajuda ao staff.
