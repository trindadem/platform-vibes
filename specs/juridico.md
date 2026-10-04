# Spec: juridico

## 1. Objetivo Operacional
O pacote de ações jurídicas do BPO (briefing.md §4 e §10): o que os processos de gestão de contratos, publicações e
certidões negativas chamam. Guarda os contratos e as certidões da empresa, calcula prazos processuais em dias úteis e
avisa antes de vencer; o que depende de integração ainda não escolhida (assinatura eletrônica, tribunais e diários,
portais de certidões; briefing.md §14, decisão 6) vai para o staff, que faz e informa o resultado na exceção.

## 2. Contrato de Entrada e Saída
Ações (`processes.declare` e `processes.worker`), cada uma o método de mesmo nome no service.py:
- `juridico.coletar_assinaturas` (externa, conexão Assinatura eletrônica): `Assinatura {parte, email, objeto}` → `Assinado {assinado_em}`.
- `juridico.arquivar_contrato` (escrita): `ContratoIn {parte, cnpj, objeto, valor, inicio, fim, reajuste_em, vigencia_meses, assinado_em, proposta_id}` → `Arquivado {contrato_id, fim, aviso_em}`.
- `juridico.consultar_publicacoes` (externa, conexão Tribunais e diários oficiais): `Consulta {cnpj}` → `Publicacoes {novas, resumo, disponibilizada_em, dias_prazo}`.
- `juridico.calcular_prazo` (leitura): `Prazo {disponibilizada_em, dias_prazo}` → `PrazoFinal {publicada_em, prazo_final, dias_uteis}`.
- `juridico.emitir_certidoes` (externa, conexão Portais de certidões): `CertidoesIn {cnpj}` → `Certidoes {positivas, validade, resumo}`.
- `juridico.registrar_certidoes` (escrita): `CertidoesEmitidas {positivas, validade, resumo}` → `RegistroCertidoes {certidao_id, aviso_em}`.
Modelos (`processes.declare`, o fluxo de partida de cada um): `gestao-contratos` (gatilho: a proposta comercial que
termina aceita), `publicacoes-processos` (dias úteis, 7h) e `certidoes-negativas` (dia 1 de cada mês).
Rotas:
- Cadastro declarado `contratos` (README §5.19): `Contrato {parte, cnpj, objeto, valor, inicio, fim, reajuste_em, status: vigente|encerrado, proposta_id}`.
- Cadastro declarado `certidoes`: `Certidao {referencia, positivas, validade, resumo}`.
- Escrevem dono, admin e operador; ao vivo `juridico.contratos` e `juridico.certidoes`.

## 3. Fluxo de Execução
1. SurrealDB, por organização: `juridico_contratos` e `juridico_certidoes` (cadastros declarados).
2. Arquivar: o contrato entra no cadastro, vigente; o fim é o informado ou o início (senão a assinatura, senão hoje)
   mais a vigência em meses (padrão 12). O aviso é 60 dias antes do fim.
3. Prazo: a publicação é o primeiro dia útil depois da disponibilização no diário (Lei 11.419/2006, art. 4º, §3º) e o
   prazo conta em dias úteis a partir do dia útil seguinte (CPC, arts. 219 e 224), sem fins de semana, feriados
   nacionais (os fixos e os da Páscoa: Carnaval, Sexta-feira Santa e Corpus Christi) e o recesso de 20/12 a 20/01
   (CPC, art. 220).
4. Certidões: cada emissão entra no cadastro com a validade mais próxima; o aviso é 15 dias antes.
5. Agendamento diário (`AvisosWorkflow`, 8h em Brasília): contrato vigente a 60 e a 30 dias do fim (e do reajuste) e
   certidão a 15 dias da validade avisam dono e administrador (`notify.roles`), cada aviso uma vez (`key`).

## 4. Casos de Borda e Erros Mapeados
- Assinatura, publicações e certidões sem integração → handoff dizendo o que o staff faz e o que informa (a saída do
  passo na exceção).
- Arquivar sem parte ou sem objeto → handoff "Faltam dados". Data fora do formato AAAA-MM-DD é ignorada (vale a vigência).
- Prazo sem a data da disponibilização ou sem os dias → handoff.
- Exemplo de saída que não confere com o modelo de saída, ação sem método no service.py ou modelo que cita ação não
  declarada: o serviço não sobe.
