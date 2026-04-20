"""Validates the 059 migration upgrades and downgrades cleanly.

Uses a temp PG database when TELEMETRY_PG_URL_TEST is set; otherwise
skips (keeps CI green on sqlite-only environments).
"""
from __future__ import annotations

import os
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TELEMETRY_PG_URL_TEST"),
    reason="needs a disposable PG; set TELEMETRY_PG_URL_TEST",
)


def _alembic(args: list[str]):
    env = {**os.environ, "TELEMETRY_PG_URL": os.environ["TELEMETRY_PG_URL_TEST"]}
    return subprocess.check_call(["alembic", *args], env=env)


def test_059_upgrade_then_downgrade_is_clean():
    _alembic(["upgrade", "058"])
    _alembic(["upgrade", "059"])
    _alembic(["downgrade", "058"])
    # Reapplying should still succeed.
    _alembic(["upgrade", "059"])


def test_059_adds_expected_columns():
    import contextlib
    import psycopg2
    _alembic(["upgrade", "059"])
    with contextlib.closing(psycopg2.connect(os.environ["TELEMETRY_PG_URL_TEST"])) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name='sessions'
                  AND column_name IN ('source', 'data_profile', 'capabilities')
            """)
            rows = dict(cur.fetchall())
    assert rows.get("source") == "text"
    assert rows.get("data_profile") == "jsonb"
    assert rows.get("capabilities") == "jsonb"
