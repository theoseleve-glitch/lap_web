"""Step 10d2: attach an honestly-labelled grip anchor to each corner-lap.

Runs immediately after 10d_per_lap_corners, the only point where the friction
model, the corner list, the resampled laps and the per-lap metrics all coexist.
"""
from __future__ import annotations

import logging
from typing import Any, Final

import numpy as np
import pandas as pd

import grip_anchor as ga
from corner_analysis import _resolve_accel_lat

logger = logging.getLogger(__name__)

_ANCHOR_KEYS = (
    "grip_anchor_tier", "grip_anchor_reason",
    "grip_anchor_pct", "grip_anchor_baseline_g",
)

# Fallback tolerance for _bin_tolerance_mps when an envelope has too few
# bins to measure its own spacing (fewer than 2 distinct bin centres).
# build_friction_model (friction_envelope.py) normally splits the observed
# speed range into ~15 equal-width bins via np.linspace, which on real kart
# data (roughly 5-35 m/s) works out to ~2 m/s spacing -- so this fallback is
# already more permissive than the common case, not a tight guess.
_FALLBACK_BIN_TOLERANCE_MPS: Final[float] = 5.0


def _corners_by_id(corners: list[Any] | None) -> dict[Any, dict]:
    """Build the corner_id -> corner lookup, skipping any entry that isn't
    dict-like. A malformed corner record (None, a bare string, ...) in the
    corners list must not raise here -- it just contributes no data, the
    same as a corner_id with no matching row."""
    by_id: dict[Any, dict] = {}
    for c in (corners or []):
        if not isinstance(c, dict):
            continue
        by_id[c.get("corner_id")] = c
    return by_id


def _corner_mask(lap_df: pd.DataFrame, corner: dict) -> np.ndarray | None:
    """Distances are 0-based per-lap metres (canonical frame, see
    resampling.resample_lap_by_distance).

    A MISSING s_start/s_end is fine (``.get`` defaults to 0.0); a
    non-numeric VALUE (e.g. "abc") must degrade to "no window" rather than
    raising ValueError out of float().
    """
    col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
    if col is None:
        return None
    try:
        s_start = float(corner.get("s_start", 0.0))
        s_end = float(corner.get("s_end", 0.0))
    except (TypeError, ValueError):
        return None
    dist = pd.to_numeric(lap_df[col], errors="coerce").values
    mask = (dist >= s_start) & (dist <= s_end)
    return mask if mask.sum() >= 3 else None


def _apply(metric: dict, anchor: ga.Anchor) -> None:
    metric["grip_anchor_tier"] = anchor.tier
    metric["grip_anchor_reason"] = anchor.reason
    metric["grip_anchor_pct"] = anchor.pct
    metric["grip_anchor_baseline_g"] = anchor.baseline_g


def run_grip_anchor(
    per_lap_corner_metrics: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    friction_model: Any = None,
    friction_envelope: Any = None,
    curvature_profile: Any = None,
    excluded_laps: frozenset[int] = frozenset(),
) -> list[dict[str, Any]]:
    """Attach grip_anchor_* to every metric dict. Returns the same list.

    Total by construction: this stage runs inside
    ``pipeline.helpers._safe_step``, which discards the ENTIRE step's
    output -- every corner-lap's labelling, not just the one bad record --
    the moment anything raises. So every branch below degrades (usually to
    ``TIER_REFUSED``) instead of propagating, for any input shape: a
    non-dict corner, a corner with a non-numeric s_start, a non-dict metric
    entry, or a decide_anchor call that fails for an unanticipated reason.
    """
    metrics = list(per_lap_corner_metrics or [])
    if not metrics:
        return metrics

    corners_by_id = _corners_by_id(corners)

    # Peak lateral per (corner, lap), and the session best per corner. Both
    # come from this session only: corner_id is not stable across sessions.
    peak: dict[tuple[Any, Any], float] = {}
    for lap_num, lap_df in (resampled_laps or {}).items():
        if lap_num in excluded_laps:
            continue
        if lap_df is None or len(lap_df) < 10:
            continue
        a_lat = _resolve_accel_lat(lap_df)          # already m/s², already abs
        for cid, corner in corners_by_id.items():
            mask = _corner_mask(lap_df, corner)
            if mask is None:
                continue
            vals = a_lat[mask]
            vals = vals[np.isfinite(vals)]
            if vals.size:
                peak[(cid, lap_num)] = float(np.nanmax(vals))

    session_best: dict[Any, float] = {}
    for (cid, _lap), v in peak.items():
        if v > session_best.get(cid, 0.0):
            session_best[cid] = v

    # One trust ratio per session, over cornering samples only.
    trust = _session_trust_ratio(resampled_laps, curvature_profile)

    for i, m in enumerate(metrics):
        # Captured BEFORE anything can raise, and never touched again inside
        # the except branch below -- if `m` itself is the malformed thing
        # (not dict-like), calling `.get()` on it a second time in the
        # handler would raise again and defeat this safety net.
        cid_for_log: Any = None
        lap_for_log: Any = None
        try:
            if not isinstance(m, dict):
                raise TypeError(f"metric entry is not a dict: {type(m).__name__}")
            cid_for_log = m.get("corner_id")
            lap_for_log = m.get("lap_number")
            cid, lap_num = cid_for_log, lap_for_log
            bin_obj, bin_out_of_range = _bin_for_speed(friction_envelope, m.get("apex_speed_mps"))
            anchor = ga.decide_anchor(
                a_lat_mps2=peak.get((cid, lap_num), float("nan")),
                a_long_mps2=0.0,
                speed_mps=float(m.get("apex_speed_mps") or 0.0),
                friction=friction_model,
                envelope_bin=bin_obj,
                bin_out_of_range=bin_out_of_range,
                trust_ratio=trust,
                session_best_lat_mps2=session_best.get(cid),
            )
        except Exception:
            logger.debug("grip anchor failed for corner=%s lap=%s", cid_for_log, lap_for_log)
            anchor = ga.Anchor(ga.TIER_REFUSED, ga.REASON_NO_MEASUREMENT, None, None)

        if not isinstance(m, dict):
            # Nothing to mutate in place -- replace the slot with a fresh
            # dict so the caller still gets an element carrying all four
            # keys, at the same position.
            m = {}
            metrics[i] = m
        _apply(m, anchor)

    tiers = {}
    for m in metrics:
        tiers[m["grip_anchor_tier"]] = tiers.get(m["grip_anchor_tier"], 0) + 1
    logger.info("Grip anchor tiers across %d corner-laps: %s", len(metrics), tiers)
    return metrics


def _bin_attr(bin_obj: Any, name: str) -> Any:
    """Read a FrictionBin field whether ``bin_obj`` is a live ``FrictionBin``
    (attribute access) or the ``.to_dict()`` mapping shape (dict key
    access).

    The pipeline persists ``summary["friction_envelope"]`` as exactly the
    latter (see ``friction_envelope.FrictionEnvelope.to_dict()``), and that
    dict form is what a future caller -- or a regression test built the
    honest way, by calling ``.to_dict()`` on a real envelope -- will
    plausibly pass in here. A bare ``getattr`` silently returns ``None``
    for a dict regardless of its contents, which upstream reads as
    "bin unmeasured" and mislabels a perfectly good measurement as
    ``bin_fabricated``. That confidently-wrong degradation, not a loud
    failure, is exactly the failure mode this helper exists to prevent.
    """
    if isinstance(bin_obj, dict):
        return bin_obj.get(name)
    return getattr(bin_obj, name, None)


def _envelope_bins(envelope: Any) -> list[Any] | None:
    """Read the ``friction_bins`` list whether ``envelope`` is a live
    ``FrictionEnvelope`` (attribute access) or its ``.to_dict()`` mapping
    shape (dict key access) -- see ``_bin_attr`` above for why both shapes
    must be supported here rather than only the object form the original
    unit-test doubles used.
    """
    if isinstance(envelope, dict):
        return envelope.get("friction_bins")
    return getattr(envelope, "friction_bins", None)


def _bin_tolerance_mps(bins: Any) -> float:
    """Half this envelope's own median bin spacing.

    Derived from THIS envelope's actual bins rather than a fixed constant,
    so the guard tracks whatever binning resolution this session's data
    produced (build_friction_model splits the observed speed range into
    ``n_speed_bins`` equal-width bins -- see friction_envelope.py). Falls
    back to ``_FALLBACK_BIN_TOLERANCE_MPS`` only when fewer than two
    distinct bin centres exist, i.e. spacing can't be measured at all.
    """
    try:
        centers = sorted({float(_bin_attr(b, "speed_center_mps")) for b in bins})
    except (TypeError, ValueError, AttributeError):
        return _FALLBACK_BIN_TOLERANCE_MPS
    if len(centers) < 2:
        return _FALLBACK_BIN_TOLERANCE_MPS
    gaps = np.diff(np.asarray(centers, dtype=float))
    gaps = gaps[gaps > 0]
    if gaps.size == 0:
        return _FALLBACK_BIN_TOLERANCE_MPS
    return float(np.median(gaps)) / 2.0


def _bin_for_speed(envelope: Any, speed: Any) -> tuple[Any, bool]:
    """Nearest friction bin to this corner's apex speed.

    Returns ``(bin_or_None, out_of_range)``. ``out_of_range`` is True only
    when a nearest-bin CANDIDATE existed but sat farther from the query
    speed than this envelope's own bin-spacing tolerance allows -- i.e. we
    deliberately refused to let a corner at one speed borrow "measured"
    confidence from a bin centred at a completely different speed regime.
    It is False (with bin=None) for the ordinary "nothing to look at" cases
    -- no envelope, no bins, an unusable speed value -- which decide_anchor
    reports through a different reason (no_envelope / bin_fabricated).

    ``envelope`` -- and each element of its ``friction_bins`` -- may be
    either a live ``FrictionEnvelope``/``FrictionBin`` or the dict shape
    ``.to_dict()`` produces (that dict shape is what actually flows through
    ``summary["friction_envelope"]``); see ``_bin_attr``/``_envelope_bins``.
    """
    bins = _envelope_bins(envelope)
    if not bins or speed is None:
        return None, False
    try:
        v = float(speed)
    except (TypeError, ValueError):
        return None, False
    if not np.isfinite(v):
        return None, False

    try:
        nearest = min(bins, key=lambda b: abs(float(_bin_attr(b, "speed_center_mps")) - v))
        dist = abs(float(_bin_attr(nearest, "speed_center_mps")) - v)
    except (TypeError, ValueError, AttributeError):
        return None, False

    if dist > _bin_tolerance_mps(bins):
        return None, True
    return nearest, False


def _session_trust_ratio(
    resampled_laps: dict[int, pd.DataFrame] | None, curvature_profile: Any,
) -> float | None:
    """Median |a_lat| / (v^2*kappa) over cornering samples across all laps."""
    if not resampled_laps or curvature_profile is None:
        return None
    try:
        cp_d = pd.to_numeric(curvature_profile["distance_m"], errors="coerce").values
        cp_k = pd.to_numeric(curvature_profile["curvature_1pm"], errors="coerce").values
    except Exception:
        return None

    ratios = []
    for lap_df in resampled_laps.values():
        if lap_df is None or len(lap_df) < 50:
            continue
        col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
        spd = next((c for c in ("Speed (m/s)", "speed_mps") if c in lap_df.columns), None)
        if col is None or spd is None:
            continue
        d = pd.to_numeric(lap_df[col], errors="coerce").values
        v = pd.to_numeric(lap_df[spd], errors="coerce").values
        r = ga.channel_trust_ratio(_resolve_accel_lat(lap_df), v, np.interp(d, cp_d, cp_k))
        if r is not None:
            ratios.append(r)
    return float(np.median(ratios)) if ratios else None
