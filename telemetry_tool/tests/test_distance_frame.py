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
