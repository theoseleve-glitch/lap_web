"""The canonical per-lap distance frame.

RaceChrono exports cumulative SESSION distance, so lap 5 of a real session
spans e.g. 4997.9-6196.5 m.  Every resampled lap must be rebased to 0 so that
corner spans detected on one lap match all the others.

The offsets used here are the measured values from
telemetry_tool/data/raw/OK_R4.csv.
"""
import numpy as np
import pandas as pd
import pytest


def _lap(d_start: float, d_end: float, lap_no: int, n: int = 500) -> pd.DataFrame:
    """A lap whose Distance column carries a genuine absolute offset."""
    d = np.linspace(d_start, d_end, n)
    return pd.DataFrame({
        "Distance (m)": d,
        "Speed (m/s)": np.linspace(10.0, 30.0, n),
        "Time (s)": np.linspace(0.0, 75.0, n),
        "Lap #": float(lap_no),
    })


def test_resampled_lap_starts_at_zero_regardless_of_absolute_offset():
    from resampling import resample_lap_by_distance

    out = resample_lap_by_distance(_lap(4997.9, 6196.5, 5), n_points=100)

    assert out["Distance (m)"].iloc[0] == pytest.approx(0.0)
    assert out["Distance (m)"].iloc[-1] == pytest.approx(6196.5 - 4997.9)


def test_all_laps_share_one_frame():
    from resampling import resample_lap_by_distance

    laps = [_lap(153.9, 1356.4, 1), _lap(4997.9, 6196.5, 5)]
    outs = [resample_lap_by_distance(l, n_points=100) for l in laps]

    for o in outs:
        assert o["Distance (m)"].iloc[0] == pytest.approx(0.0)
    # spans stay distinct (laps really are different lengths) but origins agree
    assert outs[0]["Distance (m)"].iloc[-1] != pytest.approx(
        outs[1]["Distance (m)"].iloc[-1]
    )


def test_channels_are_not_clamped_by_the_rebase():
    """Guards the shift-before-interpolate trap.

    If dist_raw is not shifted before _interp_channel, np.interp sees an
    absolute x-array against a 0-based grid, every query falls left of the
    first point, and every channel is returned as a constant.
    """
    from resampling import resample_lap_by_distance

    out = resample_lap_by_distance(_lap(4997.9, 6196.5, 5), n_points=200)

    assert out["Speed (m/s)"].iloc[0] == pytest.approx(10.0, abs=0.2)
    assert out["Speed (m/s)"].iloc[-1] == pytest.approx(30.0, abs=0.2)
    assert out["Speed (m/s)"].nunique() > 100, "channel was clamped to a constant"


def test_distance_norm_still_spans_zero_to_one():
    from resampling import resample_lap_by_distance

    out = resample_lap_by_distance(_lap(4997.9, 6196.5, 5), n_points=100)

    assert out["distance_norm"].iloc[0] == pytest.approx(0.0)
    assert out["distance_norm"].iloc[-1] == pytest.approx(1.0)


def test_corner_mask_populates_on_every_lap():
    """The headline bug: corner spans come from ONE lap, masks run on ALL laps.

    Asserts on sample COUNTS, not on the absence of exceptions - the production
    call sites swallow failures (s10b_corners.py:380-382) and return None
    (corner_diagnosis.py:238-241), so an exception-based test passes against
    the bug.
    """
    from resampling import resample_lap_by_distance

    starts = [153.9, 1356.5, 2574.6, 3784.9, 4997.9]      # measured, OK_R4
    ends = [1356.4, 2574.5, 3784.9, 4997.7, 6196.5]
    laps = {
        i + 1: resample_lap_by_distance(_lap(s, e, i + 1), n_points=1000)
        for i, (s, e) in enumerate(zip(starts, ends))
    }

    # corner spans as corner_detection would emit them: taken from ONE lap
    detection_lap = laps[min(laps)]
    d_det = detection_lap["Distance (m)"].values
    corner_spans = [(d_det[100], d_det[160]), (d_det[400], d_det[470])]

    for lap_no, lap in laps.items():
        dist = lap["Distance (m)"].values
        for ci, (s0, s1) in enumerate(corner_spans):
            n = int(((dist >= s0) & (dist <= s1)).sum())
            assert n >= 5, (
                f"lap {lap_no} corner {ci}: {n} samples - "
                "corner_diagnosis bails below 5"
            )


def test_reference_grid_covers_all_laps_not_just_the_median_one():
    """Under the old frame the common grid sat in the middle lap's absolute
    window, so _interpolate_lap_onto_grid NaN'd every other lap entirely and
    np.nanmedian silently reduced a 10-lap reference to 1 lap."""
    from resampling import resample_lap_by_distance
    from reference_line import _build_common_grid, _interpolate_lap_onto_grid

    starts = [153.9, 1356.5, 2574.6, 3784.9, 4997.9]
    ends = [1356.4, 2574.5, 3784.9, 4997.7, 6196.5]
    laps = {
        i + 1: resample_lap_by_distance(_lap(s, e, i + 1), n_points=500)
        for i, (s, e) in enumerate(zip(starts, ends))
    }

    grid = _build_common_grid(laps)
    assert grid[0] == pytest.approx(0.0, abs=1.0)

    for lap_no, lap in laps.items():
        vals = _interpolate_lap_onto_grid(lap, grid, "Speed (m/s)")
        nan_frac = float(np.isnan(vals).mean())
        assert nan_frac < 0.05, f"lap {lap_no}: {nan_frac:.0%} NaN on the grid"


def test_999m_lap_is_not_mistaken_for_row_index_distances():
    """A 1000-point trace spanning 999 m is a REAL lap, not the legacy
    row-index bug. Before Task 1 the distances[0] == 0 clause hid this;
    after it, every lap starts at 0 and only the length discriminates."""
    from web.routes.data_v2 import _looks_like_row_index_distances

    real = [i * (999.0 / 999) for i in range(1000)]      # a genuine 999 m lap
    # consistent GPS: ~999 m of real movement
    assert _looks_like_row_index_distances(real, haversine_total=999.4) is False

    # the genuine legacy bug: distances are row indices, GPS says 1240 m
    assert _looks_like_row_index_distances(real, haversine_total=1240.0) is True

    # NOTE: whether this helper is actually *called* at all three
    # haversine-substitution sites in data_v2.py (speed-trace, gps-trace,
    # gg-data) is a behavioural regression covered end-to-end via the
    # Flask test client in
    # telemetry_tool/tests/test_data_api_v2.py::TestRowIndexDistanceGuardAtEveryEndpoint
    # - a source-grep counting call sites was tried here first and
    # replaced because it would pass even for a dead/unreachable call or
    # one whose boolean result is discarded.


def test_corner_coaching_spans_are_persisted_verbatim(test_db):
    """theoretical_repo must not re-rebase corner_coaching spans that are
    already 0-based in the canonical per-lap frame.

    Regression guard for the theo_d0 rebase: it used the theoretical lap's
    (possibly non-zero, pre-Task-1) first distance to shift every persisted
    corner span, silently mutating them into a fifth coordinate frame. Post
    Task 1 the theoretical lap is always 0-based so the rebase is always a
    no-op in production - but a stale/legacy-shaped theoretical_lap with a
    non-zero first distance must still not perturb the persisted spans.
    """
    from web.repos import theoretical_repo

    theo_lap = pd.DataFrame({
        "distance_m": [150.0, 160.0, 170.0],
        "speed_mps": [30.0, 31.0, 32.0],
    })
    summary = {
        "theoretical_metrics": {"best_s": 55.0, "simulation_method": "envelope"},
        "theoretical_lap": theo_lap,
        "corner_coaching": [
            {"corner_id": 1, "corner_name": "T1", "s_start": 120.0,
             "s_end": 130.0, "s_apex": 125.0, "direction": "left"},
        ],
    }

    theoretical_repo.insert_theoretical_data(test_db, "s_distframe", summary)
    test_db.commit()

    stored = theoretical_repo.get_theoretical_data(test_db, "s_distframe")
    assert stored is not None
    assert stored["corner_coaching"][0]["s_start"] == pytest.approx(120.0), (
        "s_start was rewritten by the theo_d0 rebase (would be -30.0) "
        "instead of being persisted verbatim"
    )


def test_grip_map_bins_are_not_poisoned_by_out_of_range_samples():
    """np.clip silently dumps every out-of-frame sample into the last bin,
    which is how a coordinate-frame bug produced a plausible-looking grip
    map. Build laps where lap 2/3 fall entirely outside lap 1's distance
    range (the exact shape of the old frame bug) and assert the terminal
    bin isn't swamped relative to the rest.
    """
    import grip_map

    rng = np.random.default_rng(0)

    def _grip_lap(distances: np.ndarray) -> pd.DataFrame:
        mu = 0.9 + rng.normal(0.0, 0.01, len(distances))
        return pd.DataFrame({
            "Distance (m)": distances,
            "Lateral acceleration (G) *calc": mu,
        })

    n_bins = 10
    # Lap 1 sets bin_edges over [0, 99].
    laps = {1: _grip_lap(np.linspace(0.0, 99.0, 100))}
    # Laps 2 and 3 are entirely outside that range - simulating laps that
    # were never rebased into lap 1's frame.
    out_of_range = np.linspace(500.0, 599.0, 100)
    laps[2] = _grip_lap(out_of_range)
    laps[3] = _grip_lap(out_of_range)

    result = grip_map.compute_grip_map(laps, n_bins=n_bins)

    assert not result.is_global_fallback
    counts = [s.sample_count for s in result.bin_stats]
    mean_count = sum(counts) / len(counts)
    assert max(counts) <= 3 * mean_count, (
        f"bin sample counts {counts} (mean={mean_count:.1f}) show the "
        "terminal bin absorbing out-of-range samples instead of dropping them"
    )


def test_grip_map_curvature_branch_bins_are_not_poisoned_by_out_of_range_samples():
    """Same terminal-bin-poisoning regression as the lateral-accel test
    above, but exercised through grip_map's OTHER clip site: the
    curvature/speed branch. That branch is only reached when no lap in the
    first three carries a lateral-acceleration column (has_lat_accel stays
    False) and a curvature_profile with a "curvature_1pm" column is
    supplied - see compute_grip_map's branch selection in grip_map.py.
    """
    import grip_map

    n_bins = 10
    # Constant curvature across the whole distance span used below, so mu
    # = v^2 * |curv| / g is deterministic and every sample clears the
    # (mu > 0.01) & (|curv| > 0.001) validity filter.
    curvature_profile = pd.DataFrame({
        "distance_m": [0.0, 600.0],
        "curvature_1pm": [0.01, 0.01],
    })

    def _speed_lap(distances: np.ndarray) -> pd.DataFrame:
        # Deliberately no "Lateral acceleration (G) *calc" / "accel_lat_mps2"
        # column - this is what forces has_lat_accel to False.
        return pd.DataFrame({
            "Distance (m)": distances,
            "Speed (m/s)": np.full(len(distances), 20.0),
        })

    # Lap 1 sets bin_edges over [0, 99].
    laps = {1: _speed_lap(np.linspace(0.0, 99.0, 100))}
    # Laps 2 and 3 are entirely outside that range - simulating laps that
    # were never rebased into lap 1's frame.
    out_of_range = np.linspace(500.0, 599.0, 100)
    laps[2] = _speed_lap(out_of_range)
    laps[3] = _speed_lap(out_of_range)

    result = grip_map.compute_grip_map(
        laps, curvature_profile=curvature_profile, n_bins=n_bins
    )

    assert result.source == "curvature_speed", (
        f"test fell through to source={result.source!r} instead of "
        "exercising the curvature/speed branch"
    )
    assert not result.is_global_fallback
    counts = [s.sample_count for s in result.bin_stats]
    mean_count = sum(counts) / len(counts)
    assert max(counts) <= 3 * mean_count, (
        f"bin sample counts {counts} (mean={mean_count:.1f}) show the "
        "terminal bin absorbing out-of-range samples instead of dropping them"
    )


def test_pipeline_version_bumped_for_the_frame_change():
    """The structural hash digests step NAMES only, so a change inside
    resampling.py is invisible to it. Without a manual bump, every pre-fix
    session reports itself current forever and nothing gets reprocessed."""
    from pipeline_version import PIPELINE_VERSION, is_stale

    assert PIPELINE_VERSION >= 3
    assert is_stale(2) is True
    assert is_stale(None) is True
    assert is_stale(PIPELINE_VERSION) is False


# ── Task 10: chart cache invalidation on reprocess ─────────────────────────
#
# /corners, /speed-trace, /gps-trace and /delta are @chart_cached(ttl=3600).
# Reprocessing a session rebuilds it in the new 0-based distance frame (this
# file), but nothing invalidated the chart cache afterwards - a reprocessed
# session kept serving the OLD frame from cache for up to an hour. Two
# independent writers touch a session's results and both must invalidate:
# the Celery finalize stage (every first-time process + every reprocess) and
# the /recoach endpoint (rewrites analysis_json outside the pipeline).


def test_pipeline_finalize_invalidates_the_chart_cache():
    """pipeline_finalize is the choke point EVERY pipeline run passes
    through - first-time processing and every reprocess alike."""
    from unittest.mock import MagicMock, patch

    from tasks import pipeline_tasks

    ctx = MagicMock()
    ctx.session_id = "sess-finalize-1"
    ctx.workspace_id = 7
    ctx.current_stage = "finalize"
    conn = MagicMock()

    with patch.object(pipeline_tasks, "_get_redis", return_value=MagicMock()), \
         patch.object(pipeline_tasks, "PipelineContext") as mock_ctx_cls, \
         patch.object(pipeline_tasks, "_open_task_conn", return_value=conn), \
         patch.object(pipeline_tasks, "_return_pg_connection"), \
         patch.object(pipeline_tasks, "acquire_workspace_lock", return_value=True), \
         patch.object(pipeline_tasks, "release_workspace_lock"), \
         patch.object(pipeline_tasks, "_update_job_progress"), \
         patch.object(pipeline_tasks, "_run_finalize_stages"), \
         patch.object(pipeline_tasks, "check_worker_memory", return_value=False), \
         patch.object(pipeline_tasks, "_increment_batch_counter"), \
         patch("web.chart_cache.invalidate_session_cache") as mock_invalidate:
        mock_ctx_cls.load.return_value = ctx

        result = pipeline_tasks.pipeline_finalize("job-finalize-1")

    assert result == "job-finalize-1"
    mock_invalidate.assert_called_once_with("sess-finalize-1")


def test_pipeline_finalize_swallows_chart_cache_invalidation_failure(caplog):
    """A cache-invalidation failure must never fail the pipeline run - the
    session's real results are already persisted at this point."""
    import logging
    from unittest.mock import MagicMock, patch

    from tasks import pipeline_tasks

    ctx = MagicMock()
    ctx.session_id = "sess-finalize-2"
    ctx.workspace_id = 7
    ctx.current_stage = "finalize"
    conn = MagicMock()

    with patch.object(pipeline_tasks, "_get_redis", return_value=MagicMock()), \
         patch.object(pipeline_tasks, "PipelineContext") as mock_ctx_cls, \
         patch.object(pipeline_tasks, "_open_task_conn", return_value=conn), \
         patch.object(pipeline_tasks, "_return_pg_connection"), \
         patch.object(pipeline_tasks, "acquire_workspace_lock", return_value=True), \
         patch.object(pipeline_tasks, "release_workspace_lock"), \
         patch.object(pipeline_tasks, "_update_job_progress"), \
         patch.object(pipeline_tasks, "_run_finalize_stages"), \
         patch.object(pipeline_tasks, "check_worker_memory", return_value=False), \
         patch.object(pipeline_tasks, "_increment_batch_counter"), \
         patch(
             "web.chart_cache.invalidate_session_cache",
             side_effect=RuntimeError("redis down"),
         ) as mock_invalidate, \
         caplog.at_level(logging.WARNING):
        mock_ctx_cls.load.return_value = ctx

        result = pipeline_tasks.pipeline_finalize("job-finalize-2")

    # The call completed and returned normally - the exception did not propagate.
    assert result == "job-finalize-2"
    mock_invalidate.assert_called_once_with("sess-finalize-2")
    assert "Chart-cache invalidation failed" in caplog.text


def test_recoach_invalidates_the_chart_cache(seeded_db):
    """recoach rewrites analysis_json independently of the pipeline, so it
    must invalidate the chart cache too."""
    from unittest.mock import patch

    from flask import Flask

    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    client = app.test_client()

    fake_sections = [
        {"corner_id": 1, "corner_type": "auto", "s_start": 100.0, "s_end": 200.0},
    ]

    with patch("web.routes.data_v2.get_db_connection", return_value=seeded_db), \
         patch(
             "pipeline.stages.s10b_corners.run_track_decomposition_v2",
             return_value=fake_sections,
         ), \
         patch("pipeline.stages.s10b_corners.run_mrp_detection_v2", return_value=[]), \
         patch("pipeline.stages.s10b_corners.run_coaching_v2", return_value=[]), \
         patch("web.chart_cache.invalidate_session_cache") as mock_invalidate:
        resp = client.post("/api/v1/sessions/s1/recoach")

    assert resp.status_code == 200, resp.get_json()
    mock_invalidate.assert_called_once_with("s1")


def test_recoach_swallows_chart_cache_invalidation_failure(seeded_db, caplog):
    """A cache-invalidation failure must never fail the /recoach request -
    the analysis_json rewrite already committed at this point."""
    import logging
    from unittest.mock import patch

    from flask import Flask

    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    client = app.test_client()

    fake_sections = [
        {"corner_id": 1, "corner_type": "auto", "s_start": 100.0, "s_end": 200.0},
    ]

    with patch("web.routes.data_v2.get_db_connection", return_value=seeded_db), \
         patch(
             "pipeline.stages.s10b_corners.run_track_decomposition_v2",
             return_value=fake_sections,
         ), \
         patch("pipeline.stages.s10b_corners.run_mrp_detection_v2", return_value=[]), \
         patch("pipeline.stages.s10b_corners.run_coaching_v2", return_value=[]), \
         patch(
             "web.chart_cache.invalidate_session_cache",
             side_effect=RuntimeError("redis down"),
         ) as mock_invalidate, \
         caplog.at_level(logging.WARNING):
        resp = client.post("/api/v1/sessions/s1/recoach")

    # The request completed with 200 - the exception did not propagate.
    assert resp.status_code == 200, resp.get_json()
    mock_invalidate.assert_called_once_with("s1")
    assert "Chart-cache invalidation failed after recoach" in caplog.text
