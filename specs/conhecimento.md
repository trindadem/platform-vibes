# Spec: conhecimento

## 1. Objetivo Operacional
O primeiro passo da jornada do cliente BPO (briefing.md §3): o briefing conversado com um agente, que preenche o
perfil da empresa, e a base de conhecimento (site, documentos, respostas) que todos os agentes consultam. O cliente
vê, corrige e apaga o que a plataforma sabe dele; o workspace mostra em que pé está.

## 2. Contrato de Entrada e Saída
- `GET /briefing` → `Briefing {perfil, topicos[{id, titulo, status: feito|em_andamento|a_fazer, faltam[]}], mensagens[{id, papel: cliente|agente, texto, passos[], created_at}], concluido_em, pode_concluir}`. A primeira mensagem é a abertura fixa do agente.
- `POST /briefing/mensagem {texto: 1..4000}` → em pedaços: `Passo {ferramenta, texto, status: running|done|failed}` a cada ferramenta do agente; resultado `Briefing`. Dono e admin.
- `POST /briefing/perfil Perfil` (só os campos que mudam; vazio apaga) → `Briefing`. Campos do perfil: atividade, segmento, porte (mei|micro|pequena|media|grande), cidade, uf, site, produtos, clientes, canais_venda, bancos, recebimentos, pagamentos, contabilidade, regime_tributario (mei|simples|presumido|real|nao_sei), sistemas, documentos, colaboradores (0..100000), equipe, dores, objetivos.
- `POST /briefing/concluir {}` e `POST /briefing/reabrir {}` → `Briefing`. Concluir exige todos os tópicos feitos.
- Cadastro declarado `itens` (README §5.19): `titulo` (2..160), `conteudo` (até 5000), `tipo` (empresa|produto|cliente|fornecedor|processo|politica|contato|outro), `fonte` (briefing|site|documento|manual), `origem` (URL ou arquivo), `validade` (data). Escrita: dono e admin.
- `GET /busca?q=` → `Achados {itens[{id, titulo, trecho, fonte, origem, nota}]}`: as palavras da consulta em qualquer ordem, as melhores 5.
- `POST /site {url}` → `Leitura`. `POST /documentos/upload {filename, content_type, size}` → link de envio; `POST /documentos {key}` → `Leitura`. Documento: PDF, DOCX, TXT, MD ou CSV, até 10 MB.
- `GET /leituras?page&size&sort&status&tipo` → `LeituraPage` de `Leitura {id, tipo: site|documento, origem, status: lendo|pronta|falhou, paginas, itens, erro, created_at}`. `POST /leituras/remove {id}` apaga a leitura e os itens dela.
- `GET /resumo` → `Resumo {topicos_feitos, topicos_total, concluido_em, itens, por_fonte, leituras_lendo}` (workspace).
- Ao vivo: `conhecimento.briefing`, `conhecimento.leituras` e `conhecimento.itens`.
- RPC para outros serviços, na organização de quem pede: `rpc.conhecimento.contexto {}` → `ContextoEmpresa {perfil, topicos, concluido_em}`; `rpc.conhecimento.busca {q}` → `Achados`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `conhecimento_perfil` (um por organização, com `concluido_em`), `conhecimento_mensagens` (papel, texto, passos), `conhecimento_itens` (cadastro, busca BM25 em título e conteúdo) e `conhecimento_leituras` (tipo, origem, arquivo, status, itens).
2. Mensagem: grava a do cliente, roda o agente de briefing (`llm.run_agent`, modelo `CONHECIMENTO_MODEL`, padrão `cv/agente`) com o perfil, os tópicos e as últimas 20 mensagens no contexto e as ferramentas `registrar_perfil`, `buscar_conhecimento`, `registrar_conhecimento` e `ler_site`; grava a resposta e avisa `conhecimento.briefing`.
3. Leitura de site ou documento: grava a leitura (`lendo`) e inicia `LeituraWorkflow` no Temporal, que chama `ler_site` (até 8 páginas do mesmo site, linhas repetidas entre páginas descartadas) ou `ler_documento` (texto do arquivo guardado), corta o texto em itens de até 4500 caracteres e grava; 3 tentativas, 5 min cada; esgotadas, a leitura fica `falhou`. Ler de novo a mesma origem troca os itens antigos.

## 4. Casos de Borda e Erros Mapeados
- Membro tentando escrever → 403 `ERRO_CONHECIMENTO_FORBIDDEN`. Concluir com tópico pendente → 409 `ERRO_CONHECIMENTO_BRIEFING_INCOMPLETO`.
- Site fora do ar, sem HTML ou com endereço interno → leitura `falhou` com o motivo; URL inválida → 422.
- Documento de outro tipo ou maior que 10 MB → 422 `ERRO_FILE_TYPE`/`ERRO_FILE_TOO_LARGE`; PDF sem texto (escaneado) → leitura `falhou` ("sem texto para ler").
- Itens acima do plano (`conhecimento.itens`, padrão 2000) → 402 `ERRO_PLAN_LIMIT`; a leitura confere antes de gravar.
- Modelo indisponível, provedor recusando ou plano de IA esgotado → os erros de `core/llm.py`; a mensagem do cliente fica gravada.
