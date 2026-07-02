"""GPS-heading-derived yaw-rate variance — reliability primitive for robustness.

Yaw-rate is not a stored channel. Heading between consecutive GPS samples is
always derivable from lat/lon, and the robustness scorer uses yaw variance only
as a late/early *ratio* (absolute units cancel). Variance of wrapped heading
increments is therefore a scale-free stability proxy that works for every
user / vehicle / track that has GPS (i.e. all telemetry uploads).
"""
from __future__ import annotations

import math

# Minimum GPS samples in a lap to attempt a heading-variance estimate.
_MIN_POINTS = 8


def _wrap_pi(angle: float) -> float:
    """Wrap a radian angle to (-pi, pi]."""
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def lap_yaw_variance(lats: list[float], lons: list[float]) -> float | None:
    """Population variance of wrapped heading increments for one lap.

    Returns ``None`` when there are too few points to be meaningful. Longitude
    deltas are scaled by ``cos(lat)`` so headings are locally metric.
    """
    if lats is None or lons is None:
        return None
    n = min(len(lats), len(lons))
    if n < _MIN_POINTS:
        return None

    headings: list[float] = []
    for i in range(n - 1):
        try:
            lat0 = float(lats[i]); lat1 = float(lats[i + 1])
            lon0 = float(lons[i]); lon1 = float(lons[i + 1])
        except (TypeError, ValueError):
            continue
        if math.isnan(lat0) or math.isnan(lat1) or math.isnan(lon0) or math.isnan(lon1):
            continue
        dlat = lat1 - lat0
        dlon = (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) * 0.5))
        if dlat == 0.0 and dlon == 0.0:
            continue
        headings.append(math.atan2(dlon, dlat))

    if len(headings) < 3:
        return None

    increments = [_wrap_pi(headings[i + 1] - headings[i]) for i in range(len(headings) - 1)]
    if len(increments) < 2:
        return None

    mean = sum(increments) / len(increments)
    return sum((x - mean) ** 2 for x in increments) / len(increments)


def stint_yaw_variances(
    gps_by_lap: dict[int, tuple[list[float], list[float]]],
    ordered_lap_numbers: list[int],
) -> tuple[float | None, float | None, str]:
    """Mean per-lap yaw variance over the early third vs the late third.

    ``ordered_lap_numbers`` must be the stint's laps in running order. Returns
    ``(early_var, late_var, basis)`` where basis is ``"gps_heading"`` when at
    least one early and one late lap yielded a variance, else
    ``"insufficient_gps"`` with ``(None, None)``.
    """
    per_lap: list[float | None] = []
    for lap in ordered_lap_numbers:
        entry = gps_by_lap.get(lap)
        per_lap.append(lap_yaw_variance(entry[0], entry[1]) if entry else None)

    n = len(per_lap)
    if n == 0:
        return None, None, "insufficient_gps"
    third = max(1, n // 3)
    early_vals = [v for v in per_lap[:third] if v is not None]
    late_vals = [v for v in per_lap[-third:] if v is not None]
    if not early_vals or not late_vals:
        return None, None, "insufficient_gps"
    return (
        sum(early_vals) / len(early_vals),
        sum(late_vals) / len(late_vals),
        "gps_heading",
    )
