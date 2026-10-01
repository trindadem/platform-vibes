# Spec: webhooks

## 1. Objetivo Operacional
Avisar os sistemas de cada organização quando algo acontece na plataforma: a organização cadastra endereços HTTPS e
escolhe os eventos; cada evento sai assinado (padrão Standard Webhooks), com retentativas e registro de cada entrega.
Os serviços emitem pelo `core/webhooks.py` (README §5.16) e nunca fazem a chamada eles mesmos.

## 2. Contrato de Entrada e Saída
Todas as rotas exigem token de `owner` ou `admin` e valem para a organização ativa.
- `GET /endpoints` → `EndpointList { items: Endpoint[] }` · `Endpoint { id, url, description, events, enabled,
  failures, disabled_reason, created_at }` (`events`: nomes ou `["*"]` para todos)
- `POST /endpoints` (`EndpointInput { url, description?, events }`) → `EndpointSecret { endpoint, secret }`: o segredo
  (`whsec_...`) aparece só aqui e ao trocar
- `POST /endpoints/update` (`EndpointUpdate { id, url?, description?, events?, enabled? }`) → `Endpoint`; reativar
  zera as falhas
- `POST /endpoints/remove` (`EndpointRef { id }`) → `EndpointList`
- `POST /endpoints/rotate` (`EndpointRef`) → `EndpointSecret`: o segredo antigo deixa de valer na hora
- `POST /endpoints/test` (`EndpointRef`) → `Delivery`: envia `webhooks.teste` agora, uma tentativa, e diz o resultado
- `GET /deliveries?endpoint=&status=&event=&sort=&page=&size=` (`DeliveryQuery`, README §5.12) → `DeliveryPage` com
  `Delivery { id, endpoint, url, event, status, attempts, response_status, error, duration_ms, created_at,
  delivered_at }` (`status`: `pending | sent | failed | skipped`)
- `POST /deliveries/retry` (`DeliveryRef { id }`) → `Delivery`: reenvia o mesmo corpo, com o mesmo `webhook-id`
- `GET /events` → `EventList { items: CatalogEvent[] }` · `CatalogEvent { name, service, description, payload_schema }` (JSON Schema do `data`)
- Ao vivo (`bus.live`): `webhooks.entrega` (`DeliveryChanged { id, status }`) para a organização.
- NATS `events.webhooks.emit` (`Emitted`) e `events.webhooks.catalog` (`Catalog`), publicados pelo `core/webhooks.py`.

O que chega no endereço do cliente (POST, `content-type: application/json`):
`{ "type": "identity.membro-entrou", "timestamp": "2026-10-01T15:00:00Z", "data": { ... } }` com os cabeçalhos
`webhook-id` (o mesmo em toda tentativa), `webhook-timestamp` (segundos) e `webhook-signature`
(`v1,<base64(HMAC-SHA256(segredo, "{id}.{timestamp}.{corpo}"))>`).

## 3. Fluxo de Execução
1. SurrealDB: `webhook_endpoints` (por organização; segredo criptografado com AES-256-GCM e `WEBHOOKS_SECRETS_KEY`,
   preso à organização e ao endereço), `webhook_deliveries` (por organização; única por `message + endpoint`) e
   `webhook_events` (global; o catálogo, um por nome).
2. NATS: `events.webhooks.catalog` grava o catálogo que cada serviço declara no boot (o que saiu da lista do serviço
   sai do catálogo). `events.webhooks.emit` inicia `WebhooksWorkflow` com o id da mensagem (nunca duas execuções).
   `events.webhooks.retry` (do reenviar) inicia `RedeliverWorkflow`.
3. Temporal: `WebhooksWorkflow` → `webhooks.fan_out` (uma entrega por endereço ativo inscrito no evento) → um
   `webhooks.deliver` por entrega, com até 10 tentativas (5 s, 20 s, 80 s… até 5 h entre elas, cerca de 15 h);
   esgotadas, `webhooks.give_up`. Agendamento diário apaga entregas com mais de 30 dias.

## 4. Casos de Borda e Erros Mapeados
- `ERRO_WEBHOOKS_FORBIDDEN` (403): quem não é owner/admin.
- `ERRO_WEBHOOKS_UNSAFE_URL` (422): endereço que não é `https` público. `http` e rede interna só com
  `ENVIRONMENT=development` (receptor local). O endereço é conferido de novo a cada envio (DNS pode mudar).
- `ERRO_WEBHOOKS_UNKNOWN_EVENT` (422): evento fora do catálogo · `ERRO_WEBHOOKS_ENDPOINT_NOT_FOUND` (404) ·
  `ERRO_WEBHOOKS_DELIVERY_NOT_FOUND` (404) · `ERRO_WEBHOOKS_LIMIT` (409): mais de 20 endereços por organização.
- Resposta 2xx: entregue. `410 Gone`: o endereço é desativado na hora (o cliente pediu para parar). Outra resposta,
  redirecionamento (não seguido), tempo esgotado (15 s) ou falha de rede: nova tentativa. O corpo da resposta não é
  guardado (pode trazer dados do cliente); fica o código e o tempo.
- 20 entregas seguidas sem sucesso desativam o endereço e avisam donos e administradores (tela + e-mail). Uma
  entrega com sucesso zera a contagem.
- Endereço removido ou desativado: entregas pendentes viram `skipped`. Sem garantia de ordem entre eventos: o
  `timestamp` do corpo diz quando aconteceu.
