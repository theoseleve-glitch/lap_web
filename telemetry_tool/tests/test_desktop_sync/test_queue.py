"""Tests for SyncQueue."""
from __future__ import annotations

import pytest

from desktop_sync.queue import SyncQueue


@pytest.fixture
def queue():
    q = SyncQueue()  # in-memory sqlite
    yield q
    q.close()


class TestEnqueue:
    def test_auto_upload_true_sets_pending(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, auto_upload=True)
        entry = queue.get(qid)
        assert entry.status == "pending"

    def test_auto_upload_false_sets_skipped(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, auto_upload=False)
        entry = queue.get(qid)
        assert entry.status == "skipped"


class TestStatusTransitions:
    def test_uploading_transition(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64)
        queue.mark_uploading(qid)
        assert queue.get(qid).status == "uploading"

    def test_uploaded_transition(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64)
        queue.mark_uploaded(qid, "cloud-id-123")
        entry = queue.get(qid)
        assert entry.status == "uploaded"
        assert entry.cloud_bundle_id == "cloud-id-123"
        assert entry.uploaded_at is not None

    def test_failed_with_retry(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, max_attempts=3)
        queue.mark_failed(qid, "timeout", next_retry_at="2099-01-01T00:00:00Z")
        entry = queue.get(qid)
        assert entry.status == "pending"   # still retryable (attempt 1 < max 3)
        assert entry.attempt_count == 1
        assert entry.error_message == "timeout"

    def test_failed_exhausted(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, max_attempts=1)
        queue.mark_failed(qid, "timeout")
        entry = queue.get(qid)
        assert entry.status == "failed"    # attempt 1 >= max 1


class TestPromote:
    def test_promote_skipped_to_pending(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, auto_upload=False)
        queue.promote_skipped(qid)
        assert queue.get(qid).status == "pending"

    def test_promote_all_skipped(self, queue):
        queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, auto_upload=False)
        queue.enqueue(bundle_path="/b.zip", checksum="b" * 64, auto_upload=False)
        count = queue.promote_all_skipped()
        assert count == 2
        for e in queue.list_all():
            assert e.status == "pending"

    def test_retry_failed(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, max_attempts=1)
        queue.mark_failed(qid, "error")
        assert queue.get(qid).status == "failed"
        count = queue.retry_failed()
        assert count == 1
        assert queue.get(qid).status == "pending"
        assert queue.get(qid).attempt_count == 0


class TestGetPending:
    def test_returns_only_eligible(self, queue):
        queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, auto_upload=True)
        queue.enqueue(bundle_path="/b.zip", checksum="b" * 64, auto_upload=False)
        pending = queue.get_pending()
        assert len(pending) == 1
        assert pending[0].bundle_path == "/a.zip"

    def test_respects_next_retry_at(self, queue):
        qid = queue.enqueue(bundle_path="/a.zip", checksum="a" * 64)
        queue.mark_failed(qid, "err", next_retry_at="2099-12-31T23:59:59Z")
        # Future retry time → not yet eligible
        pending = queue.get_pending()
        assert len(pending) == 0


class TestCountByStatus:
    def test_counts(self, queue):
        queue.enqueue(bundle_path="/a.zip", checksum="a" * 64, auto_upload=True)
        queue.enqueue(bundle_path="/b.zip", checksum="b" * 64, auto_upload=False)
        counts = queue.count_by_status()
        assert counts.get("pending") == 1
        assert counts.get("skipped") == 1
