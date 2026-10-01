# Spec: notify

## 1. Objetivo Operacional
Avisar pessoas: na tela (sino com a contagem ao vivo e a lista de avisos) e por e-mail. Os serviços chamam pelo
`core/notify.py` (README §5.15) e nunca falam com servidor de e-mail: só este serviço tem as credenciais SMTP.

## 2. Contrato de Entrada e Saída
Todas as rotas exigem token e valem para quem chama, na organização ativa: ninguém vê aviso de outra pessoa.
- `GET /items?read=&sort=&page=&size=` (`NotificationQuery`, lista paginada, README §5.12) → `NotificationPage`
  com `Notification { id, title, body, link, action, service, read, created_at }`, do mais novo ao mais velho.
- `GET /unread` → `Unread { count }`: avisos não lidos.
- `POST /read` (`ReadRequest { ids }`, até 100) → `Unread` · `POST /read-all` → `Unread`.
- `GET /preferences` → `Preferences { email }` · `POST /preferences` (`Preferences { email }`) → `Preferences`.
  Desligar o e-mail vale para os avisos comuns; e-mail de segurança (senha, convite) sempre sai.
- Ao vivo (`bus.live`): `notify.nova` (`Notification`) só para a pessoa avisada.
- NATS `events.notify.send` (`NotifyRequest`, publicado pelo `core/notify.py`): destinatários (`users`, `roles` ou
  `email`), `title`, `body`, `link` (caminho da aplicação, nunca endereço de fora), `action` (texto do botão) e
  `send_email`.

## 3. Fluxo de Execução
1. SurrealDB: `notify_items` (por organização; único por `message + user`: reentrega não duplica),
   `notify_emails` (global; único por `message + to`) e `notify_prefs` (global; um por pessoa).
2. NATS: consome `events.notify.send` e inicia `NotifyWorkflow` com o id da mensagem (nunca duas execuções).
   Pergunta ao `svc-identity` quem são as pessoas (`rpc.identity.contacts`): só membros da organização de quem
   enviou, com nome e e-mail.
3. Temporal: `NotifyWorkflow` → `notify.deliver` (grava os avisos, avisa ao vivo e prepara os e-mails) → um
   `notify.send_email` por e-mail, com até 8 tentativas e espera crescente (servidor de e-mail fora do ar não perde
   aviso). E-mail já enviado não sai de novo. Depois de enviado, o conteúdo é apagado (o link de senha não fica no
   banco); fica o registro de quem, quando e o resultado.
4. Agendamento diário: apaga avisos lidos com mais de 90 dias e registros de e-mail com mais de 30.

## 4. Casos de Borda e Erros Mapeados
- Destinatário que não é membro da organização é ignorado em silêncio (saiu da organização, id errado).
- Endereço recusado pelo servidor de e-mail → registro `failed`, sem nova tentativa. Servidor fora do ar ou erro
  temporário → nova tentativa; esgotadas, `failed`.
- `SMTP_URL`: `smtps://` (TLS direto) ou `smtp://` com STARTTLS obrigatório em produção; sem TLS só em
  `ENVIRONMENT=development` (Mailpit local). Configuração inválida impede o boot.
- O e-mail sai em HTML (tudo escapado) e em texto puro; o link vira `APP_URL + link`.
- `ERRO_NOTIFY_NOT_FOUND` não existe de propósito: marcar como lido um id que não é seu não faz nada.
