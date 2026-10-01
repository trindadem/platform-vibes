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
    Principal,
    acting_as,
    current,
    hash_password,
    issue_token,
    new_secret,
    password_needs_rehash,
    verify_password,
)
from core.storage import storage
from core.surreal import db
from core.temporal_runner import activities

from schemas import (
    ACCESS_LIVE,
    INVITE_DAYS,
    INVITES,
    LOCK_MINUTES,
    LOGO_MAX_BYTES,
    LOGO_SECONDS,
    LOGO_TYPES,
    MAX_FAILED_LOGINS,
    MEMBER_JOINED_SUBJECT,
    MEMBERS_LIVE,
    MEMBERSHIPS,
    REUSE_GRACE_SECONDS,
    SESSIONS,
    TENANT_CREATED_SUBJECT,
    TENANTS,
    USERS,
    AccessChanged,
    AuthResult,
    Cleaned,
    Empty,
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
    MemberList,
    MemberRef,
    MembersChanged,
    Organization,
    RefreshInput,
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
    RETURN { user: $u.id, tenant: $inv.tenant, role: $inv.role };
}"""
_JOIN = """{
    LET $inv = (UPDATE identity_invites SET used_at = time::now(), used_by = $user
        WHERE code_hash = $code_hash AND used_at = NONE AND expires_at > time::now() RETURN AFTER)[0];
    IF $inv = NONE { RETURN NONE; };
    CREATE identity_memberships CONTENT { user: $user, tenant: $inv.tenant, roles: [$inv.role] };
    RETURN { user: $user, tenant: $inv.tenant, role: $inv.role };
}"""
_CREATE_TENANT = """{
    LET $t = CREATE ONLY identity_tenants CONTENT { name: $name, created_by: $user };
    CREATE identity_memberships CONTENT { user: $user, tenant: $t.id, roles: ['owner'] };
    RETURN $t.id;
}"""

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
        await self._announce(user_key, tenant_key, joined["role"], created=data.organization)
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
        tenant = _key(session["tenant"]) if session.get("tenant") else None
        return await self._issue(_key(session["user"]), tenant, family=session["family"])

    async def logout(self, data: RefreshInput) -> Empty:
        if data.refresh_token:
            rows = await db.query_shared(
                "SELECT family FROM identity_sessions WHERE token_hash = $h", h=_hash(data.refresh_token)
            )
            if rows:
                await self._revoke_family(rows[0]["family"])
        return Empty()

    # ── Conta e organizações ────────────────────────────────────────────────

    async def me(self, data: Empty) -> Me:
        who = _who()
        user = await db.select(f"{USERS}:{who.sub}")
        if user is None:
            raise _invalid_session()
        return Me(user=_user_view(user), tenant=who.tenant, tenants=await self._tenants(who.sub))

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
        try:
            joined = await db.query_shared(_JOIN, code_hash=_hash(data.code), user=RecordID(USERS, who.sub))
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_IDENTITY_ALREADY_MEMBER", "Você já participa desta organização.", 409) from None
            raise
        if joined is None:
            raise _invite_invalid()
        tenant_key = _key(joined["tenant"])
        await self._announce(who.sub, tenant_key, joined["role"])
        return await self._move(who.sub, tenant_key, data.refresh_token)

    # ── Convites e membros (organização ativa do token) ─────────────────────

    async def create_invite(self, data: InviteInput) -> Invite:
        who, tenant = await self._manager()
        code, expires_at = new_secret(24), _now() + timedelta(days=INVITE_DAYS)
        await db.create(INVITES, {
            "code_hash": _hash(code),
            "tenant": RecordID(TENANTS, tenant),
            "role": data.role,
            "expires_at": expires_at,  # quem convidou e quando: carimbos do banco (created_by, created_at)
        })
        return Invite(code=code, role=data.role, expires_at=expires_at)

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
        await db.delete(target["id"])
        await db.query_shared(  # perde na hora as sessões nesta organização
            "UPDATE identity_sessions SET revoked = true WHERE user = $u AND tenant = $t",
            u=RecordID(USERS, data.user), t=RecordID(TENANTS, tenant),
        )
        await bus.live(MEMBERS_LIVE, MembersChanged(user=data.user, change="removed"))
        await bus.live(ACCESS_LIVE, AccessChanged(tenant=tenant, change="removed"), user=data.user)
        return await self.list_members(Empty())

    # ── Organização: nome e logo ────────────────────────────────────────────

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
        return Organization(id=tenant, name=record["name"], logo_url=url)

    # ── Manutenção (workflows.py) ───────────────────────────────────────────

    async def cleanup(self, data: Empty) -> Cleaned:
        sessions = await db.query_shared("DELETE identity_sessions WHERE expires_at < time::now() RETURN BEFORE")
        invites = await db.query_shared("DELETE identity_invites WHERE expires_at < time::now() RETURN BEFORE")
        return Cleaned(sessions=len(sessions or []), invites=len(invites or []))

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

    async def _announce(self, user_key: str, tenant_key: str, role: str, created: str | None = None) -> None:
        """Avisa os outros serviços, em nome do novo membro (o cabeçalho leva a organização)."""
        with acting_as(Principal(sub=user_key, tenant=tenant_key, roles=frozenset({role}))):
            if created is not None:
                await bus.publish(TENANT_CREATED_SUBJECT, TenantCreated(tenant=tenant_key, name=created), msg_id=f"tenant-{tenant_key}")
            await bus.publish(
                MEMBER_JOINED_SUBJECT,
                MemberJoined(tenant=tenant_key, user=user_key, roles=[role]),
                msg_id=f"member-{tenant_key}-{user_key}",
            )
            await bus.live(MEMBERS_LIVE, MembersChanged(user=user_key, change="joined"))


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
