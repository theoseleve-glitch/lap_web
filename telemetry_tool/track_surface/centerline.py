"""
track_surface/centerline.py
----------------------------
Multi-lap centerline extraction with B-spline fitting.

Given position data from multiple laps, produces a smooth track centerline
at uniform arc-length spacing.  For a single lap, applies Gaussian smoothing
directly.  For multiple laps, computes per-distance-bin medians then fits
a parametric B-spline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)

_MIN_POINTS: Final[int] = 20


def _arc_lengths(xy: np.ndarray) -> np.ndarray:
    """Cumulative arc length along an (N, 2) path.  Returns (N,) array."""
    diffs = np.diff(xy, axis=0)
    seg_lens = np.sqrt(diffs[:, 0] ** 2 + diffs[:, 1] ** 2)
    return np.concatenate([[0.0], np.cumsum(seg_lens)])


def select_laps_by_arclength_and_time(
    laps: list[np.ndarray],
    lap_times_s: list[float] | None = None,
    tolerance_sigma: float = 2.0,
) -> tuple[list[int], list[dict]]:
    """Identify out-laps / in-laps by *statistical* deviation in arclength
    or lap time. Day-7 RC1 out-lap rejection.

    A lap is rejected when its total arclength deviates from the median
    arclength by more than ``tolerance_sigma`` * sigma, OR (when
    ``lap_times_s`` is supplied) when its lap time deviates from the
    median lap time by the same threshold.

    The rejection is intentionally **geometry-blind**: it only looks at
    aggregate length/time. The S1 OK-tail is real track geometry (Day-7
    D3 decision); rejecting laps by geometric outliers would re-introduce
    the bottom-left quadrant collapse documented in MESH_PIPELINE_AUDIT.md
    §2 S4.

    Parameters
    ----------
    laps : list of (N_i, 2) XY arrays — one per lap.
    lap_times_s : optional list of per-lap durations in seconds, parallel
        to ``laps``. If absent, only arclength is checked.
    tolerance_sigma : multiplier on the standard deviation that defines
        the rejection envelope. Default 2.0 (~95 % retention on a normal
        distribution).

    Returns
    -------
    (kept_indices, rejected_metadata)
        ``kept_indices`` is a list of indices into ``laps`` retained.
        ``rejected_metadata`` is a list of dicts ``{"index", "reason",
        "arclength", "lap_time_s", "deviation_arclength_sigma",
        "deviation_time_sigma"}`` for each rejected lap, in the original
        order. Always returns ≥ 1 kept lap (if rejection would empty the
        retention set, falls back to keeping all laps and logs a warning).

    Notes
    -----
    If ≥ 50 % of laps would be rejected, the threshold is too tight (or
    the data are too noisy for blanket rejection); we log a warning and
    proceed with the rejection anyway, leaving the caller to decide
    whether to raise. We do NOT silently widen the threshold.
    """
    n = len(laps)
    if n == 0:
        return [], []

    arclengths = np.array([float(_arc_lengths(lap)[-1]) for lap in laps])
    times = np.asarray(lap_times_s, dtype=float) if lap_times_s is not None else None

    median_L = float(np.median(arclengths))
    std_L = float(np.std(arclengths))
    threshold_L = tolerance_sigma * std_L

    if times is not None:
        median_T = float(np.median(times))
        std_T = float(np.std(times))
        threshold_T = tolerance_sigma * std_T
    else:
        median_T = std_T = threshold_T = float("nan")

    kept: list[int] = []
    rejected: list[dict] = []
    for i in range(n):
        dev_L = abs(arclengths[i] - median_L)
        dev_L_sigma = dev_L / std_L if std_L > 1e-9 else 0.0
        reject_L = std_L > 1e-9 and dev_L > threshold_L

        if times is not None:
            dev_T = abs(times[i] - median_T)
            dev_T_sigma = dev_T / std_T if std_T > 1e-9 else 0.0
            reject_T = std_T > 1e-9 and dev_T > threshold_T
        else:
            dev_T = dev_T_sigma = float("nan")
            reject_T = False

        if reject_L or reject_T:
            reason_parts = []
            if reject_L:
                reason_parts.append(
                    f"arclength {arclengths[i]:.1f}m "
                    f"({dev_L_sigma:.2f}sigma from median {median_L:.1f}m)"
                )
            if reject_T:
                reason_parts.append(
                    f"time {times[i]:.2f}s "
                    f"({dev_T_sigma:.2f}sigma from median {median_T:.2f}s)"
                )
            rejected.append({
                "index": i,
                "reason": " AND ".join(reason_parts),
                "arclength": float(arclengths[i]),
                "lap_time_s": float(times[i]) if times is not None else None,
                "deviation_arclength_sigma": float(dev_L_sigma),
                "deviation_time_sigma": float(dev_T_sigma),
            })
        else:
            kept.append(i)

    if rejected and len(rejected) >= 0.5 * n:
        logger.warning(
            "Out-lap rejection retained %d of %d laps (>=50%% rejected at "
            "tolerance_sigma=%.1f). Threshold may be too tight or the data "
            "have systematic anomalies.",
            len(kept), n, tolerance_sigma,
        )

    if not kept:
        logger.warning(
            "Out-lap rejection would empty the retention set; keeping all "
            "%d laps as a fallback. Caller should investigate.", n,
        )
        return list(range(n)), []

    return kept, rejected


def normalize_to_u(
    lap_xy: np.ndarray, cyclic: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Map a lap to fraction-of-track parameterization u ∈ [0, 1).

    Returns ``(u, lap_xy_clean)`` where ``u[i]`` = (cumulative arclength
    to sample i) / total arclength, and ``lap_xy_clean`` strips any
    duplicate-position samples that would collapse cumulative arclength.

    With ``cyclic=True`` (default), the divisor is the *cyclic* total
    arclength = open-path length + closure chord from sample N-1 back
    to sample 0. This puts ``u[-1] < 1.0`` for a one-loop trace: the
    last sample sits at fraction (N-1)/N along the closed loop, and
    u=1.0 corresponds to wrapping back to ``lap_xy[0]``. For real
    RaceChrono lap data the closure chord is sub-cm because each lap
    starts and ends at the timing line; for synthetic samplings with
    ``endpoint=False`` the closure chord is the same length as any
    other inter-sample chord.

    With ``cyclic=False``, the divisor is just ``s[-1]`` (open path).

    The Day-7 RC1 fix: switch from index-wise lap alignment (the
    broken behaviour at centerline.py:160-167 before the rewrite) to
    fraction-of-track alignment. Pointwise median at u=0.5 means
    "halfway around the track" for every retained lap, regardless of
    how many ds-samples that lap had.
    """
    if lap_xy.shape[0] < 2:
        raise ValueError("normalize_to_u: lap needs >= 2 samples")

    s = _arc_lengths(lap_xy)
    total = float(s[-1])
    if cyclic:
        closure = float(np.hypot(
            lap_xy[0, 0] - lap_xy[-1, 0],
            lap_xy[0, 1] - lap_xy[-1, 1],
        ))
        total += closure
    if total <= 0.0:
        raise ValueError("normalize_to_u: lap has zero total arclength")

    # Drop zero-length segments so u is strictly increasing — np.interp
    # below requires that.
    keep = np.concatenate([[True], np.diff(s) > 1e-9])
    return (s[keep] / total).astype(float), lap_xy[keep]


def interpolate_lap_to_u_grid(
    lap_u: np.ndarray,
    lap_xy: np.ndarray,
    u_grid: np.ndarray,
) -> np.ndarray:
    """Resample a lap onto a common u_grid using cyclic interpolation.

    Pads the lap data with one wrap-around sample on each side of [0, 1]
    so ``np.interp`` covers the seam at u = 0 ≡ u = 1 cleanly.
    Returns an (M, 2) array where M = len(u_grid).
    """
    if lap_u.shape[0] < 2 or lap_xy.shape[0] != lap_u.shape[0]:
        raise ValueError("interpolate_lap_to_u_grid: shape mismatch")

    # Cyclic extension: prepend last sample shifted by −1, append first
    # sample shifted by +1. This makes np.interp wrap-around correct
    # without copying the entire lap three times.
    u_ext = np.concatenate([[lap_u[-1] - 1.0], lap_u, [lap_u[0] + 1.0]])
    x_ext = np.concatenate([[lap_xy[-1, 0]], lap_xy[:, 0], [lap_xy[0, 0]]])
    y_ext = np.concatenate([[lap_xy[-1, 1]], lap_xy[:, 1], [lap_xy[0, 1]]])

    return np.column_stack([
        np.interp(u_grid, u_ext, x_ext),
        np.interp(u_grid, u_ext, y_ext),
    ])


def align_laps_circularly(
    lap_xy_grids: list[np.ndarray],
    reference_index: int | None = None,
) -> tuple[list[np.ndarray], list[int]]:
    """Circularly shift each lap-on-u_grid so its XY trace best matches
    a reference lap.

    Real telemetry data starts each lap at the timing-line crossing,
    which has 1-2 m jitter relative to the geometric "start". After
    fraction-of-track parameterization this jitter becomes a small
    constant offset in the u-grid index. The cross-correlation finds
    that offset by trying every possible circular shift k and picking
    the one that minimizes Σᵢ ‖lap[(i+k) % N] - ref[i]‖².

    Parameters
    ----------
    lap_xy_grids : list of (N, 2) arrays — laps already resampled onto
        the common u_grid via interpolate_lap_to_u_grid.
    reference_index : index of the lap to align everyone else against.
        Defaults to the lap with median arclength on the u_grid (most
        representative, avoids degeneracy from a single outlier lap).

    Returns
    -------
    (aligned_grids, shifts) where shifts[i] is the integer circular
    shift applied to lap i (0 for the reference itself).

    Complexity: O(N_grid²) per lap. For N_grid=512 + 10 laps that's
    ~5 ms — well within the budget for this code path.
    """
    if not lap_xy_grids:
        raise ValueError("align_laps_circularly: no laps")
    n_lap = len(lap_xy_grids)
    n_grid = lap_xy_grids[0].shape[0]

    if reference_index is None:
        # Pick the lap whose on-u_grid arclength is closest to the median.
        # (After u-parameterization every lap maps to the same u_grid;
        # arclength differences here reflect how much smoothing the
        # interpolation introduced vs the underlying geometry.)
        lap_lens = np.array([
            float(np.hypot(np.diff(g[:, 0]), np.diff(g[:, 1])).sum())
            for g in lap_xy_grids
        ])
        target = float(np.median(lap_lens))
        reference_index = int(np.argmin(np.abs(lap_lens - target)))

    ref = lap_xy_grids[reference_index]

    # FFT-based cyclic cross-correlation:
    # corr[k] = sum_i ref[i] . lap[(i+k) mod N]  (dot product per i)
    # Maximizing corr[k] gives the shift to apply via np.roll(lap, k) so
    # that the rolled lap best aligns with ref.
    F_ref_x = np.fft.fft(ref[:, 0])
    F_ref_y = np.fft.fft(ref[:, 1])

    aligned: list[np.ndarray] = []
    shifts: list[int] = []
    for i, lap in enumerate(lap_xy_grids):
        if i == reference_index:
            aligned.append(lap.copy())
            shifts.append(0)
            continue

        F_lap_x = np.fft.fft(lap[:, 0])
        F_lap_y = np.fft.fft(lap[:, 1])
        corr = np.real(np.fft.ifft(
            F_ref_x * np.conj(F_lap_x) + F_ref_y * np.conj(F_lap_y)
        ))
        shift = int(np.argmax(corr)) % n_grid
        aligned.append(np.roll(lap, shift, axis=0))
        shifts.append(shift)

    return aligned, shifts


def pointwise_median(lap_xy_grids: list[np.ndarray]) -> np.ndarray:
    """Per-grid-point XY median across laps.

    Each input is an (M, 2) array (output of ``interpolate_lap_to_u_grid``);
    output is (M, 2) where ``out[i]`` is the per-axis median of all input
    ``lap[i]`` positions.

    Robust to single-lap outliers within each u bucket — this is the
    behaviour that makes the rewrite tolerate the S1 tail without
    smearing it across other parts of the track. Each u row is its own
    median.
    """
    if not lap_xy_grids:
        raise ValueError("pointwise_median: no laps supplied")
    stack = np.stack(lap_xy_grids, axis=0)  # (n_laps, M, 2)
    return np.median(stack, axis=0)


@dataclass
class ClosedSplineFit:
    """Result of fit_closed_spline_with_curvature_target.

    tck            scipy splprep tck tuple for splev evaluation
    s_value        smoothing factor that achieved the targets
    kappa_max      |kappa|_max of the resulting spline (1/m)
    rms_deviation  RMS distance from input median_xy points (m)
    iterations     number of tuning iterations consumed (debug)
    """
    tck: tuple
    s_value: float
    kappa_max: float
    rms_deviation: float
    iterations: int


def fit_closed_spline_with_curvature_target(
    median_xy: np.ndarray,
    kappa_max_target: float = 0.2,
    rms_headroom_m: float = 0.5,
    max_iters: int = 10,
) -> ClosedSplineFit:
    """Fit a periodic cubic B-spline to ``median_xy`` and tune the
    smoothing parameter so that the resulting curvature stays under
    ``kappa_max_target`` (1/m) while the RMS deviation from
    ``median_xy`` stays under ``rms_headroom_m``.

    Tuning protocol per Day-7 brief §6 F1:
      * seed s with N (= number of median points)
      * if kappa_max > target: increase s by 2x  (more smoothing)
      * if kappa_max < 0.75 * target AND rms < rms_headroom_m:
            decrease s by 1.5x  (we have curvature headroom; tighten fit)
      * stop after max_iters or when both conditions hold
      * hard cap: accept kappa_max <= 1.25 * target, log warning
      * give up at kappa_max > 2 * target, log error and return best-effort

    The returned spline is parameterized by u in [0, 1) with per=1
    (periodic boundary conditions enforce closure).
    """
    try:
        from scipy.interpolate import splev, splprep
    except ImportError as exc:
        raise RuntimeError(
            "fit_closed_spline_with_curvature_target requires scipy"
        ) from exc

    n = median_xy.shape[0]
    if n < 4:
        raise ValueError("fit_closed_spline_with_curvature_target: need >= 4 points")

    # splprep requires the input curve to be closed by repeating the first
    # point at the end (per=1 enforces periodic boundary conditions).
    xy_closed = np.vstack([median_xy, median_xy[:1]])
    u_input = np.arange(xy_closed.shape[0]) / n  # u in [0, 1] inclusive

    # Seed strategy: start at s=0 (exact interpolation). If the median
    # points are clean (synthetic or already-smoothed) the resulting
    # spline already satisfies the curvature target and we exit at iter 0.
    # If they're noisy, we double s until kappa_max drops below target.
    s_value = 0.0
    last: ClosedSplineFit | None = None
    upper_cap = 1.25 * kappa_max_target
    halt_cap = 2.0 * kappa_max_target

    for it in range(max_iters):
        try:
            tck, _ = splprep(
                [xy_closed[:, 0], xy_closed[:, 1]],
                u=u_input,
                s=s_value,
                k=3,
                per=1,
            )
        except Exception as exc:
            logger.warning(
                "fit_closed_spline iteration %d failed: %s; loosening s",
                it, exc,
            )
            s_value = max(1.0, s_value) * 2.0
            continue

        # Evaluate kappa on a dense grid in u in [0, 1)
        u_eval = np.linspace(0.0, 1.0, 1024, endpoint=False)
        x, y = splev(u_eval, tck)
        dx, dy = splev(u_eval, tck, der=1)
        ddx, ddy = splev(u_eval, tck, der=2)
        num = np.asarray(dx) * np.asarray(ddy) - np.asarray(dy) * np.asarray(ddx)
        den = (np.asarray(dx) ** 2 + np.asarray(dy) ** 2) ** 1.5
        den = np.where(den < 1e-9, 1.0, den)
        kappa = np.abs(num / den)
        kappa_max = float(kappa.max())

        # RMS deviation: project median points onto spline by their u_input,
        # measure || spline(u_i) - median_xy[i] ||
        x_pred, y_pred = splev(u_input[:n], tck)
        rms = float(np.sqrt(np.mean(
            (np.asarray(x_pred) - median_xy[:, 0]) ** 2
            + (np.asarray(y_pred) - median_xy[:, 1]) ** 2
        )))

        last = ClosedSplineFit(
            tck=tck, s_value=s_value, kappa_max=kappa_max,
            rms_deviation=rms, iterations=it + 1,
        )

        if kappa_max <= kappa_max_target:
            # Target met; check RMS budget. If RMS is also under headroom,
            # we have a clean fit — return. Otherwise the smoothing was
            # gratuitous; this only matters when seeding at higher s
            # (defensive — for current seed=0, the smoothing factor only
            # goes up so rms is monotone-decreasing as s grows toward
            # the kappa boundary).
            if rms <= rms_headroom_m:
                return last
        # Need more smoothing to push kappa under target. Double s; bump
        # off zero on first growth.
        s_value = max(1.0, s_value) * 2.0

    if last is None:
        raise RuntimeError(
            "fit_closed_spline_with_curvature_target: no successful iteration",
        )

    if last.kappa_max <= upper_cap:
        logger.warning(
            "fit_closed_spline_with_curvature_target: kappa_max=%.4f exceeds "
            "target %.4f after %d iterations; accepting under hard cap %.4f",
            last.kappa_max, kappa_max_target, last.iterations, upper_cap,
        )
        return last

    if last.kappa_max > halt_cap:
        logger.error(
            "fit_closed_spline_with_curvature_target: kappa_max=%.4f exceeds "
            "halt cap %.4f after %d iterations. Median curve is unsmoothable "
            "at this target — consider upstream sample filtering or a tighter "
            "u_grid. Returning best-effort fit.",
            last.kappa_max, halt_cap, last.iterations,
        )
    else:
        logger.warning(
            "fit_closed_spline_with_curvature_target: kappa_max=%.4f exceeds "
            "soft cap %.4f after %d iterations; returning best-effort fit",
            last.kappa_max, upper_cap, last.iterations,
        )
    return last


@dataclass
class OpenSplineFit:
    """Result of fit_open_spline_with_curvature_target.

    Same fields as ClosedSplineFit plus:
      kappa_max_interior — |κ|_max excluding the first/last
                           ``boundary_zone`` fraction of the u-range.
                           Used as the iteration stop criterion;
                           kappa_max is the full-range max (informational).
      total_length       — input curve arclength (m).
    """
    tck: tuple
    s_value: float
    kappa_max: float
    kappa_max_interior: float
    rms_deviation: float
    iterations: int
    total_length: float


def fit_open_spline_with_curvature_target(
    xy: np.ndarray,
    kappa_max_target: float = 0.2,
    rms_headroom_m: float = 0.5,
    max_iters: int = 12,
    boundary_zone: float = 0.05,
) -> OpenSplineFit:
    """Fit a non-periodic cubic B-spline to ``xy`` and tune the smoothing
    factor so |κ|_max ≤ ``kappa_max_target`` in the INTERIOR of the curve.

    Day-9 RC5 — open-curve counterpart of
    ``fit_closed_spline_with_curvature_target``. Same iterative
    s-doubling protocol (seed s=0 → exact fit; if interior |κ|_max
    exceeds target, double s; repeat up to ``max_iters``; hard cap at
    1.25× / halt at 2× target).

    Open-curve boundary handling: scipy's non-periodic splprep can
    produce mild B-spline overshoot at the curve endpoints (where the
    spline has only single-sided support). The iteration stop criterion
    uses ``kappa_max_interior`` (|κ| excluding the first/last
    ``boundary_zone`` fraction, default 5%) rather than the full-range
    max. This prevents endpoint overshoot from forcing over-smoothing
    of the bulk of the curve. The full-range ``kappa_max`` is still
    reported for diagnostic visibility.

    Parameters
    ----------
    xy : (N, 2) array of points along the open curve, sorted by some
        parameter (typically arclength).
    kappa_max_target : interior curvature ceiling (1/m).
    rms_headroom_m : RMS deviation budget from the input xy points.
    max_iters : max iterations of s-doubling before giving up.
    boundary_zone : fraction of u-range excluded from the interior
        curvature evaluation at each end (default 5%).
    """
    try:
        from scipy.interpolate import splev, splprep
    except ImportError as exc:
        raise RuntimeError(
            "fit_open_spline_with_curvature_target requires scipy"
        ) from exc

    n = xy.shape[0]
    if n < 4:
        raise ValueError(
            "fit_open_spline_with_curvature_target: need >= 4 points"
        )

    # Arclength parameterization (uniform input from extract_centerline,
    # but compute fresh for correctness).
    diffs = np.diff(xy, axis=0)
    s_param = np.concatenate([
        [0.0], np.cumsum(np.hypot(diffs[:, 0], diffs[:, 1])),
    ])
    total_length = float(s_param[-1])
    if total_length <= 1e-6:
        raise ValueError("input curve has zero arclength")
    u_input = s_param / total_length

    # splprep requires strictly increasing u (no duplicate parameter values)
    keep = np.diff(u_input, prepend=-1.0) > 1e-9
    u_clean = u_input[keep]
    xy_clean = xy[keep]
    if u_clean.shape[0] < 4:
        raise ValueError(
            "fit_open_spline_with_curvature_target: < 4 unique u points after cleaning"
        )

    s_value = 0.0
    last: OpenSplineFit | None = None
    upper_cap = 1.25 * kappa_max_target
    halt_cap = 2.0 * kappa_max_target

    for it in range(max_iters):
        try:
            tck, _ = splprep(
                [xy_clean[:, 0], xy_clean[:, 1]],
                u=u_clean,
                s=s_value,
                k=3,
                per=0,
            )
        except Exception as exc:
            logger.warning(
                "fit_open_spline iteration %d failed: %s; loosening s",
                it, exc,
            )
            s_value = max(1.0, s_value) * 2.0
            continue

        u_eval = np.linspace(0.0, 1.0, 1024)
        dx, dy = splev(u_eval, tck, der=1)
        ddx, ddy = splev(u_eval, tck, der=2)
        num = np.asarray(dx) * np.asarray(ddy) - np.asarray(dy) * np.asarray(ddx)
        den = (np.asarray(dx) ** 2 + np.asarray(dy) ** 2) ** 1.5
        den = np.where(den < 1e-9, 1.0, den)
        kappa = np.abs(num / den)
        kappa_max_full = float(kappa.max())
        bz = int(round(u_eval.size * boundary_zone))
        if bz > 0 and bz * 2 < u_eval.size:
            kappa_max_interior = float(kappa[bz:-bz].max())
        else:
            kappa_max_interior = kappa_max_full

        # RMS deviation from input points
        x_pred, y_pred = splev(u_clean, tck)
        rms = float(np.sqrt(np.mean(
            (np.asarray(x_pred) - xy_clean[:, 0]) ** 2
            + (np.asarray(y_pred) - xy_clean[:, 1]) ** 2
        )))

        last = OpenSplineFit(
            tck=tck, s_value=s_value, kappa_max=kappa_max_full,
            kappa_max_interior=kappa_max_interior,
            rms_deviation=rms, iterations=it + 1, total_length=total_length,
        )

        if kappa_max_interior <= kappa_max_target:
            if rms <= rms_headroom_m:
                return last
        s_value = max(1.0, s_value) * 2.0

    if last is None:
        raise RuntimeError(
            "fit_open_spline_with_curvature_target: no successful iteration",
        )

    if last.kappa_max_interior <= upper_cap:
        logger.warning(
            "fit_open_spline_with_curvature_target: interior κ_max=%.4f "
            "exceeds target %.4f after %d iters; under hard cap %.4f, accepting",
            last.kappa_max_interior, kappa_max_target, last.iterations,
            upper_cap,
        )
        return last
    if last.kappa_max_interior > halt_cap:
        logger.error(
            "fit_open_spline_with_curvature_target: interior κ_max=%.4f "
            "exceeds halt cap %.4f after %d iters. Returning best-effort.",
            last.kappa_max_interior, halt_cap, last.iterations,
        )
    else:
        logger.warning(
            "fit_open_spline_with_curvature_target: interior κ_max=%.4f "
            "exceeds soft cap %.4f after %d iters; best-effort fit",
            last.kappa_max_interior, upper_cap, last.iterations,
        )
    return last


@dataclass
class ArclengthCenterline:
    """Public read-only API of a closed centerline.

    Exposes spline evaluation parameterized by arclength s (metres from
    start), with public ``sample / tangent / normal / kappa /
    total_length`` methods plus the metadata that builder.py + boundary.py
    need to thread through to the (s, n) Frenet frame.
    """
    _tck: tuple
    _s_table: np.ndarray  # cumulative arclength at each u sample
    _u_table: np.ndarray  # u values matching _s_table
    total_length: float
    n_laps_kept: int
    n_laps_rejected: int
    rejected_metadata: list[dict]
    kappa_max: float
    rms_deviation: float
    s_value: float

    def _u_for_s(self, s: float | np.ndarray) -> np.ndarray:
        """Linear interp from arclength s to spline parameter u in [0, 1)."""
        s_mod = np.mod(np.asarray(s, dtype=float), self.total_length)
        return np.interp(s_mod, self._s_table, self._u_table)

    def sample(self, s: float | np.ndarray) -> np.ndarray:
        from scipy.interpolate import splev
        u = self._u_for_s(s)
        x, y = splev(u, self._tck)
        return np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])

    def tangent(self, s: float | np.ndarray) -> np.ndarray:
        from scipy.interpolate import splev
        u = self._u_for_s(s)
        dx, dy = splev(u, self._tck, der=1)
        dx = np.atleast_1d(dx)
        dy = np.atleast_1d(dy)
        mag = np.hypot(dx, dy)
        mag = np.where(mag < 1e-9, 1.0, mag)
        return np.column_stack([dx / mag, dy / mag])

    def normal(self, s: float | np.ndarray) -> np.ndarray:
        """LEFT-pointing unit normal: +90° CCW rotation of the tangent."""
        t = self.tangent(s)
        return np.column_stack([-t[:, 1], t[:, 0]])

    def kappa(self, s: float | np.ndarray) -> np.ndarray:
        from scipy.interpolate import splev
        u = self._u_for_s(s)
        dx, dy = splev(u, self._tck, der=1)
        ddx, ddy = splev(u, self._tck, der=2)
        dx = np.atleast_1d(dx); dy = np.atleast_1d(dy)
        ddx = np.atleast_1d(ddx); ddy = np.atleast_1d(ddy)
        num = dx * ddy - dy * ddx
        den = (dx ** 2 + dy ** 2) ** 1.5
        den = np.where(den < 1e-9, 1.0, den)
        return num / den


def reparameterize_by_arclength(
    fit: ClosedSplineFit,
    n_samples_per_unit_u: int = 4096,
) -> ArclengthCenterline:
    """Build an ArclengthCenterline from a ClosedSplineFit.

    Densely samples the spline on u in [0, 1), computes cumulative
    arclength along the samples, and stores a (u, s) lookup table for
    O(log N) arclength → u conversion at evaluation time.
    """
    from scipy.interpolate import splev
    u_dense = np.linspace(0.0, 1.0, n_samples_per_unit_u, endpoint=False)
    x, y = splev(u_dense, fit.tck)
    x = np.asarray(x); y = np.asarray(y)
    seg_lens = np.hypot(np.diff(x), np.diff(y))
    s_dense = np.concatenate([[0.0], np.cumsum(seg_lens)])
    # close the loop by appending the wrap-around chord
    closure = float(np.hypot(x[0] - x[-1], y[0] - y[-1]))
    total = float(s_dense[-1] + closure)
    return ArclengthCenterline(
        _tck=fit.tck,
        _s_table=s_dense,
        _u_table=u_dense,
        total_length=total,
        n_laps_kept=0,        # filled by extract_centerline
        n_laps_rejected=0,
        rejected_metadata=[],
        kappa_max=fit.kappa_max,
        rms_deviation=fit.rms_deviation,
        s_value=fit.s_value,
    )


def _resample_uniform(xy: np.ndarray, s: np.ndarray, ds: float) -> np.ndarray:
    """Resample (N, 2) path to uniform arc-length spacing ds.

    Returns (M, 2) array where M = floor(total_length / ds) + 1.
    """
    total = s[-1]
    if total < ds:
        return xy.copy()
    s_uniform = np.arange(0, total, ds)
    x_interp = np.interp(s_uniform, s, xy[:, 0])
    y_interp = np.interp(s_uniform, s, xy[:, 1])
    return np.column_stack([x_interp, y_interp])


def _gaussian_smooth_xy(
    xy: np.ndarray,
    sigma_m: float,
    ds: float,
    *,
    closed: bool = False,
) -> np.ndarray:
    """Apply Gaussian smoothing to an (N, 2) path.

    sigma_m is in metres; ds is the spacing between points.

    When ``closed=False`` (default): reflect-mode padding (open curve).
    When ``closed=True``: wrap-mode padding so the smoothing kernel
    treats the path as a closed loop. Required for single-lap closed-
    circuit data — otherwise the reflect at index 0 / -1 biases the
    seam samples toward themselves, producing a curvature spike at the
    seam after the downstream spline fit (Day-9 RC5 finding).
    """
    if sigma_m <= 0 or ds <= 0:
        return xy.copy()
    hw = max(1, int(3 * sigma_m / ds))
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) * ds / sigma_m) ** 2)
    kernel /= kernel.sum()

    pad_mode = "wrap" if closed else "reflect"
    pad_x = np.pad(xy[:, 0], hw, mode=pad_mode)
    pad_y = np.pad(xy[:, 1], hw, mode=pad_mode)
    sx = np.convolve(pad_x, kernel, mode="valid")[: len(xy)]
    sy = np.convolve(pad_y, kernel, mode="valid")[: len(xy)]
    return np.column_stack([sx, sy])


def _align_lap_starts(
    laps: list[np.ndarray],
    ref_start: np.ndarray,
) -> list[np.ndarray]:
    """Circularly shift each lap so its closest point to ref_start is at index 0."""
    aligned = []
    for lap in laps:
        dists = np.sqrt(np.sum((lap - ref_start) ** 2, axis=1))
        shift = int(np.argmin(dists))
        aligned.append(np.roll(lap, -shift, axis=0))
    return aligned


def _fit_bspline(xy: np.ndarray, ds: float) -> tuple[np.ndarray, float]:
    """Fit a parametric B-spline and resample at ds spacing.

    Falls back to raw input if scipy is unavailable.
    Returns (centerline_xy, total_length_m).
    """
    try:
        from scipy.interpolate import splev, splprep
    except ImportError:
        logger.debug("scipy unavailable, skipping B-spline fit")
        s = _arc_lengths(xy)
        return xy.copy(), float(s[-1])

    s_param = _arc_lengths(xy)
    total = float(s_param[-1])
    if total < ds * 3:
        return xy.copy(), total

    # Normalise parameter to [0, 1]
    u = s_param / total

    # splprep needs non-duplicate u values
    mask = np.diff(u, prepend=-1) > 1e-12
    u_clean = u[mask]
    xy_clean = xy[mask]
    if len(u_clean) < 4:
        return xy.copy(), total

    try:
        tck, _ = splprep([xy_clean[:, 0], xy_clean[:, 1]], u=u_clean, s=0, k=3)
    except Exception:
        logger.debug("B-spline fit failed, using raw points")
        return xy.copy(), total

    n_out = max(int(total / ds), _MIN_POINTS)
    u_eval = np.linspace(0, 1, n_out)
    xs, ys = splev(u_eval, tck)
    result = np.column_stack([xs, ys])
    new_total = float(_arc_lengths(result)[-1])
    return result, new_total


def extract_centerline(
    laps: list[np.ndarray],
    ds_m: float = 1.0,
    smooth_sigma_m: float = 3.0,
    *,
    lap_times_s: list[float] | None = None,
    u_grid_n: int = 512,
    kappa_max_target: float = 0.2,
    return_details: bool = False,
) -> tuple[np.ndarray, float] | ArclengthCenterline:
    """Extract a track centerline from one or more lap trajectories.

    Day-7 RC1 rewrite. Pipeline:

    1. Out-lap rejection by arclength + (optional) time
       — ``select_laps_by_arclength_and_time``
    2. u-parameterization per retained lap — ``normalize_to_u``
    3. Per-lap resampling on a common u_grid — ``interpolate_lap_to_u_grid``
    4. Cyclic cross-correlation lap-start alignment — ``align_laps_circularly``
    5. Per-u XY median across laps — ``pointwise_median``
    6. Cyclic cubic B-spline with curvature regularization —
       ``fit_closed_spline_with_curvature_target``
    7. Arclength reparameterization — ``reparameterize_by_arclength``

    Parameters
    ----------
    laps : list of (N_i, 2) arrays, each a lap trajectory in (x, y) m.
    ds_m : output uniform spacing in metres for the legacy 2-tuple return.
    smooth_sigma_m : retained for the single-lap fallback; unused in the
        multi-lap path which uses curvature regularization instead.
    lap_times_s : per-lap durations in seconds, parallel to ``laps``.
        When supplied, enables time-based out-lap rejection alongside
        arclength rejection. Optional for backward compatibility — callers
        that haven't yet plumbed lap durations get arclength-only.
    u_grid_n : resolution of the shared u_grid. 512 is the audit default.
    kappa_max_target : curvature ceiling (1/m) for the cyclic B-spline fit.
    return_details : when True, returns the rich ``ArclengthCenterline``
        object; otherwise returns the legacy ``(cl_xy, total_length)``
        2-tuple. ``builder.py`` + ``boundary.py`` keep using the 2-tuple
        form; new callers (audits, diagnostics, the V1.5 Frenet rewrite)
        can opt into the rich mode.

    Returns
    -------
    (centerline_xy, total_length_m) by default; an ``ArclengthCenterline``
    when ``return_details=True``.

    Raises
    ------
    ValueError when no valid laps with >= _MIN_POINTS samples are supplied.
    """
    valid_pairs = [
        (i, lap) for i, lap in enumerate(laps) if len(lap) >= _MIN_POINTS
    ]
    if not valid_pairs:
        raise ValueError(
            f"No valid laps provided (all have < {_MIN_POINTS} points)"
        )
    valid_indices = [i for i, _ in valid_pairs]
    valid_laps = [lap for _, lap in valid_pairs]

    # ── single-lap path (Day-9 RC5 upgrade) ──
    # Replaced the pre-Day-7 path (resample → Gaussian smooth → splprep(s=0))
    # with arclength resample → curvature-target-tuned spline. The
    # iterative s-doubling drives interior |κ|_max under kappa_max_target;
    # endpoint overshoot is excluded from the iteration decision (open-
    # curve boundary handling). The Gaussian pre-smoothing step is no
    # longer needed — the curvature-tuned fit subsumes it.
    #
    # Closed-loop vs open detection: a single lap of a circuit returns
    # to its starting position (xy[0] ≈ xy[-1]). If the endpoint gap
    # is < 5 % of total arclength, treat as a closed loop and use
    # ``fit_closed_spline_with_curvature_target`` (periodic boundary)
    # instead — otherwise splprep(per=0) injects a curvature spike at
    # the open seam. The pre-Day-7 path used splprep(s=0) which exactly
    # interpolated the seam, hiding this difference; the RC5 smoothing
    # version exposes it.
    if len(valid_laps) == 1:
        lap = valid_laps[0]
        s = _arc_lengths(lap)
        total_len = float(s[-1]) if s.size > 0 else 0.0
        endpoint_gap = (
            float(np.hypot(lap[0, 0] - lap[-1, 0], lap[0, 1] - lap[-1, 1]))
            if lap.shape[0] >= 2 else 0.0
        )
        is_closed_loop = (
            total_len > 0
            and endpoint_gap / total_len < 0.05
        )
        resampled = _resample_uniform(lap, s, ds_m)
        # Light Gaussian pre-smoothing absorbs the bulk of GPS noise
        # before the curvature-target fit refines. Multi-lap path
        # achieves this implicitly via cross-lap median; single-lap
        # needs an explicit pre-pass for the curvature iteration to
        # converge in the default max_iters. smooth_sigma_m=3m is
        # the historic default; the curvature-target tuner then
        # decides if more is needed. Use wrap padding when the lap
        # data is a closed loop (otherwise reflect-mode injects a
        # seam artifact the downstream spline can't undo).
        pre_smoothed = _gaussian_smooth_xy(
            resampled, smooth_sigma_m, ds_m, closed=is_closed_loop,
        )
        try:
            if is_closed_loop:
                # Use the multi-lap's periodic-boundary fitter on the
                # resampled single lap. Drop the duplicate closure point
                # _resample_uniform may have appended (it shouldn't, but
                # be defensive).
                closed_xy = pre_smoothed
                if (
                    closed_xy.shape[0] >= 2
                    and np.allclose(closed_xy[0], closed_xy[-1], atol=1e-3)
                ):
                    closed_xy = closed_xy[:-1]
                # Single-lap closed-loop needs more iterations than
                # multi-lap (no cross-lap median to cancel noise first).
                closed_fit = fit_closed_spline_with_curvature_target(
                    closed_xy, kappa_max_target=kappa_max_target,
                    max_iters=20,
                )
                # Translate to OpenSplineFit-shaped variables for the
                # downstream evaluation. closed_fit's tck is periodic,
                # evaluated on u ∈ [0, 1).
                from scipy.interpolate import splev
                n_out = max(int(total_len / ds_m), _MIN_POINTS)
                u_eval = np.linspace(0.0, 1.0, n_out, endpoint=False)
                xs, ys = splev(u_eval, closed_fit.tck)
                cl_xy = np.column_stack([np.asarray(xs), np.asarray(ys)])
                length = float(_arc_lengths(cl_xy)[-1])
                if return_details:
                    raise NotImplementedError(
                        "return_details=True is only supported for multi-lap input"
                    )
                return cl_xy, length

            fit = fit_open_spline_with_curvature_target(
                pre_smoothed, kappa_max_target=kappa_max_target,
            )
        except (ValueError, RuntimeError) as exc:
            # Defensive fallback to the pre-Day-7 path if the new fit
            # can't run (e.g. < 4 unique u points). Logs the failure so
            # the regression is visible.
            logger.warning(
                "single-lap curvature-target fit failed (%s); "
                "falling back to Gaussian + splprep(s=0)",
                exc,
            )
            smoothed = _gaussian_smooth_xy(resampled, smooth_sigma_m, ds_m)
            cl_xy, length = _fit_bspline(smoothed, ds_m)
            if return_details:
                raise NotImplementedError(
                    "return_details=True is only supported for multi-lap input"
                )
            return cl_xy, length

        # Evaluate the tuned spline at uniform ds-spaced u for output.
        try:
            from scipy.interpolate import splev
        except ImportError as exc:
            raise RuntimeError(
                "single-lap centerline requires scipy"
            ) from exc

        n_out = max(int(fit.total_length / ds_m), _MIN_POINTS)
        u_eval = np.linspace(0.0, 1.0, n_out)
        xs, ys = splev(u_eval, fit.tck)
        cl_xy = np.column_stack([np.asarray(xs), np.asarray(ys)])
        length = float(_arc_lengths(cl_xy)[-1])
        if return_details:
            raise NotImplementedError(
                "return_details=True is only supported for multi-lap input"
            )
        return cl_xy, length

    # ── multi-lap: Day-7 RC1 closed-loop pipeline ──

    # If lap_times_s came in, sub-select to match valid_laps.
    if lap_times_s is not None:
        lap_times_filtered = [lap_times_s[i] for i in valid_indices]
    else:
        lap_times_filtered = None

    # 1. Out-lap rejection
    kept_local, rejected_metadata = select_laps_by_arclength_and_time(
        valid_laps, lap_times_s=lap_times_filtered, tolerance_sigma=2.0,
    )
    # Annotate rejection metadata with the original input index so callers
    # can correlate rejections to their pre-validation lap numbering.
    for r in rejected_metadata:
        r["original_index"] = int(valid_indices[r["index"]])
    kept_laps = [valid_laps[i] for i in kept_local]

    logger.info(
        "extract_centerline (Day-7 RC1): %d valid laps, %d kept, %d rejected.",
        len(valid_laps), len(kept_laps), len(rejected_metadata),
    )
    for r in rejected_metadata:
        logger.info("  rejected lap original_index=%d: %s",
                    r["original_index"], r["reason"])

    # 2. u-parameterization + 3. resample to common u_grid
    u_grid = np.linspace(0.0, 1.0, u_grid_n, endpoint=False)
    grids = []
    for lap in kept_laps:
        u, lap_clean = normalize_to_u(lap, cyclic=True)
        grids.append(interpolate_lap_to_u_grid(u, lap_clean, u_grid))

    # 4. Lap-start alignment
    aligned, shifts = align_laps_circularly(grids)
    if any(s != 0 for s in shifts):
        # Cyclic-magnitude: shift of N-1 is "one bin back", not "huge"
        cyclic_mag = max(min(s, u_grid_n - s) for s in shifts if s != 0)
        if cyclic_mag > u_grid_n / 10:
            logger.warning(
                "extract_centerline: large lap-start shift detected "
                "(cyclic magnitude %d > %d/10 = %d u_grid bins). Upstream "
                "lap detection may be cutting laps badly.",
                cyclic_mag, u_grid_n, u_grid_n // 10,
            )

    # 5. Per-u median
    median_xy = pointwise_median(aligned)

    # 6. Cyclic B-spline + curvature regularization
    fit = fit_closed_spline_with_curvature_target(
        median_xy, kappa_max_target=kappa_max_target,
    )

    # 7. Arclength reparameterization
    cl = reparameterize_by_arclength(fit)
    cl.n_laps_kept = len(kept_laps)
    cl.n_laps_rejected = len(rejected_metadata)
    cl.rejected_metadata = rejected_metadata

    if return_details:
        return cl

    # Legacy 2-tuple: uniform-ds_m sampling along the closed centerline.
    s_samples = np.arange(0.0, cl.total_length, ds_m)
    cl_xy = cl.sample(s_samples)
    return cl_xy, cl.total_length
