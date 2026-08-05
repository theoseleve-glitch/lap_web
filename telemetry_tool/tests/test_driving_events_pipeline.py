"""Driving events — schema, persistence, stage wiring and real-data acceptance."""
import os
from collections import Counter
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def test_driving_events_table_exists_with_the_expected_columns(test_db):
    cur = test_db.execute("SELECT * FROM driving_events LIMIT 0")
    cols = {d[0] for d in cur.description}

    for c in (
        "session_id", "lap_number", "corner_id", "event_type",
        "s_norm_start", "s_norm_end",
        "magnitude", "magnitude_unit",
        "time_cost_s", "validity", "reason",
        "n_samples_in_window", "evidence_json",
    ):
        assert c in cols, f"{c} missing from driving_events"


def test_driving_events_has_a_unique_key_so_reprocess_does_not_double(test_db):
    """Without this, every reprocess doubles the table."""
    row = dict(
        session_id="s1", lap_number=1, corner_id=1, event_type="over_slowing",
        s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4, magnitude_unit="m/s",
        time_cost_s=0.31, validity="measured", reason=None,
        n_samples_in_window=42, evidence_json="{}",
    )
    cols = ", ".join(row)
    binds = ", ".join(f":{k}" for k in row)
    sql = f"INSERT OR REPLACE INTO driving_events ({cols}) VALUES ({binds})"

    test_db.execute(sql, row)
    test_db.execute(sql, row)
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'"
    ).fetchone()[0]
    assert n == 1, "reprocess duplicated the row -- unique key missing"


def test_driving_events_is_registered_for_retention_and_gdpr():
    """Data that cannot be purged or exported is a compliance defect."""
    from tasks import retention_tasks
    import inspect
    from tasks import gdpr_tasks

    assert "driving_events" in retention_tasks._RAW_DATA_TABLES
    assert "driving_events" in inspect.getsource(gdpr_tasks)


def test_driving_events_is_registered_in_both_delete_cascade_registries():
    """A table missing from either registry leaves orphaned rows on SQLite
    (the FK there has no ON DELETE CASCADE) and under-counts every backend's
    delete-impact dry-run preview."""
    import inspect
    from web.repos.delete_cascade import CASCADE_CONFIG
    from web.repos import driver_repo

    assert "driving_events" in CASCADE_CONFIG["session"]["children"]
    assert "driving_events" in inspect.getsource(driver_repo.delete_driver_cascade)


def test_stage_returns_events_and_a_capability_record():
    from pipeline.stages import s10d3_driving_events

    n = 400
    d = np.linspace(0.0, 1200.0, n)
    def lap(v):
        return pd.DataFrame({
            "Distance (m)": d, "distance_norm": d / 1200.0,
            "Speed (m/s)": np.full(n, v),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
            "Longitudinal acceleration (G) *calc": np.zeros(n),
        })

    corners = [{"corner_id": 1, "s_start": 300.0, "s_end": 400.0}]
    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0,
         "corner_time_s": 10.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 70.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 12.5,
         "corner_time_s": 8.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 99.0},
    ]

    out = s10d3_driving_events.run_driving_events(
        metrics, corners, {1: lap(10.0), 2: lap(12.5)},
    )

    assert "events" in out and "capability" in out
    assert set(out["capability"]) == {
        "over_slowing", "late_throttle", "re_braking", "envelope_under_use"}
    # lap 1 was slower than the reference, so something must be said about it
    assert any(e.lap_number == 1 for e in out["events"])


def test_a_corner_with_no_reference_at_all_still_lets_reference_free_detectors_evaluate():
    """Fix round 1 regression: a corner where NO admissible lap ever produced
    a finite apex_speed_mps, corner_time_s or throttle_onset_m (a total
    reference gap) used to skip building ANY window for that corner --
    starving `re_braking`/`envelope_under_use`, which never read `reference`
    at all, of windows they had every field for. The reviewer's own example:
    a strong clean post-apex decel run plus a low grip_anchor_pct, but no
    apex speed / corner time / throttle onset anywhere.

    Both halves in the SAME scenario, per the fix request:
      (1) re_braking / envelope_under_use must NOT read "insufficient" --
          their own required fields (a_long_mps2+apex_idx, grip_anchor_pct)
          are present, so they must evaluate and fire here.
      (2) over_slowing / late_throttle must STILL read "insufficient", not
          "not_triggered" -- there is genuinely nothing to compare against,
          and that must not be reported as "compared, found nothing".
    """
    from pipeline.stages import s10d3_driving_events

    n = 400
    d = np.linspace(0.0, 1200.0, n)
    lap_df = pd.DataFrame({
        "Distance (m)": d, "distance_norm": d / 1200.0,
        "Speed (m/s)": np.full(n, 15.0),
        "Lateral acceleration (G) *calc": np.full(n, 0.9),
        # Strong, sustained deceleration across the WHOLE lap (well past the
        # -0.5 m/s^2 floor and the 3-sample run-length floor once masked to
        # the corner) so re_braking has a genuine event to find.
        "Longitudinal acceleration (G) *calc": np.full(n, -1.0),
    })
    corners = [{"corner_id": 1, "s_start": 300.0, "s_end": 400.0}]
    # Deliberately NO apex_speed_mps / corner_time_s / throttle_onset_m on
    # the only lap at this corner -- reference_by_corner[1] will be {}.
    metrics = [{"lap_number": 1, "corner_id": 1, "grip_anchor_pct": 40.0}]

    out = s10d3_driving_events.run_driving_events(metrics, corners, {1: lap_df})
    cap = out["capability"]

    # (1) reference-free detectors: not starved.
    assert cap["re_braking"] == "detected", cap
    assert cap["envelope_under_use"] == "detected", cap
    re_brake_events = [e for e in out["events"] if e.event_type == "re_braking"]
    envelope_events = [e for e in out["events"] if e.event_type == "envelope_under_use"]
    assert len(re_brake_events) == 1
    assert re_brake_events[0].magnitude == pytest.approx(9.80665, rel=1e-3)
    assert len(envelope_events) == 1
    assert envelope_events[0].magnitude == pytest.approx(40.0)

    # (2) reference-dependent detectors: honestly "insufficient", not a
    # silently-collapsed "not_triggered".
    assert cap["over_slowing"] == "insufficient", cap
    assert cap["late_throttle"] == "insufficient", cap
    assert not any(e.event_type in ("over_slowing", "late_throttle") for e in out["events"])


def test_stage_never_raises_on_malformed_input():
    from pipeline.stages import s10d3_driving_events

    for args in (
        ([], [], {}),
        ([None], [None], {1: None}),
        ([{"lap_number": None, "corner_id": None}], ["junk"], {1: pd.DataFrame()}),
    ):
        out = s10d3_driving_events.run_driving_events(*args)
        assert isinstance(out, dict)
        assert "events" in out and "capability" in out


@pytest.fixture
def _isolated_track_registry(tmp_path, monkeypatch):
    """Keep the pipeline's track-registration write off the tracked
    models/tracks.json -- see the parent branch's test-hygiene incident.

    Returns a `Path`, not a `str`. `_default_db_path` is annotated `-> Path`
    and `load_track_database` calls `path.exists()` on whatever it returns,
    so a `str` here made stage 05_detect_track raise
    `AttributeError: 'str' object has no attribute 'exists'`. That is
    swallowed by `pipeline/helpers.py:93`, so the isolation "worked" only by
    killing track detection outright -- every test using this fixture ran
    with `steps_failed == ['05_detect_track']` and `track_id='unknown_track'`.
    Verified during fix round 1 that correcting it leaves this module's
    driving-events output bit-identical (corner detection is purely
    geometric off lap 1 and never consults the registry). Matches the
    already-correct version at test_distance_frame.py:614.
    """
    import track_detection

    fake_path = tmp_path / "tracks_isolated.json"
    monkeypatch.setattr(track_detection, "_default_db_path", lambda: fake_path)
    return fake_path


def _write_synthetic_csv(tmp_path, n_laps=3):
    """Minimal RaceChrono-style CSV, same column shape as
    test_grip_anchor_pipeline.py's ``_make_pipeline_csv`` (already proven to
    clear column discovery and reach the friction/grip stages of
    ``pipeline.run_full_analysis``) -- copied rather than imported, since
    nothing in this test suite imports across test modules."""
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
    csv_path = tmp_path / "driving_events_wiring_test.csv"
    pd.concat(frames, ignore_index=True).to_csv(csv_path, index=False)
    return csv_path


def test_orchestrator_runs_the_driving_events_stage(_isolated_track_registry, tmp_path):
    """Behavioural: spy on the stage while driving the real orchestrator.

    Mirrors test_grip_anchor_pipeline.py's orchestrator spy exactly -- patch
    run_per_lap_corner_metrics to return a fixed non-empty list (synthetic-CSV
    corner detection is unreliable), then assert the stage under test was
    actually called. A source-grep would pass even if it were wired into dead
    code.
    """
    from unittest.mock import patch
    from pipeline.stages import s10b_corners, s10d3_driving_events
    import pipeline

    fixed = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0,
         "corner_time_s": 10.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 70.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 12.5,
         "corner_time_s": 8.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 99.0},
    ]
    csv_path = _write_synthetic_csv(tmp_path)

    with patch.object(s10b_corners, "run_per_lap_corner_metrics",
                      return_value=fixed), \
         patch.object(s10d3_driving_events, "run_driving_events",
                      wraps=s10d3_driving_events.run_driving_events) as spy:
        pipeline.run_full_analysis(str(csv_path), {})

    assert spy.call_count == 1, "the driving-events stage was never called"
    assert spy.call_args.args[0] == fixed


# ══════════════════════════════════════════════════════════════════
# Task 10 — persistence and the two read surfaces
# ══════════════════════════════════════════════════════════════════


def test_ranked_events_are_ordered_by_time_cost(test_db):
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=L, corner_id=C,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"apex_speed_mps": 10.0},
        )
        for (L, C, cost) in [(1, 1, 0.10), (7, 4, 0.885), (9, 1, 0.412)]
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=2)
    assert [round(g["time_cost_s"], 3) for g in got] == [0.885, 0.412]
    assert got[0]["lap_number"] == 7 and got[0]["corner_id"] == 4


def test_corner_consistency_reports_best_median_and_spread(test_db):
    from web.repos import events_repo
    import driving_events as de

    # corner 4 is inconsistent, corner 2 is tight
    rows = [(4, 0.0), (4, 0.45), (4, 0.89), (2, 0.0), (2, 0.05), (2, 0.09)]
    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=i + 1, corner_id=c,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        )
        for i, (c, cost) in enumerate(rows)
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    by_corner = {r["corner_id"]: r for r in
                 events_repo.get_corner_consistency(test_db, "s1")}
    assert by_corner[4]["spread_s"] > by_corner[2]["spread_s"]
    assert by_corner[4]["worst_s"] == pytest.approx(0.89)
    # Fix round 1 (IMPORTANT #2): median_s and best_s were previously
    # unpinned -- the reviewer swapped median(costs) for a hardcoded
    # 123.456 and best for -999.0 and this test still passed. sorted(corner
    # 4) = [0.0, 0.45, 0.89] -> median is the middle value, 0.45; sorted
    # (corner 2) = [0.0, 0.05, 0.09] -> median 0.05. best_s is min(costs)
    # for each corner: 0.0 in both cases here (not distinguishing, hence
    # the separate dedupe test below pins a best_s that isn't 0.0 too).
    assert by_corner[4]["median_s"] == pytest.approx(0.45)
    assert by_corner[2]["median_s"] == pytest.approx(0.05)
    assert by_corner[4]["best_s"] == pytest.approx(0.0)
    assert by_corner[2]["best_s"] == pytest.approx(0.0)


def test_corner_consistency_dedupes_a_lap_that_fired_multiple_detectors(test_db):
    """Fix round 1, IMPORTANT #1: over_slowing and late_throttle both set
    time_cost_s = corner_time - reference_corner_time for the SAME
    (lap, corner) -- see driving_events.py's _OverSlowing/_LateThrottle
    .detect. Two event rows for the same lap must count as ONE lap's gap,
    not two, or the median gets pulled toward whichever corner fired the
    most detectors.

    Concrete failure the reviewer caught: corner 4 with per-lap gaps
    [0.10, 0.50, 0.90], BOTH over_slowing and late_throttle firing on the
    lap that measured 0.10. Naive median-of-4-rows ([0.10, 0.10, 0.50,
    0.90]) gives (0.10+0.50)/2 = 0.30. The honest median-of-3-distinct-laps
    is 0.50 -- the middle value, since lap 1's duplicate must collapse to
    one observation before the median is taken.
    """
    from web.repos import events_repo
    import driving_events as de

    evs = [
        # Lap 1, corner 4: BOTH detectors fire with the same time_cost_s.
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.10,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m", time_cost_s=0.10,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=2, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.50,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=3, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    by_corner = {r["corner_id"]: r for r in
                 events_repo.get_corner_consistency(test_db, "s1")}
    assert by_corner[4]["median_s"] == pytest.approx(0.50), (
        "median must be computed over distinct (lap, corner) pairs, not "
        "event rows -- a duplicated lap must not shift it toward 0.30"
    )
    assert by_corner[4]["best_s"] == pytest.approx(0.10)
    assert by_corner[4]["worst_s"] == pytest.approx(0.90)
    assert by_corner[4]["spread_s"] == pytest.approx(0.80)


def test_ranked_events_dedupes_a_lap_that_fired_multiple_detectors(test_db):
    """Fix round 1, IMPORTANT #1, ranked-list half. Decision recorded in
    the fix report: the ranked list also dedupes to ONE entry per distinct
    (lap_number, corner_id) -- a driver wants N distinct places to work
    on, not the same corner twice under two labels."""
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=2, corner_id=1,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.50,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=10)
    assert len(got) == 2, "the two rows for (lap=1, corner=4) must collapse to one"
    keys = [(g["lap_number"], g["corner_id"]) for g in got]
    assert keys == [(1, 4), (2, 1)]


def test_ranked_events_limit_applies_after_dedup_not_before(test_db):
    """Fix round 1: a duplicate detector-pair must not consume two of the
    limit's slots. Corner 4/lap 1 fires two detectors (the highest cost,
    0.90) plus two other distinct (lap, corner) pairs -- asking for the
    top 2 distinct problems must return those 2 distinct pairs, not corner
    4/lap 1 twice with the third pair silently dropped."""
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=2, corner_id=1,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.50,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=3, corner_id=2,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.30,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=2)
    keys = [(g["lap_number"], g["corner_id"]) for g in got]
    assert keys == [(1, 4), (2, 1)], (
        "limit=2 must return 2 DISTINCT (lap, corner) pairs, not the same "
        "pair counted twice with the third pair dropped"
    )


def test_insert_is_idempotent_so_reprocess_does_not_double(test_db):
    from web.repos import events_repo
    import driving_events as de

    ev = de.DrivingEvent(
        event_type="over_slowing", lap_number=1, corner_id=1,
        s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0, magnitude_unit="m/s",
        time_cost_s=0.2, validity=de.VALIDITY_MEASURED, reason=None,
        n_samples_in_window=40, evidence={"x": 1},
    )
    events_repo.insert_driving_events(test_db, "s1", [ev])
    events_repo.insert_driving_events(test_db, "s1", [ev])
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'").fetchone()[0]
    assert n == 1


def test_insert_coerces_numpy_evidence_to_json_safe_types(test_db):
    """Resolution #4: evidence may contain numpy scalars. np.int64/np.bool_/
    np.float32 are NOT subclasses of Python's int/bool/float, so json.dumps
    raises TypeError on them directly (confirmed against this repo's own
    numpy build) -- and Phase 1 lost an entire corner_metrics write to the
    equivalent bind-time version of this bug because the exception was
    swallowed. If insert_driving_events doesn't coerce, this test raises
    TypeError instead of asserting anything -- that failure mode is itself
    the point being guarded against."""
    from web.repos import events_repo
    import driving_events as de
    import json

    ev = de.DrivingEvent(
        event_type="envelope_under_use", lap_number=1, corner_id=1,
        s_norm_start=0.2, s_norm_end=0.3, magnitude=float(np.float64(42.0)),
        magnitude_unit="pct", time_cost_s=None,
        validity=de.VALIDITY_MEASURED, reason=None,
        n_samples_in_window=40,
        evidence={
            "grip_anchor_pct": np.float64(42.0),
            "sample_count": np.int64(40),
            "clean": np.bool_(True),
            "floor_pct": np.float32(100.0),
        },
    )
    events_repo.insert_driving_events(test_db, "s1", [ev])
    test_db.commit()

    row = test_db.execute(
        "SELECT evidence_json FROM driving_events WHERE session_id='s1'"
    ).fetchone()
    parsed = json.loads(row["evidence_json"])
    assert parsed == {
        "grip_anchor_pct": 42.0, "sample_count": 40,
        "clean": True, "floor_pct": 100.0,
    }


# ── Endpoints: tenancy scoping (resolution #3) ─────────────────────
#
# Mirrors tests/test_idor_theoretical_user_corners.py's mock-based pattern
# exactly (that file's own header explains why: two confirmed cross-tenant
# blockers were routes that queried a child table by client-supplied
# session_id without first resolving ownership through
# models.get_session_by_id() on the RLS-scoped request connection). A
# session_id outside the caller's workspace must 404 and must NEVER reach
# events_repo.


@pytest.fixture
def data_v2_client():
    """Minimal Flask app with only the data_v2 blueprint -- no real DB."""
    from flask import Flask
    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    return app.test_client()


class TestDrivingEventsIdorGuard:

    @pytest.mark.parametrize("path", [
        "/api/v1/sessions/foreign-session/driving-events",
        "/api/v1/sessions/foreign-session/corner-consistency",
    ])
    def test_404_when_session_not_visible_to_caller(self, data_v2_client, path):
        """A non-owner (session invisible on the RLS-scoped connection, i.e.
        get_session_by_id returns None) must get 404, and events_repo must
        never be touched -- proves the guard fires before any query, not
        just that the final response happens to omit foreign data.

        events_repo's mocked return values are deliberately JSON-serializable
        (fix round 1, MINOR): a plain MagicMock return value makes a
        guard-removed regression fail on a 500 (Flask's jsonify choking on
        the MagicMock) before the load-bearing assert_not_called() ever
        runs, and before resp.status_code == 404 can distinguish "guard
        denied" from "guard skipped, then something else broke". With a
        real list here, removing the guard instead surfaces an explicit
        200-with-foreign-rows -- the actual thing this test exists to catch.
        """
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models, \
                patch("web.routes.data_v2.events_repo") as mock_events_repo:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None
            mock_events_repo.get_ranked_events.return_value = [
                {"lap_number": 1, "corner_id": 1, "time_cost_s": 0.5},
            ]
            mock_events_repo.get_corner_consistency.return_value = [
                {"corner_id": 1, "best_s": 0.0, "worst_s": 0.5,
                 "median_s": 0.25, "spread_s": 0.5},
            ]

            resp = data_v2_client.get(path)

            assert resp.status_code == 404, resp.get_data(as_text=True)
            body = resp.get_json()
            assert body["ok"] is False
            assert body["error"]["code"] == "NOT_FOUND"
            mock_events_repo.get_ranked_events.assert_not_called()
            mock_events_repo.get_corner_consistency.assert_not_called()

    def test_owner_gets_ranked_events(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models, \
                patch("web.routes.data_v2.events_repo") as mock_events_repo:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = {"session_id": "s1", "workspace_id": 1}
            mock_events_repo.get_ranked_events.return_value = [
                {"lap_number": 7, "corner_id": 4, "time_cost_s": 0.885},
            ]

            resp = data_v2_client.get("/api/v1/sessions/s1/driving-events?limit=5")

            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json()
            assert body["ok"] is True
            assert body["data"]["events"][0]["corner_id"] == 4
            mock_events_repo.get_ranked_events.assert_called_once_with(
                mock_db.return_value, "s1", limit=5,
            )

    def test_owner_gets_corner_consistency(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models, \
                patch("web.routes.data_v2.events_repo") as mock_events_repo:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = {"session_id": "s1", "workspace_id": 1}
            mock_events_repo.get_corner_consistency.return_value = [
                {"corner_id": 4, "best_s": 0.0, "worst_s": 0.89,
                 "median_s": 0.45, "spread_s": 0.89},
            ]

            resp = data_v2_client.get("/api/v1/sessions/s1/corner-consistency")

            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json()
            assert body["ok"] is True
            assert body["data"]["corners"][0]["spread_s"] == pytest.approx(0.89)
            mock_events_repo.get_corner_consistency.assert_called_once_with(
                mock_db.return_value, "s1",
            )


# ══════════════════════════════════════════════════════════════════
# Task 11 — real-data acceptance. This is the gate.
# ══════════════════════════════════════════════════════════════════

_REAL_CSV = "telemetry_tool/data/raw/OK_R4.csv"

# ── The floors this gate enforces ─────────────────────────────────────────
#
# Fix round 1 rewrote this section. The original gate asserted only
# "some events exist" plus a per-event vocabulary check, and a replay of
# that body against 16 deliberately mutated event lists caught exactly ONE
# of them: `run_registry -> ([], {})`. Everything else sailed through --
# every event flipped to `insufficient_samples`, every `time_cost_s` set to
# None, all 142 events collapsed onto one corner, only one of four
# detectors ever firing, the whole capability record degraded to
# "insufficient", Task 10's dedupe regressing so every event appeared five
# times. None of those is a subtle failure; all of them are things this
# phase exists to prevent, and none was asserted.
#
# The rule each constant below follows: anchor on the value MEASURED on this
# fixture, then sit far enough below it that honest track-to-track variation
# cannot trip the floor, while staying far above the collapse it exists to
# catch. That gap is wide here because the failure modes are systemic --
# they take the whole session to zero or to one, not to "somewhat less".
# Same reasoning, and the same shape, as
# test_grip_anchor_pipeline.py's _MIN_SESSION_ENVELOPE_SHARE.

# MEASURED: 72 corner-laps (8 detected corners x 9 admissible laps).
# 24 = 4 corners x 6 laps: the smallest session shape in which a per-corner
# "the driver's own best" reference means anything at all. Below 6 laps a
# per-corner best is one lucky pass rather than a reference, and below 4
# corners this is not a circuit. Every way this collapses is structural, not
# gradual -- corner detection regressing (8 -> 2 corners gives 18) or the
# admissible-lap set collapsing takes it well under 24 in one step -- so the
# 3x headroom below the measured 72 costs nothing in sensitivity.
_MIN_CORNER_LAPS = 24

# MEASURED: 142 events. Catches the "142 events collapse to 4" mutation.
# With four detectors over >= 24 corner-laps, and the two reference-comparison
# detectors structurally able to fire on up to 8 of every 9 laps per corner
# (only the record-holding lap is silent), a functioning session cannot come
# back with a single-digit event count. 30 keeps ~4.7x headroom under the
# measured value while being ~7x above the collapse case.
_MIN_EVENTS = 30

# MEASURED: 142/142 = 100% of events are validity="measured".
# Catches every wholesale validity flip. Deliberately NOT pinned at 1.0:
# the spec explicitly wants a future detector to be able to emit an honest
# `Insufficient` on windows where a channel is missing, and pinning 100%
# here would make that correct behaviour fail this gate. 0.80 still fails
# instantly on the mutation that matters -- a systemic flip drives the
# measured share to ZERO, because validity is decided per detector from
# session-wide inputs, not per event.
_MIN_MEASURED_SHARE = 0.80

# MEASURED: events on all 8 corners and all 9 laps.
# Catches "all events from one corner", "every corner_id = 1", and corner
# detection regressing 8 -> 2. Half the detected corners is the right order:
# a real session shows problems in several distinct places, and every
# collapse mode drives this to 1 or 2.
_MIN_DISTINCT_CORNERS = 4
_MIN_DISTINCT_LAPS = 4

# MEASURED: 103 of 142 events carry a time_cost_s (over_slowing +
# late_throttle; re_braking and envelope_under_use carry None by design).
# Catches "every time_cost_s = None". time_cost_s is the ranking key -- it
# is the entire reason the ranked read surface exists -- so a session that
# produces events but no costs has silently lost the product feature while
# staying green. 20 leaves ~5x headroom.
_MIN_COSTED_EVENTS = 20

# MEASURED: median cost 0.138 s, max 0.885 s.
# Catches "costs uniformly 4.9 s" -- which the old body's `<= 5.0` per-event
# bound waved straight through. A median corner-time gap above 1.0 s means
# the driver is losing ~8 s a lap to corner execution against their OWN best
# pass, which is a window/reference defect rather than driving. 1.0 s is
# ~7x the measured median and still far below the 4.9 s mutation.
_MAX_MEDIAN_COST_S = 1.0

# MEASURED: worst cost 0.885 s.
# Catches "every time_cost_s = 0.0", which every other cost assertion here
# waves through (a uniform zero is inside the per-event bounds and drags the
# median DOWN, not up). A session where no corner-lap is even a tenth of a
# second off the driver's own best at that corner does not mean a flawless
# driver -- it means the reference collapsed onto each lap individually, so
# every lap is trivially its own best and the whole comparison is vacuous.
# The plan's own composite-lap figure (0.121 s) is the smallest spread this
# session's geometry can produce. 0.10 s keeps ~9x headroom under 0.885.
_MIN_WORST_COST_S = 0.10


def _assert_driving_events_gate(summary):
    """The gate's assertion body, factored out so it can be replayed against
    deliberately mutated summaries.

    Fix round 1 exists because the previous body could not fail. Keeping the
    assertions callable means the bite-check exercises THE COMMITTED
    ASSERTIONS against each mutation, rather than a hand-copied lookalike
    that can drift from what actually ships. Returns a diagnostics dict for
    the caller to print.
    """
    import driving_events as de

    events = summary.get("driving_events") or []
    cap = summary.get("driving_events_capability") or {}
    plcm = summary.get("per_lap_corner_metrics") or []

    # ── the denominator ───────────────────────────────────────────────
    corner_laps = {(m.get("lap_number"), m.get("corner_id"))
                   for m in plcm if isinstance(m, dict)}
    assert len(corner_laps) >= _MIN_CORNER_LAPS, (
        f"only {len(corner_laps)} corner-laps reached the detectors "
        f"(floor {_MIN_CORNER_LAPS}); "
        f"{len({c for _, c in corner_laps})} corners x "
        f"{len({lap for lap, _ in corner_laps})} laps")

    # ── events exist, in quantity ─────────────────────────────────────
    assert events, "no driving events produced on real telemetry"
    assert len(events) >= _MIN_EVENTS, (
        f"only {len(events)} events over {len(corner_laps)} corner-laps "
        f"(floor {_MIN_EVENTS})")

    # ── the capability record: KEYS *and* VALUES ──────────────────────
    # The old body asserted only set(cap), which run_registry populates
    # unconditionally for every registered detector -- so it could never
    # observe a degraded value. The values are the part that carries
    # information.
    assert set(cap) == {"over_slowing", "late_throttle",
                        "re_braking", "envelope_under_use"}, cap
    assert all(v == de.CAPABILITY_DETECTED for v in cap.values()), (
        f"every detector must actually fire on this fixture, got {cap}")

    # ── all four detectors are represented in the events themselves ───
    types = {e.event_type for e in events}
    assert types == set(de.EVENT_TYPES), (
        f"expected all four detectors to emit, got {sorted(types)}")

    # ── honesty: the headline "everything is measured" claim ──────────
    n_measured = sum(1 for e in events if e.validity == de.VALIDITY_MEASURED)
    share = n_measured / len(events)
    assert share >= _MIN_MEASURED_SHARE, (
        f"only {n_measured}/{len(events)} = {share:.1%} of events are "
        f"'{de.VALIDITY_MEASURED}' (floor {_MIN_MEASURED_SHARE:.0%}); "
        f"validity mix {Counter(e.validity for e in events)}")

    # ── spread: not all one corner, not all one lap ───────────────────
    laps = {e.lap_number for e in events}
    corner_ids = {e.corner_id for e in events}
    assert len(laps) >= _MIN_DISTINCT_LAPS, f"events on only {len(laps)} laps: {laps}"
    assert len(corner_ids) >= _MIN_DISTINCT_CORNERS, (
        f"events on only {len(corner_ids)} corners: {sorted(corner_ids)} -- "
        f"a session's problems are not all in one place")

    # ── no duplicates ─────────────────────────────────────────────────
    # Each detector emits at most one event per window and windows are
    # unique per (lap, corner), so this is a structural invariant. It is
    # also the regression guard for Task 10's dedupe.
    keys = [(e.event_type, e.lap_number, e.corner_id) for e in events]
    assert len(set(keys)) == len(keys), (
        f"{len(keys) - len(set(keys))} duplicate (type, lap, corner) events")

    # ── per-event structure ───────────────────────────────────────────
    costs = []
    for e in events:
        # NOTE: these two are defence-in-depth, NOT teeth. DrivingEvent.
        # __post_init__ already raises on a bad event_type or validity and
        # run_registry swallows the construction failure, so a violating
        # event can never reach this loop. Kept because they are free and
        # would catch a future refactor that moves validation out of the
        # dataclass; do not mistake them for the assertions that bite.
        assert e.event_type in de.EVENT_TYPES
        assert e.validity in de.VALIDITIES

        # Spans must be real and ordered. Catches every span collapsing to
        # 0.0, which would make Phase 3 render every event at the start line.
        assert 0.0 <= e.s_norm_start < e.s_norm_end <= 1.0, (
            f"degenerate span [{e.s_norm_start}, {e.s_norm_end}] "
            f"(lap {e.lap_number} corner {e.corner_id})")

        if e.validity == de.VALIDITY_MEASURED:
            assert e.evidence, "a measured event must carry evidence"

            # Magnitude must clear the detector's own emission floor -- the
            # detector only emits ABOVE it, so this is structural. Catches
            # every magnitude being zeroed.
            if e.event_type == "over_slowing":
                assert e.magnitude > de.OVER_SLOWING_APEX_DEFICIT_FLOOR_MPS, (
                    f"over_slowing magnitude {e.magnitude} at or below its "
                    f"own emission floor")
            elif e.event_type == "late_throttle":
                assert e.magnitude > de.LATE_THROTTLE_ONSET_FLOOR_M, (
                    f"late_throttle magnitude {e.magnitude} at or below its "
                    f"own emission floor")

            if e.time_cost_s is not None:
                # Lower bound is an INVARIANT, not a taste: the reference
                # corner time is the minimum over admissible laps and is
                # self-inclusive (this window's own time is one of the
                # candidates -- see s10d3_driving_events' module docstring),
                # so the gap can never be negative. The old body's -0.5
                # tolerance let a uniformly-negative mutation pass.
                assert -1e-9 <= e.time_cost_s <= 5.0, (
                    f"implausible cost {e.time_cost_s}s "
                    f"(lap {e.lap_number} corner {e.corner_id})")
                costs.append(e.time_cost_s)

    # ── the ranking key actually exists and is plausible in bulk ──────
    assert len(costs) >= _MIN_COSTED_EVENTS, (
        f"only {len(costs)} of {len(events)} events carry a time_cost_s "
        f"(floor {_MIN_COSTED_EVENTS}) -- the ranked view has nothing to rank")
    median_cost = sorted(costs)[len(costs) // 2]
    assert median_cost <= _MAX_MEDIAN_COST_S, (
        f"median corner-time gap {median_cost:.3f}s exceeds "
        f"{_MAX_MEDIAN_COST_S}s -- that is a window/reference defect, "
        f"not driving")
    assert max(costs) >= _MIN_WORST_COST_S, (
        f"worst corner-time gap is only {max(costs):.3f}s (floor "
        f"{_MIN_WORST_COST_S}s) -- the per-corner reference has collapsed "
        f"onto each lap individually, making every comparison vacuous")

    return {
        "corner_laps": corner_laps, "events": events, "cap": cap,
        "costs": sorted(costs), "measured_share": share,
        "laps": laps, "corner_ids": corner_ids,
    }


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
def test_driving_events_on_real_kart_telemetry(_isolated_track_registry):
    """Acceptance: events are emitted in quantity, all four detectors fire,
    every event is measured, located and non-degenerate, and the costs are
    plausible both per-event and in bulk.

    MEASURED on this fixture: 72 corner-laps (9 laps x 8 corners), 142
    events, 100% validity="measured", all four capability values "detected",
    costs min 0.000 / median 0.138 / max 0.885 s.

    THE PROBE BASELINE, CORRECTED (fix round 1). The plan quotes
    "over_slowing 57%, late_throttle 68%, re_braking 7%" from
    `original_probe.py` variant C. Re-running that probe shows two of those
    three cannot be compared to this stage as-is:

      * `re_braking` was NEVER MEASURED by the probe. It gates on
        `if "accel_long_mps2" in lap.columns`, a pipeline-internal name that
        does not exist on the probe's raw-CSV frame (which carries
        `Longitudinal acceleration (G) *calc`), so its counter stayed 0 and
        the probe reports 0/54 = 0% in all three variants. The plan's "7%"
        came from a later note measuring the pipeline's own 8-corner
        windows, so agreeing with it is circular, not corroboration.
      * `over_slowing` (54) and `late_throttle` (40) are percentages of
        DIFFERENT denominators -- the probe divides late_throttle only by
        the windows where its onset proxy resolved.

    Restricted to the six corners the probe also found, this stage measures
    over_slowing 31/54 -- the probe's exact numerator AND denominator. So
    over_slowing's divergence is explained entirely by the two extra corners
    (ids 3 and 8) the pipeline detects and the probe did not; the probe
    feeds `detect_corners` a differently-preprocessed frame.
    `late_throttle` is NOT explained that way (45/54 here vs 27/54) and has
    a second, independent cause -- the two onset derivations differ. See the
    Task 11 report. Do not "fix" any of this by moving a threshold.

    `summary["driving_events"]` carries `driving_events.DrivingEvent`
    dataclass instances, not dicts: `orchestrator.py` assigns
    `run_driving_events(...)["events"]` straight through, and that is
    `run_registry`'s `list[DrivingEvent]`. Hence attribute access.
    """
    from pipeline import run_full_analysis

    summary = run_full_analysis(_REAL_CSV, {})
    d = _assert_driving_events_gate(summary)

    cl = d["corner_laps"]
    print(f"\ncorner-laps: {len(cl)} "
          f"({len({lap for lap, _ in cl})} laps x "
          f"{len({c for _, c in cl})} corners)")
    print(f"event types: {Counter(e.event_type for e in d['events'])}")
    print(f"capability:  {d['cap']}")
    print(f"measured:    {d['measured_share']:.1%} of {len(d['events'])} events")
    costs = d["costs"]
    print(f"cost s: min {costs[0]:.3f} median "
          f"{costs[len(costs) // 2]:.3f} max {costs[-1]:.3f}")
