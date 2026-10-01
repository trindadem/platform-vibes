"""Gateway · gera frontend/src/core/contracts.ts, o cliente tipado da API pública. Fonte da verdade: README §5.8

Junta os manifestos (gateway/endpoints/*.yaml: rota, método, request/response) com os modelos Pydantic de
services/svc-<nome>/schemas.py e escreve tipos TypeScript e uma função por rota. O frontend nunca adivinha
caminho nem campo: se errar, o TypeScript acusa. Modelo citado no manifesto e ausente no schemas.py é erro.
Rota com query: (GET de lista) recebe os parâmetros da URL tipados em query?, montados por withQuery (api.ts).
Rota stream: true vira função com options.onDelta (pedaços tipados) que resolve com o resultado final; os tópicos
live: viram a interface LiveTopics, que dá o tipo de cada evento em useLive/useLiveQuery (README §5.10).
O MODULE de cada schemas.py (core/plans.py) vira a constante appModules e o tipo ModuleName: o meta.module de uma tela
só aceita módulo que existe, e o menu agrupa pela categoria (README §5.17 e §6). Serviço com manifesto sem MODULE é erro.

Rodar (da raiz):  uv run python gateway/contracts.py           gera o arquivo
                  uv run python gateway/contracts.py --check   falha se o arquivo estiver desatualizado
"""
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(1, str(ROOT))  # o interpreter importa core/; rodando da raiz, a raiz precisa estar no path

from pydantic import BaseModel  # noqa: E402

from core.plans import Module  # noqa: E402

from interpreter import ENDPOINTS_DIR, load_manifests  # noqa: E402
from schemas import Endpoint, Manifest  # noqa: E402

OUTPUT = ROOT / "frontend" / "src" / "core" / "contracts.ts"
SERVICES_DIR = ROOT / "services"
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

HEADER = """\
// Gerado por gateway/contracts.py a partir de gateway/endpoints/*.yaml e services/*/schemas.py. Não edite:
// depois de mudar um manifesto ou um schemas.py, rode (da raiz) `uv run python gateway/contracts.py`.
import { __IMPORTS__ } from "./api";

/** Resposta de toda rota NATS: o id da mensagem publicada (o mesmo para a mesma Idempotency-Key). */
export interface Dispatched {
  message_id: string;
}

/** GET /health do gateway (README §5.18). */
export interface GatewayHealth {
  /** "ok" quando tudo responde (senão, a resposta é um erro 503). */
  status: string;
  /** Cada dependência do gateway e se respondeu ("ok"). */
  checks: Record<string, string>;
  /** Quantas rotas os manifestos publicam. */
  routes: number;
}

/** Rotas do próprio gateway. */
export const gateway = {
  /** GET /health · pública */
  health: (options?: RequestOptions) => request<GatewayHealth>("GET", "/health", undefined, options),
};
"""


def generate(endpoints_dir: Path = ENDPOINTS_DIR, services_dir: Path = SERVICES_DIR) -> str:
    sections, topics, modules = [HEADER], [], []
    for manifest in load_manifests(endpoints_dir):
        section, service_topics, module = _service_section(manifest, services_dir)
        sections.append(section)
        topics += service_topics
        modules.append((manifest.service, module))
    endpoints = [ep for manifest in load_manifests(endpoints_dir) for ep in manifest.endpoints]
    imports = ["request"]
    if any(ep.stream for ep in endpoints):
        imports.append("stream")
    if any(ep.query for ep in endpoints):
        imports.append("withQuery")
    imports.append("type RequestOptions")
    if any(ep.stream for ep in endpoints):
        imports.append("type StreamOptions")
    sections[0] = HEADER.replace("__IMPORTS__", ", ".join(imports))
    lines = "".join(f"  /** {doc} */\n  {json.dumps(name)}: {ts};\n" for name, ts, doc in topics)
    sections.append(
        "/** Eventos ao vivo (live: dos manifestos): tópico → o que o evento carrega. Use com useLive/useLiveQuery. */\n"
        f"export interface LiveTopics {{\n{lines}}}\n"
    )
    sections.append(_modules_section(modules))
    return "\n".join(sections)


def _modules_section(modules: list[tuple[str, Module]]) -> str:
    """appModules: o MODULE de cada serviço (título, categoria do menu, se é da plataforma) e o tipo ModuleName."""
    entries = "".join(
        f"  {_key(name)}: {{ title: {json.dumps(m.title, ensure_ascii=False)}, description: {json.dumps(m.description, ensure_ascii=False)}, "
        f"category: {json.dumps(m.category, ensure_ascii=False)}, core: {json.dumps(m.core)} }},\n"
        for name, m in modules
    )
    return (
        "/** Módulos (o MODULE de cada services/svc-<nome>/schemas.py): o meta.module das telas e os grupos do menu. */\n"
        f"export const appModules = {{\n{entries}}} as const;\n\n"
        "/** Nome de um módulo: o do serviço, sem svc-. */\n"
        "export type ModuleName = keyof typeof appModules;\n"
    )


def _service_section(manifest: Manifest, services_dir: Path) -> tuple[str, list[tuple[str, str, str]], Module]:
    prefix = _pascal(manifest.service)
    module = _load_schemas(services_dir / f"svc-{manifest.service}" / "schemas.py", manifest.service)
    declared = getattr(module, "MODULE", None)
    if not isinstance(declared, Module):
        raise RuntimeError(
            f"contracts: services/svc-{manifest.service}/schemas.py não declara MODULE = Module(...) (README §5.17)"
        )
    types: dict[str, str] = {}
    functions = []
    for ep in manifest.endpoints:
        where = f"{manifest.service}: {ep.method} {ep.path}"
        body = _declare(module, ep.request, prefix, types, where, response=False) if ep.request else "unknown"
        result = "Dispatched" if ep.target_type == "nats" else (
            _declare(module, ep.response, prefix, types, where, response=True) if ep.response else "unknown"
        )
        delta = _declare(module, ep.delta, prefix, types, where, response=True) if ep.delta else None
        query = _declare(module, ep.query, prefix, types, where, response=False) if ep.query else None
        functions.append(_function(manifest, ep, body, result, delta, query))
    topics = [
        (f"{manifest.service}.{t.topic}", _declare(module, t.model, prefix, types, f"{manifest.service}: live {t.topic}", response=True),
         f"svc-{manifest.service} · bus.live(\"{manifest.service}.{t.topic}\", ...)")
        for t in manifest.live
    ]
    client = f"/** svc-{manifest.service} · {manifest.base_path} */\nexport const {_camel(manifest.service)} = {{\n" + "\n".join(functions) + "\n};\n"
    return "\n".join([*types.values(), client]), topics, declared


def _function(manifest: Manifest, ep: Endpoint, body: str, result: str, delta: str | None = None, query: str | None = None) -> str:
    url = manifest.base_path + ep.path
    params = ep.params()
    path = f'"{url}"'
    if params:
        path = "`" + re.sub(r"\{([a-z_][a-z0-9_]*)\}", r"${encodeURIComponent(params.\1)}", url) + "`"
    args = []
    if params:
        args.append("params: { " + "; ".join(f"{p}: string" for p in params) + " }")
    if query:
        args.append(f"query?: {query}")
        path = f"withQuery({path}, query)"
    has_body = ep.method in ("POST", "PUT", "PATCH")
    if has_body:
        args.append(f"body: {body}")
    args.append(f"options?: StreamOptions<{delta}>" if delta else "options?: RequestOptions")
    target = (
        f"NATS {ep.nats_subject}: durável; passe options.idempotencyKey para repetir com segurança"
        if ep.target_type == "nats"
        else "http · em pedaços (options.onDelta)" if delta else "http"
    )
    access = "pública" if ep.auth == "public" else "exige token" + (f" com papéis {', '.join(ep.roles)}" if ep.roles else "")
    if ep.cookies:
        access += " · sessão em cookie"
    return (
        f"  /** {ep.method} {url} · {target} · {access} */\n"
        f"  {_key(ep.operation())}: ({', '.join(args)}) =>\n"
        f'    {f"stream<{delta}, {result}>" if delta else f"request<{result}>"}("{ep.method}", {path}, {"body" if has_body else "undefined"}, options),'
    )


def _load_schemas(path: Path, service: str) -> ModuleType:
    if not path.exists():
        raise RuntimeError(f"contracts: o manifesto {service} não tem services/svc-{service}/schemas.py")
    spec = importlib.util.spec_from_file_location(f"cv_contracts_{service.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declare(module: ModuleType, model_name: str, prefix: str, types: dict[str, str], where: str, response: bool) -> str:
    model = getattr(module, model_name, None)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise RuntimeError(f"contracts: {where} cita {model_name}, que não é um modelo Pydantic do schemas.py")
    schema = model.model_json_schema(mode="serialization" if response else "validation", ref_template="#/$defs/{model}")
    for name, definition in schema.get("$defs", {}).items():
        types.setdefault(prefix + name, _declaration(prefix + name, definition, prefix, response))
    types.setdefault(prefix + model_name, _declaration(prefix + model_name, schema, prefix, response))
    return prefix + model_name


def _declaration(name: str, schema: dict[str, Any], prefix: str, response: bool) -> str:
    doc = _doc(schema.get("description"), "")
    properties = schema.get("properties")
    if schema.get("type") != "object" or properties is None:
        return f"{doc}export type {name} = {_ts(schema, prefix)};\n"
    # Resposta sempre traz todos os campos; na entrada, campo com padrão é opcional.
    required = set(properties) if response else set(schema.get("required", []))
    lines = [f"{doc}export interface {name} {{"]
    for prop, sub in properties.items():
        lines.append(f"{_doc(sub.get('description'), '  ')}  {_key(prop)}{'' if prop in required else '?'}: {_ts(sub, prefix)};")
    return "\n".join(lines) + "\n}\n"


def _ts(schema: dict[str, Any], prefix: str) -> str:
    if "$ref" in schema:
        return prefix + schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    for combinator, glue in (("anyOf", " | "), ("oneOf", " | "), ("allOf", " & ")):
        if combinator in schema:
            return glue.join(dict.fromkeys(_ts(part, prefix) for part in schema[combinator]))
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(_ts({**schema, "type": k}, prefix) for k in kind)
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        item = _ts(schema.get("items", {}), prefix)
        return f"({item})[]" if " " in item else f"{item}[]"
    if kind == "object":
        if schema.get("properties"):
            fields = "; ".join(f"{_key(k)}{'' if k in schema.get('required', []) else '?'}: {_ts(v, prefix)}" for k, v in schema["properties"].items())
            return "{ " + fields + " }"
        extra = schema.get("additionalProperties")
        if not (isinstance(extra, dict) and extra) and schema.get("patternProperties"):  # dict com chave restrita
            values = list(schema["patternProperties"].values())
            extra = values[0] if len(values) == 1 else {"anyOf": values}
        return f"Record<string, {_ts(extra, prefix)}>" if isinstance(extra, dict) and extra else "Record<string, unknown>"
    return "unknown"


def _doc(text: str | None, indent: str) -> str:
    return f"{indent}/** {' '.join(text.split())} */\n" if text else ""


def _key(name: str) -> str:
    return name if _IDENTIFIER.match(name) else json.dumps(name)


def _pascal(kebab: str) -> str:
    return "".join(part.capitalize() for part in kebab.split("-"))


def _camel(kebab: str) -> str:
    pascal = _pascal(kebab)
    return pascal[:1].lower() + pascal[1:]


if __name__ == "__main__":
    content = generate()
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    if "--check" in sys.argv[1:]:
        if content != current:
            sys.exit(f"{OUTPUT.relative_to(ROOT)} está desatualizado: rode uv run python gateway/contracts.py")
        print(f"{OUTPUT.relative_to(ROOT)} em dia.")
    elif content != current:
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"{OUTPUT.relative_to(ROOT)} gerado.")
    else:
        print(f"{OUTPUT.relative_to(ROOT)} já estava em dia.")
