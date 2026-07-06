"""Tests for tasks/onboarding_tasks.py's bounded auto-resend fast-follow
(migration 082): _resend_expired_links + its wiring into reconcile_onboarding.

Everything external is mocked: onboarding_tasks.repo, onboarding_tasks.tokens,
and onboarding_tasks.send_email_async -- mirrors the mocking style in
test_onboarding_tasks.py. Tests call _resend_expired_links(conn) and
_run_reconcile_onboarding(conn) directly (the plain, Celery-free helpers).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tasks.onboarding_tasks as onboarding_tasks  # noqa: E402


def _row(request_id: str, **overrides) -> dict:
    base = dict(
        id=request_id,
        track_key=f"T1_{request_id}",
        track_label=f"Track {request_id}",
        emailed_at="2026-06-01T00:00:00Z",
        email_count=1,
    )
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ANNOTATOR_HOST", "https://annotator.example.com")
    monkeypatch.setenv("ONBOARDING_OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("ONBOARDING_TOKEN_TTL_HOURS", "72")


@pytest.fixture
def _mock_repo(monkeypatch):
    fake = MagicMock(name="repo")
    monkeypatch.setattr(onboarding_tasks, "repo", fake)
    return fake


@pytest.fixture
def _mock_tokens(monkeypatch):
    fake = MagicMock(name="tokens")
    fake.mint.side_effect = [
        ("raw-token-1", "jti-1"),
        ("raw-token-2", "jti-2"),
    ]
    monkeypatch.setattr(onboarding_tasks, "tokens", fake)
    return fake


@pytest.fixture
def _mock_send_email(monkeypatch):
    fake = MagicMock(name="send_email_async")
    monkeypatch.setattr(onboarding_tasks, "send_email_async", fake)
    return fake


@pytest.fixture
def conn():
    return MagicMock(name="conn")


class TestResendHappyPath:
    def test_two_expired_ids_both_claim_both_send(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn,
    ):
        _mock_repo.find_expired_emailed.return_value = ["req-1", "req-2"]
        _mock_repo.claim_resend.return_value = True
        _mock_repo.get.side_effect = [_row("req-1"), _row("req-2")]

        resent = onboarding_tasks._resend_expired_links(conn)

        assert resent == 2
        assert _mock_tokens.mint.call_count == 2
        assert _mock_tokens.mint.call_args_list == [call("req-1"), call("req-2")]
        assert _mock_repo.claim_resend.call_count == 2
        _mock_repo.claim_resend.assert_any_call(conn, "req-1", "jti-1", 72, onboarding_tasks.MAX_EMAILS)
        _mock_repo.claim_resend.assert_any_call(conn, "req-2", "jti-2", 72, onboarding_tasks.MAX_EMAILS)
        assert _mock_send_email.delay.call_count == 2

        first_call = _mock_send_email.delay.call_args_list[0]
        assert first_call.args[0] == "onboarding_task"
        assert first_call.args[1] == "ops@example.com"
        variables = first_call.args[2]
        assert variables["track_key"] == "T1_req-1"
        assert "#token=raw-token-1" in variables["annotator_url"]
        assert "?req=req-1" in variables["annotator_url"]
        assert "raw-token-1" not in variables["annotator_url"].split("#")[0]

    def test_mint_before_claim_jti_matches_emailed_token(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn,
    ):
        """The jti passed to claim_resend must be the SAME jti embedded in
        the raw token actually emailed, AND minting must happen before the
        claim call (order, not just value) -- otherwise a mint failure could
        leave a claimed/spent row with no token ever sent."""
        order: list[str] = []
        _mock_tokens.mint.side_effect = None
        _mock_tokens.mint.side_effect = lambda request_id: (order.append("mint"), ("raw-token-1", "jti-1"))[1]
        _mock_repo.claim_resend.side_effect = lambda *a, **k: (order.append("claim"), True)[1]
        _mock_repo.find_expired_emailed.return_value = ["req-1"]
        _mock_repo.get.return_value = _row("req-1")

        onboarding_tasks._resend_expired_links(conn)

        assert order == ["mint", "claim"]
        # the jti actually claimed matches the jti embedded in the emailed token
        claim_call_args = _mock_repo.claim_resend.call_args
        assert claim_call_args.args[2] == "jti-1"
        sent_url = _mock_send_email.delay.call_args.args[2]["annotator_url"]
        assert "#token=raw-token-1" in sent_url


class TestResendClaimLost:
    def test_claim_resend_false_no_email_for_that_id(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn,
    ):
        _mock_repo.find_expired_emailed.return_value = ["req-1", "req-2"]
        _mock_repo.claim_resend.side_effect = [False, True]
        _mock_repo.get.return_value = _row("req-2")

        resent = onboarding_tasks._resend_expired_links(conn)

        assert resent == 1
        assert _mock_send_email.delay.call_count == 1
        sent_variables = _mock_send_email.delay.call_args.args[2]
        assert sent_variables["track_key"] == "T1_req-2"


class TestResendExceptionIsolation:
    def test_one_id_exception_does_not_stop_the_other(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn,
    ):
        _mock_repo.find_expired_emailed.return_value = ["req-1", "req-2"]
        _mock_repo.claim_resend.side_effect = [RuntimeError("db blew up"), True]
        _mock_repo.get.return_value = _row("req-2")

        resent = onboarding_tasks._resend_expired_links(conn)

        assert resent == 1
        assert _mock_send_email.delay.call_count == 1


class TestResendMissingEnvDenySafe:
    def test_missing_operator_email_skips_entire_pass(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn, monkeypatch,
    ):
        monkeypatch.delenv("ONBOARDING_OPERATOR_EMAIL", raising=False)

        resent = onboarding_tasks._resend_expired_links(conn)

        assert resent == 0
        _mock_repo.find_expired_emailed.assert_not_called()
        _mock_send_email.delay.assert_not_called()

    def test_missing_annotator_host_skips_entire_pass(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn, monkeypatch,
    ):
        monkeypatch.delenv("ANNOTATOR_HOST", raising=False)

        resent = onboarding_tasks._resend_expired_links(conn)

        assert resent == 0
        _mock_repo.find_expired_emailed.assert_not_called()
        _mock_send_email.delay.assert_not_called()


class TestResendNoExpiredIds:
    def test_empty_list_resends_zero(
        self, _mock_repo, _mock_tokens, _mock_send_email, conn,
    ):
        _mock_repo.find_expired_emailed.return_value = []

        resent = onboarding_tasks._resend_expired_links(conn)

        assert resent == 0
        _mock_tokens.mint.assert_not_called()
        _mock_send_email.delay.assert_not_called()


class TestReconcileInvokesBothPhases:
    def test_reconcile_onboarding_calls_stale_pass_then_resend_pass(
        self, _mock_repo, monkeypatch, conn,
    ):
        _mock_repo.find_stale_unemailed.return_value = ["stale-1"]
        _mock_repo.reset_for_retry.return_value = True

        fake_draft_and_notify = MagicMock(name="draft_and_notify")
        monkeypatch.setattr(onboarding_tasks, "draft_and_notify", fake_draft_and_notify)

        fake_resend = MagicMock(name="_resend_expired_links", return_value=3)
        monkeypatch.setattr(onboarding_tasks, "_resend_expired_links", fake_resend)

        result = onboarding_tasks._run_reconcile_onboarding(conn)

        _mock_repo.find_stale_unemailed.assert_called_once()
        fake_draft_and_notify.delay.assert_called_once_with("stale-1")
        fake_resend.assert_called_once_with(conn)
        assert result == {"ok": True, "found": 1, "reset": 1, "resent": 3}


class TestInitialSendSetsEmailCountOne:
    """Covers the _run_draft_and_notify change: the initial email's
    set_status(... "emailed", ...) call must also stamp email_count=1 so
    the resend cap counts the initial send."""

    def test_initial_email_sets_email_count_one(self, monkeypatch):
        from onboarding.draft import DraftError  # noqa: F401 -- sanity import

        fake_repo = MagicMock(name="repo")
        fake_repo.claim_for_drafting.return_value = True
        row_after_claim = dict(
            id="req-x", track_key="T1", track_label="Test",
            fingerprint=None, draft_centerline=[[1.0, 2.0], [1.1, 2.1]],
            status="drafting",
            bbox={"min_lat": 45.0, "max_lat": 45.01, "min_lon": 5.0, "max_lon": 5.01},
            token_jti=None, emailed_at=None,
        )
        row_before_email = dict(row_after_claim, token_jti="jti-1", emailed_at=None)
        fake_repo.get.side_effect = [row_after_claim, row_before_email]
        fake_repo.set_status.return_value = True
        monkeypatch.setattr(onboarding_tasks, "repo", fake_repo)

        fake_tokens = MagicMock(name="tokens")
        fake_tokens.mint.return_value = ("raw-token", "jti-1")
        monkeypatch.setattr(onboarding_tasks, "tokens", fake_tokens)

        monkeypatch.setattr(onboarding_tasks, "validate_bbox", MagicMock(return_value=None))
        monkeypatch.setattr(
            onboarding_tasks, "sam2_draft",
            MagicMock(return_value={"type": "FeatureCollection"}),
        )
        monkeypatch.setattr(onboarding_tasks, "save_draft", MagicMock(return_value="/tmp/x.geojson"))
        monkeypatch.setattr(onboarding_tasks, "send_email_async", MagicMock(name="send_email_async"))

        monkeypatch.setenv("ANNOTATOR_HOST", "https://annotator.example.com")
        monkeypatch.setenv("ONBOARDING_OPERATOR_EMAIL", "ops@example.com")

        result = onboarding_tasks._run_draft_and_notify("req-x", MagicMock(name="conn"))

        assert result == {"ok": True, "status": "drafted"}
        emailed_call = [
            c for c in fake_repo.set_status.call_args_list if c.args[2] == "emailed"
        ]
        assert len(emailed_call) == 1
        assert emailed_call[0].kwargs["email_count"] == 1
        assert emailed_call[0].kwargs["emailed_at"] is not None
