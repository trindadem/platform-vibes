# Briefing: Cogniventure BPO

A camada de negócios da Cogniventure: o que vendemos, quem usa, como um processo do cliente nasce, roda e melhora, e
em que ordem construímos. O `README.md` continua sendo a regra de **como** o código é escrito; este documento diz **o
quê** e **por quê**. Decisões ainda abertas estão na seção 14. Exemplos de processos estão na seção 10.

## Glossário

| Termo | Significado |
|---|---|
| Processo | Trabalho contínuo do cliente que a Cogniventure executa (ex.: contas a pagar). Tem gatilho, passos e exceções. |
| Versão | Um desenho do processo. Rascunho, em revisão, publicada ou arquivada. Só a publicada roda. |
| Execução | Uma rodada do processo (ex.: um boleto recebido). Termina na versão em que começou. |
| Passo | Uma etapa do desenho: ação, agente, tarefa humana, decisão, espera, paralelo ou subprocesso. |
| Ação | Algo que um módulo nosso sabe fazer (ex.: `financeiro.agendar_pagamento`). Tem entrada, saída e risco declarados. |
| Agente | Um modelo de IA com instrução, ferramentas, conhecimento e política. Faz o passo que pede julgamento. |
| Handoff | A exceção: o passo vai para uma pessoa (staff ou cliente) porque o agente não pode ou não deve decidir. |
| Carteira | Os clientes que um membro do staff acompanha. |
| Autonomia | Execuções concluídas sem handoff ÷ execuções concluídas. A métrica-norte de cada processo. |

## 1. O negócio

- O cliente assina um **plano mensal de BPO**. O plano inclui uma quantidade de **processos contínuos**, executados na
  maior parte por agentes e automações.
- O humano entra na **exceção** (handoff). O objetivo é que a exceção seja cada vez mais rara, e isso é medido: a
  autonomia de cada processo aparece para o cliente e para o staff.
- O cliente compra **resultado de processo** (contas pagas no prazo, banco conciliado, lead respondido em minutos),
  não software. A plataforma é como entregamos.
- Todo handoff resolvido ensina o processo: a solução do staff vira exemplo ou regra do agente daquele passo
  (seção 5.7). É assim que a autonomia sobe.

## 2. Quem usa

| Quem | Onde | O que faz |
|---|---|---|
| Cliente: dono e admin | Organização do cliente | Faz o briefing, cuida do conhecimento, desenha e ajusta processos, aprova o que o processo pede, acompanha. |
| Cliente: membro | Organização do cliente | Acompanha e responde às tarefas que o processo manda para ele. |
| Staff Cogniventure | Organização Cogniventure + clientes da carteira | Resolve handoffs, revisa versões, ajuda no setup, acompanha a saúde da carteira. |
| Time de plataforma | Console Electron (seção 11) | Opera o cluster, os clientes, o financeiro e cria módulos com o agente de código. |

## 3. A jornada do cliente

1. **Briefing.** O cliente conta o negócio (segmento, porte, sistemas que usa, banco, contador, canais de venda),
   envia documentos e informa o site. É uma conversa guiada, não um formulário longo.
2. **Conhecimento.** Tudo do briefing vira o conhecimento da empresa (RAG): o site lido, os documentos, as respostas.
   O cliente vê, corrige, apaga e acrescenta a qualquer momento, e o conhecimento continua sendo alimentado (novos
   documentos, caixa de entrada ligada, resoluções de handoff).
3. **Descoberta de processos.** Um agente lê o conhecimento e sugere processos da biblioteca (seção 10) que fazem
   sentido para aquele negócio ("vocês recebem NF por e-mail e pagam por boleto: contas a pagar?"). O cliente também
   descreve processos próprios.
4. **Desenho.** Cada processo escolhido é desenhado numa conversa com o agente de processos, com o diagrama mudando ao
   vivo ao lado (seção 5). O agente pergunta o que falta: qual banco, quem aprova, acima de que valor.
5. **Publicação.** O rascunho é simulado, opcionalmente revisado pelo staff e publicado. Daí em diante roda sozinho.
6. **Operação.** As execuções acontecem; o que precisa do cliente (uma aprovação) chega para ele; o que é exceção vai
   para o staff.
7. **Workspace.** O cliente acompanha seus processos como projetos: o que está rodando, o que espera por ele, o
   que atrasou, a autonomia de cada um, e a cadeia quando um processo dispara outro.
8. **Setup.** A qualquer momento o cliente ajusta um processo. Ajustar cria uma versão nova (as execuções em andamento
   terminam na versão delas). De preferência com ajuda humana: o cliente pode chamar o staff para a conversa.

## 4. As áreas

Cada área é uma tela (`frontend/src/modules/<area>`) e um módulo do plano (README §5.17). Áreas são servidas por
poucos serviços de plataforma do negócio; o trabalho de cada área de BPO fica em pacotes de ações.

| Área (tela) | Serviço | O que tem |
|---|---|---|
| Briefing (`/briefing`) | `svc-conhecimento` | Perfil da empresa, conversa guiada, site e documentos de entrada. |
| Conhecimento (`/conhecimento`) | `svc-conhecimento` | Itens do conhecimento com fonte, busca, correção e remoção; fontes ligadas (site, caixa de entrada). |
| Processos (`/processos`) | `svc-processos` | Sugestões, processos da organização, desenho com o agente, versões, simulação, publicação. |
| Setup (`/processos/setup`) | `svc-processos` | Pedidos de ajuste, conversa sobre um rascunho, chamar o staff. |
| Workspace (`/workspace`) | Todos (a tela compõe) | A casa do cliente: a jornada e o passo atual, processos, execuções, tarefas do cliente, prazos, indicadores, cadeia entre processos. |
| Agentes (`/agentes`) | `svc-agentes` | Agentes da organização: instrução, modelo, ferramentas, conhecimento, política, avaliação. |
| Integrações (`/integracoes`) | `svc-integracoes` | Conexões da organização (banco, e-mail, WhatsApp, ERP, servidores MCP) e o catálogo de ações. |
| Staff (`/staff`) | `svc-staff` | Carteira, fila de handoffs da carteira, revisões pendentes, saúde dos clientes. |

**Pacotes de ações** são os módulos que o plano liga por área de BPO: `svc-financeiro`, `svc-juridico`,
`svc-administrativo` e `svc-vendas`. Cada um declara ações (o que os passos chamam), seus cadastros (ex.: leads no
`svc-vendas`) e os modelos de processo da área. O plano do cliente liga os pacotes que ele contratou.

## 5. Processos com Camunda 8

### 5.1 O que é do Camunda e o que é nosso

O motor de processos é o **Camunda 8** (orquestração em BPMN; versão 8.10 hoje). Não criamos formato próprio de
execução e não exportamos BPMN: o processo publicado **é** um BPMN implantado no Camunda.

| Camunda 8 faz | Nós fazemos |
|---|---|
| Executa o BPMN: passos, decisões, paralelos, temporizadores, mensagens. | O modelo do processo que o agente edita, e a compilação dele para BPMN. |
| Versões: implantar de novo cria a versão seguinte; execução em andamento termina na versão em que começou. | Rascunho e revisão antes da implantação; quem publicou e por quê. |
| Tarefas humanas, tentativas de job, incidentes, multi-tenancy. | As ações (workers), as credenciais, o catálogo, o plano, as telas. |

- **Telas são nossas.** Cliente e staff não usam Operate, Tasklist nem Web Modeler: tudo passa pelas nossas telas,
  pela API REST do Orchestration Cluster. O Operate fica para o time interno depurar.
- **Organização = tenant do Camunda.** Cada processo é implantado e iniciado com o tenant da organização. O worker lê
  o tenant do job e age como aquela organização (mesmo isolamento do README §5.9).
- **Camunda e Temporal têm papéis diferentes.** Camunda é o processo do cliente: o que aparece no diagrama, tem
  versão e tem tarefa humana. Temporal continua sendo a durabilidade interna de um serviço (convite, ingestão de
  documento, entrega de webhook). Uma ação pode usar Temporal por dentro; o diagrama não vê isso.
- **Variável de processo leva id e decisão, não documento nem dado pessoal.** O Camunda guarda variáveis em claro no
  estado e no armazenamento secundário. O documento, o CPF e o extrato ficam no nosso serviço (SurrealDB e
  armazenamento, isolados por organização); a variável leva `documento_id`, `valor`, `aprovado`.
- **Python:** os workers usam o SDK oficial (`camunda-orchestration-sdk`, assíncrono, API REST do 8.8+).
- **Local:** Camunda no `compose.yaml` com armazenamento secundário em banco relacional (sem Elasticsearch).

### 5.2 Licença: decisão antes de produção

Desde a 8.6, o Camunda 8 Self-Managed está sob a **Camunda License 1.0**: uso livre em desenvolvimento e teste,
**produção exige licença Enterprise** (paga; preço sob consulta). As versões 8.0 a 8.5 tinham licença comunitária que
permitia produção (menos oferecer o motor como serviço), mas estão fora de suporte. Como a plataforma roda no nosso
cluster, o primeiro cliente em produção depende de uma destas escolhas (seção 14, decisão 1):

1. **Comprar a licença Enterprise** do Camunda 8 Self-Managed (o desenho deste documento fica como está).
2. **Trocar de motor** antes de produção por um BPMN de licença Apache 2.0 (ex.: Operaton, continuação do Camunda 7).
   O custo da troca fica contido: o Camunda só é tocado pelo `svc-processos` (compilação, implantação, consulta) e
   pelo `core/processes.py` (workers); o modelo do processo, as telas e as ações não mudam. Muda a compilação (as
   extensões do BPMN são outras) e a API do motor.

Desenvolvemos no Camunda 8 de qualquer forma; a decisão precisa estar tomada antes do primeiro cliente em produção.

### 5.3 O modelo do processo

O agente não escreve BPMN nem XML. Ele edita um **modelo tipado** (JSON validado por Pydantic no `svc-processos`), e
só o modelo publicado vira BPMN. É a lição do banco de provas: modelo barato acerta muito mais preenchendo dado
estruturado do que escrevendo código.

| Passo do modelo | Vira no BPMN (Camunda 8) |
|---|---|
| Gatilho: agenda, evento, manual, outro processo | Evento de início: temporizador, mensagem, simples, ou chamado por outro processo |
| Ação | Service task com `zeebe:taskDefinition type="<pacote>.<acao>"` |
| Agente | Service task `agentes.executar`, com o agente e o objetivo do passo |
| Tarefa humana (cliente ou staff) | User task com grupo candidato `cliente` ou `staff` e prazo |
| Decisão | Gateway exclusivo; condições estruturadas (campo, operador, valor) compiladas para FEEL; caminho padrão obrigatório |
| Espera | Evento intermediário: temporizador, ou mensagem com chave de correlação |
| Paralelo | Gateway paralelo que abre e fecha |
| Subprocesso | Call activity para outro processo publicado da organização |
| Exceção | Evento de erro de fronteira `handoff` no passo → tarefa humana do staff |

A saída de cada passo fica sob o id dele (`ler_documento.valor`). Como toda ação e todo agente declaram a saída, o
validador sabe que campos existem e recusa condição que aponta para campo inexistente.

### 5.4 O diálogo que desenha o processo

- **Tela dividida, como no Lovable:** a conversa com o agente de processos de um lado, o diagrama do outro
  (renderizado com bpmn-js a partir do BPMN compilado do rascunho).
- **O agente edita por operações tipadas**, que são as ferramentas dele:
  `adicionar_passo`, `ligar`, `remover_passo`, `renomear`, `definir_gatilho`, `definir_condicao`,
  `definir_excecao`, `definir_parametro`, `simular`.
- **Cada operação é conferida na hora** e o diagrama muda. Recusa, com o motivo para o agente corrigir:
  - passo sem saída ou caminho que não chega ao fim;
  - decisão sem caminho padrão;
  - ação de pacote fora do plano da organização, ou que exige integração não conectada;
  - passo de agente sem exceção (todo agente tem um caminho de handoff);
  - ação irreversível (pagar, enviar, assinar) sem aprovação antes, quando a política da organização pede.
- **O agente sabe do que está falando:** consulta o conhecimento da empresa, o catálogo de ações, integrações e
  agentes, e os modelos da biblioteca. Sugere passos ("seu fornecedor manda NF por e-mail; ligo a caixa de entrada?").
- **Cada operação fica no histórico do rascunho** (desfazer, e saber quem mudou o quê: cliente, staff ou agente).
- **Simular antes de publicar:** o rascunho é implantado num tenant de simulação da organização, com as ações em modo
  de simulação (devolvem as saídas de exemplo do catálogo, nada sai para fora). O caminho percorrido aparece no
  diagrama.

### 5.5 Versões

- **Rascunho → revisão pelo staff (opcional) → publicada.** A revisão é obrigatória quando a versão traz ação
  irreversível nova ou integração nova, ou quando o cliente pede.
- **Publicar implanta no Camunda** e grava o número da versão do Camunda na nossa versão.
- **Ajustar no setup cria um rascunho novo** a partir da publicada. As execuções em andamento terminam na versão em
  que começaram (comportamento nativo do Camunda); as novas usam a última publicada.
- **Voltar atrás** é publicar de novo uma versão antiga (vira a versão seguinte). Migrar execuções em andamento para
  a versão nova fica para depois (o Camunda suporta).

### 5.6 Execução: ações

- **Ação = função de um pacote** declarada com entrada, saída e risco (`leitura`, `escrita`, `externa`,
  `irreversivel`), auto-registrada como worker do tipo `<pacote>.<acao>` (proposta: `core/processes.py`, no mesmo
  espírito do `@activities` do README §5.2).
- O worker age como a organização do job, confere o plano antes (módulo desligado vira handoff, não falha muda),
  registra trace e métricas (README §5.18) e devolve só o que a saída declara.
- Integração com terceiros é sempre uma ação nossa, com a credencial guardada no `svc-integracoes` (como as chaves de
  IA no `svc-ai`) e chamada pelo `core/http_client.py` com a proteção de SSRF. O BPMN só leva o id da conexão. Na v1
  não usamos o runtime de Connectors do Camunda: credencial e isolamento por organização ficam nos nossos trilhos.

### 5.7 Execução: agentes e handoff

- **Passo de agente** roda um agente da organização (seção 7) com o objetivo do passo, as ferramentas permitidas
  naquele passo (um subconjunto, nunca o catálogo todo), o conhecimento da empresa e a saída declarada.
- **O agente pode se abster.** Pouca confiança, documento ilegível, pedido fora da política: em vez de chutar, o passo
  lança o erro `handoff`, e o BPMN leva a uma tarefa humana do staff com o contexto (o que o agente viu, o que tentou,
  por que parou).
- **Ação irreversível que a política manda perguntar** também vira tarefa humana (de aprovação do cliente ou do
  staff), não uma decisão do agente.
- **Handoff tem prazo.** Não assumido dentro do prazo, sobe para o responsável pela carteira.
- **Aprender com o handoff.** Ao resolver, o staff registra o que fez e por quê, e pode marcar "virar regra". A regra
  ou o exemplo entra na especialização do agente daquele passo, depois de passar na avaliação dele (seção 7).
- **Autonomia por processo** = execuções sem handoff ÷ execuções concluídas, por versão. Aparece no workspace do
  cliente e na carteira do staff; é como sabemos se uma versão nova melhorou o processo.

### 5.8 Gatilhos

- **Agenda:** "todo dia às 8h", "dia 1 de cada mês" (temporizador do Camunda).
- **Evento:** documento chegou na caixa de entrada ou no WhatsApp, webhook de um sistema do cliente, pagamento
  confirmado pelo banco. O serviço que recebe publica a mensagem no Camunda com a chave de correlação.
- **Manual:** o cliente ou o staff inicia pela tela.
- **Outro processo:** uma proposta aceita em Vendas inicia a gestão de contratos no Jurídico e o faturamento no
  Financeiro. O workspace mostra a cadeia como um projeto.

## 6. Conhecimento

- **Fontes:** site lido no briefing, documentos enviados, respostas do briefing, caixa de entrada ligada, resoluções
  de handoff. Cada item guarda a fonte e a data.
- **CRUD pelo cliente:** ver, corrigir, apagar, acrescentar. Apagar remove do índice na hora.
- **Busca híbrida** no SurrealDB, por organização: texto (BM25) e vetores, com fusão e reordenação. As peças de
  segmentação, fusão e reordenação vêm do AgentExo (`exovision.harness.rag`); o armazenamento é o nosso.
- **Toda resposta cita a fonte.** Nenhum agente vê conhecimento de outra organização.
- **Conhecimento vencido:** item com data de validade (tabela de preços, contrato) avisa antes de vencer.

## 7. Agentes

### 7.1 A área de agentes

- **Um agente** tem instrução, modelo (cadastrado no `svc-ai`), ferramentas, escopo de conhecimento, política (o que
  pede aprovação) e uma suíte de avaliação (casos com a resposta esperada).
- **Ferramentas vêm do catálogo:** ações dos pacotes, integrações conectadas, servidores MCP cadastrados (gateways) e
  plugins nossos.
- **Agentes nossos** já vêm prontos e mantidos pela Cogniventure: agente de processos (o desenhista da seção 5.4),
  de documentos (extração), de atendimento (vendas no WhatsApp), de cobrança, de contratos.
- **Agentes do cliente** nascem como rascunho; viram verificados quando a suíte passa; confiáveis só por decisão do
  staff. Ferramenta nova criada pelo cliente segue o mesmo caminho.

### 7.2 Motor: AgentExo no lugar do Agno (recomendação)

Hoje todo agente da plataforma passa pelo `core/llm.py`, que usa o Agno por baixo. A recomendação é adotar o
**AgentExo** (`exovision-agent`, o SDK agêntico da casa) para os agentes, mantendo a interface do `core/llm.py`.

**Por que:**
- É nosso e Apache 2.0, sem dependência de runtime: corrigir ou estender é commit nosso.
- Já tem o que o negócio pede: política por risco (`Ask` vira handoff), plugins com níveis de confiança
  (rascunho → verificado → confiável), cliente MCP completo com proteção contra troca maliciosa de ferramenta,
  especialização por diretório com regras e exemplos aprendidos (o "aprender com o handoff" da seção 5.7), sessão
  durável que retoma depois de uma queda, livro-razão de custo.
- Fala com qualquer API compatível com a da OpenAI, que é o que o `svc-ai` resolve.

**Como entra na plataforma** (adaptadores no `core/llm.py`, nenhum serviço muda):

| Peça do AgentExo | Na plataforma |
|---|---|
| `OpenAICompatibleProvider` | Endereço e chave que o `svc-ai` resolve por organização; a chave não sai do processo. Uso em `events.ai.usage`. |
| `Toolset` | Ações do catálogo viram ferramentas; a chamada vai por RPC ao pacote, como a organização. |
| `Policy` | Risco da ação decide; `Ask` cria tarefa humana em vez de perguntar no terminal. |
| `MemoryPort` e RAG | Sobre o `svc-conhecimento` (SurrealDB por organização). O SQLite do SDK não é usado na plataforma. |
| `StateStore` | Journal da sessão no SurrealDB, para retomar. |
| Seams (eventos) | Trace e métricas (README §5.18) e passos do agente ao vivo na tela. |
| Tarefas e barramento do SDK | Não usados na plataforma: lá são Camunda, Temporal e NATS. |

**Cuidados:**
- O SDK é síncrono: roda em thread (`asyncio.to_thread`) dentro do worker.
- Não tem streaming de texto: no diálogo de processos a tela mostra as operações aplicadas (o diagrama muda). Se o
  texto em pedaços fizer falta, acrescentamos ao SDK.
- Está em alfa: versão fixada (wheel em `vendor/`).

**Spike do N1: passou.** O agente de briefing roda no AgentExo pelo `llm.run_agent` (README §5.11), contra o Qwen3
Next 80B no Bedrock pela API compatível: cinco mensagens de um cliente preencheram os seis tópicos do perfil, com
plano conferido e uso registrado a cada volta, e erro de ferramenta voltando ao modelo para ele corrigir. Falta tirar
o Agno de `ask`, `stream` e `agent` (passam ao cliente OpenAI direto, que o `core/llm.py` já usa, e ao `run_agent`).

No console Electron (seção 11) o AgentExo encaixa como está: local, um usuário, SQLite.

## 8. Staff e carteira

- **O staff pertence à organização Cogniventure.** A carteira é a lista de organizações clientes de cada pessoa do
  staff, mantida pelo `svc-staff`.
- **Entrar na carteira dá o papel `operador` na organização do cliente**; sair tira. O staff age dentro do cliente
  com o nome dele (o cliente vê quem fez o quê) e sem nenhum poder entre organizações além do papel. Reusa o
  isolamento que já existe (README §5.7 e §5.9).
- **A área do staff junta a carteira:** fila de handoffs de todos os clientes dela, ordenada pelo prazo; revisões de
  versão pendentes; pedidos de ajuda do setup; saúde de cada cliente (autonomia, atrasos, consumo do plano).
- **Ajuda no setup:** o staff entra na conversa de desenho do cliente, propõe operações e revisa o rascunho.
- **Gestor da carteira** recebe o que passou do prazo e redistribui.

## 9. O plano do BPO

O plano usa o que já existe em módulos, planos e limites (README §5.17):

| Item do plano | Como é conferido |
|---|---|
| Áreas contratadas | Módulos: os pacotes de ações (`financeiro`, `juridico`, `administrativo`, `vendas`) ligados pelo plano |
| Processos contínuos | Limite `processos.ativos` (processos com versão publicada), conferido ao publicar |
| Volume | Limite `processos.execucoes` por mês, conferido no gatilho |
| IA | Limites `ai.custo` e `ai.tokens` que já existem |
| Atendimento humano | Indicador de handoffs por mês (cobrança e limite: decisão 3 da seção 14) |

- **Execução em andamento nunca para no meio** por limite; o limite vale para execuções novas.
- O que acontece com execução nova acima do volume (bloquear ou cobrar excedente) é decisão comercial (seção 14).

## 10. Biblioteca de processos

Cada processo abaixo vira um **modelo** na biblioteca: gatilho, passos, integrações exigidas, parâmetros (ex.: valor
que pede aprovação), exceções e indicadores. A descoberta (seção 3) sugere modelos; o desenho adapta o modelo ao
cliente.

### Financeiro e contábil

| Processo | Gatilho | Roda sozinho | Handoff (exceção) |
|---|---|---|---|
| Contas a pagar | Boleto ou NF chega por e-mail ou WhatsApp | Agente extrai fornecedor, valor, vencimento e linha digitável; confere com o pedido ou contrato; classifica no plano de contas; agenda o pagamento no banco; concilia o comprovante | Valor diferente do pedido, fornecedor novo, documento ilegível; aprovação do cliente acima de um valor |
| Conciliação bancária | Todo dia | Puxa extratos (Open Finance ou OFX), casa com os lançamentos e classifica pelas regras aprendidas | Lançamento sem par acima da tolerância |
| Faturamento e cobrança | Pedido entregue ou contrato do mês | Emite a NFS-e, envia boleto ou Pix e roda a régua (D-3, D+1, D+7 no WhatsApp); negocia dentro dos limites do briefing | Inadimplente além de N dias ou desconto fora do limite |
| Fechamento do mês | Dia 1 | Cobra do cliente os documentos que faltam, envia ao escritório contábil, gera e paga o DAS e monta a DRE gerencial com um resumo | Documento que não chega ou divergência no imposto |

### Jurídico

| Processo | Gatilho | Roda sozinho | Handoff (exceção) |
|---|---|---|---|
| Gestão de contratos | Contrato recebido | Agente extrai partes, valores, vigência, multa, reajuste e renovação; compara com o padrão da empresa (do conhecimento); arquiva e avisa 60 e 30 dias antes de vencer ou reajustar | Cláusula de risco alto: o advogado revisa |
| Publicações e processos | Todo dia | Consulta tribunais e diários pelo CNPJ, resume cada intimação e calcula o prazo | Toda intimação vira tarefa com prazo para o advogado (handoff obrigatório) |
| Certidões negativas | Todo mês | Emite as certidões (Receita/PGFN, FGTS, trabalhista, estadual, municipal), guarda e avisa o vencimento | Certidão positiva ou irregularidade |

### Administrativo

| Processo | Gatilho | Roda sozinho | Handoff (exceção) |
|---|---|---|---|
| Admissão de colaborador | Contratação aprovada | Coleta documentos por formulário ou WhatsApp, valida, envia à folha e ao eSocial, manda o contrato para assinatura eletrônica, agenda o exame e cria acessos | Documento inválido ou pendência no eSocial |
| Compras e cotação | Requisição interna | Pede 3 cotações, compara e, aprovado pelo cliente, emite o pedido e acompanha a entrega; a NF entra no contas a pagar | Fornecedor sem resposta ou item fora do catálogo |
| Vencimentos da empresa | Todo dia | Alvarás, licenças, AVCB, seguros e contratos de serviço: avisa e inicia a renovação | Renovação que exige presença ou vistoria |

### Vendas

| Processo | Gatilho | Roda sozinho | Handoff (exceção) |
|---|---|---|---|
| Qualificação de leads | Lead no site, Instagram ou WhatsApp | Agente responde em minutos, qualifica pelo perfil de cliente ideal do briefing, agenda a reunião com o vendedor e registra no CRM; lead frio vai para nutrição | Cliente pede humano ou pedido fora do padrão |
| Proposta comercial | Pedido de proposta | Monta com a tabela e as condições do conhecimento, envia e faz os follow-ups | Desconto acima do limite: aprovação do cliente |
| Reativação de carteira | Cliente sem comprar há 90 dias | Campanha personalizada; as respostas viram oportunidades no CRM | Resposta com reclamação |

### Um modelo por inteiro: contas a pagar (piloto proposto)

```text
Contas a pagar · financeiro · gatilho: mensagem documento.recebido (caixa de entrada ou WhatsApp do cliente)
parâmetros: limite_aprovacao = R$ 5.000

 1. ler_documento     agente         extrai fornecedor, CNPJ, valor, vencimento, linha digitável
                                     exceção: ilegível ou pouca confiança → handoff staff
 2. conferir          ação           financeiro.conferir_pedido (pedido ou contrato do conhecimento)
 3. divergente?       decisão        conferir.divergente = sim → 4 · padrão → 5
 4. revisar           tarefa staff   resolve a divergência (corrige o valor ou recusa) → 5 ou fim "recusado"
 5. aprovar?          decisão        valor > limite_aprovacao ou fornecedor novo → 6 · padrão → 7
 6. aprovar           tarefa cliente prazo 1 dia útil; recusado → fim "recusado"
 7. classificar       ação           financeiro.classificar (plano de contas, regras aprendidas)
 8. agendar           ação           banco.agendar_pagamento (irreversível; conexão do banco do cliente)
 9. aguardar          espera         mensagem banco.pago com a chave do pagamento; até vencimento + 1 dia → handoff staff
10. conciliar         ação           financeiro.conciliar
    fim "pago"

indicadores: autonomia; tempo do recebimento ao agendamento; pagos em atraso
```

É o piloto proposto porque passa por tudo: gatilho por evento, agente com exceção, regra do cliente, aprovação do
cliente, integração irreversível, espera por mensagem e handoff do staff.

## 11. Console Electron (operação)

Um aplicativo só do time, na pasta `console/` deste repositório (tudo num lugar só): Electron + Vite + React +
TypeScript, com SQLite local. Não vai para cliente.

- **Cluster:** nós, pods, uso, alertas, pela API do Kubernetes e pelas métricas que a plataforma já exporta.
- **Clientes:** organização ↔ namespace, plano, módulos, instalação dedicada (o `MODULES` do README §9); criar,
  suspender e atualizar cliente.
- **Financeiro:** receita por plano contra custo de infraestrutura e de IA por cliente (dados do `svc-plans` e do
  `svc-ai`).
- **Agente de operação:** AgentExo rodando ao lado do Electron (processo filho, JSON pela entrada e saída padrão), com
  ferramentas de Kubernetes e Git. Toda ação destrutiva (apagar, escalar para zero, reverter) pede aprovação na tela.
- **IDE estilo Lovable:** conversa com o agente de código, que trabalha numa cópia (worktree) deste repositório
  pelos trilhos (`service.sh`, kit de testes, contratos). O módulo sobe num namespace de pré-visualização, a tela
  dele aparece renderizada ao lado, alguém do time aprova, e vira commit, CI e deploy. O banco de provas (`bench/`)
  mede esse agente.
- **Git:** branches, diffs e o estado do CI do que o agente fez.
- **Segurança:** kubeconfig e credenciais do Git só nas máquinas do time; o SQLite do console não guarda dado de
  cliente, só indicadores.

## 12. Cluster bare-metal

A plataforma vai rodar no nosso cluster bare-metal. Hoje a produção é `docker compose` num host (README §9). Falta
um bloco de plataforma de empacotamento para Kubernetes (proposta):

- **Nossos serviços, gateway e frontend** em manifestos gerados pelos mesmos trilhos do compose (um serviço novo do
  `service.sh` já nasce com o manifesto).
- **Dependências pelos charts oficiais:** NATS, Temporal, SurrealDB, RustFS e Camunda 8 (armazenamento secundário em
  PostgreSQL, sem Elasticsearch).
- **Namespaces:** um compartilhado (planos compartilhados), um por cliente dedicado (só os módulos dele) e os de
  pré-visualização da IDE.
- **Bare-metal:** balanceador (MetalLB), certificados (cert-manager) e armazenamento distribuído (decisão 7).

## 13. Ordem de construção

A ordem segue a jornada do cliente (seção 3). Cada bloco entrega um passo dela, usável no navegador, e alimenta o
seguinte. Nada roda sem ter passado pelos passos anteriores: o contas a pagar só executa no N4, depois de ter sido
descoberto no N2 e desenhado no N3.

- **O workspace nasce no N1 e cresce a cada bloco.** É a casa do cliente: mostra a jornada e em que passo ele está,
  e passa a mostrar os processos e as execuções conforme os blocos chegam. A tela compõe o que cada serviço publica.
- **A infraestrutura entra quando o passo precisa dela:** o AgentExo no N1 (o briefing já é uma conversa com
  agente), o Camunda no N3 (desenhar é publicar e simular), workers e integrações no N4.
- **Cada bloco termina com o critério de pronto validado na stack**, por uma pessoa no navegador.

| Bloco | O que entra | Pronto quando |
|---|---|---|
| N1 Briefing e conhecimento | Workspace com a jornada; `svc-conhecimento` (perfil da empresa, conversa guiada, site, documentos, itens com fonte, CRUD, busca); agente de briefing, que é o spike do AgentExo no `core/llm.py` | Uma organização nova faz o briefing conversando, vê e corrige o conhecimento com as fontes, e o workspace marca o passo como feito |
| N2 Descoberta de processos | `svc-processos` nasce com a biblioteca (os 13 modelos da seção 10, como dados) e os processos da organização; agente que sugere a partir do conhecimento, com o porquê; processo descrito pelo cliente | Depois do briefing de uma empresa de exemplo, o workspace mostra os processos sugeridos com o motivo, e o cliente aceita, recusa ou descreve um novo |
| N3 Desenho e versões | Modelo tipado, operações e validação (seção 5.3 e 5.4); tela dividida com o diagrama; Camunda 8 no compose; compilação para BPMN; simulação; versões rascunho → revisão → publicada; o `svc-financeiro` nasce declarando as ações do contas a pagar (entrada, saída, risco e exemplo de saída para a simulação) | O contas a pagar aceito no N2 é adaptado só pela conversa, simulado com o caminho no diagrama e publicado no Camunda; ajustar a versão publicada abre um rascunho novo |
| N4 Execução e acompanhamento | `core/processes.py` (workers); as ações do contas a pagar implementadas; `svc-integracoes` com as conexões que o piloto pede (caixa de entrada; banco simulado até o fornecedor ser escolhido); gatilhos; tarefas do cliente e do staff (papel `operador`); no workspace, execuções, tarefas, prazos e autonomia | Um boleto que chega na caixa de entrada percorre o processo publicado, o cliente aprova no workspace, uma exceção vira handoff resolvido por um operador, e publicar uma versão nova não muda a execução em andamento |
| N5 Staff, carteira e setup | `svc-staff`; carteira com o papel `operador` automático; fila de handoffs da carteira com prazo e escalonamento; revisão de versões; setup com ajuda humana (o staff entra na conversa de desenho); aprender com o handoff | Um ajuste pedido no setup é feito pelo staff junto com o cliente e publicado; um handoff resolvido vira regra e a execução seguinte passa sem handoff |
| N6 Agentes e integrações | Área de agentes (instrução, ferramentas do catálogo, MCP, política, suíte); integrações completas (catálogo, credenciais, servidores MCP) | O cliente cria um agente com uma ferramenta MCP, ele passa na suíte e é usado num passo de processo |
| N7 Pacotes de área | Jurídico, administrativo, vendas e o resto do financeiro: ações e modelos; processos que disparam outros | Os 13 modelos simulam, e a cadeia proposta → contrato → faturamento aparece no workspace como um projeto |
| P1 Cluster | Empacotamento Kubernetes (seção 12) | A plataforma sobe no cluster com um cliente compartilhado e um dedicado; precisa estar pronto antes do primeiro cliente em produção, junto com a decisão 1 |
| P2 Console | `console/` (seção 11), depois do P1 | Painéis do cluster e dos clientes, e um módulo criado pela IDE chega a deploy aprovado |

- O antigo bloco 15 (APIs, MCP e medição) entra no N6 (MCP) e nos indicadores do N4. O bloco 14 (experiência) fica
  depois do N5, quando a jornada inteira existir.
- O banco de provas passa a medir tarefas do negócio, a partir do N3: ações de pacote e "dada a descrição do
  cliente, o modelo chega ao processo esperado pelas operações tipadas?".

## 14. Decisões abertas

1. **Licença do Camunda 8 em produção** (seção 5.2): comprar a Enterprise ou trocar de motor antes do primeiro
   cliente em produção.
2. **Processo e cliente piloto:** proposta, contas a pagar (seção 10) com um cliente real.
3. **Preço e limites do plano:** quantos processos, quantas execuções, se handoff tem cota, e o que acontece acima do
   volume (bloquear ou cobrar).
4. **Staff como `operador` na organização do cliente** (seção 8): confirmar o modelo.
5. **AgentExo no lugar do Agno** (seção 7.2): o spike do N1 passou; falta decidir quando tirar o Agno de vez.
6. **Fornecedores de integração:** WhatsApp, banco (Open Finance ou API do banco), NFS-e, certidões e tribunais;
   escolhidos pelo cliente piloto.
7. **Cluster:** armazenamento distribuído e alta disponibilidade do SurrealDB.
