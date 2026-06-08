"""Tests for prune_behavioral_events — 180d retention + future-partition rollover."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _conn_with_partitions(existing):
    """Mock conn whose pg_partition queries return the given partition relnames,
    and pg_class existence checks return a row only for names already in `existing`."""
    conn = MagicMock()

    def _execute(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        if "pg_inherits" in sql or ("pg_class" in sql and "LIKE" in sql):
            # listing existing partitions of a parent table
            result.fetchall.return_value = [{"relname": n} for n in existing]
        elif "pg_class" in sql and "relname = :name" in sql:
            name = (params or {}).get("name")
            result.fetchone.return_value = {"oid": 1} if name in existing else None
        else:
            result.fetchall.return_value = []
            result.fetchone.return_value = None
        return result

    conn.execute.side_effect = _execute
    return conn


class TestPruneBehavioralEvents:
    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_constants(self, mock_db):
        from tasks.gdpr_tasks import BEHAVIORAL_RETENTION_DAYS, BEHAVIORAL_PARTITIONED_TABLES
        assert BEHAVIORAL_RETENTION_DAYS == 180
        assert "app_events" in BEHAVIORAL_PARTITIONED_TABLES
        assert "marketing_events" in BEHAVIORAL_PARTITIONED_TABLES

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_drops_aged_partition(self, mock_db):
        from tasks.gdpr_tasks import prune_behavioral_events
        # A partition ~8 months old (well past 180d) for both tables
        aged = (date.today().replace(day=1) - timedelta(days=240))
        aged_name_ae = f"app_events_{aged.year}_{aged.month:02d}"
        aged_name_me = f"marketing_events_{aged.year}_{aged.month:02d}"
        conn = _conn_with_partitions([aged_name_ae, aged_name_me])
        mock_db.return_value = conn

        prune_behavioral_events()

        # Inspect the SQL text (TextClause), not the Call repr.
        drops = [
            str(c.args[0]) for c in conn.execute.call_args_list
            if c.args and "DROP TABLE" in str(c.args[0])
        ]
        assert any(aged_name_ae in d for d in drops), f"app_events aged partition not dropped: {drops}"
        assert any(aged_name_me in d for d in drops), f"marketing_events aged partition not dropped: {drops}"

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_creates_next_month_partition(self, mock_db):
        from tasks.gdpr_tasks import prune_behavioral_events
        conn = _conn_with_partitions([])  # nothing exists -> must create
        mock_db.return_value = conn

        prune_behavioral_events()

        # Inspect the SQL text (TextClause), not the Call repr.
        creates = [
            str(c.args[0]) for c in conn.execute.call_args_list
            if c.args and "CREATE TABLE" in str(c.args[0])
        ]
        # next month's partition for both tables
        nxt = date.today().replace(day=1)
        nxt = (nxt.replace(year=nxt.year + 1, month=1) if nxt.month == 12
               else nxt.replace(month=nxt.month + 1))
        ae = f"app_events_{nxt.year}_{nxt.month:02d}"
        me = f"marketing_events_{nxt.year}_{nxt.month:02d}"
        assert any(ae in c for c in creates), f"next-month app_events partition not created: {creates}"
        assert any(me in c for c in creates), f"next-month marketing_events partition not created: {creates}"

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_idempotent_when_partition_exists(self, mock_db):
        from tasks.gdpr_tasks import prune_behavioral_events
        # next-month partitions already exist -> no CREATE issued (pg_class check short-circuits)
        nxt = date.today().replace(day=1)
        nxt = (nxt.replace(year=nxt.year + 1, month=1) if nxt.month == 12
               else nxt.replace(month=nxt.month + 1))
        existing = [
            f"app_events_{nxt.year}_{nxt.month:02d}",
            f"marketing_events_{nxt.year}_{nxt.month:02d}",
        ]
        conn = _conn_with_partitions(existing)
        mock_db.return_value = conn

        prune_behavioral_events()

        # Inspect the SQL text (TextClause), not the Call repr.
        creates = [
            str(c.args[0]) for c in conn.execute.call_args_list
            if c.args and "CREATE TABLE" in str(c.args[0])
            and any(e in str(c.args[0]) for e in existing)
        ]
        assert not creates, f"idempotency broken — re-created existing partitions: {creates}"


class TestBeatRegistration:
    def test_prune_registered_on_beat(self):
        src = (_PROJECT_ROOT / "celery_app.py").read_text()
        assert "tasks.gdpr_tasks.prune_behavioral_events" in src
        assert "prune-behavioral-events" in src
