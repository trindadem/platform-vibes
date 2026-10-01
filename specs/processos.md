# Spec: processos

## 1. Objetivo Operacional
O segundo passo da jornada do cliente BPO (briefing.md §3): a partir do briefing e do conhecimento, um agente sugere
os processos da biblioteca da Cogniventure que fazem sentido para a empresa, dizendo o porquê, e o cliente aceita,
recusa ou descreve um processo próprio. Os aceitos seguem para o desenho (bloco N3).

## 2. Contrato de Entrada e Saída
- `GET /biblioteca` → `Biblioteca {itens[ModeloProcesso {id, area: financeiro|juridico|administrativo|vendas, titulo, resumo, gatilho, roda_sozinho, handoff, integracoes[]}]}`: os modelos que a Cogniventure executa (briefing.md §10), iguais para toda organização.
- `POST /descoberta {}` → em pedaços: `PassoAgente {ferramenta, texto, status: running|done|failed}`; resultado `Descoberta {texto, processos[Processo]}`. Dono e admin.
- `POST /descrever {texto: 10..3000}` → `Processo`: o agente organiza a descrição do cliente (título, área, descrição) e liga a um modelo da biblioteca quando houver um parecido. Dono e admin.
- `GET /processos?page&size&sort&q&status&area` → `ProcessoPage` de `Processo {id, modelo, area, titulo, descricao, motivo, origem: sugestao|cliente, status: sugerido|aceito|recusado, prioridade: alta|media|baixa, created_at, updated_at}`.
- `POST /processos/aceitar {id}` e `POST /processos/recusar {id}` → `Processo`. Dono e admin.
- `GET /resumo` → `Resumo {sugeridos, aceitos, recusados}` (workspace).
- Ao vivo: `processos.processos {id, action: sugerido|aceito|recusado|descrito}`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `processos_processos` (modelo, área, título, descrição, motivo, origem, status, prioridade), com busca em título e descrição.
2. Descoberta: pede ao svc-conhecimento o perfil e os tópicos (`rpc.conhecimento.contexto`), roda o agente de descoberta (`llm.run_agent`, modelo `PROCESSOS_MODEL`, padrão `cv/agente`) com o perfil, a biblioteca e os processos que a organização já tem no contexto e as ferramentas `buscar_conhecimento` (`rpc.conhecimento.busca`) e `sugerir_processo`. Sugerir de novo um modelo já sugerido atualiza o motivo; aceito ou recusado fica como está.
3. Descrição: o agente estrutura o texto pela ferramenta `registrar_processo`; o processo nasce aceito, com origem cliente. Sem Temporal neste bloco (tudo síncrono).

## 4. Casos de Borda e Erros Mapeados
- Membro tentando escrever → 403 `ERRO_PROCESSOS_FORBIDDEN`. Processo de outra organização ou inexistente → 404 `ERRO_PROCESSOS_NAO_ENCONTRADO`.
- Briefing sem nenhum tópico feito → 409 `ERRO_PROCESSOS_SEM_BRIEFING`. svc-conhecimento fora do ar → 503 `ERRO_PROCESSOS_SEM_CONHECIMENTO`; módulo de conhecimento fora do plano → o 402 `ERRO_PLAN_MODULE` dele.
- Modelo fora da biblioteca na ferramenta → erro devolvido ao agente, que corrige. Descrição que o agente não conseguiu organizar → 422 `ERRO_PROCESSOS_DESCRICAO`.
- Modelo indisponível, provedor recusando ou plano de IA esgotado → os erros de `core/llm.py`.
