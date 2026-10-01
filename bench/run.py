"""Banco de provas da meta layer (README §7): mede quanto um modelo de código acerta, de primeira, dentro dos trilhos.

    set -a; . <arquivo fora do repositório com AWS_BEARER_TOKEN_BEDROCK>; set +a
    uv run python bench/run.py --model qwen-30b                    # todas as tarefas, até 3 tentativas cada
    uv run python bench/run.py --model qwen-next --tasks crm-contatos,vendas-orcamentos --attempts 1
    uv run python bench/run.py --reference                         # confere as tarefas com as soluções de referência

Cada tarefa (bench/tasks/<id>.yaml) é um módulo de negócio: o spec e uma prova de aceitação que o modelo não vê. Numa
cópia do repositório, o spec vira specs/<serviço>.md, o service.sh gera o esqueleto e o modelo recebe o pacote de
contexto: os trechos do README que importam, as docstrings do core, o índice do catálogo, os arquivos do serviço e um
módulo resolvido de exemplo (a referência de outra tarefa; --no-example tira).
Ele devolve os arquivos que mudam (só os do próprio serviço). Os trilhos conferem: contrato (gateway/contracts.py),
testes do serviço, prova de aceitação e npm run check. Falhou: o modelo recebe os erros e tenta de novo.
Resultado em bench/results/<data>-<modelo>.md e .json: passou de primeira, em quantas tentativas, tokens, tempo e
linhas escritas pelo modelo (o que a meta layer ainda não gera).

Ferramenta de desenvolvimento: chama o provedor direto (Bedrock ou API compatível com a da OpenAI) com a chave do
ambiente de quem roda; nenhum serviço importa daqui. A chave nunca vai para arquivo do repositório nem para o relatório.
"""
import argparse
import ast
import asyncio
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "bench" / "tasks"
RESULTS = ROOT / "bench" / "results"

# Apelido → (provedor, modelo, região). Bedrock com a chave de API (AWS_BEARER_TOKEN_BEDROCK).
MODELS = {
    "qwen-30b": ("bedrock", "qwen.qwen3-coder-30b-a3b-v1:0", "us-east-1"),
    "qwen-next": ("bedrock", "qwen.qwen3-coder-next", "us-east-1"),
    "qwen-480b": ("bedrock", "qwen.qwen3-coder-480b-a35b-v1:0", "us-west-2"),
}
MAX_OUTPUT_TOKENS = 16_000
FEEDBACK_CHARS = 4_000

# Trechos do README que o modelo recebe (cabeçalhos, na ordem): o resto do guia não muda o que ele escreve.
README_SECTIONS = (
    "## Princípios", "## 2. Convenção de Nomes", "### 5.1 ", "### 5.2 ", "### 5.3 ", "### 5.5 ", "### 5.6 ", "### 5.9 ",
    "### 5.12 ", "### 5.13 ", "### 5.15 ", "### 5.17 ", "### 5.19 ", "## 6. ",
)
CORE_DOCS = ("resources", "plans", "surreal", "notify", "testing", "security")
# Módulo resolvido que o modelo vê como exemplo (a referência de outra tarefa): cadastro, ação com regra, testes e tela.
EXAMPLES = ("financeiro-recebiveis", "vendas-orcamentos")

SYSTEM = """Você é um desenvolvedor do CV-Frame, um framework com trilhos rígidos. Implemente o spec pedido seguindo o
guia ao pé da letra:
- Prefira declarar a escrever código: cadastro é um Resource no schemas.py (core/resources.py); módulo e limites são o
  MODULE (core/plans.py). Só escreva código para regra de negócio.
- Use só APIs que aparecem no guia e nas docstrings do core; não invente funções, parâmetros nem arquivos.
- Use exatamente os nomes do spec (campos, rotas, códigos de erro, títulos).
- Respeite a regra dos 4 arquivos, os manifestos do gateway e as regras do frontend (páginas só compõem o catálogo).
Responda com no máximo 5 linhas de plano e depois só os arquivos que mudam, inteiros, no formato:
<<<FILE caminho/relativo/do/arquivo
conteúdo completo do arquivo
FILE>>>"""

FILE_BLOCK = re.compile(r"<<<FILE[ \t]+(\S+)[ \t]*\n(.*?)\n?FILE>>>", re.DOTALL)
FENCE = re.compile(r"^\s*```[a-zA-Z]*\n(.*?)\n```\s*$", re.DOTALL)


@dataclass
class Task:
    id: str
    level: int
    service: str
    title: str
    spec: str
    acceptance: str
    reference: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Task":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**{k: data[k] for k in ("id", "level", "service", "title", "spec", "acceptance")}, reference=data.get("reference") or {})

    def allowed(self, path: str) -> bool:
        s = re.escape(self.service)
        return bool(
            re.fullmatch(rf"services/svc-{s}/(schemas|service|workflows|main)\.py", path)
            or path in (f"gateway/endpoints/{self.service}.yaml", f"tests/{self.service}.py")
            or re.fullmatch(rf"frontend/src/modules/{s}(/([a-z][a-z0-9]*(-[a-z0-9]+)*|\[[a-z][a-zA-Z0-9]*\])){{0,2}}/page\.tsx", path)
        )


@dataclass
class Attempt:
    number: int
    checks: dict[str, bool]
    seconds: float
    tokens_in: int = 0
    tokens_out: int = 0
    files: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    failures: str = ""


@dataclass
class Outcome:
    task: str
    level: int
    passed_at: int | None
    attempts: list[Attempt]
    lines_written: int = 0
    error: str = ""


# ── Provedor ─────────────────────────────────────────────────────────────────

class Model:
    def __init__(self, alias: str) -> None:
        if alias not in MODELS:
            raise SystemExit(f"modelo desconhecido {alias!r}: use {', '.join(MODELS)}")
        self.alias = alias
        self.provider, self.id, self.region = MODELS[alias]
        self.token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        if self.provider == "bedrock" and not self.token:
            raise SystemExit("defina AWS_BEARER_TOKEN_BEDROCK no ambiente (nunca num arquivo do repositório)")

    async def chat(self, client: httpx.AsyncClient, messages: list[dict[str, str]]) -> tuple[str, int, int]:
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{quote(self.id, safe='')}/converse"
        body = {
            "system": [{"text": SYSTEM}],
            "messages": [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages],
            "inferenceConfig": {"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0.2},
        }
        for wait in (5, 15, 45, None):
            reply = await client.post(url, json=body, headers={"Authorization": f"Bearer {self.token}"}, timeout=600)
            if reply.status_code in (429, 500, 502, 503, 504) and wait is not None:
                await asyncio.sleep(wait)
                continue
            if reply.status_code != 200:
                raise RuntimeError(f"Bedrock respondeu {reply.status_code}: {reply.text[:300]}")
            data = reply.json()
            text = "".join(part.get("text", "") for part in data["output"]["message"]["content"])
            usage = data.get("usage", {})
            return text, usage.get("inputTokens", 0), usage.get("outputTokens", 0)
        raise RuntimeError("Bedrock sem resposta depois de 4 tentativas")


# ── Workspace ────────────────────────────────────────────────────────────────

def prepare(task: Task, base: Path) -> Path:
    """Cópia do repositório com o spec da tarefa e o esqueleto do service.sh (spec-first: o spec é preservado)."""
    ws = Path(tempfile.mkdtemp(prefix=f"{task.id}-", dir=base))
    listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True)
    for rel in listed.stdout.splitlines():
        if rel.startswith(("frontend/node_modules/", "bench/")) or not (ROOT / rel).is_file():
            continue
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    (ws / "frontend" / "node_modules").symlink_to(ROOT / "frontend" / "node_modules")
    (ws / ".venv").symlink_to(ROOT / ".venv")
    (ws / "specs" / f"{task.service}.md").write_text(task.spec, encoding="utf-8")
    run = subprocess.run(["./service.sh", task.service], cwd=ws, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"service.sh falhou: {run.stderr}")
    return ws


def service_files(task: Task, ws: Path) -> dict[str, str]:
    files = {}
    for path in sorted(ws.rglob("*")):
        rel = path.relative_to(ws).as_posix()
        if path.is_file() and not rel.startswith(("frontend/node_modules", ".venv")) and task.allowed(rel):
            files[rel] = path.read_text(encoding="utf-8")
    return files


def apply(task: Task, ws: Path, reply: str) -> tuple[list[str], list[str]]:
    written, rejected = [], []
    for path, content in FILE_BLOCK.findall(reply):
        path = path.strip().strip("`").removeprefix("./")
        if fenced := FENCE.match(content):
            content = fenced.group(1)
        if not task.allowed(path):
            rejected.append(path)
            continue
        target = ws / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        written.append(path)
    return written, rejected


# ── Trilhos ──────────────────────────────────────────────────────────────────

def checks(task: Task, ws: Path) -> tuple[dict[str, bool], str]:
    """Contrato, testes do serviço, prova de aceitação e frontend; devolve o que passou e os erros para o modelo."""
    env = {**os.environ, "PYTHONPATH": f"services/svc-{task.service}", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("AWS_BEARER_TOKEN_BEDROCK", None)  # o código gerado roda sem a chave
    (ws / "tests" / "aceite_bench.py").write_text(task.acceptance, encoding="utf-8")
    pytest = ["uv", "run", "--offline", "python", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "--no-header"]
    steps = [
        ("contrato", ["uv", "run", "--offline", "python", "gateway/contracts.py"], ws, 120),
        ("testes", [*pytest, f"tests/{task.service}.py"], ws, 180),
        ("aceite", [*pytest, "tests/aceite_bench.py"], ws, 180),
        ("frontend", ["npm", "run", "check"], ws / "frontend", 300),
    ]
    results, failures = {}, []
    for name, command, cwd, timeout in steps:
        try:
            done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
            ok, output = done.returncode == 0, done.stdout + done.stderr
        except subprocess.TimeoutExpired:
            ok, output = False, f"tempo esgotado ({timeout} s)"
        results[name] = ok
        if not ok:
            failures.append(f"## {name} falhou\n{_tail(output)}")
            if name == "contrato":  # sem contrato não há frontend nem rotas confiáveis
                results.update({"testes": False, "aceite": False, "frontend": False})
                break
    return results, "\n\n".join(failures)


def _tail(output: str) -> str:
    """O que o modelo precisa ver de uma falha: primeiro as linhas que dizem o erro (asserção, exceção, TypeScript,
    trilhos), sem os logs de rotina; depois o fim da saída, até FEEDBACK_CHARS."""
    lines = [
        line for line in output.splitlines()
        if line.strip() and "node_modules" not in line and not re.search(r"\b(INFO|WARNING|DEBUG)\b", line)
    ]
    key = [
        line for line in lines
        if line.startswith(("E ", "FAILED", "ERROR")) or re.search(r"Error\b|error TS|Trilhos|viola o trilho|modules/", line)
    ]
    focused = list(dict.fromkeys(key))
    text = "\n".join(focused)
    rest = "\n".join(line for line in lines[-60:] if line not in focused)
    combined = f"{text}\n…\n{rest}" if text else rest
    return combined if len(combined) <= FEEDBACK_CHARS else combined[:FEEDBACK_CHARS] + "\n…"


# ── Pacote de contexto ───────────────────────────────────────────────────────

def guide() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    parts = []
    for heading in README_SECTIONS:
        start = readme.find("\n" + heading)
        if start < 0:
            continue
        level = heading.split(" ")[0]
        rest = readme[start + 1:]
        stops = [m.start() for m in re.finditer(r"^#{1,%d} " % len(level), rest, re.MULTILINE) if m.start() > 0]
        parts.append(rest[: stops[0] if stops else len(rest)].strip())
    docs = []
    for name in CORE_DOCS:
        source = (ROOT / "core" / f"{name}.py").read_text(encoding="utf-8")
        docs.append(f"### core/{name}.py\n{ast.get_docstring(ast.parse(source)) or ''}")
    catalog = (ROOT / "frontend" / "src" / "components" / "CATALOG.md").read_text(encoding="utf-8")
    index = catalog[catalog.find("## Índice"): catalog.find("\n## ", catalog.find("## Índice") + 3)]
    return "\n\n".join([
        "# Guia do framework (trechos do README)", *parts,
        "# API do core (docstrings)", *docs,
        "# Catálogo de componentes do frontend (índice; página só compõe estes)", index.strip(),
    ])


def example(task: Task, tasks: list[Task]) -> str:
    """O módulo de exemplo para esta tarefa: o primeiro de EXAMPLES que não é ela mesma."""
    chosen = next((t for t in tasks if t.id in EXAMPLES and t.id != task.id and t.reference), None)
    if chosen is None:
        return ""
    files = "\n\n".join(f"<<<FILE {path}\n{content.rstrip()}\nFILE>>>" for path, content in chosen.reference.items())
    return (
        f"# Exemplo resolvido (outro módulo, para ver o formato certo; não copie os nomes dele)\n"
        f"## Spec do exemplo\n{chosen.spec}\n## Arquivos que a solução mudou\n{files}"
    )


def prompt(task: Task, files: dict[str, str], guide_text: str, example_text: str = "") -> str:
    allowed = [
        f"services/svc-{task.service}/{{schemas,service,workflows,main}}.py", f"gateway/endpoints/{task.service}.yaml",
        f"tests/{task.service}.py", f"frontend/src/modules/{task.service}/page.tsx (e subpastas <parte>/page.tsx ou [param]/page.tsx)",
    ]
    current = "\n\n".join(f"<<<FILE {path}\n{content.rstrip()}\nFILE>>>" for path, content in files.items())
    return (
        f"# Tarefa\nImplemente specs/{task.service}.md no serviço svc-{task.service}, que o service.sh acabou de gerar "
        "(arquivos atuais abaixo), seguindo o guia. Atualize também tests/" f"{task.service}.py para o que mudou.\n"
        f"Arquivos que você pode mudar: {'; '.join(allowed)}.\n\n"
        f"# Spec (specs/{task.service}.md)\n{task.spec}\n\n# Arquivos atuais do serviço\n{current}\n\n{guide_text}"
        + (f"\n\n{example_text}" if example_text else "")
    )


# ── Execução ─────────────────────────────────────────────────────────────────

def lines_written(before: dict[str, str], after: dict[str, str]) -> int:
    total = 0
    for path, content in after.items():
        old = before.get(path, "").splitlines()
        total += sum(1 for line in difflib.ndiff(old, content.splitlines()) if line.startswith("+ "))
    return total


async def run_task(
    task: Task, model: Model | None, attempts: int, base: Path, client: httpx.AsyncClient, guide_text: str, example_text: str
) -> Outcome:
    outcome = Outcome(task=task.id, level=task.level, passed_at=None, attempts=[])
    try:
        ws = await asyncio.to_thread(prepare, task, base)
        before = service_files(task, ws)
        messages = [{"role": "user", "content": prompt(task, before, guide_text, example_text)}]
        for number in range(1, attempts + 1):
            started = time.monotonic()
            if model is None:
                reply = "\n".join(f"<<<FILE {p}\n{c}\nFILE>>>" for p, c in task.reference.items())
                tokens_in = tokens_out = 0
            else:
                reply, tokens_in, tokens_out = await model.chat(client, messages)
            written, rejected = apply(task, ws, reply)
            results, failures = await asyncio.to_thread(checks, task, ws)
            if rejected:
                failures = f"## arquivos recusados (fora do serviço): {', '.join(rejected)}\n\n{failures}"
            attempt = Attempt(number, results, round(time.monotonic() - started, 1), tokens_in, tokens_out, written, rejected, failures)
            outcome.attempts.append(attempt)
            print(f"  {task.id} tentativa {number}: {' '.join(f'{k}={'ok' if v else 'X'}' for k, v in results.items())}", flush=True)
            if all(results.values()) and not rejected:
                outcome.passed_at = number
                break
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"Os trilhos recusaram:\n\n{failures}\n\nCorrija e devolva só os arquivos que mudam, inteiros, no mesmo formato."},
            ]
        outcome.lines_written = lines_written(before, service_files(task, ws))
        (base / f"{task.id}.ultima-resposta.txt").write_text(reply, encoding="utf-8")
    except Exception as exc:  # a tarefa falha sozinha; o banco segue
        outcome.error = f"{type(exc).__name__}: {exc}"[:500]
        print(f"  {task.id}: erro {outcome.error}", flush=True)
    return outcome


def report(label: str, outcomes: list[Outcome], started: datetime, seconds: float, context: str = "") -> str:
    passed1 = sum(1 for o in outcomes if o.passed_at == 1)
    passed = sum(1 for o in outcomes if o.passed_at)
    tokens_in = sum(a.tokens_in for o in outcomes for a in o.attempts)
    tokens_out = sum(a.tokens_out for o in outcomes for a in o.attempts)
    rows = [
        f"| {o.task} | {o.level} | {'sim' if o.passed_at == 1 else 'não'} | {o.passed_at or '—'} | "
        f"{' '.join(k for k, v in (o.attempts[0].checks.items() if o.attempts else []) if not v) or ('erro' if o.error else '—')} | "
        f"{sum(a.tokens_in for a in o.attempts):,} / {sum(a.tokens_out for a in o.attempts):,} | "
        f"{sum(a.seconds for a in o.attempts):.0f} s | {o.lines_written} |"
        for o in outcomes
    ]
    return "\n".join([
        f"# Banco de provas · {label} · {started:%Y-%m-%d %H:%M} UTC",
        "",
        f"- Passaram de primeira: **{passed1} de {len(outcomes)}**; com as novas tentativas: **{passed} de {len(outcomes)}**.",
        f"- Tokens: {tokens_in:,} de entrada e {tokens_out:,} de saída; tempo total {seconds / 60:.1f} min.",
        *([f"- Pacote de contexto: {context}."] if context else []),
        "- Linhas escritas: linhas novas ou mudadas pelo modelo nos arquivos do serviço, além do esqueleto.",
        "",
        "| Tarefa | Nível | De primeira | Passou na | Falhou na 1ª em | Tokens (entrada / saída) | Tempo | Linhas escritas |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ])


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=sorted(MODELS), help="modelo do Bedrock (apelido)")
    parser.add_argument("--reference", action="store_true", help="usa as soluções de referência no lugar do modelo")
    parser.add_argument("--tasks", help="ids separados por vírgula (padrão: todas)")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--keep", action="store_true", help="mantém as cópias do repositório para inspeção")
    parser.add_argument("--no-example", action="store_true", help="sem o módulo resolvido no pacote de contexto")
    args = parser.parse_args()
    if bool(args.model) == args.reference:
        raise SystemExit("escolha --model <apelido> ou --reference")
    tasks = all_tasks = [Task.load(p) for p in sorted(TASKS.glob("*.yaml"))]
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.id in wanted]
    if args.reference and (missing := [t.id for t in tasks if not t.reference]):
        raise SystemExit(f"tarefas sem referência: {', '.join(missing)}")
    model = Model(args.model) if args.model else None
    label = args.model or "referência"
    base = Path(tempfile.mkdtemp(prefix=f"bench-{label}-"))
    guide_text = guide()
    started, clock = datetime.now(UTC), time.monotonic()
    print(f"banco de provas: {len(tasks)} tarefas com {label}; cópias em {base}", flush=True)
    gate = asyncio.Semaphore(args.parallel)
    async with httpx.AsyncClient() as client:
        async def one(task: Task) -> Outcome:
            async with gate:
                example_text = "" if args.no_example else example(task, all_tasks)
                return await run_task(task, model, 1 if model is None else args.attempts, base, client, guide_text, example_text)

        outcomes = await asyncio.gather(*(one(t) for t in tasks))
    seconds = time.monotonic() - clock
    context = "README, docstrings do core, índice do catálogo e arquivos do serviço" + ("" if args.no_example else ", mais um módulo resolvido de exemplo")
    text = report(label, outcomes, started, seconds, context)
    print("\n" + text)
    if model is not None:
        RESULTS.mkdir(exist_ok=True)
        stem = RESULTS / f"{started:%Y-%m-%d-%H%M}-{label}"
        stem.with_suffix(".md").write_text(text, encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps({"model": model.id, "started": started.isoformat(), "outcomes": [asdict(o) for o in outcomes]}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"relatório: {stem.with_suffix('.md').relative_to(ROOT)}")
    if not args.keep:
        shutil.rmtree(base, ignore_errors=True)
    if args.reference and not all(o.passed_at for o in outcomes):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
