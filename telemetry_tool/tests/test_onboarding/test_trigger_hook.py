"""Test the track-onboarding GT-miss detection trigger hook (Task 13b).

This is the ONE call site that makes the whole Track Onboarding Loop fire:
``pipeline.stages.s10d_surface._maybe_trigger_onboarding``, called
immediately after ``build_track_surface`` inside ``run_surface_build``.

Everything downstream (``onboarding.service.record_missing_geometry``, its
repo/draft/email machinery) is already built and tested elsewhere (Tasks
4-12) -- this suite mocks ``record_missing_geometry`` wholesale and asserts
only the trigger's own decision logic:

  * fires exactly on a genuine GT-miss (``boundary_source is None``) from an
    operator run for a recognised track, with a valid bbox/centerline/
    canonical track_key/session_ref derived from the driven GPS.
  * refuses on a GT-hit, a non-operator run, or an unrecognised track.
  * never lets a ``record_missing_geometry`` exception escape (best-effort).

``_maybe_trigger_onboarding`` is called directly (not via the full
``run_surface_build``/pipeline) so this suite needs no CSV fixtures, no
track_surface build, no DB/broker -- matching the "mocks
record_missing_geometry" premise given in the task brief.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.stages import s10d_surface  # noqa: E402

_TRACK_ID = "kct_raw_alias"
_CANONICAL_ID = "kct"
_JOB_ID = "job-13b-abc123"


def _make_lap_df(n: int = 50, lat0: float = 45.0, lon0: float = 5.0) -> pd.DataFrame:
    """One lap's worth of a small closed GPS loop (canonical column names)."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return pd.DataFrame({
        "lat_deg": lat0 + 0.001 * np.sin(t),
        "lon_deg": lon0 + 0.001 * np.cos(t),
    })


def _resampled_laps(n_laps: int = 3) -> dict[int, pd.DataFrame]:
    return {i: _make_lap_df() for i in range(1, n_laps + 1)}


@pytest.fixture
def mock_record(monkeypatch):
    """Patch onboarding.service.record_missing_geometry (bare import path --
    matches the lazy `from onboarding.service import record_missing_geometry`
    inside _maybe_trigger_onboarding).
    """
    import onboarding.service as service

    fake = MagicMock(name="record_missing_geometry", return_value="req-id-1")
    monkeypatch.setattr(service, "record_missing_geometry", fake)
    return fake


@pytest.fixture
def mock_resolver(monkeypatch):
    """Patch track_surface.gt_loader's resolvers (bare import path) so
    _TRACK_ID resolves to _CANONICAL_ID without touching the real alias
    registry/PG.
    """
    import track_surface.gt_loader as gt_loader

    resolve_track_id = MagicMock(name="resolve_track_id", return_value=_CANONICAL_ID)
    resolve_canonical_via_pg = MagicMock(name="resolve_canonical_via_pg", return_value=None)
    monkeypatch.setattr(gt_loader, "resolve_track_id", resolve_track_id)
    monkeypatch.setattr(gt_loader, "resolve_canonical_via_pg", resolve_canonical_via_pg)
    return resolve_track_id, resolve_canonical_via_pg


def _gt_miss_surface():
    return SimpleNamespace(boundary_source=None)


def _gt_hit_surface():
    return SimpleNamespace(boundary_source="gt_anchored_native")


def _call(**overrides):
    kwargs = dict(
        session_surface=_gt_miss_surface(),
        track_id=_TRACK_ID,
        is_operator_run=True,
        job_id=_JOB_ID,
        fingerprint={"length_m": 1234.5},
        track_label="KCT Test Track",
        resampled_laps=_resampled_laps(),
    )
    kwargs.update(overrides)
    return s10d_surface._maybe_trigger_onboarding(**kwargs)


class TestGtMissOperatorConfidentTrack:
    def test_calls_record_missing_geometry_once(self, mock_record, mock_resolver):
        _call()
        assert mock_record.call_count == 1

    def test_track_key_is_canonical_id(self, mock_record, mock_resolver):
        _call()
        _, kwargs = mock_record.call_args
        assert kwargs["track_key"] == _CANONICAL_ID

    def test_session_ref_equals_job_id(self, mock_record, mock_resolver):
        _call()
        _, kwargs = mock_record.call_args
        assert kwargs["session_ref"] == _JOB_ID

    def test_bbox_is_valid_wgs84_box_from_gps(self, mock_record, mock_resolver):
        _call()
        _, kwargs = mock_record.call_args
        bbox = kwargs["bbox"]
        assert bbox is not None
        assert bbox["min_lon"] < bbox["max_lon"]
        assert bbox["min_lat"] < bbox["max_lat"]
        # Derived from the synthetic loop centred on (45.0, 5.0) with a
        # ~0.001 deg radius -- sanity-check it's in that neighbourhood.
        assert 44.9 < bbox["min_lat"] < bbox["max_lat"] < 45.1
        assert 4.9 < bbox["min_lon"] < bbox["max_lon"] < 5.1

    def test_draft_centerline_non_empty(self, mock_record, mock_resolver):
        _call()
        _, kwargs = mock_record.call_args
        centerline = kwargs["draft_centerline"]
        assert centerline
        assert len(centerline) > 0
        # [lon, lat] pairs
        assert all(len(pt) == 2 for pt in centerline)

    def test_is_operator_run_forwarded_true(self, mock_record, mock_resolver):
        _call()
        _, kwargs = mock_record.call_args
        assert kwargs["is_operator_run"] is True

    def test_fingerprint_and_label_forwarded(self, mock_record, mock_resolver):
        _call()
        _, kwargs = mock_record.call_args
        assert kwargs["fingerprint"] == {"length_m": 1234.5}
        assert kwargs["track_label"] == "KCT Test Track"


class TestRefusals:
    def test_gt_hit_not_called(self, mock_record, mock_resolver):
        _call(session_surface=_gt_hit_surface())
        mock_record.assert_not_called()

    def test_no_surface_not_called(self, mock_record, mock_resolver):
        _call(session_surface=None)
        mock_record.assert_not_called()

    def test_operator_false_not_called(self, mock_record, mock_resolver):
        _call(is_operator_run=False)
        mock_record.assert_not_called()

    def test_unknown_track_not_called(self, mock_record, mock_resolver):
        _call(track_id="unknown_track")
        mock_record.assert_not_called()

    def test_empty_track_id_not_called(self, mock_record, mock_resolver):
        _call(track_id="")
        mock_record.assert_not_called()

    def test_no_job_id_not_called(self, mock_record, mock_resolver):
        _call(job_id=None)
        mock_record.assert_not_called()

    def test_unresolvable_canonical_id_not_called(self, mock_record, monkeypatch):
        import track_surface.gt_loader as gt_loader
        monkeypatch.setattr(gt_loader, "resolve_track_id", MagicMock(return_value=None))
        monkeypatch.setattr(gt_loader, "resolve_canonical_via_pg", MagicMock(return_value=None))
        _call()
        mock_record.assert_not_called()


class TestExceptionSwallowed:
    def test_record_missing_geometry_raising_is_swallowed(self, mock_record, mock_resolver):
        mock_record.side_effect = RuntimeError("boom")
        result = _call()  # must not raise
        assert result is None
        assert mock_record.call_count == 1
