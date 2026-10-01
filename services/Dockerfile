# Imagem única de serviços e gateway (README §5.5). Contexto de build: raiz do repositório.
#   serviço: docker build -f services/Dockerfile --build-arg SERVICE=billing .
#   gateway: docker build -f services/Dockerfile --build-arg APP_DIR=gateway .
# A imagem contém só o core e a pasta do app, roda sem root e sem cabeçalho "server".
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Dependências antes do código: esta camada é compartilhada por todos os serviços
# e só é refeita quando o pyproject.toml muda.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
        > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

ARG SERVICE
ARG APP_DIR=services/svc-${SERVICE}
COPY core/ core/
COPY ${APP_DIR}/ ./

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
