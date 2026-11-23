FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN SCARF_ANALYTICS=false npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src/ ./src/
RUN npm run build \
    && mkdir dist/swagger \
    && cp node_modules/swagger-ui-dist/swagger-ui.css \
          node_modules/swagger-ui-dist/swagger-ui-bundle.js \
          node_modules/swagger-ui-dist/favicon-32x32.png \
          node_modules/swagger-ui-dist/LICENSE dist/swagger/

FROM python:3.12-slim-bookworm AS backend
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
WORKDIR /build
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --system-certs --locked --no-dev --no-install-project
COPY backend/migrations/ ./migrations/
COPY backend/src/ ./src/
RUN uv sync --system-certs --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=backend /build/.venv /build/.venv
COPY --from=frontend /build/dist /app/frontend
ENV SMARTDOC_HOST=0.0.0.0 \
    SMARTDOC_DATABASE_PATH=/data/smartdoc.sqlite3 \
    SMARTDOC_STORAGE_PATH=/data/uploads \
    SMARTDOC_FRONTEND_DIR=/app/frontend \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["/build/.venv/bin/python", "-m", "smartdoc.hosted"]
