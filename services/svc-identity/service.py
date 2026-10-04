"""svc-identity · lógica de negócio pura. Fonte da verdade: specs/identity.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "identity.<método>".
Helpers começam com _ e nunca viram activities.

Único serviço com tabelas globais (README §5.9): usa db.query_shared e grava tenant como link para a organização.
Senhas só por core.security (Argon2id); refresh e convites guardados como hash SHA-256, nunca em claro.
"""
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from surrealdb import RecordID

from core.envelope import ServiceError
from core.nats_bus import bus
from core.security import (
    SYSTEM_PREFIX,
    Principal,
    acting_as,
    current,
    current_tenant,
    hash_password,
    issue_token,
    new_secret,
    password_needs_rehash,
    system,
    verify_password,
)
from core.notify import notify
from core.plans import plans
from core.storage import storage
from core.surreal import db
from core.temporal_runner import activities
from core.webhooks import webhooks

from schemas import (
    ACCESS_LIVE,
    INVITE_DAYS,
    INVITES,
    LOCK_MINUTES,
    LOGO_MAX_BYTES,
    LOGO_SECONDS,
    LOGO_TYPES,
    MAX_FAILED_LOGINS,
    MAX_RESETS_PER_HOUR,
    MEMBER_JOINED_SUBJECT,
    MEMBER_LEFT_SUBJECT,
    MEMBERS_LIVE,
    MEMBERSHIPS,
    STAFF_SERVICE,
    RESETS,
    RESET_MINUTES,
    REUSE_GRACE_SECONDS,
    SERVICE,
    SESSIONS,
    TENANT_CREATED_SUBJECT,
    TENANTS,
    USERS,
    AccessChanged,
    AuthResult,
    Cleaned,
    ClienteCriado,
    ClienteNovo,
    ColorInput,
    Contact,
    Contacts,
    ContactsRequest,
    ConviteDono,
    ConvitePendente,
    Dono,
    Empty,
    ExcluirConta,
    ForgotInput,
    IdentitySettings,
    Invite,
    InviteCode,
    InviteInfo,
    InviteInput,
    JoinRequest,
    KeepRequest,
    LoginInput,
    Me,
    Member,
    MemberJoined,
    MemberJoinedHook,
    MemberLeft,
    MemberLeftHook,
    MemberList,
    MemberRef,
    MembersChanged,
    OperadorAcesso,
    OperadorResultado,
    OrganizacaoResumo,
    Organizacoes,
    Organization,
    RefreshInput,
    ResetInput,
    Session,
    SignupInput,
    SwitchRequest,
    Tenant,
    TenantCreated,
    TenantRequest,
    Upload,
    UploadRequest,
    User,
)

settings = IdentitySettings()

# Blocos atômicos: um erro no meio (ex.: e-mail repetido) desfaz tudo; RETURN NONE sai antes de gravar.
_SIGNUP_WITH_ORGANIZATION = """{
    LET $u = CREATE ONLY identity_users CONTENT $user;
    LET $t = CREATE ONLY identity_tenants CONTENT { name: $organization, created_by: $u.id };
    CREATE identity_memberships CONTENT { user: $u.id, tenant: $t.id, roles: ['owner'] };
    RETURN { user: $u.id, tenant: $t.id, role: 'owner' };
}"""
_SIGNUP_WITH_INVITE = """{
    LET $inv = (UPDATE identity_invites SET used_at = time::now()
        WHERE code_hash = $code_hash AND used_at = NONE AND expires_at > time::now() RETURN AFTER)[0];
    IF $inv = NONE { RETURN NONE; };
    LET $u = CREATE ONLY identity_users CONTENT $user;
    UPDATE $inv.id SET used_by = $u.id;
    CREATE identity_memberships CONTENT { user: $u.id, tenant: $inv.tenant, roles: [$inv.role] };
    RETURN { user: $u.id, tenant: $inv.tenant, role: $inv.role, inviter: $inv.created_by };
}"""
_JOIN = """{
    LET $inv = (UPDATE identity_invites SET used_at = time::now(), used_by = $user
        WHERE code_hash = $code_hash AND used_at = NONE AND expires_at > time::now() RETURN AFTER)[0];
    IF $inv = NONE { RETURN NONE; };
    CREATE identity_memberships CONTENT { user: $user, tenant: $inv.tenant, roles: [$inv.role] };
    RETURN { user: $user, tenant: $inv.tenant, role: $inv.role, inviter: $inv.created_by };
}"""
_CREATE_CLIENT = """{
    LET $t = CREATE ONLY identity_tenants CONTENT { name: $name };
    CREATE identity_invites CONTENT { code_hash: $code_hash, tenant: $t.id, role: 'owner', email: $email, expires_at: $expires_at };
    RETURN $t.id;
}"""
_CREATE_TENANT = """{
    LET $t = CREATE ONLY identity_tenants CONTENT { name: $name, created_by: $user };
    CREATE identity_memberships CONTENT { user: $user, tenant: $t.id, roles: ['owner'] };
    RETURN $t.id;
}"""

_ROLE_NAMES = {"owner": "dono", "admin": "administrador", "member": "membro", "operador": "operador"}

_dummy_hash: str | None = None


@activities("identity")
class IdentityService:
    # ── Entrada ─────────────────────────────────────────────────────────────

    async def signup(self, data: SignupInput) -> Session:
        user = {
            "email": data.email,
            "name": data.name,
            "password_hash": await hash_password(data.password),
            "failed_logins": 0,
        }
        if data.invite is not None:
            await self._room_for_one(data.invite)  # plano da organização com vaga (README §5.17)
        try:
            if data.organization is not None:
                joined = await db.query_shared(_SIGNUP_WITH_ORGANIZATION, user=user, organization=data.organization)
            else:
                joined = await db.query_shared(_SIGNUP_WITH_INVITE, user=user, code_hash=_hash(data.invite))
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_IDENTITY_EMAIL_TAKEN", "Este e-mail já tem conta. Entre com ele.", 409) from None
            raise
        if joined is None:
            raise _invite_invalid()
        user_key, tenant_key = _key(joined["user"]), _key(joined["tenant"])
        await self._announce(
            user_key, tenant_key, joined["role"], created=data.organization, name=data.name, email=data.email,
            inviter=joined.get("inviter"),
        )
        return await self._issue(user_key, tenant_key)

    async def login(self, data: LoginInput) -> Session:
        rows = await db.query_shared("SELECT * FROM identity_users WHERE email = $email", email=data.email)
        user = rows[0] if rows else None
        if user is None:
            await verify_password(await _dummy(), data.password)  # mesmo tempo de quando o e-mail existe
            raise _bad_credentials()
        if (locked := user.get("locked_until")) and locked > _now():
            raise ServiceError("ERRO_IDENTITY_LOCKED", f"Muitas tentativas. Tente de novo em {LOCK_MINUTES} minutos.", 429)
        if not await verify_password(user["password_hash"], data.password):
            failed = user.get("failed_logins", 0) + 1
            lock = failed >= MAX_FAILED_LOGINS
            await db.merge(user["id"], {
                "failed_logins": 0 if lock else failed,
                "locked_until": _now() + timedelta(minutes=LOCK_MINUTES) if lock else None,
            })
            raise _bad_credentials()
        changes = {"failed_logins": 0, "locked_until": None}
        if password_needs_rehash(user["password_hash"]):
            changes["password_hash"] = await hash_password(data.password)
        await db.merge(user["id"], changes)
        user_key = _key(user["id"])
        tenants = await self._tenants(user_key)
        if data.tenant is not None and data.tenant not in {t.id for t in tenants}:
            raise _not_member()
        return await self._issue(user_key, data.tenant or user.get("last_tenant"), tenants=tenants)

    async def refresh(self, data: RefreshInput) -> Session:
        session = await self._session(data.refresh_token)
        if session.get("rotated_at") is not None:
            if _now() - session["rotated_at"] > timedelta(seconds=REUSE_GRACE_SECONDS):
                await self._revoke_family(session["family"])  # refresh antigo reapareceu: cópia roubada
                raise _invalid_session()
            raise _rotated()  # outra aba girou há pouco: o cookie do navegador já é o novo
        claimed = await db.query_shared(
            "UPDATE $id SET rotated_at = time::now() WHERE rotated_at = NONE AND revoked = false RETURN AFTER",
            id=_rid(session["id"]),
        )
        if not claimed:
            raise _rotated()  # outra aba girou o mesmo refresh no mesmo instante
        # A sessão segue a última organização escolhida (troca em qualquer aba vale para todas): um refresh que
        # chegou atrasado, girado antes de uma troca, não leva a pessoa de volta para a organização anterior.
        user = await db.select(f"{USERS}:{_key(session['user'])}")
        tenant = (user or {}).get("last_tenant") or (_key(session["tenant"]) if session.get("tenant") else None)
        return await self._issue(_key(session["user"]), tenant, family=session["family"])

    async def logout(self, data: RefreshInput) -> Empty:
        if data.refresh_token:
            rows = await db.query_shared(
                "SELECT family FROM identity_sessions WHERE token_hash = $h", h=_hash(data.refresh_token)
            )
            if rows:
                await self._revoke_family(rows[0]["family"])
        return Empty()

    async def forgot_password(self, data: ForgotInput) -> Empty:
        """Manda o link de redefinir senha, se houver conta. A resposta é sempre a mesma: não revela quem tem conta."""
        rows = await db.query_shared("SELECT id, email FROM identity_users WHERE email = $email", email=data.email)
        if not rows:
            return Empty()
        user = _rid(rows[0]["id"])
        recent = await db.query_shared(
            "SELECT count() AS total FROM (SELECT id FROM identity_resets WHERE user = $u AND created_at > $since) GROUP ALL",
            u=user, since=_now() - timedelta(hours=1),
        )
        if recent and recent[0]["total"] >= MAX_RESETS_PER_HOUR:
            return Empty()  # caixa de alguém sendo inundada: ignora em silêncio
        code = new_secret(24)
        await db.create(RESETS, {"code_hash": _hash(code), "user": user, "expires_at": _now() + timedelta(minutes=RESET_MINUTES)})
        await notify.email(
            rows[0]["email"],
            "Redefinir sua senha",
            "Recebemos um pedido para redefinir a senha da sua conta.\n\n"
            f"O link vale por {RESET_MINUTES} minutos e só pode ser usado uma vez. "
            "Se não foi você, ignore este e-mail: a sua senha continua a mesma.",
            link=f"/redefinir-senha?codigo={code}",
            action="Redefinir senha",
            key=f"reset-{_hash(code)[:32]}",
        )
        return Empty()

    async def reset_password(self, data: ResetInput) -> Empty:
        """Troca a senha pelo link do e-mail: o link vale uma vez, todas as sessões caem e a pessoa é avisada."""
        claimed = await db.query_shared(
            "UPDATE identity_resets SET used_at = time::now() "
            "WHERE code_hash = $h AND used_at = NONE AND expires_at > time::now() RETURN AFTER",
            h=_hash(data.code),
        )
        if not claimed:
            raise ServiceError("ERRO_IDENTITY_RESET_INVALID", "Link inválido, expirado ou já usado. Peça outro.", 404)
        user = await db.select(str(claimed[0]["user"]))
        if user is None:
            raise ServiceError("ERRO_IDENTITY_RESET_INVALID", "Link inválido, expirado ou já usado. Peça outro.", 404)
        await db.merge(user["id"], {"password_hash": await hash_password(data.password), "failed_logins": 0, "locked_until": None})
        user_rid = _rid(user["id"])
        await db.query_shared("UPDATE identity_resets SET used_at = time::now() WHERE user = $u AND used_at = NONE", u=user_rid)
        await db.query_shared("UPDATE identity_sessions SET revoked = true WHERE user = $u", u=user_rid)
        await notify.email(
            user["email"],
            "Sua senha foi alterada",
            "A senha da sua conta acabou de ser alterada, e as sessões abertas foram encerradas.\n\n"
            "Se não foi você, peça um novo link agora e troque a senha.",
            link="/esqueci-senha",
            action="Trocar a senha",
            key=f"changed-{_hash(data.code)[:32]}",
        )
        return Empty()

    # ── Conta e organizações ────────────────────────────────────────────────

    async def me(self, data: Empty) -> Me:
        who = _who()
        user = await db.select(f"{USERS}:{who.sub}")
        if user is None:
            raise _invalid_session()
        return Me(user=_user_view(user), tenant=who.tenant, tenants=await self._tenants(who.sub))

    async def excluir_conta(self, data: ExcluirConta) -> Empty:
        """A pessoa apaga a própria conta (LGPD): sai de todas as organizações, perde as sessões e o cadastro some. Quem
        é o único dono de uma organização ativa passa a propriedade ou pede o cancelamento antes. O que ela fez nos
        registros fica pelo id, sem nome nem e-mail."""
        who = _who()
        user = await db.select(f"{USERS}:{who.sub}")
        if user is None:
            raise _invalid_session()
        if not await verify_password(user["password_hash"], data.password):
            raise _bad_credentials()
        user_rid = RecordID(USERS, who.sub)
        vinculos = await db.query_shared("SELECT * FROM identity_memberships WHERE user = $u", u=user_rid)
        for vinculo in vinculos:
            tenant = _key(vinculo["tenant"])
            if "owner" not in vinculo["roles"]:
                continue
            donos = await db.query_shared("SELECT VALUE id FROM identity_memberships WHERE tenant = $t AND roles CONTAINS 'owner'",
                                          t=RecordID(TENANTS, tenant))
            if len(donos) > 1:
                continue
            with acting_as(system(SERVICE, tenant)):
                encerrada = await plans.situacao() == "encerrada"
            if not encerrada:
                nome = (await db.select(f"{TENANTS}:{tenant}") or {}).get("name", tenant)
                raise ServiceError("ERRO_IDENTITY_LAST_OWNER", f"Você é o único dono de {nome}: passe a propriedade a outra pessoa "
                                   "ou peça o cancelamento em Plano antes de apagar a sua conta.", 409)
        for vinculo in vinculos:
            tenant = _key(vinculo["tenant"])
            await db.delete(vinculo["id"])
            with acting_as(system(SERVICE, tenant)):
                await bus.publish(MEMBER_LEFT_SUBJECT, MemberLeft(tenant=tenant, user=who.sub),
                                  msg_id=f"saiu-{tenant}-{who.sub}-{_key(vinculo['id'])}")  # o svc-staff tira a carteira
                await plans.count("membros", await _member_count(tenant))
                await bus.live(MEMBERS_LIVE, MembersChanged(user=who.sub, change="removed"))
        await db.query_shared("DELETE identity_sessions WHERE user = $u", u=user_rid)
        await db.query_shared("DELETE identity_resets WHERE user = $u", u=user_rid)
        await db.query_shared("DELETE identity_invites WHERE email = $e AND used_by = NONE", e=user["email"])
        await db.delete(user["id"])
        await notify.email(user["email"], "Sua conta foi apagada",
                           "A sua conta na plataforma foi apagada a seu pedido, com o nome, o e-mail e a senha. "
                           "Se não foi você, fale com a Cogniventure.", key=f"conta-apagada-{who.sub}")
        return Empty()

    async def switch_tenant(self, data: SwitchRequest) -> Session:
        who = _who()
        tenants = await self._tenants(who.sub)
        if data.tenant not in {t.id for t in tenants}:
            raise _not_member()
        return await self._move(who.sub, data.tenant, data.refresh_token, tenants)

    async def create_tenant(self, data: TenantRequest) -> Session:
        who = _who()
        tenant_id = await db.query_shared(_CREATE_TENANT, name=data.name, user=RecordID(USERS, who.sub))
        tenant_key = _key(tenant_id)
        await self._announce(who.sub, tenant_key, "owner", created=data.name)
        return await self._move(who.sub, tenant_key, data.refresh_token)

    async def join(self, data: JoinRequest) -> Session:
        who = _who()
        await self._room_for_one(data.code)
        try:
            joined = await db.query_shared(_JOIN, code_hash=_hash(data.code), user=RecordID(USERS, who.sub))
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_IDENTITY_ALREADY_MEMBER", "Você já participa desta organização.", 409) from None
            raise
        if joined is None:
            raise _invite_invalid()
        tenant_key = _key(joined["tenant"])
        user = await db.select(f"{USERS}:{who.sub}")
        await self._announce(
            who.sub, tenant_key, joined["role"], name=user["name"] if user else None, email=user["email"] if user else None,
            inviter=joined.get("inviter"),
        )
        return await self._move(who.sub, tenant_key, data.refresh_token)

    # ── Convites e membros (organização ativa do token) ─────────────────────

    async def create_invite(self, data: InviteInput) -> Invite:
        who, tenant = await self._manager()
        await plans.check("membros", used=await _member_count(tenant))  # cedo, para quem convida; vale de novo ao aceitar
        code, expires_at = new_secret(24), _now() + timedelta(days=INVITE_DAYS)
        await db.create(INVITES, {
            "code_hash": _hash(code),
            "tenant": RecordID(TENANTS, tenant),
            "role": data.role,
            "email": data.email,
            "expires_at": expires_at,  # quem convidou e quando: carimbos do banco (created_by, created_at)
        })
        if data.email is not None:
            organization = await db.select(f"{TENANTS}:{tenant}")
            inviter = await db.select(f"{USERS}:{who.sub}")
            name = organization["name"] if organization else "uma organização"
            await notify.email(
                data.email,
                f"Convite para {name}",
                f"{inviter['name'] if inviter else 'Alguém'} convidou você para participar de {name} "
                f"como {_ROLE_NAMES[data.role]}.\n\nO convite vale por {INVITE_DAYS} dias e serve para uma pessoa.",
                link=f"/convite?codigo={code}",
                action="Ver convite",
                key=f"invite-{_hash(code)[:32]}",
            )
        return Invite(code=code, role=data.role, expires_at=expires_at, email=data.email)

    async def invite_info(self, data: InviteCode) -> InviteInfo:
        rows = await db.query_shared(
            "SELECT tenant.name AS tenant_name, role, expires_at FROM identity_invites "
            "WHERE code_hash = $h AND used_at = NONE AND expires_at > time::now()",
            h=_hash(data.code),
        )
        if not rows:
            raise _invite_invalid()
        return InviteInfo.model_validate(rows[0])

    async def list_members(self, data: Empty) -> MemberList:
        _, tenant = await self._member()
        rows = await db.query_shared(
            "SELECT user.id AS id, user.name AS name, user.email AS email, roles, created_at AS joined_at "
            "FROM identity_memberships WHERE tenant = $t ORDER BY joined_at",
            t=RecordID(TENANTS, tenant),
        )
        return MemberList(items=[Member.model_validate({**row, "id": _key(row["id"])}) for row in rows])

    async def remove_member(self, data: MemberRef) -> MemberList:
        who, tenant = await self._manager()
        target = await self._membership(data.user, tenant)
        if target is None:
            raise ServiceError("ERRO_IDENTITY_MEMBER_NOT_FOUND", "Membro não encontrado.", 404)
        if "owner" in target["roles"]:
            if "owner" not in await self._roles(who.sub, tenant):
                raise _forbidden()
            owners = await db.query_shared(
                "SELECT VALUE id FROM identity_memberships WHERE tenant = $t AND roles CONTAINS 'owner'",
                t=RecordID(TENANTS, tenant),
            )
            if len(owners) <= 1:
                raise ServiceError("ERRO_IDENTITY_LAST_OWNER", "A organização precisa de pelo menos um dono.", 409)
        gone = await db.select(f"{USERS}:{data.user}")
        await db.delete(target["id"])
        await db.query_shared(  # perde na hora as sessões nesta organização
            "UPDATE identity_sessions SET revoked = true WHERE user = $u AND tenant = $t",
            u=RecordID(USERS, data.user), t=RecordID(TENANTS, tenant),
        )
        await bus.live(MEMBERS_LIVE, MembersChanged(user=data.user, change="removed"))
        await bus.live(ACCESS_LIVE, AccessChanged(tenant=tenant, change="removed"), user=data.user)
        await bus.publish(MEMBER_LEFT_SUBJECT, MemberLeft(tenant=tenant, user=data.user),
                          msg_id=f"saiu-{tenant}-{data.user}-{_key(target['id'])}")  # o svc-staff tira a carteira
        await plans.count("membros", await _member_count(tenant))
        if gone is not None:
            await webhooks.emit(
                "membro-saiu", MemberLeftHook(id=data.user, name=gone["name"], email=gone["email"]),
                key=f"saiu-{tenant}-{data.user}-{_key(target['id'])}",
            )
        return await self.list_members(Empty())

    async def contacts(self, data: ContactsRequest) -> Contacts:
        """rpc.identity.contacts (svc-notify): nome e e-mail de quem é membro da organização de quem pergunta."""
        tenant = current_tenant()
        rows = await db.query_shared(
            "SELECT user.id AS id, user.name AS name, user.email AS email FROM identity_memberships "
            "WHERE tenant = $t AND (user IN $users OR roles CONTAINSANY $roles)",
            t=RecordID(TENANTS, tenant), users=[RecordID(USERS, u) for u in data.users], roles=list(data.roles),
        )
        organization = await db.select(f"{TENANTS}:{tenant}")
        return Contacts(
            tenant_name=organization["name"] if organization else "",
            items=[Contact(id=_key(row["id"]), name=row["name"], email=row["email"]) for row in rows],
        )

    async def operador(self, data: OperadorAcesso) -> OperadorResultado:
        """rpc.identity.operador (só o svc-staff): entrar na carteira dá o papel operador na organização do cliente;
        sair tira (sem outro papel, a pessoa deixa a organização e perde as sessões nela)."""
        staff = _from_staff()
        if await db.select(f"{TENANTS}:{data.tenant}") is None or await db.select(f"{USERS}:{data.user}") is None:
            raise ServiceError("ERRO_IDENTITY_NOT_FOUND", "Pessoa ou organização não encontrada.", 404)
        if data.ativo and not await self._membership(data.user, staff.tenant):  # só quem é da Cogniventure vira operador
            raise ServiceError("ERRO_IDENTITY_NOT_FOUND", "A pessoa não é da equipe da Cogniventure.", 404)
        membership = await self._membership(data.user, data.tenant)
        roles = list(membership["roles"]) if membership else []
        if data.ativo and "operador" not in roles:
            roles.append("operador")
            if membership:
                await db.query_shared("UPDATE $m SET roles = $roles", m=membership["id"], roles=roles)
            else:
                await db.query_shared("CREATE identity_memberships CONTENT { user: $u, tenant: $t, roles: $roles }",
                                      u=RecordID(USERS, data.user), t=RecordID(TENANTS, data.tenant), roles=roles)
            with acting_as(system(SERVICE, data.tenant)):
                await bus.live(MEMBERS_LIVE, MembersChanged(user=data.user, change="joined"))
        elif not data.ativo and "operador" in roles:
            roles.remove("operador")
            if roles:
                await db.query_shared("UPDATE $m SET roles = $roles", m=membership["id"], roles=roles)
            else:
                await db.delete(membership["id"])
                await db.query_shared("UPDATE identity_sessions SET revoked = true WHERE user = $u AND tenant = $t",
                                      u=RecordID(USERS, data.user), t=RecordID(TENANTS, data.tenant))
            with acting_as(system(SERVICE, data.tenant)):
                await bus.live(MEMBERS_LIVE, MembersChanged(user=data.user, change="removed"))
                if not roles:
                    await bus.live(ACCESS_LIVE, AccessChanged(tenant=data.tenant, change="removed"), user=data.user)
        return OperadorResultado(user=data.user, tenant=data.tenant, roles=roles)

    async def organizacoes(self, data: Empty) -> Organizacoes:
        """rpc.identity.organizacoes (só o svc-staff): as organizações da plataforma, para montar a carteira e a lista
        de clientes: o dono (ou o convite de dono pendente) e o último acesso de alguém do cliente."""
        _from_staff()
        rows = await db.query_shared("SELECT id, name, created_at FROM identity_tenants ORDER BY name")
        donos = await db.query_shared("SELECT tenant, user.name AS name, user.email AS email, created_at FROM identity_memberships "
                                      "WHERE roles CONTAINS 'owner' ORDER BY created_at")
        convites = await db.query_shared("SELECT tenant, email, expires_at, created_at FROM identity_invites WHERE role = 'owner' "
                                         "AND used_at = NONE AND expires_at > time::now() ORDER BY created_at")
        acessos = await db.query_shared("SELECT tenant, roles, ultimo_acesso FROM identity_memberships WHERE ultimo_acesso != NONE")
        dono: dict[str, Dono] = {}
        for r in donos:
            dono.setdefault(_key(str(r["tenant"])), Dono(name=r["name"], email=r["email"]))
        convite = {_key(str(r["tenant"])): ConvitePendente(email=r.get("email"), expires_at=r["expires_at"]) for r in convites}
        ultimo: dict[str, datetime] = {}
        for r in acessos:
            if set(r.get("roles") or []) <= {"operador"}:
                continue  # o staff trabalhando no cliente não é o cliente usando a plataforma
            tenant = _key(str(r["tenant"]))
            if tenant not in ultimo or r["ultimo_acesso"] > ultimo[tenant]:
                ultimo[tenant] = r["ultimo_acesso"]
        return Organizacoes(items=[
            OrganizacaoResumo(id=(t := _key(r["id"])), name=r["name"], created_at=r.get("created_at"), dono=dono.get(t),
                              convite=None if t in dono else convite.get(t), ultimo_acesso=ultimo.get(t))
            for r in rows
        ])

    async def cliente(self, data: ClienteNovo) -> ClienteCriado:
        """rpc.identity.cliente (só o svc-staff): a Cogniventure abre a organização do cliente, sem ninguém dela dentro,
        e convida o dono por e-mail. Ele entra pelo convite: cadastro novo ou, se já tem conta, entrar e aceitar."""
        _from_staff()
        code, expires_at = new_secret(24), _now() + timedelta(days=INVITE_DAYS)
        tenant_id = await db.query_shared(_CREATE_CLIENT, name=data.empresa, code_hash=_hash(code), email=data.email,
                                          expires_at=expires_at)
        tenant = _key(str(tenant_id))
        with acting_as(system(SERVICE, tenant)):
            await bus.publish(TENANT_CREATED_SUBJECT, TenantCreated(tenant=tenant, name=data.empresa), msg_id=f"tenant-{tenant}")
        await _convidar_dono(data.email, data.empresa, code)
        return ClienteCriado(tenant=tenant, name=data.empresa, convite=ConvitePendente(email=data.email, expires_at=expires_at))

    async def convite_dono(self, data: ConviteDono) -> ConvitePendente:
        """rpc.identity.convite_dono (só o svc-staff): o convite do dono de novo, enquanto ninguém entrou como dono. O
        convite anterior deixa de valer."""
        _from_staff()
        organization = await db.select(f"{TENANTS}:{data.tenant}")
        if organization is None:
            raise ServiceError("ERRO_IDENTITY_NOT_FOUND", "Organização não encontrada.", 404)
        t = RecordID(TENANTS, data.tenant)
        if await db.query_shared("SELECT VALUE id FROM identity_memberships WHERE tenant = $t AND roles CONTAINS 'owner'", t=t):
            raise ServiceError("ERRO_IDENTITY_DONO_JA_ENTROU", "O dono já entrou nesta organização.", 409)
        anteriores = await db.query_shared("SELECT email, created_at FROM identity_invites WHERE tenant = $t AND role = 'owner' "
                                           "ORDER BY created_at DESC", t=t)
        email = data.email or next((r["email"] for r in anteriores if r.get("email")), None)
        if email is None:
            raise ServiceError("ERRO_IDENTITY_SEM_EMAIL", "Informe o e-mail do dono.", 422)
        await db.query_shared("UPDATE identity_invites SET expires_at = time::now() WHERE tenant = $t AND role = 'owner' "
                              "AND used_at = NONE", t=t)
        code, expires_at = new_secret(24), _now() + timedelta(days=INVITE_DAYS)
        await db.create(INVITES, {"code_hash": _hash(code), "tenant": t, "role": "owner", "email": email, "expires_at": expires_at})
        await _convidar_dono(email, organization["name"], code)
        return ConvitePendente(email=email, expires_at=expires_at)

    # ── Organização: nome, logo e cor da marca ──────────────────────────────

    async def organization(self, data: Empty) -> Organization:
        _, tenant = await self._member()
        return await self._organization(tenant)

    async def logo_upload(self, data: UploadRequest) -> Upload:
        """Link de envio do logo (imagem até 2 MB); a tela envia direto ao armazenamento e depois chama set_logo."""
        await self._manager()
        return await storage.upload(data, accept=LOGO_TYPES, max_bytes=LOGO_MAX_BYTES, folder="logo")

    async def set_logo(self, data: KeepRequest) -> Organization:
        _, tenant = await self._manager()
        stored = await storage.keep(data.key)
        record = await db.select(f"{TENANTS}:{tenant}")
        old = (record or {}).get("logo")
        await db.merge(f"{TENANTS}:{tenant}", {"logo": stored.model_dump(exclude={"size"})})
        if old:
            await storage.delete(old["key"])
        return await self._organization(tenant)

    async def set_color(self, data: ColorInput) -> Organization:
        """Cor da marca da organização (donos e administradores): a tela a usa como cor principal."""
        _, tenant = await self._manager()
        await db.merge(f"{TENANTS}:{tenant}", {"color": data.color})
        return await self._organization(tenant)

    async def remove_logo(self, data: Empty) -> Organization:
        _, tenant = await self._manager()
        record = await db.select(f"{TENANTS}:{tenant}")
        if record and record.get("logo"):
            await storage.delete(record["logo"]["key"])
            await db.merge(f"{TENANTS}:{tenant}", {"logo": None})
        return await self._organization(tenant)

    async def _organization(self, tenant: str) -> Organization:
        record = await db.select(f"{TENANTS}:{tenant}")
        if record is None:
            raise _not_member()
        logo = record.get("logo")
        url = storage.url(logo["key"], ttl=LOGO_SECONDS, filename=logo["filename"], content_type=logo["content_type"]) if logo else None
        return Organization(id=tenant, name=record["name"], logo_url=url, color=record.get("color"))

    # ── Manutenção (workflows.py) ───────────────────────────────────────────

    async def cleanup(self, data: Empty) -> Cleaned:
        sessions = await db.query_shared("DELETE identity_sessions WHERE expires_at < time::now() RETURN BEFORE")
        invites = await db.query_shared("DELETE identity_invites WHERE expires_at < time::now() RETURN BEFORE")
        resets = await db.query_shared("DELETE identity_resets WHERE expires_at < time::now() RETURN BEFORE")
        return Cleaned(sessions=len(sessions or []), invites=len(invites or []), resets=len(resets or []))

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _issue(
        self, user_key: str, prefer: str | None, *, family: str | None = None, tenants: list[Tenant] | None = None
    ) -> Session:
        """Abre (ou continua, com family) a sessão e emite o token da organização preferida, se ainda for membro."""
        user = await db.select(f"{USERS}:{user_key}")
        if user is None:
            raise _invalid_session()
        tenants = tenants if tenants is not None else await self._tenants(user_key)
        active = next((t for t in tenants if t.id == prefer), tenants[0] if tenants else None)
        refresh = new_secret(32)
        now = _now()
        await db.create(SESSIONS, {
            "token_hash": _hash(refresh),
            "family": family or uuid.uuid4().hex,
            "user": RecordID(USERS, user_key),
            "tenant": RecordID(TENANTS, active.id) if active else None,
            "revoked": False,
            "expires_at": now + timedelta(days=settings.refresh_days),
        })
        if active and user.get("last_tenant") != active.id:
            await db.merge(user["id"], {"last_tenant": active.id})
        if active:  # o último acesso de cada organização (a lista de clientes do staff)
            await db.query_shared("UPDATE identity_memberships SET ultimo_acesso = time::now() WHERE user = $u AND tenant = $t",
                                  u=RecordID(USERS, user_key), t=RecordID(TENANTS, active.id))
        token = issue_token(
            user_key,
            tenant=active.id if active else None,
            roles=active.roles if active else (),
            ttl_seconds=settings.auth_token_ttl_seconds,
        )
        auth = AuthResult(
            access_token=token,
            expires_in=settings.auth_token_ttl_seconds,
            user=_user_view(user),
            tenant=active,
            tenants=tenants,
        )
        return Session(auth=auth, refresh_token=refresh, refresh_max_age=settings.refresh_days * 86_400)

    async def _move(self, user_key: str, tenant_key: str, refresh_token: str | None, tenants: list[Tenant] | None = None) -> Session:
        """Troca a organização da sessão: o refresh atual (se for deste usuário) é girado na mesma família."""
        family = None
        if refresh_token:
            rows = await db.query_shared(
                "UPDATE identity_sessions SET rotated_at = time::now() "
                "WHERE token_hash = $h AND user = $u AND rotated_at = NONE AND revoked = false RETURN AFTER",
                h=_hash(refresh_token), u=RecordID(USERS, user_key),
            )
            family = rows[0]["family"] if rows else None
        return await self._issue(user_key, tenant_key, family=family, tenants=tenants)

    async def _session(self, refresh_token: str | None) -> dict:
        if not refresh_token:
            raise _invalid_session()
        rows = await db.query_shared("SELECT * FROM identity_sessions WHERE token_hash = $h", h=_hash(refresh_token))
        session = rows[0] if rows else None
        if session is None or session.get("revoked") or session["expires_at"] <= _now():
            raise _invalid_session()
        return session

    async def _revoke_family(self, family: str) -> None:
        await db.query_shared("UPDATE identity_sessions SET revoked = true WHERE family = $f", f=family)

    async def _tenants(self, user_key: str) -> list[Tenant]:
        rows = await db.query_shared(
            "SELECT tenant.id AS id, tenant.name AS name, roles, created_at FROM identity_memberships "
            "WHERE user = $u ORDER BY created_at",
            u=RecordID(USERS, user_key),
        )
        return [Tenant(id=_key(row["id"]), name=row["name"], roles=row["roles"]) for row in rows]

    async def _membership(self, user_key: str, tenant_key: str) -> dict | None:
        rows = await db.query_shared(
            "SELECT * FROM identity_memberships WHERE user = $u AND tenant = $t",
            u=RecordID(USERS, user_key), t=RecordID(TENANTS, tenant_key),
        )
        return rows[0] if rows else None

    async def _roles(self, user_key: str, tenant_key: str) -> list[str]:
        membership = await self._membership(user_key, tenant_key)
        return membership["roles"] if membership else []

    async def _room_for_one(self, code: str) -> None:
        """Antes de aceitar um convite: a organização dele ainda tem vaga no plano? (convite inválido segue para o
        bloco atômico, que responde ERRO_IDENTITY_INVITE_INVALID)."""
        rows = await db.query_shared(
            "SELECT VALUE tenant FROM identity_invites WHERE code_hash = $h AND used_at = NONE AND expires_at > time::now()",
            h=_hash(code),
        )
        if rows:
            tenant = _key(str(rows[0]))
            with acting_as(system(SERVICE, tenant)):  # o limite é da organização do convite, não de quem entra
                await plans.check("membros", used=await _member_count(tenant))

    async def _member(self) -> tuple[Principal, str]:
        """Quem age e a organização ativa, conferindo no banco que ainda é membro (o token pode ter até 15 min)."""
        who = _who()
        if not who.tenant or not await self._roles(who.sub, who.tenant):
            raise _not_member()
        return who, who.tenant

    async def _manager(self) -> tuple[Principal, str]:
        who, tenant = await self._member()
        if not {"owner", "admin"} & set(await self._roles(who.sub, tenant)):
            raise _forbidden()
        return who, tenant

    async def _announce(
        self,
        user_key: str,
        tenant_key: str,
        role: str,
        created: str | None = None,
        name: str | None = None,
        email: str | None = None,
        inviter: str | None = None,
    ) -> None:
        """Avisa os outros serviços e quem convidou, em nome do novo membro (o cabeçalho leva a organização)."""
        with acting_as(Principal(sub=user_key, tenant=tenant_key, roles=frozenset({role}))):
            if created is not None:
                await bus.publish(TENANT_CREATED_SUBJECT, TenantCreated(tenant=tenant_key, name=created), msg_id=f"tenant-{tenant_key}")
            await bus.publish(
                MEMBER_JOINED_SUBJECT,
                MemberJoined(tenant=tenant_key, user=user_key, roles=[role]),
                msg_id=f"member-{tenant_key}-{user_key}",
            )
            await bus.live(MEMBERS_LIVE, MembersChanged(user=user_key, change="joined"))
            await plans.count("membros", await _member_count(tenant_key))
            if created is None and name and email:  # entrou numa organização que já existia
                await webhooks.emit(
                    "membro-entrou", MemberJoinedHook(id=user_key, name=name, email=email, role=role),
                    key=f"entrou-{tenant_key}-{user_key}",
                )
            if inviter and inviter != user_key and name and not inviter.startswith(SYSTEM_PREFIX):  # carimbo de pessoa
                await notify.user(
                    inviter,
                    f"{name} entrou na organização",
                    f"{name} aceitou o seu convite e agora participa como {_ROLE_NAMES.get(role, role)}.",
                    link="/membros",
                    action="Ver membros",
                    key=f"joined-{tenant_key}-{user_key}",
                )


async def _convidar_dono(email: str, empresa: str, code: str) -> None:
    await notify.email(
        email,
        f"A conta de {empresa} está pronta",
        f"A Cogniventure abriu a conta de {empresa} na plataforma e convidou você como dono.\n\n"
        "Pelo link, crie a sua senha (ou entre, se já tiver conta) e comece pelo briefing da empresa. "
        f"O convite vale por {INVITE_DAYS} dias.",
        link=f"/convite?codigo={code}",
        action="Aceitar o convite",
        key=f"invite-{_hash(code)[:32]}",
    )


async def _member_count(tenant: str) -> int:
    rows = await db.query_shared(
        "SELECT count() AS total FROM (SELECT id FROM identity_memberships WHERE tenant = $t) GROUP ALL",
        t=RecordID(TENANTS, tenant),
    )
    return rows[0]["total"] if rows else 0


async def apagar_organizacao() -> None:
    """A organização saiu de vez (db.connected(on_purge=...), como ela, 30 dias depois do encerramento): vínculos,
    convites, sessões, o logo e a própria organização. As pessoas continuam com as contas delas."""
    tenant = current_tenant()
    t = RecordID(TENANTS, tenant)
    await db.query_shared("DELETE identity_memberships WHERE tenant = $t", t=t)
    await db.query_shared("DELETE identity_invites WHERE tenant = $t", t=t)
    await db.query_shared("DELETE identity_sessions WHERE tenant = $t", t=t)
    await db.query_shared("UPDATE identity_users SET last_tenant = NONE WHERE last_tenant = $k", k=tenant)
    await db.query_shared("DELETE $t", t=t)


def _who() -> Principal:
    who = current()
    if who is None:
        raise _invalid_session()
    return who


async def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password(new_secret())
    return _dummy_hash


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _key(record_id: str) -> str:
    return record_id.partition(":")[2].strip("⟨⟩`")


def _rid(record_id: str) -> RecordID:
    table, _, key = record_id.partition(":")
    return RecordID(table, key.strip("⟨⟩`"))


def _user_view(user: dict) -> User:
    return User(id=_key(user["id"]), name=user["name"], email=user["email"])


def _bad_credentials() -> ServiceError:
    return ServiceError("ERRO_IDENTITY_INVALID_CREDENTIALS", "E-mail ou senha inválidos.", 401)


def _invalid_session() -> ServiceError:
    return ServiceError("ERRO_IDENTITY_INVALID_SESSION", "Sessão expirada. Entre de novo.", 401)


def _rotated() -> ServiceError:
    return ServiceError("ERRO_IDENTITY_SESSION_ROTATED", "Sessão renovada em outra aba. Tente de novo.", 401)


def _invite_invalid() -> ServiceError:
    return ServiceError("ERRO_IDENTITY_INVITE_INVALID", "Convite inválido, expirado ou já usado.", 404)


def _not_member() -> ServiceError:
    return ServiceError("ERRO_IDENTITY_NOT_MEMBER", "Você não participa desta organização.", 403)


def _forbidden() -> ServiceError:
    return ServiceError("ERRO_IDENTITY_FORBIDDEN", "Só donos e administradores podem fazer isso.", 403)


def _from_staff() -> Principal:
    """As RPCs do staff atravessam organizações: só o svc-staff as chama (o Principal do NATS vem da plataforma), agindo
    na organização da Cogniventure."""
    who = current()
    if who is None or who.sub != f"{SYSTEM_PREFIX}{STAFF_SERVICE}" or not who.tenant:
        raise ServiceError("ERRO_IDENTITY_FORBIDDEN", "Só o serviço do staff faz isso.", 403)
    return who
