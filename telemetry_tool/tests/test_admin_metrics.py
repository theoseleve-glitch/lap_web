"""Tests for admin metrics collector.

Verifies:
- collect_snapshot aggregates system, DB, and security metrics
- store_snapshot inserts into system_metrics_snapshots
- prune_old_snapshots removes old rows, keeps recent ones
- Individual collectors return expected structure
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from admin.metrics_collector import (
    collect_snapshot,
    store_snapshot,
    prune_old_snapshots,
    _collect_system_metrics,
    _collect_db_metrics,
    _collect_security_metrics,
    _collect_upload_metrics,
    _collect_celery_metrics,
)


class TestCollectSystemMetrics:
    def test_returns_cpu_and_memory(self):
        with patch("admin.metrics_collector.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 42.5
            mem = MagicMock()
            mem.percent = 65.3
            mem.total = 8_000_000_000
            mem.available = 2_800_000_000
            mock_psutil.virtual_memory.return_value = mem
            disk = MagicMock()
            disk.percent = 55.0
            disk.total = 100_000_000_000
            disk.free = 45_000_000_000
            mock_psutil.disk_usage.return_value = disk

            result = _collect_system_metrics()

            assert result["cpu_percent"] == 42.5
            assert result["memory_percent"] == 65.3
            assert result["disk_percent"] == 55.0

    def test_handles_psutil_error(self):
        with patch("admin.metrics_collector.psutil", None):
            result = _collect_system_metrics()
            assert result["error"] == "psutil not available"


class TestCollectDbMetrics:
    def test_returns_job_stats(self):
        conn = MagicMock()
        call_count = [0]

        def mock_execute(sql, params=None):
            cur = MagicMock()
            key = call_count[0]
            call_count[0] += 1
            if key == 0:  # active connections
                cur.fetchone.return_value = {"cnt": 5}
            elif key == 1:  # job aggregates
                cur.fetchall.return_value = [
                    {"status": "completed", "cnt": 10},
                    {"status": "failed", "cnt": 2},
                    {"status": "running", "cnt": 1},
                ]
            elif key == 2:  # DB size
                cur.fetchone.return_value = {"size": 52428800}
            return cur

        conn.execute.side_effect = mock_execute

        result = _collect_db_metrics(conn)

        assert result["active_connections"] == 5
        assert result["jobs"]["completed"] == 10
        assert result["jobs"]["failed"] == 2
        assert result["db_size_bytes"] == 52428800

    def test_handles_db_error(self):
        conn = MagicMock()
        conn.execute.side_effect = Exception("DB error")

        result = _collect_db_metrics(conn)
        assert "error" in result


class TestCollectSecurityMetrics:
    def test_returns_event_counts(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"event_type": "login_failed", "cnt": 14},
            {"event_type": "rate_limited", "cnt": 3},
            {"event_type": "auth_denied", "cnt": 7},
        ]
        conn.execute.return_value = cur

        result = _collect_security_metrics(conn)

        assert result["login_failed_24h"] == 14
        assert result["rate_limited_24h"] == 3
        assert result["auth_denied_24h"] == 7

    def test_handles_missing_table(self):
        conn = MagicMock()
        conn.execute.side_effect = Exception("relation does not exist")

        result = _collect_security_metrics(conn)
        assert "error" in result


class TestCollectUploadMetrics:
    def test_returns_upload_counts(self):
        conn = MagicMock()
        call_count = [0]

        def mock_execute(sql, params=None):
            cur = MagicMock()
            key = call_count[0]
            call_count[0] += 1
            if key == 0:  # today's uploads
                cur.fetchone.return_value = {"total": 8, "errors": 1}
            return cur

        conn.execute.side_effect = mock_execute

        result = _collect_upload_metrics(conn)
        assert result["today"] == 8
        assert result["errors"] == 1

    def test_handles_db_error(self):
        conn = MagicMock()
        conn.execute.side_effect = Exception("DB error")

        result = _collect_upload_metrics(conn)
        assert "error" in result


class TestCollectCeleryMetrics:
    def test_returns_queue_lengths(self):
        redis_client = MagicMock()
        redis_client.llen.side_effect = lambda q: {"pipeline": 3, "default": 1}.get(q, 0)

        result = _collect_celery_metrics(redis_client)

        assert result["queue_pipeline"] == 3
        assert result["queue_default"] == 1

    def test_handles_no_redis(self):
        result = _collect_celery_metrics(None)
        assert result["error"] == "redis not available"


class TestCollectSnapshot:
    def test_aggregates_all_collectors(self):
        conn = MagicMock()
        redis_client = MagicMock()
        redis_client.llen.return_value = 0

        with patch("admin.metrics_collector._collect_system_metrics") as mock_sys, \
             patch("admin.metrics_collector._collect_db_metrics") as mock_db, \
             patch("admin.metrics_collector._collect_security_metrics") as mock_sec, \
             patch("admin.metrics_collector._collect_upload_metrics") as mock_up, \
             patch("admin.metrics_collector._collect_celery_metrics") as mock_cel:

            mock_sys.return_value = {"cpu_percent": 50.0}
            mock_db.return_value = {"active_connections": 3}
            mock_sec.return_value = {"login_failed_24h": 5}
            mock_up.return_value = {"today": 2}
            mock_cel.return_value = {"queue_default": 0}

            result = collect_snapshot(conn, redis_client)

            assert "collected_at" in result
            assert result["system"]["cpu_percent"] == 50.0
            assert result["database"]["active_connections"] == 3
            assert result["security"]["login_failed_24h"] == 5
            assert result["uploads"]["today"] == 2
            assert result["celery"]["queue_default"] == 0


class TestStoreSnapshot:
    def test_inserts_row(self):
        conn = MagicMock()
        snapshot = {"system": {"cpu_percent": 50.0}, "collected_at": "2026-02-28T12:00:00Z"}

        store_snapshot(conn, snapshot)

        conn.execute.assert_called_once()
        sql, params = conn.execute.call_args[0]
        assert "INSERT INTO system_metrics_snapshots" in sql
        assert params["metrics"] == json.dumps(snapshot)
        conn.commit.assert_called_once()


class TestPruneOldSnapshots:
    def test_deletes_old_rows(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 5
        conn.execute.return_value = cur

        deleted = prune_old_snapshots(conn, max_age_days=7)

        assert deleted == 5
        conn.execute.assert_called_once()
        sql, params = conn.execute.call_args[0]
        assert "DELETE FROM system_metrics_snapshots" in sql
        assert params["days"] == 7
        conn.commit.assert_called_once()

    def test_returns_zero_when_nothing_to_delete(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.execute.return_value = cur

        deleted = prune_old_snapshots(conn, max_age_days=7)
        assert deleted == 0
