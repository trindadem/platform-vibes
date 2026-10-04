"""svc-juridico · testes sem infraestrutura. Fonte da verdade: specs/juridico.md §2 e §4

Pelo kit do core (core/testing.py): o main.py de verdade em memória. As ações rodam pelo worker de verdade
(app.job: job do motor → handler → resultado), como a organização do processo.

Rodar (da raiz): PYTHONPATH=services/svc-juridico uv run python -m pytest tests/juridico.py
"""
from datetime import date, timedelta

from core.processes import CATALOG_SUBJECT
from core.security import acting_as, system
from core.testing import service_app

from schemas import ACTIONS, SERVICE

OWNER = ("ana", "acme", "owner")


def test_pacote_declara_as_acoes_e_os_modelos_do_juridico():
    async def cenario(app):
        return [m for s, m in app.published if s == CATALOG_SUBJECT], sorted(app.jobs)

    catalogos, jobs = service_app(cenario)
    catalogo = catalogos[0]
    assert catalogo.service == "svc-juridico" and jobs == sorted(a.name for a in catalogo.actions)
    assert {m.id for m in catalogo.models} == {"gestao-contratos", "publicacoes-processos", "certidoes-negativas"}
    contratos = next(m for m in catalogo.models if m.id == "gestao-contratos")
    assert (contratos.fluxo.gatilho.tipo, contratos.fluxo.gatilho.processo, contratos.fluxo.gatilho.resultado) == (
        "processo", "proposta-comercial", "aceita")  # a cadeia: proposta aceita → contrato
    assert all(a.example for a in ACTIONS)


def test_arquivar_o_contrato_com_a_vigencia_e_o_que_depende_de_integracao_vai_ao_staff():
    async def cenario(app):
        termos = {"parte": "Padaria Pão Quente", "cnpj": "11.222.333/0001-44", "objeto": "Fornecimento semanal de pães",
                  "valor": 4800.0, "inicio": "2026-10-10", "vigencia_meses": 6}
        arquivado = await app.job("juridico.arquivar_contrato", element="arquivar", variables={"entrada": termos})
        sem_fim = await app.job("juridico.arquivar_contrato", variables={"entrada": {**termos, "inicio": "2026-01-31", "vigencia_meses": 1}})
        faltando = await app.job("juridico.arquivar_contrato", variables={"entrada": {"valor": 10}})
        assinar = await app.job("juridico.coletar_assinaturas", element="assinar", headers={"excecao": "sim"},
                                variables={"entrada": {"parte": "Padaria Pão Quente", "email": "compras@paoquente.com.br"}})
        consultar = await app.job("juridico.consultar_publicacoes", headers={"excecao": "sim"}, variables={"entrada": {"cnpj": "00.000.000/0001-00"}})
        contratos = (await app.user(*OWNER).get("/contratos", params={"sort": "fim"})).json()["data"]["items"]
        da_beta = (await app.user("bia", "beta", "owner").get("/contratos")).json()["data"]["total"]
        return arquivado, sem_fim, faltando, assinar, consultar, contratos, da_beta

    arquivado, sem_fim, faltando, assinar, consultar, contratos, da_beta = service_app(cenario)
    assert arquivado.variables["resultado"]["fim"] == "2027-04-10" and arquivado.variables["resultado"]["aviso_em"] == "2027-02-09"
    assert sem_fim.variables["resultado"]["fim"] == "2026-02-28"  # 31/01 + 1 mês: o último dia de fevereiro
    assert faltando.status == "handoff" and "parte" in faltando.message and "objeto" in faltando.message
    assert assinar.status == "handoff" and "compras@paoquente.com.br" in assinar.message  # o staff colhe as assinaturas
    assert consultar.status == "handoff" and "00.000.000/0001-00" in consultar.message
    assert [(c["parte"], c["status"], c["fim"]) for c in contratos] == [
        ("Padaria Pão Quente", "vigente", "2026-02-28"), ("Padaria Pão Quente", "vigente", "2027-04-10")]
    assert da_beta == 0


def test_prazo_processual_em_dias_uteis_sem_feriados_nem_recesso():
    async def cenario(app):
        async def prazo(disponibilizada, dias):
            return await app.job("juridico.calcular_prazo", variables={"entrada": {"disponibilizada_em": disponibilizada, "dias_prazo": dias}})

        # Sexta 09/10/2026: o dia 12 é feriado; publicada na terça 13, o prazo conta da quarta 14.
        comum = await prazo("2026-10-09", 5)
        # Carnaval (16 e 17/02/2026) e Sexta-feira Santa (03/04/2026) não contam.
        carnaval = await prazo("2026-02-12", 3)
        # Recesso forense: de 20/12 a 20/01 nada conta.
        recesso = await prazo("2026-12-17", 2)
        sem_data = await prazo(None, 15)
        return comum, carnaval, recesso, sem_data

    comum, carnaval, recesso, sem_data = service_app(cenario)
    assert comum.variables["resultado"] == {"publicada_em": "2026-10-13", "prazo_final": "2026-10-20", "dias_uteis": 5}
    assert carnaval.variables["resultado"]["publicada_em"] == "2026-02-13"
    assert carnaval.variables["resultado"]["prazo_final"] == "2026-02-20"  # 18, 19 e 20 (o 16 e o 17 são Carnaval)
    assert recesso.variables["resultado"]["publicada_em"] == "2026-12-18"
    assert recesso.variables["resultado"]["prazo_final"] == "2027-01-22"  # 21/01 e 22/01: depois do recesso
    assert sem_data.status == "handoff"


def test_certidoes_guardadas_e_avisos_antes_de_vencer(monkeypatch):
    import service

    avisos = []

    async def roles(*papeis, **aviso):
        avisos.append((papeis, aviso["title"], aviso["key"]))

    monkeypatch.setattr(service.notify, "roles", roles)

    async def cenario(app):
        hoje = date.today()
        guardadas = await app.job("juridico.registrar_certidoes", variables={"entrada": {
            "positivas": 1, "validade": (hoje + timedelta(days=15)).isoformat(), "resumo": "Trabalhista positiva"}})
        sem_validade = await app.job("juridico.registrar_certidoes", variables={"entrada": {"positivas": 0}})
        await app.job("juridico.arquivar_contrato", variables={"entrada": {
            "parte": "Moinho Sul", "objeto": "Farinha", "fim": (hoje + timedelta(days=60)).isoformat()}})
        await app.job("juridico.arquivar_contrato", variables={"entrada": {
            "parte": "Gráfica", "objeto": "Embalagens", "fim": (hoje + timedelta(days=200)).isoformat(),
            "reajuste_em": (hoje + timedelta(days=30)).isoformat()}})
        with acting_as(system(SERVICE)):
            feitos = await service.JuridicoService().avisar(service.Empty())
        certidoes = (await app.user(*OWNER).get("/certidoes")).json()["data"]["items"]
        return guardadas, sem_validade, feitos, certidoes

    guardadas, sem_validade, feitos, certidoes = service_app(cenario)
    assert guardadas.status == "concluido" and sem_validade.status == "handoff"
    assert certidoes[0]["positivas"] == 1 and certidoes[0]["resumo"] == "Trabalhista positiva"
    assert (feitos.contratos, feitos.certidoes) == (2, 1)
    titulos = sorted(t for _, t, _ in avisos)
    assert titulos == ["Certidões vencem em 15 dias", "Contrato com Gráfica tem reajuste em 30 dias", "Contrato com Moinho Sul vence em 60 dias"]
    assert all(papeis == ("owner", "admin") for papeis, _, _ in avisos) and len({k for _, _, k in avisos}) == 3
