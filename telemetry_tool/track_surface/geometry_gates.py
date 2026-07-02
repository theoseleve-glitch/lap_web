"""Hard validation gates for track geometry (spec 2026-07-01 §3 A3).

Pure functions: no I/O, no DB. Persistence code calls run_geometry_gates()
and withholds the geometry sidecar on failure; grip persistence continues.
Thresholds are the spec's, verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_ARC_LENGTH_M = 100.0
MAX_CLOSURE_ERROR_M = 5.0
WIDTH_MIN_M = 0.5
WIDTH_MAX_M = 30.0
MAX_ELEVATION_RANGE_M = 100.0
MAX_ELEVATION_STEP_M = 2.0


@dataclass
class GateFailure:
    gate: str
    message: str
    values: dict


@dataclass
class GateReport:
    passed: bool
    failures: list[GateFailure] = field(default_factory=list)

    def to_details(self) -> dict:
        return {
            "passed": self.passed,
            "failures": [
                {"gate": f.gate, "message": f.message, "values": f.values}
                for f in self.failures
            ],
        }


def _fail(failures: list[GateFailure], gate: str, message: str, **values) -> None:
    failures.append(GateFailure(gate=gate, message=message,
                                values={k: float(v) if isinstance(v, (int, float, np.floating)) else v
                                        for k, v in values.items()}))


def _cross2(a, b) -> float:
    """Scalar cross product of 2D vectors (avoids numpy>=2 deprecation)."""
    return float(a[0] * b[1] - a[1] * b[0])


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """Proper intersection of segments p1p2 and p3p4 (shared endpoints excluded)."""
    d1 = _cross2(p4 - p3, p1 - p3)
    d2 = _cross2(p4 - p3, p2 - p3)
    d3 = _cross2(p2 - p1, p3 - p1)
    d4 = _cross2(p2 - p1, p4 - p1)
    return bool(((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)))


def _has_self_intersection(xy: np.ndarray, *, closed: bool) -> bool:
    """O(M^2 / cell) sweep on a coarse grid; M <= a few thousand in practice."""
    n = len(xy) - 1
    if n < 3:
        return False
    # Coarse spatial hash of segment bounding boxes to keep this fast.
    cell = max(float(np.ptp(xy, axis=0).max()) / 64.0, 1e-6)
    buckets: dict[tuple[int, int], list[int]] = {}
    for i in range(n):
        lo = np.minimum(xy[i], xy[i + 1]) // cell
        hi = np.maximum(xy[i], xy[i + 1]) // cell
        for gx in range(int(lo[0]), int(hi[0]) + 1):
            for gy in range(int(lo[1]), int(hi[1]) + 1):
                buckets.setdefault((gx, gy), []).append(i)
    seen: set[tuple[int, int]] = set()
    for idxs in buckets.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if abs(i - j) <= 1 or (i, j) in seen:
                    continue  # adjacent segments share a vertex
                if closed and {i, j} == {0, n - 1}:
                    continue  # closing segment touches the first (only for closed)
                seen.add((i, j))
                if _segments_intersect(xy[i], xy[i + 1], xy[j], xy[j + 1]):
                    return True
    return False


def run_geometry_gates(surface, *, closed: bool = True) -> GateReport:
    failures: list[GateFailure] = []
    frenet = getattr(surface, "frenet", None)
    if frenet is None:
        _fail(failures, "missing_frenet", "no frenet frame on surface")
        return GateReport(passed=False, failures=failures)

    xy = np.asarray(frenet.centerline_xy, dtype=float)
    s = np.asarray(frenet.s_grid, dtype=float)
    total = float(getattr(frenet, "total_length_m", s[-1] if len(s) else 0.0))

    # finite — checked first; NaNs poison every other gate.
    arrays = {"centerline_xy": xy, "s_grid": s}
    for name in ("width_left", "width_right", "elevation_m"):
        val = getattr(surface, name, None)
        if val is not None:
            arrays[name] = np.asarray(val, dtype=float)
    for name, arr in arrays.items():
        if not np.all(np.isfinite(arr)):
            _fail(failures, "finite", f"{name} contains non-finite values",
                  array=name, n_bad=int((~np.isfinite(arr)).sum()))
    if any(f.gate == "finite" for f in failures):
        return GateReport(passed=False, failures=failures)

    if total < MIN_ARC_LENGTH_M:
        _fail(failures, "arc_length",
              f"arc length {total:.1f} m < {MIN_ARC_LENGTH_M:.0f} m minimum",
              total_length_m=total, n_points=len(xy))

    if len(s) >= 2 and not np.all(np.diff(s) > 0):
        _fail(failures, "monotonic_s", "s_grid is not strictly increasing",
              n_violations=int((np.diff(s) <= 0).sum()))

    if closed and len(xy) >= 2:
        closure = float(np.linalg.norm(xy[-1] - xy[0]))
        if closure > MAX_CLOSURE_ERROR_M:
            _fail(failures, "closure",
                  f"closure error {closure:.1f} m > {MAX_CLOSURE_ERROR_M:.0f} m",
                  closure_error_m=closure)

    # Self-intersection only meaningful on non-degenerate geometry.
    if total >= MIN_ARC_LENGTH_M and _has_self_intersection(xy, closed=closed):
        _fail(failures, "self_intersection", "centerline crosses itself")

    for name in ("width_left", "width_right"):
        w = arrays.get(name)
        if w is None:
            continue
        w_min, w_max = float(np.min(w)), float(np.max(w))
        if w_min < WIDTH_MIN_M or w_max > WIDTH_MAX_M:
            _fail(failures, "width_bounds",
                  f"{name} range [{w_min:.2f}, {w_max:.2f}] m outside "
                  f"[{WIDTH_MIN_M}, {WIDTH_MAX_M}] m", side=name,
                  min_m=w_min, max_m=w_max)

    z = arrays.get("elevation_m")
    if z is not None and len(z) >= 2:
        z_range = float(np.ptp(z))
        if z_range > MAX_ELEVATION_RANGE_M:
            _fail(failures, "elevation_range",
                  f"elevation range {z_range:.1f} m > {MAX_ELEVATION_RANGE_M:.0f} m",
                  range_m=z_range)
        max_step = float(np.max(np.abs(np.diff(z))))
        if max_step > MAX_ELEVATION_STEP_M:
            _fail(failures, "elevation_step",
                  f"max |dz| step {max_step:.2f} m > {MAX_ELEVATION_STEP_M:.0f} m",
                  max_step_m=max_step)

    return GateReport(passed=not failures, failures=failures)
