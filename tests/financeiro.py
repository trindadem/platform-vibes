"""svc-financeiro · testes sem infraestrutura. Fonte da verdade: specs/financeiro.md §2 e §4

Rodar (da raiz): PYTHONPATH=services/svc-financeiro uv run python -m pytest tests/financeiro.py
"""
from core.processes import CATALOG_SUBJECT
from core.testing import service_app

from schemas import ACTIONS


def test_pacote_declara_as_acoes_do_contas_a_pagar_no_boot():
    async def cenario(app):
        return [m for s, m in app.published if s == CATALOG_SUBJECT]

    catalogos = service_app(cenario)
    assert len(catalogos) == 1 and catalogos[0].service == "svc-financeiro"
    acoes = {a.name: a for a in catalogos[0].actions}
    assert set(acoes) == {"financeiro.conferir_pedido", "financeiro.classificar", "financeiro.agendar_pagamento", "financeiro.conciliar"}
    assert acoes["financeiro.agendar_pagamento"].risk == "irreversivel" and acoes["financeiro.agendar_pagamento"].connections == ["Banco"]
    assert "divergente" in acoes["financeiro.conferir_pedido"].output_fields
    assert all(a.example for a in ACTIONS)
