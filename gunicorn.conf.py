"""Gunicorn configuration for production.

Used via: gunicorn -c gunicorn.conf.py telemetry_tool.web.app:create_app()
"""
import multiprocessing
import os

# Server
bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"
timeout = 300  # 5 min — accommodates large uploads
graceful_timeout = 30
keepalive = 2  # Short keepalive — Caddy handles client-side keepalive

# Logging — do NOT use "/dev/stderr" for accesslog/errorlog, gunicorn 25.x
# opens it with 'a+' mode which fails (not seekable). Use "-" instead.
accesslog = "-"
errorlog = "-"
access_log_format = (
    '{"timestamp":"%(t)s","method":"%(m)s","path":"%(U)s","query":"%(q)s",'
    '"status":"%(s)s","latency_s":"%(D)s","bytes":%(B)s,'
    '"ip":"%(h)s","user_agent":"%(a)s","pid":"%(p)s"}'
)
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Process management
max_requests = 1000  # Recycle workers to prevent memory leaks
max_requests_jitter = 50
preload_app = False  # Each worker creates its own app (DB connections)

# Security
forwarded_allow_ips = "*"  # Caddy sets X-Forwarded-For


def post_worker_init(worker):
    """Re-enable gunicorn.access after app initialization.

    Alembic's env.py calls fileConfig() during init_pg() which can set
    disabled=True on pre-existing loggers. This hook runs after the WSGI
    app is loaded in the worker, ensuring the access logger is enabled.
    """
    import logging

    access_logger = logging.getLogger("gunicorn.access")
    access_logger.disabled = False
    access_logger.setLevel(logging.INFO)
