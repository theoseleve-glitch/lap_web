# ── Builder stage: compile C extensions (psycopg2, argon2) ────────────
FROM python:3.11-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt gunicorn resend stripe prometheus_client

# ── Final stage: slim runtime without gcc ─────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

# Runtime dependency: libpq for psycopg2 (no gcc, no -dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Non-root user
RUN adduser --system --no-create-home --group app \
    && mkdir -p /data/uploads /data/parquet /data/exports \
    && chown -R app:app /data

COPY --chown=app:app telemetry_tool/ telemetry_tool/
COPY --chown=app:app kart_envelope/ kart_envelope/

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "--timeout", "300", "--access-logfile", "-", "telemetry_tool.web.app:create_app()"]
