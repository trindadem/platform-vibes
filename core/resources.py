"""Recursos (README §5.19): o cadastro de um módulo declarado no schemas.py. Lista, leitura, criação, edição e remoção,
as rotas, o contrato do frontend e a tela saem da declaração; o serviço só escreve o que é regra de negócio.

    class Cliente(Fields):                                        # schemas.py: os campos de quem preenche
        nome: str = Field(..., min_length=2, max_length=120, title="Nome ou razão social")
        email: Email | None = None
        status: Literal["ativo", "inativo"] = "ativo"
        limite: Money = 0

    CLIENTES = Resource(SERVICE, "clientes", Cliente, "Clientes", search=("nome", "email"), sort=("nome", "limite"),
                        filters=("status",), unique=("email",), limit="clientes")
    RESOURCES = [CLIENTES]

    db.connected(tables=..., resources=RESOURCES, ...)            # main.py: tabela, busca e índice do cadastro
    resources.mount(app, RESOURCES)                               # main.py: as 5 rotas
    resources: [clientes]                                         # gateway/endpoints/<serviço>.yaml

Rotas (todas exigem token e valem para a organização do token): GET /clientes (página, busca, filtros e ordem pela
URL), GET /clientes/item?id=, POST /clientes (cria), POST /clientes/update (muda só os campos que vieram) e POST
/clientes/remove. Do serviço, as mesmas operações: await resources.create(CLIENTES, Cliente(...)), list, get, update e
remove (ex.: um workflow que cria um cliente).

Trilhos:
- Tabela <serviço>_<recurso> (vendas_clientes), por organização, com os carimbos do banco; o id na API é a chave
  curta do registro. Campos com o nome id, tenant ou de carimbo são recusados.
- Os campos herdam de Fields (campo não declarado é recusado). Tipos com tela pronta: Money, Email, Phone, Text e
  os do Python (str, int, float, bool, date, datetime, Literal[...]). title= é o rótulo; description= é a ajuda.
- search: campos com busca por palavras; sort: campos que ordenam (created_at sempre); filters: campos Literal ou
  bool que filtram a lista; unique: campos obrigatórios que não se repetem na organização (409
  ERRO_RECORD_DUPLICATE); campo opcional não entra (o banco trata vazio como valor repetido).
- limit: nome de um Limit total do MODULE (README §5.17): conferido antes de criar e contado depois.
- write: papéis que criam, editam e removem (padrão: qualquer membro); ler é de todo membro da organização.
- Toda mudança avisa ao vivo <serviço>.<recurso> (ResourceChanged), e a lista aberta na tela se atualiza.
"""
import re
import types
from collections.abc import Sequence
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from fastapi import FastAPI, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model, field_validator
from pydantic.fields import FieldInfo

from core.envelope import ResponseEnvelope, ServiceError, error_code
from core.nats_bus import bus
from core.plans import plans
from core.security import current, current_tenant
from core.surreal import STAMPS, TENANT, ListQuery, Page, db

__all__ = [
    "Resource", "resources", "Resources", "Fields", "Money", "Email", "Phone", "Text", "Kind",
    "ResourceRef", "ResourceRemoved", "ResourceChanged",
]

_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_RESERVED = {"id", TENANT, *STAMPS}
_ID = r"^[A-Za-z0-9_-]{1,64}$"
_LONG_TEXT = 300  # str com max_length acima disso vira área de texto na tela
_MAX_COLUMNS = 5


class Kind:
    """Marca o tipo de tela de um campo (Annotated[..., Kind("money")]); os tipos abaixo já trazem a sua."""

    def __init__(self, value: str) -> None:
        self.value = value


Money = Annotated[float, Field(ge=0), Kind("money")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), Kind("email")]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, max_length=30, pattern=r"^\+?[0-9 ()-]{8,30}$"), Kind("phone")]
Text = Annotated[str, StringConstraints(max_length=5000), Kind("textarea")]


class Fields(BaseModel):
    """Base dos campos de um recurso: campo não declarado é recusado (mass assignment)."""

    model_config = ConfigDict(extra="forbid")


class ResourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, StringConstraints(pattern=_ID)] = Field(..., description="Id do registro")


class ResourceRemoved(BaseModel):
    id: str


class ResourceChanged(BaseModel):
    """Aviso ao vivo de um recurso (<serviço>.<recurso>): a lista aberta na tela busca de novo."""

    id: str
    action: Literal["created", "updated", "removed"]


class _Item(BaseModel):
    """Base do registro devolvido: id curto e carimbos; tenant e campos fora do modelo ficam de fora."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Id do registro")
    created_at: datetime | None = None
    created_by: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _short(cls, value: Any) -> Any:
        """"vendas_clientes:⟨abc⟩" → "abc": na API, o id é só a chave."""
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class Resource:
    """Um cadastro do módulo. Os modelos derivados (item, update, query, page) têm o nome do modelo de campos."""

    def __init__(
        self,
        service: str,
        name: str,
        model: type[Fields],
        title: str,
        *,
        search: Sequence[str] = (),
        sort: Sequence[str] = (),
        filters: Sequence[str] = (),
        unique: Sequence[str] = (),
        columns: Sequence[str] = (),
        limit: str | None = None,
        write: Sequence[str] = (),
    ) -> None:
        where = f"Resource({name!r})"
        if not service.startswith("svc-"):
            raise ValueError(f"{where}: o primeiro argumento é o SERVICE do schemas.py (svc-<nome>)")
        if not _NAME.match(name) or len(name) > 40:
            raise ValueError(f"{where}: nome em kebab-case, até 40 caracteres (ex.: clientes, ordens-de-servico)")
        if not (isinstance(model, type) and issubclass(model, Fields)):
            raise TypeError(f"{where}: os campos herdam de core.resources.Fields (class {name.title()}(Fields): ...)")
        if not 2 <= len(title) <= 40:
            raise ValueError(f"{where}: título de 2 a 40 caracteres")
        fields = model.model_fields
        if reserved := sorted(_RESERVED & set(fields)):
            raise ValueError(f"{where}: {', '.join(reserved)} é do banco; renomeie o campo")
        if not fields:
            raise ValueError(f"{where}: declare pelo menos um campo")
        for option, names in (("search", search), ("filters", filters), ("unique", unique), ("columns", columns)):
            if unknown := sorted(set(names) - set(fields)):
                raise ValueError(f"{where}: {option} cita campos que {model.__name__} não tem: {', '.join(unknown)}")
        if unknown := sorted(set(sort) - set(fields) - {"created_at", "updated_at"}):
            raise ValueError(f"{where}: sort cita campos que {model.__name__} não tem: {', '.join(unknown)}")
        if optional := [f for f in unique if not fields[f].is_required()]:
            raise ValueError(
                f"{where}: unique só com campo obrigatório ({', '.join(optional)} é opcional: o banco trata vazio como "
                "valor repetido)"
            )
        for field in filters:
            if _choices(fields[field].annotation) is None:
                raise ValueError(f"{where}: filters só com campos Literal[...], Enum ou bool ({field!r} não é)")
        if limit is not None and not _NAME.match(limit):
            raise ValueError(f"{where}: limit é o nome curto de um Limit total do MODULE (ex.: clientes)")
        self.service, self.name, self.model, self.title = service, name, model, title
        self.prefix = service.removeprefix("svc-")
        self.table = f"{self.prefix}_{name}".replace("-", "_")
        self.search, self.filters, self.unique = tuple(search), tuple(filters), tuple(unique)
        self.sort = tuple(dict.fromkeys([*sort, "created_at"]))
        self.limit, self.write = limit, frozenset(write)
        self.live = f"{self.prefix}.{name}"
        self.columns = tuple(columns) or tuple(
            [f for f in fields if _kind(fields[f]) != "textarea"][:_MAX_COLUMNS]
        )
        base = model.__name__
        self.item: type[BaseModel] = create_model(
            f"{base}Item", __base__=_Item, __module__=model.__module__,
            **{f: (info.annotation, _copy(info)) for f, info in fields.items()},
        )
        self.item.__doc__ = f"{title}: um registro."
        self.update: type[BaseModel] = create_model(
            f"{base}Update", __base__=ResourceRef, __module__=model.__module__,
            **{f: (info.annotation | None, _copy(info, default=None)) for f, info in fields.items()},
        )
        self.update.__doc__ = f"{title}: só os campos que mudam."
        filter_fields = {f: (fields[f].annotation | None, None) for f in self.filters}
        self.query: type[ListQuery] = type(f"{base}Query", (ListQuery,), {
            "__module__": model.__module__,
            "__annotations__": {f: annotation for f, (annotation, _) in filter_fields.items()},
            **{f: None for f in filter_fields},
            "sortable": self.sort,
            "default_sort": "-created_at",
            "__doc__": f"{title}: página, busca, filtros e ordem pela URL.",
        })
        self.page: type[Page] = create_model(f"{base}Page", __base__=Page[self.item], __module__=model.__module__)
        self.ref: type[ResourceRef] = ResourceRef  # CLIENTES.ref(id=...): o registro pelo id (o mesmo para todo cadastro)

    def meta(self) -> dict[str, Any]:
        """O que a tela precisa para montar lista e formulário (vai ao contracts.ts como dado)."""
        fields = self.model.model_fields
        return {
            "title": self.title,
            "live": self.live,
            "fields": [_field_meta(name, info) for name, info in fields.items()],
            "columns": [
                {"key": name, "header": _label(name, fields[name]), "kind": _kind(fields[name]),
                 **({"sort": name} if name in self.sort else {})}
                for name in self.columns
            ],
            "filters": [
                {"name": name, "label": _label(name, fields[name]), "options": _options(fields[name])} for name in self.filters
            ],
            "search": ", ".join(_label(name, fields[name]).lower() for name in self.search) or None,
        }


class Resources:
    """As operações de um recurso, na organização de quem age (as rotas de mount chamam estas mesmas)."""

    def mount(self, app: FastAPI, items: Sequence[Resource]) -> None:
        """As 5 rotas de cada recurso (o manifesto do gateway as publica com resources: [nome])."""
        names = [r.name for r in items]
        if len(names) != len(set(names)):
            raise ValueError("resources.mount: recurso repetido")
        for r in items:
            base = f"/{r.name}"
            app.add_api_route(base, _route(self.list, r, r.query, query=True), methods=["GET"], name=f"{r.name} list")
            app.add_api_route(f"{base}/item", _route(self.get, r, ResourceRef, query=True), methods=["GET"], name=f"{r.name} get")
            app.add_api_route(base, _route(self.create, r, r.model), methods=["POST"], name=f"{r.name} create")
            app.add_api_route(f"{base}/update", _route(self.update, r, r.update), methods=["POST"], name=f"{r.name} update")
            app.add_api_route(f"{base}/remove", _route(self.remove, r, ResourceRef), methods=["POST"], name=f"{r.name} remove")

    async def list(self, r: Resource, query: ListQuery) -> Page:
        current_tenant()
        return await db.page(r.table, query, r.page)

    async def get(self, r: Resource, ref: ResourceRef) -> BaseModel:
        row = await db.select(f"{r.table}:{ref.id}")
        if row is None:
            raise ServiceError("ERRO_RECORD_NOT_FOUND", "Registro não encontrado.", status=404)
        return r.item.model_validate(row)

    async def create(self, r: Resource, data: BaseModel) -> BaseModel:
        self._can_write(r)
        data = r.model.model_validate(data.model_dump()) if not isinstance(data, r.model) else data
        if r.limit:
            await plans.check(r.limit, used=await self._count(r))
        row = await db.create(r.table, data.model_dump(mode="json"))
        item = r.item.model_validate(row)
        await self._changed(r, item.id, "created")
        return item

    async def update(self, r: Resource, data: BaseModel) -> BaseModel:
        self._can_write(r)
        changes = data.model_dump(mode="json", exclude_unset=True, exclude={"id"})
        if not changes:
            return await self.get(r, ResourceRef(id=data.id))
        row = await db.merge(f"{r.table}:{data.id}", changes)
        item = r.item.model_validate(row)
        await self._changed(r, item.id, "updated")
        return item

    async def remove(self, r: Resource, ref: ResourceRef) -> ResourceRemoved:
        self._can_write(r)
        await self.get(r, ref)  # de outra organização ou inexistente: 404
        await db.delete(f"{r.table}:{ref.id}")
        await self._changed(r, ref.id, "removed")
        return ResourceRemoved(id=ref.id)

    def _can_write(self, r: Resource) -> None:
        who = current()
        if r.write and (who is None or not (who.is_system or r.write & who.roles)):
            raise ServiceError(error_code(r.service, "FORBIDDEN"), "Seu papel não permite alterar este cadastro.", status=403)

    async def _count(self, r: Resource) -> int:
        rows = await db.query(
            "SELECT count() AS total FROM (SELECT id FROM type::table($tb) WHERE tenant = $tenant) GROUP ALL", tb=r.table
        )
        return rows[0]["total"] if rows else 0

    async def _changed(self, r: Resource, item_id: str, action: Literal["created", "updated", "removed"]) -> None:
        if r.limit and action != "updated":
            await plans.count(r.limit, await self._count(r))  # a tela Plano mostra "3 de 20"
        await bus.live(r.live, ResourceChanged(id=item_id, action=action))


def _route(operation: Any, r: Resource, model: type[BaseModel], *, query: bool = False) -> Any:
    """Função de rota com a assinatura que o FastAPI lê: o modelo vem do corpo (POST) ou da URL (GET)."""

    async def route(data: Any) -> ResponseEnvelope:
        return ResponseEnvelope.success(data=await operation(r, data), service=r.service)

    route.__annotations__ = {"data": Annotated[model, Query()] if query else model, "return": ResponseEnvelope}
    return route


def _copy(info: FieldInfo, **changes: Any) -> FieldInfo:
    merged = FieldInfo.merge_field_infos(info, **changes)
    return merged


def _unwrap(annotation: Any) -> Any:
    """X | None → X; Annotated[X, ...] → X."""
    while True:
        origin = get_origin(annotation)
        if origin is Annotated:
            annotation = get_args(annotation)[0]
        elif origin in (Union, types.UnionType):
            args = [a for a in get_args(annotation) if a is not type(None)]
            if len(args) != 1:
                return annotation
            annotation = args[0]
        else:
            return annotation


def _choices(annotation: Any) -> list[Any] | None:
    base = _unwrap(annotation)
    if get_origin(base) is Literal:
        return list(get_args(base))
    if isinstance(base, type) and issubclass(base, Enum):
        return [member.value for member in base]
    if base is bool:
        return [True, False]
    return None


def _marker(info: FieldInfo) -> str | None:
    for item in info.metadata:
        if isinstance(item, Kind):
            return item.value
    annotation = info.annotation
    for arg in get_args(annotation):  # X | None com Annotated[X, Kind(...)] dentro
        for item in get_args(arg)[1:] if get_origin(arg) is Annotated else ():
            if isinstance(item, Kind):
                return item.value
    return None


def _kind(info: FieldInfo) -> str:
    if marker := _marker(info):
        return marker
    base = _unwrap(info.annotation)
    if _choices(info.annotation) is not None:
        return "boolean" if base is bool else "select"
    if base in (int, float):
        return "number"
    if base is datetime:
        return "datetime"
    if base is date:
        return "date"
    longest = next((m.max_length for m in info.metadata if getattr(m, "max_length", None)), None)
    return "textarea" if longest and longest > _LONG_TEXT else "text"


def _label(name: str, info: FieldInfo) -> str:
    return info.title or name.replace("_", " ").capitalize()


def _options(info: FieldInfo) -> list[dict[str, str]]:
    values = _choices(info.annotation) or []
    if values == [True, False]:
        return [{"value": "true", "label": "Sim"}, {"value": "false", "label": "Não"}]
    return [{"value": str(v), "label": str(v).replace("_", " ").capitalize()} for v in values]


def _field_meta(name: str, info: FieldInfo) -> dict[str, Any]:
    kind = _kind(info)
    meta: dict[str, Any] = {"name": name, "label": _label(name, info), "kind": kind, "required": info.is_required()}
    if kind in ("select", "boolean"):
        meta["options"] = _options(info)
    if info.description:
        meta["hint"] = info.description
    return meta


resources = Resources()
