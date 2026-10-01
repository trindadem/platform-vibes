# Imagem única de serviços e gateway (README §5.5). Contexto de build: raiz do repositório.
#   serviço: docker build -f services/Dockerfile --build-arg SERVICE=billing .
#   gateway: docker build -f services/Dockerfile --build-arg APP_DIR=gateway .
# A imagem contém só o core e a pasta do app, roda sem root e sem cabeçalho "server".

# Dependências: exatamente as versões do uv.lock, num estágio separado (o uv não vai para a imagem final).
# Esta camada é compartilhada por todos os serviços e só é refeita quando o pyproject.toml ou o uv.lock mudam.
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# --locked: lock defasado em relação ao pyproject.toml derruba o build (rode uv lock e versione).
RUN uv sync --locked --no-dev --no-install-project --no-cache

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app

ARG SERVICE
ARG APP_DIR=services/svc-${SERVICE}
COPY core/ core/
COPY ${APP_DIR}/ ./

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# Conexão ociosa vive 120 s, mais que em quem chama (Traefik: 90 s; gateway: 5 s). Quem chama sempre a descarta
# primeiro e nunca reaproveita uma que o servidor está fechando (502 avulso). O padrão do uvicorn é 5 s.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-keep-alive", "120"]
