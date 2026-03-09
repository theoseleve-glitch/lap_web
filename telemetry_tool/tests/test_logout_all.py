"""Tests for logout-all-devices (#0772)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.service import revoke_all_sessions


class TestRevokeAllSessions:
    def test_revokes_and_returns_count(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 3
        conn.execute.return_value = cur

        count = revoke_all_sessions(conn, user_id=42)

        assert count == 3
        conn.execute.assert_any_call(
            "UPDATE refresh_tokens SET revoked_at = NOW() "
            "WHERE user_id = %(uid)s AND revoked_at IS NULL",
            {"uid": 42},
        )
        conn.commit.assert_called_once()

    def test_zero_tokens(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.execute.return_value = cur

        count = revoke_all_sessions(conn, user_id=99)
        assert count == 0

    def test_audit_logged(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 2
        conn.execute.return_value = cur

        revoke_all_sessions(conn, user_id=7)

        # Second execute call is the audit log insert
        calls = conn.execute.call_args_list
        assert len(calls) == 2
        audit_sql = calls[1][0][0]
        assert "audit_log" in audit_sql

    def test_no_rowcount_attribute(self):
        conn = MagicMock()
        cur = MagicMock(spec=[])  # no rowcount
        conn.execute.return_value = cur

        count = revoke_all_sessions(conn, user_id=1)
        assert count == 0
