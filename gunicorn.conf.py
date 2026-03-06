"""Gunicorn configuration for production.

Used via: gunicorn -c gunicorn.conf.py telemetry_tool.web.app:create_app()
"""
import multiprocessing
import os

# Server
bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))
worker_class = "sync"
timeout = 300  # 5 min — accommodates large uploads
graceful_timeout = 30
keepalive = 5

# Logging — JSON access log to stdout (parsed by log aggregation)
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
