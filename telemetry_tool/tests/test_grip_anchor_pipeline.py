"""Grip anchor — schema, stage wiring and persistence."""
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
    from pipeline.stages import s10d2_grip_anchor

    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 25.0},
    ]
    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps = {1: _lap_frame(a_lat_g=0.9), 2: _lap_frame(a_lat_g=1.1)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)

    assert len(out) == 2
    for m in out:
        assert "grip_anchor_tier" in m
        assert m["grip_anchor_tier"] is not None


def test_run_grip_anchor_refuses_rather_than_inventing_when_it_has_nothing():
    """No friction model, no usable laps: it must refuse, not fabricate."""
    import grip_anchor as ga
    from pipeline.stages import s10d2_grip_anchor

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]
    out = s10d2_grip_anchor.run_grip_anchor(metrics, [], {})

    assert out[0]["grip_anchor_tier"] == ga.TIER_REFUSED
    assert out[0]["grip_anchor_pct"] is None


def test_run_grip_anchor_never_raises_on_malformed_input():
    """This runs inside _safe_step, but a stage that throws loses the whole
    step; assert on RESULTS, not on the absence of an exception."""
    from pipeline.stages import s10d2_grip_anchor

    out = s10d2_grip_anchor.run_grip_anchor(
        [{"lap_number": None, "corner_id": None}], [], {},
    )
    assert len(out) == 1
    assert "grip_anchor_tier" in out[0]
