"""Tests for tasks/onboarding_tasks.py (Task 10): draft_and_notify.

Everything external is mocked: ``onboarding_tasks.repo``, the drafting
functions (``validate_bbox``/``sam2_draft``/``gps_only_draft``/``save_draft``),
``onboarding_tasks.tokens``, and ``onboarding_tasks.send_email_async``. Tests
call ``_run_draft_and_notify(request_id, conn)`` directly -- the plain,
Celery-free helper -- with a bare ``MagicMock()`` connection, since every
call that would use it (``repo.claim_for_drafting`` etc.) is itself mocked.

Covers the two idempotency guards described in the module docstring:
  1. ``claim_for_drafting`` returning False is a hard early-return (no
     draft/save/mint/email work at all).
  2. The ``emailed_at IS NULL`` re-check right before sending gates the
     email so it is sent at most once.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from onboarding.draft import DraftError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tasks.onboarding_tasks as onboarding_tasks  # noqa: E402

_REQUEST_ID = "req-abc123"


def _row(**overrides) -> dict:
    base = dict(
        id=_REQUEST_ID,
        track_key="T1_solokart",
        track_label="Solokart FP",
        fingerprint={"n_sessions": 1},
        draft_centerline=[[5.0, 45.0], [5.001, 45.0], [5.001, 45.001]],
        status="drafting",
        bbox={"min_lat": 45.0, "max_lat": 45.01, "min_lon": 5.0, "max_lon": 5.01},
        token_jti=None,
        emailed_at=None,
    )
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ANNOTATOR_HOST", "https://annotator.example.com")
    monkeypatch.setenv("ONBOARDING_OPERATOR_EMAIL", "ops@example.com")


@pytest.fixture
def _mock_repo(monkeypatch):
    fake = MagicMock(name="repo")
    fake.claim_for_drafting.return_value = True
    fake.set_status.return_value = True
    monkeypatch.setattr(onboarding_tasks, "repo", fake)
    return fake


@pytest.fixture
def _mock_tokens(monkeypatch):
    fake = MagicMock(name="tokens")
    fake.mint.return_value = ("raw-token-xyz", "jti-1")
    monkeypatch.setattr(onboarding_tasks, "tokens", fake)
    return fake


@pytest.fixture
def _mock_validate_bbox(monkeypatch):
    fake = MagicMock(name="validate_bbox", return_value=None)
    monkeypatch.setattr(onboarding_tasks, "validate_bbox", fake)
    return fake


@pytest.fixture
def _mock_sam2_draft(monkeypatch):
    fake = MagicMock(name="sam2_draft")
    monkeypatch.setattr(onboarding_tasks, "sam2_draft", fake)
    return fake


@pytest.fixture
def _mock_gps_only_draft(monkeypatch):
    fake = MagicMock(name="gps_only_draft", return_value={"type": "FeatureCollection"})
    monkeypatch.setattr(onboarding_tasks, "gps_only_draft", fake)
    return fake


@pytest.fixture
def _mock_save_draft(monkeypatch):
    fake = MagicMock(name="save_draft", return_value="/tmp/onboarding_drafts/req-abc123.geojson")
    monkeypatch.setattr(onboarding_tasks, "save_draft", fake)
    return fake


@pytest.fixture
def _mock_send_email(monkeypatch):
    fake = MagicMock(name="send_email_async")
    monkeypatch.setattr(onboarding_tasks, "send_email_async", fake)
    return fake


@pytest.fixture
def conn():
    return MagicMock(name="conn")


class TestCenterlineFromRow:
    def test_reads_draft_centerline_column(self):
        row = _row(draft_centerline=[[1.0, 2.0], [1.1, 2.1]])
        assert onboarding_tasks._centerline_from_row(row) == [[1.0, 2.0], [1.1, 2.1]]

    def test_missing_draft_centerline_returns_empty_list_no_crash(self):
        row = _row(draft_centerline=None)
        assert onboarding_tasks._centerline_from_row(row) == []

    def test_absent_key_returns_empty_list_no_crash(self):
        row = _row()
        del row["draft_centerline"]
        assert onboarding_tasks._centerline_from_row(row) == []


class TestClaimGate:
    def test_claim_false_returns_early_no_side_effects(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        _mock_repo.claim_for_drafting.return_value = False

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": True, "skipped": "already_claimed"}
        _mock_repo.get.assert_not_called()
        _mock_validate_bbox.assert_not_called()
        _mock_sam2_draft.assert_not_called()
        _mock_gps_only_draft.assert_not_called()
        _mock_save_draft.assert_not_called()
        _mock_tokens.mint.assert_not_called()
        _mock_send_email.delay.assert_not_called()
        _mock_repo.set_status.assert_not_called()


class TestHappyPathSam2:
    def test_sam2_draft_drafted_and_emailed_once(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        row_after_claim = _row()
        row_before_email = _row(token_jti="jti-1", emailed_at=None)
        _mock_repo.get.side_effect = [row_after_claim, row_before_email]
        _mock_sam2_draft.return_value = {"type": "FeatureCollection", "features": []}

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": True, "status": "drafted"}
        _mock_validate_bbox.assert_called_once_with(row_after_claim["bbox"])
        _mock_gps_only_draft.assert_not_called()
        _mock_save_draft.assert_called_once_with(
            _REQUEST_ID, {"type": "FeatureCollection", "features": []}
        )
        _mock_tokens.mint.assert_called_once_with(_REQUEST_ID)

        # drafted status write
        drafted_call = _mock_repo.set_status.call_args_list[0]
        assert drafted_call.args[:3] == (conn, _REQUEST_ID, "drafted")
        assert drafted_call.kwargs["draft_path"] == "/tmp/onboarding_drafts/req-abc123.geojson"
        assert drafted_call.kwargs["draft_status"] == "sam2"

        # token_jti write
        token_call = _mock_repo.set_status.call_args_list[1]
        assert token_call.args[:3] == (conn, _REQUEST_ID, "drafted")
        assert token_call.kwargs["token_jti"] == "jti-1"

        # email sent exactly once, url has the fragment token
        _mock_send_email.delay.assert_called_once()
        args = _mock_send_email.delay.call_args.args
        assert args[0] == "onboarding_task"
        assert args[1] == "ops@example.com"
        variables = args[2]
        assert variables["track_label"] == "Solokart FP"
        assert variables["track_key"] == "T1_solokart"
        assert "#token=raw-token-xyz" in variables["annotator_url"]
        assert "?req=req-abc123" in variables["annotator_url"]
        assert "raw-token-xyz" not in variables["annotator_url"].split("#")[0]

        # final emailed status write
        emailed_call = _mock_repo.set_status.call_args_list[2]
        assert emailed_call.args[:3] == (conn, _REQUEST_ID, "emailed")
        assert emailed_call.kwargs["emailed_at"] is not None


class TestSam2NoneGpsFallback:
    def test_sam2_none_falls_back_to_gps_only(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        _mock_repo.get.side_effect = [_row(), _row(emailed_at=None)]
        _mock_sam2_draft.return_value = None

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": True, "status": "drafted_gps_only"}
        _mock_gps_only_draft.assert_called_once()
        drafted_call = _mock_repo.set_status.call_args_list[0]
        assert drafted_call.args[:3] == (conn, _REQUEST_ID, "drafted_gps_only")
        assert drafted_call.kwargs["draft_status"] == "gps_only"
        _mock_send_email.delay.assert_called_once()


class TestInvalidBbox:
    def test_validate_bbox_raises_marks_draft_failed_no_draft_no_email(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        _mock_repo.get.return_value = _row(bbox={"min_lat": 999})
        _mock_validate_bbox.side_effect = DraftError("bbox missing required key(s)")

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": False, "error": "invalid_bbox"}
        _mock_repo.set_status.assert_called_once()
        call = _mock_repo.set_status.call_args
        assert call.args[:3] == (conn, _REQUEST_ID, "draft_failed")
        assert "bbox missing required key(s)" in call.kwargs["error"]

        _mock_sam2_draft.assert_not_called()
        _mock_gps_only_draft.assert_not_called()
        _mock_save_draft.assert_not_called()
        _mock_tokens.mint.assert_not_called()
        _mock_send_email.delay.assert_not_called()


class TestUnexpectedDraftingFailure:
    def test_drafting_raises_marks_draft_failed_and_does_not_propagate(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        _mock_repo.get.return_value = _row()
        _mock_sam2_draft.side_effect = RuntimeError("trackreco blew up")

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": False, "error": "draft_failed"}
        _mock_repo.set_status.assert_called_once()
        call = _mock_repo.set_status.call_args
        assert call.args[:3] == (conn, _REQUEST_ID, "draft_failed")
        assert "trackreco blew up" in call.kwargs["error"]

        _mock_save_draft.assert_not_called()
        _mock_tokens.mint.assert_not_called()
        _mock_send_email.delay.assert_not_called()


class TestMissingRequiredEnvAtEmailTimeMarksDraftFailed:
    """M2: a missing ANNOTATOR_HOST/ONBOARDING_OPERATOR_EMAIL at the point
    the email is built must NOT raise (KeyError) into Celery -- it must
    transition the request to draft_failed and return cleanly instead."""

    def test_missing_operator_email_marks_draft_failed_no_send(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn, monkeypatch,
    ):
        monkeypatch.delenv("ONBOARDING_OPERATOR_EMAIL", raising=False)
        row_after_claim = _row()
        row_before_email = _row(token_jti="jti-1", emailed_at=None)
        _mock_repo.get.side_effect = [row_after_claim, row_before_email]
        _mock_sam2_draft.return_value = {"type": "FeatureCollection"}

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": False, "error": "missing_env"}
        _mock_send_email.delay.assert_not_called()
        statuses = [c.args[2] for c in _mock_repo.set_status.call_args_list]
        assert statuses[-1] == "draft_failed"

    def test_missing_annotator_host_marks_draft_failed_no_send(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn, monkeypatch,
    ):
        monkeypatch.delenv("ANNOTATOR_HOST", raising=False)
        row_after_claim = _row()
        row_before_email = _row(token_jti="jti-1", emailed_at=None)
        _mock_repo.get.side_effect = [row_after_claim, row_before_email]
        _mock_sam2_draft.return_value = {"type": "FeatureCollection"}

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": False, "error": "missing_env"}
        _mock_send_email.delay.assert_not_called()
        statuses = [c.args[2] for c in _mock_repo.set_status.call_args_list]
        assert statuses[-1] == "draft_failed"


class TestRealSam2PreflightFailureFallsBackToRealGpsOnlyDraft:
    """Closer-to-real check of the SAM2-in-prod gap this ticket closes:
    with the trackreco env vars unset (the default -- no torch/SAM2 in this
    worker), the REAL sam2_draft (not mocked) must fail its preflight and
    return None, and the REAL gps_only_draft (not mocked either) must then
    produce a usable draft -- the whole task completing without raising."""

    def test_unset_trackreco_env_falls_back_to_real_gps_only_draft(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_save_draft,
        _mock_send_email, conn, monkeypatch,
    ):
        monkeypatch.delenv("ONBOARDING_TRACKRECO_DIR", raising=False)
        monkeypatch.delenv("ONBOARDING_TRACKRECO_PYTHON", raising=False)

        # A closed-enough oval centerline so the real gps_only_draft succeeds.
        import math
        lat0, lon0 = 45.0, 5.0
        mx = math.cos(math.radians(lat0)) * 111_320.0
        my = 110_540.0
        centerline = []
        for k in range(30):
            t = 2.0 * math.pi * k / 30
            x, y = 60.0 * math.cos(t), 35.0 * math.sin(t)
            centerline.append([lon0 + x / mx, lat0 + y / my])

        row_after_claim = _row(draft_centerline=centerline)
        row_before_email = _row(draft_centerline=centerline, token_jti="jti-1", emailed_at=None)
        _mock_repo.get.side_effect = [row_after_claim, row_before_email]

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": True, "status": "drafted_gps_only"}
        drafted_call = _mock_repo.set_status.call_args_list[0]
        assert drafted_call.args[:3] == (conn, _REQUEST_ID, "drafted_gps_only")
        assert drafted_call.kwargs["draft_status"] == "gps_only"
        saved_geojson = _mock_save_draft.call_args.args[1]
        assert saved_geojson["properties"]["review_source"] == "gps_only_draft"
        _mock_send_email.delay.assert_called_once()


class TestSoftTimeLimitFallsBackToGpsOnly:
    """HIGH fix coverage: a SoftTimeLimitExceeded raised while attempting the
    SAM2 draft must be treated exactly like a plain ``None`` return from
    sam2_draft -- fall back to gps_only_draft -- NOT the generic
    draft_failed path a bare Exception gets (see TestUnexpectedDraftingFailure
    above, which must keep failing closed for every OTHER exception type)."""

    def test_soft_time_limit_during_sam2_falls_back_to_gps_only(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        row_after_claim = _row()
        row_before_email = _row(token_jti="jti-1", emailed_at=None)
        _mock_repo.get.side_effect = [row_after_claim, row_before_email]
        _mock_sam2_draft.side_effect = SoftTimeLimitExceeded()

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": True, "status": "drafted_gps_only"}
        _mock_gps_only_draft.assert_called_once()
        drafted_call = _mock_repo.set_status.call_args_list[0]
        assert drafted_call.args[:3] == (conn, _REQUEST_ID, "drafted_gps_only")
        assert drafted_call.kwargs["draft_status"] == "gps_only"
        _mock_send_email.delay.assert_called_once()

        # Must NOT be treated as a draft_failed -- no such status write.
        statuses = [c.args[2] for c in _mock_repo.set_status.call_args_list]
        assert "draft_failed" not in statuses


class TestMintFailureMarksDraftFailed:
    """M2: tokens.mint raising TokenError (e.g. unset ONBOARDING_TOKEN_SECRET)
    must not raise into Celery either -- same draft_failed treatment."""

    def test_missing_token_secret_marks_draft_failed_no_email(
        self, _mock_repo, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn, monkeypatch,
    ):
        # Deliberately NOT using the _mock_tokens fixture -- exercise the
        # real onboarding.tokens.mint so a real TokenError is raised.
        monkeypatch.delenv("ONBOARDING_TOKEN_SECRET", raising=False)
        _mock_repo.get.return_value = _row()
        _mock_sam2_draft.return_value = {"type": "FeatureCollection"}

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": False, "error": "mint_failed"}
        _mock_send_email.delay.assert_not_called()
        statuses = [c.args[2] for c in _mock_repo.set_status.call_args_list]
        assert statuses[-1] == "draft_failed"


class TestEmailedOnceGuard:
    def test_already_emailed_row_is_not_resent(
        self, _mock_repo, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn,
    ):
        # First get() (right after claim) is irrelevant to the email gate;
        # the SECOND get() (right before sending) is what must be honored --
        # simulate it already carrying emailed_at (e.g. a prior run of this
        # same request already completed the email step).
        row_after_claim = _row()
        row_before_email = _row(token_jti="jti-1", emailed_at="2026-07-05T00:00:00Z")
        _mock_repo.get.side_effect = [row_after_claim, row_before_email]
        _mock_sam2_draft.return_value = {"type": "FeatureCollection"}

        result = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)

        assert result == {"ok": True, "status": "drafted"}
        _mock_send_email.delay.assert_not_called()
        # No "emailed" status transition either -- only the drafted + token_jti writes.
        statuses = [c.args[2] for c in _mock_repo.set_status.call_args_list]
        assert "emailed" not in statuses

    def test_run_twice_with_stateful_fake_repo_sends_once(
        self, _mock_tokens, _mock_validate_bbox, _mock_sam2_draft,
        _mock_gps_only_draft, _mock_save_draft, _mock_send_email, conn, monkeypatch,
    ):
        """A closer-to-real second scenario: a stateful fake repo where the
        row is mutated in place by set_status, so a second full invocation
        (claim allowed again, simulating a redelivered message) still must
        not re-send because emailed_at is now set."""
        state = _row()

        fake_repo = MagicMock(name="repo")
        fake_repo.claim_for_drafting.return_value = True
        fake_repo.get.side_effect = lambda _conn, _id: dict(state)

        def _set_status(_conn, _id, new_status, **fields):
            state["status"] = new_status
            state.update(fields)
            return True

        fake_repo.set_status.side_effect = _set_status
        monkeypatch.setattr(onboarding_tasks, "repo", fake_repo)
        _mock_sam2_draft.return_value = {"type": "FeatureCollection"}

        first = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)
        assert first == {"ok": True, "status": "drafted"}
        assert _mock_send_email.delay.call_count == 1
        assert state["emailed_at"] is not None

        second = onboarding_tasks._run_draft_and_notify(_REQUEST_ID, conn)
        assert second == {"ok": True, "status": "drafted"}
        # Still exactly one email sent in total across both invocations.
        assert _mock_send_email.delay.call_count == 1
