# Spec: processos

## 1. Objetivo Operacional
O segundo e o terceiro passos da jornada do cliente BPO (briefing.md §3). Descoberta: a partir do briefing e do
conhecimento, um agente sugere os processos da biblioteca da Cogniventure que fazem sentido para a empresa, dizendo o
porquê, e o cliente aceita, recusa ou descreve um processo próprio. Desenho: cada processo aceito é adaptado numa
conversa com o agente de desenho, que edita um fluxo tipado pelo qual o diagrama BPMN é gerado; o cliente simula,
publica no motor (Camunda 8) e, para mudar depois, ajusta a publicada num rascunho novo (briefing.md §5).

## 2. Contrato de Entrada e Saída
- `GET /biblioteca` → `Biblioteca {itens[ModeloProcesso {id, area: financeiro|juridico|administrativo|vendas, titulo, resumo, gatilho, roda_sozinho, handoff, integracoes[]}]}`: os modelos que a Cogniventure executa (briefing.md §10), iguais para toda organização.
- `POST /descoberta {}` → em pedaços: `PassoAgente {ferramenta, texto, status: running|done|failed}`; resultado `Descoberta {texto, processos[Processo]}`. Dono e admin.
- `POST /descrever {texto: 10..3000}` → `Processo`: o agente organiza a descrição do cliente (título, área, descrição) e liga a um modelo da biblioteca quando houver um parecido. Dono e admin.
- `GET /processos?page&size&sort&q&status&area` → `ProcessoPage` de `Processo {id, modelo, area, titulo, descricao, motivo, origem: sugestao|cliente, status: sugerido|aceito|recusado, prioridade: alta|media|baixa, publicada, created_at, updated_at}` (`publicada`: número da versão que roda).
- `POST /processos/aceitar {id}` e `POST /processos/recusar {id}` → `Processo`. Dono e admin.
- `GET /resumo` → `Resumo {sugeridos, aceitos, recusados, publicados}` (workspace).
- `GET /catalogo` → `CatalogoAcoes {itens[CatalogAction {name, service, title, description, risk, connections, output_fields, example, input_schema, output_schema}]}`: as ações que os pacotes declararam (README §5.20).
- `POST /desenho/abrir {processo}` → `Desenho {processo, versao: Versao {id, numero, status: rascunho|revisao|publicada|arquivada, fluxo, alteracoes, pode_desfazer, motor {processo, chave, versao}, publicada_em}, versoes[{numero, status, motor_versao, publicada_em}], bpmn, problemas[{nivel: erro|aviso, passo, texto}], mensagens[{papel: cliente|agente, texto, passos[]}], exige_revisao}`. A versão mostrada é o rascunho; sem ele, a publicada. Na primeira vez (dono e admin) nasce o rascunho 1 a partir do fluxo de partida do modelo.
- `POST /desenho/mensagem {processo, texto: 1..4000}` → em pedaços `PassoAgente`; resultado `Desenho`. Dono e admin.
- `POST /desenho/simular {processo, valores{<passo>.<campo>: valor}, excecoes[], recusas[]}` → `Simulacao {caminho[ids do BPMN], passos[{id, nome, tipo, nota}], fim, problemas[]}`. Todo membro.
- `POST /desenho/desfazer`, `/desenho/publicar`, `/desenho/ajustar` e `/desenho/descartar {processo}` → `Desenho`. Dono e admin.
- Ao vivo: `processos.processos {id, action: sugerido|aceito|recusado|descrito}` e `processos.desenho {processo, action: alterado|mensagem|publicado|ajustado|descartado}`.
- Consome `events.processos.catalogo` (`ActionCatalog {service, actions[]}`), publicado pelos pacotes no boot.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `processos_processos` (com busca em título e descrição), `processos_versoes` (processo, número único por processo, status, fluxo, até 20 fluxos anteriores para desfazer, alterações, motor) e `processos_mensagens` (conversa de desenho, as 20 últimas no contexto). Compartilhada: `processos_acoes` (o catálogo, um registro por ação, trocado inteiro a cada declaração do serviço).
2. Descoberta: pede ao svc-conhecimento o perfil e os tópicos (`rpc.conhecimento.contexto`), roda o agente de descoberta (`llm.run_agent`, modelo `PROCESSOS_MODEL`, padrão `cv/agente`) com o perfil, a biblioteca e os processos que a organização já tem no contexto e as ferramentas `buscar_conhecimento` (`rpc.conhecimento.busca`) e `sugerir_processo`. Sugerir de novo um modelo já sugerido atualiza o motivo; aceito ou recusado fica como está.
3. Descrição: o agente estrutura o texto pela ferramenta `registrar_processo`; o processo nasce aceito, com origem cliente.
4. Desenho: o agente de desenho (modelo `PROCESSOS_DESENHO_MODEL`, padrão `cv/desenho`; sem ele cadastrado no svc-ai, usa `PROCESSOS_MODEL`) recebe o processo, o perfil, o catálogo, o fluxo atual, os problemas e a conversa, e só mexe no rascunho pelas operações `adicionar_passo`, `alterar_passo`, `remover_passo`, `ligar`, `desligar`, `definir_gatilho`, `definir_parametro` e `simular`; cada uma grava o fluxo, avisa ao vivo e devolve os problemas. Se a resposta afirma uma mudança sem nenhuma operação aplicada, ou se ficaram erros novos, o agente roda de novo uma vez com o que faltou; se ainda faltar, a resposta diz que não conseguiu ou o que ficou por resolver.
5. Simulação: percorre o fluxo da versão aberta no próprio serviço (sem motor), com o exemplo de saída de cada ação, o exemplo de cada agente e os valores do cenário; tarefas aprovam salvo as recusadas; passos em `excecoes` vão à tarefa do staff.
6. Publicar: sem erros, gera o BPMN (`to_bpmn`, id `p_<organização>_<processo>`, parâmetros na saída do início), implanta no Camunda (`camunda.deploy`), arquiva a publicada anterior, grava a versão do motor e conta o limite `ativos` (conferido na primeira publicação do processo). Ajustar copia a publicada num rascunho novo; descartar apaga o rascunho e volta para a publicada. Sem Temporal neste serviço (tudo síncrono).

## 4. Casos de Borda e Erros Mapeados
- Membro tentando escrever → 403 `ERRO_PROCESSOS_FORBIDDEN`. Processo de outra organização ou inexistente → 404 `ERRO_PROCESSOS_NAO_ENCONTRADO`.
- Briefing sem nenhum tópico feito → 409 `ERRO_PROCESSOS_SEM_BRIEFING`. svc-conhecimento fora do ar → 503 `ERRO_PROCESSOS_SEM_CONHECIMENTO`; módulo de conhecimento fora do plano → o 402 `ERRO_PLAN_MODULE` dele.
- Modelo fora da biblioteca na ferramenta → erro devolvido ao agente, que corrige. Descrição que o agente não conseguiu organizar → 422 `ERRO_PROCESSOS_DESCRICAO`.
- Desenhar processo não aceito → 409 `ERRO_PROCESSOS_NAO_ACEITO`. Simular antes de abrir → 409 `ERRO_PROCESSOS_SEM_DESENHO`. Mensagem, desfazer, publicar ou descartar sem rascunho → 409 `ERRO_PROCESSOS_SEM_RASCUNHO`. Nada a desfazer → 409 `ERRO_PROCESSOS_NADA_A_DESFAZER`.
- Publicar com erro no fluxo → 409 `ERRO_PROCESSOS_FLUXO_INVALIDO` (os três primeiros na mensagem); rascunho igual à publicada → 409 `ERRO_PROCESSOS_SEM_MUDANCA` (o motor devolveria a mesma versão). Ajustar sem publicada, ou descartar o primeiro rascunho → 409 `ERRO_PROCESSOS_SEM_PUBLICADA`. Ajustar com rascunho aberto devolve o rascunho.
- Motor recusou o BPMN → 422 `ERRO_PROCESSOS_BPMN`; motor fora do ar → 503 `ERRO_PROCESSOS_MOTOR`. Limite de processos ativos → o 402 `ERRO_PLAN_LIMIT`.
- Operação inválida do agente (passo ou ligação inexistente, condição fora de decisão, segundo caminho de um passo comum, argumentos fora do modelo) → erro devolvido ao agente, que corrige; o rascunho não muda.
- Modelo indisponível, provedor recusando ou plano de IA esgotado → os erros de `core/llm.py`.
