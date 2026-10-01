"""Gateway · contrato dos manifestos gateway/endpoints/<service_name>.yaml. Fonte da verdade: README §5.8

Trilhos (manifesto fora deles impede o boot do gateway):
- Cada manifesto só aponta para o próprio serviço: target_url = http://svc-<service>:8000/...,
  nats_subject = events.<service>.<ação>. Nunca para outro serviço nem para fora.
- NATS só aceita POST. Rota pública não tem papéis nem parâmetros no caminho.
- cookies: true (só HTTP e POST) é a única forma de um cookie passar pelo gateway: a rota recebe o Cookie do
  navegador e devolve o Set-Cookie do serviço. As demais nunca veem cookie (sessão de login, README §5.8).
- Campo desconhecido é erro (um typo não vira configuração silenciosa).
- request/response nomeiam modelos do schemas.py do serviço; gateway/contracts.py confere que existem e gera
  o cliente tipado do frontend. name é o nome da função gerada (padrão: último trecho fixo do path).
"""
import re
import string
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SERVICE_PORT = 8000
_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_PATH = re.compile(r"^(/([a-z0-9_-]+|\{[a-z_][a-z0-9_]*\}))+$")
_SUBJECT = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+){2,}$")
_MODEL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_OPERATION = re.compile(r"^[a-z][A-Za-z0-9]*$")


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
    response: str | None = None
    cookies: bool = False

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


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    base_path: str
    endpoints: tuple[Endpoint, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _rails(self) -> "Manifest":
        if not _NAME.match(self.service):
            raise ValueError(f"service inválido: {self.service!r} (kebab-case, README §2)")
        if self.base_path != f"/api/v1/{self.service}":
            raise ValueError(f"base_path deve ser /api/v1/{self.service}")
        seen, operations = set(), set()
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
            for field, model in (("request", ep.request), ("response", ep.response)):
                if model is not None and not _MODEL.match(model):
                    raise ValueError(f"{where}: {field} deve ser o nome de um modelo do schemas.py (PascalCase)")
            if ep.request is not None and ep.method in ("GET", "DELETE"):
                raise ValueError(f"{where}: {ep.method} não tem corpo; remova request")
            if ep.cookies and (ep.target_type != "http" or ep.method != "POST"):
                raise ValueError(f"{where}: cookies: true só em rota HTTP POST")
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
        if not ep.nats_subject.startswith(f"events.{self.service}.") or not _SUBJECT.match(ep.nats_subject):
            raise ValueError(f"{where}: nats_subject deve ser events.{self.service}.<ação>")
