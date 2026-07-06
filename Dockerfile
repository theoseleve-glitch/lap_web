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
    && mkdir -p /data/uploads /data/parquet /data/exports /data/models /data/sidecars /data/gt_runtime /data/onboarding_drafts \
    && chown -R app:app /data

COPY --chown=app:app telemetry_tool/ telemetry_tool/
COPY --chown=app:app kart_envelope/ kart_envelope/
COPY --chown=app:app predefined_kart_list.csv predefined_track_list.csv ./
COPY --chown=app:app gunicorn.conf.py ./
# Day-15 Phase 2: hand-traced gt_*.geojson polygons consumed by the
# (future) GeoJSON-geometric track matcher. Loader resolves /app/data/
# ground_truth/ via lap_web's gt_loader._resolve_gt_dir() repo-root
# fallback (which now lands inside the image).
COPY --chown=app:app data/ground_truth/ data/ground_truth/

ARG APP_VERSION=1.4.0
ENV PYTHONPATH=/app:/app/telemetry_tool \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}

USER app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "telemetry_tool.web.app:create_app()"]
