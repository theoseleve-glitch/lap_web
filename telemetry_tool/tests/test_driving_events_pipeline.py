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
# Task 12 — throttle onset: one threshold per corner, not one per lap
# ══════════════════════════════════════════════════════════════════
#
# The defect: `throttle_onset_m` used to be the first post-apex sample above
# THIS LAP'S OWN apex speed + 0.5 m/s. Because dv/ds = a/v on a constant-
# acceleration exit, a lap carrying MORE apex speed needs MORE distance to
# gain that same 0.5 m/s -- so the faster lap's onset was reported LATER and
# the metric was anti-correlated with corner performance. The threshold is
# now per-corner and session-fixed.

_ONSET_ACCEL_MPS2 = 3.0
_ONSET_APEX_M = 150.0
_ONSET_CRUISE_MPS = 30.0
_ONSET_LAP_M = 600.0
_ONSET_STEP_M = 0.5


def _exit_lap(apex_speed_mps):
    """A lap frame whose speed dips to `apex_speed_mps` at `_ONSET_APEX_M`
    and accelerates out of it at a constant `_ONSET_ACCEL_MPS2`.

    ``v(s) = sqrt(v_apex^2 + 2*a*|s - s_apex|)`` is the real shape of a
    constant-acceleration exit, and using it rather than a straight line is
    load-bearing: it is what makes the removed per-lap rule measurably
    invert, so this fixture actually exhibits the defect being fixed.
    """
    d = np.arange(0.0, _ONSET_LAP_M, _ONSET_STEP_M)
    v = np.minimum(
        _ONSET_CRUISE_MPS,
        np.sqrt(apex_speed_mps ** 2
                + 2 * _ONSET_ACCEL_MPS2 * np.abs(d - _ONSET_APEX_M)),
    )
    return pd.DataFrame({
        "Distance (m)": d,
        "distance_norm": d / _ONSET_LAP_M,
        "Speed (m/s)": v,
    })


def _onsets_for(apex_speeds, corners=None):
    """Run the real two-pass derivation over one synthetic lap per entry in
    `apex_speeds`, all through the same corner. Returns {lap_number: metric}.
    """
    from pipeline.stages import s10b_corners as s10b

    corners = corners or [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps, metrics, pending = {}, {}, []
    for lap_number, apex in enumerate(apex_speeds, start=1):
        lap_df = _exit_lap(apex)
        laps[lap_number] = lap_df
        m = dict(lap_number=lap_number, corner_id=1,
                 s_start=corners[0]["s_start"], s_end=corners[0]["s_end"])
        apex_idx = s10b._enrich_corner_telemetry(m, lap_df)
        metrics[lap_number] = m
        pending.append((lap_number, m, apex_idx))
    s10b._assign_throttle_onsets(pending, laps, corners)
    return metrics


def _onset_under_the_removed_rule(lap_df, apex_idx):
    """The rule this task deleted, reproduced verbatim so the fixture can be
    shown to exhibit the defect. This is a fixture property, not a second
    implementation of anything that ships -- the code it mirrors no longer
    exists, so it cannot drift out of step with production."""
    v = lap_df["Speed (m/s)"].values
    d = lap_df["Distance (m)"].values
    for k in range(apex_idx + 1, min(apex_idx + 50, len(v) - 2)):
        if v[k] > v[apex_idx] + 0.5 and v[k + 1] > v[k]:
            return float(d[k])
    return None


def test_the_removed_onset_rule_really_did_report_the_faster_lap_as_later():
    """Guards the FIXTURE, not the fix. Every assertion in the next test is
    worthless if these three laps do not actually exhibit the inversion, so
    prove it here: under the removed per-lap rule, onset RISES with apex
    speed -- the faster the lap, the later it is reported."""
    from pipeline.stages import s10b_corners as s10b

    old = []
    for apex in (14.0, 17.0, 20.0):
        lap_df = _exit_lap(apex)
        m = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        apex_idx = s10b._enrich_corner_telemetry(m, lap_df)
        old.append(_onset_under_the_removed_rule(lap_df, apex_idx))

    assert None not in old
    assert old[0] < old[1] < old[2], (
        f"the fixture does not exhibit the defect: onsets {old} do not rise "
        f"with apex speed under the removed rule")


def test_the_onset_threshold_is_session_fixed_so_the_faster_lap_is_earlier():
    """Three laps, apex speeds 14 / 17 / 20 m/s through one corner.

    The session-fixed threshold is median(14, 17, 20) + 0.5 = 17.5 m/s, so
    every lap is measured against the SAME absolute speed and each onset is
    analytically predictable from v(s) = sqrt(v_apex^2 + 2*a*(s - s_apex)).
    Pinning all three to that one number is what proves a single shared
    threshold governed them -- a per-lap threshold cannot produce this set.
    """
    import driving_events as de

    metrics = _onsets_for([14.0, 17.0, 20.0])
    onsets = [metrics[i]["throttle_onset_m"] for i in (1, 2, 3)]
    assert all(m["throttle_onset_status"] == de.ONSET_MEASURED
               for m in metrics.values())

    # THE PROPERTY: faster apex -> earlier onset. The exact inversion of what
    # the removed rule produced (previous test).
    assert onsets[2] < onsets[1] < onsets[0], (
        f"onset must fall as apex speed rises, got {onsets}")

    # And each one lands on the 17.5 m/s crossing, within one sample.
    threshold = 17.5
    for apex, onset in zip((14.0, 17.0, 20.0), onsets):
        gain = max(threshold ** 2 - apex ** 2, 0.0)
        expected = _ONSET_APEX_M + gain / (2 * _ONSET_ACCEL_MPS2)
        assert abs(onset - expected) <= _ONSET_STEP_M, (
            f"apex {apex}: onset {onset} is not the 17.5 m/s crossing "
            f"(expected ~{expected})")


def _slow_exit_lap():
    """Speed sits at 10 m/s from the corner all the way to 260 m, then rises.
    The only crossing of a ~10.5 m/s threshold is at ~260 m -- past a
    neighbouring corner at 250 m, and inside the search window without one.
    """
    d = np.arange(0.0, _ONSET_LAP_M, _ONSET_STEP_M)
    v = np.full_like(d, _ONSET_CRUISE_MPS)
    v[(d >= 100.0) & (d < 260.0)] = 10.0
    tail = d >= 260.0
    v[tail] = np.minimum(_ONSET_CRUISE_MPS, 10.0 + 0.2 * (d[tail] - 260.0))
    return pd.DataFrame({
        "Distance (m)": d,
        "distance_norm": d / _ONSET_LAP_M,
        "Speed (m/s)": v,
    })


def _run_onset_pass(lap_dfs, corners):
    from pipeline.stages import s10b_corners as s10b

    laps, metrics, pending = {}, {}, []
    for lap_number, lap_df in enumerate(lap_dfs, start=1):
        laps[lap_number] = lap_df
        m = dict(lap_number=lap_number, corner_id=1,
                 s_start=corners[0]["s_start"], s_end=corners[0]["s_end"])
        apex_idx = s10b._enrich_corner_telemetry(m, lap_df)
        metrics[lap_number] = m
        pending.append((lap_number, m, apex_idx))
    s10b._assign_throttle_onsets(pending, laps, corners)
    return metrics


def test_the_onset_search_stops_at_the_next_corner():
    """The bound is geometric, not a sample count.

    Identical telemetry, identical threshold; the ONLY difference is whether
    a neighbouring corner starts at 250 m. With one, the crossing at ~260 m
    is inside the NEXT corner and is not this corner's exit at all, so the
    scan must refuse rather than report it.
    """
    import driving_events as de

    lone = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    with_neighbour = lone + [{"corner_id": 2, "s_start": 250.0, "s_end": 300.0}]
    laps = [_slow_exit_lap(), _slow_exit_lap()]

    free = _run_onset_pass(laps, lone)[1]
    bounded = _run_onset_pass(laps, with_neighbour)[1]

    assert free["throttle_onset_status"] == de.ONSET_MEASURED
    # threshold = median apex + 0.5 = 10.5 m/s, reached 2.5 m into the
    # 0.2 m/s-per-metre ramp that starts at 260 m.
    assert free["throttle_onset_m"] == pytest.approx(262.5, abs=_ONSET_STEP_M)

    assert bounded["throttle_onset_m"] is None
    assert bounded["throttle_onset_status"] == de.ONSET_NO_SPEED_CROSSING


def test_a_corner_lap_whose_scan_found_nothing_is_reported_not_dropped():
    """The metric row survives with a named reason. Dropping it would remove
    the lap from the pool the per-corner reference is a minimum over --
    censoring the reference toward the laps whose scan happened to succeed.
    """
    import driving_events as de

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0},
               {"corner_id": 2, "s_start": 250.0, "s_end": 300.0}]
    metrics = _run_onset_pass([_slow_exit_lap()], corners)

    assert set(metrics) == {1}, "the corner-lap disappeared"
    assert metrics[1]["throttle_onset_m"] is None
    assert metrics[1]["throttle_onset_status"] in de.ONSET_REFUSAL_REASONS


def test_a_corner_too_short_to_hold_an_apex_names_its_own_reason():
    """`onset_no_apex` is reserved for exactly this: the scan had no start
    point. It must not be reported as `onset_no_speed_crossing`, which would
    send someone hunting a driving problem in a geometry problem."""
    import driving_events as de

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 100.6}]
    metrics = _run_onset_pass([_exit_lap(14.0)], corners)

    assert metrics[1]["throttle_onset_m"] is None
    assert metrics[1]["throttle_onset_status"] == de.ONSET_NO_APEX


def test_the_onset_search_limit_is_the_tighter_of_the_two_bounds():
    from pipeline.stages import s10b_corners as s10b

    corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}   # 100 m long

    # No neighbour: s_end + one corner length.
    assert s10b._onset_search_limit_m(corner, [corner]) == pytest.approx(300.0)

    # A near neighbour wins over s_end + length.
    near = [corner, {"corner_id": 2, "s_start": 250.0, "s_end": 300.0}]
    assert s10b._onset_search_limit_m(corner, near) == pytest.approx(250.0)

    # A far neighbour does not: s_end + length still wins.
    far = [corner, {"corner_id": 2, "s_start": 500.0, "s_end": 550.0}]
    assert s10b._onset_search_limit_m(corner, far) == pytest.approx(300.0)

    # A corner BEHIND this one is not a bound at all.
    behind = [corner, {"corner_id": 0, "s_start": 10.0, "s_end": 50.0}]
    assert s10b._onset_search_limit_m(corner, behind) == pytest.approx(300.0)

    # Degenerate geometry has no search window, and says so rather than
    # guessing a span.
    assert s10b._onset_search_limit_m(
        {"corner_id": 1, "s_start": 200.0, "s_end": 200.0}, []) is None
    assert s10b._onset_search_limit_m(
        {"corner_id": 1, "s_start": "x", "s_end": 200.0}, []) is None


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

# MEASURED: 143 events. Catches the "events collapse to 4" mutation.
# With four detectors over >= 24 corner-laps, and the two reference-comparison
# detectors structurally able to fire on up to 8 of every 9 laps per corner
# (only the record-holding lap is silent), a functioning session cannot come
# back with a single-digit event count. 30 keeps ~4.7x headroom under the
# measured value while being ~7x above the collapse case.
_MIN_EVENTS = 30

# MEASURED: 143/143 = 100% of events are validity="measured".
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

# MEASURED: 104 of 143 events carry a time_cost_s (over_slowing +
# late_throttle; re_braking and envelope_under_use carry None by design).
# Catches "every time_cost_s = None". time_cost_s is the ranking key -- it
# is the entire reason the ranked read surface exists -- so a session that
# produces events but no costs has silently lost the product feature while
# staying green. 20 leaves ~5x headroom.
#
# Task 12 note: a `late_throttle` event whose onset was NOT measurable
# carries no cost by construction (a not_measurable event may not carry
# numbers at all), so this floor is also the guard against the onset
# derivation degrading wholesale into refusals. On this fixture 0 of 72
# corner-laps refuse, so all 60 late_throttle events are costed.
_MIN_COSTED_EVENTS = 20

# MEASURED: median cost 0.163 s, max 0.885 s.
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

# ── Task 12: the anti-inversion floors ────────────────────────────────────
#
# These two exist because `late_throttle` shipped for a while on an onset
# metric that was anti-correlated with corner performance: the threshold was
# THIS LAP'S OWN apex speed + 0.5 m/s, so a faster lap had to reach a higher
# ABSOLUTE speed before it tripped and its onset came out LATER. Nothing in
# the gate above could see it -- every count, share, spread and cost bound
# was satisfied while the detector told the driver they were late on throttle
# precisely when they went fast. A defect that a full-strength gate cannot
# observe needs its own assertion, measured on the same real fixture.
#
# MEASURED (after the fix): corr(corner_time_s, throttle_onset_m) is POSITIVE
# on all 8 corners -- a slower pass through a corner is reported with a LATER
# onset, which is the only orientation that makes the metric mean anything.
# Range +0.185 (corner 7) to +0.925 (corner 1). BEFORE the fix it was
# NEGATIVE on 6 of 8. A floor of 2 tolerates one or two genuinely
# uninformative corners (corner 7's +0.185 is already nearly noise, and its
# sign could flip on another session) while failing instantly on the systemic
# inversion, which drives 6+ corners negative at once.
_MAX_NEGATIVELY_CORRELATED_CORNERS = 2

# MEASURED (after the fix): median within-corner corr(apex_speed_mps,
# throttle_onset_m) = -0.683; before, +0.552. The sign is the whole claim:
# carrying MORE apex speed must not push the reported onset LATER. -0.20 sits
# far below the measured -0.683 and far above the +0.552 it exists to catch,
# and deliberately does not pin the strength -- a session where the driver's
# apex speeds barely vary would legitimately show a weak correlation.
_MAX_MEDIAN_APEX_ONSET_CORR = -0.20


def _pearson(xs, ys):
    """Pearson r, or None when it is undefined (too few points, or either
    series constant -- np.corrcoef returns NaN there and a NaN silently
    defeats every comparison it is fed to)."""
    if len(xs) < 3:
        return None
    if np.std(xs) == 0 or np.std(ys) == 0:
        return None
    r = float(np.corrcoef(xs, ys)[0, 1])
    return r if np.isfinite(r) else None


def _assert_onset_is_not_inverted(plcm):
    """`throttle_onset_m` must move WITH corner time and AGAINST apex speed.

    See _MAX_NEGATIVELY_CORRELATED_CORNERS / _MAX_MEDIAN_APEX_ONSET_CORR for
    the measured basis. Correlations are computed per corner and only over
    corner-laps whose onset was actually measured -- a refused onset is not a
    late one, and folding it in as a missing value would be a made-up number.
    """
    rows = [m for m in plcm if isinstance(m, dict)]
    by_corner = {}
    for m in rows:
        onset = m.get("throttle_onset_m")
        apex = m.get("apex_speed_mps")
        ctime = m.get("corner_time_s")
        if None in (onset, apex, ctime):
            continue
        if not all(np.isfinite(v) for v in (onset, apex, ctime)):
            continue
        by_corner.setdefault(m.get("corner_id"), []).append((onset, apex, ctime))

    apex_corrs, negative_corners, n_time_corrs = [], [], 0
    for cid, vals in by_corner.items():
        onsets = [v[0] for v in vals]
        apexes = [v[1] for v in vals]
        times = [v[2] for v in vals]
        ra = _pearson(apexes, onsets)
        if ra is not None:
            apex_corrs.append(ra)
        rt = _pearson(times, onsets)
        if rt is not None:
            n_time_corrs += 1
            if rt < 0:
                negative_corners.append((cid, round(rt, 3)))

    # Below this the measurement itself is not meaningful, and silently
    # passing on two corners would be the "assertion that cannot fail" this
    # gate exists to avoid.
    assert n_time_corrs >= 4 and len(apex_corrs) >= 4, (
        f"only {n_time_corrs}/{len(apex_corrs)} corners produced a usable "
        f"onset correlation -- too few to judge the inversion")

    assert len(negative_corners) <= _MAX_NEGATIVELY_CORRELATED_CORNERS, (
        f"corr(corner_time, throttle_onset) is NEGATIVE on "
        f"{len(negative_corners)}/{n_time_corrs} corners {negative_corners} "
        f"-- a SLOWER pass through a corner is being reported with an EARLIER "
        f"throttle onset. That is the pre-2026-08-05 per-lap-threshold "
        f"inversion returning, not driving.")

    median_apex_corr = sorted(apex_corrs)[len(apex_corrs) // 2]
    assert median_apex_corr <= _MAX_MEDIAN_APEX_ONSET_CORR, (
        f"median within-corner corr(apex_speed, throttle_onset) is "
        f"{median_apex_corr:+.3f} (must be <= "
        f"{_MAX_MEDIAN_APEX_ONSET_CORR}) -- carrying more apex speed is "
        f"pushing the reported onset LATER, i.e. the metric is penalising "
        f"the driver for going fast")


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

    # ── Task 12: the onset derivation ran, and named every refusal ────
    # Wiring AND vocabulary in one assertion: a corner-lap with no status at
    # all means `_assign_throttle_onsets` never reached it (late_throttle
    # would silently read "insufficient" for that lap), and a status outside
    # the closed set means some caller invented a reason string.
    statuses = Counter(m.get("throttle_onset_status")
                       for m in plcm if isinstance(m, dict))
    stray = {s: n for s, n in statuses.items() if s not in de.ONSET_STATUSES}
    assert not stray, (
        f"{sum(stray.values())} corner-laps carry no / an unknown "
        f"throttle_onset_status: {stray}")

    # ── Task 12: the onset metric is not anti-correlated with pace ────
    _assert_onset_is_not_inverted(plcm)

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


@pytest.fixture(scope="module")
def _real_summary(tmp_path_factory):
    """Run the real pipeline ONCE for this module.

    Module-scoped because it costs minutes, and the mutation battery below
    replays two dozen deliberately degraded copies of its output against the
    SHIPPED gate helper -- re-running the pipeline per mutation would turn a
    4-minute test into an hour.

    Track-registry isolation is done by hand rather than through
    `_isolated_track_registry` only because that fixture is function-scoped
    (it uses tmp_path/monkeypatch) and pytest forbids a module-scoped fixture
    from depending on one. Same effect and same reason: keep the pipeline's
    track-registration write off the tracked models/tracks.json. Restored in
    a `finally` so a pipeline failure cannot leak the patch into later tests.
    """
    if not os.path.exists(_REAL_CSV):
        pytest.skip("real fixture absent")

    import track_detection
    from pipeline import run_full_analysis

    fake_path = tmp_path_factory.mktemp("tracks") / "tracks_isolated.json"
    original = track_detection._default_db_path
    track_detection._default_db_path = lambda: fake_path
    try:
        return run_full_analysis(_REAL_CSV, {})
    finally:
        track_detection._default_db_path = original


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
def test_driving_events_on_real_kart_telemetry(_real_summary):
    """Acceptance: events are emitted in quantity, all four detectors fire,
    every event is measured, located and non-degenerate, and the costs are
    plausible both per-event and in bulk.

    MEASURED on this fixture: 72 corner-laps (9 laps x 8 corners), 143
    events, 100% validity="measured", all four capability values "detected",
    costs min 0.000 / median 0.163 / max 0.885 s.

    TASK 12 moved these numbers. Fixing `throttle_onset_m`'s per-lap
    threshold (see s10b_corners._assign_throttle_onsets) changed the
    late_throttle count 59 -> 60 and hence events 142 -> 143 and costed
    events 103 -> 104, and the cost median 0.138 -> 0.163 s. No floor moved:
    every one of them still clears its bound by the same order of magnitude
    it was set with. The event mix is over_slowing 44, late_throttle 60,
    envelope_under_use 34, re_braking 5.

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
    summary = _real_summary
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
    print("onset status: "
          f"{Counter(m.get('throttle_onset_status') for m in summary['per_lap_corner_metrics'])}")


# ══════════════════════════════════════════════════════════════════
# Task 12 — the mutation battery. A bite-check, made permanent.
# ══════════════════════════════════════════════════════════════════
#
# A gate is only worth its runtime if it can FAIL. Fix round 1 found that the
# original body caught 1 of 16 deliberate degradations, and rewrote it; a
# later review re-verified the rewrite by replaying mutations by hand -- but
# that battery lived in a scratch script, so nothing in the repo stopped the
# gate being hollowed out again. This is that battery, committed.
#
# Each entry below takes the REAL pipeline summary and returns one
# deliberately degraded copy that a functioning gate MUST reject. They are
# replayed against `_assert_driving_events_gate` itself, not a copy of it, so
# they exercise exactly the assertions that ship.
#
# DELIBERATELY NOT INCLUDED: the calibration probes that sit exactly ON a
# floor by construction (31 events against a floor of 30, events on exactly 4
# corners against a floor of 4, costs at 0.99 s against a 1.0 s bound). Those
# measure where the gate's edge is, which is a review question; asserting they
# pass would freeze the floors against ever being tightened, and asserting
# they fail would be asserting something false.


def _replace(event, **kw):
    """`dataclasses.replace`, which RE-RUNS `__post_init__` -- so a mutation
    built this way is one the record itself considers structurally legal."""
    import dataclasses

    return dataclasses.replace(event, **kw)


def _force(event, **kw):
    """Mutate a frozen event BYPASSING `__post_init__` -- models the world
    where validation has been moved out of the dataclass, which is the only
    world in which the gate's own per-event checks have to do the work."""
    import copy

    clone = copy.copy(event)
    for k, v in kw.items():
        object.__setattr__(clone, k, v)
    return clone


def _summary_with(base, *, events=None, cap=None, plcm=None):
    return {
        "driving_events": base["driving_events"] if events is None else events,
        "driving_events_capability": (
            base["driving_events_capability"] if cap is None else cap),
        "per_lap_corner_metrics": (
            base["per_lap_corner_metrics"] if plcm is None else plcm),
    }


def _all_on_one_corner(base):
    """Every event moved to corner 1, keeping (type, lap, corner) unique so
    the duplicate check cannot fire first and mask the spread check."""
    out, seen = [], set()
    for i, e in enumerate(base["driving_events"]):
        if (e.event_type, e.lap_number, 1) in seen:
            out.append(_replace(e, corner_id=1, lap_number=100 + i))
            seen.add((e.event_type, 100 + i, 1))
        else:
            out.append(_replace(e, corner_id=1))
            seen.add((e.event_type, e.lap_number, 1))
    return out


def _onset_sign_flipped(base):
    """Reproduce the pre-2026-08-05 inversion's SIGNATURE exactly: within
    each corner, replace every onset with (C - onset). A pure reflection
    leaves the spread untouched and flips both correlations' signs, so this
    mutation degrades nothing the rest of the gate can see -- which is the
    entire point, since nothing else in the gate could see the real defect
    either."""
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    peak = {}
    for m in rows:
        v = m.get("throttle_onset_m")
        if v is not None:
            peak[m["corner_id"]] = max(peak.get(m["corner_id"], 0.0), v)
    for m in rows:
        v = m.get("throttle_onset_m")
        if v is not None:
            m["throttle_onset_m"] = 2 * peak[m["corner_id"]] - v
    return rows


def _flip_share(base, every):
    """Flip every `every`-th event to insufficient_samples."""
    import driving_events as de

    return [
        _replace(e, validity=de.VALIDITY_INSUFFICIENT_SAMPLES,
                 magnitude=None, time_cost_s=None) if i % every == 0 else e
        for i, e in enumerate(base["driving_events"])
    ]


def _one_of_each_type(base):
    import driving_events as de

    return [next(e for e in base["driving_events"] if e.event_type == t)
            for t in sorted(de.EVENT_TYPES)]


def _strip_onset_status(base):
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        m.pop("throttle_onset_status", None)
    return rows


def _invented_onset_status(base):
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        m["throttle_onset_status"] = "ok"
    return rows


def _constant_onset(base):
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        if m.get("throttle_onset_m") is not None:
            m["throttle_onset_m"] = 100.0
    return rows


# name -> builder(real summary) -> mutated summary. Kept as a dict of
# callables rather than pre-built objects because the real summary only
# exists once the module-scoped fixture has run.
_MUTATIONS = {
    # ── wholesale validity flips ──────────────────────────────────────
    "every event insufficient_samples (structurally legal form)":
        lambda b, de: _summary_with(b, events=[
            _replace(e, validity=de.VALIDITY_INSUFFICIENT_SAMPLES,
                     magnitude=None, time_cost_s=None)
            for e in b["driving_events"]]),
    "every event insufficient_samples (magnitudes kept, post_init bypassed)":
        lambda b, de: _summary_with(b, events=[
            _force(e, validity=de.VALIDITY_INSUFFICIENT_SAMPLES)
            for e in b["driving_events"]]),
    "every event not_measurable":
        lambda b, de: _summary_with(b, events=[
            _replace(e, validity=de.VALIDITY_NOT_MEASURABLE,
                     magnitude=None, time_cost_s=None)
            for e in b["driving_events"]]),
    "half the events flipped to insufficient (50% measured)":
        lambda b, de: _summary_with(b, events=_flip_share(b, 2)),
    "a quarter flipped to insufficient (75% measured)":
        lambda b, de: _summary_with(b, events=_flip_share(b, 4)),

    # ── the ranking key ───────────────────────────────────────────────
    "every time_cost_s = 0.0":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=0.0) for e in b["driving_events"]]),
    "every time_cost_s = None":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=None) for e in b["driving_events"]]),
    "costs uniformly 4.9 s":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=4.9) if e.time_cost_s is not None else e
            for e in b["driving_events"]]),
    "costs uniformly -0.4 s":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=-0.4) if e.time_cost_s is not None else e
            for e in b["driving_events"]]),

    # ── spread and quantity ───────────────────────────────────────────
    "no events at all":
        lambda b, de: _summary_with(b, events=[], cap={}),
    "events collapse to one per detector":
        lambda b, de: _summary_with(b, events=_one_of_each_type(b)),
    "all events from ONE corner (keys kept unique)":
        lambda b, de: _summary_with(b, events=_all_on_one_corner(b)),
    "all events from ONE corner (naive, duplicates)":
        lambda b, de: _summary_with(b, events=[
            _replace(e, corner_id=1) for e in b["driving_events"]]),
    "events on only 3 corners":
        lambda b, de: _summary_with(b, events=[
            e for e in b["driving_events"] if e.corner_id in (1, 2, 3)]),
    "corner detection regresses 8 -> 2":
        lambda b, de: _summary_with(
            b,
            plcm=[m for m in b["per_lap_corner_metrics"]
                  if m.get("corner_id") in (1, 2)],
            events=[e for e in b["driving_events"] if e.corner_id in (1, 2)]),
    "Task 10 dedupe regressed (every event 5x)":
        lambda b, de: _summary_with(b, events=b["driving_events"] * 5),

    # ── detectors and the capability record ───────────────────────────
    "only one detector fires (over_slowing)":
        lambda b, de: _summary_with(b, events=[
            e for e in b["driving_events"] if e.event_type == "over_slowing"]),
    "re_braking silenced (3 of 4 detectors fire)":
        lambda b, de: _summary_with(b, events=[
            e for e in b["driving_events"] if e.event_type != "re_braking"]),
    "all capability values = insufficient":
        lambda b, de: _summary_with(b, cap={
            k: de.CAPABILITY_INSUFFICIENT
            for k in b["driving_events_capability"]}),
    "all capability values = not_triggered":
        lambda b, de: _summary_with(b, cap={
            k: de.CAPABILITY_NOT_TRIGGERED
            for k in b["driving_events_capability"]}),
    "ONE capability degraded (re_braking insufficient)":
        lambda b, de: _summary_with(b, cap={
            **b["driving_events_capability"],
            "re_braking": de.CAPABILITY_INSUFFICIENT}),

    # ── per-event structure ───────────────────────────────────────────
    "every magnitude = 0.0":
        lambda b, de: _summary_with(b, events=[
            _replace(e, magnitude=0.0) for e in b["driving_events"]]),
    "every span collapsed to 0.0":
        lambda b, de: _summary_with(b, events=[
            _replace(e, s_norm_start=0.0, s_norm_end=0.0)
            for e in b["driving_events"]]),

    # ── Task 12: the throttle-onset derivation ────────────────────────
    "the onset inversion returns (sign of both correlations flipped)":
        lambda b, de: _summary_with(b, plcm=_onset_sign_flipped(b)),
    "onset stops discriminating (one constant per corner)":
        lambda b, de: _summary_with(b, plcm=_constant_onset(b)),
    "throttle_onset_status never written (second pass unwired)":
        lambda b, de: _summary_with(b, plcm=_strip_onset_status(b)),
    "throttle_onset_status invented outside the vocabulary":
        lambda b, de: _summary_with(b, plcm=_invented_onset_status(b)),
}


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
@pytest.mark.parametrize("mutation", sorted(_MUTATIONS))
def test_the_real_data_gate_rejects_each_deliberate_degradation(
    mutation, _real_summary,
):
    """Every mutation must make the SHIPPED gate helper raise.

    A green here is a failure report: it names a degradation the gate would
    ship without noticing.
    """
    import driving_events as de

    base = {
        "driving_events": _real_summary.get("driving_events") or [],
        "driving_events_capability": (
            _real_summary.get("driving_events_capability") or {}),
        "per_lap_corner_metrics": (
            _real_summary.get("per_lap_corner_metrics") or []),
    }
    mutated = _MUTATIONS[mutation](base, de)

    with pytest.raises(AssertionError):
        _assert_driving_events_gate(mutated)
