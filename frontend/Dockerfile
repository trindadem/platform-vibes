# Frontend em produção (README §9): o build do Vite (com os trilhos) servido por um nginx sem root, com CSP e os
# cabeçalhos de segurança. Contexto de build: raiz do repositório, como os serviços.
#   docker build -f frontend/Dockerfile .
# STORAGE_PUBLIC_URL (no container) entra na CSP: o navegador envia e baixa arquivos direto do armazenamento (seção 5.14).

FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Modelo lido pela imagem ao subir: ${STORAGE_PUBLIC_URL} vira o endereço do armazenamento; as variáveis do nginx ficam.
COPY <<'EOF' /etc/nginx/templates/default.conf.template
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    server_tokens off;

    # Só o próprio site roda script. Estilo inline: os primitivos do Radix ajustam o layout por <style>.
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: ${STORAGE_PUBLIC_URL}; font-src 'self'; connect-src 'self' ${STORAGE_PUBLIC_URL}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;

    # Arquivos com hash no nome nunca mudam: cache de um ano. O index.html é conferido a cada visita.
    location /assets/ {
        expires max;
        try_files $uri =404;
    }
    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok";
    }
    location / {
        expires -1;
        try_files $uri /index.html;
    }
}
EOF
ENV STORAGE_PUBLIC_URL=""
EXPOSE 8080
