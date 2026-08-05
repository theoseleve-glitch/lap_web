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


_PRE_085_CORNER_METRICS_DDL = """
CREATE TABLE corner_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    lap_number INTEGER NOT NULL,
    corner_id INTEGER NOT NULL,
    brake_point_m REAL,
    brake_intensity REAL,
    entry_speed_mps REAL,
    apex_speed_mps REAL,
    exit_speed_mps REAL,
    throttle_onset_m REAL,
    exit_accel_mps2 REAL,
    grip_utilization REAL,
    time_loss_ms REAL,
    coaching_hint TEXT,
    UNIQUE(session_id, lap_number, corner_id)
);
"""


def test_ensure_schema_adds_the_anchor_columns_to_an_existing_database(tmp_path):
    """The four columns were added ONLY to db/schema.py's CREATE TABLE body,
    which is `CREATE TABLE IF NOT EXISTS` -- a no-op against a corner_metrics
    that already exists. db/migrate.py had zero grip_anchor references, so no
    already-deployed SQLite database ever got the columns, and USE_PG defaults
    to "0" (web/config.py:60) which makes SQLite the desktop, datalogger and
    local-dev default.

    The failure is silent AND destructive: ensure_schema returns SCHEMA_VERSION
    and logs success, then the INSERT (which names the four columns
    unconditionally) raises OperationalError, and all three writers swallow it
    -- so the session persists ZERO corner metrics. Brake points,
    entry/apex/exit speeds, time loss, coaching hints and the legacy
    grip_utilization are all lost, unrecoverable without reprocessing.

    This starts from a genuine pre-085 table (created here, then handed to the
    real ensure_schema) rather than a fresh database, because a fresh database
    takes the CREATE TABLE path and can never observe the bug.
    """
    import sqlite3

    from db.migrate import ensure_schema
    from db.queries import INSERT_CORNER_METRIC

    conn = sqlite3.connect(str(tmp_path / "pre085.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(_PRE_085_CORNER_METRICS_DDL)
    conn.commit()

    before = {r[1] for r in conn.execute("PRAGMA table_info(corner_metrics)")}
    assert "grip_anchor_tier" not in before, "premise broken: table is not pre-085"

    ensure_schema(conn)

    after = {r[1] for r in conn.execute("PRAGMA table_info(corner_metrics)")}
    for col in (
        "grip_anchor_tier", "grip_anchor_reason",
        "grip_anchor_pct", "grip_anchor_baseline_g",
    ):
        assert col in after, f"{col} missing after ensure_schema on a pre-085 DB"

    # The columns existing is not the deliverable -- the write surviving is.
    conn.execute(INSERT_CORNER_METRIC, {
        "session_id": "s1", "lap_number": 1, "corner_id": 1,
        "brake_point_m": None, "brake_intensity": None,
        "entry_speed_mps": None, "apex_speed_mps": 25.0, "exit_speed_mps": None,
        "throttle_onset_m": None, "exit_accel_mps2": None,
        "grip_utilization": 0.9, "time_loss_ms": 120.0,
        "coaching_hint": "brake later",
        "grip_anchor_tier": "session_envelope_ellipse_fitted",
        "grip_anchor_reason": None,
        "grip_anchor_pct": 131.07,
        "grip_anchor_baseline_g": 1.174,
    })
    conn.commit()

    row = conn.execute(
        "SELECT grip_anchor_tier, grip_anchor_pct, coaching_hint, grip_utilization "
        "FROM corner_metrics WHERE session_id='s1'"
    ).fetchone()
    assert row["grip_anchor_tier"] == "session_envelope_ellipse_fitted"
    assert row["grip_anchor_pct"] == pytest.approx(131.07)
    # The pre-existing columns are what the swallowed failure was destroying.
    assert row["coaching_hint"] == "brake later"
    assert row["grip_utilization"] == pytest.approx(0.9)
    conn.close()


def test_ensure_schema_is_idempotent_on_an_already_migrated_database(tmp_path):
    """ensure_schema runs on every connection open, so the ALTER block must
    survive being re-run against a database that already has the columns --
    the whole reason the surrounding Phase blocks swallow OperationalError."""
    import sqlite3

    from db.migrate import ensure_schema

    conn = sqlite3.connect(str(tmp_path / "twice.db"))
    conn.executescript(_PRE_085_CORNER_METRICS_DDL)
    conn.commit()

    ensure_schema(conn)
    ensure_schema(conn)          # must not raise

    cols = [r[1] for r in conn.execute("PRAGMA table_info(corner_metrics)")]
    assert cols.count("grip_anchor_tier") == 1
    conn.close()


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


def test_insert_corner_metrics_coerces_numpy_scalars_on_the_anchor_binds():
    """The four anchor binds skipped ``_safe_float`` while every neighbouring
    numeric at score_repo.py:96-109 went through it.

    ``grip_anchor.decide_anchor`` is public and its tier-2 path returns
    ``100.0 * abs(a_lat) / best``. In the pipeline ``a_lat`` comes out of a
    numpy array, so that expression is a ``numpy.float64``, not a ``float``.
    psycopg2 raises ``can't adapt type 'numpy.float64'`` on such a bind, and
    the exception is swallowed at all three writers (``s15_persist.py:243``
    logs a warning, ``pipeline_tasks.py:1161`` warns and rolls back,
    ``endurance_tasks.py:781`` catches bare and logs nothing). The result is
    that the session persists ZERO corner metrics -- brake points,
    entry/apex/exit speeds, time loss, coaching hints and the legacy
    ``grip_utilization`` all gone with it.

    ASSERTED ON THE BIND DICT, NOT THROUGH THE DATABASE, deliberately:
    sqlite3 accepts ``numpy.float64`` without complaint, so a round-trip
    through ``seeded_db`` would stay green with ``_safe_float`` removed and
    could not observe this defect at all. Only PostgreSQL rejects it, and the
    tests do not run against PostgreSQL.
    """
    from web.repos.score_repo import insert_corner_metrics

    class _CapturingConn:
        """Records the bind dict instead of executing it."""

        def __init__(self):
            self.binds = []

        def execute(self, sql, params):
            self.binds.append(params)

    conn = _CapturingConn()
    summary = {"per_lap_corner_metrics": [{
        "lap_number": 1, "corner_id": 1,
        "apex_speed_mps": np.float64(25.0),
        "grip_anchor_tier": "session_envelope_ellipse_fitted",
        "grip_anchor_reason": None,
        "grip_anchor_pct": np.float64(131.07),        # the real measured max
        "grip_anchor_baseline_g": np.float32(1.174),  # the real measured max
    }]}

    assert insert_corner_metrics(conn, "s1", summary) == 1
    bind = conn.binds[0]

    # `type(...) is float` on purpose: numpy.float64 is a SUBCLASS of float,
    # so isinstance() passes for it and would not catch this at all.
    assert type(bind["grip_anchor_pct"]) is float, (
        f"grip_anchor_pct bound as {type(bind['grip_anchor_pct']).__name__}, "
        f"which psycopg2 cannot adapt"
    )
    assert type(bind["grip_anchor_baseline_g"]) is float, (
        f"grip_anchor_baseline_g bound as "
        f"{type(bind['grip_anchor_baseline_g']).__name__}"
    )
    assert bind["grip_anchor_pct"] == pytest.approx(131.07)
    assert bind["grip_anchor_baseline_g"] == pytest.approx(1.174, abs=1e-6)

    # The two TEXT binds are deliberately left alone -- _safe_float would
    # turn the tier string into None and silently erase the label.
    assert bind["grip_anchor_tier"] == "session_envelope_ellipse_fitted"
    assert bind["grip_anchor_reason"] is None


def test_insert_corner_metrics_nulls_non_finite_anchor_values():
    """The other half of what ``_safe_float`` buys: a non-finite pct becomes
    NULL rather than a poisoned row. ``ellipse_fill_pct`` refuses to emit
    inf/NaN, but ``decide_anchor``'s tier-2 path divides by a session best it
    only checks for ``> 0``, and the column is DOUBLE PRECISION, so an
    infinity would be stored and then served."""
    from web.repos.score_repo import insert_corner_metrics

    class _CapturingConn:
        def __init__(self):
            self.binds = []

        def execute(self, sql, params):
            self.binds.append(params)

    conn = _CapturingConn()
    summary = {"per_lap_corner_metrics": [{
        "lap_number": 1, "corner_id": 1,
        "grip_anchor_tier": "refused",
        "grip_anchor_pct": np.float64("inf"),
        "grip_anchor_baseline_g": np.float64("nan"),
    }]}

    assert insert_corner_metrics(conn, "s1", summary) == 1
    bind = conn.binds[0]
    assert bind["grip_anchor_pct"] is None
    assert bind["grip_anchor_baseline_g"] is None


def _lap_frame(n=400, a_lat_g=0.9):
    d = np.linspace(0.0, 1200.0, n)
    return pd.DataFrame({
        "Distance (m)": d,
        "distance_norm": d / 1200.0,
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
    corner-lap needs to reach a SESSION-ENVELOPE tier is deliberately made healthy
    (a real friction model, a genuinely trusted lateral channel) so that,
    without the distance guard, it WOULD reach TIER_SESSION_ENVELOPE_ELLIPSE_FITTED
    off a bin measured 35 m/s away from its own apex speed -- reaching a
    session-envelope tier off a borrowed, distant bin would claim measured coverage
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
        standing between this input and a false session-envelope-tier reading."""
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


def test_run_grip_anchor_reaches_the_session_envelope_tier_off_a_dict_shaped_envelope():
    """Regression for the Task-10 real-data finding: the orchestrator persists
    ``summary["friction_envelope"]`` as ``FrictionEnvelope.to_dict()`` (a plain
    dict) and -- after the Task-10 fix -- still sometimes threads a dict form
    through, so ``run_grip_anchor`` must accept that shape, not only a live
    ``FrictionEnvelope`` object.

    Before the fix, ``_bin_for_speed``'s ``getattr(envelope, "friction_bins",
    None)`` silently read ``None`` off a dict (``getattr`` never sees dict
    keys), which made ``envelope_bin`` ``None`` for every corner-lap
    regardless of the envelope's real quality, and ``bin_is_measured``'s own
    ``getattr(bin_obj, "confidence")`` did the same to a dict-shaped bin. Both
    degraded silently to ``REASON_BIN_FABRICATED`` -- a confidently WRONG
    label, not a loud failure, which is why it went unnoticed until Task 10's
    real-pipeline run: on OK_R4.csv, every one of 72 corner-laps read
    ``bin_fabricated`` even though the friction envelope built from that
    session had 15/15 bins at ``confidence=1.0`` with 300-700+ samples each.

    Every existing test double for the envelope in this file (see
    ``_Envelope`` just above, and ``_FullFriction``'s siblings) is a
    hand-built object exposing ``.friction_bins`` as an attribute -- never
    the dict shape ``.to_dict()`` actually produces. That is precisely why
    those tests could not have caught this: none of them exercises the dict
    path at all. This test closes that gap by building a REAL
    ``FrictionEnvelope``/``FrictionBin`` and calling ``.to_dict()`` on it,
    the same call the orchestrator makes, rather than hand-writing a dict
    that might not match its real shape.
    """
    from pipeline.stages import s10d2_grip_anchor
    import grip_anchor as ga
    from friction_envelope import FrictionBin, FrictionEnvelope

    v_full = 25.0   # constant "Speed (m/s)" in _lap_frame -- matches the bin below
    real_bin = FrictionBin(
        speed_center_mps=v_full, combined_g_p95=1.3, lat_max_g=1.3,
        accel_max_g=0.35, brake_max_g=0.62, sample_count=41, confidence=1.0,
    )
    envelope_dict = FrictionEnvelope(
        speed_bins=np.array([v_full]),
        friction_bins=[real_bin],
        global_combined_g=1.3,
        is_reliable=True,
        warning=None,
    ).to_dict()   # <-- the exact call orchestrator.py makes into summary[...]

    class _FullFriction:
        exponent = 2.0
        exponent_source = "fitted"

        def lateral_max(self, speed_mps):
            return 20.0

        def traction_max(self, speed_mps):
            return 20.0

        def braking_max(self, speed_mps):
            return 20.0

    a_lat_g = 0.9
    kappa = (a_lat_g * 9.80665) / (v_full ** 2)   # makes trust_ratio exactly 1.0
    curvature_profile = pd.DataFrame({
        "distance_m": np.linspace(0.0, 1200.0, 400),
        "curvature_1pm": np.full(400, kappa),
    })

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": v_full}]
    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps = {1: _lap_frame(a_lat_g=a_lat_g)}

    out = s10d2_grip_anchor.run_grip_anchor(
        metrics, corners, laps,
        friction_model=_FullFriction(),
        friction_envelope=envelope_dict,   # plain dict, not an object
        curvature_profile=curvature_profile,
    )
    assert out[0]["grip_anchor_tier"] == ga.TIER_SESSION_ENVELOPE_ELLIPSE_FITTED, (
        f"a dict-shaped envelope with a genuinely measured, in-range bin "
        f"must still reach a session-envelope tier -- got {out[0]!r}"
    )
    assert out[0]["grip_anchor_reason"] is None
    assert out[0]["grip_anchor_pct"] is not None


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


import os

_REAL_CSV = "telemetry_tool/data/raw/OK_R4.csv"


@pytest.fixture
def _isolated_track_registry(tmp_path, monkeypatch):
    """Keep the pipeline's track-registration write off the tracked
    models/tracks.json — see the parent branch's test-hygiene incident.

    Returns a `Path`, not a `str`. `_default_db_path` is annotated `-> Path`
    and `load_track_database` calls `path.exists()` on whatever it returns,
    so a `str` here made stage 05_detect_track raise
    `AttributeError: 'str' object has no attribute 'exists'`. That is
    swallowed by `pipeline/helpers.py:93`, so the isolation "worked" only by
    killing track detection outright. Corrected in fix round 1 of Task 11;
    matches the already-correct version at test_distance_frame.py:614.
    """
    import track_detection

    fake_path = tmp_path / "tracks_isolated.json"
    monkeypatch.setattr(track_detection, "_default_db_path", lambda: fake_path)
    return fake_path


# Minimum share of corner-laps that must reach a session-envelope tier on this
# fixture. MEASURED: 57 of 72 = 79.2%.
#
# WHY 25% AND NOT SOMETHING TIGHTER. The value has to survive honest variation
# and still fail on collapse, and those two pull in opposite directions. The
# share legitimately moves with the track: the 15 corner-laps that miss here do
# so for REASON_SPEED_OUT_OF_BINS (apex speeds of 8.9-11.6 m/s against a lowest
# envelope bin centred at 11.99 m/s -- a genuine coverage gap, correctly
# refused), and a circuit with more slow corners than OK_R4 would legitimately
# push that group larger. A floor pinned near the measured 79% would start
# failing on track shape rather than on defects.
#
# 25% leaves a factor of ~3 of headroom below the measured value -- enough that
# a session would need most of its corners outside envelope coverage before it
# tripped -- while still being far above the failure mode this exists to catch.
# Every systemic collapse of this feature drives the share to ZERO, not to
# something merely low: sabotaging bin_is_measured, or the channel-trust gate,
# or the envelope threading, takes all 72 corner-laps to driver_best_session at
# once, because those inputs are session-wide, not per-corner. So the gap
# between "collapsed" (0%) and "unusually slow track" (still well above 25%) is
# wide, and the floor sits inside it rather than near either edge.
_MIN_SESSION_ENVELOPE_SHARE = 0.25


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
def test_grip_anchor_on_real_kart_telemetry(_isolated_track_registry):
    """Acceptance: on real data every corner-lap gets a tier from the closed
    vocabulary, corner-laps ACTUALLY REACH the session-envelope tier, their
    percentages are physically plausible, and the channel-trust ratio the
    pipeline really computed lands inside the trust band.

    THIS TEST USED TO BE UNABLE TO FAIL ON ITS HEADLINE CLAIM. The plausibility
    assertions all lived inside `for m in physics:`, so an empty `physics` list
    meant the loop body never ran and the test passed -- green while asserting
    nothing. Proven by sabotage: forcing `bin_is_measured` to return False
    yields a tier distribution of `{'driver_best_session': 72}`, zero
    session-envelope tiers, and the test still PASSED. That is the exact defect
    caught by hand at Task 10, which would have shipped green. Hence the three
    assertions the old version lacked: a non-empty result, a floor on the
    share, and a check on the trust ratio the docstring already claimed.

    The trust ratio is observed by spying on the LIVE stage helper rather than
    recomputed here, so the number under test is the one the pipeline actually
    used to make its tier decisions, not a lookalike.
    """
    import grip_anchor as ga
    import pipeline.stages.s10d2_grip_anchor as stage
    from pipeline import run_full_analysis

    seen_trust = []
    real_trust_ratio = stage._session_trust_ratio

    def _spy(*args, **kwargs):
        value = real_trust_ratio(*args, **kwargs)
        seen_trust.append(value)
        return value

    # NOTE: the brief's literal call is `run_full_analysis(_REAL_CSV)`, but
    # pipeline.orchestrator.run_full_analysis's `session_meta` is a required
    # positional parameter (no default) -- calling with one arg raises
    # TypeError before the pipeline ever runs. Passing {} matches how every
    # other real-pipeline test in this file already calls it (see
    # test_orchestrator_calls_grip_anchor_with_the_per_lap_metrics_and_friction_model
    # above: `pipeline.run_full_analysis(str(csv_path), {})`).
    with patch.object(stage, "_session_trust_ratio", side_effect=_spy):
        summary = run_full_analysis(_REAL_CSV, {})

    metrics = summary.get("per_lap_corner_metrics") or []
    assert metrics, "no per-lap corner metrics produced"

    tiers = [m.get("grip_anchor_tier") for m in metrics]
    reasons = [m.get("grip_anchor_reason") for m in metrics]
    distribution = {t: tiers.count(t) for t in set(tiers)}
    assert all(t in ga.TIERS for t in tiers), f"tier outside vocabulary: {set(tiers)}"

    # Every lap must be represented — the parent branch fixed the bug where
    # only lap 1 produced corner data.
    laps = {m["lap_number"] for m in metrics}
    assert len(laps) >= 5, f"only {len(laps)} laps produced corner metrics: {laps}"

    envelope_tier = [
        m for m in metrics
        if ga.is_quotable_as_session_envelope(m.get("grip_anchor_tier"))
        and m.get("grip_anchor_pct") is not None
    ]

    # (1) The headline claim itself. Without this, everything below is vacuous.
    assert len(envelope_tier) > 0, (
        "NOT ONE corner-lap reached a session-envelope tier -- Phase 1's "
        f"headline claim did not survive on real data. tiers={distribution} "
        f"reasons={ {r: reasons.count(r) for r in set(reasons)} }"
    )

    # (2) ...and enough of them that a near-total collapse is caught too.
    share = len(envelope_tier) / len(metrics)
    assert share >= _MIN_SESSION_ENVELOPE_SHARE, (
        f"only {len(envelope_tier)}/{len(metrics)} ({share:.1%}) corner-laps "
        f"reached a session-envelope tier, under the {_MIN_SESSION_ENVELOPE_SHARE:.0%} "
        f"floor. tiers={distribution} "
        f"reasons={ {r: reasons.count(r) for r in set(reasons)} }"
    )

    # (3) The trust ratio the docstring has always claimed, now checked. This
    # is the value the live stage computed and fed to every tier decision.
    assert seen_trust, "the stage never computed a channel-trust ratio at all"
    trust = seen_trust[0]
    assert trust is not None, (
        "the channel-trust ratio was unmeasurable on real kart data; every "
        "corner-lap would fail safe to the session-relative tier"
    )
    assert ga.TRUST_BAND_LOW <= trust <= ga.TRUST_BAND_HIGH, (
        f"channel-trust ratio {trust:.4f} is outside the trust band "
        f"[{ga.TRUST_BAND_LOW}, {ga.TRUST_BAND_HIGH}] -- measured 0.9865 on "
        f"this fixture during design"
    )

    for m in envelope_tier:
        assert 0.0 <= m["grip_anchor_pct"] <= 300.0, (
            f"implausible grip pct {m['grip_anchor_pct']} "
            f"(lap {m['lap_number']} corner {m['corner_id']})"
        )
        assert 0.2 <= m["grip_anchor_baseline_g"] <= 3.0, (
            f"implausible baseline {m['grip_anchor_baseline_g']} G"
        )

    print(f"\ntier distribution: {distribution}")
    print(f"reason distribution: { {r: reasons.count(r) for r in set(reasons)} }")
    print(f"session-envelope share: {len(envelope_tier)}/{len(metrics)} ({share:.1%})")
    print(f"channel-trust ratio: {trust:.4f}")


def test_grip_anchor_ignores_excluded_laps_when_choosing_the_session_best():
    """An excluded lap must not set the per-corner reference. On real data the
    truncated final lap otherwise wins 'best' at almost every corner."""
    from pipeline.stages import s10d2_grip_anchor

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]

    # lap 2 is excluded but has a much higher lateral peak
    laps = {
        1: _lap_frame(a_lat_g=0.9),
        2: _lap_frame(a_lat_g=2.0),
    }

    out = s10d2_grip_anchor.run_grip_anchor(
        metrics, corners, laps, excluded_laps=frozenset({2}),
    )
    # lap 1 is the only admissible lap, so it IS the session best -> 100%
    assert out[0]["grip_anchor_pct"] == pytest.approx(100.0, abs=0.5)


def test_grip_anchor_uses_an_excluded_lap_if_not_told_to_exclude_it():
    """Control: without the exclusion, lap 2's higher peak becomes the
    reference and lap 1 scores below 100. This is what pins the fix."""
    from pipeline.stages import s10d2_grip_anchor

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]
    laps = {1: _lap_frame(a_lat_g=0.9), 2: _lap_frame(a_lat_g=2.0)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)
    assert out[0]["grip_anchor_pct"] < 60.0     # 0.9 / 2.0


def test_corner_window_is_frame_stable_across_laps_of_different_length():
    """Two laps of the same circuit driven at different measured lengths must
    yield the same corner window in FRACTION of the lap, not the same window
    in absolute metres. Real laps on OK_R4 span 1198.7-1218.0 m."""
    from pipeline.stages import s10d2_grip_anchor

    def _lap_of_length(total_m, n=1000):
        d = np.linspace(0.0, total_m, n)
        return pd.DataFrame({
            "Distance (m)": d,
            "distance_norm": d / total_m,
            "Speed (m/s)": np.full(n, 25.0),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
        })

    short, long = _lap_of_length(1000.0), _lap_of_length(1200.0)
    corner = {"corner_id": 1, "s_start": 250.0, "s_end": 350.0}   # 25%-35%

    m_short = s10d2_grip_anchor._corner_mask(short, corner, short)
    m_long = s10d2_grip_anchor._corner_mask(long, corner, short)

    assert m_short is not None and m_long is not None
    # Same FRACTION of each lap -> sample counts within one of each other.
    assert abs(int(m_short.sum()) - int(m_long.sum())) <= 1

    # And the long lap's window really is further along in metres.
    d_long = long["Distance (m)"].values[m_long]
    assert d_long.min() == pytest.approx(300.0, abs=5.0)   # 25% of 1200


def test_corner_time_is_measured_and_referenced_to_the_session_best():
    """Each corner-lap gets its own traversal time and the best time any
    admissible lap achieved through the same corner."""
    from pipeline.stages import s10d2_grip_anchor

    def _lap_at(speed, n=1000, total=1000.0):
        d = np.linspace(0.0, total, n)
        return pd.DataFrame({
            "Distance (m)": d,
            "distance_norm": d / total,
            "Speed (m/s)": np.full(n, speed),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
        })

    corners = [{"corner_id": 1, "s_start": 250.0, "s_end": 350.0}]
    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 20.0},
    ]
    laps = {1: _lap_at(10.0), 2: _lap_at(20.0)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)
    by_lap = {m["lap_number"]: m for m in out}

    # 100 m at 10 m/s = 10 s; at 20 m/s = 5 s.
    assert by_lap[1]["corner_time_s"] == pytest.approx(10.0, rel=0.02)
    assert by_lap[2]["corner_time_s"] == pytest.approx(5.0, rel=0.02)
    # Both rows carry the SAME best -- the fastest admissible pass.
    assert by_lap[1]["corner_time_best_s"] == pytest.approx(5.0, rel=0.02)
    assert by_lap[2]["corner_time_best_s"] == pytest.approx(5.0, rel=0.02)


def test_corner_time_is_none_when_the_window_is_unusable():
    from pipeline.stages import s10d2_grip_anchor

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0}]
    out = s10d2_grip_anchor.run_grip_anchor(metrics, [], {})
    assert out[0]["corner_time_s"] is None
    assert out[0]["corner_time_best_s"] is None
