"""svc-financeiro · lógica de negócio pura. Fonte da verdade: specs/financeiro.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py. As ações do pacote (schemas.ACTIONS) são métodos de mesmo nome: o worker do motor de processos
(core/processes.py) as chama como a organização do processo, com a entrada vinda dos passos anteriores.
"""
import re
from typing import Any

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.nats_bus import bus
from core.processes import Handoff
from core.resources import resources
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    AGENDAR_SUBJECT,
    CONTA_PADRAO,
    FORNECEDORES,
    LIVE_TITULOS,
    TITULOS,
    Agendamento,
    AgendarPagamento,
    Classificacao,
    Comprovante,
    Conciliacao,
    Conferencia,
    Documento,
    Fornecedor,
    Pagamento,
    PagamentoAgendado,
    Titulo,
    TituloMudou,
    TituloPage,
    TituloQuery,
)

MIGRATIONS: list[Migration] = []


@activities("financeiro")
class FinanceiroService:
    # ── Ações do contas a pagar (o motor chama) ──────────────────────────────

    async def conferir_pedido(self, data: Documento) -> Conferencia:
        """Fornecedor conhecido? O valor bate com o contrato dele? Sem valor no documento não dá para conferir."""
        if data.valor is None:
            raise Handoff("O documento não trouxe o valor: não dá para conferir.")
        fornecedor = await _fornecedor(data)
        if fornecedor is None:
            return Conferencia(divergente=False, diferenca=0, pedido=None, fornecedor_novo=True)
        contrato = fornecedor.get("valor_contrato")
        if not contrato:
            return Conferencia(divergente=False, diferenca=0, pedido=None, fornecedor_novo=False)
        diferenca = round(data.valor - float(contrato), 2)
        return Conferencia(divergente=abs(diferenca) > max(1.0, float(contrato) * 0.01), diferenca=diferenca,
                           pedido=f"Contrato {fornecedor['nome']}", fornecedor_novo=False)

    async def classificar(self, data: Documento) -> Classificacao:
        """A conta do fornecedor; fornecedor novo entra no cadastro com a conta padrão (a próxima nota já não é nova)."""
        fornecedor = await _fornecedor(data)
        if fornecedor is None:
            if not data.fornecedor:
                return Classificacao(conta=CONTA_PADRAO, centro_custo=None)
            try:
                await resources.create(FORNECEDORES, Fornecedor(nome=data.fornecedor[:200], cnpj=data.cnpj))
            except ServiceError as exc:
                if exc.code != "ERRO_RECORD_DUPLICATE":  # outro processo cadastrou o mesmo fornecedor agora
                    raise
            return Classificacao(conta=CONTA_PADRAO, centro_custo=None)
        return Classificacao(conta=fornecedor.get("conta") or CONTA_PADRAO, centro_custo=fornecedor.get("centro_custo"))

    async def agendar_pagamento(self, data: Pagamento) -> Agendamento:
        """Agenda no banco conectado da organização (svc-integracoes) e abre o título a pagar."""
        try:
            agendado = await bus.request(AGENDAR_SUBJECT, AgendarPagamento(
                valor=data.valor, vencimento=data.vencimento, fornecedor=data.fornecedor, linha_digitavel=data.linha_digitavel,
            ), PagamentoAgendado, timeout=10)
        except NatsError:
            raise ServiceError("ERRO_FINANCEIRO_BANCO_FORA", "O serviço de integrações não respondeu.", 503) from None
        row = await db.create(TITULOS, {"fornecedor": data.fornecedor, "valor": data.valor, "vencimento": data.vencimento,
                                        "data": agendado.data, "pagamento_id": agendado.pagamento_id, "status": "agendado"})
        await bus.live(LIVE_TITULOS, TituloMudou(id=Titulo.model_validate(row).id, action="agendado"))
        return Agendamento(pagamento_id=agendado.pagamento_id, data=agendado.data)

    async def conciliar(self, data: Comprovante) -> Conciliacao:
        """O banco confirmou: o título agendado com este pagamento fica pago."""
        rows = await db.query(f"SELECT * FROM {TITULOS} WHERE tenant = $tenant AND pagamento_id = $p LIMIT 1", p=data.pagamento_id)
        if not rows:
            raise Handoff(f"O pagamento {data.pagamento_id} não está nos títulos agendados.")
        titulo = Titulo.model_validate(rows[0])
        if titulo.status != "pago":
            await db.merge(f"{TITULOS}:{titulo.id}", {"status": "pago"})
            await bus.live(LIVE_TITULOS, TituloMudou(id=titulo.id, action="pago"))
        return Conciliacao(conciliado=True, diferenca=0)

    # ── Tela ─────────────────────────────────────────────────────────────────

    async def titulos(self, data: TituloQuery) -> TituloPage:
        return await db.page(TITULOS, data, TituloPage)


async def _fornecedor(data: Documento) -> dict[str, Any] | None:
    """O fornecedor do documento: pelo CNPJ (só os dígitos) e, sem ele, pelo nome."""
    digitos = re.sub(r"\D", "", data.cnpj or "")
    if digitos:
        rows = await db.query(f"SELECT * FROM {FORNECEDORES.table} WHERE tenant = $tenant")
        achado = next((r for r in rows if re.sub(r"\D", "", r.get("cnpj") or "") == digitos), None)
        if achado:
            return achado
    if data.fornecedor:
        rows = await db.query(f"SELECT * FROM {FORNECEDORES.table} WHERE tenant = $tenant AND string::lowercase(nome) = $n LIMIT 1",
                              n=data.fornecedor.strip().lower())
        return rows[0] if rows else None
    return None
