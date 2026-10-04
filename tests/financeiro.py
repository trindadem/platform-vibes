"""svc-financeiro · testes sem infraestrutura. Fonte da verdade: specs/financeiro.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. As ações rodam pelo worker de verdade
(app.job: job do motor → handler → resultado), como a organização do processo; o banco (svc-integracoes) é app.respond.

Rodar (da raiz): PYTHONPATH=services/svc-financeiro uv run python -m pytest tests/financeiro.py
"""
from datetime import date, timedelta

from core.envelope import ServiceError
from core.processes import CATALOG_SUBJECT, STEP_SUBJECT, ActionCall, action_subject
from core.security import acting_as, system
from core.testing import service_app

from schemas import ACTIONS, AGENDAR_SUBJECT, COBRAR_SUBJECT, EMAIL_SUBJECT, EXTRATO_SUBJECT, SERVICE

OWNER = ("ana", "acme", "owner")
DOC = {"fornecedor": "Moinho Sul", "cnpj": "12.345.678/0001-90", "valor": 1250.0, "vencimento": "2026-10-15"}


def test_pacote_declara_as_acoes_e_os_modelos_do_financeiro_no_boot():
    async def cenario(app):
        return [m for s, m in app.published if s == CATALOG_SUBJECT], sorted(app.jobs)

    catalogos, jobs = service_app(cenario)
    assert len(catalogos) == 1 and catalogos[0].service == "svc-financeiro"
    acoes = {a.name: a for a in catalogos[0].actions}
    assert {"financeiro.conferir_pedido", "financeiro.classificar", "financeiro.agendar_pagamento", "financeiro.conciliar",
            "financeiro.conciliar_extrato", "financeiro.faturar", "financeiro.emitir_nota", "financeiro.cobrar", "financeiro.baixar",
            "financeiro.pendencias_do_mes", "financeiro.enviar_ao_contador", "financeiro.apurar_das", "financeiro.montar_dre"} == set(acoes)
    assert acoes["financeiro.agendar_pagamento"].risk == "irreversivel" and acoes["financeiro.agendar_pagamento"].connections == ["Banco"]
    assert "divergente" in acoes["financeiro.conferir_pedido"].output_fields
    assert all(a.example for a in ACTIONS)
    assert jobs == sorted(acoes)  # o worker pega os jobs de cada ação declarada
    modelos = {m.id: m.fluxo for m in catalogos[0].models}
    assert set(modelos) == {"contas-a-pagar", "conciliacao-bancaria", "faturamento-cobranca", "fechamento-mes"}
    assert modelos["faturamento-cobranca"].gatilho.processo == "proposta-comercial"  # a cadeia: proposta aceita → faturamento
    assert modelos["fechamento-mes"].gatilho.agenda == "0 11 1 * *"


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


def test_agente_da_empresa_usa_a_acao_de_leitura_como_ferramenta():
    """rpc.financeiro.acao (core/processes.py): a mesma ação do passo, para um agente da empresa (svc-agentes)."""
    async def cenario(app):
        criado = await app.user(*OWNER).post("/fornecedores", json={"nome": "Moinho Sul", "cnpj": DOC["cnpj"], "valor_contrato": 1000})
        acao = app.handlers[action_subject(SERVICE)]
        conferido = {}
        for org in ("acme", "beta"):
            with acting_as(system("svc-agentes", org)):
                conferido[org] = await acao(ActionCall(acao="conferir_pedido", entrada=DOC))
        with acting_as(system("svc-agentes", "acme")):
            sem_valor = await acao(ActionCall(acao="conferir_pedido", entrada={**DOC, "valor": None}))
            try:
                await acao(ActionCall(acao="agendar_pagamento", entrada={"valor": 1250, "vencimento": "2099-10-15"}))
            except ServiceError as exc:
                irreversivel = (exc.code, exc.status)
        return criado.status_code, conferido, sem_valor, irreversivel, app.requests

    criado, conferido, sem_valor, irreversivel, pedidos = service_app(cenario)
    assert criado == 200
    assert conferido["acme"].ok and conferido["acme"].resultado["divergente"] is True  # 1250 contra o contrato de 1000
    assert conferido["beta"].resultado["fornecedor_novo"] is True  # na beta, o Moinho Sul não existe: só a organização do agente
    assert (sem_valor.ok, sem_valor.motivo) == (False, "O documento não trouxe o valor: não dá para conferir.")
    assert irreversivel == ("ERRO_PROCESSOS_ACAO_IRREVERSIVEL", 403)
    assert not [s for s, _ in pedidos if s == AGENDAR_SUBJECT]  # o banco nem foi chamado


def test_agendar_no_banco_e_conciliar_o_titulo():
    agendamentos = []

    def banco(pedido):
        agendamentos.append(pedido)
        if pedido.valor > 1_000_000:
            raise ServiceError("ERRO_INTEGRACOES_SEM_BANCO", "Conecte o banco da empresa em Integrações.", 409)
        return {"pagamento_id": "PG-AB12" if len(agendamentos) == 1 else f"PG-X{len(agendamentos)}", "data": pedido.vencimento}

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
        # A foto que quebrou a linha: a linha digitável lida pela metade não se paga, vai ao staff (o banco nem é chamado).
        pela_metade = await app.job("financeiro.agendar_pagamento", headers={"excecao": "sim"}, variables={"entrada": {
            **pagamento, "linha_digitavel": "34191.79001 01043.510047 91020.150008 1"}})
        inteira = await app.job("financeiro.agendar_pagamento", headers={"excecao": "sim"}, variables={"entrada": {
            **pagamento, "linha_digitavel": "34191.79001 01043.510047 91020.150008 1 98760000189050"}})
        return agendado, sem_banco, faltando, titulos, conciliado, estranho, pago, da_beta, app.published, pela_metade, inteira

    agendado, sem_banco, faltando, titulos, conciliado, estranho, pago, da_beta, publicados, pela_metade, inteira = service_app(cenario)
    assert pela_metade.status == "handoff" and "33 dígitos" in pela_metade.message and inteira.status != "handoff"
    assert [a.linha_digitavel for a in agendamentos if a.linha_digitavel] == ["34191.79001 01043.510047 91020.150008 1 98760000189050"]
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


def test_faturar_emitir_nota_com_o_staff_cobrar_e_baixar_pelo_extrato():
    enviados, extrato = [], {"itens": []}

    def cobrar(pedido):
        return {"cobranca_id": "CB-1A2B3C4D", "linha_digitavel": "34191.79001 01043.510047", "vencimento": pedido.vencimento}

    def email(pedido):
        enviados.append(pedido)
        return {"mensagem_id": "m1", "de": "acme.1a2b3c4d@entrada.localhost"}

    async def cenario(app):
        app.respond(COBRAR_SUBJECT, cobrar)
        app.respond(EMAIL_SUBJECT, email)
        app.respond(EXTRATO_SUBJECT, lambda pedido: extrato)
        venda = {"cliente": "Padaria Pão Quente", "email": "compras@paoquente.com.br", "descricao": "Pães por 3 meses", "valor": 4800.0,
                 "prazo_pagamento": 10, "proposta_id": "pp1"}
        faturado = await app.job("financeiro.faturar", element="faturar", variables={"entrada": venda})
        sem_valor = await app.job("financeiro.faturar", variables={"entrada": {**venda, "valor": None}})
        fatura_id = faturado.variables["resultado"]["fatura_id"]
        nota = await app.job("financeiro.emitir_nota", element="emitir", variables={"entrada": {"fatura_id": fatura_id}}, headers={"excecao": "sim"})
        cobrado = await app.job("financeiro.cobrar", variables={"entrada": {"fatura_id": fatura_id, "nota_numero": "2026/000123",
                                                                            "nota_documento": "notapdf1"}})
        de_novo = await app.job("financeiro.emitir_nota", variables={"entrada": {"fatura_id": fatura_id}})  # a nota já está na fatura
        antes = await app.job("financeiro.baixar", variables={"entrada": {"cobranca_id": "CB-1A2B3C4D"}})
        extrato["itens"] = [{"tipo": "recebimento", "id": "CB-1A2B3C4D", "valor": 4800.0, "data": "2026-10-05"}]
        depois = await app.job("financeiro.baixar", variables={"entrada": {"cobranca_id": "CB-1A2B3C4D"}})
        faturas = (await app.user(*OWNER).get("/faturas")).json()["data"]["items"]
        combinada = await app.job("financeiro.faturar", variables={"entrada": {**venda, "vencimento": "2026-10-15"}})  # a mensalidade do plano
        return faturado, sem_valor, nota, cobrado, antes, depois, faturas, combinada, de_novo

    faturado, sem_valor, nota, cobrado, antes, depois, faturas, combinada, de_novo = service_app(cenario)
    vencimento = (date.today() + timedelta(days=10)).isoformat()
    assert faturado.variables["resultado"]["vencimento"] == vencimento and sem_valor.status == "handoff"
    assert combinada.variables["resultado"]["vencimento"] == "2026-10-15"  # a data combinada vale mais que o prazo
    assert nota.status == "handoff" and "R$ 4.800,00" in nota.message and "prefeitura" in nota.message  # NFS-e: o staff emite
    assert cobrado.variables["resultado"]["enviada"] is True and enviados[0].para == "compras@paoquente.com.br"
    assert "2026/000123" in enviados[0].texto and "34191.79001" in enviados[0].texto
    # O boleto da cobrança e o PDF da nota que o staff anexou vão junto (os arquivos ficam no svc-integracoes).
    assert enviados[0].anexos == [{"cobranca": "CB-1A2B3C4D"}, {"documento": "notapdf1"}] and "vão anexados" in enviados[0].texto
    assert de_novo.variables["resultado"] == {"nota_numero": "2026/000123", "nota_documento": "notapdf1"}
    assert "anexe o PDF" in nota.message
    from schemas import Nota  # na exceção, o campo da nota é um arquivo anexado (o svc-processos lê o format)
    assert Nota.model_json_schema()["properties"]["nota_documento"]["format"] == "documento"
    assert antes.variables["resultado"] == {"recebido": False, "valor": 0} and depois.variables["resultado"] == {"recebido": True, "valor": 4800.0}
    assert [(f["status"], f["nota_numero"], f["cobranca_id"]) for f in faturas] == [("paga", "2026/000123", "CB-1A2B3C4D")]


def test_conciliar_o_extrato_e_fechar_o_mes(monkeypatch):
    import service

    avisos, enviados = [], []

    async def roles(*papeis, **aviso):
        avisos.append(aviso)

    monkeypatch.setattr(service.notify, "roles", roles)
    referencia = date.today().strftime("%Y-%m")

    async def cenario(app):
        app.respond(AGENDAR_SUBJECT, lambda p: {"pagamento_id": "PG-1", "data": date.today().isoformat()})
        app.respond(COBRAR_SUBJECT, lambda p: {"cobranca_id": "CB-1", "linha_digitavel": "1", "vencimento": p.vencimento})
        app.respond(EMAIL_SUBJECT, lambda p: enviados.append(p) or {"mensagem_id": "m", "de": "x@y"})
        app.respond(EXTRATO_SUBJECT, lambda p: {"itens": [
            {"tipo": "pagamento", "id": "PG-1", "valor": -1000.0, "data": "2026-10-05"},
            {"tipo": "recebimento", "id": "CB-1", "valor": 5000.0, "data": "2026-10-05"},
            {"tipo": "recebimento", "id": "PIX-DESCONHECIDO", "valor": 75.5, "data": "2026-10-05"}]})
        await app.job("financeiro.agendar_pagamento", variables={"entrada": {"valor": 1000.0, "vencimento": date.today().isoformat(),
                                                                            "fornecedor": "Moinho Sul"}})
        fatura = await app.job("financeiro.faturar", variables={"entrada": {"cliente": "Café Central", "valor": 5000.0}})
        await app.job("financeiro.cobrar", variables={"entrada": {"fatura_id": fatura.variables["resultado"]["fatura_id"]}})
        conciliado = await app.job("financeiro.conciliar_extrato", variables={"entrada": {"dias": 1}})
        pendencias = await app.job("financeiro.pendencias_do_mes", variables={"entrada": {"referencia": referencia}})
        sem_contador = await app.job("financeiro.enviar_ao_contador", variables={"entrada": {"email_contador": "", "referencia": referencia}})
        contador = await app.job("financeiro.enviar_ao_contador", variables={"entrada": {"email_contador": "fiscal@contabil.com", "referencia": referencia}})
        das = await app.job("financeiro.apurar_das", variables={"entrada": {"referencia": referencia, "aliquota": 6.0}})
        dre = await app.job("financeiro.montar_dre", variables={"entrada": {"referencia": referencia}})
        titulos = (await app.user(*OWNER).get("/titulos")).json()["data"]["items"]
        return conciliado, pendencias, sem_contador, contador, das, dre, titulos

    conciliado, pendencias, sem_contador, contador, das, dre, titulos = service_app(cenario)
    assert conciliado.variables["resultado"] == {"lancamentos": 3, "conciliados": 2, "sem_par": 1, "valor_sem_par": 75.5}
    assert titulos[0]["status"] == "pago" and titulos[0]["conciliado"] is True
    assert pendencias.variables["resultado"] == {"referencia": referencia, "pendencias": 1, "resumo": "1 fatura(s) sem nota fiscal"}
    assert sem_contador.status == "handoff" and "email_contador" in sem_contador.message
    assert contador.status == "concluido" and enviados[-1].para == "fiscal@contabil.com" and "Café Central" in enviados[-1].texto
    ano, mes = (int(p) for p in referencia.split("-"))
    vence = date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 20).isoformat()
    assert das.variables["resultado"] == {"valor": 300.0, "vencimento": vence, "fornecedor": "Receita Federal — DAS", "linha_digitavel": None}
    assert dre.variables["resultado"]["resultado"] == 4000.0 and dre.variables["resultado"]["resumo"].startswith("Lucro de R$ 4.000,00")
    assert avisos[-1]["title"] == f"DRE de {referencia}" and avisos[-1]["key"] == f"dre-{referencia}"


def test_modelos_declaram_os_indicadores_e_o_pacote_calcula_os_dele():
    """Item 7 do alinhamento pós-N7: cada modelo declara os indicadores do mês; os que as execuções não sabem (pagos em
    atraso, valor em atraso) o pacote calcula com os títulos e as faturas (rpc.financeiro.indicadores)."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from core.processes import IndicatorRequest, indicators_subject
    from core.security import acting_as, system
    from core.surreal import db

    from schemas import FATURAS, TITULOS

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    mes = hoje.strftime("%Y-%m")
    ontem, amanha = (hoje - timedelta(days=1)).isoformat(), (hoje + timedelta(days=1)).isoformat()

    async def cenario(app):
        with acting_as(system("svc-financeiro", "acme")):
            for data, vencimento, status in ((hoje.isoformat(), ontem, "pago"),  # pago depois do vencimento
                                             (hoje.isoformat(), amanha, "pago"),  # em dia
                                             (hoje.isoformat(), "2000-01-01", "agendado")):  # ainda sem comprovante: não entra
                await db.create(TITULOS, {"fornecedor": "Moinho Sul", "valor": 100.0, "vencimento": vencimento, "data": data,
                                          "pagamento_id": f"PG-{data}-{vencimento}-{status}", "status": status})
            for valor, vencimento, status, recebido in ((700.0, ontem, "cobrada", None),  # vencida e não recebida: em atraso
                                                        (300.0, ontem, "paga", datetime.now(UTC)),  # recebida: não entra
                                                        (900.0, amanha, "cobrada", None)):  # ainda não venceu
                await db.create(FATURAS, {"cliente": "Café Central", "valor": valor, "vencimento": vencimento, "status": status,
                                          "cobranca_id": f"CB-{valor}", "recebido_em": recebido})
        responder = app.handlers[indicators_subject("svc-financeiro")]
        with acting_as(system("svc-processos", "acme")):  # o svc-processos pede na organização do cliente
            a_pagar = await responder(IndicatorRequest(modelo="contas-a-pagar", mes=mes, nomes=["pagos_em_atraso", "valor_pago"]))
            a_receber = await responder(IndicatorRequest(modelo="faturamento-cobranca", mes=mes, nomes=["valor_em_atraso"]))
            futuro = await responder(IndicatorRequest(modelo="contas-a-pagar", mes="2099-01", nomes=["pagos_em_atraso"]))
        with acting_as(system("svc-processos", "beta")):  # outra organização não vê os títulos da acme
            outra = await responder(IndicatorRequest(modelo="faturamento-cobranca", mes=mes, nomes=["valor_em_atraso"]))
        return [m for s, m in app.published if s == CATALOG_SUBJECT], a_pagar, a_receber, futuro, outra

    catalogos, a_pagar, a_receber, futuro, outra = service_app(cenario)
    indicadores = {m.id: [(i.nome, i.calculo, i.unidade) for i in m.indicadores] for m in catalogos[0].models}
    assert indicadores == {
        "contas-a-pagar": [("valor_pago", "soma", "moeda"), ("pagos_em_atraso", "pacote", "numero"), ("tempo_ate_agendar", "tempo", "horas")],
        "conciliacao-bancaria": [("conciliados_sozinhos", "razao", "percentual"), ("valor_sem_par", "soma", "moeda")],
        "faturamento-cobranca": [("valor_recebido", "soma", "moeda"), ("valor_em_atraso", "pacote", "moeda"), ("prazo_recebimento", "tempo", "dias")],
        "fechamento-mes": [("dias_para_fechar", "tempo", "dias"), ("documentos_faltantes", "soma", "numero")],
    }
    assert a_pagar.valores == {"pagos_em_atraso": 1.0, "valor_pago": None}  # valor_pago é das execuções, não do pacote
    assert a_receber.valores == {"valor_em_atraso": 700.0}
    assert futuro.valores == {"pagos_em_atraso": None} and outra.valores == {"valor_em_atraso": 0.0}
