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

    @staticmethod
    def _audit_insert(mock_conn):
        """Return (sql, params) of the audit_log INSERT among all execute calls.

        Robust to the INSERT being wrapped in SAVEPOINT/RELEASE statements, so
        callers don't rely on it being the last (or only) execute call.
        """
        for c in mock_conn.execute.call_args_list:
            if "INSERT INTO audit_log" in c.args[0]:
                return c.args[0], c.args[1]
        raise AssertionError("audit_log INSERT was not executed")

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
            sql, params = self._audit_insert(mock_conn)
            self.assertIn("INSERT INTO audit_log", sql)
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
            _, params = self._audit_insert(mock_conn)
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
            _, params = self._audit_insert(mock_conn)
            self.assertEqual(len(params["ip"]), 45)

    def test_audit_log_empty_details(self):
        """audit_log() with None details stores empty JSON object."""
        from web.middleware.audit import audit_log

        app = self._make_app()
        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            mock_conn = MagicMock()
            audit_log(mock_conn, "test_action")
            _, params = self._audit_insert(mock_conn)
            self.assertEqual(params["details"], "{}")

    def test_audit_log_failure_isolated_in_savepoint(self):
        """A failing audit INSERT must be wrapped in a SAVEPOINT so it cannot
        abort the surrounding transaction.

        Regression guard for the ghost-session delete bug: an audit_log INSERT
        that errors at the DB level (e.g. a schema-drifted column) used to
        poison the connection, turning the delete's conn.commit() into a silent
        ROLLBACK. The INSERT must run between SAVEPOINT and ROLLBACK TO SAVEPOINT
        so the outer delete transaction survives an audit failure.
        """
        from web.middleware.audit import audit_log

        app = self._make_app()
        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            g.workspace_id = 1
            mock_conn = MagicMock()

            def execute(sql, *args, **kwargs):
                if "INSERT INTO audit_log" in sql:
                    raise Exception(
                        'column "new_value" of relation "audit_log" does not exist'
                    )
                return MagicMock()

            mock_conn.execute.side_effect = execute

            # Must swallow the failure WITHOUT propagating it...
            audit_log(mock_conn, "session.delete", {"session_id": "s1"})

            executed = [c.args[0].upper() for c in mock_conn.execute.call_args_list]
            # ...by opening a SAVEPOINT before the INSERT...
            self.assertTrue(
                any(s.startswith("SAVEPOINT") for s in executed),
                "audit_log must open a SAVEPOINT before the INSERT",
            )
            # ...and rolling back to it on failure (not aborting the whole txn).
            self.assertTrue(
                any("ROLLBACK TO SAVEPOINT" in s for s in executed),
                "audit_log must ROLLBACK TO SAVEPOINT on failure",
            )
