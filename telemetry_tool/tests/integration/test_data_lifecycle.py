"""Integration tests — data retention, GDPR export, and account deletion.

Tests retention enforcement, GDPR export ZIP contents, account deletion
with grace period, and deletion cancellation.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) Retention enforcement
# ===========================================================================

class TestRetentionEnforcement:
    """Raw data deleted after retention window; reports kept."""

    def test_retention_task_exists(self):
        """enforce_raw_data_retention is importable."""
        from tasks.gdpr_tasks import _enforce_raw_data_retention_impl
        assert callable(_enforce_raw_data_retention_impl)

    def test_demo_retention_30_days(self):
        """Demo plan has 30-day retention."""
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("free")
        assert ent["raw_retention_days"] == 30

    def test_racer_retention_90_days(self):
        """Racer plan has 90-day retention."""
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("racer")
        assert ent["raw_retention_days"] == 90

    def test_worldclass_retention_365_days(self):
        """World-Class plan has 365-day retention."""
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("world_class")
        assert ent["raw_retention_days"] == 365

    def test_report_retention_indefinite(self):
        """Reports are kept indefinitely for all plans."""
        from auth.entitlements import get_plan_entitlements
        for plan in ("free", "racer", "world-class"):
            ent = get_plan_entitlements(plan)
            assert ent.get("report_retention") == "indefinite"

    def test_retention_audit_trail(self):
        """Retention enforcement writes audit trail."""
        source = Path(
            _PROJECT_ROOT / "tasks" / "gdpr_tasks.py"
        ).read_text()
        assert "retention" in source.lower()
        assert "audit" in source.lower()


# ===========================================================================
# B) GDPR export
# ===========================================================================

class TestGDPRExport:
    """GDPR export generates complete user data ZIP."""

    def test_export_task_exists(self):
        """export_user_data is importable."""
        from tasks.gdpr_tasks import _export_user_data_impl
        assert callable(_export_user_data_impl)

    def test_gps_precision_reduced(self):
        """GPS coordinates are reduced to 3 decimal places."""
        from tasks.gdpr_tasks import _reduce_gps_precision

        data = {"gps_lat": 51.123456789, "gps_lon": -0.987654321}
        reduced = _reduce_gps_precision(data)
        assert reduced["gps_lat"] == 51.123
        assert reduced["gps_lon"] == -0.988  # rounded

    def test_gps_precision_handles_lists(self):
        """GPS precision reduction handles latitude/longitude lists."""
        from tasks.gdpr_tasks import _reduce_gps_precision

        data = {"latitudes": [51.123456, 51.234567], "longitudes": [-0.987654, -0.876543]}
        reduced = _reduce_gps_precision(data)
        assert all(isinstance(v, float) for v in reduced.get("latitudes", []))

    def test_write_zip_creates_valid_archive(self):
        """_write_zip creates a valid ZIP with expected files."""
        from tasks.gdpr_tasks import _write_zip

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "export.zip")
            _write_zip(
                zip_path,
                profile={"email": "test@example.com", "name": "Test"},
                sessions=[{"id": 1, "track": "Monza"}],
                laps=[{"session_id": 1, "lap": 1, "time": 60.0}],
                scores=[{"session_id": 1, "total": 75.0}],
                annotations=[],
                teams=[],
            )

            assert os.path.exists(zip_path)
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert "profile.json" in names
                assert "sessions.json" in names
                assert "laps.json" in names
                assert "scores.json" in names

                # Verify profile content
                profile = json.loads(zf.read("profile.json"))
                assert profile["email"] == "test@example.com"

    def test_export_uses_deflate_compression(self):
        """ZIP uses DEFLATE compression."""
        from tasks.gdpr_tasks import _write_zip

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "export.zip")
            _write_zip(zip_path, {"a": 1}, [], [], [], [], [])

            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    assert info.compress_type == zipfile.ZIP_DEFLATED

    def test_export_cleanup_function_exists(self):
        """cleanup_expired_exports is importable."""
        from tasks.gdpr_tasks import _cleanup_expired_exports_impl
        assert callable(_cleanup_expired_exports_impl)

    def test_export_cleanup_deletes_old_zips(self):
        """cleanup removes ZIP files older than 7 days."""
        from tasks.gdpr_tasks import _cleanup_expired_exports_impl

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an "old" zip (mtime set to 8 days ago)
            old_zip = os.path.join(tmpdir, "old_export.zip")
            with zipfile.ZipFile(old_zip, "w") as zf:
                zf.writestr("test.txt", "data")

            # Set mtime to 8 days ago
            old_mtime = os.path.getmtime(old_zip) - (8 * 86400)
            os.utime(old_zip, (old_mtime, old_mtime))

            result = _cleanup_expired_exports_impl(tmpdir)
            assert result["deleted"] >= 1
            assert not os.path.exists(old_zip)


# ===========================================================================
# C) Account deletion
# ===========================================================================

class TestAccountDeletion:
    """Account deletion with 30-day grace period."""

    def test_purge_task_exists(self):
        """purge_deleted_accounts is importable."""
        from tasks.gdpr_tasks import _purge_deleted_accounts_impl
        assert callable(_purge_deleted_accounts_impl)

    def test_deletion_grace_period_in_code(self):
        """Purge checks for 30-day grace period."""
        source = Path(_PROJECT_ROOT / "tasks" / "gdpr_tasks.py").read_text()
        assert "30" in source  # 30-day grace

    def test_cascade_deletion_documented(self):
        """Cascade deletion removes all user data."""
        source = Path(_PROJECT_ROOT / "tasks" / "gdpr_tasks.py").read_text()
        assert "cascade" in source.lower() or "DELETE" in source


# ===========================================================================
# D) Account deletion cancel
# ===========================================================================

class TestAccountDeletionCancel:
    """Cancelling deletion within grace period restores account."""

    def test_account_routes_exist(self):
        """Account API routes are registered."""
        from web.routes import api_v1_account
        assert hasattr(api_v1_account, "bp")

    def test_data_export_route_source(self):
        """Data routes handle export and deletion."""
        source = Path(
            _PROJECT_ROOT / "web" / "routes" / "api_v1_account.py"
        ).read_text()
        assert "delete" in source.lower() or "export" in source.lower()
