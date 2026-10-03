"""svc-integracoes · testes sem infraestrutura. Fonte da verdade: specs/integracoes.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. O Mailpit (aviso + mensagem RFC 822) e o
armazenamento de arquivos são dublês; o banco simulado roda de verdade, menos o timer do Temporal (app.workflows).

Rodar (da raiz): PYTHONPATH=services/svc-integracoes uv run python -m pytest tests/integracoes.py
"""
from email.message import EmailMessage

import httpx
import pytest

from core.http_client import http
from core.security import Principal, acting_as
from core.storage import StoredFile, storage
from core.testing import service_app

import service
from schemas import AGENDAR_SUBJECT, DOCUMENTO_SUBJECT, EVENT_SUBJECT, AgendarPagamento, DocumentoRef, PagamentoRef

OWNER = ("ana", "acme", "owner")


def _pdf(texto: str) -> bytes:
    """PDF mínimo com uma linha de texto (o pypdf lê a camada de texto)."""
    stream = f"BT /F1 12 Tf 40 760 Td ({texto}) Tj ET".encode()
    objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    saida, posicoes = b"%PDF-1.4\n", []
    for i, obj in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1) + b"".join(b"%010d 00000 n \n" % p for p in posicoes)
    return saida + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)


def _email(para: str, anexo: bytes | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "Moinho Sul <cobranca@moinho.com>", para, "Boleto de outubro"
    msg.set_content("Segue o boleto do mês.")
    if anexo is not None:
        msg.add_attachment(anexo, maintype="application", subtype="pdf", filename="boleto-outubro.pdf")
    return msg.as_bytes()


@pytest.fixture
def fora(monkeypatch):
    """Mailpit e armazenamento de mentira: mensagens por id e arquivos em memória."""
    estado = {"mensagens": {}, "arquivos": {}}
    monkeypatch.setattr(service.settings, "mailpit_url", "http://mailpit:8025")

    async def get(url, **kwargs):
        assert kwargs.get("allow_private") and kwargs.get("allow_http")  # só o receptor local usa rede interna
        bruto = estado["mensagens"].get(url.rsplit("/", 2)[-2])
        return httpx.Response(200, content=bruto) if bruto else httpx.Response(404)

    async def save(data, *, filename, content_type, max_bytes, folder="files"):
        chave = f"t/x/svc-integracoes/{folder}/{len(estado['arquivos']):032x}"
        estado["arquivos"][chave] = data
        return StoredFile(key=chave, filename=filename, content_type=content_type, size=len(data))

    async def delete(key):
        estado["arquivos"].pop(key, None)

    monkeypatch.setattr(http, "get", get)
    monkeypatch.setattr(storage, "save", save)
    monkeypatch.setattr(storage, "delete", delete)
    monkeypatch.setattr(storage, "url", lambda key, **kw: f"https://arquivos/{key}")
    return estado


def test_email_na_caixa_de_entrada_vira_documento_e_evento_uma_vez_so(fora):
    async def cenario(app):
        ana = app.user(*OWNER)
        caixa = (await ana.post("/conexoes", json={"tipo": "caixa_entrada"})).json()["data"]
        de_novo = await ana.post("/conexoes", json={"tipo": "caixa_entrada"})
        membro = await app.user("mel", "acme", "member").post("/conexoes", json={"tipo": "banco_simulado"})
        beta = (await app.user("bia", "beta", "owner").post("/conexoes", json={"tipo": "caixa_entrada"})).json()["data"]
        endereco, codigo_errado = caixa["endereco"], caixa["endereco"].replace(".", ".0", 1)[:-1]
        fora["mensagens"]["m1"] = _email(endereco, _pdf("Moinho Sul R$ 1.250,00 vence 2026-10-15"))
        fora["mensagens"]["m2"] = _email(f"{codigo_errado}, {beta['endereco']}")  # só o corpo, para a beta
        interno = app.anonymous()  # o Mailpit chama sem token, pela rede interna
        primeiro = (await interno.post("/entrada/mailpit", json={"ID": "m1", "Subject": "x"})).json()["data"]
        repetido = (await interno.post("/entrada/mailpit", json={"ID": "m1"})).json()["data"]
        outro = (await interno.post("/entrada/mailpit", json={"ID": "m2"})).json()["data"]
        sumido = await interno.post("/entrada/mailpit", json={"ID": "m9"})
        docs = (await ana.get("/documentos")).json()["data"]
        doc = docs["items"][0]
        with acting_as(Principal(sub="system:svc-processos", tenant="acme", roles=frozenset({"system"}))):
            lido = await app.handlers[DOCUMENTO_SUBJECT](DocumentoRef(id=doc["id"]))
        with acting_as(Principal(sub="system:svc-processos", tenant="beta", roles=frozenset({"system"}))):
            with pytest.raises(Exception) as alheio:
                await app.handlers[DOCUMENTO_SUBJECT](DocumentoRef(id=doc["id"]))
        link = (await ana.get("/documentos/arquivo", params={"id": doc["id"]})).json()["data"]
        resumo = (await ana.get("/resumo")).json()["data"]
        return caixa, de_novo, membro, primeiro, repetido, outro, sumido, docs, lido, alheio.value, link, resumo, app.published

    caixa, de_novo, membro, primeiro, repetido, outro, sumido, docs, lido, alheio, link, resumo, publicados = service_app(cenario)
    assert caixa["endereco"].startswith("acme.") and caixa["endereco"].endswith("@entrada.localhost")
    assert de_novo.json()["error"]["code"] == "ERRO_INTEGRACOES_JA_CONECTADA" and membro.status_code == 403
    assert (primeiro, repetido, outro) == ({"documentos": 1}, {"documentos": 0}, {"documentos": 1})
    assert sumido.status_code == 404
    assert docs["total"] == 1 and docs["items"][0]["nome"] == "boleto-outubro.pdf" and docs["items"][0]["tem_texto"] is True
    assert "1.250,00" in lido.texto and lido.assunto == "Boleto de outubro"
    assert getattr(alheio, "code", "") == "ERRO_INTEGRACOES_NAO_ENCONTRADO"  # documento de outra organização não existe
    assert link["url"].startswith("https://arquivos/") and link["nome"] == "boleto-outubro.pdf"
    assert resumo["caixa_entrada"] == caixa["endereco"] and resumo["documentos"] == 1 and resumo["banco"] is False
    eventos = [m for s, m in publicados if s == EVENT_SUBJECT]
    assert [e.nome for e in eventos] == ["documento.recebido", "documento.recebido"]  # um da acme, um da beta
    assert eventos[0].dados["documento_id"] == docs["items"][0]["id"] and eventos[0].dados["origem"] == "email"


def test_banco_simulado_agenda_e_confirma_avisando_o_processo(fora):
    async def cenario(app):
        ana = app.user(*OWNER)
        sistema = Principal(sub="system:svc-financeiro", tenant="acme", roles=frozenset({"system"}))
        with acting_as(sistema):
            with pytest.raises(Exception) as sem_banco:
                await app.handlers[AGENDAR_SUBJECT](AgendarPagamento(valor=1250, vencimento="2099-10-15"))
        await ana.post("/conexoes", json={"tipo": "banco_simulado", "confirmar_apos": 5})
        with acting_as(sistema):
            agendado = await app.handlers[AGENDAR_SUBJECT](AgendarPagamento(valor=1250, vencimento="2099-10-15", fornecedor="Moinho Sul"))
            vencido = await app.handlers[AGENDAR_SUBJECT](AgendarPagamento(valor=90, vencimento="2001-01-01"))
        lista = (await ana.get("/pagamentos", params={"status": "agendado"})).json()["data"]
        pagamento = next(p for p in lista["items"] if p["pagamento_id"] == agendado.pagamento_id)
        membro = await app.user("mel", "acme", "member").post("/pagamentos/confirmar", json={"id": pagamento["id"]})
        operador = await app.user("otto", "acme", "operador").post("/pagamentos/confirmar", json={"id": pagamento["id"]})
        with acting_as(sistema):  # o timer do banco simulado dispara depois: já pago, não avisa de novo
            await service.IntegracoesService().confirmar_pagamento(PagamentoRef(id=pagamento["id"]))
        return sem_banco.value, agendado, vencido, lista, membro, operador.json()["data"], app.workflows, app.published

    sem_banco, agendado, vencido, lista, membro, pago, workflows, publicados = service_app(cenario)
    assert getattr(sem_banco, "code", "") == "ERRO_INTEGRACOES_SEM_BANCO"
    assert agendado.pagamento_id.startswith("PG-") and agendado.data == "2099-10-15"
    assert vencido.data != "2001-01-01"  # vencido: agenda para hoje
    assert lista["total"] == 2 and membro.status_code == 403
    assert pago["status"] == "pago" and pago["pago_em"]
    assert [w[0] for w in workflows] == ["PagamentoSimuladoWorkflow.run"] * 2 and workflows[0][1].segundos == 5
    eventos = [m for s, m in publicados if s == EVENT_SUBJECT]
    assert [(e.nome, e.chave) for e in eventos] == [("banco.pago", agendado.pagamento_id)]
    assert eventos[0].dados["valor"] == 1250
