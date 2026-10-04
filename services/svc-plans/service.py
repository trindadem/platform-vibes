"""svc-plans · lógica de negócio pura. Fonte da verdade: specs/plans.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo
de schemas.py, retorna 1 modelo de schemas.py e vira a activity Temporal "plans.<método>".
Helpers começam com _ e nunca viram activities.

Serviço de plataforma (README §5.17): guarda o catálogo de módulos e limites que os serviços declaram, os planos
(geridos por quem administra a plataforma, PLATFORM_TENANT), o plano e o ajuste de módulos de cada organização e o
consumo do mês. Quem confere é o core/plans.py, no serviço chamado (módulo) ou que vai criar ou gastar (limite); aqui
só se resolve, soma e avisa.

A conta de cada cliente (alinhamento pós-N7, itens 2 e 13): a mensalidade e o vencimento, a situação (ativa, suspensa
por atraso ou encerrada) e o cancelamento no fim do mês pago. No fechamento do mês, cada cliente pagante inicia o
Faturamento e cobrança na organização da Cogniventure. Encerrada, a conta fica 30 dias com os dados (o dono baixa o
pacote e pode reativar) e depois sai de vez, de todos os serviços e dos arquivos.
"""
import csv
import functools
import io
import json
import os
import tempfile
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nats.errors import NoRespondersError

from surrealdb import RecordID

from core.envelope import ServiceError
from core.nats_bus import bus
from core.notify import notify
from core.security import Principal, acting_as, current, current_tenant, system
from core.storage import storage
from core.surreal import DataPage, DataRequest, Migration, db
from core.temporal_runner import activities, runner

from schemas import (
    ACCOUNTS,
    MODULE_CATALOG,
    ALERTS,
    CONTACTS_SUBJECT,
    COUNTS,
    DIAS_ATE_EXCLUIR,
    ENCERRADA_SUBJECT,
    EXPORT_FILE_BYTES,
    EXPORTS,
    FATURAMENTO_MODELO,
    FUSO,
    INICIAR_MODELO_SUBJECT,
    KEEP_LOG_DAYS,
    KEEP_MONTHS,
    MANAGERS,
    NO_PLAN,
    PURGE_SUBJECT,
    SERVICE,
    STAFF_SERVICE,
    TASK_QUEUE,
    TIERS,
    USAGE,
    USAGE_LIVE,
    USAGE_LOG,
    VENCIMENTO_PADRAO,
    Account,
    AccountRef,
    Assigned,
    AssignInput,
    AssignRequest,
    Cancelamento,
    CancelamentoIn,
    Catalog,
    CatalogLimit,
    CatalogModule,
    Cleaned,
    Cobrado,
    Contacts,
    ContactsRequest,
    Conta,
    ContaAcao,
    ContaEncerrada,
    CountReport,
    Current,
    Empty,
    Encerramentos,
    ExecucaoIniciada,
    Exportacao,
    ExportacaoAtual,
    ExportacaoRef,
    Fechamento,
    FechamentoIn,
    IniciarModelo,
    LimitsRequest,
    LimitState,
    ModuleCatalog,
    ModuleList,
    ModuleState,
    Plan,
    PlanInput,
    PlanLimits,
    PlanList,
    PlanRef,
    PlansSettings,
    PlanUpdate,
    PurgeRequest,
    UsageChanged,
    UsageReport,
)

# Mudanças de dados versionadas, rodadas uma vez por banco no boot (README §5.13). Nunca edite uma já publicada.
MIGRATIONS: list[Migration] = []

# Bloco atômico: a linha da mensagem e a soma do mês entram juntas ou nenhuma. Mensagem repetida (reentrega do NATS)
# viola o índice único da linha e nada é somado.
_ADD_USAGE = """{
    CREATE plan_usage_log CONTENT { tenant: $tenant, message: $message, name: $name, month: $month, amount: $amount };
    LET $row = (UPDATE plan_usage SET used += $amount
        WHERE tenant = $tenant AND name = $name AND month = $month RETURN AFTER)[0];
    IF $row = NONE {
        LET $new = CREATE ONLY plan_usage CONTENT { tenant: $tenant, name: $name, month: $month, used: $amount, alerted: 0 };
        RETURN $new;
    };
    RETURN $row;
}"""


@functools.cache
def settings() -> PlansSettings:
    return PlansSettings()


@activities("plans")
class PlansService:
    # ── Organização (qualquer membro) ───────────────────────────────────────

    async def current(self, data: Empty) -> Current:
        who = _member()
        tier, _ = await self._plan_of(who.tenant)
        resolved = await self.resolve(LimitsRequest())
        return Current(
            tenant=who.tenant, plan=_plan(tier) if tier else None, month=resolved.month, limits=resolved.limits,
            modules=resolved.modules, manages_platform=_manages_platform(who), conta=await _conta(who.tenant),
        )

    async def modules(self, data: Empty) -> ModuleList:
        """Os módulos e se cada um está ligado para a organização ativa: o menu da tela esconde os desligados."""
        _member()
        return ModuleList(items=(await self.resolve(LimitsRequest())).modules)

    async def list_plans(self, data: Empty) -> PlanList:
        """Os públicos e o da própria organização; quem administra a plataforma vê todos."""
        who = _member()
        tier, _ = await self._plan_of(who.tenant)
        manages = _manages_platform(who)
        rows = await db.query_shared(
            "SELECT * FROM plan_tiers WHERE public = true OR slug = $current OR $all = true ORDER BY price, name",
            current=tier["slug"] if tier else "", all=manages,
        )
        return PlanList(items=[_plan(row) for row in rows], current=tier["slug"] if tier else None, manages_platform=manages)

    async def catalog(self, data: Empty) -> Catalog:
        _member()
        return Catalog(modules=list((await _module_catalog()).values()), limits=await _limit_catalog())

    # ── Planos (quem administra a plataforma) ───────────────────────────────

    async def create_plan(self, data: PlanInput) -> Plan:
        _platform_manager()
        record = {
            "slug": data.slug, "name": data.name, "description": data.description, "price": data.price,
            "currency": data.currency, "public": data.public, "is_default": data.default,
            "limits": await _checked_limits(data.limits), "modules": await _checked_modules(data.modules, {}),
        }
        try:
            row = await db.create(TIERS, record)
        except ServiceError as exc:
            if exc.code == "ERRO_RECORD_DUPLICATE":
                raise ServiceError("ERRO_PLANS_SLUG_TAKEN", f"Já existe um plano {data.slug}.", 409) from None
            raise
        if data.default:
            await _only_default(data.slug)
        return _plan(row)

    async def update_plan(self, data: PlanUpdate) -> Plan:
        _platform_manager()
        row = await _tier(data.slug)
        changes = data.model_dump(exclude={"slug", "default", "limits", "modules"}, exclude_none=True)
        if data.limits is not None:
            changes["limits"] = await _checked_limits(data.limits)
        if data.modules is not None:
            changes["modules"] = await _checked_modules(data.modules, {})
        if data.default is not None:
            changes["is_default"] = data.default
        if changes:
            row = await db.merge(row["id"], changes)
        if data.default:
            await _only_default(data.slug)
        return _plan(row)

    async def remove_plan(self, data: PlanRef) -> PlanList:
        _platform_manager()
        row = await _tier(data.slug)
        if row.get("is_default"):
            raise ServiceError("ERRO_PLANS_IN_USE", "Este é o plano padrão: marque outro como padrão antes de remover.", 409)
        using = await db.query_shared(
            "SELECT count() AS total FROM (SELECT id FROM plan_accounts WHERE plan = $slug) GROUP ALL", slug=data.slug
        )
        if using and using[0]["total"]:
            raise ServiceError(
                "ERRO_PLANS_IN_USE", f"{using[0]['total']} organização(ões) usam este plano: troque o plano delas antes.", 409
            )
        await db.delete(row["id"])
        return await self.list_plans(Empty())

    async def account(self, data: AccountRef) -> Account:
        """Pela tela: quem administra a plataforma vê o plano e o ajuste de módulos de uma organização, pelo id dela."""
        _platform_manager()
        name = await _tenant_name(data.tenant)
        tier, account = await self._plan_of(data.tenant)
        return Account(
            tenant=data.tenant, tenant_name=name, plan=tier["slug"] if tier else None, plan_name=tier["name"] if tier else NO_PLAN,
            assigned=bool(account and account.get("plan")), modules=_flags(account, "modules"),
        )

    async def assign_plan(self, data: AssignInput) -> Account:
        """Pela tela: quem administra a plataforma troca o plano (e o ajuste de módulos) de uma organização, pelo id."""
        who = _platform_manager()
        tier = await _tier(data.plan)
        name = await _tenant_name(data.tenant)
        with acting_as(system(SERVICE, data.tenant)):
            modules = await self._assign(tier, data.modules, by=who.sub)
        return Account(
            tenant=data.tenant, tenant_name=name, plan=tier["slug"], plan_name=tier["name"], assigned=True, modules=modules
        )

    async def assign(self, data: AssignRequest) -> Assigned:
        """rpc.plans.assign: o serviço de pagamentos do produto troca o plano, como tarefa da plataforma."""
        who = current()
        if who is None or not who.is_system:
            raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só tarefas da plataforma trocam o plano por aqui.", 403)
        tier = await _tier(data.plan)
        modules = await self._assign(tier, data.modules, by=who.sub)
        return Assigned(tenant=current_tenant(), plan=tier["slug"], plan_name=tier["name"], modules=modules)

    # ── Serviços (core/plans.py) ────────────────────────────────────────────

    async def resolve(self, data: LimitsRequest) -> PlanLimits:
        """rpc.plans.limits: plano da organização de quem pergunta, módulos ligados, valores de cada limite e consumo
        do mês."""
        tenant = current_tenant()
        tier, account = await self._plan_of(tenant)
        values = _values(tier)
        month = _month()
        sums = {row["name"]: row["used"] for row in await db.query(
            "SELECT name, used FROM plan_usage WHERE tenant = $tenant AND month = $month", month=month
        )}
        totals = {row["name"]: row["total"] for row in await db.query("SELECT name, total FROM plan_counts WHERE tenant = $tenant")}
        states = [
            LimitState(
                **limit.model_dump(),
                limit=values[limit.name] if limit.name in values else limit.default,
                used=sums.get(limit.name, 0.0) if limit.monthly else totals.get(limit.name, 0),
            )
            for limit in await _limit_catalog()
        ]
        situacao = (account or {}).get("situacao") or "ativa"
        return PlanLimits(
            plan=tier["slug"] if tier else None, plan_name=tier["name"] if tier else NO_PLAN, month=month, limits=states,
            modules=_module_states(await _module_catalog(), tier, account), situacao=situacao, aviso=_aviso(account),
        )

    async def record_catalog(self, data: ModuleCatalog) -> Empty:
        """events.plans.catalog: o módulo e os limites que um serviço declarou no boot."""
        module = data.module
        await db.query_shared(
            "UPSERT $id SET name = $name, service = $service, title = $title, description = $description, "
            "category = $category, is_core = $core, default_enabled = $default, requires = $requires",
            id=RecordID(MODULE_CATALOG, module.name), name=module.name, service=data.service, title=module.title,
            description=module.description, category=module.category, core=module.core, default=module.default,
            requires=module.requires,
        )
        for limit in data.limits:
            await db.query_shared(
                "UPSERT $id SET name = $name, service = $service, description = $description, default_value = $default, "
                "monthly = $monthly, unit = $unit, currency = $currency",
                id=RecordID("plan_limits", limit.name), name=limit.name, service=data.service, description=limit.description,
                default=limit.default, monthly=limit.monthly, unit=limit.unit, currency=limit.currency,
            )
        await db.query_shared(  # o que saiu da lista do serviço sai do catálogo
            "DELETE plan_limits WHERE service = $service AND name NOT IN $names",
            service=data.service, names=[limit.name for limit in data.limits],
        )
        return Empty()

    async def record_usage(self, data: UsageReport) -> UsageChanged:
        """events.plans.usage: soma no mês da organização de quem consumiu, uma vez por mensagem."""
        message = bus.message_id() or uuid.uuid4().hex
        params = {"message": message, "name": data.name, "month": data.month, "amount": data.amount}
        try:
            row = await db.query(_ADD_USAGE, **params)
        except ServiceError as exc:
            if exc.code != "ERRO_RECORD_DUPLICATE":
                raise
            seen = await db.query("SELECT id FROM plan_usage_log WHERE tenant = $tenant AND message = $message", message=message)
            if not seen:
                raise  # duas mensagens criaram a soma do mês ao mesmo tempo: a reentrega do NATS soma esta
            row = (await db.query(
                "SELECT * FROM plan_usage WHERE tenant = $tenant AND name = $name AND month = $month", name=data.name, month=data.month
            ))[0]
            return UsageChanged(name=data.name, used=row["used"])  # reentrega: já somado e avisado
        changed = UsageChanged(name=data.name, used=row["used"])
        await bus.live(USAGE_LIVE, changed)  # a tela Plano aberta atualiza sozinha
        await self._alert(row)
        return changed

    async def record_count(self, data: CountReport) -> UsageChanged:
        """events.plans.count: o total que o serviço informou, se for mais novo que o guardado."""
        params = {"name": data.name, "total": data.total, "at": data.at}
        updated = await db.query(
            "UPDATE plan_counts SET total = $total, at = $at WHERE tenant = $tenant AND name = $name AND at < $at RETURN AFTER",
            **params,
        )
        if not updated:
            older = await db.query("SELECT total FROM plan_counts WHERE tenant = $tenant AND name = $name", name=data.name)
            if older:
                return UsageChanged(name=data.name, used=older[0]["total"])  # chegou depois de um total mais novo
            await db.create(COUNTS, params)
        changed = UsageChanged(name=data.name, used=data.total)
        await bus.live(USAGE_LIVE, changed)
        return changed

    # ── Conta: mensalidade, situação e cancelamento ────────────────────────

    async def cancelar(self, data: CancelamentoIn) -> Conta:
        """O dono pede o cancelamento: tudo funciona até o fim do mês pago; na data, a conta encerra."""
        who = _owner()
        row = await _account_row(who.tenant)
        if row.get("situacao") == "encerrada" or row.get("cancelamento"):
            raise ServiceError("ERRO_PLANS_JA_CANCELADA", "O cancelamento já foi pedido.", 409)
        efetivo = _fim_do_mes()
        await db.merge(row["id"], {"cancelamento": {"pedido_em": _now(), "por": who.sub, "origem": "cliente", "motivo": data.motivo,
                                                    "efetivo_em": efetivo}})
        nome = await _tenant_name(who.tenant)
        with acting_as(system(SERVICE, who.tenant)):
            await notify.user(who.sub, "Cancelamento pedido",
                              f"A conta de {nome} funciona até {_dia(efetivo - timedelta(days=1))}, o fim do mês pago. Depois disso, "
                              f"os dados ficam {DIAS_ATE_EXCLUIR} dias para baixar em Plano, e você pode desfazer até lá.",
                              link="/plano", action="Ver plano", key=f"cancelamento-{who.tenant}")
        await _avisar_gestores(f"{nome} pediu o cancelamento", f"Encerra em {_dia(efetivo)}." + (f" Motivo: {data.motivo}" if data.motivo else ""),
                               key=f"cancelamento-{who.tenant}")
        return await _conta(who.tenant)

    async def desfazer_cancelamento(self, data: Empty) -> Conta:
        """O dono desfaz o cancelamento que pediu: antes da data, como se não tivesse pedido; depois, reativa (até a
        exclusão). As conexões desligadas no encerramento precisam ser refeitas."""
        who = _owner()
        row = await _account_row(who.tenant)
        if not _pode_desfazer(row):
            raise ServiceError("ERRO_PLANS_SEM_CANCELAMENTO", "Não há cancelamento seu para desfazer.", 409)
        await _desfazer(row)
        await _avisar_gestores(f"{await _tenant_name(who.tenant)} desfez o cancelamento", "A conta segue ativa.",
                               key=f"desfeito-{who.tenant}-{_now():%Y%m%d%H%M}")
        return await _conta(who.tenant)

    async def conta(self, data: ContaAcao) -> Conta:
        """rpc.plans.conta (só o svc-staff, agindo na organização do cliente; o svc-staff confere que é o gestor)."""
        who = current()
        if who is None or who.sub != f"system:{STAFF_SERVICE}":
            raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só o svc-staff muda a conta de um cliente.", 403)
        org = current_tenant()
        if org == settings().platform_tenant:
            raise ServiceError("ERRO_PLANS_PLATAFORMA", "A conta da Cogniventure não se cobra nem se suspende.", 409)
        if data.acao == "ver":
            return await _conta(org)
        await _tenant_name(org)  # organização inexistente → 404
        row = await _account_row(org)
        situacao = row.get("situacao") or "ativa"
        if data.acao == "cobranca":
            changes: dict[str, Any] = {}
            if data.valor is not None:
                changes["valor"] = round(data.valor, 2)
            if data.vencimento is not None:
                changes["vencimento"] = data.vencimento
            if changes:
                await db.merge(row["id"], changes)
        elif data.acao == "suspender":
            if situacao != "ativa":
                raise ServiceError("ERRO_PLANS_SITUACAO", f"A conta está {situacao}: só a ativa se suspende.", 409)
            if not data.motivo:
                raise ServiceError("ERRO_PLANS_MOTIVO", "Diga o motivo da suspensão (o cliente vê).", 422)
            await db.merge(row["id"], {"situacao": "suspensa", "suspensa_em": _now(), "motivo": data.motivo, "suspensa_por": data.por})
            await _avisar_cliente(org, "Conta suspensa", f"{data.motivo}\n\nEnquanto isso, nenhuma execução nova começa: as que estão em "
                                  "andamento terminam. Fale com a Cogniventure para regularizar.", key=f"suspensa-{org}-{_now():%Y%m%d%H%M}")
        elif data.acao == "reativar":
            if situacao != "suspensa":
                raise ServiceError("ERRO_PLANS_SITUACAO", f"A conta está {situacao}: só a suspensa se reativa por aqui.", 409)
            await db.merge(row["id"], {"situacao": "ativa", "suspensa_em": None, "motivo": None})
            await _avisar_cliente(org, "Conta reativada", "As execuções voltam a começar normalmente.", key=f"reativada-{org}-{_now():%Y%m%d%H%M}")
        elif data.acao == "encerrar":
            if situacao == "encerrada" or row.get("cancelamento"):
                raise ServiceError("ERRO_PLANS_JA_CANCELADA", "O encerramento já foi pedido.", 409)
            agora = situacao == "suspensa"  # suspensa por atraso: o mês não foi pago, encerra na hora
            efetivo = _now() if agora else _fim_do_mes()
            await db.merge(row["id"], {"cancelamento": {"pedido_em": _now(), "por": data.por, "origem": "cogniventure",
                                                        "motivo": data.motivo, "efetivo_em": efetivo}})
            if agora:
                await _encerrar(await _account_row(org))
            else:
                await _avisar_cliente(org, "A Cogniventure encerrou a conta",
                                      f"A conta funciona até {_dia(efetivo - timedelta(days=1))}, o fim do mês pago."
                                      + (f"\n\nMotivo: {data.motivo}" if data.motivo else ""), key=f"encerrar-{org}")
        elif data.acao == "desfazer":
            if not (row.get("cancelamento") or situacao == "encerrada"):
                raise ServiceError("ERRO_PLANS_SEM_CANCELAMENTO", "Não há cancelamento para desfazer.", 409)
            await _desfazer(row)
        return await _conta(org)

    async def fechar_mes(self, data: FechamentoIn) -> Fechamento:
        """O fechamento do mês (agendado no dia 1, ou pelo gestor da plataforma): cada cliente pagante inicia o
        Faturamento e cobrança publicado na organização da Cogniventure, com quem paga, o e-mail do dono, o valor e o
        vencimento. A mesma organização no mesmo mês não inicia duas vezes."""
        who = current()
        if who is not None and not who.is_system:
            _platform_manager()
        platform = settings().platform_tenant
        mes = data.mes or _hoje().strftime("%Y-%m")
        if not platform:
            return Fechamento(mes=mes, cobrados=[])
        cobrados: list[Cobrado] = []
        sem_processo = False
        for row in await db.query_shared("SELECT * FROM plan_accounts WHERE org != $p ORDER BY org", p=platform):
            if (row.get("situacao") or "ativa") == "encerrada":
                continue
            tier, _ = await self._plan_of(row["org"])
            valor = _valor(row, tier)
            if valor <= 0:
                continue
            ano, mes_n = (int(x) for x in mes.split("-"))
            vence = date(ano, mes_n, int(row.get("vencimento") or VENCIMENTO_PADRAO))
            with acting_as(system(SERVICE, row["org"])):
                try:
                    contatos = await bus.request(CONTACTS_SUBJECT, ContactsRequest(roles=["owner"]), Contacts, timeout=5)
                except (TimeoutError, NoRespondersError):
                    cobrados.append(Cobrado(tenant=row["org"], nome=row["org"], valor=valor, vencimento=vence.isoformat(),
                                            erro="svc-identity fora do ar: tente de novo"))
                    continue
            nome = contatos.tenant_name or row["org"]
            plano = f" (plano {tier['name']})" if tier else ""
            dados = {"cliente": nome, "email": contatos.items[0].email if contatos.items else None,
                     "descricao": f"Mensalidade da Cogniventure de {_mes_br(mes)}{plano}", "valor": valor,
                     "vencimento": vence.isoformat(), "cliente_org": row["org"], "mes": mes}
            item = Cobrado(tenant=row["org"], nome=nome, valor=valor, vencimento=vence.isoformat())
            with acting_as(system(SERVICE, platform)):
                try:
                    iniciada = await bus.request(INICIAR_MODELO_SUBJECT, IniciarModelo(
                        modelo=FATURAMENTO_MODELO, dados=dados, chave=f"plano-{row['org']}-{mes}", resumo=f"{nome}: mensalidade de {_mes_br(mes)}",
                    ), ExecucaoIniciada, timeout=30)
                    item.execucao = iniciada.id
                except ServiceError as exc:
                    item.erro = exc.message
                    sem_processo = sem_processo or exc.code == "ERRO_PROCESSOS_SEM_PUBLICADA"
                except (TimeoutError, NoRespondersError):
                    item.erro = "svc-processos fora do ar: rode o fechamento de novo (o mesmo mês não cobra duas vezes)"
            cobrados.append(item)
        falhas = [c for c in cobrados if c.erro]
        if falhas:
            texto = ("Publique o Faturamento e cobrança na organização da Cogniventure e rode o fechamento de novo."
                     if sem_processo else "; ".join(f"{c.nome}: {c.erro}" for c in falhas[:5]))
            await _avisar_gestores(f"Fechamento de {_mes_br(mes)}: {len(falhas)} cliente(s) sem cobrança", texto, key=f"fechamento-{mes}-{len(falhas)}")
        return Fechamento(mes=mes, cobrados=cobrados)

    async def encerramentos(self, data: Empty) -> Encerramentos:
        """Agendado (todo dia, logo depois da meia-noite de Brasília): encerra as contas cujo mês pago acabou e apaga de
        vez as encerradas há 30 dias (de todos os serviços, pelo events.plans.exclusao, e dos arquivos)."""
        encerradas = excluidas = 0
        agora = _now()
        for row in await db.query_shared("SELECT * FROM plan_accounts WHERE cancelamento != NONE AND situacao != 'encerrada'"):
            if _quando(row["cancelamento"]["efetivo_em"]) <= agora:
                await _encerrar(row)
                encerradas += 1
        for row in await db.query_shared("SELECT * FROM plan_accounts WHERE situacao = 'encerrada' AND exclusao_em <= $agora", agora=agora):
            await _excluir(row)
            excluidas += 1
        return Encerramentos(encerradas=encerradas, excluidas=excluidas)

    # ── Exportação dos dados (o dono baixa um pacote) ───────────────────────

    async def pedir_exportacao(self, data: Empty) -> Exportacao:
        """O dono pede o pacote dos dados (JSON e CSV de cada cadastro, execução e versão, mais os arquivos): fica pronto
        em segundo plano, e ele é avisado."""
        who = _owner()
        rows = await db.query("SELECT * FROM plan_exports WHERE tenant = $tenant AND status = 'preparando' LIMIT 1")
        if rows:
            return _exportacao(rows[0])
        row = await db.create(EXPORTS, {"status": "preparando", "pedido_por": who.sub})
        from workflows import ExportarWorkflow  # o workflow importa este módulo

        await runner.start_workflow(ExportarWorkflow.run, ExportacaoRef(id=_key(row["id"])), task_queue=TASK_QUEUE, id=f"exportar-{_key(row['id'])}")
        return _exportacao(row)

    async def exportacao(self, data: Empty) -> ExportacaoAtual:
        """O último pacote pedido, com o link para baixar quando pronto."""
        _owner()
        rows = await db.query("SELECT * FROM plan_exports WHERE tenant = $tenant ORDER BY created_at DESC LIMIT 1")
        return ExportacaoAtual(item=_exportacao(rows[0]) if rows else None)

    async def exportar(self, data: ExportacaoRef) -> Exportacao:
        """Activity: monta o zip na organização de quem pediu (cada serviço entrega as linhas dele por rpc.<serviço>.dados;
        os arquivos vêm do armazenamento), guarda e avisa. Os pacotes anteriores saem."""
        org = current_tenant()
        pedido = await db.select(f"{EXPORTS}:{data.id}")
        if pedido is None:
            raise ServiceError("ERRO_PLANS_NOT_FOUND", "Exportação não encontrada.", 404)
        fora: list[str] = []
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temporario:
            caminho = temporario.name
        try:
            with acting_as(system(SERVICE, org)):
                nome = await _tenant_name(org)
                servicos = sorted({m.service for m in (await _module_catalog()).values()} | {SERVICE})
                with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as pacote:
                    tabelas = 0
                    for servico in servicos:
                        try:
                            tabelas += await _exportar_servico(pacote, servico)
                        except (TimeoutError, NoRespondersError):
                            fora.append(servico)
                    arquivos = await _exportar_arquivos(pacote, org)
                    pacote.writestr("LEIA-ME.txt", _leia_me(nome, tabelas, arquivos, fora))
                antigos = await db.query("SELECT * FROM plan_exports WHERE tenant = $tenant AND id != $id AND chave != NONE", id=_rid(pedido["id"]))
                salvo = await storage.save_file(caminho, filename=f"dados-{_hoje():%Y-%m-%d}.zip", content_type="application/zip", folder="exportacoes")
                for antigo in antigos:
                    await storage.delete(antigo["chave"])
                    await db.delete(antigo["id"])
        except Exception:
            await db.merge(pedido["id"], {"status": "falhou", "aviso": "Não foi possível montar o pacote: peça de novo em alguns minutos."})
            raise
        finally:
            if os.path.exists(caminho):
                os.remove(caminho)
        aviso = f"Fora do ar no momento, ficaram de fora: {', '.join(fora)}. Peça de novo mais tarde." if fora else None
        row = await db.merge(pedido["id"], {"status": "pronta", "pronta_em": _now(), "chave": salvo.key, "tamanho": salvo.size, "aviso": aviso})
        with acting_as(system(SERVICE, org)):
            await notify.user(pedido.get("pedido_por") or [], "Os dados da organização estão prontos",
                              "O pacote (JSON e CSV, mais os arquivos) está em Plano para baixar.", link="/plano",
                              action="Baixar", key=f"exportacao-{data.id}")
        return _exportacao(row)

    # ── Manutenção (agendamento diário) ─────────────────────────────────────

    async def cleanup(self, data: Empty) -> Cleaned:
        before = _now() - timedelta(days=KEEP_LOG_DAYS)
        oldest = _month(_now() - timedelta(days=31 * KEEP_MONTHS))
        removed_log = removed_usage = 0
        for org in await db.tenants(USAGE_LOG):
            with acting_as(system(SERVICE, org)):
                gone = await db.query(
                    "DELETE plan_usage_log WHERE tenant = $tenant AND created_at < $before RETURN BEFORE", before=before
                )
                removed_log += len(gone or [])
        for org in await db.tenants(USAGE):
            with acting_as(system(SERVICE, org)):
                gone = await db.query("DELETE plan_usage WHERE tenant = $tenant AND month < $oldest RETURN BEFORE", oldest=oldest)
                removed_usage += len(gone or [])
        return Cleaned(usage_log=removed_log, usage=removed_usage)

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _plan_of(self, org: str) -> tuple[dict | None, dict | None]:
        """Plano em vigor (o atribuído ou, sem ele, o padrão; None: sem plano, valem os defaults) e a linha da
        organização em plan_accounts (o ajuste de módulos), se houver."""
        accounts = await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org)
        account = accounts[0] if accounts else None
        if account and account.get("plan"):  # a conta pode existir sem plano atribuído (cancelamento, mensalidade)
            rows = await db.query_shared("SELECT * FROM plan_tiers WHERE slug = $slug", slug=account["plan"])
            if rows:
                return rows[0], account
        rows = await db.query_shared("SELECT * FROM plan_tiers WHERE is_default = true ORDER BY slug LIMIT 1")
        return (rows[0] if rows else None), account

    async def _assign(self, tier: dict, modules: dict[str, bool] | None, *, by: str) -> dict[str, bool]:
        """Troca o plano da organização atual (e o ajuste de módulos, se veio) e recomeça os patamares de aviso do
        mês. Devolve o ajuste que ficou."""
        org = current_tenant()
        rows = await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org)
        own = _flags(rows[0] if rows else None, "modules") if modules is None else modules
        stored = await _checked_modules(own, _flags(tier, "modules"))
        record = {"plan": tier["slug"], "modules": stored, "assigned_by": by}
        if rows:
            await db.merge(rows[0]["id"], record)
        else:
            await db.create(ACCOUNTS, {"org": org, **record})
        await db.query("UPDATE plan_usage SET alerted = 0 WHERE tenant = $tenant AND month = $month", month=_month())
        return {item["name"]: item["enabled"] for item in stored}

    async def _alert(self, row: dict) -> None:
        """Avisa donos e administradores ao cruzar 80% e 100% de um limite mensal (uma vez por mês e por patamar)."""
        if row["month"] != _month() or row.get("alerted", 0) >= ALERTS[0]:
            return
        tier, _ = await self._plan_of(current_tenant())
        catalog = await db.query_shared("SELECT * FROM plan_limits WHERE name = $name", name=row["name"])
        if not catalog:
            return
        limit = _catalog(catalog[0])
        values = _values(tier)
        value = values[limit.name] if limit.name in values else limit.default
        if not value:  # sem limite (None) ou fora do plano (0): nada a avisar
            return
        reached = next((threshold for threshold in ALERTS if row["used"] >= value * threshold / 100), None)
        if reached is None or row.get("alerted", 0) >= reached:
            return
        claimed = await db.query(
            "UPDATE plan_usage SET alerted = $level WHERE tenant = $tenant AND id = $id AND alerted < $level RETURN AFTER",
            id=_rid(row["id"]), level=reached,
        )
        if not claimed:
            return  # outra mensagem já avisou este patamar
        plan = tier["name"] if tier else NO_PLAN
        ending = (
            "O limite foi atingido: o uso fica bloqueado até o mês que vem ou até a troca de plano."
            if reached >= 100
            else "Ao chegar a 100%, o uso fica bloqueado até o mês que vem ou até a troca de plano."
        )
        await notify.roles(
            "owner", "admin",
            title=f"{limit.description[:90]}: {reached}% do limite",
            body=f"A organização usou {reached}% do que o plano {plan} permite neste mês.\n\n{ending}",
            link="/plano",
            action="Ver plano",
            key=f"plano-{limit.name}-{row['month']}-{reached}",
        )


# ── Conta: helpers ──────────────────────────────────────────────────────────

async def _account_row(org: str) -> dict:
    """A linha da organização em plan_accounts; sem ela (nunca teve plano atribuído), cria uma sem plano (vale o padrão)."""
    rows = await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org)
    if rows:
        return rows[0]
    try:
        return await db.create(ACCOUNTS, {"org": org, "plan": None, "modules": [], "assigned_by": (current() or system(SERVICE)).sub})
    except ServiceError as exc:
        if exc.code != "ERRO_RECORD_DUPLICATE":
            raise
        return (await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org))[0]


async def _conta(org: str) -> Conta:
    rows = await db.query_shared("SELECT * FROM plan_accounts WHERE org = $org", org=org)
    row = rows[0] if rows else {}
    accounts = await db.query_shared("SELECT * FROM plan_tiers WHERE slug = $slug", slug=row.get("plan") or "")
    tier = accounts[0] if accounts else ((await db.query_shared("SELECT * FROM plan_tiers WHERE is_default = true ORDER BY slug LIMIT 1")) or [None])[0]
    cancelamento = row.get("cancelamento")
    return Conta(
        tenant=org, situacao=row.get("situacao") or "ativa", valor=_valor(row, tier), valor_combinado=row.get("valor") is not None,
        moeda=(tier or {}).get("currency") or "BRL", vencimento=int(row.get("vencimento") or VENCIMENTO_PADRAO),
        suspensa_em=row.get("suspensa_em"), motivo=row.get("motivo"),
        cancelamento=Cancelamento.model_validate(cancelamento) if cancelamento else None,
        encerrada_em=row.get("encerrada_em"), exclusao_em=row.get("exclusao_em"), aviso=_aviso(row), pode_desfazer=_pode_desfazer(row),
    )


def _valor(row: dict | None, tier: dict | None) -> float:
    """A mensalidade: a combinada com o cliente ou, sem ela, o preço do plano."""
    if row and row.get("valor") is not None:
        return float(row["valor"])
    return float((tier or {}).get("price") or 0)


def _aviso(row: dict | None) -> str | None:
    """O que a organização vê no workspace e em Plano sobre a conta."""
    if not row:
        return None
    situacao = row.get("situacao") or "ativa"
    if situacao == "encerrada":
        quando = _quando(row["exclusao_em"]) if row.get("exclusao_em") else None
        return ("Conta encerrada: nenhuma execução nova começa. "
                + (f"Os dados ficam disponíveis para baixar em Plano até {_dia(quando)}." if quando else ""))
    if situacao == "suspensa":
        return "Conta suspensa: nenhuma execução nova começa até a regularização. Fale com a Cogniventure."
    if row.get("cancelamento"):
        efetivo = _quando(row["cancelamento"]["efetivo_em"])
        return f"Cancelamento pedido: a conta funciona até {_dia(efetivo - timedelta(days=1))}, o fim do mês pago."
    return None


def _pode_desfazer(row: dict) -> bool:
    """O dono desfaz o que ele pediu: o cancelamento ainda não efetivo ou a conta encerrada, até a exclusão."""
    cancelamento = row.get("cancelamento") or {}
    return cancelamento.get("origem") == "cliente" and (row.get("situacao") != "encerrada" or bool(row.get("exclusao_em")))


async def _desfazer(row: dict) -> None:
    org = row["org"]
    encerrada = row.get("situacao") == "encerrada"
    await db.merge(row["id"], {"cancelamento": None, "situacao": "ativa" if encerrada else row.get("situacao") or "ativa",
                               "encerrada_em": None, "exclusao_em": None})
    texto = ("A conta voltou a funcionar. As conexões desligadas no encerramento (banco, e-mail, webhooks) precisam ser "
             "refeitas, e a Cogniventure volta a acompanhar." if encerrada else "O cancelamento foi desfeito: a conta segue normalmente.")
    await _avisar_cliente(org, "Conta reativada" if encerrada else "Cancelamento desfeito", texto, key=f"desfeito-{org}-{_now():%Y%m%d%H%M}")


async def _encerrar(row: dict) -> None:
    """O mês pago acabou (ou a Cogniventure encerrou a suspensa): nenhuma execução nova, os dados ficam 30 dias e
    cada serviço desliga o que é da organização (events.plans.encerrada)."""
    org, agora = row["org"], _now()
    exclusao = agora + timedelta(days=DIAS_ATE_EXCLUIR)
    await db.merge(row["id"], {"situacao": "encerrada", "encerrada_em": agora, "exclusao_em": exclusao})
    with acting_as(system(SERVICE, org)):
        await bus.publish(ENCERRADA_SUBJECT, ContaEncerrada(tenant=org, em=agora), msg_id=f"encerrada-{org}-{agora:%Y%m%d}")
    await _avisar_cliente(org, "Conta encerrada",
                          f"Nenhuma execução nova começa, e as conexões foram desligadas. Os dados ficam disponíveis para baixar em "
                          f"Plano até {_dia(exclusao)}; depois disso, são apagados de vez.", key=f"encerrada-{org}-{agora:%Y%m%d}")
    await _avisar_gestores(f"Conta encerrada: {await _tenant_name_or(org)}", f"Os dados saem de vez em {_dia(exclusao)}.",
                           key=f"encerrada-{org}-{agora:%Y%m%d}")


async def _excluir(row: dict) -> None:
    """30 dias depois do encerramento: cada serviço apaga as linhas da organização (events.plans.exclusao), os arquivos
    saem do armazenamento e a conta sai daqui."""
    org = row["org"]
    nome = await _tenant_name_or(org)
    with acting_as(system(SERVICE, org)):
        await bus.publish(PURGE_SUBJECT, PurgeRequest(tenant=org), msg_id=f"exclusao-{org}")
        await storage.purge()
    await db.delete(row["id"])
    await _avisar_gestores(f"Dados apagados: {nome}", "A organização encerrada há 30 dias saiu de vez da plataforma.", key=f"excluida-{org}")


async def _avisar_cliente(org: str, titulo: str, texto: str, *, key: str) -> None:
    with acting_as(system(SERVICE, org)):
        await notify.roles("owner", "admin", title=titulo, body=texto, link="/plano", action="Ver plano", key=key)


async def _avisar_gestores(titulo: str, texto: str, *, key: str) -> None:
    """Dono e admin da Cogniventure (os gestores do staff)."""
    platform = settings().platform_tenant
    if not platform:
        return
    with acting_as(system(SERVICE, platform)):
        await notify.roles("owner", "admin", title=titulo[:120], body=texto, link="/staff?aba=clientes", action="Ver clientes", key=key)


async def _tenant_name_or(org: str) -> str:
    try:
        return await _tenant_name(org)
    except (ServiceError, TimeoutError, NoRespondersError):
        return org


async def _exportar_servico(pacote: zipfile.ZipFile, servico: str) -> int:
    """As tabelas de um serviço, cada uma em JSON e em CSV. Devolve quantas tinham linhas."""
    subject = f"rpc.{servico.removeprefix('svc-')}.dados"
    lista = await bus.request(subject, DataRequest(), DataPage, timeout=10)
    com_linhas = 0
    for tabela in lista.tables:
        linhas: list[dict[str, Any]] = []
        start: int | None = 0
        while start is not None:
            pagina = await bus.request(subject, DataRequest(table=tabela, start=start), DataPage, timeout=30)
            linhas += pagina.rows
            start = pagina.next
        if not linhas:
            continue
        com_linhas += 1
        pasta = servico.removeprefix("svc-")
        pacote.writestr(f"{pasta}/{tabela}.json", json.dumps(linhas, ensure_ascii=False, indent=1, default=str))
        pacote.writestr(f"{pasta}/{tabela}.csv", _csv(linhas))
    return com_linhas


async def _exportar_arquivos(pacote: zipfile.ZipFile, org: str) -> int:
    """Os arquivos guardados da organização (documentos recebidos, conhecimento, logo), menos os pacotes anteriores."""
    total = 0
    for key in await storage.keys():
        partes = key.split("/")  # t/<org>/<serviço>/<pasta>/<id>
        if len(partes) != 5 or partes[2] == SERVICE:
            continue
        info = await storage.info(key)
        destino = f"arquivos/{partes[2].removeprefix('svc-')}/{partes[3]}/{partes[4][:8]}-{info.filename}"
        if info.size > EXPORT_FILE_BYTES:
            pacote.writestr(destino + ".txt", f"Arquivo de {info.size} bytes, grande demais para o pacote: peça à Cogniventure.")
        else:
            pacote.writestr(destino, await storage.read(key, max_bytes=EXPORT_FILE_BYTES))
        total += 1
    return total


def _csv(linhas: list[dict[str, Any]]) -> str:
    """Uma coluna por campo (o que é lista ou objeto vai como JSON), com BOM para o Excel reconhecer o UTF-8."""
    colunas = list(dict.fromkeys(k for linha in linhas for k in linha))
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(colunas)
    for linha in linhas:
        escritor.writerow([json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, dict | list) else ("" if v is None else v)
                           for v in (linha.get(c) for c in colunas)])
    return "\ufeff" + saida.getvalue()


def _leia_me(nome: str, tabelas: int, arquivos: int, fora: list[str]) -> str:
    texto = (f"Dados de {nome}, exportados em {_dia(_now())}.\n\n"
             f"Cada pasta é um módulo da plataforma; cada tabela vem em JSON (completa) e em CSV (uma coluna por campo).\n"
             f"Tabelas com dados: {tabelas}. Arquivos: {arquivos}, na pasta arquivos/.\n"
             "Datas em UTC (ISO 8601). Vetores de busca ficam de fora; texto muito longo vem cortado, e o arquivo original vem junto.\n")
    if fora:
        texto += f"\nFora do ar no momento da exportação (ficaram de fora): {', '.join(fora)}.\n"
    return texto


def _exportacao(row: dict) -> Exportacao:
    url = None
    if row.get("status") == "pronta" and row.get("chave"):
        url = storage.url(row["chave"], ttl=600, filename=f"dados-{_quando(row['pronta_em']):%Y-%m-%d}.zip", content_type="application/zip")
    return Exportacao(id=_key(row["id"]), status=row["status"], created_at=row.get("created_at"), pronta_em=row.get("pronta_em"),
                      tamanho=row.get("tamanho"), url=url, aviso=row.get("aviso"))


def _owner() -> Principal:
    """O dono da organização (que não seja a Cogniventure): cancela, desfaz e exporta."""
    who = _member()
    if "owner" not in who.roles:
        raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só o dono da organização pede o cancelamento e a exportação.", 403)
    if who.tenant == settings().platform_tenant:
        raise ServiceError("ERRO_PLANS_PLATAFORMA", "A organização da Cogniventure não se cancela por aqui.", 409)
    return who


def _fim_do_mes() -> datetime:
    """A meia-noite (Brasília) do primeiro dia do mês seguinte: quando acaba o mês pago."""
    hoje = _hoje()
    seguinte = date(hoje.year + (hoje.month == 12), hoje.month % 12 + 1, 1)
    return datetime(seguinte.year, seguinte.month, 1, tzinfo=ZoneInfo(FUSO)).astimezone(UTC)


def _hoje() -> date:
    return _now().astimezone(ZoneInfo(FUSO)).date()


def _dia(quando: datetime) -> str:
    return quando.astimezone(ZoneInfo(FUSO)).strftime("%d/%m/%Y")


_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _mes_br(mes: str) -> str:
    ano, numero = mes.split("-")
    return f"{_MESES[int(numero) - 1]} de {ano}"


def _quando(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def _key(record_id: Any) -> str:
    return str(record_id).partition(":")[2].strip("⟨⟩`") if ":" in str(record_id) else str(record_id)


async def _tier(slug: str) -> dict:
    rows = await db.query_shared("SELECT * FROM plan_tiers WHERE slug = $slug", slug=slug)
    if not rows:
        raise ServiceError("ERRO_PLANS_NOT_FOUND", "Plano não encontrado.", 404)
    return rows[0]


async def _only_default(slug: str) -> None:
    await db.query_shared("UPDATE plan_tiers SET is_default = false WHERE is_default = true AND slug != $slug", slug=slug)


async def _checked_limits(limits: dict[str, float | None]) -> list[dict[str, Any]]:
    """Só limites do catálogo; guardados como lista de { name, value } (o nome tem ponto: não serve de chave)."""
    known = set(await db.query_shared("SELECT VALUE name FROM plan_limits WHERE name IN $names", names=list(limits)))
    if unknown := sorted(set(limits) - known):
        raise ServiceError("ERRO_PLANS_UNKNOWN_LIMIT", f"Limite fora do catálogo: {', '.join(unknown)}.", 422)
    return [{"name": name, "value": value} for name, value in sorted(limits.items())]


async def _checked_modules(modules: dict[str, bool], base: dict[str, bool]) -> list[dict[str, Any]]:
    """Só módulos do catálogo; os da plataforma ficam sempre ligados (ligar é ignorado, desligar é erro). Quem fica
    ligado precisa dos requires ligados, contando base (o plano, para o ajuste de uma organização) e os defaults."""
    catalog = await _module_catalog()
    if unknown := sorted(set(modules) - set(catalog)):
        raise ServiceError("ERRO_PLANS_UNKNOWN_MODULE", f"Módulo fora do catálogo: {', '.join(unknown)}.", 422)
    if core := sorted(catalog[name].title for name, on in modules.items() if catalog[name].core and not on):
        raise ServiceError("ERRO_PLANS_CORE_MODULE", f"{', '.join(core)}: módulo da plataforma, sempre ligado.", 422)
    chosen = {name: module.core or modules.get(name, base.get(name, module.default)) for name, module in catalog.items()}
    for name in sorted(name for name, on in modules.items() if on):  # quem liga precisa dos requires ligados
        if missing := [required for required in catalog[name].requires if not chosen.get(required, False)]:
            titles = ", ".join(catalog[required].title if required in catalog else required for required in missing)
            raise ServiceError(
                "ERRO_PLANS_MODULE_REQUIRES", f"{catalog[name].title} precisa de {titles}: ligue também ou desligue {catalog[name].title}.", 422
            )
    for name in sorted(name for name, on in modules.items() if not on):  # quem desliga não pode faltar a um ligado
        if needed_by := [catalog[other].title for other in catalog if chosen[other] and name in catalog[other].requires]:
            raise ServiceError(
                "ERRO_PLANS_MODULE_REQUIRES", f"{', '.join(needed_by)} precisa de {catalog[name].title}: desligue também ou mantenha ligado.", 422
            )
    return [{"name": name, "enabled": on} for name, on in sorted(modules.items()) if not catalog[name].core]


def _module_states(catalog: dict[str, CatalogModule], tier: dict | None, account: dict | None) -> list[ModuleState]:
    """Ligado: módulo da plataforma; senão o ajuste da organização, o plano ou o default. E só com os requires ligados
    (requisito fora do catálogo, não instalado, desliga quem depende dele)."""
    plan, own = _flags(tier, "modules"), _flags(account, "modules")
    chosen = {name: module.core or own.get(name, plan.get(name, module.default)) for name, module in catalog.items()}
    effective: dict[str, bool] = {}

    def on(name: str, path: tuple[str, ...] = ()) -> bool:
        if name in effective:
            return effective[name]
        if not chosen.get(name, False) or name in path:  # fora do catálogo, desligado ou dependência circular
            return False
        effective[name] = all(on(required, (*path, name)) for required in catalog[name].requires)
        return effective[name]

    return [ModuleState(**module.model_dump(), enabled=on(name)) for name, module in catalog.items()]


async def _module_catalog() -> dict[str, CatalogModule]:
    """Os módulos que os serviços declararam; numa instalação dedicada (MODULES), só os da plataforma e os instalados."""
    rows = await db.query_shared("SELECT * FROM plan_modules ORDER BY category, title")
    chosen = settings().installed()
    return {row["name"]: _module(row) for row in rows if chosen is None or row.get("is_core") or row["name"] in chosen}


async def _limit_catalog() -> list[CatalogLimit]:
    return [_catalog(row) for row in await db.query_shared("SELECT * FROM plan_limits ORDER BY name")]


async def _tenant_name(tenant: str) -> str:
    """Nome da organização pelo svc-identity; inexistente → 404."""
    with acting_as(system(SERVICE, tenant)):
        found = await bus.request(CONTACTS_SUBJECT, ContactsRequest(), Contacts, timeout=5)
    if not found.tenant_name:
        raise ServiceError("ERRO_PLANS_TENANT_NOT_FOUND", "Organização não encontrada.", 404)
    return found.tenant_name


def _flags(row: dict | None, field: str) -> dict[str, bool]:
    """Lista de { name, enabled } (módulos do plano ou o ajuste da organização) → módulo → ligado."""
    return {item["name"]: bool(item["enabled"]) for item in (row or {}).get(field) or []}


def _values(tier: dict | None) -> dict[str, float | None]:
    """Limites que o plano cita. Sem value (o banco não guarda nulo dentro do objeto): sem limite."""
    return {item["name"]: item.get("value") for item in (tier or {}).get("limits", [])}


def _plan(row: dict) -> Plan:
    return Plan(
        slug=row["slug"], name=row["name"], description=row.get("description", ""), price=row["price"],
        currency=row["currency"], public=row["public"], default=bool(row.get("is_default")), limits=_values(row),
        modules=_flags(row, "modules"),
    )


def _catalog(row: dict) -> CatalogLimit:
    return CatalogLimit(
        name=row["name"], service=row["service"], description=row["description"], default=row.get("default_value"),
        monthly=row["monthly"], unit=row.get("unit") or "", currency=row.get("currency"),
    )


def _module(row: dict) -> CatalogModule:
    return CatalogModule(
        name=row["name"], service=row["service"], title=row["title"], description=row["description"],
        category=row["category"], core=bool(row.get("is_core")), default=bool(row.get("default_enabled")),
        requires=row.get("requires") or [],
    )


def _member() -> Principal:
    who = current()
    if who is None or not who.tenant:
        raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", 403)
    return who


def _manages_platform(who: Principal) -> bool:
    platform = settings().platform_tenant
    return bool(platform) and who.tenant == platform and bool(MANAGERS & who.roles)


def _platform_manager() -> Principal:
    who = _member()
    if not _manages_platform(who):
        raise ServiceError("ERRO_PLANS_FORBIDDEN", "Só quem administra a plataforma gerencia os planos.", 403)
    return who


def _now() -> datetime:
    return datetime.now(UTC)


def _month(at: datetime | None = None) -> str:
    return (at or _now()).strftime("%Y-%m")


def _rid(record_id: str) -> RecordID:
    table, _, key = record_id.partition(":")
    return RecordID(table, key.strip("⟨⟩`"))
