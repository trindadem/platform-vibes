"""svc-processos · testes sem infraestrutura. Fonte da verdade: specs/processos.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. O svc-conhecimento e o svc-ai respondem por
app.respond; os agentes rodam no laço de verdade (core/llm.py + AgentExo) contra um provedor falso.

Rodar (da raiz): PYTHONPATH=services/svc-processos uv run python -m pytest tests/processos.py
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from core.llm import RESOLVE_SUBJECT, Resolved, llm
from core.testing import service_app

from schemas import BIBLIOTECA, BUSCA_SUBJECT, CONTEXTO_SUBJECT, Descricao, Sugestao

OWNER = ("ana", "acme", "owner")
PERFIL = {"segmento": "padaria", "pagamentos": "Boleto pelo Itaú", "documentos": "NF e boletos por e-mail",
          "dores": "Conciliar o caixa e pagar boletos em dia"}
FEITO = [{"id": "negocio", "titulo": "O negócio", "status": "feito", "faltam": []}]


def _sse(texto: str) -> list[tuple[str, dict]]:
    eventos = []
    for bloco in texto.strip().split("\n\n"):
        linhas = dict(linha.split(": ", 1) for linha in bloco.splitlines() if ": " in linha)
        if "event" in linhas:
            eventos.append((linhas["event"], json.loads(linhas["data"])))
    return eventos


def _resposta(model: str, mensagem: dict, motivo: str) -> httpx.Response:
    uso = {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": model, "usage": uso,
                                     "choices": [{"index": 0, "message": mensagem, "finish_reason": motivo}]})


def _chamadas(*chamadas: tuple[str, dict]) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": nome, "arguments": json.dumps(args)}}
        for i, (nome, args) in enumerate(chamadas)]}


@pytest.fixture
def provedor():
    """Provedor falso: na primeira volta faz as chamadas de estado["chamadas"]; na seguinte, responde com texto."""
    estado = {"chamadas": [], "pedidos": []}

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        estado["pedidos"].append(body)
        if body["messages"][-1]["role"] != "tool" and estado["chamadas"]:
            return _resposta(body["model"], _chamadas(*estado["chamadas"]), "tool_calls")
        return _resposta(body["model"], {"role": "assistant", "content": "Sugeri contas a pagar e conciliação."}, "stop")

    salvo = llm._transport
    llm._transport = httpx.MockTransport(responder)
    llm.clear()
    yield estado
    llm._transport = salvo
    llm.clear()


def _servicos(app, perfil=PERFIL, topicos=FEITO):
    """svc-ai e svc-conhecimento respondendo como no ar."""
    app.respond(RESOLVE_SUBJECT, lambda _: Resolved(provider="cv", scope="platform", model="falso",
                                                     base_url="https://ia.exemplo.com/v1", api_key="sk-x"))
    app.respond(CONTEXTO_SUBJECT, lambda _: {"perfil": perfil, "topicos": topicos, "concluido_em": None})
    app.respond(BUSCA_SUBJECT, lambda q: {"itens": [{"titulo": "Pagamentos", "trecho": "Boleto toda sexta", "fonte": "briefing"}]})


def test_biblioteca_tem_os_13_modelos_das_4_areas():
    async def cenario(app):
        return (await app.user(*OWNER).get("/biblioteca")).json()["data"]["itens"]

    itens = service_app(cenario)
    assert len(itens) == 13 and len({i["id"] for i in itens}) == 13
    assert {i["area"] for i in itens} == {"financeiro", "juridico", "administrativo", "vendas"}
    assert itens[0]["titulo"] == "Contas a pagar" and itens[0]["integracoes"] == ["Caixa de entrada", "Banco"]


def test_descoberta_sugere_com_motivo_e_nao_ressuscita_o_recusado(provedor):
    provedor["chamadas"] = [
        ("sugerir_processo", {"modelo": "contas-a-pagar", "motivo": "Vocês pagam fornecedores por boleto e as notas chegam por e-mail.", "prioridade": "alta"}),
        ("sugerir_processo", {"modelo": "conciliacao-bancaria", "motivo": "Conciliar o caixa é a dor que vocês citaram.", "prioridade": "alta"}),
        ("sugerir_processo", {"modelo": "processo-inventado", "motivo": "Não existe na biblioteca."}),
        ("buscar_conhecimento", {"consulta": "fornecedores"}),
    ]

    async def cenario(app):
        _servicos(app)
        ana = app.user(*OWNER)
        primeira = await ana.post("/descoberta", json={})
        lista = (await ana.get("/processos", params={"status": "sugerido", "sort": "titulo"})).json()["data"]["items"]
        conciliacao = next(p for p in lista if p["modelo"] == "conciliacao-bancaria")
        recusado = await ana.post("/processos/recusar", json={"id": conciliacao["id"]})
        aceito = await ana.post("/processos/aceitar", json={"id": next(p for p in lista if p["modelo"] == "contas-a-pagar")["id"]})
        segunda = await ana.post("/descoberta", json={})  # o agente sugere as mesmas de novo
        depois = (await ana.get("/processos", params={"sort": "titulo"})).json()["data"]["items"]
        resumo = (await ana.get("/resumo")).json()["data"]
        return primeira, lista, recusado, aceito, segunda, depois, resumo, app.live

    primeira, lista, recusado, aceito, segunda, depois, resumo, live = service_app(cenario)
    eventos = _sse(primeira.text)
    passos = [(d["ferramenta"], d["status"]) for e, d in eventos if e == "delta"]
    assert passos.count(("sugerir_processo", "done")) == 2 and ("sugerir_processo", "failed") in passos  # modelo inventado
    assert ("buscar_conhecimento", "done") in passos
    final = eventos[-1]
    assert final[0] == "done" and final[1]["data"]["texto"] == "Sugeri contas a pagar e conciliação."
    assert [p["modelo"] for p in final[1]["data"]["processos"]] == ["contas-a-pagar", "conciliacao-bancaria"]
    assert [(p["titulo"], p["area"], p["prioridade"], p["origem"]) for p in lista] == [
        ("Conciliação bancária", "financeiro", "alta", "sugestao"), ("Contas a pagar", "financeiro", "alta", "sugestao")]
    assert "boleto" in lista[1]["motivo"]
    assert recusado.json()["data"] is not None, recusado.text
    assert recusado.json()["data"]["status"] == "recusado" and aceito.json()["data"]["status"] == "aceito"
    assert _sse(segunda.text)[-1][1]["data"]["processos"] == []  # já decididos: nada sugerido de novo
    assert [(p["modelo"], p["status"]) for p in depois] == [("conciliacao-bancaria", "recusado"), ("contas-a-pagar", "aceito")]
    assert resumo == {"sugeridos": 0, "aceitos": 1, "recusados": 1}
    assert ("processos.processos", "sugerido") in [(t, a) for t, _, a in live]
    contexto = json.dumps(provedor["pedidos"][0]["messages"], ensure_ascii=False)
    assert "Boleto pelo Itaú" in contexto and "contas-a-pagar (financeiro)" in contexto  # perfil e biblioteca no contexto


def test_descoberta_sem_briefing_ou_sem_conhecimento_e_recusada(provedor):
    async def cenario(app):
        ana = app.user(*OWNER)
        sem_conhecimento = await ana.post("/descoberta", json={})  # ninguém responde o rpc.conhecimento.contexto
        _servicos(app, perfil={}, topicos=[{"id": "negocio", "titulo": "O negócio", "status": "a_fazer", "faltam": []}])
        sem_briefing = await ana.post("/descoberta", json={})
        membro = await app.user("mel", "acme", "member").post("/descoberta", json={})
        return sem_conhecimento, sem_briefing, membro

    sem_conhecimento, sem_briefing, membro = service_app(cenario)
    assert _sse(sem_conhecimento.text)[-1][1]["error"]["code"] == "ERRO_PROCESSOS_SEM_CONHECIMENTO"
    assert _sse(sem_briefing.text)[-1][1]["error"]["code"] == "ERRO_PROCESSOS_SEM_BRIEFING"
    assert _sse(membro.text)[-1][1]["error"]["code"] == "ERRO_PROCESSOS_FORBIDDEN"
    assert provedor["pedidos"] == []  # nenhum agente rodou


def test_processo_descrito_pelo_cliente_nasce_aceito_e_ligado_a_biblioteca(provedor):
    provedor["chamadas"] = [("registrar_processo", {
        "titulo": "Reembolso de despesas", "area": "financeiro", "modelo": None,
        "descricao": "Funcionário manda o recibo pelo WhatsApp; a dona aprova; pagamos por Pix na sexta."})]

    async def cenario(app):
        _servicos(app)
        ana = app.user(*OWNER)
        criado = await ana.post("/descrever", json={"texto": "Quando um funcionário gasta do bolso, manda o recibo e a gente devolve."})
        provedor["chamadas"] = []  # o agente não chama a ferramenta
        nao_entendeu = await ana.post("/descrever", json={"texto": "alguma coisa que fazemos às vezes"})
        de_outra = await app.user("bia", "beta", "owner").post("/processos/aceitar", json={"id": criado.json()["data"]["id"]})
        curta = await ana.post("/descrever", json={"texto": "oi"})
        return criado, nao_entendeu, de_outra, curta

    criado, nao_entendeu, de_outra, curta = service_app(cenario)
    processo = criado.json()["data"]
    assert (processo["titulo"], processo["status"], processo["origem"], processo["area"]) == (
        "Reembolso de despesas", "aceito", "cliente", "financeiro")
    assert nao_entendeu.status_code == 422 and nao_entendeu.json()["error"]["code"] == "ERRO_PROCESSOS_DESCRICAO"
    assert de_outra.status_code == 404 and curta.status_code == 422


def test_modelos_de_entrada_recusam_o_que_nao_e_da_biblioteca_ou_nao_declarado():
    assert {m.id for m in BIBLIOTECA} >= {"contas-a-pagar", "reativacao-carteira"}
    with pytest.raises(ValidationError):
        Sugestao(modelo="inventado", motivo="um motivo qualquer")
    with pytest.raises(ValidationError):
        Descricao.model_validate({"texto": "um processo qualquer aqui", "status": "aceito"})
