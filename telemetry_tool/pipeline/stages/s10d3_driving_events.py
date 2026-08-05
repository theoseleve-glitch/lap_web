"""Step 10d3: build a `CornerWindow` per corner-lap from real pipeline data
and run the Phase 2 driving-event detector registry over them.

Runs immediately after 10d2_grip_anchor, for the same reason 10d2 runs where
it does: this is the point where the per-lap corner metrics, the corner
list and the resampled laps all coexist, and 10d2 has already had its
chance to attach `grip_anchor_pct` to each metric.

Unit conversion happens HERE, ONCE. The resampled frame carries lateral and
longitudinal acceleration in G, under `Lateral acceleration (G) *calc` and
`Longitudinal acceleration (G) *calc` -- NOT `accel_long_mps2` (an earlier
probe read that column name against the real resampled frame and got a
false 0% fire rate: the column simply is not there). The lateral channel is
resolved via `corner_analysis._resolve_accel_lat` (already converts G to
m/s^2 and takes abs()) rather than a second converter. The longitudinal
channel is resolved explicitly below by `_resolve_accel_long_mps2` rather
than reusing `corner_analysis._resolve_accel_long`: that function falls back
to a finite-difference proxy derived from speed when the real channel is
absent, which would silently fabricate a value where `CornerWindow.a_long_mps2`
is documented to be `None` -- exactly the distinction `re_braking`'s
`requires` gate depends on to report "insufficient" instead of scoring a
proxy as if it were measured.

THE REFERENCE GAP. `CornerWindow.reference` is a plain dict that is always
present (even if empty), so it can never appear in a detector's `requires`
frozenset -- `run_registry` only gates on top-level `CornerWindow` attributes
being non-None. A window built with `reference={}` would still pass every
`requires` check that doesn't happen to need `reference`, and its detector
would fall through `detect()`'s internal `_all_finite(...)` guard to
`None` ("looked, found nothing") -- collapsing "there was nothing to
compare against" into "compared and found nothing", which is the exact
distinction this whole layer exists to preserve (see driving_events.py's
CAPABILITIES docstring).

FIX ROUND 1 revised this. The first cut skipped building ANY window for a
corner whose aggregated reference was completely empty -- but that gate was
corner-wide, and only `over_slowing`/`late_throttle` ever read `reference`
at all. `re_braking` (`requires={"a_long_mps2", "apex_idx"}`) and
`envelope_under_use` (`requires={"grip_anchor_pct"}`) never touch it, so the
corner-wide skip silently starved them of windows they had every field for
-- a real corner with a strong clean re-brake and a low grip-anchor
percentage, but no apex speed / corner time / throttle onset on any lap,
came back `{"re_braking": "insufficient", "envelope_under_use":
"insufficient"}` with zero events, when both should have fired.

THE FIX: windows are now built unconditionally -- `reference_by_corner.get
(cid) or {}` is passed through even when empty, and `requires` alone decides
what each detector can evaluate. This is safe, not just convenient, because
of an invariant in how `_build_references` is built: it aggregates each
field (apex speed / throttle onset / corner time) SELF-INCLUSIVELY -- every
admissible lap's own metric row is one of the candidates for its own
corner's reference, including the very lap the window is being built for.
Consequently, whenever a window's own `apex_speed_mps` (or `corner_time_s`,
or `throttle_onset_m`) is non-None, `reference` for that corner is
GUARANTEED to carry that same field too (this window's own value is at
minimum a candidate). The reverse holds as well: if `reference` for a
corner is missing a field entirely, EVERY admissible lap's window at that
corner independently has that same field as None, because both are read via
the identical `_finite_float(metric.get(...))` call on the identical metric
dict. So `over_slowing`'s `requires={"apex_speed_mps", "corner_time_s"}`
already fails on its OWN window-native fields in exactly the scenario that
used to need the corner-wide skip -- no separate reference-emptiness check
is needed, and `re_braking`/`envelope_under_use` are no longer collateral
damage. `_build_windows` still computes `corners_without_reference` and
logs it once, but purely as a diagnostic -- it no longer gates anything.

`late_throttle` reaches the same outcome by a different route since the
2026-08-05 onset fix: it requires `throttle_onset_status` rather than
`throttle_onset_m`, precisely so that "the onset derivation ran and found
no speed crossing" can surface as an explicit `not_measurable` event naming
its cause instead of vanishing. `corner_time_s` is still in its `requires`,
so the total-reference-gap scenario above still reads "insufficient" for it
-- that is what the paired test asserts. A metric dict that never went
through `s10b_corners._assign_throttle_onsets` carries no status at all and
is likewise gated out as "insufficient", never as "looked, found nothing".
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

import driving_events as de
from corner_analysis import _resolve_accel_lat
from pipeline.stages import s10d2_grip_anchor

logger = logging.getLogger(__name__)

_G_TO_MPS2 = 9.80665


def _finite_float(value: Any) -> float | None:
    """Coerce a raw metric-dict value to a finite float, or None.

    Metric dicts come from upstream stages and from callers directly (the
    malformed-input test passes ``{"lap_number": None, "corner_id": None}``),
    so a value here may be missing, None, a string, or a non-finite float --
    none of those may raise, and none may silently become a fabricated 0.0.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _positive_float(value: Any) -> float | None:
    """``_finite_float``, but a value at or below zero also reads ABSENT.

    For the two fields where a non-positive number is not a measurement but
    a silent substitution: ``corner_analysis.py:731`` writes
    ``actual_apex_speed_mps=0.0`` whenever its corner slice comes back empty
    or all-NaN, and that 0.0 is finite, so every finiteness guard downstream
    passes it through. The final review demonstrated the consequence: an
    ``over_slowing`` event carrying ``validity="measured"``, magnitude
    17.82 m/s, and ``evidence={"apex_speed_mps": 0.0}``.

    Stripping it HERE rather than only inside the detector is the point.
    A window whose ``apex_speed_mps`` is None fails ``over_slowing``'s
    ``requires`` and the detector is reported ``insufficient`` -- "could not
    look". A detector that instead returned None for the same window would
    be counted as ``not_triggered`` -- "looked, found nothing" -- which is
    exactly the collapse ``driving_events.CAPABILITIES`` exists to prevent.
    ``driving_events._all_positive`` re-checks inside the detectors as an
    independent second layer for windows this stage did not build.
    """
    v = _finite_float(value)
    return v if v is not None and v > 0 else None


def _resolve_accel_long_mps2(lap_df: pd.DataFrame) -> np.ndarray | None:
    """Longitudinal acceleration in m/s^2 for the WHOLE lap, or None.

    Deliberately explicit and minimal -- unlike
    ``corner_analysis._resolve_accel_long``, this never falls back to a
    finite-difference proxy derived from speed. A genuinely absent channel
    must read as None, because ``CornerWindow.a_long_mps2 is None`` is what
    tells ``run_registry`` to mark ``re_braking`` "insufficient" rather than
    silently scoring a derived proxy as a measured deceleration.
    """
    if "accel_long_mps2" in lap_df.columns:
        return pd.to_numeric(lap_df["accel_long_mps2"], errors="coerce").values.astype(float)
    if "Longitudinal acceleration (G) *calc" in lap_df.columns:
        vals = pd.to_numeric(
            lap_df["Longitudinal acceleration (G) *calc"], errors="coerce"
        ).values.astype(float)
        return vals * _G_TO_MPS2
    return None


def _local_apex_idx(speed_mps: np.ndarray) -> int | None:
    """Window-local apex index: argmin of speed WITHIN this window's own
    (already corner-masked) array.

    Mirrors ``s10b_corners.py:490-492``'s ``np.nanargmin`` derivation, but
    expressed as an index into the window's own arrays rather than the full
    lap -- ``CornerWindow.apex_idx`` is the single source of truth every
    post-apex detector (``re_braking``) slices against, so a second argmin
    over the full lap here would give this module two different notions of
    "the apex".
    """
    if speed_mps.size == 0:
        return None
    try:
        return int(np.nanargmin(speed_mps))
    except ValueError:
        return None  # an all-NaN slice


def _build_references(
    metrics: list[dict[str, Any]], excluded_laps: frozenset[int],
) -> dict[Any, dict[str, float]]:
    """Per corner_id: this driver's own best apex speed (max), earliest
    throttle onset (min -- smaller distance-after-apex is earlier), and
    fastest corner time (min), aggregated across every admissible metric row
    for that corner.

    Computed independently of ``grip_anchor``'s own ``corner_time_best_s``
    (rather than reading that field back off the metric dicts) so this
    stage's notion of "the reference" survives even when 10d2_grip_anchor
    itself failed for this session -- the anchor is decoration on top of
    10d's metrics, not a dependency of this stage's own comparison logic.

    ``best_onset`` can only be a minimum over the laps whose onset was
    actually measurable, which is a censored subset whenever any lap's scan
    came back empty. That censoring is not hidden: every such corner-lap
    still produces a `late_throttle` event, with ``validity="not_measurable"``
    and a named reason, so the size and location of the censored set is
    readable off the output rather than inferable only from a missing row.
    On the real fixture the censored set is currently empty (72 of 72
    corner-laps measurable).
    """
    best_apex: dict[Any, float] = {}
    best_onset: dict[Any, float] = {}
    best_time: dict[Any, float] = {}

    for m in metrics:
        if not isinstance(m, dict):
            continue
        cid = m.get("corner_id")
        lap_num = m.get("lap_number")
        if cid is None or lap_num in excluded_laps:
            continue

        # `_positive_float` on the two speed/time fields: a substituted 0.0
        # would never win the apex MAX, but it would always win the corner
        # time MIN and become "the driver's best pass through this corner",
        # poisoning every other lap's comparison at that corner.
        apex = _positive_float(m.get("apex_speed_mps"))
        if apex is not None and apex > best_apex.get(cid, float("-inf")):
            best_apex[cid] = apex

        onset = _finite_float(m.get("throttle_onset_m"))
        if onset is not None and onset < best_onset.get(cid, float("inf")):
            best_onset[cid] = onset

        t = _positive_float(m.get("corner_time_s"))
        if t is not None and t < best_time.get(cid, float("inf")):
            best_time[cid] = t

    references: dict[Any, dict[str, float]] = {}
    for cid in set(best_apex) | set(best_onset) | set(best_time):
        ref: dict[str, float] = {}
        if cid in best_apex:
            ref["apex_speed_mps"] = best_apex[cid]
        if cid in best_onset:
            ref["throttle_onset_m"] = best_onset[cid]
        if cid in best_time:
            ref["corner_time_s"] = best_time[cid]
        references[cid] = ref
    return references


def _build_one_window(
    lap_num: Any,
    cid: Any,
    corner: dict[str, Any],
    metric: dict[str, Any],
    lap_df: pd.DataFrame,
    detection_lap: pd.DataFrame,
    reference: dict[str, float],
) -> "de.CornerWindow | None":
    """Build one CornerWindow, reusing `s10d2_grip_anchor._corner_mask` for
    the window itself (never a second mask -- see that function's docstring
    for the measured 0.0665 s median corner-time drift a second, absolute-
    metres implementation reintroduced on real data)."""
    mask = s10d2_grip_anchor._corner_mask(lap_df, corner, detection_lap)
    if mask is None:
        return None

    dist_col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
    speed_col = next((c for c in ("Speed (m/s)", "speed_mps") if c in lap_df.columns), None)
    if dist_col is None or speed_col is None or "distance_norm" not in lap_df.columns:
        return None

    # No `n_samples < floor` guard here: `_corner_mask` above already
    # refuses to return a mask with fewer than 3 samples (`mask.sum() >= 3`
    # is its own return condition), so `mask.sum()` at this point can never
    # be smaller than that -- a second floor here would be provably dead
    # code, confirmed by fix round 1's review.
    n_samples = int(mask.sum())

    dist_m = pd.to_numeric(lap_df[dist_col], errors="coerce").values[mask]
    speed_mps = pd.to_numeric(lap_df[speed_col], errors="coerce").values[mask]
    dist_norm = pd.to_numeric(lap_df["distance_norm"], errors="coerce").values[mask]

    a_lat_mps2 = _resolve_accel_lat(lap_df)[mask]  # already m/s^2, already abs()

    a_long_full = _resolve_accel_long_mps2(lap_df)
    a_long_mps2 = a_long_full[mask] if a_long_full is not None else None

    apex_idx = _local_apex_idx(speed_mps)
    s_norm_apex = float(dist_norm[apex_idx]) if apex_idx is not None else None

    finite_norm = dist_norm[np.isfinite(dist_norm)]
    if finite_norm.size == 0:
        return None
    s_norm_start = float(np.min(finite_norm))
    s_norm_end = float(np.max(finite_norm))

    return de.CornerWindow(
        lap_number=lap_num,
        corner_id=cid,
        s_norm_start=s_norm_start,
        s_norm_end=s_norm_end,
        n_samples=n_samples,
        speed_mps=speed_mps,
        a_lat_mps2=a_lat_mps2,
        a_long_mps2=a_long_mps2,
        dist_m=dist_m,
        # `_positive_float`, not `_finite_float`: a 0.0 here is a silent
        # substitution, not a measurement -- see that helper's docstring.
        apex_speed_mps=_positive_float(metric.get("apex_speed_mps")),
        apex_idx=apex_idx,
        s_norm_apex=s_norm_apex,
        corner_time_s=_positive_float(metric.get("corner_time_s")),
        throttle_onset_m=_finite_float(metric.get("throttle_onset_m")),
        # The frame-free primitive behind `throttle_onset_m`; see
        # CornerWindow's docstring. Absent on a hand-built metric dict, which
        # is not fatal -- `late_throttle` compares the metre values, which
        # were converted from this one against a single session-wide length.
        throttle_onset_norm=_finite_float(metric.get("throttle_onset_norm")),
        # Passed through as-is, NOT coerced: this is the upstream
        # derivation's own record of whether it ran and what it found. A
        # metric dict without the key (an older run, a caller that builds
        # metrics by hand) leaves it None, which `late_throttle`'s
        # `requires` reads as "the derivation never ran" -> insufficient.
        throttle_onset_status=metric.get("throttle_onset_status"),
        reference=dict(reference),
        grip_anchor_pct=_finite_float(metric.get("grip_anchor_pct")),
    )


def _build_windows(
    per_lap_corner_metrics: list[dict[str, Any]] | None,
    corners: list[dict[str, Any]] | None,
    resampled_laps: dict[int, pd.DataFrame] | None,
    excluded_laps: frozenset[int],
) -> list["de.CornerWindow"]:
    metrics = [m for m in (per_lap_corner_metrics or []) if isinstance(m, dict)]
    if not metrics:
        return []

    corners_by_id = s10d2_grip_anchor._corners_by_id(corners)
    if not corners_by_id:
        return []

    resampled_laps = resampled_laps or {}
    if not resampled_laps:
        return []

    valid_laps = {
        lap_num: lap_df
        for lap_num, lap_df in resampled_laps.items()
        if isinstance(lap_df, pd.DataFrame) and not lap_df.empty and lap_num not in excluded_laps
    }
    if not valid_laps:
        return []

    # The lap corners were detected FROM -- see s10d2_grip_anchor's own
    # comment above its identical derivation. Corners' absolute s_start/
    # s_end are relative to THIS lap's span, so every _corner_mask call
    # below (even for a different lap) is threaded the same detection_lap.
    detection_lap = resampled_laps.get(sorted(resampled_laps.keys())[0])
    if not isinstance(detection_lap, pd.DataFrame) or detection_lap.empty:
        return []

    metrics_by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
    for m in metrics:
        lap_num = m.get("lap_number")
        cid = m.get("corner_id")
        if lap_num is None or cid is None:
            continue
        metrics_by_key[(lap_num, cid)] = m

    reference_by_corner = _build_references(metrics, excluded_laps)
    # Diagnostic only (fix round 1) -- does NOT gate window construction.
    # `over_slowing`/`late_throttle` already read "insufficient" for these
    # corners on their own, via their own `requires` on the window's OWN
    # apex_speed_mps/corner_time_s/throttle_onset_m fields (see the module
    # docstring's invariant); `re_braking`/`envelope_under_use` still get a
    # window and evaluate normally. Logged so a real-data run can see how
    # often this happens without it silently discarding two of four
    # detectors' evaluability.
    corners_without_reference = {
        cid for cid in corners_by_id if not reference_by_corner.get(cid)
    }
    if corners_without_reference:
        logger.info(
            "driving_events: %d corner(s) have no established reference "
            "across admissible laps (no lap gave a finite apex_speed_mps, "
            "corner_time_s or throttle_onset_m) -- over_slowing/late_throttle "
            "will read 'insufficient' for them; re_braking/envelope_under_use "
            "are unaffected and still evaluate normally: %s",
            len(corners_without_reference),
            sorted(corners_without_reference, key=str),
        )

    windows: list[de.CornerWindow] = []
    for (lap_num, cid), metric in metrics_by_key.items():
        if lap_num not in valid_laps:
            continue
        corner = corners_by_id.get(cid)
        if corner is None:
            continue
        reference = reference_by_corner.get(cid) or {}
        try:
            window = _build_one_window(
                lap_num, cid, corner, metric,
                valid_laps[lap_num], detection_lap, reference,
            )
        except Exception:
            logger.exception(
                "driving_events: failed building a window for lap=%s corner=%s",
                lap_num, cid,
            )
            continue
        if window is not None:
            windows.append(window)

    return windows


def run_driving_events(
    per_lap_corner_metrics: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    excluded_laps: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Build one CornerWindow per corner-lap and run the Phase 2 detector
    registry over them. Returns ``{"events": [...], "capability": {...}}``.

    Must never raise: this runs inside ``pipeline.helpers._safe_step``, and
    a Phase-1 review already proved a raise there discards every corner
    metric for the session (see the ``_plcm``/``_plcm_anchored`` comment at
    ``orchestrator.py:1194-1198``). Window construction is wrapped
    end-to-end so any unanticipated malformed-input shape still degrades to
    an empty window list rather than propagating -- ``driving_events.
    run_registry`` is separately already total over its own input (see its
    docstring), so calling it with an empty list still returns a full
    capability dict rather than an empty one.
    """
    excluded_laps = excluded_laps or frozenset()
    try:
        windows = _build_windows(
            per_lap_corner_metrics, corners, resampled_laps, excluded_laps,
        )
    except Exception:
        logger.exception("run_driving_events: window construction failed outright")
        windows = []

    events, capability = de.run_registry(windows)
    return {"events": events, "capability": capability}
