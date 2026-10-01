"""svc-processos · lógica de negócio pura. Fonte da verdade: specs/processos.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py (ou é um gerador de pedaços, que não vira activity), e vira a activity "processos.<método>".
O perfil e o conhecimento da empresa vêm do svc-conhecimento por RPC (rpc.conhecimento.*), na organização de quem age.
"""
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from nats.errors import Error as NatsError

from core.envelope import ServiceError
from core.llm import AgentStep, llm
from core.nats_bus import bus
from core.security import current
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    BIBLIOTECA,
    BUSCA_SUBJECT,
    CONTEXTO_SUBJECT,
    DESCOBERTA_INSTRUCOES,
    DESCRICAO_INSTRUCOES,
    LIVE_PROCESSOS,
    PASSOS,
    PROCESSOS,
    WRITERS,
    Achados,
    Biblioteca,
    BuscaQuery,
    ContextoEmpresa,
    Descoberta,
    Descricao,
    Empty,
    PassoAgente,
    Processo,
    ProcessoDescrito,
    ProcessoMudou,
    ProcessoPage,
    ProcessoQuery,
    ProcessoRef,
    ProcessosSettings,
    Resumo,
    Sugestao,
)

MIGRATIONS: list[Migration] = []
settings = ProcessosSettings()
_MODELOS = {m.id: m for m in BIBLIOTECA}


@activities("processos")
class ProcessosService:
    async def biblioteca(self, data: Empty) -> Biblioteca:
        """Os modelos de processo que a Cogniventure executa (os mesmos para toda organização)."""
        return Biblioteca(itens=BIBLIOTECA)

    async def listar(self, data: ProcessoQuery) -> ProcessoPage:
        return await db.page(PROCESSOS, data, ProcessoPage)

    async def resumo(self, data: Empty) -> Resumo:
        """O passo de descoberta da jornada, para o workspace."""
        rows = await db.query(f"SELECT status, count() AS total FROM {PROCESSOS} WHERE tenant = $tenant GROUP BY status")
        total = {r["status"]: r["total"] for r in rows}
        return Resumo(sugeridos=total.get("sugerido", 0), aceitos=total.get("aceito", 0), recusados=total.get("recusado", 0))

    async def descobrir(self, data: Empty) -> AsyncIterator[PassoAgente | Descoberta]:
        """O agente de descoberta lê o perfil e sugere processos da biblioteca, com o porquê; cada ferramenta é um passo."""
        _writer()
        contexto = await _contexto_da_empresa()
        if not any(t.get("status") == "feito" for t in contexto.topicos):
            raise ServiceError("ERRO_PROCESSOS_SEM_BRIEFING", "Faça o briefing antes: ainda não há nada sobre a empresa.", 409)
        existentes = await _todos()
        sugeridos: list[str] = []
        fila: asyncio.Queue[AgentStep | None] = asyncio.Queue()
        ferramentas = [_buscar_conhecimento, _sugerir(sugeridos)]
        tarefa = asyncio.create_task(llm.run_agent(
            settings.model,
            "Sugira os processos da biblioteca que fazem sentido para esta empresa, chamando sugerir_processo para cada um, "
            "e escreva no fim o resumo para o cliente.",
            instructions=DESCOBERTA_INSTRUCOES, tools=ferramentas, context=_contexto(contexto, existentes),
            on_step=fila.put_nowait, max_turns=10,
        ))
        tarefa.add_done_callback(lambda _: fila.put_nowait(None))
        while (passo := await fila.get()) is not None:
            yield PassoAgente(ferramenta=passo.tool, texto=PASSOS.get(passo.tool, passo.tool), status=passo.status)
        resultado = await tarefa
        processos = [p for p in await _todos() if p.id in sugeridos]
        texto = resultado.text.strip() or (f"Sugeri {len(processos)} processos." if processos else "Não encontrei processos da biblioteca para sugerir agora.")
        yield Descoberta(texto=texto, processos=processos)

    async def descrever(self, data: Descricao) -> Processo:
        """O cliente descreve um processo próprio: o agente organiza e o processo nasce aceito."""
        _writer()
        registrados: list[Processo] = []

        async def registrar_processo(dados: ProcessoDescrito) -> str:
            """Registra o processo descrito pelo cliente, organizado (chame uma única vez)."""
            if registrados:
                return "Já registrado."
            row = await db.create(PROCESSOS, {"modelo": dados.modelo, "area": dados.area, "titulo": dados.titulo,
                                              "descricao": dados.descricao, "motivo": None, "origem": "cliente",
                                              "status": "aceito", "prioridade": "media"})
            registrados.append(_processo(row))
            return f"Registrado: {dados.titulo}."

        catalogo = "\n".join(f"- {m.id} ({m.area}): {m.titulo}. {m.resumo}" for m in BIBLIOTECA)
        await llm.run_agent(settings.model, f"Processo descrito pelo cliente:\n{data.texto}", instructions=DESCRICAO_INSTRUCOES,
                            tools=[registrar_processo], context=f"Biblioteca:\n{catalogo}", max_turns=3)
        if not registrados:
            raise ServiceError("ERRO_PROCESSOS_DESCRICAO", "Não consegui organizar a descrição. Conte o gatilho, o que acontece e quem participa.", 422)
        await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=registrados[0].id, action="descrito"))
        return registrados[0]

    async def aceitar(self, data: ProcessoRef) -> Processo:
        return await _mudar(data.id, "aceito")

    async def recusar(self, data: ProcessoRef) -> Processo:
        return await _mudar(data.id, "recusado")


# ── Ajudantes ────────────────────────────────────────────────────────────────

def _writer() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_PROCESSOS_FORBIDDEN", "Só donos e administradores mexem nos processos.", 403)


def _short(record_id: Any) -> str:
    """"processos_processos:⟨abc⟩" → "abc": na API, o id é só a chave."""
    return str(record_id).partition(":")[2].strip("⟨⟩`") if ":" in str(record_id) else str(record_id)


def _processo(row: dict[str, Any]) -> Processo:
    return Processo.model_validate({**row, "id": _short(row["id"])})


async def _todos() -> list[Processo]:
    rows = await db.query(f"SELECT * FROM {PROCESSOS} WHERE tenant = $tenant ORDER BY created_at")
    return [_processo(r) for r in rows]


async def _mudar(processo_id: str, status: str) -> Processo:
    _writer()
    if await db.select(f"{PROCESSOS}:{processo_id}") is None:
        raise ServiceError("ERRO_PROCESSOS_NAO_ENCONTRADO", "Processo não encontrado.", status=404)
    processo = _processo(await db.merge(f"{PROCESSOS}:{processo_id}", {"status": status}))
    await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=processo.id, action=status))
    return processo


async def _contexto_da_empresa() -> ContextoEmpresa:
    try:
        return await bus.request(CONTEXTO_SUBJECT, Empty(), ContextoEmpresa, timeout=10)
    except (NatsError, TimeoutError):
        raise ServiceError("ERRO_PROCESSOS_SEM_CONHECIMENTO", "O conhecimento da empresa não respondeu. Tente de novo em instantes.", 503) from None


async def _buscar_conhecimento(consulta: str) -> str:
    """Busca no conhecimento da empresa (site, documentos e briefing) e devolve os trechos mais relevantes."""
    try:
        achados = await bus.request(BUSCA_SUBJECT, BuscaQuery(q=consulta), Achados, timeout=10)
    except (NatsError, TimeoutError):
        return "O conhecimento não respondeu agora; siga com o perfil."
    if not achados.itens:
        return "Nada encontrado no conhecimento."
    return json.dumps([{k: a.get(k) for k in ("titulo", "trecho", "fonte")} for a in achados.itens], ensure_ascii=False)


def _sugerir(sugeridos: list[str]) -> Any:
    async def sugerir_processo(dados: Sugestao) -> str:
        """Sugere à empresa um processo da biblioteca, com o motivo (o que no briefing mostra que serve)."""
        modelo = _MODELOS[dados.modelo]
        rows = await db.query(f"SELECT * FROM {PROCESSOS} WHERE tenant = $tenant AND modelo = $modelo LIMIT 1", modelo=dados.modelo)
        if rows and rows[0]["status"] != "sugerido":
            return f"{modelo.titulo} já foi {rows[0]['status']} pela empresa; não sugira de novo."
        campos = {"motivo": dados.motivo, "prioridade": dados.prioridade}
        if rows:
            row = await db.merge(f"{PROCESSOS}:{_short(rows[0]['id'])}", campos)
        else:
            row = await db.create(PROCESSOS, {"modelo": modelo.id, "area": modelo.area, "titulo": modelo.titulo,
                                              "descricao": modelo.resumo, "origem": "sugestao", "status": "sugerido", **campos})
        processo = _processo(row)
        if processo.id not in sugeridos:
            sugeridos.append(processo.id)
        await bus.live(LIVE_PROCESSOS, ProcessoMudou(id=processo.id, action="sugerido"))
        return f"Sugerido: {modelo.titulo}."

    return sugerir_processo


def _contexto(empresa: ContextoEmpresa, existentes: list[Processo]) -> str:
    perfil = [f"- {k}: {v}" for k, v in empresa.perfil.items() if v not in (None, "")]
    linhas = ["Perfil da empresa:", *(perfil or ["- (vazio)"]), "", "Biblioteca (id, área, título — o que faz; sinais):"]
    linhas += [f"- {m.id} ({m.area}): {m.titulo} — {m.resumo} Gatilho: {m.gatilho}. Sinais: {'; '.join(m.sinais)}."
               for m in BIBLIOTECA]
    linhas += ["", "Processos da empresa:"]
    linhas += [f"- {p.modelo or p.titulo}: {p.status}" for p in existentes] or ["- (nenhum ainda)"]
    return "\n".join(linhas)
