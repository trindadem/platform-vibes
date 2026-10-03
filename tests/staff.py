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
                              "ajudas": 0, "organizacoes": 0}


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
