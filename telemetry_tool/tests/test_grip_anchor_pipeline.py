"""Grip anchor — schema, stage wiring and persistence."""
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


def test_corner_metrics_has_the_grip_anchor_columns(test_db):
    """The pytest fixture builds from db/schema.py, so a column that exists
    only in Alembic is invisible here — and therefore untestable."""
    cur = test_db.execute("SELECT * FROM corner_metrics LIMIT 0")
    cols = {d[0] for d in cur.description}

    assert "grip_anchor_tier" in cols
    assert "grip_anchor_reason" in cols
    assert "grip_anchor_pct" in cols
    assert "grip_anchor_baseline_g" in cols


def test_insert_corner_metric_carries_the_anchor_columns():
    from db.queries import INSERT_CORNER_METRIC

    for col in (
        "grip_anchor_tier", "grip_anchor_reason",
        "grip_anchor_pct", "grip_anchor_baseline_g",
    ):
        assert col in INSERT_CORNER_METRIC, f"{col} missing from the INSERT"
        assert f":{col}" in INSERT_CORNER_METRIC, f":{col} bind param missing"


def test_insert_corner_metrics_writer_does_not_crash_without_anchor_keys(seeded_db):
    """The real production writer (score_repo.insert_corner_metrics, reached
    from s15_persist.py, pipeline_tasks.py, endurance_tasks.py and
    sessions_v2.py) must still insert when the pipeline summary's per-lap
    metric dicts carry none of the four grip_anchor_* keys -- e.g. before the
    pipeline stage that computes them has run. Without binding all four
    params, sqlite3 raises ProgrammingError and the whole write is lost."""
    from web.repos.score_repo import insert_corner_metrics

    summary = {"per_lap_corner_metrics": [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0},
    ]}
    count = insert_corner_metrics(seeded_db, "s1", summary)
    assert count == 1

    row = seeded_db.execute(
        "SELECT grip_anchor_tier, grip_anchor_reason, grip_anchor_pct, "
        "grip_anchor_baseline_g FROM corner_metrics "
        "WHERE session_id = 's1' AND lap_number = 1 AND corner_id = 1"
    ).fetchone()
    assert row is not None
    assert row["grip_anchor_tier"] is None
    assert row["grip_anchor_reason"] is None
    assert row["grip_anchor_pct"] is None
    assert row["grip_anchor_baseline_g"] is None


def test_insert_corner_metrics_round_trips_anchor_values_uncapped(seeded_db):
    """grip_anchor_pct is deliberately NOT capped at 100 (the friction
    envelope is a p95 percentile, so exceedance is expected and diagnostic)
    -- prove the writer doesn't clamp it."""
    from web.repos.score_repo import insert_corner_metrics

    summary = {"per_lap_corner_metrics": [{
        "lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0,
        "grip_anchor_tier": "tier2_session_best",
        "grip_anchor_reason": "no_friction_model",
        "grip_anchor_pct": 137.5,
        "grip_anchor_baseline_g": 1.42,
    }]}
    count = insert_corner_metrics(seeded_db, "s1", summary)
    assert count == 1

    row = seeded_db.execute(
        "SELECT grip_anchor_tier, grip_anchor_reason, grip_anchor_pct, "
        "grip_anchor_baseline_g FROM corner_metrics "
        "WHERE session_id = 's1' AND lap_number = 1 AND corner_id = 1"
    ).fetchone()
    assert row["grip_anchor_tier"] == "tier2_session_best"
    assert row["grip_anchor_reason"] == "no_friction_model"
    assert row["grip_anchor_pct"] == pytest.approx(137.5)
    assert row["grip_anchor_baseline_g"] == pytest.approx(1.42)


def _lap_frame(n=400, a_lat_g=0.9):
    d = np.linspace(0.0, 1200.0, n)
    return pd.DataFrame({
        "Distance (m)": d,
        "Speed (m/s)": np.full(n, 25.0),
        "Lateral acceleration (G) *calc": np.full(n, a_lat_g),
        "accel_long_mps2": np.zeros(n),
    })


def test_run_grip_anchor_attaches_a_tier_to_every_metric():
    """Assert COMPUTED values, not just key presence -- a wrong impl where
    _corner_mask always returns None would ALSO make every metric come back
    with a non-None tier (TIER_REFUSED is still not-None), so the vocabulary
    membership check alone isn't enough either. The session-best baseline
    must be genuinely cross-lap: lap 1 scores against lap 2's peak, not its
    own (which would silently read 100% for every lap)."""
    from pipeline.stages import s10d2_grip_anchor
    import grip_anchor as ga

    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 25.0},
    ]
    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps = {1: _lap_frame(a_lat_g=0.9), 2: _lap_frame(a_lat_g=1.1)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)

    assert len(out) == 2
    for m in out:
        assert m["grip_anchor_tier"] in ga.TIERS

    # No friction model was supplied, so both must fall to the session-best
    # tier, named "no envelope" (not fabricated, not refused).
    lap1, lap2 = out[0], out[1]
    assert lap1["grip_anchor_tier"] == ga.TIER_DRIVER_BEST_SESSION
    assert lap1["grip_anchor_reason"] == ga.REASON_NO_ENVELOPE
    assert lap1["grip_anchor_pct"] == pytest.approx(100 * 0.9 / 1.1)   # ~81.82%, vs lap 2's peak
    assert lap1["grip_anchor_baseline_g"] == pytest.approx(1.1)

    assert lap2["grip_anchor_tier"] == ga.TIER_DRIVER_BEST_SESSION
    assert lap2["grip_anchor_reason"] == ga.REASON_NO_ENVELOPE
    assert lap2["grip_anchor_pct"] == pytest.approx(100.0)             # lap 2 IS the session best
    assert lap2["grip_anchor_baseline_g"] == pytest.approx(1.1)


def test_run_grip_anchor_refuses_rather_than_inventing_when_it_has_nothing():
    """No friction model, no usable laps: it must refuse, not fabricate.

    Asserting the REASON, not just the tier, matters here: a wrong
    implementation where decide_anchor always raises would ALSO land on
    TIER_REFUSED (the stage's except-branch fallback), but with
    REASON_NO_MEASUREMENT rather than the REASON_NO_LAP_BASELINE that
    decide_anchor itself genuinely reaches for this input -- so this
    distinguishes an honest refusal from every call being swallowed.
    """
    import grip_anchor as ga
    from pipeline.stages import s10d2_grip_anchor

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]
    out = s10d2_grip_anchor.run_grip_anchor(metrics, [], {})

    assert out[0]["grip_anchor_tier"] == ga.TIER_REFUSED
    assert out[0]["grip_anchor_reason"] == ga.REASON_NO_LAP_BASELINE
    assert out[0]["grip_anchor_pct"] is None
    assert out[0]["grip_anchor_baseline_g"] is None


def test_run_grip_anchor_never_raises_on_malformed_input():
    """This runs inside _safe_step, but a stage that throws loses the whole
    step; assert on RESULTS, not on the absence of an exception. A wrong
    implementation could satisfy a weaker "has the four keys" check while
    fabricating an out-of-vocabulary tier or an unbounded pct -- assert the
    genuine, honest refusal values instead."""
    from pipeline.stages import s10d2_grip_anchor
    import grip_anchor as ga

    out = s10d2_grip_anchor.run_grip_anchor(
        [{"lap_number": None, "corner_id": None}], [], {},
    )
    assert len(out) == 1
    assert out[0]["grip_anchor_tier"] == ga.TIER_REFUSED
    assert out[0]["grip_anchor_tier"] in ga.TIERS
    assert out[0]["grip_anchor_reason"] == ga.REASON_NO_LAP_BASELINE
    assert out[0]["grip_anchor_pct"] is None
    assert out[0]["grip_anchor_baseline_g"] is None


def test_run_grip_anchor_is_total_against_malformed_corners_and_metrics():
    """Fuzz-style regression for the three raise sites the reviewer found:
    a non-dict corner record, a corner with a non-numeric s_start, and a
    non-dict metric entry. None of these may raise, and every element that
    comes back -- even one that started life as `None` -- must carry all
    four grip_anchor_* keys."""
    from pipeline.stages import s10d2_grip_anchor

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]
    laps = {1: _lap_frame(a_lat_g=0.9)}

    for corners in (
        [None],
        ["garbage"],
        [{"corner_id": 1, "s_start": "abc", "s_end": 200.0}],
    ):
        out = s10d2_grip_anchor.run_grip_anchor(list(metrics), corners, laps)
        assert len(out) == 1
        for key in (
            "grip_anchor_tier", "grip_anchor_reason",
            "grip_anchor_pct", "grip_anchor_baseline_g",
        ):
            assert key in out[0], f"missing {key} for corners={corners!r}"

    out = s10d2_grip_anchor.run_grip_anchor([None], [], {})
    assert len(out) == 1
    for key in (
        "grip_anchor_tier", "grip_anchor_reason",
        "grip_anchor_pct", "grip_anchor_baseline_g",
    ):
        assert key in out[0], "missing key for a non-dict metric entry"


def test_run_grip_anchor_refuses_to_borrow_a_distant_envelope_bin():
    """A friction envelope with real measured coverage only far from this
    corner's apex speed must NOT be treated as a hit. Everything else this
    corner-lap needs to reach a PHYSICS tier is deliberately made healthy
    (a real friction model, a genuinely trusted lateral channel) so that,
    without the distance guard, it WOULD reach TIER_PHYSICS_ELLIPSE_FITTED
    off a bin measured 35 m/s away from its own apex speed -- reaching a
    physics tier off a borrowed, distant bin would claim measured coverage
    the data doesn't have. Must instead degrade to the session-relative
    tier, named speed_out_of_bins (not bin_fabricated: the bin IS
    genuinely measured, just at the wrong speed for this sample)."""
    from pipeline.stages import s10d2_grip_anchor
    import grip_anchor as ga
    from friction_envelope import FrictionBin

    far_bin = FrictionBin(
        speed_center_mps=40.0, combined_g_p95=1.3, lat_max_g=1.3,
        accel_max_g=0.35, brake_max_g=0.62, sample_count=41, confidence=1.0,
    )

    class _Envelope:
        friction_bins = [far_bin]

    class _FullFriction:
        """A real, healthy friction model -- everything downstream of the
        bin-distance check must pass, so the guard is the ONLY thing
        standing between this input and a false physics-tier reading."""
        exponent = 2.0
        exponent_source = "fitted"

        def lateral_max(self, speed_mps):
            return 20.0

        def traction_max(self, speed_mps):
            return 20.0

        def braking_max(self, speed_mps):
            return 20.0

    a_lat_g = 0.9
    v_full = 25.0                        # constant "Speed (m/s)" in _lap_frame
    kappa = (a_lat_g * 9.80665) / (v_full ** 2)   # makes trust_ratio exactly 1.0
    curvature_profile = pd.DataFrame({
        "distance_m": np.linspace(0.0, 1200.0, 400),
        "curvature_1pm": np.full(400, kappa),
    })

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 5.0}]
    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps = {1: _lap_frame(a_lat_g=a_lat_g)}

    out = s10d2_grip_anchor.run_grip_anchor(
        metrics, corners, laps,
        friction_model=_FullFriction(),
        friction_envelope=_Envelope(),
        curvature_profile=curvature_profile,
    )
    assert out[0]["grip_anchor_tier"] == ga.TIER_DRIVER_BEST_SESSION
    assert out[0]["grip_anchor_reason"] == ga.REASON_SPEED_OUT_OF_BINS
    assert out[0]["grip_anchor_pct"] == pytest.approx(100.0)   # only lap, is its own session best


def _make_pipeline_csv(tmp_path, n_laps=3):
    """Minimal RaceChrono-style CSV, same column shape as the fixture in
    test_grip_pipeline.py / test_pipeline_racing_line_trigger.py, which is
    already proven to clear column discovery and reach the friction/grip
    stages of ``pipeline.run_full_analysis``."""
    rng = np.random.default_rng(7)
    n_per_lap = 150
    lap_length = 500.0
    frames = []
    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        frames.append(pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.4, n_per_lap),
        }))
    csv_path = tmp_path / "grip_anchor_wiring_test.csv"
    pd.concat(frames, ignore_index=True).to_csv(csv_path, index=False)
    return csv_path


def test_orchestrator_calls_grip_anchor_with_the_per_lap_metrics_and_friction_model(tmp_path):
    """Prove the 10d2 stage is wired into the LIVE orchestrator execution
    path by observing a real invocation during an actual pipeline run --
    not by grepping source text for the stage's name, which would pass even
    if the call sat in dead code (a reviewer concern on this branch).

    Corner DETECTION on a small synthetic CSV isn't reliable enough to
    assert on deterministically, so ``run_per_lap_corner_metrics`` is
    patched to hand back a fixed, non-empty per-lap-corner-metrics list --
    that's the value the orchestrator's own gate (``if _plcm:``) reacts to,
    and it sits upstream of, and independent from, the wiring under test.
    ``run_grip_anchor`` itself is spied on (side effect: pass its input
    through unchanged, matching its documented mutate-in-place-and-return
    contract) so the rest of the pipeline still completes normally.
    """
    csv_path = _make_pipeline_csv(tmp_path)
    fixed_plcm = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 24.0},
    ]

    import pipeline

    with (
        patch(
            "pipeline.stages.s10b_corners.run_per_lap_corner_metrics",
            return_value=fixed_plcm,
        ),
        patch(
            "pipeline.stages.s10d2_grip_anchor.run_grip_anchor",
            side_effect=lambda plcm, *a, **k: plcm,
        ) as spy,
    ):
        summary = pipeline.run_full_analysis(str(csv_path), {})

    spy.assert_called_once()
    args, kwargs = spy.call_args
    assert args[0] == fixed_plcm, (
        "the stage must receive the real per-lap corner metrics list, not a stub"
    )
    assert kwargs.get("friction_model") == summary.get("friction_model"), (
        "the stage must receive the pipeline's live friction model"
    )
    # The (pass-through) result must actually land back in the summary --
    # proving the call sits on the path that feeds summary, not a side branch.
    assert summary["per_lap_corner_metrics"] == fixed_plcm


def test_grip_anchor_failure_does_not_discard_the_per_lap_corner_metrics(tmp_path):
    """Regression for a Critical review finding: the wiring used to rebind
    ``_plcm`` in place from ``_safe_step``'s result. Since ``_safe_step``
    returns ``(None, err)`` on ANY exception, a failure inside
    ``run_grip_anchor`` turned ``_plcm`` into ``None`` and then, at
    ``per_lap_corner_metrics = _plcm or []``, into an empty list -- silently
    discarding step 10d's brake points, apex/entry/exit speeds and every
    other substantive field, even though none of that data has anything to
    do with grip anchoring and 10d itself succeeded.

    The grip anchor is decoration on top of 10d's metrics, not their source:
    a failure here must degrade to the unanchored metrics, never delete
    them. This drives the real orchestrator with run_grip_anchor patched to
    raise, and asserts step 10d's substantive data survives intact.
    """
    csv_path = _make_pipeline_csv(tmp_path)
    fixed_plcm = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 24.0},
    ]

    import pipeline

    with (
        patch(
            "pipeline.stages.s10b_corners.run_per_lap_corner_metrics",
            return_value=fixed_plcm,
        ),
        patch(
            "pipeline.stages.s10d2_grip_anchor.run_grip_anchor",
            side_effect=RuntimeError("boom: simulated grip-anchor failure"),
        ),
    ):
        summary = pipeline.run_full_analysis(str(csv_path), {})

    got = summary["per_lap_corner_metrics"]
    assert len(got) == 2, (
        "a grip-anchor failure must not change how many corner-lap metrics survive"
    )
    assert [m.get("apex_speed_mps") for m in got] == [25.0, 24.0], (
        "step 10d's substantive fields must survive a grip-anchor failure untouched"
    )
    assert [m.get("lap_number") for m in got] == [1, 2]
    assert [m.get("corner_id") for m in got] == [1, 1]

    # The failure must be recorded, not swallowed silently.
    assert "10d2_grip_anchor" in summary["steps_failed"]
    assert "10d2_grip_anchor" in summary["errors"]

    # And the metrics must simply lack the anchor -- not carry fabricated
    # values -- when the stage that would set them blew up.
    for m in got:
        assert m.get("grip_anchor_tier") is None
        assert m.get("grip_anchor_pct") is None
