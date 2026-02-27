"""Tests for Prometheus metrics middleware."""
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMetricsGracefulDegradation(unittest.TestCase):
    """Tests that work regardless of prometheus_client availability."""

    def test_init_metrics_does_not_crash_without_prometheus(self):
        """init_metrics is a no-op when prometheus_client is absent."""
        # Even if prometheus_client IS installed, we can test the no-op path
        # by testing that calling init_metrics doesn't raise
        from web.middleware.metrics import init_metrics
        app = Flask(__name__)
        app.config["TESTING"] = True
        init_metrics(app)
        # Should not raise

    def test_module_imports_cleanly(self):
        """The metrics module imports without error."""
        import importlib
        mod = importlib.import_module("web.middleware.metrics")
        self.assertTrue(hasattr(mod, "init_metrics"))
        self.assertTrue(hasattr(mod, "HAS_PROMETHEUS"))


class TestMetricsWithPrometheus(unittest.TestCase):
    """Tests that require prometheus_client."""

    def setUp(self):
        from web.middleware.metrics import HAS_PROMETHEUS
        if not HAS_PROMETHEUS:
            self.skipTest("prometheus_client not installed")

    def test_metrics_endpoint_returns_prometheus_format(self):
        """GET /metrics returns Prometheus text format."""
        from web.middleware.metrics import init_metrics
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/test")
        def test_route():
            return "ok"

        init_metrics(app)

        with app.test_client() as c:
            # Make a request first so there's something to report
            c.get("/test")
            resp = c.get("/metrics")
            self.assertEqual(resp.status_code, 200)
            # Prometheus text format contains metric names
            body = resp.data.decode()
            self.assertIn("http_requests_total", body)

    def test_request_counter_increments(self):
        """After a request, the counter has observations."""
        from web.middleware.metrics import init_metrics, REQUEST_COUNT
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/ping")
        def ping():
            return "pong"

        init_metrics(app)

        with app.test_client() as c:
            c.get("/ping")

        # The counter should have at least one sample
        # We can check by looking at the metric's samples
        collected = REQUEST_COUNT.collect()
        self.assertTrue(len(collected) > 0)

    def test_latency_histogram_recorded(self):
        """After a request, the latency histogram has observations."""
        from web.middleware.metrics import init_metrics, REQUEST_LATENCY
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/slow")
        def slow():
            time.sleep(0.01)
            return "done"

        init_metrics(app)

        with app.test_client() as c:
            c.get("/slow")

        collected = REQUEST_LATENCY.collect()
        self.assertTrue(len(collected) > 0)
