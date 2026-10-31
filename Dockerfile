# Imagen de producción: compila la PWA con Node y la sirve FastAPI con Python.
# Una sola imagen, un solo proceso HTTP, migraciones al arrancar.

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src \
    NEXO_ENV=production \
    NEXO_STATIC_DIR=/app/web/dist

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY --from=web /web/dist ./web/dist

RUN useradd --create-home --uid 10001 nexo \
    && mkdir -p /app/var /app/.sec_cache /app/.price_cache \
    && chown -R nexo:nexo /app
USER nexo

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

# `alembic upgrade head` es idempotente: aplica solo las migraciones pendientes.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
