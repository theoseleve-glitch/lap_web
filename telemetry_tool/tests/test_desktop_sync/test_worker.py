"""Tests for SyncWorker — upload logic with mocked HTTP."""
from __future__ import annotations

import json
import zipfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest

from desktop_sync.queue import SyncQueue
from desktop_sync.worker import SyncWorker


def _make_bundle(tmp_path: Path, name: str = "test") -> tuple[Path, str]:
    """Build a minimal zip that the worker can upload."""
    import hashlib
    zip_path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"schema_version": 2}))
        zf.writestr("telemetry.ibt", b"x" * 16)
    checksum = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return zip_path, checksum


class _MockBundleHandler(BaseHTTPRequestHandler):
    """Fake webapp that returns 201 for uploads."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        body = json.dumps({
            "ok": True,
            "data": {"bundle_id": "mock-bundle-id", "status": "accepted"},
        }).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass   # suppress request logging in tests


class _MockDuplicateHandler(BaseHTTPRequestHandler):
    """Returns 409 BUNDLE_DUPLICATE."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        body = json.dumps({
            "ok": False,
            "error": {
                "code": "BUNDLE_DUPLICATE",
                "message": "already uploaded",
                "details": [{"existing_bundle_id": "existing-id"}],
            },
        }).encode()
        self.send_response(409)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def queue():
    q = SyncQueue()
    yield q
    q.close()


class TestDrainOnce:
    def test_uploads_pending_entry(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        qid = queue.enqueue(bundle_path=str(bundle_path), checksum=checksum)

        server = HTTPServer(("127.0.0.1", 0), _MockBundleHandler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request, daemon=True)
        t.start()

        worker = SyncWorker(queue=queue, api_url=f"http://127.0.0.1:{port}")
        count = worker.drain_once()
        t.join(timeout=5)
        server.server_close()

        assert count == 1
        entry = queue.get(qid)
        assert entry.status == "uploaded"
        assert entry.cloud_bundle_id == "mock-bundle-id"

    def test_duplicate_treated_as_uploaded(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        qid = queue.enqueue(bundle_path=str(bundle_path), checksum=checksum)

        server = HTTPServer(("127.0.0.1", 0), _MockDuplicateHandler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request, daemon=True)
        t.start()

        worker = SyncWorker(queue=queue, api_url=f"http://127.0.0.1:{port}")
        count = worker.drain_once()
        t.join(timeout=5)
        server.server_close()

        assert count == 1
        entry = queue.get(qid)
        assert entry.status == "uploaded"
        assert entry.cloud_bundle_id == "existing-id"

    def test_missing_bundle_marks_failed(self, queue):
        qid = queue.enqueue(bundle_path="/nonexistent.zip", checksum="a" * 64)
        worker = SyncWorker(queue=queue, api_url="http://localhost:9999")
        count = worker.drain_once()
        assert count == 0
        assert queue.get(qid).status == "failed"
        assert "missing" in queue.get(qid).error_message

    def test_skipped_entries_not_picked_up(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        queue.enqueue(bundle_path=str(bundle_path), checksum=checksum, auto_upload=False)
        worker = SyncWorker(queue=queue, api_url="http://localhost:9999")
        count = worker.drain_once()
        assert count == 0

    def test_network_error_increments_attempt(self, tmp_path, queue):
        bundle_path, checksum = _make_bundle(tmp_path)
        qid = queue.enqueue(bundle_path=str(bundle_path), checksum=checksum)
        # No server running → connection refused
        worker = SyncWorker(queue=queue, api_url="http://127.0.0.1:1")
        count = worker.drain_once()
        assert count == 0
        entry = queue.get(qid)
        assert entry.attempt_count == 1
        assert "network" in entry.error_message.lower() or "refused" in entry.error_message.lower()
