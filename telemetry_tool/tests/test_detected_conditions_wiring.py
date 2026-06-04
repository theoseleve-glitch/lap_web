"""Detected track condition must feed the grip/theoretical models.

The scalar conditions classifier (step 10f) historically ran AFTER the
physics phase, so the grip/surface partition writers (orchestrator step
09j / 10d-ii) and run_theoretical consumed ``meta["track_state"]`` —
which is always the "dry" default now that the upload form has no Track
Condition dropdown. These tests pin the hoisted wiring:

1. the scalar classifier runs BEFORE Phase 3 physics (steps_ok order);
2. the detected label lands in ``meta["track_state"]`` (the key every
   condition consumer reads at call time) and reaches run_theoretical's
   ``condition=`` kwarg;
3. the zero-confidence safe-dry fallback does NOT overwrite an incoming
   label (a weather-API outage must not relabel a wet session as dry);
4. the ``meta["condition"]`` user override wins end-to-end.

Weather + centroid are mocked (no Open-Meteo network), mirroring the
``mock_deps`` pattern in tests/test_conditions/test_classifier_synthetic.py
but patching the BARE ``conditions.classifier`` module — the one the
orchestrator's ``from conditions import ...`` actually resolves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on path (matches test_re_port_correctness.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from conditions.open_meteo import OpenMeteoFetchError, WeatherFetchResult  # noqa: E402


# ── Synthetic CSV (same shape as test_re_port_correctness.py) ──────────

_SYNTHETIC_CSV = """\
Time (s),Lap #,Distance (m),Speed (m/s),Latitude (deg),Longitude (deg)
0.0,1,0.0,10.0,45.5000,9.2000
1.0,1,10.0,12.0,45.5001,9.2001
2.0,1,22.0,14.0,45.5002,9.2002
3.0,1,36.0,13.5,45.5003,9.2003
4.0,1,49.5,13.0,45.5004,9.2004
5.0,1,62.5,12.5,45.5005,9.2005
6.0,1,75.0,12.0,45.5006,9.2006
7.0,1,87.0,11.5,45.5007,9.2007
8.0,1,98.5,11.0,45.5008,9.2008
9.0,1,109.5,10.5,45.5009,9.2009
10.0,1,120.0,10.0,45.5010,9.2010
11.0,2,0.0,10.5,45.5000,9.2000
12.0,2,10.5,12.5,45.5001,9.2001
13.0,2,23.0,14.5,45.5002,9.2002
14.0,2,37.5,13.0,45.5003,9.2003
15.0,2,50.5,12.5,45.5004,9.2004
16.0,2,63.0,12.0,45.5005,9.2005
17.0,2,75.0,11.5,45.5006,9.2006
18.0,2,86.5,11.0,45.5007,9.2007
19.0,2,97.5,10.5,45.5008,9.2008
20.0,2,108.0,10.0,45.5009,9.2009
21.0,2,118.0,9.5,45.5010,9.2010
22.0,3,0.0,10.0,45.5000,9.2000
23.0,3,10.0,12.0,45.5001,9.2001
24.0,3,22.0,14.0,45.5002,9.2002
25.0,3,36.0,13.5,45.5003,9.2003
26.0,3,49.5,13.0,45.5004,9.2004
27.0,3,62.5,12.5,45.5005,9.2005
28.0,3,75.0,12.0,45.5006,9.2006
29.0,3,87.0,11.5,45.5007,9.2007
30.0,3,98.5,11.0,45.5008,9.2008
31.0,3,109.5,10.5,45.5009,9.2009
32.0,3,120.0,10.0,45.5010,9.2010
"""


def _make_weather(*, p_1h: float = 0.0) -> WeatherFetchResult:
    """Minimal 49h hourly + 30d daily weather; p_1h is session-start precip.

    p_1h > 2.0 trips classifier Rule 1 → label "wet" (precip_1h_heavy).
    p_1h = 0.0 with the warm/dry constants below classifies "dry".
    """
    n_hourly = 49
    hourly_arr = [0.0] * n_hourly
    hourly_arr[-1] = p_1h
    return WeatherFetchResult(
        hourly={
            "hourly": {
                "time": [
                    f"2026-02-{(5 + i // 24):02d}T{(i % 24):02d}:00"
                    for i in range(n_hourly)
                ],
                "temperature_2m": [20.0] * n_hourly,
                "precipitation": hourly_arr,
                "cloudcover": [30.0] * n_hourly,
                "windspeed_10m": [10.0] * n_hourly,
                "winddirection_10m": [180.0] * n_hourly,
                "shortwave_radiation": [500.0] * n_hourly,
                "relative_humidity_2m": [50.0] * n_hourly,
                "dewpoint_2m": [5.0] * n_hourly,
            }
        },
        daily={
            "daily": {
                "time": [f"day{i:02d}" for i in range(30)],
                "precipitation_sum": [0.0] * 30,
            }
        },
        source="api",
    )


def _run_pipeline(tmp_dir: Path, session_meta: dict, *,
                  weather=None, weather_exc=None) -> tuple[dict, dict]:
    """Run run_full_analysis with mocked classifier deps + a theoretical spy.

    Returns (summary, captured) where captured["condition"] is the kwarg
    run_theoretical received.
    """
    csv_file = tmp_dir / "synthetic_session.csv"
    csv_file.write_text(_SYNTHETIC_CSV, encoding="utf-8")

    from pipeline import run_full_analysis
    import pipeline.stages.s10_theoretical as s10t

    captured: dict = {}

    def theo_spy(*args, **kwargs):
        captured["condition"] = kwargs.get("condition")
        return None  # orchestrator handles theoretical_lap=None gracefully

    def fake_centroid(track_id):
        return (47.0, 0.0)

    def fake_fetch(lat, lon, when, *, cache_dir=None):
        if weather_exc is not None:
            raise weather_exc
        return weather

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr("conditions.classifier.resolve_track_centroid", fake_centroid)
        mp.setattr("conditions.classifier.fetch_weather", fake_fetch)
        mp.setattr(s10t, "run_theoretical", theo_spy)
        summary = run_full_analysis(
            csv_path=str(csv_file),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )
    finally:
        mp.undo()
    return summary, captured


# ══════════════════════════════════════════════════════════════════
# Scenario 1 — weather detects WET (Rule 1, P1 > 2 mm)
# ══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def wet_run(tmp_path_factory):
    meta = {
        "session_type": "practice",
        "driver_name": "TestDriver",
        "date": "2026-03-01",
    }
    return _run_pipeline(
        tmp_path_factory.mktemp("wet"), meta, weather=_make_weather(p_1h=2.5)
    )


class TestDetectedWetFeedsModels:

    def test_classifier_runs_before_physics(self, wet_run):
        """The scalar classification must precede Phase 3 (steps_ok order)."""
        summary, _ = wet_run
        steps = summary["steps_ok"]
        assert "10f_conditions" in steps, f"steps_ok={steps}"
        assert steps.index("10f_conditions") < steps.index("09a_reference_line"), (
            "10f_conditions must run before Phase 3 physics; "
            f"steps_ok order = {steps}"
        )

    def test_detected_label_lands_in_track_state(self, wet_run):
        """meta['track_state'] (read by every condition consumer) = detected."""
        summary, _ = wet_run
        assert summary["session_meta"]["track_state"] == "wet"

    def test_detected_label_reaches_theoretical(self, wet_run):
        """run_theoretical receives the detected label, not the dry default."""
        _, captured = wet_run
        assert captured.get("condition") == "wet"

    def test_conditions_blob_still_correct(self, wet_run):
        """Pin: the displayed classifier blob keeps working as before."""
        summary, _ = wet_run
        conditions = summary.get("conditions")
        assert conditions is not None
        assert conditions["label"] == "wet"
        assert conditions["source"] == "weather"


# ══════════════════════════════════════════════════════════════════
# Scenario 2 — weather API outage → safe-dry fallback must NOT overwrite
# ══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def fallback_run(tmp_path_factory):
    meta = {
        "session_type": "practice",
        "driver_name": "TestDriver",
        "date": "2026-03-01",
        "track_state": "wet",  # incoming label (e.g. batch re-analysis)
    }
    return _run_pipeline(
        tmp_path_factory.mktemp("fallback"), meta,
        weather_exc=OpenMeteoFetchError("simulated outage"),
    )


class TestSafeDryFallbackDoesNotOverwrite:

    def test_incoming_label_preserved(self, fallback_run):
        """Zero-confidence fallback must not relabel a wet session dry."""
        summary, _ = fallback_run
        assert summary["session_meta"]["track_state"] == "wet"

    def test_consumers_see_incoming_label(self, fallback_run):
        _, captured = fallback_run
        assert captured.get("condition") == "wet"

    def test_fallback_blob_recorded(self, fallback_run):
        """Pin: the safe-dry blob is still surfaced for display/rationale."""
        summary, _ = fallback_run
        conditions = summary.get("conditions")
        assert conditions is not None
        assert conditions["dominant_factor"] == "safe_dry_fallback"
        assert conditions["confidence"] == 0.0


# ══════════════════════════════════════════════════════════════════
# Scenario 3 — meta["condition"] user override wins end-to-end
# ══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def override_run(tmp_path_factory):
    meta = {
        "session_type": "practice",
        "driver_name": "TestDriver",
        "date": "2026-03-01",
        "condition": "greasy",  # explicit user override channel
    }
    return _run_pipeline(
        tmp_path_factory.mktemp("override"), meta, weather=_make_weather(p_1h=0.0)
    )


class TestUserOverrideWins:

    def test_override_label_lands_in_track_state(self, override_run):
        summary, _ = override_run
        assert summary["session_meta"]["track_state"] == "greasy"

    def test_override_reaches_theoretical(self, override_run):
        _, captured = override_run
        assert captured.get("condition") == "greasy"

    def test_override_source_is_user(self, override_run):
        """Pin: classifier reports source='user' with full confidence."""
        summary, _ = override_run
        conditions = summary.get("conditions")
        assert conditions is not None
        assert conditions["label"] == "greasy"
        assert conditions["source"] == "user"
