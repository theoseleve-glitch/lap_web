"""Corner spans must never come back inverted (s_end < s_start).

Every window mask in this codebase -- 44 of them, across coaching, corner
analysis, deltas, persistence and driving events -- is of the form
``(d >= s_start) & (d <= s_end)``. That expression is EMPTY for an inverted
span, so a corner reported as ``s_start=244, s_end=226`` silently produces no
corner metrics, no coaching, no deltas and no driving events, while every
stage still reports success.

That is exactly what happened in production. A real KCT session detected one
corner at ``s_start=244.14, s_end=225.98`` on a 385.9 m lap, because the
detector merged the first and last curvature regions into a single
``wrapped=True`` region and then dropped the ``wrapped`` flag when building
its output dict. ``corner_metrics`` got 0 rows; all four driving-event
detectors reported ``insufficient``.

`corner_detection` already had an invariant test for this
(``t_valid_extents``: "s_end > s_start for all corners"). It never fired,
because its fixture lays corners out along ``linspace(0, LAP_LENGTH_M)`` and
cannot produce one that straddles the start/finish line. The guarantee was
asserted only on inputs incapable of breaking it -- which is why this file
builds a lap that specifically DOES straddle the boundary.
"""
import numpy as np
import pandas as pd
import pytest

import corner_detection


def _lap_with_corner_across_the_line(lap_len_m: float = 386.0,
                                     n: int = 1000) -> pd.DataFrame:
    """A closed lap with real straights and a corner sitting on the boundary.

    Two narrow curvature bumps -- one just after the start line, one just
    before it -- with low curvature between them, plus one ordinary mid-lap
    corner. The two boundary bumps are the two halves of a single physical
    corner that straddles start/finish, and their wrap gap is ~0 m, which is
    precisely the condition the removed merge step used to act on.

    The straights matter: the detector's adaptive threshold is a PERCENTILE of
    the lap's own curvature, so a uniformly-curved lap has nothing above its
    own p85 and yields no corners at all. `corner_detection`'s own fixture
    lays corners along linspace and never straddles the boundary, which is why
    its `s_end > s_start` invariant test could not catch this.
    """
    dist = np.linspace(0.0, lap_len_m, n)
    frac = dist / lap_len_m

    def bump(centre: float, width: float = 0.03) -> np.ndarray:
        return np.exp(-((frac - centre) ** 2) / (2 * width ** 2))

    curvature = (
        0.001                      # straight
        + 0.12 * bump(0.04)        # just after the line
        + 0.12 * bump(0.96)        # just before it -- same physical corner
        + 0.10 * bump(0.50)        # an ordinary mid-lap corner
    )
    speed = np.full(n, 14.0)
    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "yaw_rate_dps": np.degrees(curvature * speed),
    })


def _spans(corners):
    return [(c["corner_id"], c["s_start"], c["s_end"]) for c in corners]


def test_a_corner_across_the_start_finish_line_is_not_inverted():
    df = _lap_with_corner_across_the_line()
    corners = corner_detection.detect_corners(df)
    assert corners, "expected at least one corner on a lap built entirely of corner"
    inverted = [(cid, s, e) for cid, s, e in _spans(corners) if e < s]
    assert not inverted, (
        "corner span(s) came back with s_end < s_start: "
        f"{inverted}. Every window mask in this codebase is "
        "(d >= s_start) & (d <= s_end), which is EMPTY for such a span -- "
        "the corner silently yields no metrics, no coaching and no events."
    )


def test_every_span_has_positive_length():
    df = _lap_with_corner_across_the_line()
    for cid, s, e in _spans(corner_detection.detect_corners(df)):
        assert e > s, f"corner {cid}: zero or negative length ({s} -> {e})"


def test_spans_stay_inside_the_lap():
    df = _lap_with_corner_across_the_line()
    lo = float(df["Distance (m)"].min())
    hi = float(df["Distance (m)"].max())
    for cid, s, e in _spans(corner_detection.detect_corners(df)):
        assert lo <= s <= hi, f"corner {cid}: s_start {s} outside [{lo}, {hi}]"
        assert lo <= e <= hi, f"corner {cid}: s_end {e} outside [{lo}, {hi}]"


def test_an_ordinary_mid_lap_corner_is_unaffected():
    """The boundary fix must not disturb the normal case."""
    dist = np.linspace(0.0, 400.0, 1000)
    frac = dist / 400.0
    # single hump in the middle of the lap, flat at both ends
    curvature = 0.09 * np.exp(-((frac - 0.5) ** 2) / (2 * 0.02)) + 0.001
    df = pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": np.full(1000, 14.0),
        "yaw_rate_dps": np.degrees(curvature * 14.0),
    })
    corners = corner_detection.detect_corners(df)
    assert corners, "a clear mid-lap corner should still be detected"
    for cid, s, e in _spans(corners):
        assert e > s
        assert 0.0 <= s <= 400.0 and 0.0 <= e <= 400.0


def _lap_with_shallow_gaps(lap_len_m: float = 400.0, n: int = 1000) -> pd.DataFrame:
    """Three corners separated by SHALLOW gaps rather than true straights.

    At a strict threshold the gaps fall below the bar and three corners
    separate cleanly. Relax the threshold and the gaps clear it too, so the
    three merge into one blob spanning most of the lap. This is the shape
    that made the adaptive retry counter-productive on a real KCT lap.
    """
    dist = np.linspace(0.0, lap_len_m, n)
    frac = dist / lap_len_m

    def bump(centre: float, width: float = 0.035) -> np.ndarray:
        return np.exp(-((frac - centre) ** 2) / (2 * width ** 2))

    curvature = 0.02 + 0.10 * (bump(0.15) + bump(0.50) + bump(0.85))
    speed = np.full(n, 14.0)
    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "yaw_rate_dps": np.degrees(curvature * speed),
    })


def test_relaxing_the_threshold_merges_rather_than_splits_on_this_lap():
    """Pins the premise the next test depends on -- not the behaviour itself."""
    df = _lap_with_shallow_gaps()
    strict = corner_detection.detect_corners(df, curvature_threshold=0.09)
    relaxed = corner_detection.detect_corners(df, curvature_threshold=0.045)
    assert len(strict) > len(relaxed), (
        "fixture no longer exhibits merge-on-relax "
        f"(strict={len(strict)}, relaxed={len(relaxed)}); the retry test below "
        "would then prove nothing"
    )


def test_the_adaptive_retry_is_not_allowed_to_lose_corners():
    """The retry exists to find MORE corners; if it finds fewer it must not win.

    It used to `return` the relaxed pass unconditionally. On a real KCT lap
    that turned 3 plausible corners (25-114, 173-219, 349-372) into 2 blobs
    spanning 59% and 37% of a 386 m lap -- so everything downstream measured
    "corners" that were really most of a lap.
    """
    df = _lap_with_shallow_gaps()
    strict = corner_detection.detect_corners(df, curvature_threshold=0.09)
    adaptive = corner_detection.detect_corners(df)
    assert len(adaptive) >= len(strict), (
        f"adaptive detection returned {len(adaptive)} corner(s) but a strict "
        f"threshold finds {len(strict)} on the same lap -- the relaxed retry "
        "was accepted despite finding fewer"
    )
