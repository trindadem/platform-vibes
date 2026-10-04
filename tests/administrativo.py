"""svc-administrativo · testes sem infraestrutura. Fonte da verdade: specs/administrativo.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. As ações rodam pelo worker de verdade
(app.job: job do motor → handler → resultado), como a organização do processo; o e-mail (svc-integracoes) é app.respond.

Rodar (da raiz): PYTHONPATH=services/svc-administrativo uv run python -m pytest tests/administrativo.py
"""
from datetime import date, timedelta

from core.envelope import ServiceError
from core.processes import CATALOG_SUBJECT, EVENT_SUBJECT
from core.testing import service_app

from schemas import ACTIONS, EMAIL_SUBJECT

OWNER = ("ana", "acme", "owner")


def _caixa(enviados):
    def enviar(pedido):
        if pedido.para.endswith("@sem-caixa.com"):
            raise ServiceError("ERRO_INTEGRACOES_SEM_CAIXA", "Conecte a caixa de entrada da empresa em Integrações.", 409)
        enviados.append(pedido)
        return {"mensagem_id": f"m{len(enviados)}", "de": "acme.1a2b3c4d@entrada.localhost"}
    return enviar


def test_pacote_declara_as_acoes_e_os_modelos_com_a_admissao_em_paralelo():
    async def cenario(app):
        return [m for s, m in app.published if s == CATALOG_SUBJECT], sorted(app.jobs)

    catalogos, jobs = service_app(cenario)
    catalogo = catalogos[0]
    assert jobs == sorted(a.name for a in catalogo.actions) and all(a.example for a in ACTIONS)
    assert {m.id for m in catalogo.models} == {"admissao-colaborador", "compras-cotacao", "vencimentos-empresa"}
    admissao = next(m.fluxo for m in catalogo.models if m.id == "admissao-colaborador")
    assert [f.para for f in admissao.outgoing("abrir")] == ["esocial", "contrato", "exame", "acessos"]  # os ramos ao mesmo tempo
    assert admissao.gatilho.evento == "administrativo.admissao"


def test_admissao_registrada_inicia_o_processo_e_cada_passo_grava_no_colaborador():
    enviados = []

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        criado = (await ana.post("/admissoes", json={"nome": "João Lima", "email": "joao@exemplo.com", "cargo": "Vendedor",
                                                    "inicio": (date.today() + timedelta(days=10)).isoformat()})).json()["data"]
        membro = await app.user("mel", "acme", "member").post("/admissoes", json={"nome": "X Y", "email": "x@y.com", "cargo": "Caixa"})
        evento = next(m for s, m in app.published if s == EVENT_SUBJECT)
        entrada = {"entrada": {k: evento.dados.get(k) for k in ("colaborador_id", "colaborador", "email", "cargo", "inicio")}}
        documentos = await app.job("administrativo.pedir_documentos", variables=entrada, headers={"excecao": "sim"})
        esocial = await app.job("administrativo.enviar_esocial", variables=entrada, headers={"excecao": "sim"})
        exame = await app.job("administrativo.agendar_exame", variables=entrada)
        acessos = await app.job("administrativo.criar_acessos", variables=entrada)
        concluido = await app.job("administrativo.concluir_admissao", variables=entrada)
        sem_colaborador = await app.job("administrativo.agendar_exame", variables={"entrada": {}})
        colaborador = (await ana.get("/colaboradores/item", params={"id": criado["id"]})).json()["data"]
        return criado, membro, evento, documentos, esocial, exame, acessos, concluido, sem_colaborador, colaborador

    criado, membro, evento, documentos, esocial, exame, acessos, concluido, sem_colaborador, colaborador = service_app(cenario)
    assert criado["status"] == "admissao" and membro.status_code == 403
    assert evento.nome == "administrativo.admissao" and evento.dados["colaborador"] == "João Lima"
    assert evento.dados["resumo"] == "Admissão de João Lima"
    assert documentos.status == "concluido" and enviados[0].para == "joao@exemplo.com" and "Carteira de trabalho" in enviados[0].texto
    assert esocial.status == "handoff" and "S-2200" in esocial.message  # sem integração: o staff lança e informa o recibo
    assert exame.status == "concluido" and exame.variables["resultado"]["exame_em"].endswith("09:00")
    assert acessos.variables["resultado"]["acessos"] == "E-mail da empresa; CRM e WhatsApp da empresa"
    assert concluido.variables["resultado"] == {"status": "ativo"} and sem_colaborador.status == "handoff"
    assert colaborador["status"] == "ativo" and colaborador["exame_em"] and "CRM" in colaborador["acessos"]


def test_compras_pede_cotacoes_compara_e_emite_o_pedido():
    enviados = []

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        for nome, email, categoria in (("Embalagens Sul", "vendas@embsul.com", "embalagens"), ("Caixas Já", "cotacao@caixasja.com", "Embalagens"),
                                       ("Limpa Tudo", "contato@limpatudo.com", "limpeza")):
            await ana.post("/fornecedores", json={"nome": nome, "email": email, "categoria": categoria})
        requisicao = (await ana.post("/requisicoes", json={"item": "Caixas de papelão 30x30", "quantidade": 500, "categoria": "embalagens"})).json()["data"]
        entrada = {"entrada": {"requisicao_id": requisicao["id"]}}
        cotar = await app.job("administrativo.pedir_cotacoes", variables=entrada, headers={"excecao": "sim"})
        sem_resposta = await app.job("administrativo.comparar_cotacoes", variables=entrada, headers={"excecao": "sim"})
        await ana.post("/requisicoes/cotacao", json={"requisicao": requisicao["id"], "fornecedor": "Embalagens Sul", "valor": 820, "prazo_dias": 5})
        await ana.post("/requisicoes/cotacao", json={"requisicao": requisicao["id"], "fornecedor": "Caixas Já", "valor": 900})
        comparado = await app.job("administrativo.comparar_cotacoes", variables=entrada)
        pedido = await app.job("administrativo.emitir_pedido", variables={"entrada": {**entrada["entrada"], **comparado.variables["resultado"]}})
        outra = (await ana.post("/requisicoes", json={"item": "Detergente", "quantidade": 10})).json()["data"]
        cancelada = await app.job("administrativo.encerrar_requisicao", variables={"entrada": {"requisicao_id": outra["id"], "aprovado": False}})
        lista = (await ana.get("/requisicoes", params={"q": "caixas"})).json()["data"]["items"]
        de_outra = await app.user("bia", "beta", "owner").post("/requisicoes/cotacao", json={"requisicao": requisicao["id"], "fornecedor": "Xis", "valor": 1})
        eventos = [m.nome for s, m in app.published if s == EVENT_SUBJECT]
        return cotar, sem_resposta, comparado, pedido, cancelada, lista, de_outra, eventos

    cotar, sem_resposta, comparado, pedido, cancelada, lista, de_outra, eventos = service_app(cenario)
    assert cotar.variables["resultado"] == {"fornecedores": 2}  # só os de embalagens (sem diferença de maiúscula)
    assert {e.para for e in enviados[:2]} == {"vendas@embsul.com", "cotacao@caixasja.com"}
    assert sem_resposta.status == "handoff" and "Nenhum fornecedor respondeu" in sem_resposta.message
    assert comparado.variables["resultado"] == {"recebidas": 2, "melhor_fornecedor": "Embalagens Sul", "melhor_valor": 820.0, "prazo_dias": 5}
    numero = pedido.variables["resultado"]["pedido_numero"]
    assert numero == f"PC-{date.today().year}-0001" and enviados[-1].para == "vendas@embsul.com" and "R$ 820,00" in enviados[-1].texto
    assert cancelada.variables["resultado"] == {"status": "cancelada"}
    assert [(r["status"], r["pedido_numero"]) for r in lista] == [("pedido", numero)]
    assert de_outra.status_code == 404 and eventos == ["administrativo.requisicao", "administrativo.requisicao"]


def test_vencimentos_avisam_uma_vez_por_vencimento(monkeypatch):
    import service

    avisos = []

    async def roles(*papeis, **aviso):
        avisos.append(aviso["body"])

    monkeypatch.setattr(service.notify, "roles", roles)

    async def cenario(app):
        ana = app.user(*OWNER)
        hoje = date.today()
        await ana.post("/vencimentos", json={"nome": "AVCB", "tipo": "avcb", "vence_em": (hoje + timedelta(days=20)).isoformat(), "exige_vistoria": True})
        await ana.post("/vencimentos", json={"nome": "Seguro", "tipo": "seguro", "vence_em": (hoje + timedelta(days=10)).isoformat()})
        await ana.post("/vencimentos", json={"nome": "Alvará", "tipo": "alvara", "vence_em": (hoje + timedelta(days=200)).isoformat()})
        primeira = await app.job("administrativo.verificar_vencimentos", variables={"entrada": {"antecedencia_dias": 30}})
        segunda = await app.job("administrativo.verificar_vencimentos", variables={"entrada": {"antecedencia_dias": None}})
        return primeira, segunda

    primeira, segunda = service_app(cenario)
    assert (primeira.variables["resultado"]["proximos"], primeira.variables["resultado"]["exige_presenca"]) == (2, 1)
    assert "AVCB" in primeira.variables["resultado"]["resumo"] and "Alvará" not in primeira.variables["resultado"]["resumo"]
    assert segunda.variables["resultado"]["proximos"] == 0 and len(avisos) == 1  # o mesmo vencimento não avisa de novo


def test_indicadores_do_pacote_pedidos_economia_e_vencidos():
    """Item 7 do alinhamento pós-N7: pedidos que saíram no mês, a economia nas cotações e os vencidos sem renovação."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from core.processes import IndicatorRequest, indicators_subject
    from core.security import acting_as, system

    enviados = []
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    mes = hoje.strftime("%Y-%m")

    async def cenario(app):
        app.respond(EMAIL_SUBJECT, _caixa(enviados))
        ana = app.user(*OWNER)
        await ana.post("/fornecedores", json={"nome": "Embalagens Sul", "email": "vendas@embsul.com", "categoria": "embalagens"})
        for item, cotacoes in (("Caixas", [("Embalagens Sul", 820), ("Caixas Já", 900), ("Papelão Bom", 1000)]),  # economia 180
                               ("Fitas", [("Embalagens Sul", 50)])):  # uma cotação só: sem economia
            requisicao = (await ana.post("/requisicoes", json={"item": item, "quantidade": 1, "categoria": "embalagens"})).json()["data"]
            for fornecedor, valor in cotacoes:
                await ana.post("/requisicoes/cotacao", json={"requisicao": requisicao["id"], "fornecedor": fornecedor, "valor": valor})
            entrada = {"requisicao_id": requisicao["id"]}
            comparado = await app.job("administrativo.comparar_cotacoes", variables={"entrada": entrada})
            await app.job("administrativo.emitir_pedido", variables={"entrada": {**entrada, **comparado.variables["resultado"]}})
        await ana.post("/requisicoes", json={"item": "Sem pedido", "quantidade": 1})  # sem pedido: não conta
        for nome, vence in (("Alvará", (hoje - timedelta(days=3)).isoformat()), ("Seguro", (hoje + timedelta(days=20)).isoformat())):
            await ana.post("/vencimentos", json={"nome": nome, "vence_em": vence})
        responder = app.handlers[indicators_subject("svc-administrativo")]
        with acting_as(system("svc-processos", "acme")):
            compras = await responder(IndicatorRequest(modelo="compras-cotacao", mes=mes, nomes=["pedidos_emitidos", "economia_cotacoes",
                                                                                                 "dias_ate_pedido"]))
            vencimentos = await responder(IndicatorRequest(modelo="vencimentos-empresa", mes=mes, nomes=["vencidos_sem_renovacao"]))
            passado = await responder(IndicatorRequest(modelo="compras-cotacao", mes="2001-01", nomes=["pedidos_emitidos"]))
        catalogo = next(m for s, m in app.published if s == CATALOG_SUBJECT)
        return compras, vencimentos, passado, catalogo

    compras, vencimentos, passado, catalogo = service_app(cenario)
    assert compras.valores == {"pedidos_emitidos": 2.0, "economia_cotacoes": 180.0, "dias_ate_pedido": None}
    assert vencimentos.valores == {"vencidos_sem_renovacao": 1.0} and passado.valores == {"pedidos_emitidos": 0.0}
    indicadores = {m.id: [i.nome for i in m.indicadores] for m in catalogo.models}
    assert indicadores == {"admissao-colaborador": ["admissoes_concluidas", "dias_ate_ativo"],
                           "compras-cotacao": ["pedidos_emitidos", "economia_cotacoes", "dias_ate_pedido"],
                           "vencimentos-empresa": ["avisados", "vencidos_sem_renovacao"]}
