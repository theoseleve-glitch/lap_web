FROM python:3.11-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY telemetry_tool/ telemetry_tool/
COPY kart_envelope/ kart_envelope/

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "--timeout", "120", "telemetry_tool.web.app:create_app()"]
