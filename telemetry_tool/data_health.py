"""
data_health.py
--------------
Compute data health / quality metrics for telemetry sessions.

Aggregates GPS quality, accelerometer quality, channel completeness,
data gaps, and produces an overall 0-100 quality score.

Reuses existing ``data_quality.py`` diagnostics where possible.

Public API
~~~~~~~~~~
``compute_data_health(resampled_laps, raw_df, dq_report)``
    Aggregate health metrics from pipeline data.

``compute_data_health_from_session(conn, session_id)``
    Recompute health from stored session data (for batch processing).

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust: missing data degrades individual scores, not the whole result.
- Deterministic: identical inputs → identical outputs.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── GPS quality scoring ─────────────────────────────────────────

def _score_gps_quality(
    resampled_laps: dict[int, pd.DataFrame],
) -> tuple[float, dict[str, Any]]:
    """
    Score GPS data quality from 0-100.

    Checks: presence of lat/lon columns, NaN ratio, coordinate jitter,
    and point density.
    """
    if not resampled_laps:
        return 0.0, {"reason": "no_laps"}

    lat_col = lon_col = None
    sample_df = next(iter(resampled_laps.values()))
    for c in sample_df.columns:
        cl = c.lower()
        if "latitude" in cl and "deg" in cl:
            lat_col = c
        elif "longitude" in cl and "deg" in cl:
            lon_col = c

    if lat_col is None or lon_col is None:
        return 0.0, {"reason": "no_gps_columns"}

    nan_ratios = []
    jitter_values = []
    point_counts = []

    for lap_num, df in resampled_laps.items():
        if lat_col not in df.columns or lon_col not in df.columns:
            continue

        lats = pd.to_numeric(df[lat_col], errors="coerce")
        lons = pd.to_numeric(df[lon_col], errors="coerce")

        n_total = len(lats)
        point_counts.append(n_total)

        # NaN ratio
        n_nan = int(lats.isna().sum() + lons.isna().sum())
        nan_ratios.append(n_nan / max(2 * n_total, 1))

        # Jitter: std of diff (lower = smoother = better)
        lat_clean = lats.dropna().values
        lon_clean = lons.dropna().values
        if len(lat_clean) > 2:
            lat_jitter = float(np.std(np.diff(lat_clean)))
            lon_jitter = float(np.std(np.diff(lon_clean)))
            jitter_values.append((lat_jitter + lon_jitter) / 2)

    if not point_counts:
        return 0.0, {"reason": "no_valid_laps"}

    # Score components
    avg_nan_ratio = float(np.mean(nan_ratios))
    nan_score = max(0, 100 * (1 - avg_nan_ratio * 5))  # 20% NaN = 0

    avg_points = float(np.mean(point_counts))
    density_score = min(100, avg_points / 2)  # 200+ points = full

    jitter_score = 100.0
    if jitter_values:
        avg_jitter = float(np.mean(jitter_values))
        # Typical good jitter: < 0.00001; bad: > 0.0005
        jitter_score = max(0, min(100, 100 * (1 - avg_jitter / 0.0003)))

    overall = 0.4 * nan_score + 0.3 * density_score + 0.3 * jitter_score

    return round(overall, 1), {
        "nan_ratio": round(avg_nan_ratio, 4),
        "avg_points": round(avg_points, 0),
        "jitter": round(float(np.mean(jitter_values)), 8) if jitter_values else None,
        "nan_score": round(nan_score, 1),
        "density_score": round(density_score, 1),
        "jitter_score": round(jitter_score, 1),
    }


# ── Accelerometer quality scoring ──────────────────────────────

def _score_accel_quality(
    resampled_laps: dict[int, pd.DataFrame],
) -> tuple[float, dict[str, Any]]:
    """
    Score accelerometer data quality from 0-100.

    Checks: presence of accel columns, NaN ratio, reasonable value ranges.
    """
    if not resampled_laps:
        return 0.0, {"reason": "no_laps"}

    sample_df = next(iter(resampled_laps.values()))

    # Find accel columns
    accel_cols = []
    for c in sample_df.columns:
        cl = c.lower()
        if "accel" in cl or "braking" in cl or "jerk" in cl:
            accel_cols.append(c)

    if not accel_cols:
        return 0.0, {"reason": "no_accel_columns", "columns_found": []}

    nan_ratios = []
    range_scores = []

    for lap_num, df in resampled_laps.items():
        for col in accel_cols:
            if col not in df.columns:
                continue
            vals = pd.to_numeric(df[col], errors="coerce")
            n_total = len(vals)
            n_nan = int(vals.isna().sum())
            nan_ratios.append(n_nan / max(n_total, 1))

            # Check for reasonable ranges
            clean = vals.dropna().values
            if len(clean) > 0:
                val_range = float(np.ptp(clean))
                # Accel should have some variation (not all zeros)
                if val_range < 0.01:
                    range_scores.append(0.0)
                else:
                    range_scores.append(min(100, val_range * 20))

    avg_nan = float(np.mean(nan_ratios)) if nan_ratios else 1.0
    nan_score = max(0, 100 * (1 - avg_nan * 5))

    avg_range = float(np.mean(range_scores)) if range_scores else 0
    column_count = len(accel_cols)
    completeness = min(100, column_count * 20)  # 5+ accel cols = full

    overall = 0.4 * nan_score + 0.3 * avg_range + 0.3 * completeness

    return round(overall, 1), {
        "columns": accel_cols,
        "column_count": column_count,
        "nan_ratio": round(avg_nan, 4),
        "nan_score": round(nan_score, 1),
        "range_score": round(avg_range, 1),
        "completeness_score": round(completeness, 1),
    }


# ── Channel completeness ──────────────────────────────────────

_EXPECTED_CHANNELS = [
    "speed", "latitude", "longitude", "distance",
    "accel", "braking", "lateral", "jerk", "yaw",
]


def _score_channel_completeness(
    resampled_laps: dict[int, pd.DataFrame],
) -> tuple[int, list[str], float]:
    """
    Count available channels and identify missing ones.

    Returns (channel_count, missing_channels, completeness_pct).
    """
    if not resampled_laps:
        return 0, list(_EXPECTED_CHANNELS), 0.0

    sample_df = next(iter(resampled_laps.values()))
    all_cols_lower = {c.lower() for c in sample_df.columns}

    found = 0
    missing = []
    for expected in _EXPECTED_CHANNELS:
        if any(expected in col for col in all_cols_lower):
            found += 1
        else:
            missing.append(expected)

    completeness = (found / len(_EXPECTED_CHANNELS)) * 100
    return len(sample_df.columns), missing, round(completeness, 1)


# ── Data gap detection ────────────────────────────────────────

def _count_data_gaps(
    resampled_laps: dict[int, pd.DataFrame],
    gap_threshold: int = 5,
) -> tuple[int, int]:
    """
    Count data gaps (runs of NaN values longer than threshold).

    Returns (gap_count, total_samples).
    """
    total_gaps = 0
    total_samples = 0

    for lap_num, df in resampled_laps.items():
        total_samples += len(df)
        for col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            is_nan = vals.isna().values
            gap_len = 0
            for v in is_nan:
                if v:
                    gap_len += 1
                else:
                    if gap_len >= gap_threshold:
                        total_gaps += 1
                    gap_len = 0
            if gap_len >= gap_threshold:
                total_gaps += 1

    return total_gaps, total_samples


# ── Main entry point ───────────────────────────────────────────

def compute_data_health(
    resampled_laps: dict[int, pd.DataFrame],
    raw_df: Optional[pd.DataFrame] = None,
    dq_report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Compute comprehensive data health metrics for a session.

    Parameters
    ----------
    resampled_laps : dict
        Distance-resampled lap DataFrames keyed by lap number.
    raw_df : DataFrame, optional
        Raw CSV data (for additional diagnostics).
    dq_report : dict, optional
        Existing data quality report from pipeline.

    Returns
    -------
    dict with keys:
        gps_quality, accel_quality, channel_count, missing_channels,
        data_gaps, total_samples, overall_score, report_json
    """
    result: dict[str, Any] = {
        "gps_quality": 0.0,
        "accel_quality": 0.0,
        "channel_count": 0,
        "missing_channels": "",
        "data_gaps": 0,
        "total_samples": 0,
        "overall_score": 0.0,
        "report_json": "{}",
    }

    if not resampled_laps:
        logger.warning("No resampled laps for data health computation.")
        result["report_json"] = json.dumps({"error": "no_data"})
        return result

    # GPS quality
    gps_score, gps_detail = _score_gps_quality(resampled_laps)
    result["gps_quality"] = gps_score

    # Accelerometer quality
    accel_score, accel_detail = _score_accel_quality(resampled_laps)
    result["accel_quality"] = accel_score

    # Channel completeness
    ch_count, missing, completeness_pct = _score_channel_completeness(resampled_laps)
    result["channel_count"] = ch_count
    result["missing_channels"] = ",".join(missing) if missing else ""

    # Data gaps
    gaps, total = _count_data_gaps(resampled_laps)
    result["data_gaps"] = gaps
    result["total_samples"] = total

    # Overall score: weighted average
    overall = (
        0.30 * gps_score
        + 0.25 * accel_score
        + 0.25 * completeness_pct
        + 0.20 * max(0, 100 - gaps * 5)  # penalise gaps
    )
    result["overall_score"] = round(min(100, max(0, overall)), 1)

    # Detailed report
    report = {
        "gps": gps_detail,
        "accel": accel_detail,
        "channels": {
            "count": ch_count,
            "missing": missing,
            "completeness_pct": completeness_pct,
        },
        "gaps": {
            "count": gaps,
            "total_samples": total,
        },
    }

    # Include DQ report if available
    if dq_report:
        report["dq_report"] = dq_report

    result["report_json"] = json.dumps(report, default=str)

    logger.info(
        "Data health: GPS=%.1f, Accel=%.1f, Channels=%d (missing: %s), "
        "Gaps=%d, Overall=%.1f",
        gps_score, accel_score, ch_count,
        ",".join(missing) if missing else "none",
        gaps, result["overall_score"],
    )
    return result


# ── Inline tests ────────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite."""
    import traceback as tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, tb.format_exc()))

    # Test 1: empty data
    def t_empty():
        result = compute_data_health({})
        assert result["overall_score"] == 0.0
        assert result["gps_quality"] == 0.0

    _test("empty_data", t_empty)

    # Test 2: clean GPS data
    def t_clean_gps():
        laps = {}
        for i in range(3):
            laps[i + 1] = pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 200),
                "Latitude (deg)": np.linspace(45.0, 45.01, 200),
                "Longitude (deg)": np.linspace(7.0, 7.01, 200),
                "speed_mps": np.random.uniform(10, 30, 200),
                "braking_mps2": np.random.uniform(-5, 0, 200),
                "lat_accel_mps2": np.random.uniform(-2, 2, 200),
                "jerk_mps3": np.random.uniform(-5, 5, 200),
                "yaw_rate_dps": np.random.uniform(-30, 30, 200),
            })
        result = compute_data_health(laps)
        assert result["gps_quality"] > 50, f"GPS quality too low: {result['gps_quality']}"
        assert result["overall_score"] > 40, f"Overall too low: {result['overall_score']}"
        assert result["channel_count"] > 0

    _test("clean_gps", t_clean_gps)

    # Test 3: missing GPS columns
    def t_no_gps():
        laps = {
            1: pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 100),
                "speed_mps": np.random.uniform(10, 30, 100),
            })
        }
        result = compute_data_health(laps)
        assert result["gps_quality"] == 0.0

    _test("no_gps_columns", t_no_gps)

    # Test 4: data with NaN gaps
    def t_nan_gaps():
        lats = np.linspace(45.0, 45.01, 200)
        lats[50:60] = np.nan  # 10-sample gap
        laps = {
            1: pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 200),
                "Latitude (deg)": lats,
                "Longitude (deg)": np.linspace(7.0, 7.01, 200),
                "speed_mps": np.random.uniform(10, 30, 200),
            })
        }
        result = compute_data_health(laps)
        assert result["data_gaps"] >= 1
        assert result["gps_quality"] < 100

    _test("nan_gaps", t_nan_gaps)

    # Test 5: corrupt accel (all zeros)
    def t_corrupt_accel():
        laps = {
            1: pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 100),
                "Latitude (deg)": np.linspace(45.0, 45.01, 100),
                "Longitude (deg)": np.linspace(7.0, 7.01, 100),
                "speed_mps": np.random.uniform(10, 30, 100),
                "braking_mps2": np.zeros(100),
                "accel_mps2": np.zeros(100),
            })
        }
        result = compute_data_health(laps)
        assert result["accel_quality"] < 55, f"Corrupt accel scored too high: {result['accel_quality']}"

    _test("corrupt_accel", t_corrupt_accel)

    # Test 6: report_json is valid JSON
    def t_report_json():
        laps = {
            1: pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 100),
                "speed_mps": np.random.uniform(10, 30, 100),
            })
        }
        result = compute_data_health(laps)
        report = json.loads(result["report_json"])
        assert isinstance(report, dict)

    _test("report_json_valid", t_report_json)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nData Health Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
