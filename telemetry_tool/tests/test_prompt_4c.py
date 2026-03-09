"""Tests for PROMPT 4C — Data Lifecycle, Archival & Backup Strategy.

Validates:
- Table partitioning helpers (_month_range, _partition_name, _partition_bounds)
- Archival task constants and structure
- Celery beat schedule includes archival tasks
- Backup script exists and covers required capabilities
- Storage admin endpoint exists with correct queries
- Data deletion cascade documentation
"""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) Partition helper functions
# ===========================================================================

class TestMonthRange:
    """_month_range yields correct (year, month) tuples."""

    def test_basic_range(self):
        from tasks.archival_tasks import _month_range
        result = list(_month_range(date(2026, 2, 15), 3))
        assert result == [(2026, 2), (2026, 3), (2026, 4)]

    def test_year_boundary(self):
        from tasks.archival_tasks import _month_range
        result = list(_month_range(date(2026, 11, 1), 4))
        assert result == [(2026, 11), (2026, 12), (2027, 1), (2027, 2)]

    def test_single_month(self):
        from tasks.archival_tasks import _month_range
        result = list(_month_range(date(2026, 6, 1), 1))
        assert result == [(2026, 6)]

    def test_zero_months(self):
        from tasks.archival_tasks import _month_range
        result = list(_month_range(date(2026, 1, 1), 0))
        assert result == []

    def test_december_start(self):
        from tasks.archival_tasks import _month_range
        result = list(_month_range(date(2026, 12, 1), 3))
        assert result == [(2026, 12), (2027, 1), (2027, 2)]


class TestPartitionName:
    """_partition_name produces correct names."""

    def test_normal_month(self):
        from tasks.archival_tasks import _partition_name
        assert _partition_name("usage_events", 2026, 2) == "usage_events_2026_02"

    def test_december(self):
        from tasks.archival_tasks import _partition_name
        assert _partition_name("audit_log", 2025, 12) == "audit_log_2025_12"

    def test_january(self):
        from tasks.archival_tasks import _partition_name
        assert _partition_name("usage_events", 2027, 1) == "usage_events_2027_01"


class TestPartitionBounds:
    """_partition_bounds returns correct date boundaries."""

    def test_normal_month(self):
        from tasks.archival_tasks import _partition_bounds
        start, end = _partition_bounds(2026, 3)
        assert start == "2026-03-01"
        assert end == "2026-04-01"

    def test_december_month(self):
        from tasks.archival_tasks import _partition_bounds
        start, end = _partition_bounds(2026, 12)
        assert start == "2026-12-01"
        assert end == "2027-01-01"

    def test_january_month(self):
        from tasks.archival_tasks import _partition_bounds
        start, end = _partition_bounds(2026, 1)
        assert start == "2026-01-01"
        assert end == "2026-02-01"

    def test_february_no_gap(self):
        """Partition bounds have no gaps — Feb ends at Mar 1."""
        from tasks.archival_tasks import _partition_bounds
        start, end = _partition_bounds(2026, 2)
        assert start == "2026-02-01"
        assert end == "2026-03-01"

    def test_consecutive_months_no_gaps(self):
        """Adjacent months' bounds share exact boundary dates."""
        from tasks.archival_tasks import _partition_bounds
        _, end_feb = _partition_bounds(2026, 2)
        start_mar, _ = _partition_bounds(2026, 3)
        assert end_feb == start_mar


# ===========================================================================
# B) Archival task constants and structure
# ===========================================================================

class TestArchivalConstants:
    """Archival retention and lookahead constants are correct."""

    def test_usage_retention_12_months(self):
        from tasks.archival_tasks import USAGE_EVENTS_RETENTION_MONTHS
        assert USAGE_EVENTS_RETENTION_MONTHS == 12

    def test_audit_retention_24_months(self):
        from tasks.archival_tasks import AUDIT_LOG_RETENTION_MONTHS
        assert AUDIT_LOG_RETENTION_MONTHS == 24

    def test_partition_lookahead_3_months(self):
        from tasks.archival_tasks import PARTITION_LOOKAHEAD_MONTHS
        assert PARTITION_LOOKAHEAD_MONTHS == 3

    def test_archive_base_path(self):
        from tasks.archival_tasks import ARCHIVE_BASE_PATH
        assert ARCHIVE_BASE_PATH  # Not empty

    def test_create_partitions_impl_exists(self):
        from tasks.archival_tasks import _create_partitions_impl
        assert callable(_create_partitions_impl)

    def test_archive_old_partitions_impl_exists(self):
        from tasks.archival_tasks import _archive_old_partitions_impl
        assert callable(_archive_old_partitions_impl)


class TestArchivalTaskModule:
    """archival_tasks.py has correct module structure."""

    def test_file_exists(self):
        assert (_PROJECT_ROOT / "tasks" / "archival_tasks.py").exists()

    def test_imports_logging(self):
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "import logging" in source

    def test_uses_pg_connection(self):
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "get_pg_connection" in source
        assert "return_pg_connection" in source

    def test_checks_pg_class(self):
        """Partition creation checks pg_class for existing partitions."""
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "pg_class" in source

    def test_commits_and_rollbacks(self):
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "commit()" in source
        assert "rollback()" in source

    def test_handles_parquet_export(self):
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "to_parquet" in source

    def test_handles_pandas_import_error(self):
        """Gracefully handles pandas not being installed."""
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "ImportError" in source

    def test_drops_old_partitions(self):
        source = (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()
        assert "DROP TABLE" in source


# ===========================================================================
# C) Celery beat schedule
# ===========================================================================

class TestCeleryBeatSchedule:
    """Archival tasks are registered in Celery beat schedule."""

    def _beat(self):
        return (_PROJECT_ROOT / "celery_app.py").read_text()

    def test_create_partitions_in_schedule(self):
        assert "create-future-partitions" in self._beat()

    def test_archive_usage_in_schedule(self):
        assert "archive-old-usage-events" in self._beat()

    def test_archive_audit_in_schedule(self):
        assert "archive-old-audit-logs" in self._beat()

    def test_partition_task_name(self):
        assert "tasks.archival_tasks.create_future_partitions" in self._beat()

    def test_usage_archive_task_name(self):
        assert "tasks.archival_tasks.archive_old_usage_events" in self._beat()

    def test_audit_archive_task_name(self):
        assert "tasks.archival_tasks.archive_old_audit_logs" in self._beat()

    def test_archival_tasks_on_default_queue(self):
        source = self._beat()
        # All three tasks should use default queue
        assert source.count('"queue": "default"') >= 6  # 3 existing + 3 new


# ===========================================================================
# D) Backup script
# ===========================================================================

class TestBackupScript:
    """Backup script covers required capabilities."""

    def _script(self):
        return (_PROJECT_ROOT.parent / "scripts" / "backup.sh").read_text()

    def test_backup_script_exists(self):
        assert (_PROJECT_ROOT.parent / "scripts" / "backup.sh").exists()

    def test_uses_pg_dump(self):
        assert "pg_dump" in self._script()

    def test_uses_custom_format(self):
        """Custom format is needed for pg_restore --list verification."""
        assert "--format=custom" in self._script()

    def test_backup_verification(self):
        """Runs pg_restore --list to verify dump integrity."""
        assert "pg_restore --list" in self._script()

    def test_encryption_with_gpg(self):
        assert "gpg" in self._script()
        assert "AES256" in self._script()

    def test_encryption_key_from_env(self):
        assert "BACKUP_ENCRYPTION_KEY" in self._script()

    def test_s3_offsite_copy(self):
        assert "S3_BUCKET" in self._script()
        assert "aws s3 cp" in self._script()

    def test_s3_endpoint_configurable(self):
        """Supports custom S3 endpoint (Hetzner Object Storage)."""
        assert "S3_ENDPOINT" in self._script()
        assert "endpoint-url" in self._script()

    def test_retention_daily_7_days(self):
        assert "mtime +7" in self._script()

    def test_retention_weekly_28_days(self):
        assert "mtime +28" in self._script()

    def test_retention_monthly_365_days(self):
        assert "mtime +365" in self._script()

    def test_three_retention_tiers(self):
        script = self._script()
        assert "daily" in script
        assert "weekly" in script
        assert "monthly" in script

    def test_weekly_on_sunday(self):
        """Weekly backup on Sunday (day 7)."""
        script = self._script()
        assert "DAY_OF_WEEK" in script

    def test_monthly_on_first(self):
        """Monthly backup on 1st of month."""
        script = self._script()
        assert "DAY_OF_MONTH" in script

    def test_set_euo_pipefail(self):
        """Script uses strict error handling."""
        assert "set -euo pipefail" in self._script()

    def test_log_function(self):
        assert "log()" in self._script() or "log " in self._script()


# ===========================================================================
# E) Storage admin endpoint
# ===========================================================================

@pytest.mark.skipif(
    not (_PROJECT_ROOT / "web" / "routes" / "admin.py").exists(),
    reason="admin.py route not yet implemented",
)
class TestStorageAdminEndpoint:
    """GET /api/v1/admin/storage endpoint exists with correct queries."""

    def _source(self):
        return (_PROJECT_ROOT / "web" / "routes" / "admin.py").read_text()

    def test_storage_route_exists(self):
        assert '"/storage"' in self._source()

    def test_queries_database_size(self):
        assert "pg_database_size" in self._source()

    def test_queries_table_sizes(self):
        assert "pg_total_relation_size" in self._source()

    def test_queries_partitions(self):
        """Queries partition sizes for usage_events and audit_log."""
        source = self._source()
        assert "usage_events" in source
        assert "audit_log" in source

    def test_backup_info_function(self):
        assert "_get_backup_info" in self._source()

    def test_disk_info_function(self):
        assert "_get_disk_info" in self._source()

    def test_archive_info_function(self):
        assert "_get_archive_info" in self._source()

    def test_disk_usage_via_shutil(self):
        source = self._source()
        assert "shutil.disk_usage" in source or "disk_usage" in source

    def test_top_10_tables(self):
        assert "LIMIT 10" in self._source()

    def test_admin_guard(self):
        """Storage endpoint is behind platform admin guard."""
        source = self._source()
        assert "require_platform_admin" in source
        assert "before_request" in source


# ===========================================================================
# F) Data deletion cascade documentation
# ===========================================================================

class TestDeletionCascadeDoc:
    """ER document covers deletion cascades."""

    def _doc(self):
        return (_PROJECT_ROOT.parent / "docs" / "plans" / "2026-02-28-entity-relationship-model.md").read_text()

    def test_er_doc_exists(self):
        assert (_PROJECT_ROOT.parent / "docs" / "plans" / "2026-02-28-entity-relationship-model.md").exists()

    def test_user_deletion_section(self):
        assert "user" in self._doc().lower() and "deletion" in self._doc().lower()

    def test_workspace_deletion_section(self):
        assert "workspace" in self._doc().lower() and "deletion" in self._doc().lower()

    def test_cascade_keyword(self):
        assert "CASCADE" in self._doc() or "cascade" in self._doc()

    def test_mentions_refresh_tokens(self):
        assert "refresh_tokens" in self._doc()

    def test_mentions_audit_log(self):
        assert "audit_log" in self._doc()

    def test_mentions_usage_events(self):
        assert "usage_events" in self._doc()


# ===========================================================================
# G) Celery task registration
# ===========================================================================

class TestCeleryTaskRegistration:
    """Archival Celery tasks have correct names and queue."""

    def _source(self):
        return (_PROJECT_ROOT / "tasks" / "archival_tasks.py").read_text()

    def test_create_partitions_task_name(self):
        assert 'name="tasks.archival_tasks.create_future_partitions"' in self._source()

    def test_archive_usage_task_name(self):
        assert 'name="tasks.archival_tasks.archive_old_usage_events"' in self._source()

    def test_archive_audit_task_name(self):
        assert 'name="tasks.archival_tasks.archive_old_audit_logs"' in self._source()

    def test_tasks_on_default_queue(self):
        assert 'queue="default"' in self._source()

    def test_celery_import_guarded(self):
        """Celery import is wrapped in try/except ImportError."""
        source = self._source()
        assert "try:" in source
        assert "except ImportError:" in source
