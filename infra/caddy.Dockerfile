# Caddy serving the built frontend, proxying /api and /ws to the backend, with automatic HTTPS (PROMPT.md §12).
FROM node:20-slim AS web
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/
RUN npm --prefix frontend ci --no-fund --no-audit
COPY frontend/ frontend/
COPY shared/ shared/
RUN npm --prefix frontend run build

FROM caddy:2
COPY --from=web /app/frontend/dist /srv
COPY infra/Caddyfile /etc/caddy/Caddyfile
