"""svc-conhecimento · lógica de negócio pura. Fonte da verdade: specs/conhecimento.md §3

Trilho (validado no import por @activities): todo método público é async, recebe 1 modelo de schemas.py e retorna 1
modelo de schemas.py (ou é um gerador de pedaços, que não vira activity), e vira a activity "conhecimento.<método>".
O cadastro de itens (RESOURCES) não precisa de código aqui; aqui ficam o briefing com o agente, a busca e as leituras.
"""
import asyncio
import io
import json
import re
import unicodedata
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from pypdf import PdfReader

from core.envelope import ServiceError
from core.http_client import http
from core.llm import AgentStep, llm
from core.nats_bus import bus
from core.plans import plans
from core.resources import ResourceChanged, resources
from core.security import current
from core.storage import storage
from core.surreal import Migration, db
from core.temporal_runner import activities

from schemas import (
    BRIEFING_ABERTURA,
    BRIEFING_INSTRUCOES,
    DOCUMENT_MAX_BYTES,
    DOCUMENT_MAX_ITEMS,
    DOCUMENT_TYPES,
    HISTORY,
    ITEM_CHARS,
    ITENS,
    LEITURAS,
    LIVE_BRIEFING,
    LIVE_LEITURAS,
    MENSAGENS,
    PAGE_MAX_BYTES,
    PASSOS,
    PERFIL,
    SEARCH_RESULTS,
    TOPICOS,
    TRIGGER_SUBJECT,
    WRITERS,
    Achado,
    Achados,
    Briefing,
    BriefingMudou,
    BuscaQuery,
    Conhecimento,
    ConhecimentoSettings,
    Empty,
    KeepRequest,
    Leitura,
    LeituraFalha,
    LeituraMudou,
    LeituraPage,
    LeituraPedido,
    LeituraQuery,
    LeituraRef,
    Mensagem,
    MensagemIn,
    NovoConhecimento,
    Passo,
    Perfil,
    Resumo,
    SiteIn,
    Topico,
    Upload,
    UploadRequest,
)

MIGRATIONS: list[Migration] = []
settings = ConhecimentoSettings()
_respostas: set[asyncio.Task] = set()  # respostas do agente em andamento (quem fecha a tela não perde a resposta)


@activities("conhecimento")
class ConhecimentoService:
    # ── Briefing ─────────────────────────────────────────────────────────────

    async def briefing(self, data: Empty) -> Briefing:
        """O briefing da organização: perfil, tópicos, conversa e se já pode concluir."""
        return await self._briefing()

    async def conversar(self, data: MensagemIn) -> AsyncIterator[Passo | Briefing]:
        """Uma mensagem do cliente: o agente responde usando as ferramentas; cada ferramenta vira um passo na tela."""
        _writer()
        perfil = await self._perfil()
        historico = await self._mensagens()
        leituras = await db.query(
            f"SELECT tipo, origem, status, paginas, created_at FROM {LEITURAS} WHERE tenant = $tenant ORDER BY created_at DESC LIMIT 5"
        )
        await db.create(MENSAGENS, {"papel": "cliente", "texto": data.texto, "passos": []})
        await bus.live(LIVE_BRIEFING, BriefingMudou(action="mensagem"))
        fila: asyncio.Queue[AgentStep | None] = asyncio.Queue()
        resposta = asyncio.create_task(self._responder(data.texto, _contexto(perfil, historico, leituras), fila.put_nowait))
        _respostas.add(resposta)
        resposta.add_done_callback(_respostas.discard)
        resposta.add_done_callback(lambda _: fila.put_nowait(None))
        while (passo := await fila.get()) is not None:
            yield Passo(ferramenta=passo.tool, texto=PASSOS.get(passo.tool, passo.tool), status=passo.status)
        await resposta  # erro do modelo ou do plano sobe aqui (a mensagem do cliente fica gravada)
        yield await self._briefing()

    async def salvar_perfil(self, data: Perfil) -> Briefing:
        """O cliente corrige o perfil: só os campos enviados mudam; vazio apaga."""
        _writer()
        await self._gravar_perfil(data.model_dump(mode="json", exclude_unset=True))
        await bus.live(LIVE_BRIEFING, BriefingMudou(action="perfil"))
        return await self._briefing()

    async def concluir(self, data: Empty) -> Briefing:
        _writer()
        briefing = await self._briefing()
        if not briefing.pode_concluir:
            faltam = ", ".join(t.titulo for t in briefing.topicos if t.status != "feito")
            raise ServiceError("ERRO_CONHECIMENTO_BRIEFING_INCOMPLETO", f"Ainda faltam tópicos do briefing: {faltam}.", status=409)
        row = await self._perfil()
        await db.merge(_ref(PERFIL, row), {"concluido_em": datetime.now(UTC)})
        await bus.live(LIVE_BRIEFING, BriefingMudou(action="concluido"))
        return await self._briefing()

    async def reabrir(self, data: Empty) -> Briefing:
        _writer()
        row = await self._perfil()
        await db.merge(_ref(PERFIL, row), {"concluido_em": None})
        await bus.live(LIVE_BRIEFING, BriefingMudou(action="reaberto"))
        return await self._briefing()

    # ── Busca e workspace ────────────────────────────────────────────────────

    async def buscar(self, data: BuscaQuery) -> Achados:
        """O que os agentes encontram no conhecimento com estas palavras."""
        return Achados(itens=await self._buscar(data.q))

    async def resumo(self, data: Empty) -> Resumo:
        """O passo de briefing e conhecimento da jornada, para o workspace."""
        row = await self._perfil()
        topicos = _topicos(_perfil_de(row))
        fontes = await db.query(f"SELECT fonte, count() AS total FROM {ITENS.table} WHERE tenant = $tenant GROUP BY fonte")
        lendo = await db.query(
            f"SELECT count() AS total FROM (SELECT id FROM {LEITURAS} WHERE tenant = $tenant AND status = 'lendo') GROUP ALL"
        )
        por_fonte = {r["fonte"]: r["total"] for r in fontes}
        return Resumo(
            topicos_feitos=sum(t.status == "feito" for t in topicos),
            topicos_total=len(topicos),
            concluido_em=row.get("concluido_em"),
            itens=sum(por_fonte.values()),
            por_fonte=por_fonte,
            leituras_lendo=lendo[0]["total"] if lendo else 0,
        )

    # ── Leituras: site e documentos ──────────────────────────────────────────

    async def pedir_site(self, data: SiteIn) -> Leitura:
        """Começa a leitura do site (em segundo plano, pelo LeituraWorkflow)."""
        _writer()
        return await self._pedir("site", _site_url(data.url))

    async def documento_upload(self, data: UploadRequest) -> Upload:
        """Link de envio de um documento (PDF, DOCX, TXT, MD ou CSV, até 10 MB); depois a tela chama documento."""
        _writer()
        return await storage.upload(data, accept=DOCUMENT_TYPES, max_bytes=DOCUMENT_MAX_BYTES, folder="documentos")

    async def documento(self, data: KeepRequest) -> Leitura:
        """Confirma o documento enviado e começa a leitura dele."""
        _writer()
        arquivo = await storage.keep(data.key)
        return await self._pedir("documento", arquivo.filename, arquivo=arquivo.model_dump())

    async def leituras(self, data: LeituraQuery) -> LeituraPage:
        return await db.page(LEITURAS, data, LeituraPage)

    async def remover_leitura(self, data: LeituraRef) -> LeituraMudou:
        """Apaga a leitura, os itens que ela criou e o arquivo (se for documento)."""
        _writer()
        row = await self._leitura(data.id)
        removidos = await self._apagar_itens(row.get("item_ids") or [])
        if row.get("arquivo"):
            await storage.delete(row["arquivo"]["key"])
        await db.delete(_ref(LEITURAS, row))
        await self._itens_mudaram(removidos, "removed")
        mudou = LeituraMudou(id=data.id, status="removida")
        await bus.live(LIVE_LEITURAS, mudou)
        return mudou

    # Activities do LeituraWorkflow (workflows.py)

    async def ler_site(self, data: LeituraRef) -> Leitura:
        """Lê até CONHECIMENTO_SITE_PAGES páginas do site, a primeira e as do mesmo site que ela cita."""
        row = await self._leitura(data.id)
        paginas = await _baixar_site(row["origem"], settings.site_pages)
        partes = [(titulo if len(pedacos) == 1 else f"{titulo} ({i}/{len(pedacos)})", pedaco, url)
                  for url, titulo, texto in paginas for pedacos in [_pedacos(texto)] for i, pedaco in enumerate(pedacos, 1)]
        return await self._gravar_leitura(row, partes, paginas=len(paginas), fonte="site")

    async def ler_documento(self, data: LeituraRef) -> Leitura:
        """Extrai o texto do documento guardado e o corta em itens."""
        row = await self._leitura(data.id)
        arquivo = row["arquivo"]
        conteudo = await storage.read(arquivo["key"], max_bytes=DOCUMENT_MAX_BYTES)
        texto, paginas = _texto_documento(conteudo, arquivo["content_type"], arquivo["filename"])
        pedacos = _pedacos(texto)[:DOCUMENT_MAX_ITEMS]
        if not pedacos:
            raise ServiceError("ERRO_CONHECIMENTO_SEM_TEXTO", "O documento não tem texto para ler (é uma imagem escaneada?).", 422)
        nome = arquivo["filename"]
        partes = [(nome if len(pedacos) == 1 else f"{nome} ({i}/{len(pedacos)})", p, nome) for i, p in enumerate(pedacos, 1)]
        return await self._gravar_leitura(row, partes, paginas=paginas, fonte="documento")

    async def falhou(self, data: LeituraFalha) -> LeituraMudou:
        """Tentativas esgotadas: a leitura fica falhou, com o motivo (os itens que já existiam continuam)."""
        row = await db.select(f"{LEITURAS}:{data.id}")
        if row is not None:
            await self._apagar_itens(row.get("item_ids") or [])
            await db.merge(_ref(LEITURAS, row), {"status": "falhou", "erro": data.erro, "item_ids": [], "itens": 0})
        mudou = LeituraMudou(id=data.id, status="falhou")
        await bus.live(LIVE_LEITURAS, mudou)
        return mudou

    # ── Ajudantes ────────────────────────────────────────────────────────────

    async def _responder(self, texto: str, contexto: str, passo: Any) -> None:
        """Roda o agente e grava a resposta (em tarefa própria: segue até o fim mesmo se a tela fechar)."""
        feitos: list[str] = []

        def registrar(step: AgentStep) -> None:
            if step.status == "done" and (rotulo := PASSOS.get(step.tool, step.tool)) not in feitos:
                feitos.append(rotulo)
            passo(step)

        tarefa = f"Nova mensagem do cliente:\n{texto}\n\nRegistre o que ela trouxe e escreva a sua próxima fala para o cliente."
        resultado = await llm.run_agent(settings.model, tarefa, instructions=BRIEFING_INSTRUCOES, tools=self._ferramentas(),
                                        context=contexto, on_step=registrar, max_turns=8)
        resposta = resultado.text.strip() or "Anotei. Pode me contar mais?"
        await db.create(MENSAGENS, {"papel": "agente", "texto": resposta, "passos": feitos})
        await bus.live(LIVE_BRIEFING, BriefingMudou(action="mensagem"))

    def _ferramentas(self) -> list[Any]:
        """As ferramentas do agente de briefing, em nome de quem conversa."""

        async def registrar_perfil(dados: Perfil) -> str:
            """Registra no perfil da empresa o que a pessoa contou. Envie só os campos que ela disse, resumidos."""
            mudancas = dados.model_dump(mode="json", exclude_none=True)  # o agente não apaga: só o cliente, na tela
            if not mudancas:
                return "Nada para registrar."
            perfil = await self._gravar_perfil(mudancas)
            await bus.live(LIVE_BRIEFING, BriefingMudou(action="perfil"))
            return "Registrado. " + _estado(_topicos(perfil))

        async def registrar_conhecimento(dados: NovoConhecimento) -> str:
            """Guarda no conhecimento um detalhe útil que não cabe em nenhum campo do perfil (ex.: regra de aprovação de
            pagamentos, fornecedores principais). O que cabe num campo do perfil vai em registrar_perfil."""
            item = await resources.create(ITENS, Conhecimento(**dados.model_dump(), fonte="briefing", origem="Briefing"))
            return f"Guardado no conhecimento: {item.titulo}."

        async def buscar_conhecimento(consulta: str) -> str:
            """Busca no conhecimento da empresa (site, documentos e briefing) e devolve os trechos mais relevantes."""
            achados = await self._buscar(consulta)
            if not achados:
                return "Nada encontrado no conhecimento."
            return json.dumps([a.model_dump(include={"titulo", "trecho", "fonte", "origem"}) for a in achados], ensure_ascii=False)

        async def ler_site(url: str) -> str:
            """Começa a leitura do site da empresa em segundo plano; as páginas entram no conhecimento em instantes."""
            leitura = await self._pedir("site", _site_url(url))
            return f"Leitura do site {leitura.origem} iniciada."

        return [registrar_perfil, registrar_conhecimento, buscar_conhecimento, ler_site]

    async def _briefing(self) -> Briefing:
        row = await self._perfil()
        perfil = _perfil_de(row)
        topicos = _topicos(perfil)
        return Briefing(
            perfil=perfil,
            topicos=topicos,
            mensagens=[_ABERTURA, *[_mensagem(r) for r in await self._mensagens()]],
            concluido_em=row.get("concluido_em"),
            pode_concluir=all(t.status == "feito" for t in topicos),
        )

    async def _perfil(self) -> dict[str, Any]:
        """O registro do perfil da organização; criado na primeira vez (a chave fixa é única por organização)."""
        rows = await db.query(f"SELECT * FROM {PERFIL} WHERE tenant = $tenant LIMIT 1")
        if rows:
            return rows[0]
        try:
            return await db.create(PERFIL, {"chave": "perfil", "concluido_em": None})
        except ServiceError as exc:  # duas abas ao mesmo tempo: a outra criou primeiro
            if exc.code != "ERRO_RECORD_DUPLICATE":
                raise
            return (await db.query(f"SELECT * FROM {PERFIL} WHERE tenant = $tenant LIMIT 1"))[0]

    async def _gravar_perfil(self, mudancas: dict[str, Any]) -> Perfil:
        row = await self._perfil()
        limpas = {k: (None if v == "" else v) for k, v in mudancas.items() if k in Perfil.model_fields}
        if limpas:
            row = await db.merge(_ref(PERFIL, row), limpas)
        return _perfil_de(row)

    async def _mensagens(self) -> list[dict[str, Any]]:
        rows = await db.query(
            f"SELECT * FROM {MENSAGENS} WHERE tenant = $tenant ORDER BY created_at DESC, id DESC LIMIT $n", n=HISTORY
        )
        return list(reversed(rows))

    async def _buscar(self, consulta: str) -> list[Achado]:
        """Itens que têm qualquer uma das palavras (no título ou no conteúdo), do mais relevante ao menos."""
        palavras = _palavras(consulta)
        if not palavras:
            return []
        conditions, scores, params = [], [], {}
        for i, palavra in enumerate(palavras):
            params[f"p{i}"] = palavra
            for j, campo in enumerate(("titulo", "conteudo")):
                ref = 2 * i + j
                conditions.append(f"{campo} @{ref}@ $p{i}")
                scores.append(f"search::score({ref})")
        rows = await db.query(
            f"SELECT id, titulo, conteudo, fonte, origem, ({' + '.join(scores)}) AS nota FROM {ITENS.table} "
            f"WHERE tenant = $tenant AND ({' OR '.join(conditions)}) ORDER BY nota DESC LIMIT $limite",
            limite=SEARCH_RESULTS, **params,
        )
        return [
            Achado(id=_short(r["id"]), titulo=r["titulo"], trecho=_trecho(r["conteudo"], palavras), fonte=r["fonte"],
                   origem=r.get("origem"), nota=round(float(r.get("nota") or 0), 3))
            for r in rows
        ]

    async def _pedir(self, tipo: str, origem: str, arquivo: dict[str, Any] | None = None) -> Leitura:
        """Grava a leitura e dispara o LeituraWorkflow. A mesma origem ainda em leitura não começa de novo."""
        rows = await db.query(
            f"SELECT * FROM {LEITURAS} WHERE tenant = $tenant AND tipo = $tipo AND origem = $origem AND status = 'lendo' LIMIT 1",
            tipo=tipo, origem=origem,
        )
        if rows and arquivo is None:
            return _leitura_de(rows[0])
        row = await db.create(LEITURAS, {"tipo": tipo, "origem": origem, "arquivo": arquivo, "status": "lendo",
                                         "paginas": 0, "itens": 0, "item_ids": [], "erro": None})
        leitura = _leitura_de(row)
        await bus.publish(TRIGGER_SUBJECT, LeituraPedido(id=leitura.id, tipo=leitura.tipo), msg_id=f"leitura-{leitura.id}")
        await bus.live(LIVE_LEITURAS, LeituraMudou(id=leitura.id, status="lendo"))
        return leitura

    async def _leitura(self, leitura_id: str) -> dict[str, Any]:
        row = await db.select(f"{LEITURAS}:{leitura_id}")
        if row is None:
            raise ServiceError("ERRO_CONHECIMENTO_LEITURA_NAO_ENCONTRADA", "Leitura não encontrada.", status=404)
        return row

    async def _gravar_leitura(self, row: dict[str, Any], partes: list[tuple[str, str, str]], *, paginas: int, fonte: str) -> Leitura:
        """Troca os itens da origem pelos novos: os de leituras anteriores da mesma origem e os de uma tentativa que caiu."""
        mesma_origem = await db.query(
            f"SELECT * FROM {LEITURAS} WHERE tenant = $tenant AND tipo = $tipo AND origem = $origem",
            tipo=row["tipo"], origem=row["origem"],
        )
        anteriores = [r for r in mesma_origem if r["id"] != row["id"]]
        velhos = [i for r in [row, *anteriores] for i in (r.get("item_ids") or [])]
        existentes = await _contar_itens()
        await plans.check("itens", used=existentes - len(velhos), adding=len(partes))
        removidos = await self._apagar_itens(velhos)
        for anterior in anteriores:
            if anterior.get("arquivo") and anterior["arquivo"]["key"] != (row.get("arquivo") or {}).get("key"):
                await storage.delete(anterior["arquivo"]["key"])
            await db.delete(_ref(LEITURAS, anterior))
        ids: list[str] = []
        for titulo, conteudo, origem in partes:
            item = await db.create(ITENS.table, Conhecimento(titulo=titulo[:160], conteudo=conteudo, tipo="empresa",
                                                             fonte=fonte, origem=origem[:300]).model_dump(mode="json"))
            ids.append(_short(item["id"]))
            await db.merge(_ref(LEITURAS, row), {"item_ids": ids})  # tentativa que cair no meio sabe o que apagar
        row = await db.merge(_ref(LEITURAS, row), {"status": "pronta", "paginas": paginas, "itens": len(ids), "erro": None})
        await self._itens_mudaram(removidos + ids, "created")
        await bus.live(LIVE_LEITURAS, LeituraMudou(id=_short(row["id"]), status="pronta"))
        return _leitura_de(row)

    async def _apagar_itens(self, ids: list[str]) -> list[str]:
        for item_id in ids:
            await db.delete(f"{ITENS.table}:{item_id}")
        return list(ids)

    async def _itens_mudaram(self, ids: list[str], action: str) -> None:
        """Um aviso só para a lista de itens (não um por item) e o total para a tela do plano."""
        if not ids:
            return
        await plans.count("itens", await _contar_itens())
        await bus.live(ITENS.live, ResourceChanged(id=ids[-1], action=action))


# ── Funções puras ────────────────────────────────────────────────────────────

_ABERTURA = Mensagem(id="abertura", papel="agente", texto=BRIEFING_ABERTURA)
_LABELS = {name: (info.title or name) for name, info in Perfil.model_fields.items()}
_STOPWORDS = frozenset(
    "a o as os um uma uns umas de do da dos das no na nos nas em por para com sem que se e ou mas como mais menos "
    "ao aos à às é são ser foi era há tem ter isso isto esse essa este esta qual quais quando onde quem sobre "
    "the and for with".split()
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template", "iframe", "head", "form", "button", "select"})
_BLOCK_TAGS = frozenset({"p", "div", "li", "ul", "ol", "br", "tr", "td", "th", "section", "article", "header", "footer",
                         "nav", "main", "aside", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "dd", "dt"})
_FILE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|ico|pdf|zip|rar|mp4|mp3|avi|mov|docx?|xlsx?|pptx?|css|js|json|xml)$", re.I)
_PRIORITY = re.compile(r"sobre|quem-somos|empresa|institucional|servi[cç]o|produto|solu[cç]|contato|atendimento|about|"
                       r"services|products|pre[cç]o|planos|faq|duvidas", re.I)


def _writer() -> None:
    who = current()
    if who is None or not (who.is_system or WRITERS & who.roles):
        raise ServiceError("ERRO_CONHECIMENTO_FORBIDDEN", "Só donos e administradores mexem no briefing e no conhecimento.", 403)


def _short(record_id: Any) -> str:
    """"conhecimento_leituras:⟨abc⟩" → "abc": na API, o id é só a chave."""
    return str(record_id).partition(":")[2].strip("⟨⟩`") if ":" in str(record_id) else str(record_id)


def _ref(table: str, row: dict[str, Any]) -> str:
    return f"{table}:{_short(row['id'])}"


def _perfil_de(row: dict[str, Any]) -> Perfil:
    return Perfil.model_validate({k: row.get(k) for k in Perfil.model_fields if row.get(k) is not None})


def _topicos(perfil: Perfil) -> list[Topico]:
    valores = perfil.model_dump()
    topicos = []
    for t in TOPICOS:
        preenchidos = [c for c in t.campos if valores.get(c) not in (None, "")]
        faltam = [_LABELS[c] for c in t.obrigatorios if valores.get(c) in (None, "")]
        status = "feito" if not faltam else ("em_andamento" if preenchidos else "a_fazer")
        topicos.append(Topico(id=t.id, titulo=t.titulo, status=status, faltam=faltam))
    return topicos


def _estado(topicos: list[Topico]) -> str:
    pendentes = [f"{t.titulo} (falta: {', '.join(t.faltam)})" for t in topicos if t.status != "feito"]
    return "Tópicos pendentes: " + "; ".join(pendentes) if pendentes else "Todos os tópicos estão feitos."


def _mensagem(row: dict[str, Any]) -> Mensagem:
    return Mensagem(id=_short(row["id"]), papel=row["papel"], texto=row["texto"], passos=row.get("passos") or [],
                    created_at=row.get("created_at"))


def _contexto(perfil_row: dict[str, Any], historico: list[dict[str, Any]], leituras: list[dict[str, Any]]) -> str:
    perfil = _perfil_de(perfil_row)
    preenchido = [f"- {_LABELS[k]} ({k}): {v}" for k, v in perfil.model_dump(exclude_none=True).items()]
    linhas = [f"Hoje: {datetime.now(UTC):%Y-%m-%d}.", "Perfil até agora:", *(preenchido or ["- (vazio)"])]
    linhas += ["Tópicos:"] + [
        f"- {t.titulo}: {'feito' if t.status == 'feito' else 'falta ' + ', '.join(t.faltam)}" for t in _topicos(perfil)
    ]
    if leituras:
        linhas += ["Leituras recentes:"] + [f"- {r['tipo']} {r['origem']}: {r['status']}" for r in leituras]
    if perfil_row.get("concluido_em"):
        linhas.append("O briefing já foi concluído; a pessoa pode estar completando ou corrigindo informações.")
    linhas += ["Conversa até aqui (da mais antiga para a mais nova):", f"Agente: {BRIEFING_ABERTURA}"]
    linhas += [f"{'Cliente' if r['papel'] == 'cliente' else 'Agente'}: {r['texto']}" for r in historico]
    return "\n".join(linhas)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _palavras(consulta: str) -> list[str]:
    vistas: list[str] = []
    for palavra in re.findall(r"\w+", consulta.lower()):
        if len(palavra) >= 3 and palavra not in _STOPWORDS and palavra not in vistas:
            vistas.append(palavra)
    return vistas[:8]


def _trecho(conteudo: str, palavras: list[str], tamanho: int = 400) -> str:
    """O pedaço do conteúdo em volta da primeira palavra encontrada."""
    base = _sem_acento(conteudo)
    posicoes = [p for p in (base.find(_sem_acento(w)) for w in palavras) if p >= 0]
    inicio = max(0, min(posicoes) - tamanho // 4) if posicoes else 0
    trecho = conteudo[inicio:inicio + tamanho].strip()
    return ("…" if inicio else "") + trecho + ("…" if inicio + tamanho < len(conteudo) else "")


def _pedacos(texto: str, limite: int = ITEM_CHARS) -> list[str]:
    """Texto em pedaços de até `limite` caracteres, juntando parágrafos; parágrafo enorme é cortado entre frases."""
    pedacos, atual = [], ""
    for paragrafo in (p.strip() for p in re.split(r"\n", texto)):
        while paragrafo:
            espaco = limite - len(atual) - (1 if atual else 0)
            if len(paragrafo) <= espaco:
                atual = f"{atual}\n{paragrafo}" if atual else paragrafo
                break
            if espaco < limite // 4:  # pouco espaço sobrando: fecha o pedaço e recomeça
                pedacos.append(atual)
                atual = ""
                continue
            corte = paragrafo.rfind(". ", 0, espaco)
            corte = corte + 1 if corte > espaco // 2 else espaco
            parte, paragrafo = paragrafo[:corte].strip(), paragrafo[corte:].strip()
            pedacos.append(f"{atual}\n{parte}" if atual else parte)
            atual = ""
    if atual:
        pedacos.append(atual)
    return [p for p in pedacos if len(p) >= 2]


def _leitura_de(row: dict[str, Any]) -> Leitura:
    return Leitura.model_validate({**row, "id": _short(row["id"])})


async def _contar_itens() -> int:
    rows = await db.query(f"SELECT count() AS total FROM (SELECT id FROM {ITENS.table} WHERE tenant = $tenant) GROUP ALL")
    return rows[0]["total"] if rows else 0


def _site_url(url: str) -> str:
    """Endereço do site com esquema (https:// se não veio) e sem fragmento; recusa o que não é site."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname or "." not in partes.hostname or partes.username:
        raise ServiceError("ERRO_CONHECIMENTO_URL", "Endereço de site inválido.", status=422)
    return urldefrag(url)[0]


class _LeitorHtml(HTMLParser):
    """Texto visível, título e links de uma página (sem script, estilo, formulário nem cabeçalho técnico)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titulo, self.descricao, self.links = "", "", []
        self._partes: list[str] = []
        self._pular, self._no_titulo = 0, False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        valores = dict(attrs)
        if tag == "title":
            self._no_titulo = True
        elif tag == "meta" and (valores.get("name") or "").lower() == "description":
            self.descricao = (valores.get("content") or "").strip()
        elif tag in _SKIP_TAGS:
            self._pular += 1
        elif tag == "a" and valores.get("href"):
            self.links.append(valores["href"] or "")
        if tag in _BLOCK_TAGS:
            self._partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._no_titulo = False
        elif tag in _SKIP_TAGS and self._pular:
            self._pular -= 1
        if tag in _BLOCK_TAGS:
            self._partes.append("\n")

    def handle_data(self, data: str) -> None:
        if self._no_titulo:
            self.titulo += data
        elif not self._pular:
            self._partes.append(data)

    def linhas(self) -> list[str]:
        texto = "".join(self._partes)
        return [re.sub(r"\s+", " ", linha).strip() for linha in texto.split("\n") if len(linha.strip()) >= 3]


async def _baixar(url: str) -> tuple[str, str] | str:
    """(endereço final, HTML), seguindo até 4 redirecionamentos, cada um conferido pelo http_client; senão, o motivo."""
    for _ in range(5):
        resposta = await http.get(url, allow_http=True, max_bytes=PAGE_MAX_BYTES,
                                  headers={"User-Agent": "Mozilla/5.0 (compatible; CogniventureBot/1.0)", "Accept": "text/html"})
        if resposta.status_code in (301, 302, 303, 307, 308) and resposta.headers.get("location"):
            url = urljoin(url, resposta.headers["location"])
            continue
        if resposta.status_code != 200:
            return f"o site respondeu HTTP {resposta.status_code}"
        tipo = resposta.headers.get("content-type", "").split(";")[0].strip()
        if "html" not in tipo:
            return f"o endereço não é uma página ({tipo or 'sem tipo'})"
        return url, resposta.text
    return "redirecionamentos demais"


def _mesmo_site(a: str, b: str) -> bool:
    host = lambda u: (urlsplit(u).hostname or "").removeprefix("www.")  # noqa: E731
    return host(a) == host(b)


async def _baixar_site(inicio: str, limite: int) -> list[tuple[str, str, str]]:
    """[(endereço, título, texto)] da página inicial e das páginas do mesmo site que ela cita, até `limite` páginas.
    Linhas que já apareceram numa página anterior (menu, rodapé) saem das seguintes."""
    try:
        primeira = await _baixar(inicio)
    except ServiceError:
        raise
    except httpx.HTTPError:
        raise ServiceError("ERRO_CONHECIMENTO_SITE", "O site não respondeu. Confira o endereço.", status=422) from None
    if isinstance(primeira, str):
        raise ServiceError("ERRO_CONHECIMENTO_SITE", f"Não consegui ler o site: {primeira}.", status=422)
    fila, vistas, paginas, linhas_vistas = [primeira], {urldefrag(primeira[0])[0]}, [], set()
    while fila and len(paginas) < limite:
        url, html = fila.pop(0)
        leitor = _LeitorHtml()
        leitor.feed(html)
        linhas = [linha for linha in leitor.linhas() if linha not in linhas_vistas]
        linhas_vistas.update(linhas)
        texto = "\n".join(([leitor.descricao] if leitor.descricao and not paginas else []) + linhas)
        if texto.strip():
            titulo = re.sub(r"\s+", " ", leitor.titulo).strip() or urlsplit(url).path or url
            paginas.append((url, titulo, texto))
        if len(paginas) == 1 and not fila:  # links só da primeira página, os mais prováveis primeiro
            candidatas = []
            for href in leitor.links:
                alvo = urldefrag(urljoin(url, href.strip()))[0]
                if (alvo.startswith(("http://", "https://")) and _mesmo_site(alvo, url) and alvo not in vistas
                        and not _FILE_EXT.search(urlsplit(alvo).path)):
                    vistas.add(alvo)
                    candidatas.append(alvo)
            candidatas.sort(key=lambda a: (not _PRIORITY.search(a), len(a)))
            for alvo in candidatas[: limite - 1]:
                try:
                    baixada = await _baixar(alvo)
                except (ServiceError, httpx.HTTPError):
                    continue
                if not isinstance(baixada, str):
                    fila.append(baixada)
    if not paginas:
        raise ServiceError("ERRO_CONHECIMENTO_SITE", "O site não tem texto para ler.", status=422)
    return paginas


def _texto_documento(conteudo: bytes, tipo: str, nome: str) -> tuple[str, int]:
    """(texto, páginas) de PDF, DOCX ou texto puro."""
    try:
        if tipo == "application/pdf":
            leitor = PdfReader(io.BytesIO(conteudo))
            return "\n\n".join((pagina.extract_text() or "") for pagina in leitor.pages), len(leitor.pages)
        if tipo.endswith("wordprocessingml.document"):
            with zipfile.ZipFile(io.BytesIO(conteudo)) as docx:
                raiz = ElementTree.fromstring(docx.read("word/document.xml"))
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragrafos = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in raiz.iter(f"{ns}p")]
            return "\n".join(paragrafos), 1
        return conteudo.decode("utf-8", errors="replace"), 1
    except Exception:
        raise ServiceError("ERRO_CONHECIMENTO_DOCUMENTO", f"Não consegui abrir {nome}: o arquivo parece corrompido.", 422) from None
