"""svc-staff · testes sem infraestrutura. Fonte da verdade: specs/staff.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. A organização da Cogniventure é "cogni"; a
identidade (rpc.identity.*) e o acompanhamento (rpc.processos.acompanhamento) respondem por app.respond.

Rodar (da raiz): PYTHONPATH=services/svc-staff uv run python -m pytest tests/staff.py
"""
from datetime import UTC, datetime, timedelta

import pytest

from core.envelope import ServiceError
from core.notify import SEND_SUBJECT
from core.security import Principal, acting_as
from core.testing import service_app

import service
from schemas import ACOMPANHAMENTO_SUBJECT, OPERADOR_SUBJECT, ORGANIZACOES_SUBJECT, STAFF_SUBJECT, Empty, ItemStaff

GESTORA = ("gina", "cogni", "admin")
OTTO = ("otto", "cogni", "member")
ZOE = ("zoe", "cogni", "member")
ORGS = {"items": [{"id": "cogni", "name": "Cogniventure"}, {"id": "acme", "name": "Acme"}, {"id": "beta", "name": "Beta"}]}


@pytest.fixture(autouse=True)
def plataforma(monkeypatch):
    monkeypatch.setattr(service.settings, "platform_tenant", "cogni")


def _identidade(app, operadores):
    def operador(pedido):
        operadores.append((pedido.user, pedido.tenant, pedido.ativo))
        return {"user": pedido.user, "tenant": pedido.tenant, "roles": ["operador"] if pedido.ativo else []}

    app.respond(ORGANIZACOES_SUBJECT, lambda _: ORGS)
    app.respond(OPERADOR_SUBJECT, operador)


def _item(tipo="excecao", ref="t1", status="aberta", prazo=None, titulo="Contas a pagar: Exceção: Ler o documento"):
    return ItemStaff(tipo=tipo, ref=ref, titulo=titulo, detalhe="Documento ilegível", status=status, prazo=prazo,
                     link="/processos/tarefas", em=datetime.now(UTC))


def _de(org):
    return Principal(sub="system:svc-processos", tenant=org, roles=frozenset({"system"}))


def test_gestor_monta_a_carteira_e_a_pessoa_ganha_e_perde_o_papel_operador():
    async def cenario(app):
        operadores = []
        _identidade(app, operadores)
        gina, otto = app.user(*GESTORA), app.user(*OTTO)
        orgs = (await gina.get("/organizacoes")).json()["data"]["items"]
        criada = (await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})).json()["data"]
        de_novo = await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})
        a_propria = await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "cogni"})
        staff_monta = await otto.post("/carteiras", json={"pessoa": "otto", "organizacao": "beta"})
        cliente = await app.user("bia", "acme", "owner").get("/carteiras")
        minhas = (await otto.get("/carteiras")).json()["data"]["itens"]
        removida = (await gina.post("/carteiras/remover", json={"id": criada["id"]})).json()["data"]
        resumo_cliente = (await app.user("bia", "acme", "owner").get("/resumo")).json()["data"]
        return orgs, criada, de_novo, a_propria, staff_monta, cliente, minhas, removida, operadores, resumo_cliente

    orgs, criada, de_novo, a_propria, staff_monta, cliente, minhas, removida, operadores, resumo_cliente = service_app(cenario)
    assert [o["id"] for o in orgs] == ["acme", "beta"]  # a própria Cogniventure não é cliente
    assert (criada["pessoa"], criada["organizacao"], criada["organizacao_nome"]) == ("otto", "acme", "Acme")
    assert de_novo.json()["error"]["code"] == "ERRO_STAFF_JA_NA_CARTEIRA" and a_propria.status_code == 404
    assert staff_monta.status_code == 403 and cliente.status_code == 403  # só o gestor monta; cliente não entra
    assert [c["organizacao"] for c in minhas] == ["acme"] and removida["id"] == criada["id"]
    assert operadores == [("otto", "acme", True), ("otto", "acme", False)]  # entrar dá o papel; sair tira
    assert resumo_cliente == {"staff": False, "gestor": False, "excecoes": 0, "atrasadas": 0, "escaladas": 0, "revisoes": 0,
                              "ajudas": 0, "pedidos": 0, "organizacoes": 0}


def test_fila_da_carteira_assumir_escalar_e_redistribuir():
    async def cenario(app):
        _identidade(app, [])
        gina, otto, zoe = app.user(*GESTORA), app.user(*OTTO), app.user(*ZOE)
        await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})
        vencida = datetime.now(UTC) - timedelta(hours=1)
        await app.deliver(STAFF_SUBJECT, _item(ref="t1", prazo=vencida), who=_de("acme"))
        await app.deliver(STAFF_SUBJECT, _item(ref="t1", prazo=vencida), who=_de("acme"))  # reentrega: um item só
        await app.deliver(STAFF_SUBJECT, _item(ref="t2", prazo=vencida + timedelta(minutes=5)), who=_de("acme"))
        await app.deliver(STAFF_SUBJECT, _item(tipo="ajuda", ref="p1", titulo="Contas a pagar: ajuda no desenho"), who=_de("beta"))
        da_otto = (await otto.get("/fila", params={"status": "aberta"})).json()["data"]
        da_zoe = (await zoe.get("/fila")).json()["data"]
        todas = (await gina.get("/fila", params={"todas": "true"})).json()["data"]
        otto_todas = (await otto.get("/fila", params={"todas": "true"})).json()["data"]
        t2 = next(i for i in da_otto["items"] if i["ref"] == "t2")
        await otto.post("/fila/assumir", json={"id": t2["id"]})
        zoe_assume = await zoe.post("/fila/assumir", json={"id": t2["id"]})
        with acting_as(Principal(sub="system:svc-staff", tenant=None, roles=frozenset({"system"}))):
            escaladas = await service.StaffService().escalar(Empty())
            de_novo = await service.StaffService().escalar(Empty())
        t1 = next(i for i in (await gina.get("/fila", params={"todas": "true", "escalada": "true"})).json()["data"]["items"])
        passada = (await gina.post("/fila/atribuir", json={"id": t1["id"], "pessoa": "zoe"})).json()["data"]
        await app.deliver(STAFF_SUBJECT, _item(ref="t1", status="concluida"), who=_de("acme"))
        abertas = (await gina.get("/fila", params={"todas": "true", "status": "aberta"})).json()["data"]
        resumo = (await gina.get("/resumo")).json()["data"]
        avisos = [m for s, m in app.published if s == SEND_SUBJECT]
        return da_otto, da_zoe, todas, otto_todas, zoe_assume, escaladas, de_novo, t1, passada, abertas, resumo, avisos

    da_otto, da_zoe, todas, otto_todas, zoe_assume, escaladas, de_novo, t1, passada, abertas, resumo, avisos = service_app(cenario)
    assert [i["ref"] for i in da_otto["items"]] == ["t1", "t2"] and da_otto["items"][0]["organizacao_nome"] == "Acme"
    assert da_zoe["total"] == 0 and todas["total"] == 3 and otto_todas["total"] == 2  # todas é só do gestor
    assert zoe_assume.status_code == 403  # a Acme não está na carteira da Zoe
    assert (escaladas.itens, de_novo.itens) == (1, 0) and t1["ref"] == "t1"  # só a não assumida sobe, uma vez
    assert (passada["atribuida_a"], passada["assumida_por"]) == ("zoe", "zoe")
    assert {i["ref"] for i in abertas["items"]} == {"t2", "p1"}
    assert resumo["gestor"] is True and (resumo["excecoes"], resumo["ajudas"], resumo["atrasadas"]) == (1, 1, 1)
    assert any(getattr(a, "roles", None) == ["owner", "admin"] and "Passou do prazo" in a.title for a in avisos)
    assert any(getattr(a, "users", None) == ["zoe"] for a in avisos)


def test_carteira_mostra_a_saude_de_cada_cliente():
    async def cenario(app):
        _identidade(app, [])
        perguntas = []

        def acompanhamento(pedido):
            perguntas.append(pedido)
            return {"andamento": 2, "concluidas": 8, "incidentes": 0, "tarefas_cliente": 1, "tarefas_staff": 1, "atrasadas": 0,
                    "autonomia": 0.75, "processos": []}

        app.respond(ACOMPANHAMENTO_SUBJECT, acompanhamento)
        gina, otto = app.user(*GESTORA), app.user(*OTTO)
        await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})
        await app.deliver(STAFF_SUBJECT, _item(tipo="revisao", ref="p9", titulo="Contas a pagar: revisão da versão 2"), who=_de("acme"))
        carteira = (await otto.get("/carteira")).json()["data"]
        with pytest.raises(ServiceError):
            with acting_as(Principal(sub="otto", tenant="acme", roles=frozenset({"operador"}))):
                await service.StaffService().carteira(Empty())  # na organização do cliente, não é a área do staff
        return carteira, perguntas

    carteira, perguntas = service_app(cenario)
    assert carteira["gestor"] is False and len(carteira["itens"]) == 1
    saude = carteira["itens"][0]
    assert (saude["nome"], saude["autonomia"], saude["andamento"], saude["revisoes"], saude["disponivel"]) == ("Acme", 0.75, 2, 1, True)
    assert len(perguntas) == 1


def test_gestor_abre_o_cliente_e_acompanha_a_jornada():
    from core.notify import CONTACTS_SUBJECT
    from core.plans import ASSIGN_SUBJECT, LIMITS_SUBJECT
    from core.security import current_tenant

    from schemas import CLIENTE_SUBJECT, CONTEXTO_SUBJECT, CONVITE_DONO_SUBJECT

    async def cenario(app):
        operadores, planos, criados = [], {}, []
        orgs = {"items": [{"id": "cogni", "name": "Cogniventure"},
                          {"id": "acme", "name": "Acme", "dono": {"name": "Bia", "email": "bia@acme.com"},
                           "ultimo_acesso": "2026-10-04T12:00:00Z"}]}
        _identidade(app, operadores)
        app.respond(ORGANIZACOES_SUBJECT, lambda _: orgs)
        app.respond(CONTACTS_SUBJECT, lambda p: {"tenant_name": "Cogniventure",
                                                  "items": [{"id": u, "name": u.title(), "email": f"{u}@cogni.com"} for u in p.users if u == "otto"]})

        def cliente(pedido):
            criados.append(pedido)
            novo = {"id": "padaria", "name": pedido.empresa, "convite": {"email": pedido.email, "expires_at": "2026-10-11T12:00:00Z"}}
            orgs["items"].append(novo)
            return {"tenant": "padaria", "name": pedido.empresa, "convite": novo["convite"]}

        def assign(pedido):
            planos[current_tenant()] = pedido.plan
            return {"tenant": current_tenant(), "plan": pedido.plan, "plan_name": pedido.plan.title()}

        def limits(_):
            plano = planos.get(current_tenant())
            staff = {"name": "staff", "service": "svc-staff", "title": "Staff", "description": "", "category": "Cogniventure",
                     "core": False, "default": False, "requires": [], "enabled": current_tenant() == "cogni"}
            return {"plan": plano, "plan_name": plano.title() if plano else "", "month": "2026-10", "limits": [], "modules": [staff]}

        app.respond(CLIENTE_SUBJECT, cliente)
        app.respond(CONVITE_DONO_SUBJECT, lambda p: {"email": "dono@padaria.com", "expires_at": "2026-10-12T12:00:00Z"})
        app.respond(ASSIGN_SUBJECT, assign)
        app.respond(LIMITS_SUBJECT, limits)
        app.respond(CONTEXTO_SUBJECT, lambda _: {"concluido_em": "2026-10-03T12:00:00Z", "perfil": {}, "topicos": []})
        app.respond(ACOMPANHAMENTO_SUBJECT, lambda _: {"andamento": 1, "concluidas": 3, "incidentes": 0, "tarefas_cliente": 0,
                                                        "tarefas_staff": 0, "atrasadas": 0, "autonomia": 1.0, "processos": [],
                                                        "aceitos": 2, "publicados": 0})
        gina, otto = app.user(*GESTORA), app.user(*OTTO)
        de_fora = await gina.post("/clientes", json={"empresa": "Padaria", "email": "dono@padaria.com", "plano": "pro", "pessoa": "zed"})
        novo = (await gina.post("/clientes", json={"empresa": "Padaria Pão Quente", "email": "dono@padaria.com", "plano": "pro",
                                                    "pessoa": "otto"})).json()["data"]
        lista = (await gina.get("/clientes")).json()["data"]["itens"]
        de_novo = (await gina.post("/clientes/convite", json={"organizacao": "padaria"})).json()["data"]
        staff_abre = await otto.post("/clientes", json={"empresa": "Xis", "email": "x@x.com", "plano": "pro", "pessoa": "otto"})
        return de_fora, novo, lista, de_novo, staff_abre, operadores, planos, criados

    de_fora, novo, lista, de_novo, staff_abre, operadores, planos, criados = service_app(cenario)
    assert de_fora.json()["error"]["code"] == "ERRO_STAFF_PESSOA" and len(criados) == 1  # nada criado para quem não é do staff
    assert (novo["organizacao"], novo["plano"], novo["responsaveis"], novo["passo"]) == ("padaria", "Pro", ["otto"], "convite")
    assert novo["convite"]["email"] == "dono@padaria.com" and planos == {"padaria": "pro"}
    assert ("otto", "padaria", True) in operadores  # a carteira deu o papel operador
    por_org = {c["organizacao"]: c for c in lista}
    assert set(por_org) == {"acme", "padaria"}  # a Cogniventure não é cliente
    assert (por_org["acme"]["passo"], por_org["acme"]["dono"]["email"], por_org["acme"]["autonomia"]) == ("desenho", "bia@acme.com", 1.0)
    assert por_org["padaria"]["passo"] == "convite" and de_novo["convite"]["email"] == "dono@padaria.com"
    assert staff_abre.status_code == 403  # só o gestor abre cliente


def test_quem_sai_da_cogniventure_sai_das_carteiras_e_da_fila():
    from schemas import MEMBER_LEFT_SUBJECT, MemberLeft

    async def cenario(app):
        operadores = []
        _identidade(app, operadores)
        gina = app.user(*GESTORA)
        await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})
        await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "beta"})
        await gina.post("/carteiras", json={"pessoa": "zoe", "organizacao": "acme"})
        await app.deliver(STAFF_SUBJECT, _item(ref="t1"), who=_de("acme"))
        item = (await gina.get("/fila", params={"todas": "true"})).json()["data"]["items"][0]
        await gina.post("/fila/atribuir", json={"id": item["id"], "pessoa": "otto"})
        await app.deliver(MEMBER_LEFT_SUBJECT, MemberLeft(tenant="acme", user="zoe"),
                          who=Principal(sub="bia", tenant="acme", roles=frozenset({"owner"})))  # saiu de um cliente: nada muda
        await app.deliver(MEMBER_LEFT_SUBJECT, MemberLeft(tenant="cogni", user="otto"),
                          who=Principal(sub="gina", tenant="cogni", roles=frozenset({"admin"})))
        carteiras = (await gina.get("/carteiras")).json()["data"]["itens"]
        depois = (await gina.get("/fila", params={"todas": "true"})).json()["data"]["items"][0]
        return operadores, carteiras, depois

    operadores, carteiras, depois = service_app(cenario)
    assert ("otto", "acme", False) in operadores and ("otto", "beta", False) in operadores
    assert [(c["pessoa"], c["organizacao"]) for c in carteiras] == [("zoe", "acme")]
    assert depois["assumida_por"] is None and depois["atribuida_a"] is None  # volta sem dono (e sobe se o prazo passar)


def test_fila_resolve_sem_trocar_de_organizacao_e_o_gestor_ve_os_numeros():
    from core.notify import CONTACTS_SUBJECT
    from core.security import current, current_tenant

    from schemas import (ATENDIMENTO_SUBJECT, FILA_DECIDIR_SUBJECT, FILA_RESOLVER_SUBJECT, FILA_REVISAO_SUBJECT, FILA_TAREFA_SUBJECT,
                         PEDIDO_SUBJECT, RESPONDER_SUBJECT)

    async def cenario(app):
        _identidade(app, [])
        chamadas = []

        def registra(nome, resposta):
            def handler(pedido):
                chamadas.append((nome, current_tenant(), current().sub, pedido.model_dump()))
                return resposta
            return handler

        tarefa = {"id": "t1", "titulo": "Contas a pagar", "nome": "Exceção: Ler o documento", "status": "aberta", "motivo": "Ilegível",
                  "campos": [{"nome": "valor", "rotulo": "Valor", "tipo": "numero"}], "contexto": [{"rotulo": "Documento", "valor": "b.pdf"}]}
        revisao = {"processo": "p9", "titulo": "Contas a pagar", "numero": 2, "status": "revisao", "mudancas": ["Limite: 5000 → 10000"]}
        pedido = {"id": "q1", "assunto": "Boleto não entrou", "status": "aberto",
                  "mensagens": [{"papel": "cliente", "autor_nome": "Beto", "texto": "Boleto não entrou", "em": "2026-10-04T12:00:00Z"}]}
        app.respond(FILA_TAREFA_SUBJECT, registra("tarefa", tarefa))
        app.respond(FILA_RESOLVER_SUBJECT, registra("resolver", {**tarefa, "status": "concluida"}))
        app.respond(FILA_REVISAO_SUBJECT, registra("revisao", revisao))
        app.respond(FILA_DECIDIR_SUBJECT, registra("decidir", {**revisao, "status": "publicada"}))
        app.respond(PEDIDO_SUBJECT, registra("pedido", pedido))
        app.respond(RESPONDER_SUBJECT, registra("responder", {**pedido, "status": "respondido"}))
        app.respond(CONTACTS_SUBJECT, lambda p: {"tenant_name": "Cogniventure", "items": [{"id": "otto", "name": "Otto", "email": "o@c.com"}]})
        gina, otto, zoe = app.user(*GESTORA), app.user(*OTTO), app.user(*ZOE)
        await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})
        await app.deliver(STAFF_SUBJECT, _item(ref="t1"), who=_de("acme"))
        await app.deliver(STAFF_SUBJECT, _item(tipo="revisao", ref="p9", titulo="Contas a pagar: revisão da versão 2"), who=_de("acme"))
        await app.deliver(ATENDIMENTO_SUBJECT, _item(tipo="pedido", ref="q1", titulo="Pedido de ajuda: Boleto não entrou"),
                          who=Principal(sub="system:svc-atendimento", tenant="acme", roles=frozenset({"system"})))
        itens = {i["tipo"]: i for i in (await otto.get("/fila")).json()["data"]["items"]}
        detalhe = (await otto.get("/fila/detalhe", params={"id": itens["excecao"]["id"]})).json()["data"]
        de_fora = await zoe.get("/fila/detalhe", params={"id": itens["excecao"]["id"]})
        tipo_errado = await otto.post("/fila/resolver", json={"id": itens["revisao"]["id"], "dados": {}})
        resolvida = (await otto.post("/fila/resolver", json={"id": itens["excecao"]["id"], "dados": {"valor": 7200}})).json()["data"]
        de_novo = await otto.post("/fila/resolver", json={"id": itens["excecao"]["id"], "dados": {"valor": 7200}})
        sem_motivo = await otto.post("/fila/revisao", json={"id": itens["revisao"]["id"], "aprovar": False})
        devolvida = (await otto.post("/fila/revisao", json={"id": itens["revisao"]["id"], "aprovar": False, "motivo": "Falta o limite"})).json()["data"]
        respondido = (await otto.post("/fila/responder", json={"id": itens["pedido"]["id"], "texto": "Entrou agora."})).json()["data"]
        await app.deliver(STAFF_SUBJECT, _item(ref="t1", status="concluida"), who=_de("acme"))  # o aviso do processo chega depois
        numeros = (await gina.get("/numeros", params={"dias": 7})).json()["data"]
        otto_numeros = await otto.get("/numeros")
        return detalhe, de_fora, tipo_errado, resolvida, de_novo, sem_motivo, devolvida, respondido, numeros, otto_numeros, chamadas

    detalhe, de_fora, tipo_errado, resolvida, de_novo, sem_motivo, devolvida, respondido, numeros, otto_numeros, chamadas = service_app(cenario)
    assert detalhe["tarefa"]["motivo"] == "Ilegível" and detalhe["tarefa"]["campos"][0]["rotulo"] == "Valor"
    assert de_fora.status_code == 403 and tipo_errado.json()["error"]["code"] == "ERRO_STAFF_TIPO"
    assert (resolvida["status"], resolvida["resolvida_por"]) == ("concluida", "otto") and de_novo.status_code == 409
    assert sem_motivo.json()["error"]["code"] == "ERRO_STAFF_MOTIVO" and devolvida["status"] == "concluida"
    assert respondido["resolvida_por"] == "otto"
    feitas = {nome: (org, quem, corpo) for nome, org, quem, corpo in chamadas}
    assert feitas["resolver"] == ("acme", "system:svc-staff", {"id": "t1", "dados": {"valor": 7200}, "comentario": None, "regra": None, "por": "otto"})
    assert feitas["decidir"][2] == {"processo": "p9", "aprovar": False, "motivo": "Falta o limite", "por": "otto"}
    assert feitas["responder"][2] == {"id": "q1", "texto": "Entrou agora.", "por": "otto", "por_nome": "Otto"}
    assert [(p["chave"], p["resolvidos"], p["no_prazo"]) for p in numeros["pessoas"]] == [("otto", 3, 3)]
    assert [(c["chave"], c["resolvidos"], c["abertos"]) for c in numeros["clientes"]] == [("acme", 3, 0)]
    assert otto_numeros.status_code == 403  # números são do gestor


# ── A conta do cliente (alinhamento pós-N7, itens 2 e 13) ────────────────────

from core.surreal import PURGE_SUBJECT, PurgeRequest  # noqa: E402

from schemas import CONTA_SUBJECT, ENCERRADA_SUBJECT, ContaEncerrada  # noqa: E402

CONTA = {"situacao": "ativa", "valor": 99.0, "valor_combinado": False, "moeda": "BRL", "vencimento": 10}


def test_gestor_combina_a_mensalidade_suspende_e_encerra_pela_aba_clientes():
    async def cenario(app):
        _identidade(app, [])
        pedidos = []

        estado = dict(CONTA)

        def conta(pedido):  # o svc-plans guarda a conta; aqui, um dicionário
            pedidos.append((service.current_tenant(), service.current().sub, pedido.acao, pedido.valor, pedido.vencimento, pedido.motivo, pedido.por))
            if pedido.valor is not None:
                estado.update(valor=pedido.valor, valor_combinado=True)
            estado["situacao"] = {"suspender": "suspensa", "encerrar": "encerrada", "reativar": "ativa"}.get(pedido.acao, estado["situacao"])
            return estado

        app.respond(CONTA_SUBJECT, conta)
        gina = app.user(*GESTORA)
        cobranca = (await gina.post("/clientes/cobranca", json={"organizacao": "acme", "valor": 150, "vencimento": 15})).json()["data"]
        suspenso = (await gina.post("/clientes/situacao", json={"organizacao": "acme", "acao": "suspender", "motivo": "Atraso"})).json()["data"]
        staff = await app.user(*OTTO).post("/clientes/situacao", json={"organizacao": "acme", "acao": "reativar"})
        a_propria = await gina.post("/clientes/cobranca", json={"organizacao": "cogni", "valor": 1})
        return cobranca, suspenso, staff, a_propria, pedidos

    cobranca, suspenso, staff, a_propria, pedidos = service_app(cenario)
    assert (cobranca["conta"]["valor"], cobranca["conta"]["valor_combinado"]) == (150, True)
    assert suspenso["conta"]["situacao"] == "suspensa"
    assert staff.status_code == 403 and a_propria.json()["error"]["code"] == "ERRO_STAFF_ORGANIZACAO"
    acoes = [p for p in pedidos if p[2] != "ver"]
    assert acoes == [("acme", "system:svc-staff", "cobranca", 150, 15, None, "gina"), ("acme", "system:svc-staff", "suspender", None, None, "Atraso", "gina")]


def test_conta_encerrada_tira_o_staff_da_carteira_e_a_exclusao_apaga_a_fila_do_cliente():
    async def cenario(app):
        operadores = []
        _identidade(app, operadores)
        gina = app.user(*GESTORA)
        await gina.post("/carteiras", json={"pessoa": "otto", "organizacao": "acme"})
        await gina.post("/carteiras", json={"pessoa": "zoe", "organizacao": "beta"})
        await app.deliver(STAFF_SUBJECT, _item(ref="t1"), who=_de("acme"))
        await app.deliver(STAFF_SUBJECT, _item(ref="t2"), who=_de("beta"))
        plans = Principal(sub="system:svc-plans", tenant="acme", roles=frozenset({"system"}))
        await app.deliver(ENCERRADA_SUBJECT, ContaEncerrada(tenant="acme", em=datetime.now(UTC)), who=plans)
        carteiras = (await gina.get("/carteiras")).json()["data"]["itens"]
        fila = (await gina.get("/fila", params={"todas": True, "status": "aberta"})).json()["data"]["items"]
        await app.deliver(PURGE_SUBJECT, PurgeRequest(tenant="acme"), who=plans)
        toda = (await gina.get("/fila", params={"todas": True})).json()["data"]["items"]
        return operadores, carteiras, fila, toda

    operadores, carteiras, fila, toda = service_app(cenario)
    assert ("otto", "acme", False) in operadores  # perde o papel operador no cliente encerrado
    assert [c["organizacao"] for c in carteiras] == ["beta"]
    assert [i["organizacao"] for i in fila] == ["beta"]  # o que esperava no encerrado fecha
    assert [i["organizacao"] for i in toda] == ["beta"]  # 30 dias depois, o histórico do cliente sai também
