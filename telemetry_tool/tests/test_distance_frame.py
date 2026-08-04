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
