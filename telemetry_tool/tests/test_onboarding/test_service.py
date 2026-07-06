"""Test onboarding/service.py (Task 6): record_missing_geometry.

Everything here is mocked -- ``service.repo``, ``service.load_gt``, the
connection helpers, and the lazily-imported ``tasks.onboarding_tasks``.
This function must REFUSE to onboard in several cases (returns ``None``,
never touches ``repo``), and must only enqueue the async draft job when
the upserted row is brand new or was stuck in ``draft_failed``.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.onboarding import service  # noqa: E402

_TRACK_KEY = "T1_solokart"


@pytest.fixture(autouse=True)
def _mock_connection(monkeypatch):
    """Stub the connection helpers so no real PG connection is ever opened."""
    conn = MagicMock(name="conn")
    monkeypatch.setattr(service, "get_maint_connection", MagicMock(return_value=conn))
    monkeypatch.setattr(service, "return_pg_connection", MagicMock())
    return conn


@pytest.fixture
def _mock_repo(monkeypatch):
    fake_repo = MagicMock(name="repo")
    monkeypatch.setattr(service, "repo", fake_repo)
    return fake_repo


@pytest.fixture
def _mock_load_gt(monkeypatch):
    fake = MagicMock(name="load_gt", return_value=None)
    monkeypatch.setattr(service, "load_gt", fake)
    return fake


@pytest.fixture
def _mock_draft_and_notify(monkeypatch):
    """Inject a fake ``tasks.onboarding_tasks`` module (Task 10 doesn't
    exist yet) so the lazy ``from tasks.onboarding_tasks import
    draft_and_notify`` import inside ``service._enqueue_draft`` resolves
    to this fake instead of raising ImportError.
    """
    fake_task = MagicMock(name="draft_and_notify")
    fake_module = types.ModuleType("tasks.onboarding_tasks")
    fake_module.draft_and_notify = fake_task
    monkeypatch.setitem(sys.modules, "tasks.onboarding_tasks", fake_module)
    # Ensure a "tasks" package placeholder exists so the submodule import
    # machinery finds it (a bare ModuleType has no __path__, but Python's
    # `from tasks.onboarding_tasks import x` looks up sys.modules first
    # for the fully-qualified submodule name, which is enough here).
    if "tasks" not in sys.modules:
        monkeypatch.setitem(sys.modules, "tasks", types.ModuleType("tasks"))
    return fake_task


def _kwargs(**overrides):
    base = dict(
        track_key=_TRACK_KEY,
        track_label="Solokart FP",
        fingerprint={"n_sessions": 1},
        bbox={"min_lat": 1, "max_lat": 2, "min_lon": 3, "max_lon": 4},
        session_ref="sess-001",
        is_operator_run=True,
    )
    base.update(overrides)
    return base


class TestOperatorMissNewTrack:
    def test_new_track_enqueues_once(
        self, _mock_repo, _mock_load_gt, _mock_draft_and_notify, _mock_connection
    ):
        _mock_repo.upsert_open_request.return_value = ("req-1", True)

        result = service.record_missing_geometry(**_kwargs())

        assert result == "req-1"
        _mock_load_gt.assert_called_once_with(_TRACK_KEY)
        _mock_repo.upsert_open_request.assert_called_once()
        _mock_connection.commit.assert_called_once()
        _mock_draft_and_notify.delay.assert_called_once_with("req-1")
        # created=True -> no need to re-check existing row status
        _mock_repo.get.assert_not_called()


class TestSecondSessionSameTrack:
    def test_attach_to_emailed_row_does_not_enqueue(
        self, _mock_repo, _mock_load_gt, _mock_draft_and_notify, _mock_connection
    ):
        _mock_repo.upsert_open_request.return_value = ("req-1", False)
        _mock_repo.get.return_value = {"id": "req-1", "status": "emailed"}

        result = service.record_missing_geometry(**_kwargs(session_ref="sess-002"))

        assert result == "req-1"
        _mock_repo.get.assert_called_once_with(_mock_connection, "req-1")
        _mock_draft_and_notify.delay.assert_not_called()


class TestDraftFailedRetries:
    def test_existing_draft_failed_row_reenqueues(
        self, _mock_repo, _mock_load_gt, _mock_draft_and_notify, _mock_connection
    ):
        _mock_repo.upsert_open_request.return_value = ("req-1", False)
        _mock_repo.get.return_value = {"id": "req-1", "status": "draft_failed"}

        result = service.record_missing_geometry(**_kwargs(session_ref="sess-003"))

        assert result == "req-1"
        _mock_draft_and_notify.delay.assert_called_once_with("req-1")


class TestRefusals:
    def test_not_operator_run_returns_none_and_skips_upsert(
        self, _mock_repo, _mock_load_gt, _mock_connection
    ):
        result = service.record_missing_geometry(**_kwargs(is_operator_run=False))

        assert result is None
        _mock_repo.upsert_open_request.assert_not_called()
        _mock_load_gt.assert_not_called()

    @pytest.mark.parametrize("bad_key", ["", None, "unknown_track"])
    def test_bogus_track_key_returns_none_and_skips_upsert(
        self, _mock_repo, _mock_load_gt, _mock_connection, bad_key
    ):
        result = service.record_missing_geometry(**_kwargs(track_key=bad_key))

        assert result is None
        _mock_repo.upsert_open_request.assert_not_called()
        _mock_load_gt.assert_not_called()

    def test_gt_already_present_returns_none_and_skips_upsert(
        self, _mock_repo, _mock_load_gt, _mock_connection
    ):
        _mock_load_gt.return_value = object()  # any non-None GT

        result = service.record_missing_geometry(**_kwargs())

        assert result is None
        _mock_repo.upsert_open_request.assert_not_called()
