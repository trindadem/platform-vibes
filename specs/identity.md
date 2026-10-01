# Spec: identity

## 1. Objetivo Operacional
Dar a cada pessoa uma conta e a cada cliente uma organização isolada: cadastro, login, sessão renovável e convites.
É o único serviço que emite tokens (só ele tem `AUTH_PRIVATE_KEY`) e o único com tabelas globais (README §5.7 e §5.9).

## 2. Contrato de Entrada e Saída
Públicas (sem token):
- `POST /signup` (`SignupInput`): `{ name, email, password, organization? , invite? }`, exatamente um dos dois últimos → `AuthResult`
- `POST /login` (`LoginInput`): `{ email, password, tenant? }` → `AuthResult`
- `POST /refresh` e `POST /logout` (`Empty`, cookie `cv_refresh`) → `AuthResult` / `Empty`
- `POST /invite-info` (`InviteCode`): `{ code }` → `InviteInfo { tenant_name, role, expires_at }`

Com token:
- `GET /me` → `Me { user, tenant, tenants }` · `GET /members` → `MemberList { items }`
- `POST /switch` (`SwitchInput { tenant }`), `POST /tenants` (`TenantInput { name }`), `POST /join` (`InviteCode`) → `AuthResult`
- `POST /invites` (`InviteInput { role: admin | member }`) → `Invite { code, role, expires_at }` · só owner/admin
- `POST /members/remove` (`MemberRef { user }`) → `MemberList` · só owner/admin

`AuthResult = { access_token, expires_in, user: User, tenant: Tenant | null, tenants: Tenant[] }`, com
`User { id, name, email }` e `Tenant { id, name, roles }`. O token de acesso é EdDSA de 15 min: `sub` = usuário,
`tenant` = organização ativa, `roles` = papéis nela (`owner | admin | member`). O refresh nunca vai no corpo: vai no
cookie `cv_refresh` (HttpOnly, SameSite=Strict, Path=/api/v1/identity, Secure em produção, 30 dias).

## 3. Fluxo de Execução
1. SurrealDB, tabelas globais (`shared`): `identity_users` (email único, `password_hash` Argon2id, `failed_logins`,
   `locked_until`, `last_tenant`), `identity_tenants` (`name`), `identity_memberships` (`user`, `tenant`, `roles`; único
   por usuário e organização), `identity_invites` (`code_hash` único, `tenant`, `role`, `expires_at` em 7 dias,
   `used_by`) e `identity_sessions` (`token_hash` único, `family`, `user`, `tenant`, `expires_at`, `rotated_at`,
   `revoked`). Cadastro, convite e criação de organização gravam num bloco atômico.
2. NATS: `events.identity.tenant-created` `{ tenant, name }` e `events.identity.member-joined` `{ tenant, user, roles }`,
   publicados em nome do novo membro. `events.identity.trigger` inicia a limpeza.
3. Temporal: `IdentityWorkflow` → activity `identity.cleanup` (apaga sessões e convites vencidos; timeout 5 min,
   3 tentativas).

## 4. Casos de Borda e Erros Mapeados
- `ERRO_IDENTITY_INVALID_CREDENTIALS` (401): e-mail ou senha errados; mesma mensagem e mesmo tempo se o e-mail não existe.
- `ERRO_IDENTITY_LOCKED` (429): 5 erros seguidos bloqueiam o login por 15 min.
- `ERRO_IDENTITY_EMAIL_TAKEN` (409) · `ERRO_IDENTITY_ALREADY_MEMBER` (409) · `ERRO_IDENTITY_LAST_OWNER` (409).
- `ERRO_IDENTITY_INVALID_SESSION` (401): refresh ausente, vencido, revogado ou reusado. Refresh já trocado que
  reaparece depois de 30 s revoga a sessão inteira (cópia roubada).
- `ERRO_IDENTITY_SESSION_ROTATED` (401): o mesmo refresh foi trocado há menos de 30 s (corrida entre abas); o cookie
  do navegador já é o novo, então o cliente tenta de novo uma vez.
- `ERRO_IDENTITY_NOT_MEMBER` (403) · `ERRO_IDENTITY_FORBIDDEN` (403: só owner/admin convidam e removem; admin não
  remove owner) · `ERRO_IDENTITY_INVITE_INVALID` (404) · `ERRO_IDENTITY_MEMBER_NOT_FOUND` (404).
- Limites: nome e organização 2–80 caracteres, e-mail até 254 (guardado em minúsculas), senha 8–1024.
- Membro removido perde na hora as sessões daquela organização; o token de acesso já emitido vale até expirar (≤ 15 min).
- Sem e-mail na v1: não há verificação de e-mail nem "esqueci a senha".
