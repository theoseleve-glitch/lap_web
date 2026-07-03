"""081 migration: sessions reflection columns + RLS-scoped session_competitors."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MIG = (_ROOT / "alembic" / "versions" / "081_feeling_competition.py").read_text(encoding="utf-8")


def test_chains_off_deployed_head_077():
    assert 'down_revision = "077_stripe_pending_entitlements"' in _MIG
    assert 'revision = "081_feeling_competition"' in _MIG


def test_adds_sessions_reflection_columns():
    for col in ("result_tags", "driver_perceived_conditions", "felt_performance_rating",
                "race_position", "race_total_competitors", "race_gap_to_leader_s",
                "race_gap_to_nearest_s", "race_laps_completed", "race_is_dnf"):
        assert col in _MIG, f"missing sessions column {col}"


def test_session_competitors_is_rls_scoped():
    assert "session_competitors" in _MIG
    assert "workspace_id" in _MIG
    assert "ENABLE ROW LEVEL SECURITY" in _MIG
    assert "FORCE ROW LEVEL SECURITY" in _MIG
    assert "session_competitors_tenant_isolation" in _MIG
    assert "current_setting('app.current_workspace_id'" in _MIG
    # never the pre-044 wrong GUC
    assert "app.workspace_id'" not in _MIG


def test_grants_to_app_and_maint_roles():
    assert "telemetry_app" in _MIG
    assert "telemetry_maint" in _MIG


def test_has_downgrade():
    assert "def downgrade" in _MIG
    # downgrade drops the table via the idiomatic Alembic API (op.drop_table),
    # matching the upgrade's op.create_table — not raw "DROP TABLE" SQL.
    assert "drop_table" in _MIG and "session_competitors" in _MIG
