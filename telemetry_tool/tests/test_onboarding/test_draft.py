"""Tests for onboarding/draft.py (Task 7).

Key test: gps_only_draft's raw output must pass the REAL
track_surface.gt_validate.validate_gt_geojson (which returns a list of
failure messages -- empty means valid, see gt_validate.py:61).
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from onboarding import draft
from track_surface.gt_validate import validate_gt_geojson

# ── fixtures ──────────────────────────────────────────────────────────────

_LAT0 = 45.0
_LON0 = 5.0
_MX = math.cos(math.radians(_LAT0)) * 111_320.0
_MY = 110_540.0


def _ellipse_centerline_lonlat(n: int = 30, a_m: float = 60.0, b_m: float = 35.0) -> list:
    """A ~30-point closed-ish oval lap trace (min curvature radius ~20 m,
    comfortably bigger than DEFAULT_HALF_WIDTH_M=4 m, so offsetting it
    cannot self-intersect)."""
    pts = []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        x = a_m * math.cos(t)
        y = b_m * math.sin(t)
        lon = _LON0 + x / _MX
        lat = _LAT0 + y / _MY
        pts.append([lon, lat])
    return pts


SAMPLE_CENTERLINE_LONLAT = _ellipse_centerline_lonlat()

VALID_BBOX = {"min_lat": 44.999, "max_lat": 45.001, "min_lon": 4.999, "max_lon": 5.001}


def _session_gps_from_centerline(n: int = 40) -> list:
    return _ellipse_centerline_lonlat(n=n)


def _flower_centerline_lonlat(n: int = 120, r0_m: float = 20.0, r1_m: float = 15.0, k: int = 5) -> list:
    """A 5-lobed rose curve (r = r0 + r1*cos(k*theta)): curvature varies fast
    enough between lobes that offsetting by DEFAULT_HALF_WIDTH_M (4 m) is
    guaranteed to fold a lobe's boundary across itself (verified empirically:
    self-intersects for half_width_m >= 2 here, well under the default)."""
    out = []
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        r = r0_m + r1_m * math.cos(k * theta)
        x = r * math.cos(theta)
        y = r * math.sin(theta)
        lon = _LON0 + x / _MX
        lat = _LAT0 + y / _MY
        out.append([lon, lat])
    return out


# ── gps_only_draft: the key acceptance test ───────────────────────────────

def test_gps_only_draft_passes_gt_validator(tmp_path):
    gj = draft.gps_only_draft(SAMPLE_CENTERLINE_LONLAT)

    p = tmp_path / "d.geojson"
    p.write_text(json.dumps(gj), encoding="utf-8")

    messages = validate_gt_geojson(p)  # real return type: list[str], empty == valid
    assert messages == [], f"draft failed gt_validate: {messages}"


def test_gps_only_draft_shape():
    gj = draft.gps_only_draft(SAMPLE_CENTERLINE_LONLAT)
    assert gj["type"] == "FeatureCollection"
    assert gj["properties"]["schema"] == "trackreco_ground_truth_v1"
    assert gj["properties"]["reviewed_by"]
    roles = {f["properties"]["role"] for f in gj["features"]}
    assert roles == {"left_boundary_gt", "right_boundary_gt"}
    for feat in gj["features"]:
        coords = feat["geometry"]["coordinates"]
        assert len(coords) >= 20
        assert coords[0] == coords[-1]  # closed loop


def test_gps_only_draft_rejects_too_short_centerline():
    with pytest.raises(draft.DraftError):
        draft.gps_only_draft([[5.0, 45.0], [5.0001, 45.0001]])


def test_gps_only_draft_rejects_non_finite_centerline():
    bad = [list(p) for p in SAMPLE_CENTERLINE_LONLAT]
    bad[0][0] = float("nan")
    with pytest.raises(draft.DraftError):
        draft.gps_only_draft(bad)


def test_gps_only_draft_rejects_self_intersection_at_tight_lobes():
    # Rapidly-varying curvature (5-lobed rose curve) -> offsetting by the
    # default half_width_m folds a lobe's boundary across itself ->
    # DraftError, not silently invalid geometry.
    flower = _flower_centerline_lonlat()
    with pytest.raises(draft.DraftError):
        draft.gps_only_draft(flower)  # default half_width_m=4.0


def test_gps_only_draft_rejects_non_positive_half_width():
    with pytest.raises(draft.DraftError):
        draft.gps_only_draft(SAMPLE_CENTERLINE_LONLAT, half_width_m=0.0)


# ── validate_bbox ──────────────────────────────────────────────────────────

def test_validate_bbox_accepts_valid_bbox():
    draft.validate_bbox(VALID_BBOX)  # must not raise


@pytest.mark.parametrize(
    "bad_bbox",
    [
        {"min_lat": float("nan"), "max_lat": 45.001, "min_lon": 4.999, "max_lon": 5.001},
        {"min_lat": 0.0, "max_lat": 200.0, "min_lon": 4.999, "max_lon": 5.001},
        {"min_lat": 44.999, "max_lat": 45.001, "min_lon": 0.0, "max_lon": 999.0},
        {"min_lat": 45.001, "max_lat": 44.999, "min_lon": 4.999, "max_lon": 5.001},  # min>=max
        {"min_lat": 44.0, "max_lat": 44.5, "min_lon": 4.999, "max_lon": 5.001},  # 0.5 deg span
    ],
    ids=["nan", "lat_out_of_range", "lon_out_of_range", "min_gte_max", "span_too_large"],
)
def test_validate_bbox_rejects_bad_bboxes(bad_bbox):
    with pytest.raises(draft.DraftError):
        draft.validate_bbox(bad_bbox)


def test_validate_bbox_rejects_missing_keys():
    with pytest.raises(draft.DraftError):
        draft.validate_bbox({"min_lat": 0.0, "max_lat": 1.0})


# ── sam2_draft: best-effort, never raises ─────────────────────────────────

def _configure_preflight_ok(monkeypatch, tmp_path):
    """Set ONBOARDING_TRACKRECO_DIR/PYTHON so ``_sam2_preflight()`` passes.

    Several sam2_draft tests below monkeypatch ``_trackreco_script`` and/or
    ``subprocess.run`` directly to control what happens AFTER preflight --
    but preflight itself runs first (see sam2_draft) and, if left unset in
    the bare test-process env, fails closed before subprocess.run is ever
    reached -- silently turning those tests vacuous (they'd pass for the
    wrong reason: preflight skip, not the subprocess behavior they name).
    Call this first so the tests actually exercise what they claim to.
    """
    checkout = tmp_path.joinpath(*draft._SAM2_SCRIPT_RELPATH).parent
    checkout.mkdir(parents=True, exist_ok=True)
    checkout.joinpath(draft._SAM2_SCRIPT_RELPATH[-1]).write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(tmp_path))
    fake_python = tmp_path / "fake_python.exe"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("ONBOARDING_TRACKRECO_PYTHON", str(fake_python))
    assert draft._sam2_preflight() == "ok"
    return tmp_path


def test_sam2_draft_returns_none_when_trackreco_checkout_absent(monkeypatch, tmp_path):
    """Defensive-fallback path INSIDE sam2_draft: even once preflight passes
    (so this is NOT merely the preflight-skip shortcut, see
    test_sam2_draft_skips_without_raising_when_preflight_fails below), if
    _trackreco_script() itself still comes back None on the actual attempt,
    sam2_draft must return None rather than raise."""
    _configure_preflight_ok(monkeypatch, tmp_path)
    monkeypatch.setattr(draft, "_trackreco_script", lambda: None)
    result = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())
    assert result is None


def test_sam2_draft_returns_none_when_subprocess_raises(monkeypatch, tmp_path):
    _configure_preflight_ok(monkeypatch, tmp_path)
    fake_script = tmp_path.joinpath(*draft._SAM2_SCRIPT_RELPATH)
    monkeypatch.setattr(draft, "_trackreco_script", lambda: fake_script)

    def _raise(*a, **k):
        raise FileNotFoundError("python interpreter not found")

    monkeypatch.setattr(draft.subprocess, "run", _raise)
    result = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())
    assert result is None


def test_sam2_draft_returns_none_on_nonzero_exit(monkeypatch, tmp_path):
    _configure_preflight_ok(monkeypatch, tmp_path)
    fake_script = tmp_path.joinpath(*draft._SAM2_SCRIPT_RELPATH)
    monkeypatch.setattr(draft, "_trackreco_script", lambda: fake_script)

    class _Result:
        returncode = 1
        stdout = b""
        stderr = b"boom"

    monkeypatch.setattr(draft.subprocess, "run", lambda *a, **k: _Result())
    result = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())
    assert result is None


def test_sam2_draft_returns_none_on_subprocess_timeout(monkeypatch, tmp_path):
    """HIGH fix coverage: a slow SAM2 subprocess must hit subprocess.run's
    OWN catchable ``TimeoutExpired`` (never Celery's uncatchable hard-limit
    SIGKILL) so this always falls through to gps_only_draft. See
    onboarding/draft.py's _SAM2_TIMEOUT_S and tasks/onboarding_tasks.py's
    _ONBOARDING_SOFT_TIME_LIMIT_S/_ONBOARDING_HARD_TIME_LIMIT_S for how the
    three numbers are kept ordered so this is guaranteed, not a race."""
    _configure_preflight_ok(monkeypatch, tmp_path)
    fake_script = tmp_path.joinpath(*draft._SAM2_SCRIPT_RELPATH)
    monkeypatch.setattr(draft, "_trackreco_script", lambda: fake_script)

    def _timeout(cmd, **kwargs):
        raise draft.subprocess.TimeoutExpired(cmd=cmd, timeout=draft._SAM2_TIMEOUT_S)

    monkeypatch.setattr(draft.subprocess, "run", _timeout)
    result = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())
    assert result is None


def test_sam2_draft_returns_none_on_invalid_bbox(monkeypatch):
    # Never even gets to subprocess -- validate_bbox fails first, caught
    # internally (sam2_draft NEVER raises).
    result = draft.sam2_draft({"min_lat": 999.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0},
                               _session_gps_from_centerline())
    assert result is None


def test_sam2_draft_returns_none_on_too_few_gps_points(monkeypatch):
    monkeypatch.setattr(draft, "_trackreco_script", lambda: object())
    result = draft.sam2_draft(VALID_BBOX, [[5.0, 45.0]] * 3)
    assert result is None


# ── _sam2_preflight ──────────────────────────────────────────────────────

def _make_trackreco_checkout(tmp_path):
    """A tmp dir with the trackreco script (but no interpreter) in place."""
    script = tmp_path.joinpath(*draft._SAM2_SCRIPT_RELPATH)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# stub\n", encoding="utf-8")
    return tmp_path


def test_sam2_preflight_reason_when_dir_env_unset(monkeypatch):
    monkeypatch.delenv("ONBOARDING_TRACKRECO_DIR", raising=False)
    reason = draft._sam2_preflight()
    assert reason == "ONBOARDING_TRACKRECO_DIR is not set"


def test_sam2_preflight_reason_when_dir_does_not_exist(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(missing))
    reason = draft._sam2_preflight()
    assert "does not exist" in reason
    assert "does-not-exist" in reason


def test_sam2_preflight_reason_when_script_missing(monkeypatch, tmp_path):
    # Directory exists but has no scripts/lap_track_to_draft.py under it.
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(tmp_path))
    reason = draft._sam2_preflight()
    assert "trackreco script not found" in reason


def test_sam2_preflight_reason_when_interpreter_env_unset(monkeypatch, tmp_path):
    _make_trackreco_checkout(tmp_path)
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(tmp_path))
    monkeypatch.delenv("ONBOARDING_TRACKRECO_PYTHON", raising=False)
    reason = draft._sam2_preflight()
    assert "ONBOARDING_TRACKRECO_PYTHON is not set" in reason


def test_sam2_preflight_reason_when_interpreter_does_not_exist(monkeypatch, tmp_path):
    _make_trackreco_checkout(tmp_path)
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(tmp_path))
    missing_python = tmp_path / "no-such-python.exe"
    monkeypatch.setenv("ONBOARDING_TRACKRECO_PYTHON", str(missing_python))
    reason = draft._sam2_preflight()
    assert "does not exist" in reason
    assert "no-such-python.exe" in reason


def test_sam2_preflight_ok_when_everything_present(monkeypatch, tmp_path):
    _make_trackreco_checkout(tmp_path)
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(tmp_path))
    fake_python = tmp_path / "fake_python.exe"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("ONBOARDING_TRACKRECO_PYTHON", str(fake_python))
    assert draft._sam2_preflight() == "ok"


# ── sam2_draft: interpreter selection + preflight gating ─────────────────

def test_sam2_draft_skips_without_raising_when_preflight_fails(monkeypatch):
    # No ONBOARDING_TRACKRECO_DIR/PYTHON set in this test process -> preflight
    # fails -> sam2_draft must skip (return None) WITHOUT ever touching
    # subprocess.run, never raising.
    monkeypatch.delenv("ONBOARDING_TRACKRECO_DIR", raising=False)
    monkeypatch.delenv("ONBOARDING_TRACKRECO_PYTHON", raising=False)

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called when preflight fails")

    monkeypatch.setattr(draft.subprocess, "run", _boom)
    result = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())
    assert result is None


def test_sam2_draft_uses_configured_interpreter(monkeypatch, tmp_path):
    checkout = _make_trackreco_checkout(tmp_path)
    monkeypatch.setenv("ONBOARDING_TRACKRECO_DIR", str(checkout))
    configured_python = tmp_path / "trackreco_venv_python.exe"
    configured_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("ONBOARDING_TRACKRECO_PYTHON", str(configured_python))

    captured_cmd = {}

    class _Result:
        returncode = 1  # non-zero so sam2_draft returns None right after capturing cmd
        stdout = b""
        stderr = b""

    def _fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(draft.subprocess, "run", _fake_run)
    result = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())

    assert result is None
    assert captured_cmd["cmd"][0] == str(configured_python)


def test_sam2_draft_falls_back_to_gps_only_draft_on_preflight_failure(monkeypatch):
    """Integration-style check of the module docstring's contract: when
    sam2_draft yields None (here, via a failing preflight), the caller
    (tasks.onboarding_tasks._run_draft_and_notify) falls back to
    gps_only_draft, and that fallback itself never raises."""
    monkeypatch.delenv("ONBOARDING_TRACKRECO_DIR", raising=False)
    monkeypatch.delenv("ONBOARDING_TRACKRECO_PYTHON", raising=False)

    geojson = draft.sam2_draft(VALID_BBOX, _session_gps_from_centerline())
    assert geojson is None

    fallback = draft.gps_only_draft(SAMPLE_CENTERLINE_LONLAT)
    assert fallback["properties"]["review_source"] == "gps_only_draft"


# ── save_draft / load_draft ────────────────────────────────────────────────

def test_save_and_load_draft_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ONBOARDING_DRAFT_DIR", str(tmp_path))
    gj = draft.gps_only_draft(SAMPLE_CENTERLINE_LONLAT)

    path = draft.save_draft("req-abc123", gj)
    assert path == str(tmp_path / "req-abc123.geojson")

    loaded = draft.load_draft("req-abc123")
    assert loaded == gj


def test_load_draft_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ONBOARDING_DRAFT_DIR", str(tmp_path))
    with pytest.raises(draft.DraftError):
        draft.load_draft("does-not-exist")


@pytest.mark.parametrize(
    "bad_id",
    ["../../etc/passwd", "a/b", "a\\b", "..", ""],
)
def test_load_draft_rejects_path_separators(tmp_path, monkeypatch, bad_id):
    monkeypatch.setenv("ONBOARDING_DRAFT_DIR", str(tmp_path))
    with pytest.raises(draft.DraftError):
        draft.load_draft(bad_id)


@pytest.mark.parametrize(
    "bad_id",
    ["../../etc/passwd", "a/b", "a\\b", "..", ""],
)
def test_save_draft_rejects_path_separators(tmp_path, monkeypatch, bad_id):
    monkeypatch.setenv("ONBOARDING_DRAFT_DIR", str(tmp_path))
    with pytest.raises(draft.DraftError):
        draft.save_draft(bad_id, {"type": "FeatureCollection", "features": []})
