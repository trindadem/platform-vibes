"""svc-vendas · testes sem infraestrutura. Fonte da verdade: specs/vendas.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. As ações rodam pelo worker de verdade
(app.job: job do motor → handler → resultado), como a organização do processo; o e-mail (svc-integracoes) é app.respond.

Rodar (da raiz): PYTHONPATH=services/svc-vendas uv run python -m pytest tests/vendas.py
"""
from datetime import UTC, date, datetime, timedelta

from core.envelope import ServiceError
from core.processes import CATALOG_SUBJECT, EVENT_SUBJECT
from core.security import Principal, acting_as, system
from core.surreal import db
from core.testing import service_app

from schemas import ACTIONS, EMAIL_SUBJECT, PROPOSTAS, SERVICE

OWNER = ("ana", "acme", "owner")
ACME = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))


def _caixa(enviados, conectada=True):
    def enviar(pedido):
        if not conectada:
            raise ServiceError("ERRO_INTEGRACOES_SEM_CAIXA", "Conecte a caixa de entrada da empresa em Integrações.", 409)
        enviados.append(pedido)
        return {"mensagem_id": f"m{len(enviados)}", "de": "acme.1a2b3c4d@entrada.localhost"}
    return enviar


def test_pacote_declara_as_acoes_e_os_modelos_de_vendas():
    async def cenario(app):
        return [m for s, m in app.published if s == CATALOG_SUBJECT], sorted(app.jobs)

    catalogos, jobs = service_app(cenario)
    catalogo = catalogos[0]
    assert jobs == sorted(a.name for a in catalogo.actions) and all(a.example for a in ACTIONS)
    assert {m.id for m in catalogo.models} == {"qualificacao-leads", "proposta-comercial", "reativacao-carteira"}
    proposta = next(m.fluxo for m in catalogo.models if m.id == "proposta-comercial")
    assert {s.resultado for s in proposta.passos if s.tipo == "fim"} == {"aceita", "recusada", "nao_enviada"}  # a cadeia começa no aceita


def test_pedido_de_proposta_inicia_o_processo_e_a_aceita_vira_cliente():
    enviados = []

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        pedido = (await ana.post("/propostas", json={"cliente": "Padaria Pão Quente", "email": "compras@paoquente.com.br",
                                                    "pedido": "Precisamos de 40 kg de pão francês por semana, por 3 meses."})).json()["data"]
        membro = await app.user("mel", "acme", "member").post("/propostas", json={"cliente": "X Y", "pedido": "um pedido qualquer aqui"})
        evento = next(m for s, m in app.published if s == EVENT_SUBJECT)
        montada = await app.job("vendas.registrar_proposta", variables={"entrada": {
            "proposta_id": pedido["id"], "cliente": "Padaria Pão Quente", "email": "compras@paoquente.com.br",
            "descricao": "40 kg de pão francês por semana, 3 meses", "valor": 4800.0, "desconto": 5.0}})
        sem_valor = await app.job("vendas.registrar_proposta", variables={"entrada": {"proposta_id": pedido["id"], "descricao": "x"}})
        enviada = await app.job("vendas.enviar_proposta", variables={"entrada": {"proposta_id": pedido["id"]}}, headers={"excecao": "sim"})
        sem_resposta = await app.job("vendas.registrar_resposta", variables={"entrada": {"proposta_id": pedido["id"]}})
        aceita = await app.job("vendas.registrar_resposta", variables={"entrada": {"proposta_id": pedido["id"], "aprovado": True}})
        lista = (await ana.get("/propostas", params={"status": "aceita"})).json()["data"]["items"]
        clientes = (await ana.get("/clientes")).json()["data"]["items"]
        return pedido, membro, evento, montada, sem_valor, enviada, sem_resposta, aceita, lista, clientes

    pedido, membro, evento, montada, sem_valor, enviada, sem_resposta, aceita, lista, clientes = service_app(cenario)
    assert pedido["status"] == "pedida" and membro.status_code == 403
    assert (evento.nome, evento.dados["proposta_id"], evento.dados["resumo"]) == ("vendas.pedido_proposta", pedido["id"], "Proposta para Padaria Pão Quente")
    assert montada.status == "concluido" and montada.variables["resultado"]["proposta_id"] == pedido["id"]
    assert sem_valor.status == "handoff"
    assert enviada.status == "concluido" and enviados[0].para == "compras@paoquente.com.br"
    assert "R$ 4.800,00" in enviados[0].texto and "5% de desconto" in enviados[0].texto
    assert sem_resposta.status == "handoff" and aceita.variables["resultado"] == {"status": "aceita", "aceita": True}
    assert [p["id"] for p in lista] == [pedido["id"]]
    assert [(c["nome"], c["ultima_compra"]) for c in clientes] == [("Padaria Pão Quente", date.today().isoformat())]


def test_lead_qualificado_ganha_reuniao_no_proximo_horario_livre_e_o_frio_vai_para_nutricao():
    enviados = []

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        lead = (await ana.post("/leads/receber", json={"nome": "Café Central", "email": "dono@cafecentral.com", "origem": "site",
                                                      "interesse": "Pão de fermentação natural toda manhã"})).json()["data"]
        evento = next(m for s, m in app.published if s == EVENT_SUBJECT)
        registrado = await app.job("vendas.registrar_lead", variables={"entrada": {"lead_id": lead["id"], "nome": "Café Central"}})
        de_fora = await app.job("vendas.registrar_lead", variables={"entrada": {"nome": "Lanchonete", "email": "DONO@cafecentral.com"}})
        novo = await app.job("vendas.registrar_lead", variables={"entrada": {"nome": "Bar do Zé", "email": "não é e-mail", "origem": "whatsapp"}})
        primeira = await app.job("vendas.agendar_reuniao", variables={"entrada": {"lead_id": lead["id"], "resumo": "Pães toda manhã"}},
                                 headers={"excecao": "sim"})
        segunda = await app.job("vendas.agendar_reuniao", variables={"entrada": {"lead_id": novo.variables["resultado"]["lead_id"]}},
                                headers={"excecao": "sim"})
        frio = await app.job("vendas.nutrir", variables={"entrada": {"lead_id": novo.variables["resultado"]["lead_id"]}})
        leads = (await ana.get("/leads", params={"sort": "nome"})).json()["data"]["items"]
        return lead, evento, registrado, de_fora, novo, primeira, segunda, frio, leads

    lead, evento, registrado, de_fora, novo, primeira, segunda, frio, leads = service_app(cenario)
    assert lead["status"] == "novo" and evento.nome == "vendas.lead" and evento.dados["lead_id"] == lead["id"]
    assert registrado.variables["resultado"] == {"lead_id": lead["id"], "novo": True}
    assert de_fora.variables["resultado"] == {"lead_id": lead["id"], "novo": False}  # o mesmo e-mail não duplica
    um, dois = primeira.variables["resultado"]["reuniao_em"], segunda.variables["resultado"]["reuniao_em"]
    assert um.endswith("10:00") and dois.endswith("11:00") and um[:10] == dois[:10]  # uma por hora
    assert date.fromisoformat(um[:10]).weekday() < 5 and date.fromisoformat(um[:10]) > date.today()
    assert enviados[0].para == "dono@cafecentral.com" and "Pães toda manhã" in enviados[0].texto
    assert frio.variables["resultado"] == {"status": "nutricao"}
    assert [(item["nome"], item["status"], item["email"]) for item in leads] == [
        ("Bar do Zé", "nutricao", None), ("Café Central", "reuniao", "dono@cafecentral.com")]


def test_reativacao_follow_up_e_sem_caixa_de_entrada_vai_ao_staff():
    enviados = []

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        hoje = date.today()
        await ana.post("/clientes", json={"nome": "Café Central", "email": "dono@cafecentral.com", "ultima_compra": (hoje - timedelta(days=120)).isoformat()})
        await ana.post("/clientes", json={"nome": "Mercado Bom", "ultima_compra": (hoje - timedelta(days=200)).isoformat()})
        await ana.post("/clientes", json={"nome": "Padaria Nova", "email": "a@b.com", "ultima_compra": (hoje - timedelta(days=10)).isoformat()})
        inativos = await app.job("vendas.selecionar_inativos", variables={"entrada": {"dias_sem_comprar": 90}})
        campanha = await app.job("vendas.enviar_campanha", variables={"entrada": {"mensagem": "Sentimos sua falta!", "dias_sem_comprar": 90}})
        depois = await app.job("vendas.selecionar_inativos", variables={"entrada": {"dias_sem_comprar": 90}})
        # Uma proposta enviada há 4 dias: o follow-up de 3 dias sai uma vez.
        pedido = (await ana.post("/propostas", json={"cliente": "Café Central", "email": "dono@cafecentral.com", "pedido": "Pães para o café"})).json()["data"]
        with acting_as(ACME):
            await db.merge(f"{PROPOSTAS}:{pedido['id']}", {"status": "enviada", "valor": 900.0, "validade": hoje.isoformat(),
                                                           "enviada_em": datetime.now(UTC) - timedelta(days=4)})
        import service

        with acting_as(system(SERVICE)):
            primeira = await service.VendasService().follow_up(service.Empty())
            segunda = await service.VendasService().follow_up(service.Empty())
        app.respond(EMAIL_SUBJECT, _caixa(enviados, conectada=False))
        sem_caixa = await app.job("vendas.enviar_proposta", variables={"entrada": {"proposta_id": pedido["id"]}}, headers={"excecao": "sim"})
        return inativos, campanha, depois, primeira, segunda, sem_caixa

    inativos, campanha, depois, primeira, segunda, sem_caixa = service_app(cenario)
    assert inativos.variables["resultado"] == {"clientes": 2, "nomes": "Café Central, Mercado Bom"}
    assert campanha.variables["resultado"] == {"enviados": 1}  # o Mercado Bom não tem e-mail
    assert depois.variables["resultado"]["clientes"] == 1  # quem recebeu a campanha sai da lista no período
    assert (primeira.enviados, segunda.enviados) == (1, 0) and "Conseguiu ver a nossa proposta" in enviados[-1].texto
    assert (sem_caixa.status, sem_caixa.message) == ("handoff", "Conecte a caixa de entrada da empresa em Integrações.")


def test_indicadores_do_pacote_propostas_e_reativacao():
    """Item 7 do alinhamento pós-N7: propostas que saíram no mês, a taxa de aceite e quem voltou a comprar."""
    from zoneinfo import ZoneInfo

    from core.processes import IndicatorRequest, indicators_subject

    enviados = []
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    mes = hoje.strftime("%Y-%m")

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        for cliente, resposta in (("Padaria Pão Quente", True), ("Café Central", False), ("Mercado Sol", None)):
            pedido = (await ana.post("/propostas", json={"cliente": cliente, "email": "compras@cliente.com.br",
                                                        "pedido": "Pão francês toda semana, por três meses"})).json()["data"]
            await app.job("vendas.registrar_proposta", variables={"entrada": {"proposta_id": pedido["id"], "cliente": cliente,
                                                                              "descricao": "Pão francês", "valor": 1000.0}})
            await app.job("vendas.enviar_proposta", variables={"entrada": {"proposta_id": pedido["id"]}})
            if resposta is not None:
                await app.job("vendas.registrar_resposta", variables={"entrada": {"proposta_id": pedido["id"], "aprovado": resposta}})
        for nome, ultima, campanha in (("Voltou", hoje, hoje - timedelta(days=5)), ("Parado", hoje - timedelta(days=120), hoje - timedelta(days=3)),
                                       ("Sem campanha", hoje, None)):
            await ana.post("/clientes", json={"nome": nome, "ultima_compra": ultima.isoformat(),
                                              "campanha_em": campanha.isoformat() if campanha else None})
        responder = app.handlers[indicators_subject("svc-vendas")]
        with acting_as(system("svc-processos", "acme")):
            propostas = await responder(IndicatorRequest(modelo="proposta-comercial", mes=mes, nomes=["propostas_enviadas", "taxa_aceite", "valor_aceito"]))
            reativacao = await responder(IndicatorRequest(modelo="reativacao-carteira", mes=mes, nomes=["voltaram_a_comprar"]))
            vazio = await responder(IndicatorRequest(modelo="proposta-comercial", mes="2001-01", nomes=["taxa_aceite", "propostas_enviadas"]))
        catalogo = next(m for s, m in app.published if s == CATALOG_SUBJECT)
        return propostas, reativacao, vazio, catalogo

    propostas, reativacao, vazio, catalogo = service_app(cenario)
    assert propostas.valores == {"propostas_enviadas": 3.0, "taxa_aceite": 50.0, "valor_aceito": None}  # valor_aceito: das execuções
    assert reativacao.valores == {"voltaram_a_comprar": 1.0}
    assert vazio.valores == {"taxa_aceite": None, "propostas_enviadas": 0.0}  # sem resposta no mês, a taxa fica sem dado
    indicadores = {m.id: [(i.nome, i.calculo) for i in m.indicadores] for m in catalogo.models}
    assert indicadores == {
        "qualificacao-leads": [("leads_recebidos", "contagem"), ("qualificados", "percentual"), ("tempo_primeira_resposta", "tempo")],
        "proposta-comercial": [("propostas_enviadas", "pacote"), ("taxa_aceite", "pacote"), ("valor_aceito", "soma")],
        "reativacao-carteira": [("clientes_contatados", "soma"), ("voltaram_a_comprar", "pacote")],
    }
