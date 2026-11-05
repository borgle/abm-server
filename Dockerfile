FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ABM_HOST=0.0.0.0 \
    ABM_PORT=18050 \
    ABM_DATABASE_URL=sqlite+aiosqlite:////data/abm.db

WORKDIR /app

COPY pyproject.toml README.md ./
COPY abm_server ./abm_server

RUN python -m pip install ".[render,s3]" \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 abm \
    && mkdir -p /data \
    && chown -R abm:abm /app /data

USER abm

EXPOSE 18050

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18050/healthz', timeout=3)"

CMD ["sh", "-c", "abm-server-migrate && exec abm-server"]

