# Spec: agentes

## 1. Objetivo Operacional
A área de agentes da empresa (briefing.md §7.1): cada agente tem instrução, modelo (cadastrado no svc-ai), ferramentas
do catálogo (as da plataforma e as dos sistemas da empresa conectados por MCP em Integrações), a política de cada
ferramenta (usar sozinho ou pedir aprovação) e uma suíte de casos com a resposta esperada. Nasce rascunho; vira
verificado quando a suíte passa; confiável, só por decisão do staff. Só verificado ou confiável faz um passo de processo.
Módulo (schemas.MODULE): "Agentes", categoria Sua empresa, ligado por padrão; telas em /agentes e /agentes/:id.

## 2. Contrato de Entrada e Saída
- `GET /agentes` → `Agentes {itens[Agente]}`; `GET /agentes/item?id` → `Agente {id, nome, descricao, instrucao, modelo,
  ferramentas[{ref, modo: permitir|perguntar}], casos[Caso], status: rascunho|verificado|confiavel, versao, avaliando,
  avaliacao {versao, ok, resultados[{caso, ok, saida, detalhes[], ferramentas[]}], em}, confiavel_por, created_at,
  updated_at}`. Todo membro lê.
- `POST /agentes` (`NovoAgente {nome: 2..60, descricao?, instrucao: 10..4000, modelo = cv/agente, ferramentas[], casos[]}`)
  → `Agente` (rascunho, versão 1). `POST /agentes/editar` (`EdicaoAgente {id, ...}`) → `Agente`: mudar instrução,
  modelo, ferramentas ou casos sobe a versão e volta a rascunho. `POST /agentes/remover {id}` → `Agente`. Dono, admin
  e operador (o staff ajuda no setup).
- Ferramenta: `ref` = `documento` (ler o documento do gatilho), `conhecimento` (buscar no conhecimento da empresa),
  `acao:<pacote>.<ação>` (uma ação de um pacote ligado no plano) ou `mcp:<servidor>:<ferramenta>`. `GET /ferramentas` →
  `CatalogoFerramentas {itens[{ref, nome, descricao, origem: plataforma|pacote|mcp, servidor_nome, pacote, risco,
  parametros}], integracoes, processos}` (nessa ordem: plataforma, pacotes, MCP; `processos`/`integracoes` falsos quando
  o svc-processos/svc-integracoes não respondeu): só o que está no catálogo agora entra num agente. Ferramenta
  irreversível só entra com `modo: perguntar`.
- Caso: `{id, nome, tarefa, dados{}, esperado{campo: valor}}` (até 20). `POST /agentes/avaliar {id}` → `Agente` com
  `avaliando`: a suíte roda em segundo plano. `POST /agentes/confiar {id}` (só operador, sobre um verificado) → `Agente`.
- `POST /agentes/testar {id, tarefa, dados{}, saidas{campo: texto|numero|sim_nao}}` → `Execucao {saidas, fontes,
  ajuda, aprovacao, ferramentas[], lidos[], texto}`: experimenta, sem mudar o status.
- RPC `rpc.agentes.lista` (`Empty`) → `ListaAgentes {itens[{id, nome, descricao, status, ferramentas[]}]}` e RPC
  `rpc.agentes.executar` (`ExecutarAgente {agente, tarefa, contexto, saidas{campo: tipo}, leitura, regras[]}`) →
  `Execucao`: o svc-processos oferece os agentes no desenho, confere o status e roda o passo. Na organização de quem pede.
- Consome `rpc.processos.acoes` (as ações dos pacotes ligados, com o título do pacote), `rpc.<pacote>.acao`
  (`ActionCall {acao, entrada}` → `ActionResult {ok, resultado, motivo}`, core/processes.py), `rpc.integracoes.ferramentas`,
  `rpc.integracoes.mcp_chamar`, `rpc.integracoes.documento` e `rpc.conhecimento.busca`. Ao vivo: `agentes.agentes {id, action: criado|alterado|avaliando|avaliado|confiavel|removido}`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `agentes_agentes` (nome único), com os casos e a última avaliação no registro.
2. O agente roda no laço do AgentExo (`llm.run_agent`, o modelo dele): instrução dele mais as regras da plataforma
   (concluir com as saídas ou pedir ajuda; não chutar), ferramentas `concluir` (as saídas pedidas e, num passo de
   leitura, `fontes`), `pedir_ajuda` e as escolhidas. Ferramenta MCP entra como `SchemaTool` (nome
   `mcp_<servidor>_<ferramenta>`, o schema do servidor) e a chamada vai ao svc-integracoes, que guarda a credencial; o
   que ela responde entra em `lidos` (o svc-processos confere as fontes contra isso). Ação de pacote entra como
   `SchemaTool` `acao_<pacote>_<ação>` (até 60 caracteres, com o `input_schema` da ação) e a chamada vai ao próprio
   pacote (`rpc.<pacote>.acao`, 60 s) como `system:svc-agentes` na organização do agente: o pacote a roda com a mesma
   conferência de um passo. A saída entra em `lidos`; `ok: false` volta ao modelo com o motivo.
3. Política: ferramenta com `perguntar` não roda; o agente recebe "precisa de aprovação" e `aprovacao` registra o que
   ele ia fazer (num processo, vira a exceção do staff; na suíte, o caso falha). Ferramenta irreversível (de qualquer
   origem) roda sempre como `perguntar`, mesmo gravada antes da regra; o pacote também recusa a irreversível (403). Ferramenta fora do catálogo (servidor
   removido, em quarentena) some do agente.
4. Suíte: `AvaliarSuiteWorkflow` (Temporal) → activity `agentes.rodar_suite` (30 min, 2 tentativas): cada caso roda o
   agente de verdade e compara (número igual a um centavo; sim/não igual; texto sem acento, caixa e pontuação, igual
   ou contido; pedir ajuda ou aprovação reprova). Todos passam e a versão não mudou no meio → verificado (o confiável
   continua confiável). Sem terminar → `agentes.encerrar_suite` registra o motivo e tira o agente da avaliação.
5. Ciclo de vida (README §5.13): agendamentos e migrações: nenhum ainda.

## 4. Casos de Borda e Erros Mapeados
- Membro mexendo em agente → 403 `ERRO_AGENTES_FORBIDDEN`; confiar sem ser operador → 403.
- Nome repetido → 409 `ERRO_AGENTES_NOME`. Ferramenta fora do catálogo, repetida ou irreversível sem `perguntar` →
  422 `ERRO_AGENTES_FERRAMENTA`;
  dois casos com o mesmo id → 422 `ERRO_AGENTES_CASO`.
- Avaliar sem casos → 409 `ERRO_AGENTES_SEM_CASOS`. Confiar ou executar num processo um agente em rascunho → 409
  `ERRO_AGENTES_NAO_VERIFICADO`. Agente inexistente ou de outra organização → 404 `ERRO_AGENTES_NAO_ENCONTRADO`.
- svc-integracoes fora do ar: o catálogo fica sem as MCP (`integracoes: false`); a ferramenta MCP falha e o agente
  pede ajuda. svc-processos fora do ar: sem as ações dos pacotes (`processos: false`). Pacote desligado no plano: a ação
  some do catálogo e do agente; pacote fora do ar: a ferramenta responde que ele não respondeu. Modelo recusado ou plano de IA no limite → o erro do core (README §5.11).
