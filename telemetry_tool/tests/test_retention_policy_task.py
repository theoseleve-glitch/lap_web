"""Tests for tier-based raw data retention enforcement job."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.gdpr_tasks import _enforce_raw_data_retention_impl


class _Result:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


def test_enforces_retention_and_deletes_old_files(tmp_path):
    raw_dir = tmp_path / "raw"
    ws = raw_dir / "1"
    ws.mkdir(parents=True)
    old_file = ws / "old.csv"
    old_file.write_text("old")
    new_file = ws / "new.csv"
    new_file.write_text("new")

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=40)).timestamp()
    os.utime(old_file, (old_ts, old_ts))

    conn = MagicMock()

    def _execute(sql, params=None):
        sql_s = str(sql)
        if "SELECT w.id AS workspace_id" in sql_s:
            m = MagicMock()
            m.fetchall.return_value = [{"workspace_id": 1, "tier": "free"}]
            return m
        if "DELETE FROM" in sql_s:
            return _Result(rowcount=2)
        return _Result(rowcount=0)

    conn.execute.side_effect = _execute

    with patch("tasks.gdpr_tasks.get_pg_connection", return_value=conn), \
         patch.dict(os.environ, {"TELEMETRY_RAW_DIR": str(raw_dir)}):
        result = _enforce_raw_data_retention_impl()

    assert result["workspaces"] == 1
    assert result["deleted_rows"] >= 2
    assert result["deleted_files"] == 1
    assert not old_file.exists()
    assert new_file.exists()
