"""Tests for Beta features: auto-analyze, analysis status tracking, panel state."""
from __future__ import annotations

import json
import zipfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
import hashlib

import pytest

from desktop_sync.queue import SyncQueue
from desktop_sync.worker import SyncWorker


def _make_bundle(tmp_path: Path, name: str = "test") -> tuple[Path, str]:
    zip_path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"schema_version": 2}))
        zf.writestr("telemetry.ibt", b"x" * 16)
    checksum = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return zip_path, checksum


class _Upload201ThenAnalyze202(BaseHTTPRequestHandler):
    """Mock: 201 on upload, 202 on analyze."""
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        if "/analyze" in self.path:
            body = json.dumps({"ok": True, "data": {"run_id": "run_1", "status": "queued"}}).encode()
            self.send_response(202)
        else:
            body = json.dumps({"ok": True, "data": {"bundle_id": "bun_1", "status": "accepted"}}).encode()
            self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Upload201AnalyzeConflict(BaseHTTPRequestHandler):
    """Mock: 201 on upload, 409 CONFLICT on analyze."""
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        if "/analyze" in self.path:
            body = json.dumps({"ok": False, "error": {"code": "CONFLICT", "message": "in flight"}}).encode()
            self.send_response(409)
        else:
            body = json.dumps({"ok": True, "data": {"bundle_id": "bun_2", "status": "accepted"}}).encode()
            self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def queue():
    q = SyncQueue()
    yield q
    q.close()


class TestAutoAnalyze:
    def test_auto_analyze_triggers_after_upload(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        qid = queue.enqueue(bundle_path=str(bundle_path), checksum=checksum)

        server = HTTPServer(("127.0.0.1", 0), _Upload201ThenAnalyze202)
        port = server.server_address[1]
        # Need to handle TWO requests (upload + analyze)
        t = Thread(target=lambda: (server.handle_request(), server.handle_request()), daemon=True)
        t.start()

        worker = SyncWorker(
            queue=queue, api_url=f"http://127.0.0.1:{port}",
            auto_analyze=True,
        )
        worker.drain_once()
        t.join(timeout=10)
        server.server_close()

        entry = queue.get(qid)
        assert entry.status == "uploaded"
        assert entry.cloud_bundle_id == "bun_1"
        # Analysis was triggered
        assert entry.analysis_status in ("queued", "running")

    def test_no_auto_analyze_when_disabled(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        qid = queue.enqueue(bundle_path=str(bundle_path), checksum=checksum)

        server = HTTPServer(("127.0.0.1", 0), _Upload201ThenAnalyze202)
        port = server.server_address[1]
        t = Thread(target=server.handle_request, daemon=True)
        t.start()

        worker = SyncWorker(
            queue=queue, api_url=f"http://127.0.0.1:{port}",
            auto_analyze=False,   # Racer mode
        )
        worker.drain_once()
        t.join(timeout=5)
        server.server_close()

        entry = queue.get(qid)
        assert entry.status == "uploaded"
        assert entry.analysis_status is None   # not triggered

    def test_analyze_conflict_treated_as_running(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        qid = queue.enqueue(bundle_path=str(bundle_path), checksum=checksum)

        server = HTTPServer(("127.0.0.1", 0), _Upload201AnalyzeConflict)
        port = server.server_address[1]
        t = Thread(target=lambda: (server.handle_request(), server.handle_request()), daemon=True)
        t.start()

        worker = SyncWorker(
            queue=queue, api_url=f"http://127.0.0.1:{port}",
            auto_analyze=True,
        )
        worker.drain_once()
        t.join(timeout=10)
        server.server_close()

        entry = queue.get(qid)
        assert entry.status == "uploaded"
        assert entry.analysis_status == "running"   # 409 = already analyzing


class TestAnalysisStatusTracking:
    def test_update_analysis_status(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64)
        queue.update_analysis_status(qid, "succeeded", "A")
        entry = queue.get(qid)
        assert entry.analysis_status == "succeeded"
        assert entry.analysis_tier == "A"

    def test_update_session_metadata(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64)
        queue.update_session_metadata(qid, "Daytona", "MX-5")
        entry = queue.get(qid)
        assert entry.track_name == "Daytona"
        assert entry.vehicle_name == "MX-5"


class TestCombinedStatus:
    def test_uploaded_no_analysis(self):
        from desktop_sync.ui_sync_panel import _combined_status, _STATUS_DISPLAY
        from desktop_sync.queue import SyncQueueEntry
        entry = SyncQueueEntry(
            queue_id="x", bundle_path="", checksum_sha256="", status="uploaded",
            attempt_count=0, max_attempts=5, last_attempt_at=None,
            next_retry_at=None, error_message=None, cloud_bundle_id="bun",
            created_at="", uploaded_at="", analysis_status=None,
        )
        label, color = _combined_status(entry)
        assert label == "Uploaded"

    def test_uploaded_with_analysis_succeeded_tier_a(self):
        from desktop_sync.ui_sync_panel import _combined_status
        from desktop_sync.queue import SyncQueueEntry
        entry = SyncQueueEntry(
            queue_id="x", bundle_path="", checksum_sha256="", status="uploaded",
            attempt_count=0, max_attempts=5, last_attempt_at=None,
            next_retry_at=None, error_message=None, cloud_bundle_id="bun",
            created_at="", uploaded_at="", analysis_status="succeeded",
            analysis_tier="A",
        )
        label, color = _combined_status(entry)
        assert "Full" in label
        assert color == "#22C55E"

    def test_skipped_shows_local_only(self):
        from desktop_sync.ui_sync_panel import _combined_status
        from desktop_sync.queue import SyncQueueEntry
        entry = SyncQueueEntry(
            queue_id="x", bundle_path="", checksum_sha256="", status="skipped",
            attempt_count=0, max_attempts=5, last_attempt_at=None,
            next_retry_at=None, error_message=None, cloud_bundle_id=None,
            created_at="", uploaded_at=None, analysis_status=None,
        )
        label, color = _combined_status(entry)
        assert label == "Local Only"
