"""svc-atendimento · testes sem infraestrutura. Fonte da verdade: specs/atendimento.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. A organização da Cogniventure é "cogni"; os nomes
vêm do svc-identity (rpc.identity.contacts), que responde por app.respond.

Rodar (da raiz): PYTHONPATH=services/svc-atendimento uv run python -m pytest tests/atendimento.py
"""
import pytest

from core.notify import CONTACTS_SUBJECT, SEND_SUBJECT
from core.security import Principal, acting_as
from core.testing import service_app

import service
from schemas import STAFF_SUBJECT, PedidoRef, Resposta

NOMES = {"ana": "Ana Lima", "beto": "Beto", "otto": "Otto"}


@pytest.fixture(autouse=True)
def plataforma(monkeypatch):
    monkeypatch.setattr(service.settings, "platform_tenant", "cogni")


def _nomes(app):
    app.respond(CONTACTS_SUBJECT, lambda p: {"tenant_name": "Padaria",
                                             "items": [{"id": u, "name": NOMES[u], "email": f"{u}@x.com"} for u in p.users if u in NOMES]})


def test_cliente_pede_ajuda_o_operador_responde_e_o_historico_fica():
    async def cenario(app):
        _nomes(app)
        ana, beto, otto = app.user("ana", "pq", "owner"), app.user("beto", "pq", "member"), app.user("otto", "pq", "operador")
        aberto = (await beto.post("/pedidos", json={"texto": "O boleto da Leite Bom não entrou no contas a pagar, pode olhar?",
                                                    "pagina": "/processos/execucoes"})).json()["data"]
        resumo_beto = (await beto.get("/resumo")).json()["data"]
        respondido = (await otto.post("/pedidos/mensagem", json={"id": aberto["id"], "texto": "Entrou agora: o e-mail tinha 2 anexos."})).json()["data"]
        reaberto = (await beto.post("/pedidos/mensagem", json={"id": aberto["id"], "texto": "E o da Padaria Sol?"})).json()["data"]
        da_ana = (await ana.get("/pedidos")).json()["data"]
        do_beto = (await beto.get("/pedidos")).json()["data"]
        await ana.post("/pedidos", json={"texto": "Como mudo o limite de aprovação?"})
        so_dele = (await beto.get("/pedidos")).json()["data"]
        de_outro = await beto.get("/pedidos/item", params={"id": (await ana.get("/pedidos")).json()["data"]["items"][0]["id"]})
        encerrado = (await beto.post("/pedidos/encerrar", json={"id": aberto["id"]})).json()["data"]
        depois = await beto.post("/pedidos/mensagem", json={"id": aberto["id"], "texto": "Mais uma"})
        fila = [m for s, m in app.published if s == STAFF_SUBJECT]
        avisos = [m for s, m in app.published if s == SEND_SUBJECT]
        return aberto, resumo_beto, respondido, reaberto, da_ana, do_beto, so_dele, de_outro, encerrado, depois, fila, avisos

    aberto, resumo_beto, respondido, reaberto, da_ana, do_beto, so_dele, de_outro, encerrado, depois, fila, avisos = service_app(cenario)
    assert aberto["status"] == "aberto" and aberto["pagina"] == "/processos/execucoes" and aberto["autor_nome"] == "Beto"
    assert aberto["assunto"].startswith("O boleto da Leite Bom") and aberto["prazo"] is not None
    assert resumo_beto == {"pode_pedir": True, "abertos": 1, "respondidos": 0}
    assert respondido["status"] == "respondido" and respondido["mensagens"][-1]["papel"] == "staff"
    assert respondido["mensagens"][-1]["autor_nome"] == "Otto" and respondido["respondido_em"] is not None
    assert reaberto["status"] == "aberto" and len(reaberto["mensagens"]) == 3  # a mensagem nova reabre com prazo novo
    assert da_ana["total"] == 1 and do_beto["total"] == 1
    assert so_dele["total"] == 1 and de_outro.status_code == 404  # membro vê só os seus
    assert encerrado["status"] == "encerrado" and depois.json()["error"]["code"] == "ERRO_ATENDIMENTO_ENCERRADO"
    estados = [(i.tipo, i.status, i.por) for i in fila if i.ref == aberto["id"]]
    assert estados == [("pedido", "aberta", None), ("pedido", "concluida", "otto"), ("pedido", "aberta", None), ("pedido", "concluida", None)]
    assert all(i.link == f"/atendimento?pedido={i.ref}" for i in fila)
    assert any(getattr(a, "roles", None) == ["operador"] and a.title.startswith("Pedido de ajuda") for a in avisos)
    assert any(getattr(a, "users", None) == ["beto"] and a.title.startswith("A Cogniventure respondeu") for a in avisos)


def test_staff_nao_pede_ajuda_e_responde_pela_fila():
    async def cenario(app):
        _nomes(app)
        na_cogni = await app.user("gil", "cogni", "owner").post("/pedidos", json={"texto": "teste da equipe"})
        operador = await app.user("otto", "pq", "operador").post("/pedidos", json={"texto": "teste do operador"})
        resumo_operador = (await app.user("otto", "pq", "operador").get("/resumo")).json()["data"]
        aberto = (await app.user("ana", "pq", "owner").post("/pedidos", json={"texto": "Preciso de ajuda com o banco"})).json()["data"]
        svc = service.AtendimentoService()
        with acting_as(Principal(sub="ana", tenant="pq", roles=frozenset({"owner"}))):
            with pytest.raises(Exception) as de_pessoa:
                await svc.responder(Resposta(id=aberto["id"], texto="oi", por="ana"))
        with acting_as(Principal(sub="system:svc-staff", tenant="pq", roles=frozenset({"system"}))):
            visto = await svc.pedido(PedidoRef(id=aberto["id"]))
            respondido = await svc.responder(Resposta(id=aberto["id"], texto="Reconectei o banco.", por="otto", por_nome="Otto"))
        with acting_as(Principal(sub="system:svc-staff", tenant="beta", roles=frozenset({"system"}))):
            with pytest.raises(Exception) as de_outra_org:
                await svc.pedido(PedidoRef(id=aberto["id"]))
        return na_cogni, operador, resumo_operador, de_pessoa.value, visto, respondido, de_outra_org.value

    na_cogni, operador, resumo_operador, de_pessoa, visto, respondido, de_outra_org = service_app(cenario)
    assert na_cogni.status_code == 403 and operador.status_code == 403 and resumo_operador["pode_pedir"] is False
    assert de_pessoa.code == "ERRO_ATENDIMENTO_FORBIDDEN"
    assert visto.assunto == "Preciso de ajuda com o banco"
    assert respondido.status == "respondido" and respondido.mensagens[-1].autor_nome == "Otto"
    assert de_outra_org.code == "ERRO_ATENDIMENTO_NAO_ENCONTRADO"  # a RPC só vê a organização em que age
