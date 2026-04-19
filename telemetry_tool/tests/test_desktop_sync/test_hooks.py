"""Integration tests for the post-finalize hooks.

Verifies that on_session_finalized and on_ibt_captured produce bundles
and enqueue them correctly — without touching the network.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from desktop_sync.entitlements import SyncPolicy
from desktop_sync.hooks import on_session_finalized, on_ibt_captured
from desktop_sync.queue import SyncQueue

# Racer policy: can_upload=True, auto_upload=False
_RACER_POLICY = SyncPolicy(can_upload=True, auto_upload=False, auto_analyze=False,
                            max_uploads_month=10, plan_tier="racer")
_WC_POLICY = SyncPolicy(can_upload=True, auto_upload=True, auto_analyze=True,
                          max_uploads_month=-1, plan_tier="world_class")
_FREE_POLICY = SyncPolicy.free_default()


@pytest.fixture(autouse=True)
def _reset_hooks_state():
    """Reset the module-level singletons between tests."""
    import desktop_sync.hooks as h
    h._WORKER = None
    h._QUEUE = None
    yield
    if h._WORKER is not None:
        h._WORKER.stop(timeout=1)
        h._WORKER = None
    if h._QUEUE is not None:
        h._QUEUE.close()
        h._QUEUE = None


@pytest.fixture
def ibt_file(tmp_path):
    ibt = tmp_path / "session.ibt"
    ibt.write_bytes(b"FAKE_IBT" * 100)
    return ibt


class TestOnSessionFinalized:
    def test_ibt_session_creates_bundle_and_enqueues(self, tmp_path, ibt_file):
        results = [{
            "steps_ok": ["s1"],
            "steps_failed": [],
            "output_dir": str(tmp_path / "output"),
            "track_id": "Daytona",
        }]
        session_info = {"car_name": "MX-5", "session_type": "practice"}

        queue = SyncQueue()
        with patch("desktop_sync.hooks._get_queue", return_value=queue), \
             patch("desktop_sync.hooks._get_sync_policy", return_value=_RACER_POLICY), \
             patch("desktop_sync.hooks._get_config") as mock_cfg:
            cfg = mock_cfg.return_value
            cfg.max_upload_attempts = 5

            on_session_finalized(results, ibt_file, session_info)

        entries = queue.list_all()
        assert len(entries) == 1
        assert entries[0].status == "skipped"   # racer = auto_upload=false
        assert Path(entries[0].bundle_path).suffix == ".zip"
        queue.close()

    def test_csv_session_is_skipped(self, tmp_path):
        csv = tmp_path / "session.csv"
        csv.write_text("fake,csv")
        results = [{"steps_ok": ["s1"], "steps_failed": [], "output_dir": str(tmp_path)}]

        queue = SyncQueue()
        with patch("desktop_sync.hooks._get_queue", return_value=queue), \
             patch("desktop_sync.hooks._get_config") as mock_cfg:
            cfg = mock_cfg.return_value
            cfg.auto_upload = True

            on_session_finalized(results, csv, {})

        # CSV sessions don't produce bundles
        assert len(queue.list_all()) == 0
        queue.close()

    def test_pipeline_crash_does_not_raise(self, tmp_path, ibt_file):
        results = [{
            "steps_ok": [],
            "steps_failed": ["pipeline_crash"],
            "errors": {"pipeline_crash": "boom"},
            "output_dir": str(tmp_path),
        }]

        queue = SyncQueue()
        with patch("desktop_sync.hooks._get_queue", return_value=queue), \
             patch("desktop_sync.hooks._get_sync_policy", return_value=_RACER_POLICY), \
             patch("desktop_sync.hooks._get_config") as mock_cfg:
            cfg = mock_cfg.return_value
            cfg.max_upload_attempts = 5

            # Should not raise even with a crashed pipeline.
            on_session_finalized(results, ibt_file, {})

        # Still enqueues (partial results are still sync-worthy)
        assert len(queue.list_all()) == 1
        queue.close()

    def test_empty_results_produces_nothing(self):
        queue = SyncQueue()
        with patch("desktop_sync.hooks._get_queue", return_value=queue):
            on_session_finalized([], Path("/fake.ibt"), {})
        assert len(queue.list_all()) == 0
        queue.close()


class TestOnIbtCaptured:
    def test_creates_bundle_and_enqueues(self, tmp_path, ibt_file):
        meta = {
            "track_name": "Spa",
            "car_name": "BMW M2",
            "collected_at": "2026-04-16T10:00:00Z",
            "source": "replay_ibt_capture",
        }

        queue = SyncQueue()
        with patch("desktop_sync.hooks._get_queue", return_value=queue), \
             patch("desktop_sync.hooks._get_sync_policy", return_value=_WC_POLICY), \
             patch("desktop_sync.hooks._get_config") as mock_cfg:
            cfg = mock_cfg.return_value
            cfg.max_upload_attempts = 5
            cfg.cloud_api_url = ""   # prevent worker start

            on_ibt_captured(ibt_file, meta, tmp_path)

        entries = queue.list_all()
        assert len(entries) == 1
        assert entries[0].status == "pending"   # world_class = auto_upload=true
        assert "spa_bmw_m2.zip" in entries[0].bundle_path
        queue.close()
