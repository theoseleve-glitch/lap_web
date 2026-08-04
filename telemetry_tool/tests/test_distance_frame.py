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


# ── Task 11: per-lap corner failures must be audible, not swallowed ────────
#
# run_per_lap_corner_metrics used to log per-lap exceptions at DEBUG only,
# which is invisible in production. A total failure of every lap produced
# silence - exactly how the coordinate-frame bug this branch fixes survived
# undetected (9 of 10 laps returned zero corner samples, nothing said so).


def test_per_lap_corner_failures_are_reported_at_warning_level(caplog):
    """A per-lap exception during corner analysis must surface at WARNING."""
    import logging
    import types
    from unittest.mock import patch

    from pipeline.stages import s10b_corners

    laps = {n: _lap(0.0, 100.0, n) for n in (1, 2, 3)}
    corners = [{"corner_id": 1, "s_start": 10.0, "s_end": 20.0}]

    def fake_analyze_corners(corners_arg, driver_lap, theoretical_result, friction):
        lap_no = int(driver_lap["Lap #"].iloc[0])
        if lap_no == 2:
            raise RuntimeError("synthetic corner-analysis failure")
        return [{"time_loss_s": 0.1, "corner_id": 1}]

    fake_ca_mod = types.SimpleNamespace(analyze_corners=fake_analyze_corners)

    with patch.object(s10b_corners, "lazy_import", return_value=fake_ca_mod), \
         caplog.at_level(logging.WARNING):
        results = s10b_corners.run_per_lap_corner_metrics(corners, laps)

    # Lap 2 raised - its corner never made it into results, but 1 and 3 did.
    assert {r["lap_number"] for r in results} == {1, 3}
    assert any(rec.levelno == logging.WARNING for rec in caplog.records), (
        "a per-lap corner-analysis exception must be logged at WARNING, "
        "not left invisible at DEBUG"
    )
    assert "1/3" in caplog.text, "warning must report failed-count/attempted-count"
    assert "[2]" in caplog.text, "warning must name the failed lap(s)"


def test_per_lap_corner_success_produces_no_failure_warning(caplog):
    """When every lap succeeds, the per-lap-failure warning must not fire."""
    import logging
    import types
    from unittest.mock import patch

    from pipeline.stages import s10b_corners

    laps = {n: _lap(0.0, 100.0, n) for n in (1, 2, 3)}
    corners = [{"corner_id": 1, "s_start": 10.0, "s_end": 20.0}]

    def fake_analyze_corners(corners_arg, driver_lap, theoretical_result, friction):
        return [{"time_loss_s": 0.1, "corner_id": 1}]

    fake_ca_mod = types.SimpleNamespace(analyze_corners=fake_analyze_corners)

    with patch.object(s10b_corners, "lazy_import", return_value=fake_ca_mod), \
         caplog.at_level(logging.WARNING):
        results = s10b_corners.run_per_lap_corner_metrics(corners, laps)

    assert {r["lap_number"] for r in results} == {1, 2, 3}
    assert not any(rec.levelno == logging.WARNING for rec in caplog.records), (
        "no lap failed, so no per-lap-failure warning should have fired: "
        f"{caplog.text}"
    )


# ── Task 11 fix round 1: coverage signal for the silent-fallback case ──────
#
# The exception warning above cannot catch the actual historical incident:
# corner_analysis.analyze_corners does not raise on a degenerate/zero-sample
# mask - it falls back or returns nothing for that lap. That is precisely
# the shape of the coordinate-frame bug this branch fixes (corner spans
# detected on lap 1 didn't intersect laps 2..N), and it produced NO
# exception - it was only found by a standalone script counting samples.
# A second, independent signal is needed: how many of the laps that were
# actually attempted (not excluded, not too-short) ended up represented in
# results at all - regardless of whether anything raised.


def test_per_lap_corner_coverage_warning_fires_on_the_historical_incident_shape(caplog):
    """Regression guard for the real incident: laps are attempted, nothing
    raises, but corner spans only intersect one lap out of five - so
    `results` covers just that one lap. The exception-based warning cannot
    see this (there are zero exceptions); the coverage warning must."""
    import logging
    import types
    from unittest.mock import patch

    from pipeline.stages import s10b_corners

    laps = {n: _lap(0.0, 100.0, n) for n in (1, 2, 3, 4, 5)}
    corners = [{"corner_id": 1, "s_start": 10.0, "s_end": 20.0}]

    def fake_analyze_corners(corners_arg, driver_lap, theoretical_result, friction):
        lap_no = int(driver_lap["Lap #"].iloc[0])
        if lap_no == 1:
            return [{"time_loss_s": 0.1, "corner_id": 1}]
        # Spans detected on lap 1 don't intersect this lap - no exception,
        # analyze_corners just comes back with nothing for it.
        return []

    fake_ca_mod = types.SimpleNamespace(analyze_corners=fake_analyze_corners)

    with patch.object(s10b_corners, "lazy_import", return_value=fake_ca_mod), \
         caplog.at_level(logging.WARNING):
        results = s10b_corners.run_per_lap_corner_metrics(corners, laps)

    # Only lap 1 is represented - 4 of 5 attempted laps produced nothing,
    # and none of them raised.
    assert {r["lap_number"] for r in results} == {1}
    assert any(rec.levelno == logging.WARNING for rec in caplog.records), (
        "near-total coverage loss with zero exceptions must still surface "
        "a warning - this is the actual historical incident shape"
    )
    assert "1/5" in caplog.text, "coverage warning must report covered/attempted"
    assert "no exceptions raised" in caplog.text.lower(), (
        "coverage warning must state it is independent of the exception count"
    )
    # And the exception-count warning specifically must NOT have fired -
    # there were no exceptions, only empty results.
    assert "raised an exception" not in caplog.text


def test_per_lap_corner_coverage_warning_does_not_fire_when_all_laps_covered(caplog):
    """A healthy session where every attempted lap is represented must not
    trip the coverage warning."""
    import logging
    import types
    from unittest.mock import patch

    from pipeline.stages import s10b_corners

    laps = {n: _lap(0.0, 100.0, n) for n in (1, 2, 3, 4, 5)}
    corners = [{"corner_id": 1, "s_start": 10.0, "s_end": 20.0}]

    def fake_analyze_corners(corners_arg, driver_lap, theoretical_result, friction):
        return [{"time_loss_s": 0.1, "corner_id": 1}]

    fake_ca_mod = types.SimpleNamespace(analyze_corners=fake_analyze_corners)

    with patch.object(s10b_corners, "lazy_import", return_value=fake_ca_mod), \
         caplog.at_level(logging.WARNING):
        results = s10b_corners.run_per_lap_corner_metrics(corners, laps)

    assert {r["lap_number"] for r in results} == {1, 2, 3, 4, 5}
    assert not any(rec.levelno == logging.WARNING for rec in caplog.records), (
        f"all 5 attempted laps were covered, no warning should fire: {caplog.text}"
    )


# ── Shared: isolate real-pipeline tests from the tracked tracks.json ───────
#
# Any test that drives pipeline.run_full_analysis() reaches Step 05's
# track-detection stage (pipeline/stages/s05_track.py -> track_detection.
# register_or_match_track), which fingerprints the session and - since
# synthetic test data never matches an existing fingerprint - APPENDS a new
# "Unknown Track" entry and persists it. Unpatched, that write lands on
# track_detection._default_db_path(), which resolves to the real, GIT-
# TRACKED telemetry_tool/models/tracks.json: every local/CI run of these
# tests would dirty the working tree and permanently accumulate junk
# low-confidence entries in a tracked repo file.
#
# The fix patches only the module's own path-resolution seam
# (_default_db_path) so register_or_match_track / load_track_database /
# save_track_database all still run for real - just against a throwaway
# tmp_path file instead of the tracked one.


@pytest.fixture
def _isolated_track_registry(tmp_path, monkeypatch):
    """Redirect track_detection's tracks.json registry to a throwaway path
    for the duration of one test."""
    import track_detection

    fake_path = tmp_path / "tracks_isolated.json"
    monkeypatch.setattr(track_detection, "_default_db_path", lambda: fake_path)
    return fake_path


# ── Task 12: data_quality persists as a dict, not the raw dataclass ────────
#
# orchestrator.py stored summary["data_quality"] as the raw DataQualityReport
# dataclass, while both persistence paths (tasks/pipeline_tasks.py:562-563
# and web/routes/sessions_v2.py:269-270) gate storage on isinstance(dq, dict).
# So analysis_json.data_quality_summary was never written. Proven end-to-end
# below - a real pipeline run producing a real DataQualityReport, fed through
# the actual persistence-blob builder - not a source-text grep.


def test_data_quality_report_survives_the_persistence_gate(tmp_path, _isolated_track_registry):
    """A DataQualityReport produced by the real pipeline must land in
    summary["data_quality"] as a dict, and that dict must still be present
    after _build_analysis_blob() - the same builder the Celery finalize path
    uses to populate analysis_json.data_quality_summary.
    """
    import pipeline
    from tasks import pipeline_tasks

    n = 500
    laps = np.repeat([1, 2], n // 2)
    time = np.linspace(0, 60, n)
    speed = np.random.default_rng(42).uniform(10, 30, n)
    dist = np.cumsum(speed * np.diff(np.concatenate([[0], time])))
    lat = np.linspace(45.0, 45.001, n)
    lon = np.linspace(9.0, 9.001, n)

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
    })
    csv_path = tmp_path / "quality.csv"
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path), {})

    dq = summary.get("data_quality")
    assert isinstance(dq, dict), (
        f"summary['data_quality'] is a {type(dq).__name__}, not a dict - "
        "both persistence paths gate on isinstance(dq, dict) and would "
        "silently drop it"
    )
    assert "overall_confidence" in dq
    assert isinstance(dq["overall_confidence"], (int, float))
    assert isinstance(dq.get("warnings"), list)

    blob = pipeline_tasks._build_analysis_blob(summary)
    assert "data_quality_summary" in blob, (
        "data_quality_summary was never written to the persisted blob - "
        "the isinstance(dq, dict) gate dropped the raw dataclass"
    )
    assert blob["data_quality_summary"] == dq


# ── Task 13: best_lap_number must reach the v2 handling ensemble ───────────
#
# s10b_corners.run_handling_analysis_v2 defaults best_lap_number to 1 when
# not supplied. The orchestrator's Step 10g3 call never supplied it, even
# though best_lap_df passed alongside it is the ACTUAL best lap (from
# select_best_lap). So the 17-detector handling ensemble silently masked
# lap 1's telemetry against best_lap_df's data whenever the real best lap
# was not lap 1.


def test_handling_v2_receives_the_real_best_lap_number(tmp_path, _isolated_track_registry):
    """Drives the real orchestrator (same fixture shape as
    test_data_quality_report_survives_the_persistence_gate) with lap 2 built
    to be the faster lap, so lap 2 - not lap 1 - is the real best lap.
    Asserts run_handling_analysis_v2 is called with best_lap_number=2, not
    left to fall back to the callee's own hardcoded default of 1.
    """
    from unittest.mock import MagicMock, patch

    import pipeline
    from pipeline.stages import s10b_corners

    n = 500
    half = n // 2
    laps = np.repeat([1, 2], half)
    # Lap 1 spans 60s (slow); lap 2 spans 40s (fast) - lap 2 is the real
    # best lap, deliberately NOT lap 1.
    time = np.concatenate([
        np.linspace(0.0, 60.0, half),
        np.linspace(0.0, 40.0, half),
    ])
    speed = np.random.default_rng(42).uniform(10, 30, n)
    dist = np.concatenate([
        np.cumsum(speed[:half] * np.diff(np.concatenate([[0.0], time[:half]]))),
        np.cumsum(speed[half:] * np.diff(np.concatenate([[0.0], time[half:]]))),
    ])
    lat = np.linspace(45.0, 45.001, n)
    lon = np.linspace(9.0, 9.001, n)

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
    })
    csv_path = tmp_path / "handling_best_lap.csv"
    df.to_csv(csv_path, index=False)

    # Force the v2-sections gate open (Step 10g3 is skipped entirely when
    # v2_sections is falsy) without depending on real corner detection.
    fake_sections = [
        {"corner_id": 1, "corner_type": "auto", "s_start": 10.0, "s_end": 20.0},
    ]
    handling_mock = MagicMock(return_value=None)

    with patch.object(
        s10b_corners, "run_track_decomposition_v2", return_value=fake_sections
    ), patch.object(s10b_corners, "run_handling_analysis_v2", handling_mock):
        summary = pipeline.run_full_analysis(str(csv_path), {})

    assert summary.get("best_lap_key") == 2, (
        "fixture setup invalid - expected lap 2 (the faster lap) to be "
        f"selected as best lap, got {summary.get('best_lap_key')!r}"
    )
    handling_mock.assert_called_once()
    _, kwargs = handling_mock.call_args
    assert kwargs.get("best_lap_number") == 2, (
        "run_handling_analysis_v2 was not called with the real best lap "
        f"number (2) - got kwargs={kwargs!r}. The callee silently defaults "
        "missing best_lap_number to 1, which is the bug this test guards "
        "against: the 17-detector handling ensemble would mask lap 1's "
        "telemetry against best_lap_df's data whenever the real best lap "
        "wasn't lap 1."
    )


# ── Final review I1: the Celery-side cache invalidation must actually run ──
#
# pipeline_finalize invalidates the chart cache (Task 10), but chart_cache's
# _get_redis started with `getattr(g, "_redis", None)`. getattr's default only
# swallows AttributeError, and Flask's `g` raises RuntimeError when there is
# no application context. Celery workers have none, so the invalidation raised,
# was swallowed by its own try/except in pipeline_tasks, and cleared nothing.
# These tests exercise invalidate_session_cache with NO app context and assert
# the Redis scan/delete path was genuinely reached.


def test_invalidate_session_cache_reaches_redis_without_a_flask_app_context():
    """The Celery-worker path: no app context, so _get_redis must construct a
    client directly instead of exploding on flask.g."""
    from unittest.mock import MagicMock, patch

    import flask

    from web import chart_cache

    assert not flask.has_app_context(), (
        "this test is only meaningful outside a Flask application context"
    )

    fake_redis = MagicMock()
    fake_redis.scan_iter.return_value = iter(["chart:sess-x:corners:default",
                                              "chart:sess-x:speed_trace:default"])
    fake_redis.delete.return_value = 2

    with patch("redis.Redis.from_url", return_value=fake_redis) as from_url:
        deleted = chart_cache.invalidate_session_cache("sess-x")

    from_url.assert_called_once()
    fake_redis.scan_iter.assert_called_once()
    assert fake_redis.scan_iter.call_args.kwargs["match"] == "chart:sess-x:*", (
        "invalidation ran against the wrong key pattern"
    )
    fake_redis.delete.assert_called_once_with(
        "chart:sess-x:corners:default", "chart:sess-x:speed_trace:default"
    )
    assert deleted == 2, (
        "invalidate_session_cache returned 0 - the Redis path was never "
        "reached (a RuntimeError from flask.g was silently swallowed)"
    )


def test_invalidate_session_cache_still_prefers_the_app_context_client():
    """Inside a request the pooled client is still reused - the no-context
    fallback must not bypass it and open a second connection."""
    from unittest.mock import MagicMock, patch

    from flask import Flask

    from web import chart_cache

    app_redis = MagicMock()
    app_redis.scan_iter.return_value = iter(["chart:sess-y:corners:default"])
    app_redis.delete.return_value = 1

    app = Flask(__name__)
    app.extensions["redis"] = app_redis

    with app.app_context():
        with patch("redis.Redis.from_url") as from_url:
            deleted = chart_cache.invalidate_session_cache("sess-y")

    from_url.assert_not_called()
    app_redis.delete.assert_called_once_with("chart:sess-y:corners:default")
    assert deleted == 1


# ── Final review I2: the drop warning must not fire on a HEALTHY session ───
#
# np.linspace/np.digitize put a sample sitting exactly on the last bin edge
# (the reference lap's own final sample, d == d_max) at index n_bins - out of
# range - so the Task 7 warning fired on every correctly-framed session.
# Measured on real data: 1/953, 7/935, 2/948, 3/951 dropped, i.e. four WARNING
# lines per healthy session across five worker services. A real frame
# regression drops ~100% of a lap's samples, so the signal is distinguishable
# - but the noise would get the alarm filtered out inside a week, defeating
# Task 7 entirely.


def _healthy_grip_laps(rng) -> dict:
    """Three correctly-framed laps: all 0-based, spans differing by ~1%.

    Mirrors real data - OK_R4's per-lap spans are 1202.5 / 1218.0 / 1210.3 /
    1212.8 / 1198.6 m, so laps genuinely run a little past the reference lap's
    final edge and a handful of samples are legitimately dropped.
    """
    def _grip_lap(distances: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame({
            "Distance (m)": distances,
            "Lateral acceleration (G) *calc": 0.9 + rng.normal(
                0.0, 0.01, len(distances)
            ),
        })

    return {
        1: _grip_lap(np.linspace(0.0, 1202.5, 500)),
        2: _grip_lap(np.linspace(0.0, 1218.0, 500)),
        3: _grip_lap(np.linspace(0.0, 1198.6, 500)),
    }


def _grip_map_warnings(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.name == "grip_map" and r.levelno >= 30
    ]


def test_healthy_session_logs_no_grip_map_drop_warning(caplog):
    """Lateral-accel branch: a correctly-framed session must be silent."""
    import logging

    import grip_map

    laps = _healthy_grip_laps(np.random.default_rng(0))

    with caplog.at_level(logging.WARNING, logger="grip_map"):
        result = grip_map.compute_grip_map(laps, n_bins=20)

    assert not result.is_global_fallback
    assert _grip_map_warnings(caplog) == [], (
        "a healthy, correctly-framed session must produce ZERO drop warnings - "
        "otherwise alarm fatigue buries the real frame-regression signal"
    )


def test_reference_lap_right_edge_sample_is_binned_not_dropped():
    """The exact d == d_max sample is legitimately in frame and must land in
    the last bin. np.digitize's half-open intervals put it at index n_bins,
    which the naive range check dropped - one spurious drop per lap, per site.
    """
    import grip_map

    n = 500

    def _grip_lap(distances: np.ndarray) -> pd.DataFrame:
        # Constant mu on purpose: bin_stats.sample_count is len(clean), i.e.
        # POST-_iqr_reject, so any noise would let outlier rejection remove
        # samples too and this test could no longer attribute a shortfall to
        # the binning. With zero spread the IQR fence is degenerate and keeps
        # everything, making the count a pure measure of what got binned.
        return pd.DataFrame({
            "Distance (m)": distances,
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
        })

    # Every lap spans exactly the same 0-based range, so NOTHING is out of
    # frame and the total binned sample count must be exactly 3 x 500.
    laps = {k: _grip_lap(np.linspace(0.0, 1202.5, n)) for k in (1, 2, 3)}

    result = grip_map.compute_grip_map(laps, n_bins=20)

    assert not result.is_global_fallback
    total_binned = sum(s.sample_count for s in result.bin_stats)
    assert total_binned == 3 * n, (
        f"{3 * n - total_binned} sample(s) dropped from a session where every "
        "lap shares one frame - the exact right-edge sample (d == d_max) is "
        "being treated as out of range"
    )


def test_healthy_session_logs_no_grip_map_drop_warning_curvature_branch(caplog):
    """Same guarantee through grip_map's OTHER binning site: the
    curvature/speed branch, reached only when no lap carries a lateral-accel
    column and a curvature_profile is supplied."""
    import logging

    import grip_map

    curvature_profile = pd.DataFrame({
        "distance_m": [0.0, 1300.0],
        "curvature_1pm": [0.01, 0.01],
    })

    def _speed_lap(distances: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame({
            "Distance (m)": distances,
            "Speed (m/s)": np.full(len(distances), 20.0),
        })

    laps = {
        1: _speed_lap(np.linspace(0.0, 1202.5, 500)),
        2: _speed_lap(np.linspace(0.0, 1218.0, 500)),
        3: _speed_lap(np.linspace(0.0, 1198.6, 500)),
    }

    with caplog.at_level(logging.WARNING, logger="grip_map"):
        result = grip_map.compute_grip_map(
            laps, curvature_profile=curvature_profile, n_bins=20
        )

    assert result.source == "curvature_speed", (
        f"test fell through to source={result.source!r} instead of "
        "exercising the curvature/speed branch"
    )
    assert not result.is_global_fallback
    assert _grip_map_warnings(caplog) == [], (
        "a healthy, correctly-framed session must produce ZERO drop warnings "
        "on the curvature branch either"
    )


def test_out_of_frame_lap_still_warns(caplog):
    """The threshold must not silence the case Task 7 exists for: a lap that
    is entirely out of frame drops ~100% of its samples and must be loud."""
    import logging

    import grip_map

    rng = np.random.default_rng(2)

    def _grip_lap(distances: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame({
            "Distance (m)": distances,
            "Lateral acceleration (G) *calc": 0.9 + rng.normal(
                0.0, 0.01, len(distances)
            ),
        })

    laps = {
        1: _grip_lap(np.linspace(0.0, 1202.5, 500)),
        # Never rebased - still carrying cumulative session distance.
        2: _grip_lap(np.linspace(4997.9, 6196.5, 500)),
        3: _grip_lap(np.linspace(6196.5, 7395.1, 500)),
    }

    with caplog.at_level(logging.WARNING, logger="grip_map"):
        grip_map.compute_grip_map(laps, n_bins=20)

    warnings = _grip_map_warnings(caplog)
    assert len(warnings) == 2, (
        f"both out-of-frame laps must warn, got {warnings}"
    )
    assert all("500/500 samples (100.0%)" in w for w in warnings), warnings


# ── Final review M2: the two warnings' denominators must agree ─────────────
#
# The exception warning divided by len(sorted_keys) (every lap in the dict,
# including ones legitimately skipped) while the coverage warning divided by
# _attempted, and the comment claimed they were the same. Worse, a lap that
# raised AFTER appending some metrics landed in _failed_laps AND in the
# coverage numerator (which was recomputed from `results`), so the numerator
# could exceed its own denominator.


def test_per_lap_corner_warning_denominators_exclude_skipped_and_failed_laps(caplog):
    """Both warnings must count only laps that genuinely entered analysis,
    and a lap that raises must never also be counted as covered."""
    import logging
    import types
    from unittest.mock import patch

    from pipeline.stages import s10b_corners

    laps = {n: _lap(0.0, 100.0, n) for n in range(1, 9)}   # 8 laps present
    excluded = frozenset({7, 8})                           # 2 legitimately skipped
    corners = [{"corner_id": 1, "s_start": 10.0, "s_end": 20.0}]

    def fake_analyze_corners(corners_arg, driver_lap, theoretical_result, friction):
        lap_no = int(driver_lap["Lap #"].iloc[0])
        if lap_no == 1:
            # One usable metric, then a value the loop cannot convert
            # (dict(object()) raises TypeError). Lap 1 therefore RAISES while
            # having already appended partial output to `results`.
            return [{"time_loss_s": 0.1, "corner_id": 1}, object()]
        # Laps 2..6: no exception, but nothing to show for it - the shape of
        # the historical distance-frame incident.
        return []

    fake_ca_mod = types.SimpleNamespace(analyze_corners=fake_analyze_corners)

    with patch.object(s10b_corners, "lazy_import", return_value=fake_ca_mod), \
         caplog.at_level(logging.WARNING):
        results = s10b_corners.run_per_lap_corner_metrics(
            corners, laps, excluded_laps=excluded,
        )

    # Partial output from the failed lap is retained - dropping it would be a
    # data change, and this is a logging fix.
    assert {r["lap_number"] for r in results} == {1}

    # 6 laps were attempted (8 minus the 2 excluded), 1 of them raised.
    assert "1/6" in caplog.text, (
        "exception warning must divide by attempted laps (6), not by every "
        f"lap in the dict (8): {caplog.text}"
    )
    assert "1/8" not in caplog.text, (
        f"exception warning is still counting legitimately skipped laps: {caplog.text}"
    )

    # 5 laps did not raise; NONE of them produced a metric. Lap 1 produced one
    # but raised, so it belongs to the exception tally only.
    assert "0/5" in caplog.text, (
        "coverage warning must report 0 covered of the 5 laps that did not "
        f"raise: {caplog.text}"
    )
    assert "1/5" not in caplog.text, (
        "the lap that raised is being double-counted as covered, which is how "
        f"the coverage numerator could exceed its denominator: {caplog.text}"
    )
