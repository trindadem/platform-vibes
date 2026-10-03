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


def _servicos(app, perfil=PERFIL, topicos=FEITO, modelos=None):
    """svc-ai e svc-conhecimento respondendo como no ar (modelos=: só esses estão cadastrados no svc-ai)."""
    from core.envelope import ServiceError

    def resolver(pedido):
        if modelos is not None and pedido.model not in modelos:
            raise ServiceError("ERRO_AI_MODEL_UNAVAILABLE", "Modelo indisponível.", 404)
        return Resolved(provider="cv", scope="platform", model=pedido.model, base_url="https://ia.exemplo.com/v1", api_key="sk-x")

    app.respond(RESOLVE_SUBJECT, resolver)
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
    assert resumo == {"sugeridos": 0, "aceitos": 1, "recusados": 1, "publicados": 0}
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


# ── Desenho: catálogo, rascunho, simulação, agente de desenho, versões e publicação ─

from core.processes import ActionCatalog, CatalogAction  # noqa: E402
from core.security import Principal, acting_as  # noqa: E402
from core.surreal import db  # noqa: E402

from schemas import CATALOG_SUBJECT, PROCESSOS  # noqa: E402

ACME = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))
ACOES = ActionCatalog(service="svc-financeiro", actions=[
    CatalogAction(name="financeiro.conferir_pedido", service="svc-financeiro", title="Conferir", description="Confere", risk="leitura",
                  output_fields=["divergente", "diferenca"], example={"divergente": False, "diferenca": 0}),
    CatalogAction(name="financeiro.classificar", service="svc-financeiro", title="Classificar", description="Classifica", risk="escrita",
                  output_fields=["conta"], example={"conta": "2.1.01"}),
    CatalogAction(name="financeiro.agendar_pagamento", service="svc-financeiro", title="Agendar", description="Agenda", risk="irreversivel",
                  connections=["Banco"], output_fields=["pagamento_id", "data"], example={"pagamento_id": "PG-1", "data": "2026-10-15"}),
    CatalogAction(name="financeiro.conciliar", service="svc-financeiro", title="Conciliar", description="Concilia", risk="escrita",
                  connections=["Banco"], output_fields=["conciliado"], example={"conciliado": True}),
])


async def _aceito(app, modelo="contas-a-pagar", status="aceito") -> str:
    await app.handlers[CATALOG_SUBJECT](ACOES)  # o svc-financeiro declarou as ações no boot
    with acting_as(ACME):
        row = await db.create(PROCESSOS, {"modelo": modelo, "area": "financeiro", "titulo": "Contas a pagar",
                                          "descricao": "Boletos viram pagamentos", "origem": "sugestao", "status": status, "prioridade": "alta"})
    return str(row["id"]).partition(":")[2]


def test_desenho_abre_o_fluxo_de_partida_e_simula_os_caminhos():
    async def cenario(app):
        ana = app.user(*OWNER)
        pid = await _aceito(app)
        sugerido = await _aceito(app, modelo="conciliacao-bancaria", status="sugerido")
        desenho = (await ana.post("/desenho/abrir", json={"processo": pid})).json()["data"]
        de_novo = (await ana.post("/desenho/abrir", json={"processo": pid})).json()["data"]
        padrao = (await ana.post("/desenho/simular", json={"processo": pid})).json()["data"]
        caro_recusado = (await ana.post("/desenho/simular", json={"processo": pid, "valores": {"ler_documento.valor": 8000},
                                                                   "recusas": ["aprovar"]})).json()["data"]
        ilegivel = (await ana.post("/desenho/simular", json={"processo": pid, "excecoes": ["ler_documento"]})).json()["data"]
        nao_aceito = await ana.post("/desenho/abrir", json={"processo": sugerido})
        catalogo = (await ana.get("/catalogo")).json()["data"]["itens"]
        return pid, desenho, de_novo, padrao, caro_recusado, ilegivel, nao_aceito, catalogo

    pid, desenho, de_novo, padrao, caro_recusado, ilegivel, nao_aceito, catalogo = service_app(cenario)
    versao = desenho["versao"]
    assert (versao["numero"], versao["status"], len(versao["fluxo"]["passos"])) == (1, "rascunho", 14)
    assert de_novo["versao"]["id"] == versao["id"]  # abrir de novo não cria outro rascunho
    assert f'id="p_acme_{pid}"' in desenho["bpmn"] and "bpmndi:BPMNShape" in desenho["bpmn"]
    assert {p["nivel"] for p in desenho["problemas"]} == {"aviso"}  # Banco e o pagamento sem aprovação em todo caminho
    assert any("irreversível" in p["texto"] for p in desenho["problemas"]) and desenho["exige_revisao"] is True
    assert [p["id"] for p in padrao["passos"]] == ["ler_documento", "conferir", "divergente", "precisa_aprovacao", "classificar",
                                                  "agendar", "aguardar", "conciliar", "pago"]
    assert padrao["fim"] == "pago" and "f_precisa_aprovacao_classificar" in padrao["caminho"]
    assert caro_recusado["fim"] == "recusado" and "aprovar" in caro_recusado["caminho"]
    assert "ler_documento__excecao" in ilegivel["caminho"] and ilegivel["fim"] == "pago"
    assert nao_aceito.status_code == 409 and len(catalogo) == 4


def _desenhista(estado):
    """Provedor falso do agente de desenho: baixa o limite, põe uma tarefa depois da conferência e responde."""
    estado["chamadas"] = [
        ("definir_parametro", {"nome": "limite_aprovacao", "valor": 2000}),
        ("adicionar_passo", {"id": "avisar_fornecedor", "tipo": "tarefa", "nome": "Avisar fornecedor novo", "responsavel": "staff",
                             "pergunta": "Fornecedor confirmado?", "depois_de": "conferir"}),
        ("ligar", {"de": "nao_existe", "para": "pago"}),  # erro devolvido ao agente
    ]


def test_conversa_de_desenho_muda_o_rascunho_por_operacoes_e_desfaz(provedor):
    _desenhista(provedor)

    async def cenario(app):
        _servicos(app, modelos={"cv/agente"})  # sem o cv/desenho cadastrado: o agente usa o modelo dos outros
        ana = app.user(*OWNER)
        pid = await _aceito(app)
        await ana.post("/desenho/abrir", json={"processo": pid})
        resposta = await ana.post("/desenho/mensagem", json={"processo": pid, "texto": "Quero aprovar tudo acima de 2 mil."})
        desfeito = (await ana.post("/desenho/desfazer", json={"processo": pid})).json()["data"]
        membro = await app.user("mel", "acme", "member").post("/desenho/mensagem", json={"processo": pid, "texto": "oi"})
        return resposta, desfeito, membro, app.live

    resposta, desfeito, membro, live = service_app(cenario)
    eventos = _sse(resposta.text)
    passos = [(d["ferramenta"], d["status"]) for e, d in eventos if e == "delta"]
    assert ("definir_parametro", "done") in passos and ("adicionar_passo", "done") in passos
    final = eventos[-1][1]["data"]
    fluxo = final["versao"]["fluxo"]
    assert fluxo["parametros"]["limite_aprovacao"] == 2000 and final["versao"]["alteracoes"] == 2
    assert {"de": "conferir", "para": "avisar_fornecedor", "condicao": None} in fluxo["ligacoes"]
    assert {"de": "avisar_fornecedor", "para": "divergente", "condicao": None} in fluxo["ligacoes"]  # entrou no meio
    assert [m["papel"] for m in final["mensagens"]] == ["cliente", "agente"] and final["mensagens"][1]["passos"]
    assert not any(p["passo"] == "avisar_fornecedor" and p["nivel"] == "erro" for p in final["problemas"])
    novo = next(p["nome"] for p in fluxo["passos"] if p["id"] == "avisar_fornecedor")
    assert final["mudancas"][:2] == ["Parâmetro limite aprovacao: 5000 → 2000", f"Passo novo: {novo}"]  # contra o fluxo de partida
    assert f"Caminho novo: Conferir com o pedido → {novo}" in final["mudancas"]
    assert f"Caminho removido: Conferir com o pedido → Confere com o pedido?" in final["mudancas"]
    contexto = json.dumps(provedor["pedidos"][0]["messages"], ensure_ascii=False)
    assert "financeiro.agendar_pagamento" in contexto and "precisa_aprovacao → aprovar se ler_documento.valor >" in contexto
    assert desfeito["versao"]["alteracoes"] == 1 and "avisar_fornecedor" not in json.dumps(desfeito["versao"]["fluxo"])
    assert _sse(membro.text)[-1][1]["error"]["code"] == "ERRO_PROCESSOS_FORBIDDEN"
    assert ("processos.desenho", "alterado") in [(t, a) for t, _, a in live]
    assert {p["model"] for p in provedor["pedidos"]} == {"cv/agente"}


def test_agente_que_diz_que_mudou_sem_chamar_operacao_e_chamado_de_novo(provedor):
    """O modelo às vezes responde "Adicionei..." sem chamar ferramenta: o serviço pede de novo; sem mudança, não mente."""
    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        provedor["pedidos"].append(body)
        cobrado = "não chamou nenhuma ferramenta" in json.dumps(body["messages"], ensure_ascii=False)
        if cobrado and provedor["obedece"] and body["messages"][-1]["role"] != "tool":
            return _resposta(body["model"], _chamadas(("definir_parametro", {"nome": "limite_aprovacao", "valor": 3000})), "tool_calls")
        texto = "Pronto, subi o limite." if body["messages"][-1]["role"] == "tool" else "Adicionei o limite de 3000."
        return _resposta(body["model"], {"role": "assistant", "content": texto}, "stop")

    llm._transport = httpx.MockTransport(responder)

    async def cenario(app):
        _servicos(app)
        ana = app.user(*OWNER)
        pid = await _aceito(app)
        await ana.post("/desenho/abrir", json={"processo": pid})
        provedor["obedece"] = True
        obedeceu = _sse((await ana.post("/desenho/mensagem", json={"processo": pid, "texto": "Limite de 3 mil."})).text)[-1][1]["data"]
        provedor["obedece"] = False
        teimou = _sse((await ana.post("/desenho/mensagem", json={"processo": pid, "texto": "Limite de 4 mil."})).text)[-1][1]["data"]
        return obedeceu, teimou

    obedeceu, teimou = service_app(cenario)
    assert obedeceu["versao"]["fluxo"]["parametros"]["limite_aprovacao"] == 3000 and obedeceu["versao"]["alteracoes"] == 1
    assert obedeceu["mensagens"][-1]["texto"] == "Pronto, subi o limite."
    assert teimou["versao"]["alteracoes"] == 1 and teimou["mensagens"][-1]["texto"].startswith("Não consegui aplicar")
    assert len(provedor["pedidos"]) == 3 + 2  # 1ª conversa: mentiu, foi cobrado, chamou e respondeu; 2ª: mentiu duas vezes


def test_ligar_recusa_o_que_viraria_erro_e_erros_novos_sao_cobrados_do_agente(provedor):
    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        provedor["pedidos"].append(body)
        if body["messages"][-1]["role"] == "tool":
            return _resposta(body["model"], {"role": "assistant", "content": "Tirei o fim."}, "stop")
        if "deixaram estes erros" in json.dumps(body["messages"], ensure_ascii=False):
            return _resposta(body["model"], _chamadas(("adicionar_passo", {"id": "pago", "tipo": "fim", "nome": "Pago",
                                                                          "resultado": "pago", "depois_de": "conciliar"})), "tool_calls")
        return _resposta(body["model"], _chamadas(
            ("remover_passo", {"id": "pago"}),
            ("ligar", {"de": "conferir", "para": "aprovar", "condicao": {"campo": "conferir.fornecedor_novo", "operador": "verdadeiro"}}),
            ("ligar", {"de": "classificar", "para": "aprovar"})), "tool_calls")

    llm._transport = httpx.MockTransport(responder)

    async def cenario(app):
        _servicos(app)
        ana = app.user(*OWNER)
        pid = await _aceito(app)
        await ana.post("/desenho/abrir", json={"processo": pid})
        return _sse((await ana.post("/desenho/mensagem", json={"processo": pid, "texto": "Sem fim."})).text)[-1][1]["data"]

    final = service_app(cenario)
    respostas = [m["content"] for p in provedor["pedidos"] for m in p["messages"] if m["role"] == "tool"]
    assert any("condições só saem de decisões" in r for r in respostas)  # recusada na hora, o fluxo não muda
    assert any("classificar já segue para agendar" in r for r in respostas)
    assert final["versao"]["alteracoes"] == 2 and not [p for p in final["problemas"] if p["nivel"] == "erro"]
    assert {"de": "conciliar", "para": "pago", "condicao": None} in final["versao"]["fluxo"]["ligacoes"]
    assert final["mensagens"][-1]["texto"] == "Tirei o fim."


def test_publicar_implanta_no_motor_ajustar_abre_rascunho_e_a_publicada_arquiva():
    async def cenario(app):
        ana = app.user(*OWNER)
        pid = await _aceito(app)
        await ana.post("/desenho/abrir", json={"processo": pid})
        # O v1 traz ação irreversível (agendar no banco): a empresa pede a revisão e o staff publica.
        direto = await ana.post("/desenho/publicar", json={"processo": pid})
        em_revisao = (await ana.post("/desenho/revisao", json={"processo": pid, "mensagem": "Olhem o agendamento"})).json()["data"]
        conversa_travada = await ana.post("/desenho/mensagem", json={"processo": pid, "texto": "oi"})
        dono_aprova = await ana.post("/desenho/aprovar", json={"processo": pid})
        primeira = (await app.user("otto", "acme", "operador").post("/desenho/aprovar", json={"processo": pid})).json()["data"]
        sem_rascunho = await ana.post("/desenho/publicar", json={"processo": pid})
        ajustado = (await ana.post("/desenho/ajustar", json={"processo": pid})).json()["data"]
        igual = await ana.post("/desenho/publicar", json={"processo": pid})
        with acting_as(ACME):  # uma mudança no rascunho (o agente faria pela conversa)
            await db.query("UPDATE processos_versoes SET fluxo.parametros.limite_aprovacao = 2500 WHERE tenant = $tenant AND status = 'rascunho'")
        segunda = (await ana.post("/desenho/publicar", json={"processo": pid})).json()["data"]
        await ana.post("/desenho/ajustar", json={"processo": pid})
        descartado = (await ana.post("/desenho/descartar", json={"processo": pid})).json()["data"]
        processo = (await ana.get("/processos")).json()["data"]["items"][0]
        membro = await app.user("mel", "acme", "member").post("/desenho/ajustar", json={"processo": pid})
        revisoes = [(m.tipo, m.status) for s, m in app.published if s == "events.processos.staff"]
        return (pid, direto, em_revisao, conversa_travada, dono_aprova, primeira, sem_rascunho, ajustado, igual, segunda, descartado,
                processo, membro, app.motor.deployed, revisoes)

    (pid, direto, em_revisao, conversa_travada, dono_aprova, primeira, sem_rascunho, ajustado, igual, segunda, descartado, processo,
     membro, motor, revisoes) = service_app(cenario)
    assert direto.json()["error"]["code"] == "ERRO_PROCESSOS_REVISAO"
    assert em_revisao["versao"]["status"] == "revisao" and em_revisao["exige_revisao"] is True
    assert _sse(conversa_travada.text)[-1][1]["error"]["code"] == "ERRO_PROCESSOS_EM_REVISAO"
    assert dono_aprova.status_code == 403  # quem revisa é o staff
    assert revisoes == [("revisao", "aberta"), ("revisao", "concluida")]
    assert [m["papel"] for m in primeira["mensagens"]] == ["cliente", "staff"]
    assert igual.status_code == 409 and igual.json()["error"]["code"] == "ERRO_PROCESSOS_SEM_MUDANCA"
    assert (primeira["versao"]["status"], primeira["versao"]["motor"]["versao"]) == ("publicada", 1)
    assert motor[0][0] == f"p_acme_{pid}" and 'name="Contas a pagar"' in motor[0][1]
    assert sem_rascunho.status_code == 409 and sem_rascunho.json()["error"]["code"] == "ERRO_PROCESSOS_SEM_RASCUNHO"
    assert (ajustado["versao"]["numero"], ajustado["versao"]["status"]) == (2, "rascunho")
    assert ajustado["versao"]["fluxo"] == primeira["versao"]["fluxo"]  # o rascunho nasce da publicada
    assert [(v["numero"], v["status"], v["motor_versao"]) for v in segunda["versoes"]] == [(1, "arquivada", 1), (2, "publicada", 2)]
    assert (descartado["versao"]["numero"], descartado["versao"]["status"]) == (2, "publicada")
    assert processo["publicada"] == 2 and membro.status_code == 403


def test_fluxo_com_erro_nao_publica_e_os_problemas_dizem_o_que_falta():
    from core.processes import Flow, Fluxo, Step

    from service import _problemas

    quebrado = Fluxo(passos=[
        Step(id="ler", tipo="agente", nome="Ler"),
        Step(id="decidir", tipo="decisao", nome="Decidir"),
        Step(id="pagar", tipo="acao", nome="Pagar", acao="banco.inexistente"),
        Step(id="solto", tipo="tarefa", nome="Solto"),
    ], ligacoes=[Flow(de="inicio", para="ler"), Flow(de="ler", para="decidir"), Flow(de="decidir", para="pagar")])
    textos = [p.texto for p in _problemas(quebrado, {a.name: a for a in ACOES.actions}) if p.nivel == "erro"]
    for esperado in ("pelo menos um fim", "O agente Ler precisa de um objetivo", "caminho de exceção", "pelo menos dois caminhos",
                     "banco.inexistente não está no catálogo", "Solto não é alcançado", "Solto precisa de um responsável"):
        assert any(esperado in t for t in textos), (esperado, textos)

    # Condição que o motor não consegue avaliar (achado na stack: "agendar.pagamento_id é verdadeiro" virou incidente).
    from core.processes import Condition

    from schemas import FLUXOS

    catalogo = {a.name: a for a in ACOES.actions}
    partida = FLUXOS["contas-a-pagar"]
    assert not [p for p in _problemas(partida, catalogo) if p.nivel == "erro"]
    tipos_errados = partida.model_copy(deep=True)
    condicionais = [f for f in tipos_errados.ligacoes if f.condicao is not None]
    condicionais[0].condicao = Condition(campo="agendar.pagamento_id", operador="verdadeiro")
    condicionais[1].condicao = Condition(campo="ler_documento.fornecedor", operador=">", valor=3,
                                         ou=[{"campo": "parametros.limite_aprovacao", "operador": "falso"}])
    textos = [p.texto for p in _problemas(tipos_errados, catalogo) if p.nivel == "erro"]
    assert any("agendar.pagamento_id é verdadeiro, mas ele é texto" in t for t in textos), textos
    assert any("ler_documento.fornecedor com >, mas ele é texto" in t for t in textos), textos
    assert any("parametros.limite_aprovacao é falso, mas ele é numero" in t for t in textos), textos
    condicionais[0].condicao = Condition(campo="ler_documento.valor", operador="=", valor="3000")
    condicionais[1].condicao = Condition(campo="ler_documento.fornecedor", operador="!=", valor="parametros.limite_aprovacao")
    textos = [p.texto for p in _problemas(tipos_errados, catalogo) if p.nivel == "erro"]
    assert any("compara ler_documento.valor (numero) com '3000' (texto)" in t for t in textos), textos
    assert any("compara ler_documento.fornecedor (texto) com 'parametros.limite_aprovacao' (numero)" in t for t in textos), textos
    # Dois caminhos da mesma decisão com a mesma condição (achado na stack): o motor seguiria só o primeiro.
    repetido = partida.model_copy(deep=True)
    aprovado = next(f for f in repetido.ligacoes if f.de == "aprovado" and f.condicao is not None)
    repetido.ligacoes.append(Flow(de="aprovado", para="agendar", condicao=aprovado.condicao))
    textos = [p.texto for p in _problemas(repetido, catalogo) if p.nivel == "erro"]
    assert any("dois caminhos com a mesma condição (aprovar.aprovado verdadeiro)" in t for t in textos), textos

    async def cenario(app):
        ana = app.user(*OWNER)
        pid = await _aceito(app, modelo=None)  # processo sem fluxo desenhado: parte de um agente que faz tudo
        aberto = (await ana.post("/desenho/abrir", json={"processo": pid})).json()["data"]
        with acting_as(ACME):
            await db.query("UPDATE processos_versoes SET fluxo.passos[1].tipo = 'tarefa' WHERE tenant = $tenant")
        recusado = await ana.post("/desenho/publicar", json={"processo": pid})
        return aberto, recusado, app.motor.deployed

    aberto, recusado, motor = service_app(cenario)
    assert [p["tipo"] for p in aberto["versao"]["fluxo"]["passos"]] == ["agente", "fim"]
    assert recusado.status_code == 409 and recusado.json()["error"]["code"] == "ERRO_PROCESSOS_FLUXO_INVALIDO"
    assert motor == []


# ── Execução: gatilhos, tarefas, linha do tempo, autonomia e o agente de passo ─

from core.processes import JOB_AGENT, JOB_END, JOB_START, JOB_TASK, JOB_WAIT  # noqa: E402
from core.security import Principal  # noqa: E402

from schemas import DOCUMENTO_SUBJECT, EVENT_SUBJECT, STEP_SUBJECT, EventoExterno, PassoFeito  # noqa: E402

SISTEMA = Principal(sub="system:svc-integracoes", tenant="acme", roles=frozenset({"system"}))
GATILHO = {"documento_id": "doc1", "origem": "email", "nome": "boleto-outubro.pdf", "assunto": "Boleto"}
LIDO = {"fornecedor": "Moinho Sul", "cnpj": "12.345.678/0001-90", "valor": 7200.0, "vencimento": "2026-10-15"}
FONTES = {"fornecedor": "Moinho Sul", "cnpj": "CNPJ 12.345.678/0001-90", "valor": "R$ 7.200,00", "vencimento": "venc. 15/10/2026"}


async def _publicado(app) -> str:
    ana = app.user(*OWNER)
    pid = await _aceito(app)
    await ana.post("/desenho/abrir", json={"processo": pid})
    await app.user("otto", "acme", "operador").post("/desenho/publicar", json={"processo": pid})  # o staff publica o v1
    return pid


def test_documento_recebido_inicia_o_processo_publicado_uma_vez_e_o_banco_acorda_a_espera():
    async def cenario(app):
        pid = await _publicado(app)
        rascunho = await _aceito(app)  # aceito mas não publicado: o evento não o inicia
        await app.user(*OWNER).post("/desenho/abrir", json={"processo": rascunho})
        evento = EventoExterno(nome="documento.recebido", dados=GATILHO)
        await app.deliver(EVENT_SUBJECT, evento, who=SISTEMA, msg_id="m-1")
        await app.deliver(EVENT_SUBJECT, evento, who=SISTEMA, msg_id="m-1")  # reentrega do NATS: não inicia de novo
        await app.deliver(EVENT_SUBJECT, EventoExterno(nome="banco.pago", chave="PG-1", dados={"valor": 7200.0}), who=SISTEMA, msg_id="m-2")
        import service  # o ouvinte do começo chegou depois e também tentou registrar: não apaga o que o evento sabia
        with acting_as(ACME):
            processo = await service._processo_por_id(pid)
            await service._registrar_execucao(processo, app.motor.started[0][0] and str(app.motor._seq), 1, origem="evento", resumo=None)
        lista = (await app.user("mel", "acme", "member").get("/execucoes")).json()["data"]
        manual = await app.user(*OWNER).post("/execucoes/iniciar", json={"processo": pid, "dados": {"documento_id": "doc2"}})
        membro = await app.user("mel", "acme", "member").post("/execucoes/iniciar", json={"processo": pid})
        sem_publicar = await app.user(*OWNER).post("/execucoes/iniciar", json={"processo": rascunho})
        return pid, lista, manual.json()["data"], membro, sem_publicar, app.motor.started, app.motor.messages

    pid, lista, manual, membro, sem_publicar, iniciadas, mensagens = service_app(cenario)
    assert [(p, v["gatilho"]["documento_id"]) for p, v in iniciadas] == [(f"p_acme_{pid}", "doc1"), (f"p_acme_{pid}", "doc2")]
    assert lista["total"] == 1 and lista["items"][0]["resumo"] == "boleto-outubro.pdf" and lista["items"][0]["versao"] == 1
    assert lista["items"][0]["status"] == "andamento" and lista["items"][0]["origem"] == "evento"
    assert manual["origem"] == "manual" and membro.status_code == 403
    assert sem_publicar.json()["error"]["code"] == "ERRO_PROCESSOS_SEM_PUBLICADA"
    assert mensagens == [("acme.banco.pago", "PG-1", {"mensagem": {"valor": 7200.0}})]  # só a execução da acme acorda


def test_tarefas_do_cliente_e_do_staff_linha_do_tempo_e_autonomia():
    async def cenario(app):
        pid = await _publicado(app)
        await app.deliver(EVENT_SUBJECT, EventoExterno(nome="documento.recebido", dados=GATILHO), who=SISTEMA, msg_id="m-1")
        instancia = app.motor.started[0][1] and str(app.motor._seq)
        comum = {"processo": pid, "instance": instancia}
        await app.job(JOB_START, kind="EXECUTION_LISTENER", listener="START", element=f"p_acme_{pid}", variables={"gatilho": GATILHO}, **comum)
        # O agente pediu ajuda (core: handoff) e o staff resolve a leitura.
        await app.deliver(STEP_SUBJECT, PassoFeito(instancia=instancia, processo=pid, motor_versao=1, passo="ler_documento",
                                                   tipo=JOB_AGENT, status="handoff", motivo="Documento ilegível"), who=SISTEMA)
        await app.job(JOB_TASK, element="ler_documento__excecao", kind="TASK_LISTENER", listener="CREATING", variables={"gatilho": GATILHO},
                      user_task={"userTaskKey": "71", "dueDate": "2026-10-04T15:17:21.164Z[GMT]"}, **comum)
        staff = (await app.user("otto", "acme", "operador").get("/tarefas", params={"responsavel": "staff"})).json()["data"]["items"][0]
        dono_na_excecao = await app.user(*OWNER).post("/tarefas/responder", json={"id": staff["id"], "dados": LIDO})
        texto_no_numero = await app.user("otto", "acme", "operador").post("/tarefas/responder", json={"id": staff["id"], "dados": {**LIDO, "valor": "sete mil"}})
        resolvida = (await app.user("otto", "acme", "operador").post("/tarefas/responder", json={"id": staff["id"], "dados": LIDO})).json()["data"]
        # A conferência passou e o valor pede aprovação do cliente.
        await app.deliver(STEP_SUBJECT, PassoFeito(instancia=instancia, processo=pid, motor_versao=1, passo="conferir", tipo="financeiro.conferir_pedido",
                                                   status="concluido", saida={"divergente": False, "fornecedor_novo": True}), who=SISTEMA)
        await app.job(JOB_TASK, element="aprovar", kind="TASK_LISTENER", listener="CREATING",
                      variables={"gatilho": GATILHO, "ler_documento": LIDO, "conferir": {"divergente": False, "fornecedor_novo": True}},
                      user_task={"userTaskKey": "72", "dueDate": "2020-01-01T00:00:00Z"}, **comum)
        await app.job(JOB_TASK, element="aprovar", kind="TASK_LISTENER", listener="CREATING", variables={"gatilho": GATILHO},
                      user_task={"userTaskKey": "72"}, **comum)  # reentrega do ouvinte: uma tarefa só
        resumo_antes = (await app.user(*OWNER).get("/acompanhamento")).json()["data"]
        cliente = (await app.user(*OWNER).get("/tarefas", params={"responsavel": "cliente", "status": "aberta"})).json()["data"]["items"]
        operador_aprova = await app.user("otto", "acme", "operador").post("/tarefas/responder", json={"id": cliente[0]["id"], "aprovado": True})
        sem_decidir = await app.user(*OWNER).post("/tarefas/responder", json={"id": cliente[0]["id"]})
        regra_na_aprovacao = await app.user(*OWNER).post("/tarefas/responder", json={"id": cliente[0]["id"], "aprovado": True,
                                                                                    "regra": "Aprovar sempre a Leite Bom."})
        aprovada = (await app.user(*OWNER).post("/tarefas/responder", json={"id": cliente[0]["id"], "aprovado": True, "comentario": "ok"})).json()["data"]
        de_novo = await app.user(*OWNER).post("/tarefas/responder", json={"id": cliente[0]["id"], "aprovado": False})
        await app.job(JOB_WAIT, element="aguardar", kind="EXECUTION_LISTENER", listener="START", **comum)
        await app.job(JOB_END, element="pago", kind="EXECUTION_LISTENER", listener="START", **comum)
        app.motor.paths[instancia] = [{"id": "inicio", "estado": "COMPLETED"}, {"id": "ler_documento", "estado": "TERMINATED"},
                                      {"id": "ler_documento__excecao", "estado": "COMPLETED"}, {"id": "conferir", "estado": "COMPLETED"}]
        execucao = (await app.user(*OWNER).get("/execucoes")).json()["data"]["items"][0]
        detalhe = (await app.user(*OWNER).get("/execucoes/item", params={"id": execucao["id"]})).json()["data"]
        resumo = (await app.user(*OWNER).get("/acompanhamento")).json()["data"]
        return (staff, dono_na_excecao, texto_no_numero, resolvida, resumo_antes, cliente, operador_aprova, sem_decidir, aprovada,
                de_novo, execucao, detalhe, resumo, app.motor.completed, regra_na_aprovacao)

    (staff, dono_na_excecao, texto_no_numero, resolvida, resumo_antes, cliente, operador_aprova, sem_decidir, aprovada,
     de_novo, execucao, detalhe, resumo, concluidas, regra_na_aprovacao) = service_app(cenario)
    assert regra_na_aprovacao.json()["error"]["code"] == "ERRO_PROCESSOS_REGRA"  # só exceção de agente ensina
    assert (staff["tipo"], staff["responsavel"], staff["motivo"]) == ("excecao", "staff", "Documento ilegível")
    assert [c["nome"] for c in staff["campos"]] == ["fornecedor", "cnpj", "valor", "vencimento", "linha_digitavel"]
    assert {"rotulo": "Documento", "valor": "boleto-outubro.pdf"} in staff["contexto"] and staff["documento_id"] == "doc1"
    assert dono_na_excecao.status_code == 403  # exceção é do staff
    assert texto_no_numero.json()["error"]["code"] == "ERRO_PROCESSOS_RESPOSTA"
    assert resolvida["status"] == "concluida" and resolvida["concluida_por"] == "otto"
    assert concluidas[0] == ("71", {"ler_documento": {**LIDO, "linha_digitavel": None}})  # a saída do passo, no motor
    assert resumo_antes["tarefas_cliente"] == 1 and resumo_antes["atrasadas"] == 1 and resumo_antes["andamento"] == 1
    assert len(cliente) == 1 and cliente[0]["pergunta"] == "Aprovar o pagamento?"
    assert {"rotulo": "Valor", "valor": "R$ 7.200,00"} in cliente[0]["contexto"] and {"rotulo": "Fornecedor novo", "valor": "Sim"} in cliente[0]["contexto"]
    assert operador_aprova.status_code == 403 and sem_decidir.json()["error"]["code"] == "ERRO_PROCESSOS_RESPOSTA"
    assert aprovada["resposta"] == {"aprovado": True, "comentario": "ok"} and de_novo.json()["error"]["code"] == "ERRO_PROCESSOS_TAREFA_FECHADA"
    assert concluidas[1] == ("72", {"aprovar": {"aprovado": True, "comentario": "ok"}})
    assert (execucao["status"], execucao["resultado"], execucao["handoffs"]) == ("concluida", "pago", 1)
    assert [m["status"] for m in execucao["marcos"]] == ["iniciada", "handoff", "tarefa", "resolvido", "concluido", "tarefa", "resolvido", "aguardando", "fim"]
    assert execucao["saidas"]["ler_documento"]["valor"] == 7200.0 and execucao["saidas"]["aprovar"]["aprovado"] is True
    assert "f_ler_documento_conferir" not in detalhe["caminho"] and "f_inicio_ler_documento" in detalhe["caminho"]
    assert detalhe["atuais"] == [] and 'id="p_acme_' in detalhe["bpmn"]
    assert resumo["concluidas"] == 1 and resumo["autonomia"] == 0.0  # teve handoff: não conta como sozinha
    assert resumo["processos"][0]["por_versao"] == [{"versao": 1, "concluidas": 1, "sem_handoff": 0, "autonomia": 0.0}]


def test_passo_de_agente_le_o_documento_conclui_ou_pede_ajuda(provedor):
    roteiro = {"pede_ajuda": False, "saida": {**LIDO, "linha_digitavel": None, "fontes": FONTES}}

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        provedor["pedidos"].append(body)
        ultimas = [m for m in body["messages"] if m["role"] == "tool"]
        if not ultimas:
            return _resposta(body["model"], _chamadas(("ler_documento", {"documento_id": "doc1"})), "tool_calls")
        if len(ultimas) == 1:
            if roteiro["pede_ajuda"]:
                return _resposta(body["model"], _chamadas(("pedir_ajuda", {"motivo": "Boleto sem valor legível"})), "tool_calls")
            return _resposta(body["model"], _chamadas(("concluir", roteiro["saida"])), "tool_calls")
        return _resposta(body["model"], {"role": "assistant", "content": "Feito."}, "stop")

    llm._transport = httpx.MockTransport(responder)

    async def cenario(app):
        _servicos(app)
        pid = await _publicado(app)
        agente = {"processo": pid, "element": "ler_documento", "variables": {"gatilho": GATILHO}, "headers": {"excecao": "sim"}}
        app.respond(DOCUMENTO_SUBJECT, lambda ref: {"id": ref.id, "nome": "boleto.pdf", "tipo": "application/pdf",
                                                    "texto": "Moinho Sul CNPJ 12.345.678/0001-90 R$ 7.200,00 venc. 15/10/2026"})
        lido = await app.job(JOB_AGENT, **agente)
        # Não chuta: a data citada não é a que o documento traz, ou o trecho citado não está no documento.
        roteiro["saida"] = {**LIDO, "vencimento": "2026-10-20", "fontes": FONTES}
        outra_data = await app.job(JOB_AGENT, **agente)
        roteiro["saida"] = {**LIDO, "fontes": {**FONTES, "vencimento": "Vencimento: 15/10/2026"}}
        inventado = await app.job(JOB_AGENT, **agente)
        roteiro["saida"] = {**LIDO, "fontes": {**FONTES, "vencimento": "regra"}}
        regra_que_nao_existe = await app.job(JOB_AGENT, **agente)
        roteiro["pede_ajuda"] = True
        ajuda = await app.job(JOB_AGENT, **agente)
        return lido, outra_data, inventado, regra_que_nao_existe, ajuda, [m for s, m in app.published if s == STEP_SUBJECT]

    lido, outra_data, inventado, regra_que_nao_existe, ajuda, passos = service_app(cenario)
    assert lido.status == "concluido" and lido.variables["resultado"]["valor"] == 7200.0 and "fontes" not in lido.variables["resultado"]
    for chute in (outra_data, inventado, regra_que_nao_existe):
        assert (chute.status, chute.message) == ("handoff", "O agente não mostrou no documento de onde tirou: vencimento.")
    assert (ajuda.status, ajuda.message) == ("handoff", "Boleto sem valor legível")
    assert [(p.passo, p.status) for p in passos] == [("ler_documento", "concluido")] + [("ler_documento", "handoff")] * 4
    ferramentas = {t["function"]["name"] for t in provedor["pedidos"][0]["tools"]}
    assert ferramentas == {"ler_documento", "buscar_conhecimento", "concluir", "pedir_ajuda"}
    concluir = json.dumps(next(t for t in provedor["pedidos"][0]["tools"] if t["function"]["name"] == "concluir"))
    assert "valor" in concluir and "fontes" in concluir


# ── Staff (N5): ajuda no setup, conversa do staff, regras aprendidas com o handoff ──

from schemas import ACOMPANHAMENTO_SUBJECT, STAFF_SUBJECT, Empty, RegraRef  # noqa: E402

OPERADOR = ("otto", "acme", "operador")


def test_empresa_pede_ajuda_e_o_staff_ajusta_na_conversa_e_publica(provedor):
    provedor["chamadas"] = [("definir_parametro", {"nome": "limite_aprovacao", "valor": 3000})]

    async def cenario(app):
        _servicos(app)
        ana, otto = app.user(*OWNER), app.user(*OPERADOR)
        pid = await _aceito(app)
        await ana.post("/desenho/abrir", json={"processo": pid})
        membro = await app.user("mel", "acme", "member").post("/desenho/ajuda", json={"processo": pid, "texto": "socorro"})
        pedido = (await ana.post("/desenho/ajuda", json={"processo": pid, "texto": "Acima de 3 mil eu quero aprovar"})).json()["data"]
        conversa = await otto.post("/desenho/mensagem", json={"processo": pid, "texto": "Ajustando o limite pedido pela Ana para 3 mil."})
        publicado = (await otto.post("/desenho/publicar", json={"processo": pid})).json()["data"]
        itens = [(m.tipo, m.status, m.link) for s, m in app.published if s == STAFF_SUBJECT]
        with acting_as(ACME):
            saude = await app.handlers[ACOMPANHAMENTO_SUBJECT](Empty())  # a carteira do staff (svc-staff) pergunta
        return membro, pedido, _sse(conversa.text)[-1][1]["data"], publicado, itens, saude, pid

    membro, pedido, depois, publicado, itens, saude, pid = service_app(cenario)
    assert saude.andamento == 0 and saude.processos == []
    assert membro.status_code == 403
    assert pedido["processo"]["ajuda"]["texto"] == "Acima de 3 mil eu quero aprovar"
    assert pedido["mensagens"][-1]["papel"] == "cliente" and pedido["mensagens"][-1]["texto"].startswith("Pedi ajuda ao staff")
    staff = next(m for m in depois["mensagens"] if m["papel"] == "staff")
    assert staff["autor"] == "otto" and depois["versao"]["fluxo"]["parametros"]["limite_aprovacao"] == 3000
    enviado = json.dumps(provedor["pedidos"][0]["messages"], ensure_ascii=False)
    assert "Mensagem do staff da Cogniventure:\\nAjustando" in enviado and "Cliente: Pedi ajuda ao staff" in enviado
    assert publicado["versao"]["status"] == "publicada" and publicado["processo"]["ajuda"] is None
    assert itens == [("ajuda", "aberta", f"/processos/{pid}"), ("ajuda", "concluida", f"/processos/{pid}")]


def test_excecao_de_agente_vira_regra_avaliada_que_entra_no_agente(provedor):
    roteiro = {"vencimento": "2026-11-15"}
    caso = {"gatilho": GATILHO}
    leite = {"fornecedor": "Leite Bom", "cnpj": "45.678.901/0001-23", "valor": 7200.0}
    fontes = {"fornecedor": "Leite Bom", "cnpj": "CNPJ 45.678.901/0001-23", "valor": "R$ 7.200,00", "vencimento": "regra"}

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        provedor["pedidos"].append(body)
        ferramentas = [m for m in body["messages"] if m["role"] == "tool"]
        if not ferramentas:
            return _resposta(body["model"], _chamadas(("ler_documento", {"documento_id": "doc1"})), "tool_calls")
        if len(ferramentas) == 1:
            return _resposta(body["model"], _chamadas(("concluir", {**leite, "vencimento": roteiro["vencimento"], "fontes": fontes})), "tool_calls")
        return _resposta(body["model"], {"role": "assistant", "content": "Feito."}, "stop")

    llm._transport = httpx.MockTransport(responder)

    async def cenario(app):
        import service

        _servicos(app)
        app.respond(DOCUMENTO_SUBJECT, lambda ref: {"id": ref.id, "nome": "boleto.pdf", "tipo": "application/pdf",
                                                    "texto": "Leite Bom CNPJ 45.678.901/0001-23 R$ 7.200,00 referência outubro/2026"})
        pid = await _publicado(app)
        await app.deliver(EVENT_SUBJECT, EventoExterno(nome="documento.recebido", dados=GATILHO), who=SISTEMA, msg_id="m-1")
        comum = {"processo": pid, "instance": str(app.motor._seq)}
        # Sem regra, o vencimento que o boleto não traz não se conclui: vai para o staff, com o que o agente leu.
        sem_regra = await app.job(JOB_AGENT, element="ler_documento", variables=caso, headers={"excecao": "sim"}, **comum)
        await app.job(JOB_TASK, element="ler_documento__excecao", kind="TASK_LISTENER", listener="CREATING", variables=caso,
                      user_task={"userTaskKey": "81"}, **comum)
        otto = app.user(*OPERADOR)
        tarefa = (await otto.get("/tarefas", params={"responsavel": "staff"})).json()["data"]["items"][0]
        regra_curta = await otto.post("/tarefas/responder", json={"id": tarefa["id"], "dados": {**leite, "vencimento": "2026-11-15"}, "regra": "curta"})
        await otto.post("/tarefas/responder", json={"id": tarefa["id"], "dados": {**leite, "vencimento": "2026-11-15"},
                                                    "regra": "A Leite Bom não põe vencimento: é o dia 15 do mês seguinte ao da referência."})
        regras = (await otto.get("/regras", params={"processo": pid})).json()["data"]["itens"]
        with acting_as(ACME):
            aprovada = await service.ProcessosService().avaliar_regra(RegraRef(id=regras[0]["id"]))
        contexto_avaliacao = json.dumps(provedor["pedidos"][-3]["messages"], ensure_ascii=False)
        # Outra regra, que leva o agente a outra resposta: reprovada, não entra.
        await app.job(JOB_TASK, element="ler_documento__excecao", kind="TASK_LISTENER", listener="CREATING", variables=caso,
                      user_task={"userTaskKey": "82"}, **comum)
        segunda = (await otto.get("/tarefas", params={"responsavel": "staff", "status": "aberta"})).json()["data"]["items"][0]
        await otto.post("/tarefas/responder", json={"id": segunda["id"], "dados": {**leite, "vencimento": "2026-12-01"},
                                                    "regra": "A Leite Bom vence sempre no primeiro dia do mês seguinte."})
        regras = (await otto.get("/regras", params={"processo": pid})).json()["data"]["itens"]
        with acting_as(ACME):
            reprovada = await service.ProcessosService().avaliar_regra(RegraRef(id=regras[1]["id"]))
        # A execução seguinte: o agente do passo recebe a regra ativa (e não a reprovada).
        provedor["pedidos"].clear()
        lido = await app.job(JOB_AGENT, processo=pid, element="ler_documento", variables=caso, headers={"excecao": "sim"})
        contexto_execucao = json.dumps(provedor["pedidos"][0]["messages"], ensure_ascii=False)
        desligada = (await otto.post("/regras/desativar", json={"id": aprovada.id})).json()["data"]
        desenho = (await app.user(*OWNER).post("/desenho/abrir", json={"processo": pid})).json()["data"]
        return (sem_regra, tarefa, regra_curta, aprovada, reprovada, contexto_avaliacao, lido, contexto_execucao, desligada, desenho,
                app.workflows, [(m.tipo, m.status) for s, m in app.published if s == STAFF_SUBJECT])

    (sem_regra, tarefa, regra_curta, aprovada, reprovada, contexto_avaliacao, lido, contexto_execucao, desligada, desenho,
     workflows, itens) = service_app(cenario)
    assert (sem_regra.status, sem_regra.message) == ("handoff", "O agente não mostrou no documento de onde tirou: vencimento.")
    assert {c["nome"]: c["valor"] for c in tarefa["campos"]} == {**leite, "vencimento": None, "linha_digitavel": None}  # só falta o que ele não achou
    assert tarefa["aprende"] is True and regra_curta.status_code == 422  # exceção de agente ensina; regra sem conteúdo não entra
    assert [w[0] for w in workflows] == ["AvaliarRegraWorkflow.run"] * 2  # a avaliação roda em segundo plano, durável
    assert aprovada.status == "ativa" and aprovada.avaliacao.ok and aprovada.esperado["vencimento"] == "2026-11-15"
    assert "dia 15 do mês seguinte" in contexto_avaliacao  # a avaliação refaz o caso com a regra
    assert reprovada.status == "reprovada" and "vencimento" in reprovada.avaliacao.detalhes[0]
    assert lido.status == "concluido" and "dia 15 do mês seguinte" in contexto_execucao and "primeiro dia" not in contexto_execucao
    assert desligada["status"] == "desativada" and [r["status"] for r in desenho["regras"]] == ["desativada", "reprovada"]
    assert itens.count(("excecao", "aberta")) == 2 and itens.count(("excecao", "concluida")) == 2
