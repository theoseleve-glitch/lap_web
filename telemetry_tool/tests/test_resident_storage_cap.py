"""Tests for the hard resident-storage cap enforced at upload time.

Distinct from the existing monthly upload-VOLUME flow limit
(upload_volume_mb_per_month, checked via check_and_record_quota) -- this
caps TOTAL resident storage regardless of when it accumulated.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# _check_tier_limits reads `g.current_user_id` (Flask request-global) for the
# monthly-volume check. These storage-cap tests run outside a request context,
# so patch g to a stand-in whose current_user_id is None -> the volume block
# (covered by its own tests) is skipped, isolating the storage-cap logic.
_NO_USER_G = SimpleNamespace(current_user_id=None)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.entitlements import PLAN_ENTITLEMENTS
from web.routes.sessions_v2 import _check_tier_limits


class TestPlanEntitlementsStorageCap:
    def test_locked_tier_has_zero_cap(self):
        assert PLAN_ENTITLEMENTS["locked"]["resident_storage_cap_gb"] == 0

    def test_racer_tier_has_a_finite_cap(self):
        cap = PLAN_ENTITLEMENTS["racer"]["resident_storage_cap_gb"]
        assert cap > 0

    def test_world_class_tier_is_unlimited(self):
        assert PLAN_ENTITLEMENTS["world_class"]["resident_storage_cap_gb"] == -1


class TestCheckTierLimitsStorageCap:
    def _make_file(self, size_bytes: int) -> io.BytesIO:
        return io.BytesIO(b"x" * size_bytes)

    def test_rejects_upload_that_would_exceed_resident_cap(self):
        f = self._make_file(10 * 1024 * 1024)  # 10 MB
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        with (
            patch("web.routes.sessions_v2.get_storage") as mock_get_storage,
            patch("auth.entitlements.check_and_record_quota", return_value=(True, {})),
            patch.dict(
                "auth.entitlements.PLAN_ENTITLEMENTS",
                {"racer": {**PLAN_ENTITLEMENTS["racer"], "resident_storage_cap_gb": 1}},
            ),
        ):
            # racer's cap patched to 1 GB (1024 MiB); already at 1020 MiB used,
            # so a 10 MiB upload (1030 MiB total) tips over the cap.
            mock_get_storage.return_value = {"used_bytes": 1020 * 1024 * 1024}
            error = _check_tier_limits(f, conn, "9", "racer")
        assert error is not None
        assert "storage" in error.lower()

    def test_allows_upload_within_resident_cap(self):
        f = self._make_file(1 * 1024 * 1024)  # 1 MB
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        with (
            patch("web.routes.sessions_v2.get_storage", return_value={"used_bytes": 10 * 1024 * 1024}),
            patch("auth.entitlements.check_and_record_quota", return_value=(True, {})),
            patch("web.routes.sessions_v2.g", _NO_USER_G),
        ):
            error = _check_tier_limits(f, conn, "9", "racer")
        assert error is None

    def test_unlimited_tier_skips_the_cap_check_entirely(self):
        f = self._make_file(500 * 1024 * 1024)
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        with (
            patch("web.routes.sessions_v2.get_storage") as mock_get_storage,
            patch("auth.entitlements.check_and_record_quota", return_value=(True, {})),
            patch("web.routes.sessions_v2.g", _NO_USER_G),
        ):
            error = _check_tier_limits(f, conn, "9", "world_class")
        assert error is None
        mock_get_storage.assert_not_called()
