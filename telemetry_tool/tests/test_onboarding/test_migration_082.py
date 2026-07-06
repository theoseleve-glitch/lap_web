"""Test migration 082: track_onboarding_requests.email_count (bounded
auto-resend fast-follow).

Mirrors test_migration_081.py: a structural check that runs everywhere (no
PG needed) plus a PG column-existence check that skips when
TELEMETRY_PG_URL is unset.
"""
import importlib.util
import inspect
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_pg_url = os.environ.get("TELEMETRY_PG_URL", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_url,
    reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL migration test",
)

_MIGRATION = (
    _PROJECT_ROOT / "alembic" / "versions" / "082_onboarding_email_count.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m082", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_file_exists():
    assert _MIGRATION.exists(), f"Missing migration file: {_MIGRATION}"


def test_082_revision_chains_off_081():
    """Runs without PG: 082 is a valid revision chained onto the 081 head."""
    mod = _load_migration()
    assert mod.revision == "082_onboarding_email_count"
    assert mod.down_revision == "081_track_onboarding_requests"
    assert mod.branch_labels is None
    assert mod.depends_on is None
    assert callable(mod.upgrade) and callable(mod.downgrade)


def test_082_no_other_migration_claims_081_as_parent():
    """Single-head guard: 082 must be the ONLY file chaining off 081."""
    versions_dir = _MIGRATION.parent
    claimants = [
        p for p in versions_dir.glob("*.py")
        if p.name != _MIGRATION.name
        and 'down_revision = "081_track_onboarding_requests"' in p.read_text(encoding="utf-8")
    ]
    assert claimants == [], f"081 has multiple children (broken alembic head): {claimants}"


def test_082_adds_email_count_column():
    upgrade_src = inspect.getsource(_load_migration().upgrade)
    assert "track_onboarding_requests" in upgrade_src
    assert '"email_count"' in upgrade_src
    assert "nullable=False" in upgrade_src
    assert 'server_default="0"' in upgrade_src


def test_082_downgrade_drops_column():
    downgrade_src = inspect.getsource(_load_migration().downgrade)
    assert "track_onboarding_requests" in downgrade_src
    assert "email_count" in downgrade_src


@_skip_no_pg
def test_082_column_exists_in_pg():
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(_pg_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name='track_onboarding_requests' AND column_name='email_count'"
            )
            row = cur.fetchone()
            assert row is not None, "email_count column missing"
            _, is_nullable, column_default = row
            assert is_nullable == "NO"
            assert column_default is not None and "0" in column_default
    finally:
        conn.close()
