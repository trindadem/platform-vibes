"""svc-financeiro · testes sem infraestrutura. Fonte da verdade: specs/financeiro.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. As ações rodam pelo worker de verdade
(app.job: job do motor → handler → resultado), como a organização do processo; o banco (svc-integracoes) é app.respond.

Rodar (da raiz): PYTHONPATH=services/svc-financeiro uv run python -m pytest tests/financeiro.py
"""
from core.envelope import ServiceError
from core.processes import CATALOG_SUBJECT, STEP_SUBJECT
from core.testing import service_app

from schemas import ACTIONS, AGENDAR_SUBJECT

OWNER = ("ana", "acme", "owner")
DOC = {"fornecedor": "Moinho Sul", "cnpj": "12.345.678/0001-90", "valor": 1250.0, "vencimento": "2026-10-15"}


def test_pacote_declara_as_acoes_do_contas_a_pagar_no_boot():
    async def cenario(app):
        return [m for s, m in app.published if s == CATALOG_SUBJECT], sorted(app.jobs)

    catalogos, jobs = service_app(cenario)
    assert len(catalogos) == 1 and catalogos[0].service == "svc-financeiro"
    acoes = {a.name: a for a in catalogos[0].actions}
    assert set(acoes) == {"financeiro.conferir_pedido", "financeiro.classificar", "financeiro.agendar_pagamento", "financeiro.conciliar"}
    assert acoes["financeiro.agendar_pagamento"].risk == "irreversivel" and acoes["financeiro.agendar_pagamento"].connections == ["Banco"]
    assert "divergente" in acoes["financeiro.conferir_pedido"].output_fields
    assert all(a.example for a in ACTIONS)
    assert jobs == sorted(acoes)  # o worker pega os jobs de cada ação declarada


def test_conferir_e_classificar_pelo_cadastro_de_fornecedores():
    async def cenario(app):
        novo = await app.job("financeiro.conferir_pedido", element="conferir", variables={"entrada": DOC})
        classificado = await app.job("financeiro.classificar", element="classificar", variables={"entrada": DOC})
        cadastrado = (await app.user(*OWNER).get("/fornecedores")).json()["data"]["items"]
        await app.user(*OWNER).post("/fornecedores/update", json={"id": cadastrado[0]["id"], "valor_contrato": 1000,
                                                                   "conta": "4.1.02 Insumos"})
        caro = await app.job("financeiro.conferir_pedido", variables={"entrada": {**DOC, "cnpj": "12345678000190"}})
        quase = await app.job("financeiro.conferir_pedido", variables={"entrada": {**DOC, "cnpj": None, "valor": 1005.0}})
        conta = await app.job("financeiro.classificar", variables={"entrada": DOC})
        sem_valor = await app.job("financeiro.conferir_pedido", variables={"entrada": {**DOC, "valor": None}})
        return novo, classificado, cadastrado, caro, quase, conta, sem_valor, app.published

    novo, classificado, cadastrado, caro, quase, conta, sem_valor, publicados = service_app(cenario)
    assert novo.variables["resultado"] == {"divergente": False, "diferenca": 0, "pedido": None, "fornecedor_novo": True}
    assert classificado.variables["resultado"]["conta"] == "2.1.01 Fornecedores"
    assert [(f["nome"], f["cnpj"]) for f in cadastrado] == [("Moinho Sul", "12.345.678/0001-90")]  # o novo entrou no cadastro
    assert caro.variables["resultado"] == {"divergente": True, "diferenca": 250.0, "pedido": "Contrato Moinho Sul", "fornecedor_novo": False}
    assert quase.variables["resultado"]["divergente"] is False  # dentro de 1% do contrato, achado pelo nome
    assert conta.variables["resultado"]["conta"] == "4.1.02 Insumos"
    assert (sem_valor.status, sem_valor.message) == ("handoff", "O documento não trouxe o valor: não dá para conferir.")
    passos = [m for s, m in publicados if s == STEP_SUBJECT]
    assert [(p.passo, p.status) for p in passos[:2]] == [("conferir", "concluido"), ("classificar", "concluido")]
    assert passos[0].processo == "proc1" and passos[0].saida["fornecedor_novo"] is True


def test_agendar_no_banco_e_conciliar_o_titulo():
    agendamentos = []

    def banco(pedido):
        agendamentos.append(pedido)
        if pedido.valor > 1_000_000:
            raise ServiceError("ERRO_INTEGRACOES_SEM_BANCO", "Conecte o banco da empresa em Integrações.", 409)
        return {"pagamento_id": "PG-AB12", "data": pedido.vencimento}

    async def cenario(app):
        app.respond(AGENDAR_SUBJECT, banco)
        pagamento = {"valor": 1250.0, "vencimento": "2026-10-15", "fornecedor": "Moinho Sul"}
        agendado = await app.job("financeiro.agendar_pagamento", element="agendar", variables={"entrada": pagamento},
                                 headers={"excecao": "sim"})
        sem_banco = await app.job("financeiro.agendar_pagamento", variables={"entrada": {**pagamento, "valor": 2e6}},
                                  headers={"excecao": "sim"})
        faltando = await app.job("financeiro.agendar_pagamento", variables={"entrada": {"valor": 10}})
        titulos = (await app.user(*OWNER).get("/titulos")).json()["data"]
        conciliado = await app.job("financeiro.conciliar", variables={"entrada": {"pagamento_id": "PG-AB12"}})
        estranho = await app.job("financeiro.conciliar", variables={"entrada": {"pagamento_id": "PG-0000"}})
        pago = (await app.user(*OWNER).get("/titulos", params={"status": "pago"})).json()["data"]
        da_beta = (await app.user("bia", "beta", "owner").get("/titulos")).json()["data"]
        return agendado, sem_banco, faltando, titulos, conciliado, estranho, pago, da_beta, app.published

    agendado, sem_banco, faltando, titulos, conciliado, estranho, pago, da_beta, publicados = service_app(cenario)
    assert agendado.variables["resultado"] == {"pagamento_id": "PG-AB12", "data": "2026-10-15"}
    assert agendamentos[0].fornecedor == "Moinho Sul"
    assert (sem_banco.status, sem_banco.message) == ("handoff", "Conecte o banco da empresa em Integrações.")
    assert faltando.status == "handoff" and "vencimento" in faltando.message
    assert titulos["total"] == 1 and titulos["items"][0]["status"] == "agendado"
    assert conciliado.variables["resultado"] == {"conciliado": True, "diferenca": 0}
    assert estranho.status == "handoff" and pago["total"] == 1 and da_beta["total"] == 0
    status = [(m.status, m.motivo) for s, m in publicados if s == STEP_SUBJECT]
    assert status[1] == ("handoff", "Conecte o banco da empresa em Integrações.")  # com exceção no passo: staff
    assert status[2][0] == "incidente"  # sem caminho de exceção: incidente
