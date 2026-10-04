"""svc-agentes · testes sem infraestrutura. Fonte da verdade: specs/agentes.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. O svc-ai (rpc.ai.resolve), as ferramentas MCP do
svc-integracoes (rpc.integracoes.ferramentas e mcp_chamar) respondem por app.respond; o modelo é um provedor falso que
segue um roteiro: consulta o ERP pela ferramenta MCP e conclui com o que leu.

Rodar (da raiz): PYTHONPATH=services/svc-agentes uv run python -m pytest tests/agentes.py
"""
import json

import httpx
import pytest

from core.llm import RESOLVE_SUBJECT, Resolved, llm
from core.security import Principal, acting_as
from core.testing import service_app

import service
from schemas import EXECUTAR_SUBJECT, FERRAMENTAS_SUBJECT, LISTA_SUBJECT, MCP_SUBJECT, Empty, ExecutarAgente, SuiteRef

OWNER = ("ana", "acme", "owner")
OPERADOR = ("otto", "acme", "operador")
SISTEMA = Principal(sub="system:svc-processos", tenant="acme", roles=frozenset({"system"}))
PEDIDOS = {"12345678000190": [{"numero": "PC-1001", "valor": 7200.0}], "45678901000123": [{"numero": "PC-2001", "valor": 1850.0}]}
FERRAMENTA = "mcp:erp1:consultar_pedido"
CASOS = [
    {"id": "confere", "nome": "Boleto igual ao pedido", "tarefa": "Confira o boleto com o pedido de compra.",
     "dados": {"ler_documento": {"cnpj": "12.345.678/0001-90", "valor": 7200}}, "esperado": {"divergente": False, "diferenca": 0}},
    {"id": "diverge", "nome": "Boleto acima do pedido", "tarefa": "Confira o boleto com o pedido de compra.",
     "dados": {"ler_documento": {"cnpj": "45.678.901/0001-23", "valor": 1900}}, "esperado": {"divergente": True, "diferenca": 50}},
]
AGENTE = {"nome": "Conferente de pedidos", "descricao": "Confere o boleto com o pedido de compra no ERP",
          "instrucao": "Consulte o pedido de compra do fornecedor no ERP e compare o valor com o do boleto.",
          "ferramentas": [{"ref": FERRAMENTA, "modo": "permitir"}], "casos": CASOS}


def _resposta(model: str, mensagem: dict, motivo: str) -> httpx.Response:
    uso = {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40}
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": model, "usage": uso,
                                     "choices": [{"index": 0, "message": mensagem, "finish_reason": motivo}]})


def _chamada(nome: str, argumentos: dict) -> dict:
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": nome, "arguments": json.dumps(argumentos)}}]}


@pytest.fixture
def modelo():
    """O modelo falso: 1ª volta consulta o ERP pelo CNPJ dos dados; 2ª conclui comparando; 3ª encerra."""
    pedidos: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pedidos.append(body)
        texto = json.dumps(body["messages"], ensure_ascii=False)
        ferramentas = [m for m in body["messages"] if m["role"] == "tool"]
        nomes = [t["function"]["name"] for t in body.get("tools", [])]
        if not ferramentas:
            cnpj = "45.678.901/0001-23" if "45.678.901" in texto else "12.345.678/0001-90"
            mcp = next(n for n in nomes if n.startswith("mcp_"))
            return _resposta(body["model"], _chamada(mcp, {"cnpj": cnpj}), "tool_calls")
        if len(ferramentas) == 1:
            resposta = ferramentas[0]["content"]
            if "aprovação" in resposta:
                return _resposta(body["model"], _chamada("pedir_ajuda", {"motivo": "Preciso consultar o ERP, que pede aprovação."}), "tool_calls")
            valor_pedido = 1850.0 if "PC-2001" in resposta else 7200.0
            valor_boleto = 1900.0 if "45.678.901" in texto else 7200.0
            saida = {"divergente": valor_boleto != valor_pedido, "diferenca": valor_boleto - valor_pedido}
            if "fontes" in json.dumps(body.get("tools", [])):
                saida["fontes"] = {"divergente": "PC-1001", "diferenca": "7200"}
            return _resposta(body["model"], _chamada("concluir", saida), "tool_calls")
        return _resposta(body["model"], {"role": "assistant", "content": "Feito."}, "stop")

    salvo = llm._transport
    llm._transport = httpx.MockTransport(responder)
    llm.clear()
    yield pedidos
    llm._transport = salvo
    llm.clear()


def _integracoes(app, chamadas, quarentena=False):
    app.respond(RESOLVE_SUBJECT, lambda p: Resolved(provider="cv", scope="platform", model=p.model, base_url="https://ia.exemplo.com/v1", api_key="sk-x"))
    itens = [] if quarentena else [{"servidor": "erp1", "servidor_nome": "ERP da Acme", "nome": "consultar_pedido", "risco": "externa",
                                    "descricao": "Pedidos de compra abertos de um fornecedor, pelo CNPJ.",
                                    "parametros": {"type": "object", "properties": {"cnpj": {"type": "string"}}, "required": ["cnpj"]}}]
    app.respond(FERRAMENTAS_SUBJECT, lambda _: {"itens": itens})

    def chamar(pedido):
        chamadas.append((pedido.ferramenta, pedido.argumentos))
        cnpj = "".join(c for c in pedido.argumentos["cnpj"] if c.isdigit())
        return {"ok": True, "texto": json.dumps({"pedidos": PEDIDOS.get(cnpj, [])}), "dados": None}

    app.respond(MCP_SUBJECT, chamar)


def test_agente_nasce_rascunho_com_ferramentas_do_catalogo_e_volta_a_rascunho_quando_muda(modelo):
    async def cenario(app):
        _integracoes(app, [])
        ana = app.user(*OWNER)
        catalogo = (await ana.get("/ferramentas")).json()["data"]
        criado = (await ana.post("/agentes", json=AGENTE)).json()["data"]
        de_novo = await ana.post("/agentes", json=AGENTE)
        fora = await ana.post("/agentes", json={**AGENTE, "nome": "Outro", "ferramentas": [{"ref": "mcp:erp9:apagar_tudo"}]})
        membro = await app.user("mel", "acme", "member").post("/agentes", json={**AGENTE, "nome": "Do membro"})
        so_nome = (await ana.post("/agentes/editar", json={"id": criado["id"], "descricao": "Confere boletos"})).json()["data"]
        mudou = (await ana.post("/agentes/editar", json={"id": criado["id"], "instrucao": "Consulte o ERP e compare os valores."})).json()["data"]
        with acting_as(SISTEMA):
            lista = await app.handlers[LISTA_SUBJECT](Empty())
            with pytest.raises(Exception) as rascunho:  # rascunho não roda num processo
                await app.handlers[EXECUTAR_SUBJECT](ExecutarAgente(agente=criado["id"], tarefa="x", saidas={"divergente": "sim_nao"}))
        return catalogo, criado, de_novo, fora, membro, so_nome, mudou, lista, rascunho.value

    catalogo, criado, de_novo, fora, membro, so_nome, mudou, lista, rascunho = service_app(cenario)
    assert [i["ref"] for i in catalogo["itens"]] == ["documento", "conhecimento", FERRAMENTA] and catalogo["integracoes"]
    assert catalogo["itens"][2]["servidor_nome"] == "ERP da Acme" and catalogo["itens"][2]["risco"] == "externa"
    assert (criado["status"], criado["versao"], len(criado["casos"])) == ("rascunho", 1, 2)
    assert de_novo.json()["error"]["code"] == "ERRO_AGENTES_NOME" and fora.json()["error"]["code"] == "ERRO_AGENTES_FERRAMENTA"
    assert membro.status_code == 403
    assert so_nome["versao"] == 1 and mudou["versao"] == 2  # descrição não muda o que ele faz; instrução, sim
    assert [(a.nome, a.status, a.ferramentas) for a in lista.itens] == [("Conferente de pedidos", "rascunho", [FERRAMENTA])]
    assert getattr(rascunho, "code", None) == "ERRO_AGENTES_NAO_VERIFICADO"


def test_suite_roda_o_agente_com_a_ferramenta_mcp_e_verifica_e_o_staff_marca_confiavel(modelo):
    chamadas = []

    async def cenario(app):
        _integracoes(app, chamadas)
        ana, otto = app.user(*OWNER), app.user(*OPERADOR)
        criado = (await ana.post("/agentes", json=AGENTE)).json()["data"]
        sem_casos = (await ana.post("/agentes", json={**AGENTE, "nome": "Sem suíte", "casos": []})).json()["data"]
        vazia = await ana.post("/agentes/avaliar", json={"id": sem_casos["id"]})
        avaliando = (await ana.post("/agentes/avaliar", json={"id": criado["id"]})).json()["data"]
        with acting_as(Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))):
            avaliado = await service.AgentesService().rodar_suite(SuiteRef(id=criado["id"], versao=1))  # a activity do workflow
        dono_confia = await ana.post("/agentes/confiar", json={"id": criado["id"]})
        confiavel = (await otto.post("/agentes/confiar", json={"id": criado["id"]})).json()["data"]
        with acting_as(SISTEMA):
            passo = await app.handlers[EXECUTAR_SUBJECT](ExecutarAgente(
                agente=criado["id"], tarefa="Confira com o pedido", contexto='ler_documento: {"cnpj": "12.345.678/0001-90", "valor": 7200}',
                saidas={"divergente": "sim_nao", "diferenca": "numero"}, leitura=True, regras=["Use sempre o pedido aberto."]))
        return vazia, avaliando, avaliado, dono_confia, confiavel, passo, app.workflows

    vazia, avaliando, avaliado, dono_confia, confiavel, passo, workflows = service_app(cenario)
    assert vazia.json()["error"]["code"] == "ERRO_AGENTES_SEM_CASOS"
    assert avaliando["avaliando"] is True and [w[0] for w in workflows] == ["AvaliarSuiteWorkflow.run"]
    assert avaliado.status == "verificado" and avaliado.avaliacao.ok and not avaliado.avaliando
    assert [(r.caso, r.ok, r.ferramentas) for r in avaliado.avaliacao.resultados] == [
        ("confere", True, ["consultar_pedido"]), ("diverge", True, ["consultar_pedido"])]
    assert chamadas[:2] == [("consultar_pedido", {"cnpj": "12.345.678/0001-90"}), ("consultar_pedido", {"cnpj": "45.678.901/0001-23"})]
    assert dono_confia.status_code == 403 and (confiavel["status"], confiavel["confiavel_por"]) == ("confiavel", "otto")
    assert passo.saidas == {"divergente": False, "diferenca": 0.0} and passo.fontes["divergente"] == "PC-1001"
    assert passo.ferramentas == ["consultar_pedido"] and any("PC-1001" in lido for lido in passo.lidos)
    contexto = json.dumps(modelo[-3]["messages"], ensure_ascii=False)
    assert "Use sempre o pedido aberto." in contexto and "Regras da plataforma" in contexto  # regras do staff e da plataforma


def test_agente_que_responde_em_texto_sem_concluir_tem_uma_segunda_chance(modelo, monkeypatch):
    """Achado com o modelo real: a resposta vem escrita ("concluir(divergente=false)") sem chamar a ferramenta."""
    rodadas = []

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        rodadas.append(body)
        if "Chame a ferramenta concluir" in json.dumps(body["messages"], ensure_ascii=False):
            if any(m["role"] == "tool" for m in body["messages"]):
                return _resposta(body["model"], {"role": "assistant", "content": "Feito."}, "stop")
            return _resposta(body["model"], _chamada("concluir", {"divergente": False, "diferenca": 0}), "tool_calls")
        return _resposta(body["model"], {"role": "assistant", "content": "divergente: false, diferenca: 0\n\nconcluir(divergente=false)"}, "stop")

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(responder))

    async def cenario(app):
        _integracoes(app, [])
        ana = app.user(*OWNER)
        criado = (await ana.post("/agentes", json={**AGENTE, "ferramentas": []})).json()["data"]
        return (await ana.post("/agentes/testar", json={"id": criado["id"], "tarefa": "Confira o boleto.",
                                                        "saidas": {"divergente": "sim_nao", "diferenca": "numero"}})).json()["data"]

    teste = service_app(cenario)
    assert teste["saidas"] == {"divergente": False, "diferenca": 0.0}
    segunda = json.dumps(rodadas[1]["messages"], ensure_ascii=False)
    assert "Sua resposta anterior, sem chamar concluir" in segunda and len(rodadas) == 3


def test_resposta_em_json_no_texto_vale_quando_traz_todas_as_saidas(monkeypatch):
    respostas = iter(['Conferi: {"divergente": false, "diferenca": 0.0}', '{"divergente": false}', "Sem JSON nenhum.", "Nada."])

    def responder(request: httpx.Request) -> httpx.Response:
        return _resposta(json.loads(request.content)["model"], {"role": "assistant", "content": next(respostas)}, "stop")

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(responder))

    async def cenario(app):
        _integracoes(app, [])
        ana = app.user(*OWNER)
        criado = (await ana.post("/agentes", json={**AGENTE, "ferramentas": []})).json()["data"]
        corpo = {"id": criado["id"], "tarefa": "Confira o boleto.", "saidas": {"divergente": "sim_nao", "diferenca": "numero"}}
        em_json = (await ana.post("/agentes/testar", json=corpo)).json()["data"]  # 1ª rodada já traz o JSON (a 2ª nem precisa ler)
        incompleto = (await ana.post("/agentes/testar", json=corpo)).json()["data"]  # falta diferenca: não conclui
        return em_json, incompleto

    em_json, incompleto = service_app(cenario)
    assert em_json["saidas"] == {"divergente": False, "diferenca": 0.0}
    assert incompleto["saidas"] == {}


def test_politica_perguntar_nao_executa_a_ferramenta_e_a_suite_falha(modelo):
    chamadas = []

    async def cenario(app):
        _integracoes(app, chamadas)
        ana = app.user(*OWNER)
        criado = (await ana.post("/agentes", json={**AGENTE, "ferramentas": [{"ref": FERRAMENTA, "modo": "perguntar"}]})).json()["data"]
        with acting_as(Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))):
            avaliado = await service.AgentesService().rodar_suite(SuiteRef(id=criado["id"], versao=1))
        teste = (await ana.post("/agentes/testar", json={"id": criado["id"], "tarefa": "Confira o boleto.",
                                                         "dados": {"ler_documento": {"cnpj": "12.345.678/0001-90", "valor": 7200}},
                                                         "saidas": {"divergente": "sim_nao"}})).json()["data"]
        return avaliado, teste

    avaliado, teste = service_app(cenario)
    assert chamadas == []  # a política mandou perguntar: o ERP não foi chamado
    assert avaliado.status == "rascunho" and not avaliado.avaliacao.ok
    assert any("pediu aprovação" in d for d in avaliado.avaliacao.resultados[0].detalhes)
    assert "consultar_pedido (ERP da Acme)" in teste["aprovacao"] and teste["ajuda"]
