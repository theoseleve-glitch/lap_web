"""Tests for audit_log helper."""
import json
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, g


class TestAuditLog(unittest.TestCase):

    def _make_app(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        return app

    def test_audit_log_inserts_row(self):
        """audit_log() executes INSERT into audit_log table."""
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

        from web.middleware.audit import audit_log

        app = self._make_app()
        with app.test_request_context(
            "/api/v1/test",
            environ_base={"REMOTE_ADDR": "1.2.3.4"},
            headers={"User-Agent": "TestAgent/1.0", "X-Request-Id": "req-123"},
        ):
            g.current_user_id = 42
            g.workspace_id = 7
            mock_conn = MagicMock()
            audit_log(mock_conn, "team_created", {"team_id": 1})
            mock_conn.execute.assert_called_once()
            args = mock_conn.execute.call_args
            self.assertIn("INSERT INTO audit_log", args[0][0])
            params = args[0][1]
            self.assertEqual(params["uid"], 42)
            self.assertEqual(params["wsid"], 7)
            self.assertEqual(params["action"], "team_created")
            self.assertEqual(params["ip"], "1.2.3.4")
            self.assertEqual(params["rid"], "req-123")
            details = json.loads(params["details"])
            self.assertEqual(details["team_id"], 1)

    def test_audit_log_handles_missing_user(self):
        """audit_log() works when g.current_user_id is not set."""
        from web.middleware.audit import audit_log

        app = self._make_app()
        with app.test_request_context("/api/v1/test"):
            # Don't set g.current_user_id
            mock_conn = MagicMock()
            audit_log(mock_conn, "anonymous_action", {})
            params = mock_conn.execute.call_args[0][1]
            self.assertIsNone(params["uid"])

    def test_audit_log_truncates_long_values(self):
        """IP truncated to 45 chars."""
        from web.middleware.audit import audit_log

        app = self._make_app()
        long_ip = "x" * 100
        with app.test_request_context(
            "/api/v1/test",
            environ_base={"REMOTE_ADDR": long_ip},
        ):
            g.current_user_id = 1
            mock_conn = MagicMock()
            audit_log(mock_conn, "test", {})
            params = mock_conn.execute.call_args[0][1]
            self.assertEqual(len(params["ip"]), 45)

    def test_audit_log_empty_details(self):
        """audit_log() with None details stores empty JSON object."""
        from web.middleware.audit import audit_log

        app = self._make_app()
        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            mock_conn = MagicMock()
            audit_log(mock_conn, "test_action")
            params = mock_conn.execute.call_args[0][1]
            self.assertEqual(params["details"], "{}")
