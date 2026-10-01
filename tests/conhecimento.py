"""svc-conhecimento · testes sem infraestrutura. Fonte da verdade: specs/conhecimento.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória, com o SurrealDB embutido, NATS, Temporal e
plano de mentira. O agente de briefing roda no laço de verdade (core/llm.py + AgentExo) contra um provedor falso;
o site é servido por um transporte falso e o armazenamento de documentos por dublês.

Rodar (da raiz): PYTHONPATH=services/svc-conhecimento uv run python -m pytest tests/conhecimento.py
"""
import io
import json
import zipfile

import httpx
import pytest
from pydantic import ValidationError

from core import http_client
from core.http_client import http
from core.llm import RESOLVE_SUBJECT, Resolved, llm
from core.security import Principal, acting_as
from core.storage import StoredFile, storage
from core.testing import service_app

from schemas import BUSCA_SUBJECT, CONTEXTO_SUBJECT, TRIGGER_SUBJECT, BuscaQuery, Empty, LeituraFalha, LeituraPedido, LeituraRef, MensagemIn, NovoConhecimento, Perfil

OWNER = ("ana", "acme", "owner")
ACME = Principal(sub="ana", tenant="acme", roles=frozenset({"owner"}))
COMPLETO = {
    "atividade": "Padaria artesanal com café", "segmento": "padaria", "porte": "micro", "cidade": "Poços de Caldas",
    "produtos": "Pães, bolos e café", "clientes": "Moradores do bairro e empresas", "recebimentos": "Pix e cartão",
    "pagamentos": "Boleto de fornecedores", "sistemas": "Planilha e maquininha", "documentos": "NF por e-mail",
    "colaboradores": 12, "dores": "Conciliar o caixa toma o dia todo",
}


def _sse(texto: str) -> list[tuple[str, dict]]:
    eventos = []
    for bloco in texto.strip().split("\n\n"):
        linhas = dict(linha.split(": ", 1) for linha in bloco.splitlines() if ": " in linha)
        if "event" in linhas:
            eventos.append((linhas["event"], json.loads(linhas["data"])))
    return eventos


# ── Briefing: perfil, tópicos e conclusão ────────────────────────────────────

def test_briefing_comeca_com_a_abertura_e_conclui_so_com_os_topicos_feitos():
    async def cenario(app):
        ana, mel = app.user(*OWNER), app.user("mel", "acme", "member")
        inicio = (await ana.get("/briefing")).json()["data"]
        parcial = await ana.post("/briefing/perfil", json={"segmento": "padaria", "atividade": "Pães e bolos"})
        cedo = await ana.post("/briefing/concluir", json={})
        await ana.post("/briefing/perfil", json=COMPLETO)
        concluido = await ana.post("/briefing/concluir", json={})
        apagado = await ana.post("/briefing/perfil", json={"dores": ""})  # vazio apaga e reabre o tópico
        reaberto = await ana.post("/briefing/reabrir", json={})
        membro_le, membro_escreve = await mel.get("/briefing"), await mel.post("/briefing/perfil", json={"uf": "MG"})
        invalido = await ana.post("/briefing/perfil", json={"porte": "gigante", "senha": "x"})
        da_beta = (await app.user("bia", "beta", "owner").get("/briefing")).json()["data"]
        return inicio, parcial, cedo, concluido, apagado, reaberto, membro_le, membro_escreve, invalido, da_beta, app.live

    inicio, parcial, cedo, concluido, apagado, reaberto, membro_le, membro_escreve, invalido, da_beta, live = service_app(cenario)
    assert inicio["mensagens"][0]["id"] == "abertura" and inicio["mensagens"][0]["papel"] == "agente"
    assert {t["status"] for t in inicio["topicos"]} == {"a_fazer"} and inicio["pode_concluir"] is False
    negocio = parcial.json()["data"]["topicos"][0]
    assert (negocio["status"], negocio["faltam"]) == ("em_andamento", ["Porte"])
    assert cedo.status_code == 409 and cedo.json()["error"]["code"] == "ERRO_CONHECIMENTO_BRIEFING_INCOMPLETO"
    assert concluido.status_code == 200 and concluido.json()["data"]["concluido_em"]
    assert apagado.json()["data"]["perfil"].get("dores") is None and apagado.json()["data"]["pode_concluir"] is False
    assert reaberto.json()["data"]["concluido_em"] is None
    assert membro_le.status_code == 200 and membro_escreve.status_code == 403
    assert invalido.status_code == 422
    assert da_beta["perfil"] == {k: None for k in Perfil.model_fields}  # cada organização tem o seu
    assert ("conhecimento.briefing", "concluido") in [(topic, action) for topic, _, action in live]


# ── Conversa: o agente de verdade (AgentExo) contra um provedor falso ────────

def _provedor_falso(pedidos: list[dict]):
    """Primeira volta: chama registrar_perfil e registrar_conhecimento; segunda: responde com texto."""

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pedidos.append(body)
        uso = {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        if body["messages"][-1]["role"] != "tool":
            chamadas = [
                {"id": "c1", "type": "function", "function": {"name": "registrar_perfil",
                 "arguments": json.dumps({"segmento": "padaria", "cidade": "Poços de Caldas", "porte": None})}},
                {"id": "c2", "type": "function", "function": {"name": "registrar_conhecimento",
                 "arguments": json.dumps({"titulo": "Aprovação de pagamentos", "conteudo": "Acima de R$ 2.000 a dona aprova.",
                                          "tipo": "processo"})}},
            ]
            mensagem = {"role": "assistant", "content": None, "tool_calls": chamadas}
            return httpx.Response(200, json={"id": "1", "object": "chat.completion", "created": 0, "model": body["model"],
                                             "choices": [{"index": 0, "message": mensagem, "finish_reason": "tool_calls"}], "usage": uso})
        texto = "Anotei! E como vocês recebem dos clientes?"
        return httpx.Response(200, json={"id": "2", "object": "chat.completion", "created": 0, "model": body["model"],
                                         "choices": [{"index": 0, "message": {"role": "assistant", "content": texto},
                                                      "finish_reason": "stop"}], "usage": uso})

    return responder


@pytest.fixture
def provedor():
    pedidos: list[dict] = []
    salvo = llm._transport
    llm._transport = httpx.MockTransport(_provedor_falso(pedidos))
    llm.clear()
    yield pedidos
    llm._transport = salvo
    llm.clear()


def test_conversa_roda_o_agente_que_preenche_o_perfil_e_guarda_conhecimento_em_passos(provedor):
    async def cenario(app):
        app.respond(RESOLVE_SUBJECT, lambda pedido: Resolved(
            provider="cv", scope="platform", model="modelo-falso", base_url="https://ia.exemplo.com/v1", api_key="sk-x"))
        ana = app.user(*OWNER)
        resposta = await ana.post("/briefing/mensagem", json={"texto": "Somos uma padaria em Poços de Caldas."})
        itens = (await ana.get("/itens")).json()["data"]["items"]
        return resposta, itens, app.published, app.requests

    resposta, itens, published, requests = service_app(cenario)
    eventos = _sse(resposta.text)
    passos = [(dados["ferramenta"], dados["status"]) for evento, dados in eventos if evento == "delta"]
    assert passos == [("registrar_perfil", "running"), ("registrar_perfil", "done"),
                      ("registrar_conhecimento", "running"), ("registrar_conhecimento", "done")]
    assert eventos[0][1]["texto"] == "Anotando no perfil"
    final = eventos[-1]
    assert final[0] == "done"
    briefing = final[1]["data"]
    assert (briefing["perfil"]["segmento"], briefing["perfil"]["cidade"]) == ("padaria", "Poços de Caldas")
    assert briefing["perfil"]["porte"] is None  # null do modelo não apaga nem inventa
    assert [(m["papel"], m["texto"][:6]) for m in briefing["mensagens"]] == [
        ("agente", "Olá! S"), ("cliente", "Somos "), ("agente", "Anotei")]
    assert briefing["mensagens"][-1]["passos"] == ["Anotando no perfil", "Guardando no conhecimento"]
    assert [(i["titulo"], i["fonte"], i["tipo"]) for i in itens] == [("Aprovação de pagamentos", "briefing", "processo")]
    contexto = json.dumps(provedor[0]["messages"], ensure_ascii=False)
    assert "Conversa até aqui" in contexto and "O negócio: falta O que a empresa faz, Segmento, Porte" in contexto
    nomes = [t["function"]["name"] for t in provedor[0]["tools"]]
    assert nomes == ["registrar_perfil", "registrar_conhecimento", "buscar_conhecimento", "ler_site"]
    assert "segmento" in provedor[0]["tools"][0]["function"]["parameters"]["properties"]  # o perfil achatado
    assert [s for s, _ in published].count("events.ai.usage") == 2  # uma volta, um uso


def test_conversa_sem_modelo_disponivel_guarda_a_mensagem_e_devolve_o_erro():
    async def cenario(app):
        ana = app.user(*OWNER)  # ninguém responde o rpc.ai.resolve: o svc-ai fora do ar
        resposta = await ana.post("/briefing/mensagem", json={"texto": "Oi"})
        membro = await app.user("mel", "acme", "member").post("/briefing/mensagem", json={"texto": "Oi"})
        return resposta, (await ana.get("/briefing")).json()["data"], membro

    resposta, briefing, membro = service_app(cenario)
    evento, dados = _sse(resposta.text)[-1]
    assert evento == "error" and dados["error"]["code"]
    assert [m["papel"] for m in briefing["mensagens"]] == ["agente", "cliente"]  # a do cliente ficou
    assert _sse(membro.text) == [("error", _sse(membro.text)[0][1])]  # recusado antes de gravar ou chamar o agente
    assert _sse(membro.text)[0][1]["error"]["code"] == "ERRO_CONHECIMENTO_FORBIDDEN"


# ── Busca ─────────────────────────────────────────────────────────────────────

def test_busca_acha_por_qualquer_palavra_com_trecho_e_so_na_organizacao():
    async def cenario(app):
        ana, bia = app.user(*OWNER), app.user("bia", "beta", "owner")
        for titulo, conteudo in (
            ("Pagamentos", "Fornecedores são pagos por boleto toda sexta-feira. Acima de R$ 2.000 a dona aprova."),
            ("Horário", "A padaria abre às 6h e fecha às 20h."),
            ("Entregas", "Entregamos pães para empresas do bairro, com pagamento mensal."),
        ):
            await ana.post("/itens", json={"titulo": titulo, "conteudo": conteudo})
        await bia.post("/itens", json={"titulo": "Pagamentos da Beta", "conteudo": "Segredo da Beta: boleto"})
        return [await ana.get("/busca", params={"q": q}) for q in ("como pagamos o boleto", "padaria horário", "xyz", "a")]

    boleto, horario, nada, curta = service_app(cenario)
    achados = boleto.json()["data"]["itens"]
    assert [a["titulo"] for a in achados][0] == "Pagamentos" and "Beta" not in json.dumps(achados)
    assert "boleto" in achados[0]["trecho"]
    assert horario.json()["data"]["itens"][0]["titulo"] == "Horário"
    assert nada.json()["data"]["itens"] == [] and curta.status_code == 422


# ── Leitura do site ───────────────────────────────────────────────────────────

MENU = "<nav><a href='/'>Início</a> <a href='/sobre'>Sobre nós</a> <a href='/contato'>Contato</a></nav>"
PAGINAS = {
    "/": f"<html><head><title>Padaria Aurora</title><meta name='description' content='Pães artesanais desde 1990'>"
         f"<script>var x = 1;</script></head><body>{MENU}<h1>Padaria Aurora</h1><p>Pães de fermentação natural.</p>"
         f"<a href='/sobre'>Conheça</a><a href='/cardapio.pdf'>Cardápio</a><a href='https://instagram.com/aurora'>Insta</a>"
         f"<footer>Rua das Flores, 10 - Poços de Caldas</footer></body></html>",
    "/sobre": f"<html><head><title>Sobre</title></head><body>{MENU}<p>Fundada em 1990 pela família Silva.</p>"
              f"<footer>Rua das Flores, 10 - Poços de Caldas</footer></body></html>",
    "/contato": f"<html><head><title>Contato</title></head><body>{MENU}<p>WhatsApp (35) 99999-0000.</p></body></html>",
}


def _site(pedidos: list[str]):
    def servir(request: httpx.Request) -> httpx.Response:
        pedidos.append(str(request.url))
        if request.url.host == "aurora.com.br":  # sem www: redireciona
            return httpx.Response(301, headers={"location": f"https://www.aurora.com.br{request.url.path}"})
        if request.url.host != "www.aurora.com.br" or request.url.path not in PAGINAS:
            return httpx.Response(404, text="não achei")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGINAS[request.url.path])

    return servir


@pytest.fixture
def site(monkeypatch):
    pedidos: list[str] = []

    async def publico(url, **kwargs):  # o DNS de verdade não existe aqui; a conferência de SSRF tem teste no core
        return None

    monkeypatch.setattr(http_client, "assert_public_url", publico)
    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(_site(pedidos)), follow_redirects=False))
    return pedidos


def test_leitura_do_site_vira_itens_sem_menu_repetido_e_ler_de_novo_troca_os_itens(site):
    async def cenario(app):
        ana = app.user(*OWNER)
        pedida = (await ana.post("/site", json={"url": "aurora.com.br"})).json()["data"]
        de_novo = (await ana.post("/site", json={"url": "aurora.com.br"})).json()["data"]  # ainda lendo: a mesma
        gatilho = next(m for s, m in app.published if s == TRIGGER_SUBJECT)
        await app.handlers[TRIGGER_SUBJECT](gatilho)  # o NATS entrega: vira workflow
        with acting_as(ACME):
            pronta = await app.main.svc.ler_site(LeituraRef(id=pedida["id"]))
        itens = (await ana.get("/itens", params={"sort": "titulo"})).json()["data"]["items"]
        segunda = (await ana.post("/site", json={"url": "https://aurora.com.br"})).json()["data"]
        with acting_as(ACME):
            await app.main.svc.ler_site(LeituraRef(id=segunda["id"]))
        depois = (await ana.get("/itens")).json()["data"]["total"]
        leituras = (await ana.get("/leituras")).json()["data"]["items"]
        invalida = await ana.post("/site", json={"url": "nada"})
        return pedida, de_novo, gatilho, app.workflows, pronta, itens, depois, leituras, invalida

    pedida, de_novo, gatilho, workflows, pronta, itens, depois, leituras, invalida = service_app(cenario)
    assert (pedida["status"], pedida["origem"]) == ("lendo", "https://aurora.com.br") and de_novo["id"] == pedida["id"]
    assert gatilho == LeituraPedido(id=pedida["id"], tipo="site") and [w for w, _ in workflows] == ["LeituraWorkflow.run"]
    assert (pronta.status, pronta.paginas, pronta.itens) == ("pronta", 3, 3)
    assert [i["titulo"] for i in itens] == ["Contato", "Padaria Aurora", "Sobre"]
    por_titulo = {i["titulo"]: i for i in itens}
    assert "Pães artesanais desde 1990" in por_titulo["Padaria Aurora"]["conteudo"]  # a descrição entra na primeira
    assert "var x" not in json.dumps(itens) and por_titulo["Padaria Aurora"]["fonte"] == "site"
    assert "Sobre nós" not in por_titulo["Sobre"]["conteudo"] and "Rua das Flores" not in por_titulo["Sobre"]["conteudo"]
    assert por_titulo["Sobre"]["origem"] == "https://www.aurora.com.br/sobre"
    assert not any("cardapio.pdf" in p or "instagram" in p for p in site)  # nem arquivo nem outro site
    assert depois == 3 and [(lt["status"], lt["itens"]) for lt in leituras] == [("pronta", 3)]  # trocou, não somou
    assert invalida.status_code == 422


def test_site_fora_do_ar_e_tentativas_esgotadas_deixam_a_leitura_como_falhou(site):
    async def cenario(app):
        ana = app.user(*OWNER)
        pedida = (await ana.post("/site", json={"url": "https://outro.com.br"})).json()["data"]
        with acting_as(ACME):
            with pytest.raises(Exception) as erro:
                await app.main.svc.ler_site(LeituraRef(id=pedida["id"]))
            await app.main.svc.falhou(LeituraFalha(id=pedida["id"], erro=erro.value.message))
        return (await ana.get("/leituras")).json()["data"]["items"][0]

    leitura = service_app(cenario)
    assert (leitura["status"], leitura["erro"]) == ("falhou", "Não consegui ler o site: o site respondeu HTTP 404.")


# ── Documentos ────────────────────────────────────────────────────────────────

def _docx(*paragrafos: str) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    corpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragrafos)
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{corpo}</w:body></w:document>')
    return saida.getvalue()


def _pdf(*linhas: str) -> bytes:
    conteudo = "BT /F1 12 Tf 20 100 Td " + " ".join(f"({linha}) Tj 0 -16 Td" for linha in linhas) + " ET"
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(conteudo)}>>stream\n{conteudo}\nendstream", "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    saida, posicoes = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        posicoes.append(len(saida))
        saida += f"{i} 0 obj{obj}endobj\n".encode()
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{p:010d} 00000 n \n".encode() for p in posicoes)
    return saida + f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF".encode()


@pytest.fixture
def arquivos(monkeypatch):
    """Armazenamento de mentira: o que o navegador enviou fica num dicionário pela chave."""
    guardados: dict[str, tuple[str, str, bytes]] = {}
    apagados: list[str] = []

    async def keep(key):
        nome, tipo, conteudo = guardados[key]
        return StoredFile(key=key, filename=nome, content_type=tipo, size=len(conteudo))

    async def read(key, *, max_bytes):
        return guardados[key][2]

    async def delete(key):
        apagados.append(key)

    monkeypatch.setattr(storage, "keep", keep)
    monkeypatch.setattr(storage, "read", read)
    monkeypatch.setattr(storage, "delete", delete)
    return guardados, apagados


def test_documentos_viram_itens_e_remover_a_leitura_apaga_itens_e_arquivo(arquivos):
    guardados, apagados = arquivos
    chave = "t/acme/svc-conhecimento/documentos/" + "{:032x}"
    guardados[chave.format(1)] = ("politica.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                  _docx("Política de compras", "Toda compra acima de R$ 500 precisa de 3 cotações."))
    guardados[chave.format(2)] = ("precos.pdf", "application/pdf", _pdf("Tabela de precos 2026", "Pao frances: R$ 18,90 o kg"))
    guardados[chave.format(3)] = ("escaneado.pdf", "application/pdf", _pdf())
    guardados[chave.format(4)] = ("notas.md", "text/markdown", ("# Notas\n\n" + "Linha de nota. " * 700).encode())

    async def cenario(app):
        ana = app.user(*OWNER)
        leituras = [(await ana.post("/documentos", json={"key": chave.format(i)})).json()["data"] for i in range(1, 5)]
        resultados = []
        with acting_as(ACME):
            for leitura in leituras:
                try:
                    resultados.append((await app.main.svc.ler_documento(LeituraRef(id=leitura["id"]))).itens)
                except Exception as exc:
                    resultados.append(exc.code)
        itens = (await ana.get("/itens", params={"fonte": "documento", "size": 50})).json()["data"]["items"]
        busca = (await ana.get("/busca", params={"q": "cotações compra"})).json()["data"]["itens"]
        listada = (await ana.get("/leituras", params={"sort": "origem"})).json()["data"]["items"]
        assert all(":" not in lt["id"] for lt in listada)  # a lista devolve a chave, como a criação
        removida = await ana.post("/leituras/remove", json={"id": next(lt["id"] for lt in listada if lt["origem"] == "politica.docx")})
        resto = (await ana.get("/itens", params={"fonte": "documento"})).json()["data"]["total"]
        resumo = (await ana.get("/resumo")).json()["data"]
        return resultados, itens, busca, removida, resto, resumo

    resultados, itens, busca, removida, resto, resumo = service_app(cenario)
    assert resultados == [1, 1, "ERRO_CONHECIMENTO_SEM_TEXTO", 3]  # 10 mil caracteres viram 3 itens
    assert "Pao frances: R$ 18,90 o kg" in next(i["conteudo"] for i in itens if i["titulo"] == "precos.pdf")
    assert {i["titulo"] for i in itens} >= {"politica.docx", "notas.md (1/3)", "notas.md (3/3)"}
    assert all(len(i["conteudo"]) <= 4500 for i in itens)
    assert busca[0]["titulo"] == "politica.docx"
    assert removida.json()["data"]["status"] == "removida" and apagados == [chave.format(1)]
    assert resto == 4 and resumo["por_fonte"] == {"documento": 4} and resumo["topicos_total"] == 6


def test_rpc_de_contexto_e_busca_para_outros_servicos_na_organizacao_de_quem_pede():
    async def cenario(app):
        await app.user(*OWNER).post("/briefing/perfil", json=COMPLETO)
        await app.user(*OWNER).post("/itens", json={"titulo": "Pagamentos", "conteudo": "Boleto toda sexta"})
        with acting_as(ACME):
            contexto = await app.handlers[CONTEXTO_SUBJECT](Empty())
            achados = await app.handlers[BUSCA_SUBJECT](BuscaQuery(q="boleto"))
        with acting_as(Principal(sub="bia", tenant="beta", roles=frozenset({"owner"}))):
            da_beta = await app.handlers[BUSCA_SUBJECT](BuscaQuery(q="boleto"))
        return contexto, achados, da_beta

    contexto, achados, da_beta = service_app(cenario)
    assert contexto.perfil.segmento == "padaria" and sum(t.status == "feito" for t in contexto.topicos) == 6
    assert contexto.concluido_em is None
    assert [a.titulo for a in achados.itens] == ["Pagamentos"] and da_beta.itens == []


def test_modelos_de_entrada_recusam_campo_nao_declarado():
    assert NovoConhecimento(titulo="Equipe", conteudo="Ana e Bia", tipo="equipe").tipo == "outro"  # tipo inventado
    with pytest.raises(ValidationError):
        MensagemIn.model_validate({"texto": "oi", "papel": "agente"})
    with pytest.raises(ValidationError):
        Perfil.model_validate({"senha": "x"})
