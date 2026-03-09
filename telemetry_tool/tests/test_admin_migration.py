"""Tests for migration 022 — Race Control tables.

Validates migration module structure, revision chain, and that
upgrade/downgrade define the expected operations.
"""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_migration():
    """Import migration module directly."""
    import importlib.util
    migration_path = _PROJECT_ROOT / "alembic" / "versions" / "022_race_control.py"
    spec = importlib.util.spec_from_file_location("migration_022", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration022Structure:
    def test_revision_chain(self):
        mod = _load_migration()
        assert mod.revision == "022"
        assert mod.down_revision == "021"

    def test_upgrade_function_exists(self):
        mod = _load_migration()
        assert callable(mod.upgrade)

    def test_downgrade_function_exists(self):
        mod = _load_migration()
        assert callable(mod.downgrade)


class TestMigration022Operations:
    """Verify that upgrade() calls the expected alembic ops by mocking."""

    def test_upgrade_adds_user_columns(self):
        from unittest.mock import MagicMock, call, patch
        mod = _load_migration()

        with patch("alembic.op.add_column") as mock_add, \
             patch("alembic.op.create_table") as mock_ct, \
             patch("alembic.op.create_index") as mock_ci:
            mod.upgrade()

        # Should add is_superadmin and admin_role to users
        add_calls = mock_add.call_args_list
        table_names = [c[0][0] for c in add_calls]
        assert all(t == "users" for t in table_names)
        col_names = [c[0][1].name for c in add_calls]
        assert "is_superadmin" in col_names
        assert "admin_role" in col_names
        # Should NOT re-add totp columns (already in migration 020)
        assert "totp_secret" not in col_names
        assert "totp_enabled" not in col_names

    def test_upgrade_creates_five_tables(self):
        from unittest.mock import patch
        mod = _load_migration()

        with patch("alembic.op.add_column"), \
             patch("alembic.op.create_table") as mock_ct, \
             patch("alembic.op.create_index"):
            mod.upgrade()

        created_tables = [c[0][0] for c in mock_ct.call_args_list]
        assert "admin_audit_log" in created_tables
        assert "system_metrics_snapshots" in created_tables
        assert "stripe_webhook_log" in created_tables
        assert "security_events" in created_tables
        assert "incident_notes" in created_tables
        assert len(created_tables) == 5

    def test_upgrade_creates_indexes(self):
        from unittest.mock import patch
        mod = _load_migration()

        with patch("alembic.op.add_column"), \
             patch("alembic.op.create_table"), \
             patch("alembic.op.create_index") as mock_ci:
            mod.upgrade()

        index_names = [c[0][0] for c in mock_ci.call_args_list]
        assert "idx_admin_audit_admin" in index_names
        assert "idx_admin_audit_target" in index_names
        assert "idx_admin_audit_action" in index_names
        assert "idx_metrics_collected" in index_names
        assert "idx_stripe_wh_type" in index_names
        assert "idx_stripe_wh_status" in index_names
        assert "idx_security_type_created" in index_names
        assert "idx_security_ip" in index_names
        assert "idx_incidents_status" in index_names

    def test_downgrade_drops_tables_in_order(self):
        from unittest.mock import call, patch
        mod = _load_migration()

        with patch("alembic.op.drop_table") as mock_dt, \
             patch("alembic.op.drop_column") as mock_dc:
            mod.downgrade()

        dropped_tables = [c[0][0] for c in mock_dt.call_args_list]
        assert dropped_tables == [
            "incident_notes",
            "security_events",
            "stripe_webhook_log",
            "system_metrics_snapshots",
            "admin_audit_log",
        ]

        dropped_cols = [c[0][1] for c in mock_dc.call_args_list]
        assert "admin_role" in dropped_cols
        assert "is_superadmin" in dropped_cols

    def test_admin_audit_log_has_expected_columns(self):
        from unittest.mock import MagicMock, patch
        mod = _load_migration()

        with patch("alembic.op.add_column"), \
             patch("alembic.op.create_table") as mock_ct, \
             patch("alembic.op.create_index"):
            mod.upgrade()

        # Find the admin_audit_log create_table call
        for call_obj in mock_ct.call_args_list:
            if call_obj[0][0] == "admin_audit_log":
                columns = call_obj[0][1:]
                col_names = [c.name for c in columns]
                assert "id" in col_names
                assert "admin_user_id" in col_names
                assert "action" in col_names
                assert "target_type" in col_names
                assert "details_json" in col_names
                assert "ip_address" in col_names
                assert "created_at" in col_names
                break
        else:
            pytest.fail("admin_audit_log table not created")

    def test_security_events_has_severity_column(self):
        from unittest.mock import patch
        mod = _load_migration()

        with patch("alembic.op.add_column"), \
             patch("alembic.op.create_table") as mock_ct, \
             patch("alembic.op.create_index"):
            mod.upgrade()

        for call_obj in mock_ct.call_args_list:
            if call_obj[0][0] == "security_events":
                col_names = [c.name for c in call_obj[0][1:]]
                assert "severity" in col_names
                assert "event_type" in col_names
                assert "user_id" in col_names
                assert "ip_address" in col_names
                break
        else:
            pytest.fail("security_events table not created")

    def test_stripe_webhook_log_has_unique_event_id(self):
        from unittest.mock import patch
        mod = _load_migration()

        with patch("alembic.op.add_column"), \
             patch("alembic.op.create_table") as mock_ct, \
             patch("alembic.op.create_index"):
            mod.upgrade()

        for call_obj in mock_ct.call_args_list:
            if call_obj[0][0] == "stripe_webhook_log":
                for col in call_obj[0][1:]:
                    if col.name == "stripe_event_id":
                        assert col.unique is True
                        break
                else:
                    pytest.fail("stripe_event_id column not found")
                break
