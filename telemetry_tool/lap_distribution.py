"""
lap_distribution.py
-------------------
Lap Time Distribution Analysis — provides statistical distribution
metrics and histogram data for visualising lap time spread.

Core Features
~~~~~~~~~~~~~
1. **Histogram**: Bin lap times into configurable buckets with frequency counts.
2. **Quartile Analysis**: Q1, median, Q3, IQR, whiskers (box-plot data).
3. **Kernel Density Estimate**: Gaussian KDE for smooth distribution curve.
4. **Outlier Detection**: Flag laps beyond 1.5×IQR from Q1/Q3.
5. **Distribution Shape**: Skewness, kurtosis, modality detection.
6. **Coaching**: Context-aware insight about the distribution.

Public API
~~~~~~~~~~
- ``analyze_lap_distribution(lap_times, lap_numbers=None)``
- ``compute_histogram(values, n_bins=None)``
- ``compute_kde(values, n_points=100)``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

DEFAULT_N_BINS: Final[int] = 15
KDE_BANDWIDTH_FACTOR: Final[float] = 0.4  # Silverman factor multiplier
KDE_N_POINTS: Final[int] = 100
OUTLIER_IQR_FACTOR: Final[float] = 1.5
BIMODAL_DIP_THRESHOLD: Final[float] = 0.15  # relative dip to detect bimodality


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class HistogramBin:
    """A single histogram bin."""
    bin_start: float = 0.0
    bin_end: float = 0.0
    bin_center: float = 0.0
    count: int = 0
    frequency: float = 0.0  # count / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "bin_start": round(self.bin_start, 4),
            "bin_end": round(self.bin_end, 4),
            "bin_center": round(self.bin_center, 4),
            "count": self.count,
            "frequency": round(self.frequency, 4),
        }


@dataclass
class QuartileStats:
    """Box-plot statistics."""
    q1: float = 0.0
    median: float = 0.0
    q3: float = 0.0
    iqr: float = 0.0
    lower_whisker: float = 0.0
    upper_whisker: float = 0.0
    lower_fence: float = 0.0
    upper_fence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "q1": round(self.q1, 4),
            "median": round(self.median, 4),
            "q3": round(self.q3, 4),
            "iqr": round(self.iqr, 4),
            "lower_whisker": round(self.lower_whisker, 4),
            "upper_whisker": round(self.upper_whisker, 4),
            "lower_fence": round(self.lower_fence, 4),
            "upper_fence": round(self.upper_fence, 4),
        }


@dataclass
class OutlierLap:
    """A lap flagged as an outlier."""
    lap_number: int = 0
    lap_time_s: float = 0.0
    deviation_s: float = 0.0
    direction: str = ""  # "slow" or "fast"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_number": self.lap_number,
            "lap_time_s": round(self.lap_time_s, 4),
            "deviation_s": round(self.deviation_s, 4),
            "direction": self.direction,
        }


@dataclass
class LapDistributionResult:
    """Full distribution analysis result."""
    n_laps: int = 0
    mean_s: float = 0.0
    std_s: float = 0.0
    min_s: float = 0.0
    max_s: float = 0.0
    range_s: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    shape: str = ""  # "normal", "left_skewed", "right_skewed", "bimodal", "tight"
    quartiles: QuartileStats = field(default_factory=QuartileStats)
    histogram: list[HistogramBin] = field(default_factory=list)
    kde_x: list[float] = field(default_factory=list)
    kde_y: list[float] = field(default_factory=list)
    outliers: list[OutlierLap] = field(default_factory=list)
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps": self.n_laps,
            "mean_s": round(self.mean_s, 4),
            "std_s": round(self.std_s, 4),
            "min_s": round(self.min_s, 4),
            "max_s": round(self.max_s, 4),
            "range_s": round(self.range_s, 4),
            "skewness": round(self.skewness, 3),
            "kurtosis": round(self.kurtosis, 3),
            "shape": self.shape,
            "quartiles": self.quartiles.to_dict(),
            "histogram": [b.to_dict() for b in self.histogram],
            "kde_x": [round(x, 4) for x in self.kde_x],
            "kde_y": [round(y, 6) for y in self.kde_y],
            "outliers": [o.to_dict() for o in self.outliers],
            "coaching": self.coaching,
        }


# ============================================================================
# Core Functions
# ============================================================================


def compute_histogram(
    values: list[float],
    n_bins: int | None = None,
) -> list[HistogramBin]:
    """Compute histogram bins from values."""
    if not values:
        return []

    arr = np.array(values, dtype=float)
    if n_bins is None:
        # Sturges' rule with a minimum
        n_bins = max(5, min(DEFAULT_N_BINS, int(np.ceil(np.log2(len(arr)) + 1))))

    counts, edges = np.histogram(arr, bins=n_bins)
    total = len(arr)
    bins = []
    for i in range(len(counts)):
        bins.append(HistogramBin(
            bin_start=float(edges[i]),
            bin_end=float(edges[i + 1]),
            bin_center=float((edges[i] + edges[i + 1]) / 2),
            count=int(counts[i]),
            frequency=float(counts[i]) / total if total > 0 else 0.0,
        ))
    return bins


def compute_kde(
    values: list[float],
    n_points: int = KDE_N_POINTS,
) -> tuple[list[float], list[float]]:
    """Compute Gaussian kernel density estimate."""
    if len(values) < 3:
        return [], []

    arr = np.array(values, dtype=float)
    std = float(np.std(arr, ddof=1))
    if std < 1e-10:
        # All identical — degenerate case
        return [float(arr[0])], [1.0]

    # Silverman's rule of thumb
    n = len(arr)
    bandwidth = KDE_BANDWIDTH_FACTOR * std * (n ** (-1 / 5))

    x_min = float(arr.min()) - 3 * bandwidth
    x_max = float(arr.max()) + 3 * bandwidth
    x = np.linspace(x_min, x_max, n_points)

    # Gaussian kernel
    kde = np.zeros(n_points)
    for v in arr:
        kde += np.exp(-0.5 * ((x - v) / bandwidth) ** 2)
    kde /= (n * bandwidth * np.sqrt(2 * np.pi))

    return [float(xi) for xi in x], [float(yi) for yi in kde]


def compute_quartiles(values: list[float]) -> QuartileStats:
    """Compute quartile statistics for box-plot."""
    if not values:
        return QuartileStats()

    arr = np.array(sorted(values), dtype=float)
    q1 = float(np.percentile(arr, 25))
    median = float(np.percentile(arr, 50))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1

    lower_fence = q1 - OUTLIER_IQR_FACTOR * iqr
    upper_fence = q3 + OUTLIER_IQR_FACTOR * iqr

    # Whiskers are the most extreme non-outlier values
    lower_whisker = float(arr[arr >= lower_fence].min()) if np.any(arr >= lower_fence) else float(arr.min())
    upper_whisker = float(arr[arr <= upper_fence].max()) if np.any(arr <= upper_fence) else float(arr.max())

    return QuartileStats(
        q1=q1, median=median, q3=q3, iqr=iqr,
        lower_whisker=lower_whisker, upper_whisker=upper_whisker,
        lower_fence=lower_fence, upper_fence=upper_fence,
    )


def detect_outliers(
    lap_times: list[float],
    lap_numbers: list[int],
    quartiles: QuartileStats,
) -> list[OutlierLap]:
    """Detect outlier laps using IQR method."""
    outliers = []
    for lt, ln in zip(lap_times, lap_numbers):
        if lt < quartiles.lower_fence:
            outliers.append(OutlierLap(
                lap_number=ln,
                lap_time_s=lt,
                deviation_s=quartiles.lower_fence - lt,
                direction="fast",
            ))
        elif lt > quartiles.upper_fence:
            outliers.append(OutlierLap(
                lap_number=ln,
                lap_time_s=lt,
                deviation_s=lt - quartiles.upper_fence,
                direction="slow",
            ))
    return outliers


def classify_shape(
    skewness: float,
    kurtosis: float,
    kde_y: list[float],
    std: float,
    mean: float,
) -> str:
    """Classify distribution shape."""
    # Check for tight cluster
    if mean > 0 and (std / mean) < 0.005:
        return "tight"

    # Check for bimodality (dip in KDE)
    if len(kde_y) > 10:
        max_y = max(kde_y)
        if max_y > 0:
            # Look for a dip > threshold between two peaks
            peaks = []
            for i in range(1, len(kde_y) - 1):
                if kde_y[i] > kde_y[i - 1] and kde_y[i] > kde_y[i + 1]:
                    peaks.append((i, kde_y[i]))
            if len(peaks) >= 2:
                # Check dip between first two peaks
                p0, p1 = peaks[0], peaks[1]
                dip = min(kde_y[p0[0]:p1[0] + 1])
                avg_peak = (p0[1] + p1[1]) / 2
                if avg_peak > 0 and (avg_peak - dip) / avg_peak > BIMODAL_DIP_THRESHOLD:
                    return "bimodal"

    if skewness > 0.5:
        return "right_skewed"
    if skewness < -0.5:
        return "left_skewed"
    return "normal"


def _generate_coaching(result: LapDistributionResult) -> str:
    """Generate coaching insight from distribution analysis."""
    parts = []

    if result.shape == "tight":
        parts.append("Exceptionally consistent lap times with minimal spread.")
    elif result.shape == "bimodal":
        parts.append("Distribution shows two pace modes — possible setup change, tyre switch, or warm-up phase.")
    elif result.shape == "right_skewed":
        parts.append("A few slower laps pull the distribution right — check for traffic or mistakes on those laps.")
    elif result.shape == "left_skewed":
        parts.append("Most laps cluster toward the slower end with a few fast outliers — the fast pace is achievable but not yet repeatable.")
    else:
        parts.append("Symmetrical lap time distribution around the median.")

    n_out = len(result.outliers)
    if n_out > 0:
        slow_out = sum(1 for o in result.outliers if o.direction == "slow")
        fast_out = n_out - slow_out
        if slow_out > 0:
            parts.append(f"{slow_out} slow outlier(s) detected — review those laps for incidents or errors.")
        if fast_out > 0:
            parts.append(f"{fast_out} unusually fast lap(s) — could indicate favorable conditions or drafting.")

    if result.quartiles.iqr > 0 and result.mean_s > 0:
        iqr_pct = (result.quartiles.iqr / result.mean_s) * 100
        if iqr_pct < 0.5:
            parts.append("The IQR is very tight — excellent pace control.")
        elif iqr_pct > 2.0:
            parts.append(f"Wide IQR ({iqr_pct:.1f}% of mean pace) suggests room for consistency improvement.")

    return " ".join(parts)


def analyze_lap_distribution(
    lap_times: list[float],
    lap_numbers: list[int] | None = None,
) -> LapDistributionResult:
    """
    Full lap time distribution analysis.

    Parameters
    ----------
    lap_times:
        List of valid lap times in seconds.
    lap_numbers:
        Optional corresponding lap numbers (defaults to 1..N).

    Returns
    -------
    LapDistributionResult
    """
    result = LapDistributionResult()

    # Filter valid values
    valid_pairs = []
    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    for lt, ln in zip(lap_times, lap_numbers):
        if lt is not None and math.isfinite(lt) and lt > 0:
            valid_pairs.append((lt, ln))

    if len(valid_pairs) < 2:
        result.coaching = "Not enough valid laps for distribution analysis."
        return result

    times = [p[0] for p in valid_pairs]
    numbers = [p[1] for p in valid_pairs]
    arr = np.array(times, dtype=float)

    result.n_laps = len(times)
    result.mean_s = float(np.mean(arr))
    result.std_s = float(np.std(arr, ddof=1))
    result.min_s = float(arr.min())
    result.max_s = float(arr.max())
    result.range_s = result.max_s - result.min_s

    # Skewness & kurtosis (Fisher)
    if result.std_s > 1e-10:
        centered = arr - result.mean_s
        n = len(arr)
        m3 = float(np.mean(centered ** 3))
        m4 = float(np.mean(centered ** 4))
        result.skewness = m3 / (result.std_s ** 3) if result.std_s > 0 else 0.0
        result.kurtosis = (m4 / (result.std_s ** 4)) - 3.0 if result.std_s > 0 else 0.0

    # Histogram
    result.histogram = compute_histogram(times)

    # KDE
    result.kde_x, result.kde_y = compute_kde(times)

    # Quartiles
    result.quartiles = compute_quartiles(times)

    # Outliers
    result.outliers = detect_outliers(times, numbers, result.quartiles)

    # Shape classification
    result.shape = classify_shape(
        result.skewness, result.kurtosis,
        result.kde_y, result.std_s, result.mean_s,
    )

    # Coaching
    result.coaching = _generate_coaching(result)

    logger.info(
        "Lap distribution: %d laps, shape=%s, mean=%.3fs, std=%.3fs, %d outliers",
        result.n_laps, result.shape, result.mean_s, result.std_s, len(result.outliers),
    )

    return result


# ============================================================================
# Self-Tests
# ============================================================================


def _run_tests() -> None:
    """Verify all functions with synthetic data."""
    import sys

    passed = 0
    failed = 0
    total = 14

    def _ok(name: str):
        nonlocal passed
        passed += 1
        print(f"  OK {name}")

    def _fail(name: str, msg: str):
        nonlocal failed
        failed += 1
        print(f"  FAIL {name}: {msg}")

    # 1. Basic histogram
    try:
        bins = compute_histogram([1.0, 2.0, 3.0, 4.0, 5.0], n_bins=5)
        assert len(bins) == 5, f"expected 5 bins, got {len(bins)}"
        total_count = sum(b.count for b in bins)
        assert total_count == 5, f"total count {total_count} != 5"
        freq_sum = sum(b.frequency for b in bins)
        assert abs(freq_sum - 1.0) < 0.01, f"freq sum {freq_sum}"
        _ok("histogram_basic")
    except Exception as e:
        _fail("histogram_basic", str(e))

    # 2. Histogram empty
    try:
        bins = compute_histogram([])
        assert bins == []
        _ok("histogram_empty")
    except Exception as e:
        _fail("histogram_empty", str(e))

    # 3. KDE basic
    try:
        x, y = compute_kde([60.0, 60.5, 61.0, 60.2, 60.8])
        assert len(x) == KDE_N_POINTS
        assert len(y) == KDE_N_POINTS
        assert max(y) > 0
        _ok("kde_basic")
    except Exception as e:
        _fail("kde_basic", str(e))

    # 4. KDE degenerate (all identical)
    try:
        x, y = compute_kde([50.0, 50.0, 50.0])
        assert len(x) == 1
        _ok("kde_degenerate")
    except Exception as e:
        _fail("kde_degenerate", str(e))

    # 5. Quartiles
    try:
        q = compute_quartiles([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        assert abs(q.median - 5.5) < 0.01, f"median {q.median}"
        assert q.q1 < q.median < q.q3
        assert q.iqr > 0
        _ok("quartiles")
    except Exception as e:
        _fail("quartiles", str(e))

    # 6. Outlier detection
    try:
        times = [60.0, 60.1, 60.2, 60.0, 60.1, 60.3, 60.1, 60.2, 60.0, 90.0]
        numbers = list(range(1, 11))
        q = compute_quartiles(times)
        outs = detect_outliers(times, numbers, q)
        assert len(outs) >= 1, f"expected outliers, got {len(outs)}"
        assert outs[-1].direction == "slow"
        assert outs[-1].lap_number == 10
        _ok("outlier_detection")
    except Exception as e:
        _fail("outlier_detection", str(e))

    # 7. Shape: right skewed
    try:
        # Many fast laps + a few slow ones
        times = [60.0] * 20 + [60.1] * 10 + [65.0, 66.0, 70.0]
        r = analyze_lap_distribution(times)
        assert r.skewness > 0.3, f"skewness {r.skewness} expected > 0.3"
        _ok("shape_right_skewed")
    except Exception as e:
        _fail("shape_right_skewed", str(e))

    # 8. Shape: tight cluster
    try:
        times = [60.001, 60.002, 60.001, 60.003, 60.002, 60.001, 60.002, 60.003]
        r = analyze_lap_distribution(times)
        assert r.shape == "tight", f"shape={r.shape}"
        _ok("shape_tight")
    except Exception as e:
        _fail("shape_tight", str(e))

    # 9. Full analysis basic
    try:
        times = [60.0 + i * 0.1 for i in range(20)]
        r = analyze_lap_distribution(times)
        assert r.n_laps == 20
        assert r.mean_s > 0
        assert r.std_s > 0
        assert len(r.histogram) > 0
        assert len(r.kde_x) > 0
        assert r.coaching != ""
        d = r.to_dict()
        assert "histogram" in d
        assert "kde_x" in d
        assert "quartiles" in d
        _ok("full_analysis")
    except Exception as e:
        _fail("full_analysis", str(e))

    # 10. NaN robustness
    try:
        times = [60.0, float("nan"), 61.0, None, 60.5, float("inf"), 60.2]
        numbers = [1, 2, 3, 4, 5, 6, 7]
        r = analyze_lap_distribution(times, numbers)
        assert r.n_laps == 4  # only valid ones
        assert r.mean_s > 0
        _ok("nan_robustness")
    except Exception as e:
        _fail("nan_robustness", str(e))

    # 11. Single lap
    try:
        r = analyze_lap_distribution([60.0])
        assert r.n_laps == 0  # needs >= 2
        assert "Not enough" in r.coaching
        _ok("single_lap")
    except Exception as e:
        _fail("single_lap", str(e))

    # 12. Serialization roundtrip
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8, 59.5, 60.3]
        r = analyze_lap_distribution(times)
        d = r.to_dict()
        assert isinstance(d["histogram"], list)
        assert isinstance(d["kde_x"], list)
        assert isinstance(d["outliers"], list)
        assert isinstance(d["quartiles"], dict)
        # Verify all values are JSON-serializable
        import json
        json.dumps(d)
        _ok("serialization")
    except Exception as e:
        _fail("serialization", str(e))

    # 13. Bimodal detection
    try:
        # Two clear clusters
        times = [60.0, 60.1, 60.0, 60.1, 60.0, 60.1, 60.0, 60.1,
                 65.0, 65.1, 65.0, 65.1, 65.0, 65.1, 65.0, 65.1]
        r = analyze_lap_distribution(times)
        assert r.shape == "bimodal", f"shape={r.shape}, expected bimodal"
        _ok("bimodal_detection")
    except Exception as e:
        _fail("bimodal_detection", str(e))

    # 14. Deterministic
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8, 59.5, 60.3, 61.5]
        r1 = analyze_lap_distribution(times)
        r2 = analyze_lap_distribution(times)
        assert r1.to_dict() == r2.to_dict()
        _ok("deterministic")
    except Exception as e:
        _fail("deterministic", str(e))

    print(f"\nLap Distribution Tests: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
