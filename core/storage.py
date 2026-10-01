"""Arquivos: qualquer armazenamento compatível com S3 (RustFS no ambiente local; S3, R2, B2... em produção). README §5.14

O arquivo nunca passa pelos serviços nem pelo gateway: o navegador envia direto ao armazenamento, por um link assinado.

    pedido = await storage.upload(data, accept=IMAGES, max_bytes=2_000_000)  # 1. link de envio (Upload)
    # 2. a tela envia o arquivo (core/api.ts: uploadFile / useUpload)
    arquivo = await storage.keep(KeepRequest.key)                             # 3. confirma: sai da área temporária
    await db.merge(registro, {"logo": arquivo.key})                           #    e o serviço guarda a chave
    link = storage.url(arquivo.key)                                           # 4. download/visualização (5 min)
    conteudo = await storage.read(arquivo.key, max_bytes=10_000_000)          #    o serviço lê (ex.: extrair texto)
    await storage.delete(arquivo.key)                                         # 5. ao apagar o registro

Trilhos:
- Toda chave começa pela organização de quem age: tmp/<org>/... no envio, t/<org>/<serviço>/... depois de guardada.
  Chave de outra organização é, para quem pede, inexistente (404 ERRO_FILE_NOT_FOUND). Ninguém escolhe a chave.
- Tamanho e tipo entram na assinatura do envio: o armazenamento recusa outro tamanho ou outro tipo. O serviço diz o
  que aceita (accept=tipos ou prefixos como "image/") e o máximo (max_bytes); fora disso, 422 antes de assinar.
- Envio não confirmado some sozinho em 1 dia (regra de ciclo de vida da área tmp/, criada no boot).
- Download: imagens comuns e PDF abrem na tela; o resto (inclusive SVG e HTML, que podem trazer script) sai como
  anexo. O nome original vai só no Content-Disposition, nunca na chave.
- Credenciais só no ambiente; o link assinado vale para uma operação, numa chave, por pouco tempo.

Variáveis: STORAGE_URL (endereço interno; padrão http://localhost:9000), STORAGE_PUBLIC_URL (o que o navegador
alcança; padrão = STORAGE_URL), STORAGE_BUCKET, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY (obrigatórias),
STORAGE_REGION (padrão us-east-1) e STORAGE_CORS_ORIGINS (origens da tela que enviam direto ao armazenamento,
separadas por vírgula; o compose repassa CORS_ORIGINS).
"""
import asyncio
import logging
import re
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote, unquote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from core.envelope import ServiceError
from core.security import current_tenant

UPLOAD_SECONDS = 600  # validade do link de envio
DOWNLOAD_SECONDS = 300  # validade padrão do link de download
TEMP_DAYS = 1  # envio não confirmado some depois disso
IMAGES = ("image/png", "image/jpeg", "image/webp", "image/gif")  # atalho para accept=
_INLINE = frozenset({*IMAGES, "image/avif", "application/pdf"})  # abrem na tela; o resto sai como anexo
_FILENAME_META = "filename"
_CONTENT_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$")
_SERVICE = re.compile(r"^svc-[a-z0-9-]+$")
_KEY_ID = re.compile(r"^[0-9a-f]{32}$")

log = logging.getLogger("core.storage")


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    url: str = "http://localhost:9000"
    public_url: str | None = None
    bucket: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")]
    access_key: SecretStr
    secret_key: SecretStr
    region: str = "us-east-1"


class _CorsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, value: Any) -> Any:
        return [o.strip() for o in value.split(",") if o.strip()] if isinstance(value, str) else value


class UploadRequest(BaseModel):
    """O que a tela diz antes de enviar: nome, tipo e tamanho do arquivo (o envio só vale para esse tamanho e tipo)."""

    model_config = ConfigDict(extra="forbid")

    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    content_type: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=255)]
    size: int = Field(..., ge=1, description="Tamanho em bytes")

    @field_validator("content_type")
    @classmethod
    def _media_type(cls, value: str) -> str:
        if not _CONTENT_TYPE.match(value):
            raise ValueError("Tipo de arquivo inválido.")
        return value


class Upload(BaseModel):
    """Link de envio: a tela faz PUT do arquivo em url com estes cabeçalhos e depois confirma a key no serviço."""

    key: str
    url: str
    headers: dict[str, str] = Field(..., description="Cabeçalhos que o PUT precisa levar exatamente assim")
    expires_at: datetime


class KeepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(max_length=300)] = Field(..., description="A key devolvida em Upload")


class StoredFile(BaseModel):
    key: str = Field(..., description="Chave definitiva: guarde no registro")
    filename: str
    content_type: str
    size: int


class Storage:
    def __init__(self) -> None:
        self._settings: StorageSettings | None = None
        self._service: str | None = None
        self._client: Any = None  # operações (endereço interno)
        self._signer: Any = None  # links assinados (endereço que o navegador alcança: a assinatura inclui o host)

    async def connected(self, service: str) -> "Storage":
        """No boot (lifespan): confere as credenciais e garante o bucket, a expiração da área tmp/ e o CORS."""
        if not _SERVICE.match(service):
            raise ValueError(f"storage.connected: nome de serviço inválido {service!r} (svc-<nome>)")
        s = StorageSettings()
        self._settings, self._service = s, service
        self._client = _client(s, s.url)
        self._signer = _client(s, s.public_url or s.url)
        await asyncio.to_thread(self._prepare_bucket)
        return self

    async def upload(
        self, request: UploadRequest, *, accept: Iterable[str], max_bytes: int, folder: str = "files"
    ) -> Upload:
        """Link de PUT (10 min) só para este tamanho e tipo, numa chave nova da área temporária da organização."""
        s = self._ready()
        accepted = tuple(accept)
        if not any(request.content_type == a or (a.endswith("/") and request.content_type.startswith(a)) for a in accepted):
            raise ServiceError("ERRO_FILE_TYPE", f"Tipo de arquivo não aceito aqui ({', '.join(accepted)}).", status=422)
        if request.size > max_bytes:
            raise ServiceError("ERRO_FILE_TOO_LARGE", f"Arquivo maior que o permitido ({_human(max_bytes)}).", status=422)
        if not re.fullmatch(r"[a-z0-9-]{1,40}", folder):
            raise ValueError(f"folder inválido: {folder!r} (a-z, 0-9 e hífen)")
        key = f"tmp/{_tenant_segment()}/{self._service}/{folder}/{uuid.uuid4().hex}"
        headers = {"Content-Type": request.content_type, f"x-amz-meta-{_FILENAME_META}": quote(_clean_name(request.filename))}
        url = self._signer.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": s.bucket,
                "Key": key,
                "ContentType": request.content_type,
                "ContentLength": request.size,
                "Metadata": {_FILENAME_META: headers[f"x-amz-meta-{_FILENAME_META}"]},
            },
            ExpiresIn=UPLOAD_SECONDS,
        )
        return Upload(key=key, url=url, headers=headers, expires_at=datetime.now(UTC) + timedelta(seconds=UPLOAD_SECONDS))

    async def keep(self, key: str) -> StoredFile:
        """Confirma um envio: copia da área temporária para a definitiva (t/<org>/<serviço>/...) e apaga o temporário."""
        s = self._ready()
        parts = key.split("/")
        tenant = _tenant_segment()
        if len(parts) != 5 or parts[:3] != ["tmp", tenant, self._service] or not _KEY_ID.match(parts[4]):
            raise _not_found()
        final = "/".join(["t", tenant, self._service, parts[3], parts[4]])
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=s.bucket, Key=key)
            await asyncio.to_thread(
                self._client.copy_object, Bucket=s.bucket, Key=final, CopySource={"Bucket": s.bucket, "Key": key},
                MetadataDirective="COPY",
            )
            await asyncio.to_thread(self._client.delete_object, Bucket=s.bucket, Key=key)
        except ClientError as exc:
            if _missing(exc):
                raise _not_found() from None  # não enviado ainda, expirado ou já confirmado
            raise
        return StoredFile(
            key=final,
            filename=unquote(head.get("Metadata", {}).get(_FILENAME_META, "")) or parts[4],
            content_type=head.get("ContentType", "application/octet-stream"),
            size=head["ContentLength"],
        )

    def url(self, key: str, *, ttl: int = DOWNLOAD_SECONDS, filename: str | None = None, content_type: str | None = None) -> str:
        """Link de GET assinado (padrão 5 min) para um arquivo guardado da organização atual."""
        s = self._ready()
        self._own(key)
        inline = content_type in _INLINE if content_type else False
        disposition = "inline" if inline else "attachment"
        if filename:
            disposition += f"; filename*=UTF-8''{quote(_clean_name(filename))}"
        params = {"Bucket": s.bucket, "Key": key, "ResponseContentDisposition": disposition}
        if content_type and not inline:
            params["ResponseContentType"] = "application/octet-stream"  # nada que o navegador interprete
        return self._signer.generate_presigned_url("get_object", Params=params, ExpiresIn=max(1, min(ttl, 7 * 86400)))

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        """Conteúdo de um arquivo guardado da organização atual, para o serviço processar (extrair texto, conferir).
        Maior que max_bytes → 422 ERRO_FILE_TOO_LARGE, sem baixar."""
        s = self._ready()
        self._own(key)
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=s.bucket, Key=key)
            if head["ContentLength"] > max_bytes:
                raise ServiceError("ERRO_FILE_TOO_LARGE", f"Arquivo maior que o permitido ({_human(max_bytes)}).", status=422)
            body = (await asyncio.to_thread(self._client.get_object, Bucket=s.bucket, Key=key))["Body"]
            return await asyncio.to_thread(body.read, max_bytes + 1)
        except ClientError as exc:
            if _missing(exc):
                raise _not_found() from None
            raise

    async def delete(self, key: str) -> None:
        """Apaga um arquivo guardado da organização atual (não existir não é erro)."""
        s = self._ready()
        self._own(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=s.bucket, Key=key)

    def _own(self, key: str) -> None:
        parts = key.split("/")
        if len(parts) != 5 or parts[:2] != ["t", _tenant_segment()] or not _KEY_ID.match(parts[4]) or ".." in key:
            raise _not_found()

    def _ready(self) -> StorageSettings:
        if self._settings is None or self._service is None:
            raise RuntimeError("storage não conectado: await storage.connected(SERVICE) no lifespan (README §5.14)")
        return self._settings

    def _prepare_bucket(self) -> None:
        s = self._ready()
        try:
            self._client.head_bucket(Bucket=s.bucket)
        except ClientError as exc:
            if not _missing(exc):
                raise RuntimeError(f"storage: sem acesso ao bucket {s.bucket!r} (confira STORAGE_*)") from None
            self._client.create_bucket(Bucket=s.bucket)
        rules = [
            {"ID": "cv-tmp", "Status": "Enabled", "Filter": {"Prefix": "tmp/"}, "Expiration": {"Days": TEMP_DAYS}},
            {"ID": "cv-multipart", "Status": "Enabled", "Filter": {"Prefix": ""}, "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}},
        ]
        origins = _CorsSettings().cors_origins
        cors = {"CORSRules": [{"AllowedOrigins": origins, "AllowedMethods": ["PUT", "GET"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 600}]}
        # Em produção o bucket pode ser gerido pela infraestrutura (sem permissão para isso): avisa e segue.
        for call, kwargs in (
            (self._client.put_bucket_lifecycle_configuration, {"LifecycleConfiguration": {"Rules": rules}}),
            *([(self._client.put_bucket_cors, {"CORSConfiguration": cors})] if origins else []),
        ):
            try:
                call(Bucket=s.bucket, **kwargs)
            except ClientError as exc:
                log.warning("storage: %s não aplicado no bucket %s (%s)", call.__name__, s.bucket, exc.response.get("Error", {}).get("Code"))


def _client(s: StorageSettings, endpoint: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=s.access_key.get_secret_value(),
        aws_secret_access_key=s.secret_key.get_secret_value(),
        region_name=s.region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )


def _tenant_segment() -> str:
    tenant = current_tenant()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tenant):
        raise ServiceError("ERRO_TENANT_REQUIRED", "Selecione uma organização para continuar.", status=403)
    return tenant


def _clean_name(name: str) -> str:
    """Só o nome (sem pasta), sem caractere de controle, até 200 caracteres."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C").strip()
    return base[:200] or "arquivo"


def _human(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB".replace(".", ",") if size >= 1_000_000 else f"{size // 1000} KB"


def _missing(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


def _not_found() -> ServiceError:
    return ServiceError("ERRO_FILE_NOT_FOUND", "Arquivo não encontrado.", status=404)


storage = Storage()
