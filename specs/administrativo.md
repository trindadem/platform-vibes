# Spec: administrativo

## 1. Objetivo Operacional
O pacote de ações administrativas do BPO (briefing.md §4 e §10): o que os processos de admissão de colaborador,
compras e cotação e vencimentos da empresa chamam. Guarda colaboradores, fornecedores de compras, requisições com as
cotações e os vencimentos (alvarás, licenças, seguros); pede documentos e cotações por e-mail e avisa o que vence. O
que depende de integração ainda não escolhida (eSocial ou folha, assinatura eletrônica; briefing.md §14, decisão 6)
vai para o staff, que faz e informa o resultado na exceção.

## 2. Contrato de Entrada e Saída
Ações (`processes.declare` e `processes.worker`), cada uma o método de mesmo nome no service.py:
- `administrativo.pedir_documentos` (externa, conexão Caixa de entrada): `Admissao {colaborador_id, colaborador, email, cargo, inicio}` → `PedidoDocumentos {enviado_em}`.
- `administrativo.enviar_esocial` (externa, conexão eSocial ou folha): `Admissao` → `Esocial {recibo}`.
- `administrativo.coletar_assinatura` (externa, conexão Assinatura eletrônica): `Admissao` → `Assinado {assinado_em}`.
- `administrativo.agendar_exame` (escrita): `Admissao` → `Exame {exame_em}`.
- `administrativo.criar_acessos` (escrita): `Admissao` → `Acessos {acessos}`.
- `administrativo.concluir_admissao` (escrita): `Admissao` → `Admitido {status}`.
- `administrativo.pedir_cotacoes` (externa, conexão Caixa de entrada): `RequisicaoIn {requisicao_id, item, quantidade, categoria}` → `PedidoCotacao {fornecedores}`.
- `administrativo.comparar_cotacoes` (leitura): `RequisicaoRef {requisicao_id}` → `Comparacao {recebidas, melhor_fornecedor, melhor_valor, prazo_dias}`.
- `administrativo.emitir_pedido` (externa, conexão Caixa de entrada): `PedidoIn {requisicao_id, melhor_fornecedor, melhor_valor}` → `PedidoCompra {pedido_numero}`.
- `administrativo.encerrar_requisicao` (escrita): `Encerramento {requisicao_id, aprovado}` → `Encerrada {status}` (a compra que a empresa não aprovou fica cancelada).
- `administrativo.verificar_vencimentos` (escrita): `Antecedencia {antecedencia_dias}` → `Vencimentos {proximos, exige_presenca, resumo}`.
Modelos: `admissao-colaborador` (evento `administrativo.admissao`; ramos em paralelo depois dos documentos),
`compras-cotacao` (evento `administrativo.requisicao`) e `vencimentos-empresa` (todo dia, 8h).
Rotas:
- Cadastros declarados (README §5.19), escrevem dono, admin e operador: `colaboradores` (`Colaborador {nome, email, cargo, salario, inicio, status: admissao|ativo|desligado, exame_em, acessos}`), `fornecedores` (`FornecedorCompra {nome, email, categoria}`) e `vencimentos` (`Vencimento {nome, tipo: alvara|licenca|avcb|seguro|contrato_servico|outro, vence_em, exige_vistoria, avisado_em}`).
- `POST /admissoes {nome, email, cargo, salario?, inicio?}` → `ColaboradorItem`: entra como colaborador em admissão e emite `administrativo.admissao` (o processo começa). Dono, admin e operador.
- `GET /requisicoes?page&size&sort&status&q` → `RequisicaoPage` de `Requisicao {id, item, quantidade, categoria, observacao, status: aberta|cotando|pedido|cancelada, cotacoes[{fornecedor, valor, prazo_dias}], melhor_fornecedor, melhor_valor, pedido_numero, created_at}`.
- `POST /requisicoes {item, quantidade, categoria?, observacao?}` → `Requisicao` e emite `administrativo.requisicao`; `POST /requisicoes/cotacao {requisicao, fornecedor, valor, prazo_dias?}` → `Requisicao` (a cotação que chegou). Dono, admin e operador.
- Ao vivo: `administrativo.colaboradores`, `administrativo.fornecedores`, `administrativo.vencimentos` e `administrativo.requisicoes {id, action}`.
- Consome `rpc.integracoes.enviar_email` (contrato repetido no schemas.py); emite `events.processos.evento` por `processes.emit`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `administrativo_colaboradores`, `administrativo_fornecedores`, `administrativo_vencimentos`
   (cadastros declarados) e `administrativo_requisicoes` (busca em item e categoria).
2. Admissão: o e-mail ao novo colaborador lista os documentos e pede a resposta para a caixa de entrada; exame
   no primeiro dia útil a partir de amanhã (9h), antes do início; acessos pelo cargo (e-mail e sistemas da empresa).
   Concluir deixa o colaborador ativo. Cada passo grava no colaborador e avisa dono e administrador.
3. Compras: pede cotação por e-mail aos fornecedores da categoria (sem categoria, a todos); as cotações que chegam
   entram na requisição pela tela; comparar escolhe a de menor valor; o pedido vai por e-mail ao fornecedor escolhido
   com o número `PC-<ano>-<sequência>`.
4. Vencimentos: os que vencem dentro da antecedência (padrão 30 dias) e ainda não foram avisados avisam dono e
   administrador numa mensagem só e ficam com `avisado_em`.

## 4. Casos de Borda e Erros Mapeados
- eSocial e assinatura sem integração → handoff dizendo o que o staff faz e informa.
- Sem caixa de entrada conectada (ou sem provedor de envio) → o 409 do svc-integracoes vira handoff; fora do ar → 503 `ERRO_ADMINISTRATIVO_INTEGRACOES_FORA` (o motor tenta de novo).
- Colaborador sem e-mail, requisição ou colaborador inexistente → handoff. Nenhum fornecedor para cotar → handoff
  "cadastre fornecedores"; nenhuma cotação recebida → handoff "fornecedor sem resposta".
- Membro criando admissão, requisição ou cotação → 403 `ERRO_ADMINISTRATIVO_FORBIDDEN`; requisição de outra organização → 404 `ERRO_ADMINISTRATIVO_NAO_ENCONTRADA`.
- Exemplo de saída que não confere, ação sem método ou modelo com ação não declarada: o serviço não sobe.
