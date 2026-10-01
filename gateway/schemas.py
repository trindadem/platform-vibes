"""Gateway · contrato dos manifestos gateway/endpoints/<service_name>.yaml. Fonte da verdade: README §5.8

Trilhos (manifesto fora deles impede o boot do gateway):
- Cada manifesto só aponta para o próprio serviço: target_url = http://svc-<service>:8000/...,
  nats_subject = events.<service>.trigger (o gatilho assíncrono). Nunca para outro serviço nem para fora.
- NATS só aceita POST. Rota pública não tem papéis nem parâmetros no caminho.
- cookies: true (só HTTP e POST) é a única forma de um cookie passar pelo gateway: a rota recebe o Cookie do
  navegador e devolve o Set-Cookie do serviço. As demais nunca veem cookie (sessão de login, README §5.8).
- stream: true (só HTTP) repassa a resposta em pedaços (SSE); exige delta: <Modelo> de cada pedaço (README §5.10).
- live: [{ topic, model }] declara os eventos ao vivo que o serviço emite (<service>.<topic>); viram tipos no
  frontend. O nome de serviço "live" é reservado: /api/v1/live é a conexão ao vivo do próprio gateway.
- Campo desconhecido é erro (um typo não vira configuração silenciosa).
- request/response nomeiam modelos do schemas.py do serviço; gateway/contracts.py confere que existem e gera
  o cliente tipado do frontend. name é o nome da função gerada (padrão: último trecho fixo do path).
- query (só em GET) nomeia o modelo dos parâmetros da URL, em geral um ListQuery (lista paginada, README §5.12):
  vira o argumento tipado query? da função gerada. O gateway repassa a query string como veio; o serviço valida.
- resources: [nome] publica as 5 rotas de cada cadastro declarado no schemas.py (core/resources.py, README §5.19):
  GET /<nome>, GET /<nome>/item, POST /<nome>, POST /<nome>/update e POST /<nome>/remove, todas com token. O aviso
  ao vivo <service>.<nome> vem junto (não declare em live:).
"""
import re
import string
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SERVICE_PORT = 8000
_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_PATH = re.compile(r"^(/([a-z0-9_-]+|\{[a-z_][a-z0-9_]*\}))+$")
_MODEL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_OPERATION = re.compile(r"^[a-z][A-Za-z0-9]*$")
_EVENT = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_HEADER = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = {"live"}
# Cabeçalhos que nenhuma rota repassa a mais: sessão, roteamento e os que o gateway já trata (interpreter.py).
BLOCKED_HEADERS = {
    "authorization", "content-type", "accept", "x-request-id", "cookie", "host", "content-length",
    "transfer-encoding", "connection", "upgrade", "forwarded", "x-forwarded-for", "x-forwarded-host",
    "x-forwarded-proto", "x-real-ip",
}


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    name: str | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    auth: Literal["client_jwt", "public"]
    roles: tuple[str, ...] = ()
    target_type: Literal["http", "nats"]
    target_url: str | None = None
    nats_subject: str | None = None
    timeout: float = Field(30, gt=0, le=120)
    request: str | None = None
    query: str | None = None
    response: str | None = None
    cookies: bool = False
    headers: tuple[str, ...] = Field((), max_length=8, description="Cabeçalhos extras repassados (webhook que chega)")
    stream: bool = False
    delta: str | None = None

    def params(self) -> list[str]:
        """Parâmetros do caminho, na ordem em que aparecem."""
        return re.findall(r"\{([a-z_][a-z0-9_]*)\}", self.path)

    def operation(self) -> str:
        """Nome da função no cliente gerado: name, ou o último trecho fixo do path em camelCase."""
        if self.name:
            return self.name
        fixed = [part for part in self.path.split("/") if part and not part.startswith("{")]
        words = re.split(r"[-_]", fixed[-1] if fixed else "root")
        return words[0] + "".join(word.capitalize() for word in words[1:])


class LiveTopic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: str = Field(..., description="Evento; o tópico completo é <service>.<topic>")
    model: str = Field(..., description="Modelo do schemas.py que o evento carrega")


RESOURCE_ROUTES = (  # (método, sufixo do caminho, nome da operação): as rotas de core/resources.py
    ("GET", "", "list"),
    ("GET", "/item", "get"),
    ("POST", "", "create"),
    ("POST", "/update", "update"),
    ("POST", "/remove", "remove"),
)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    base_path: str
    endpoints: tuple[Endpoint, ...] = ()
    resources: tuple[str, ...] = Field((), description="Cadastros do schemas.py (core/resources.py) publicados")
    live: tuple[LiveTopic, ...] = ()

    def resource_endpoints(self, name: str) -> list[Endpoint]:
        """As 5 rotas de um cadastro, como endpoints HTTP do próprio serviço."""
        return [
            Endpoint(
                path=f"/{name}{suffix}", name=f"{name}-{operation}", method=method, auth="client_jwt", target_type="http",
                target_url=f"http://svc-{self.service}:{SERVICE_PORT}/{name}{suffix}",
            )
            for method, suffix, operation in RESOURCE_ROUTES
        ]

    def all_endpoints(self) -> list[Endpoint]:
        """As rotas declaradas e as dos cadastros: o que o gateway monta."""
        return [*self.endpoints, *(ep for name in self.resources for ep in self.resource_endpoints(name))]

    @model_validator(mode="after")
    def _rails(self) -> "Manifest":
        if not _NAME.match(self.service):
            raise ValueError(f"service inválido: {self.service!r} (kebab-case, README §2)")
        if self.service in RESERVED:
            raise ValueError(f"service {self.service!r} é reservado (/api/v1/{self.service} é do gateway)")
        events = [t.topic for t in self.live]
        for t in self.live:
            if not _EVENT.match(t.topic):
                raise ValueError(f"live: topic {t.topic!r} inválido (kebab-case, ex.: criado, pagamento-aprovado)")
            if not _MODEL.match(t.model):
                raise ValueError(f"live: model {t.model!r} deve ser o nome de um modelo do schemas.py (PascalCase)")
        if len(events) != len(set(events)):
            raise ValueError("live: topic repetido")
        if self.base_path != f"/api/v1/{self.service}":
            raise ValueError(f"base_path deve ser /api/v1/{self.service}")
        if not self.endpoints and not self.resources:
            raise ValueError("declare endpoints ou resources (o manifesto publica ao menos uma rota)")
        for name in self.resources:
            if not _NAME.match(name):
                raise ValueError(f"resources: {name!r} inválido (kebab-case, o nome do Resource no schemas.py)")
        if len(self.resources) != len(set(self.resources)):
            raise ValueError("resources: cadastro repetido")
        if clash := sorted(set(self.resources) & set(events)):
            raise ValueError(f"live: {', '.join(clash)} é o aviso de um cadastro (resources) e já vem junto")
        seen, operations = set(), set()
        for name in self.resources:
            for ep in self.resource_endpoints(name):
                seen.add((ep.method, ep.path))
        for ep in self.endpoints:
            where = f"{ep.method} {ep.path}"
            if (ep.method, ep.path) in seen:
                raise ValueError(f"{where}: rota duplicada")
            seen.add((ep.method, ep.path))
            if not _PATH.match(ep.path):
                raise ValueError(f"{where}: path inválido (ex.: /execute, /itens/{{item_id}})")
            if ep.name is not None and not _OPERATION.match(ep.name):
                raise ValueError(f"{where}: name deve ser camelCase (ex.: listarFaturas)")
            if ep.operation() in operations:
                raise ValueError(f"{where}: outra rota já gera a função {ep.operation()!r}; defina name: diferente")
            operations.add(ep.operation())
            for field, model in (("request", ep.request), ("query", ep.query), ("response", ep.response), ("delta", ep.delta)):
                if model is not None and not _MODEL.match(model):
                    raise ValueError(f"{where}: {field} deve ser o nome de um modelo do schemas.py (PascalCase)")
            if ep.request is not None and ep.method in ("GET", "DELETE"):
                raise ValueError(f"{where}: {ep.method} não tem corpo; remova request")
            if ep.query is not None and (ep.method != "GET" or ep.target_type != "http"):
                raise ValueError(f"{where}: query (parâmetros da URL) só em rota HTTP GET")
            if ep.cookies and (ep.target_type != "http" or ep.method != "POST"):
                raise ValueError(f"{where}: cookies: true só em rota HTTP POST")
            if ep.headers and (ep.target_type != "http" or ep.method != "POST"):
                raise ValueError(f"{where}: headers só em rota HTTP POST (ex.: a assinatura de um webhook que chega)")
            for header in ep.headers:
                if not _HEADER.match(header) or header in BLOCKED_HEADERS:
                    raise ValueError(f"{where}: headers: {header!r} não pode ser repassado (minúsculas; nem sessão nem roteamento)")
            if ep.stream and (ep.target_type != "http" or ep.delta is None):
                raise ValueError(f"{where}: stream: true só em rota HTTP e exige delta: <Modelo> de cada pedaço")
            if ep.delta is not None and not ep.stream:
                raise ValueError(f"{where}: delta só existe com stream: true")
            if ep.auth == "public" and (ep.roles or ep.params()):
                raise ValueError(f"{where}: rota pública não tem roles nem parâmetros no caminho")
            if ep.target_type == "http":
                self._check_http(ep, where)
            else:
                self._check_nats(ep, where)
        return self

    def _check_http(self, ep: Endpoint, where: str) -> None:
        if ep.target_url is None or ep.nats_subject is not None:
            raise ValueError(f"{where}: target_type http exige target_url (e não aceita nats_subject)")
        url = urlsplit(ep.target_url)
        if (url.scheme, url.hostname, url.port) != ("http", f"svc-{self.service}", SERVICE_PORT):
            raise ValueError(f"{where}: target_url deve começar com http://svc-{self.service}:{SERVICE_PORT}/")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError(f"{where}: target_url não aceita credenciais, query ou fragmento")
        placeholders = {name for _, name, _, _ in string.Formatter().parse(url.path) if name}
        if not placeholders <= set(ep.params()):
            raise ValueError(f"{where}: target_url usa parâmetros que o path não declara: {placeholders - set(ep.params())}")

    def _check_nats(self, ep: Endpoint, where: str) -> None:
        if ep.nats_subject is None or ep.target_url is not None:
            raise ValueError(f"{where}: target_type nats exige nats_subject (e não aceita target_url)")
        if ep.method != "POST":
            raise ValueError(f"{where}: rota NATS só aceita POST")
        if ep.response is not None:
            raise ValueError(f"{where}: rota NATS sempre responde {{ message_id }}; remova response")
        if ep.nats_subject != f"events.{self.service}.trigger":
            # O gatilho do serviço. Em produção, é o único subject em que o gateway pode publicar (compose.prod.yaml).
            raise ValueError(f"{where}: nats_subject deve ser events.{self.service}.trigger (mais de uma ação: um campo no payload)")
