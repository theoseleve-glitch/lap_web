"""Prometheus metrics for the Flask API.

Registers request counters, latency histograms, and a ``/metrics`` scrape
endpoint.  Gracefully degrades when ``prometheus_client`` is not installed
(local dev / PyInstaller builds).

Usage in ``create_app()``::

    from web.middleware.metrics import init_metrics
    init_metrics(app)
"""
import logging
import time

from flask import g, request

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    logger.info("prometheus_client not installed; /metrics endpoint disabled")

if HAS_PROMETHEUS:
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "endpoint"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )
    ACTIVE_REQUESTS = Gauge(
        "http_requests_active",
        "Currently active HTTP requests",
    )
    WEBHOOK_EVENTS = Counter(
        "stripe_webhook_events_total",
        "Stripe webhook events processed",
        ["event_type", "outcome"],
    )


def init_metrics(app):
    """Register Prometheus metrics hooks and /metrics endpoint.

    No-op when ``prometheus_client`` is not installed.
    """
    if not HAS_PROMETHEUS:
        logger.info("Skipping Prometheus metrics (library not available)")
        return

    @app.before_request
    def _metrics_start():
        g._metrics_start = time.monotonic()
        ACTIVE_REQUESTS.inc()

    @app.after_request
    def _metrics_record(response):
        if hasattr(g, "_metrics_start"):
            latency = time.monotonic() - g._metrics_start
            endpoint = request.endpoint or "unknown"
            REQUEST_LATENCY.labels(
                method=request.method,
                endpoint=endpoint,
            ).observe(latency)
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=response.status_code,
            ).inc()
            ACTIVE_REQUESTS.dec()
        return response

    @app.route("/metrics")
    def prometheus_metrics():
        """Prometheus scrape endpoint."""
        from flask import Response

        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    logger.info("Prometheus metrics enabled at /metrics")
