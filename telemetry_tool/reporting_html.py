"""
reporting_html.py -- -
Self-contained HTML report generator for motorsport telemetry sessions.

Consumes the output of every upstream module and produces a single
``index.html`` file with embedded PNG plots and no external dependencies
so the file can be opened offline in any browser.

Input contract
~~~~~~~~~~~~~~
All inputs are plain dicts / DataFrames returned by the existing pipeline
modules.  Every field is optional  — missing data degrades to a placeholder
message rather than an exception.

Required upstream outputs
~~~~~~~~~~~~~~~~~~~~~~~~~
``score_result``         — dict from ``scoring.score_session()``
``theoretical_lap``      — pd.DataFrame from ``theoretical_engine.build_theoretical_lap()``
                          (columns: ``distance_m``, ``v_env_mps``)
``best_lap``             — pd.DataFrame (distance-resampled, columns:
                          ``Distance (m)``, ``Speed (m/s)``)
``delta_segments``       — list[dict] from ``deltas.classify_time_loss_cause()``
``lap_times``            — list[float] lap times in seconds (for the heatmap Y-axis)
``segment_losses``       — list[list[float]]  — ``n_laps  — n_segments`` time-loss
                          matrix in milliseconds (rows = laps, cols = segments)
``driver_profiles``      — list[dict] from ``driver_profile.generate_driver_profile()``
``session_meta``         — dict with optional keys: ``session_id``, ``track_id``,
                          ``track_state``, ``driver_name``, ``date``

Output
~~~~~~
A single ``index.html`` file (typically  ≈  200–400 KB depending on plot
resolution) with:
   --  Session headline score and grade
   --  Sub-score breakdown (bar chart + detail table)
   --  Theoretical vs best lap speed trace
   --  Segment delta heatmap with cause annotations
   --  Multi-driver comparison table

Design principles
~~~~~~~~~~~~~~~~~
- Pure-Python: matplotlib + Jinja2 + base64.  No JS frameworks, no CDN.
- Dark theme optimised for motorsport / data-engineering readability.
- Self-contained: all assets embedded; zero external requests.
- NaN-robust: missing data -- grey placeholders, not crashes.
- Deterministic: identical inputs -- identical bytes (fixed random_state
  for matplotlib where relevant).
"""

from __future__ import annotations

import base64
import io
import logging
import math
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

# Matplotlib  --  use non-interactive backend (no display required)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import matplotlib.colors as mcolors      # noqa: E402
from matplotlib.figure import Figure     # noqa: E402

from jinja2 import Environment, BaseLoader  # noqa: E402

logger = logging.getLogger(__name__)


# ============================================================================

# Column-name constants (mirrors upstream modules)

# ============================================================================


_COL_DIST:  Final[str] = "Distance (m)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_OUT_DIST:  Final[str] = "distance_m"
_OUT_SPEED: Final[str] = "v_env_mps"

# Plot dimensions

_FIG_DPI:     Final[int] = 130
_SPEED_FIGSIZE: Final[tuple[float, float]] = (10.0, 4.0)
_HEAT_FIGSIZE:  Final[tuple[float, float]] = (12.0, 5.5)
_SCORE_FIGSIZE: Final[tuple[float, float]] = (7.0, 3.5)
_GG_FIGSIZE:    Final[tuple[float, float]] = (6.0, 6.0)
_GRIP_FIGSIZE:  Final[tuple[float, float]] = (10.0, 4.0)

# Colour palette  --  dark motorsport theme

_BG_DARK:    Final[str] = "#0f1117"
_BG_CARD:    Final[str] = "#181b24"
_TEXT_LIGHT:  Final[str] = "#e0e0e0"
_TEXT_MED:    Final[str] = "#9a9a9a"
_ACCENT:      Final[str] = "#00d4ff"
_ACCENT_WARM: Final[str] = "#ff6b35"
_GREEN:       Final[str] = "#3ddc84"
_RED:         Final[str] = "#ff4444"
_YELLOW:      Final[str] = "#ffd600"


# ============================================================================

# Exceptions

# ============================================================================


class ReportError(Exception):
    """Raised when a report cannot be generated."""


# ============================================================================

# Internal  --  matplotlib helpers

# ============================================================================


def _apply_dark_style(fig: Figure, ax) -> None:
    """Apply consistent dark theme to a figure and axes."""
    fig.patch.set_facecolor(_BG_CARD)
    ax.set_facecolor(_BG_CARD)
    ax.tick_params(colors=_TEXT_MED, labelsize=8)
    ax.xaxis.label.set_color(_TEXT_LIGHT)
    ax.yaxis.label.set_color(_TEXT_LIGHT)
    ax.title.set_color(_TEXT_LIGHT)
    for spine in ax.spines.values():
        spine.set_color("#333")


def _fig_to_base64(fig: Figure) -> str:
    """Render a matplotlib figure to a base64-encoded PNG data URI."""
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=_FIG_DPI,
        bbox_inches="tight", facecolor=fig.get_facecolor(),
        edgecolor="none",
    )
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _safe_float(v: Any, default: float = float("nan")) -> float:
    """Coerce to float; return *default* on failure."""
    try:
        f = float(v)
        return default if not math.isfinite(f) else f
    except (TypeError, ValueError):
        return default


# ============================================================================

# Plot generators

# ============================================================================


def _plot_speed_trace(
    theoretical_lap: Optional[pd.DataFrame],
    best_lap: Optional[pd.DataFrame],
) -> str:
    """
    Theoretical vs best-lap speed trace.

    Returns base64 data URI, or empty string if data is missing.
    """
    if theoretical_lap is None and best_lap is None:
        return ""

    fig, ax = plt.subplots(figsize=_SPEED_FIGSIZE)
    _apply_dark_style(fig, ax)

    plotted = False

    if theoretical_lap is not None:
        d_col = _OUT_DIST if _OUT_DIST in theoretical_lap.columns else _COL_DIST
        s_col = _OUT_SPEED if _OUT_SPEED in theoretical_lap.columns else _COL_SPEED
        if d_col in theoretical_lap.columns and s_col in theoretical_lap.columns:
            dist = pd.to_numeric(theoretical_lap[d_col], errors="coerce").values
            spd  = pd.to_numeric(theoretical_lap[s_col], errors="coerce").values
            mask = np.isfinite(dist) & np.isfinite(spd)
            if mask.sum() > 1:
                ax.plot(
                    dist[mask], spd[mask] * 3.6,
                    color=_ACCENT, linewidth=1.8, alpha=0.9,
                    label="Theoretical",
                )
                plotted = True

    if best_lap is not None:
        d_col = _OUT_DIST if _OUT_DIST in best_lap.columns else _COL_DIST
        s_col = _OUT_SPEED if _OUT_SPEED in best_lap.columns else _COL_SPEED
        if d_col in best_lap.columns and s_col in best_lap.columns:
            dist = pd.to_numeric(best_lap[d_col], errors="coerce").values
            spd  = pd.to_numeric(best_lap[s_col], errors="coerce").values
            mask = np.isfinite(dist) & np.isfinite(spd)
            if mask.sum() > 1:
                ax.plot(
                    dist[mask], spd[mask] * 3.6,
                    color=_ACCENT_WARM, linewidth=1.4, alpha=0.85,
                    label="Best Lap",
                )
                plotted = True

    if not plotted:
        plt.close(fig)
        return ""

    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Speed (km/h)")
    ax.set_title("Theoretical vs Best Lap  — Speed Trace", fontsize=11, fontweight="bold")
    ax.legend(
        loc="lower right", fontsize=8,
        facecolor=_BG_CARD, edgecolor="#444",
        labelcolor=_TEXT_LIGHT,
    )
    ax.grid(True, alpha=0.15, color="#555")
    return _fig_to_base64(fig)


def _plot_delta_heatmap(
    segment_losses: Optional[list[list[float]]],
    n_segments: int = 0,
    lap_labels: Optional[list[str]] = None,
    cause_data: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Heatmap of segment time losses across laps.

    Rows = laps, columns = segments.  Green = time gained, red = time lost.
    Returns base64 data URI, or empty string if data missing.
    """
    if not segment_losses or not any(segment_losses):
        return ""

    # Guard against ragged arrays: pad shorter rows with 0.0 so every
    # row has the same length.  This can happen when some laps had
    # fewer valid segments than others.
    max_cols = max(len(row) for row in segment_losses)
    if max_cols == 0:
        return ""
    padded = [
        row + [0.0] * (max_cols - len(row)) if len(row) < max_cols else row
        for row in segment_losses
    ]

    matrix = np.array(padded, dtype=float)
    if matrix.ndim != 2:
        return ""
    n_laps, n_segs = matrix.shape

    if n_laps == 0 or n_segs == 0:
        return ""

    fig, ax = plt.subplots(figsize=_HEAT_FIGSIZE)
    _apply_dark_style(fig, ax)

    # Symmetric colour scale centred on zero

    abs_max = max(np.nanmax(np.abs(matrix)), 1.0)
    norm = mcolors.TwoSlopeNorm(vmin=-abs_max, vcenter=0.0, vmax=abs_max)

    # Green = gain (negative loss), Red = loss (positive)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "delta_cmap",
        [(0.0, _GREEN), (0.5, _BG_CARD), (1.0, _RED)],
    )

    im = ax.imshow(
        matrix, aspect="auto", cmap=cmap, norm=norm,
        interpolation="nearest",
    )

    # Axis labels

    seg_labels = [f"S{i + 1}" for i in range(n_segs)]
    ax.set_xticks(np.arange(n_segs))
    ax.set_xticklabels(seg_labels, fontsize=7, rotation=45, ha="right")

    if lap_labels is None:
        lap_labels = [f"L{i + 1}" for i in range(n_laps)]
    ax.set_yticks(np.arange(n_laps))
    ax.set_yticklabels(lap_labels[:n_laps], fontsize=7)

    # Annotate cells with value if matrix is small enough

    if n_laps <= 25 and n_segs <= 25:
        for i in range(n_laps):
            for j in range(n_segs):
                val = matrix[i, j]
                if np.isfinite(val):
                    txt = f"{val:+.0f}" if abs(val) >= 1 else ""
                    text_col = "#000" if abs(val) > abs_max * 0.6 else _TEXT_MED
                    ax.text(
                        j, i, txt, ha="center", va="center",
                        fontsize=6, color=text_col,
                    )

    cbar = fig.colorbar(im, ax=ax, pad=0.02, shrink=0.85)
    cbar.set_label("Time loss (ms)", color=_TEXT_LIGHT, fontsize=8)
    cbar.ax.tick_params(colors=_TEXT_MED, labelsize=7)

    # Annotate dominant cause per segment along top if data available

    if cause_data and len(cause_data) >= n_segs:
        cause_abbrev = {
            "entry_loss":       "ENT", "mid_corner_loss": "MID",
            "exit_loss":        "EXT", "instability":     "INS",
            "line_inefficiency": "LIN", "on_pace":         "",
            "undetermined":     "?",
        }
        for j, seg in enumerate(cause_data[:n_segs]):
            cause = seg.get("likely_cause", "")
            abbr  = cause_abbrev.get(cause, cause[:3].upper())
            if abbr:
                ax.text(
                    j, -0.7, abbr, ha="center", va="center",
                    fontsize=6, color=_YELLOW, fontweight="bold",
                )

    ax.set_xlabel("Track Segment")
    ax.set_ylabel("Lap")
    ax.set_title("Segment Delta Heatmap (ms)", fontsize=11, fontweight="bold")

    return _fig_to_base64(fig)


def _plot_sub_scores(
    sub_scores: Optional[dict[str, Any]],
) -> str:
    """
    Horizontal bar chart of sub-score categories.

    Returns base64 data URI, or empty string if data missing.
    """
    if not sub_scores:
        return ""

    categories = ["pace", "consistency", "execution", "robustness"]
    labels     = ["Pace", "Consistency", "Execution", "Robustness"]
    scores     = []
    maxes      = []

    for cat in categories:
        info = sub_scores.get(cat, {})
        scores.append(_safe_float(info.get("score"), 0.0))
        maxes.append(_safe_float(info.get("max"), 25.0))

    fig, ax = plt.subplots(figsize=_SCORE_FIGSIZE)
    _apply_dark_style(fig, ax)

    y_pos = np.arange(len(categories))

    # Background bars (max possible)

    ax.barh(y_pos, maxes, height=0.55, color="#252830", edgecolor="#333", linewidth=0.5)

    # Actual score bars with gradient colouring

    colours = []
    for s, m in zip(scores, maxes):
        pct = s / m if m > 0 else 0
        if pct >= 0.80:
            colours.append(_GREEN)
        elif pct >= 0.50:
            colours.append(_YELLOW)
        else:
            colours.append(_RED)

    ax.barh(y_pos, scores, height=0.55, color=colours, edgecolor="none")

    # Value labels

    for i, (s, m) in enumerate(zip(scores, maxes)):
        pct = s / m * 100 if m > 0 else 0
        ax.text(
            s + 0.3, i, f"{s:.1f} / {m:.0f}  ({pct:.0f}%)",
            va="center", fontsize=8, color=_TEXT_LIGHT,
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Score")
    ax.set_title("Sub-Score Breakdown", fontsize=11, fontweight="bold")
    ax.set_xlim(0, max(maxes) * 1.35)
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.12, color="#555")

    return _fig_to_base64(fig)



# ============================================================================

# New plot generators  — physics-based analysis

# ============================================================================


_CORNERING_BG: Final[str] = "#1a2a3a"   # tinted background for cornering zones


def _plot_physics_speed_overlay(
    theoretical_lap: Optional[pd.DataFrame],
    best_lap: Optional[pd.DataFrame],
    median_lap: Optional[pd.DataFrame] = None,
    cornering_limited: Optional[np.ndarray] = None,
    sim_distance: Optional[np.ndarray] = None,
) -> str:
    """
    Physics theoretical vs best & median lap speed traces with gap shading.

    - Cyan = theoretical (physics sim), orange = best, grey = median.
    - Red shading between theoretical and best = opportunity.
    - Blue-tinted background for cornering-limited zones.
    """
    if theoretical_lap is None and best_lap is None:
        return ""

    fig, ax = plt.subplots(figsize=_SPEED_FIGSIZE)
    _apply_dark_style(fig, ax)

    # --- Extract theoretical line

    theo_dist = theo_spd = None
    if theoretical_lap is not None:
        d_col = _OUT_DIST if _OUT_DIST in theoretical_lap.columns else _COL_DIST
        s_col = _OUT_SPEED if _OUT_SPEED in theoretical_lap.columns else _COL_SPEED
        if d_col in theoretical_lap.columns and s_col in theoretical_lap.columns:
            theo_dist = pd.to_numeric(theoretical_lap[d_col], errors="coerce").values
            theo_spd  = pd.to_numeric(theoretical_lap[s_col], errors="coerce").values * 3.6

    # --- Extract best lap

    best_dist = best_spd = None
    if best_lap is not None:
        d_col = _OUT_DIST if _OUT_DIST in best_lap.columns else _COL_DIST
        s_col = _OUT_SPEED if _OUT_SPEED in best_lap.columns else _COL_SPEED
        if d_col in best_lap.columns and s_col in best_lap.columns:
            best_dist = pd.to_numeric(best_lap[d_col], errors="coerce").values
            best_spd  = pd.to_numeric(best_lap[s_col], errors="coerce").values * 3.6

    # --- Extract median lap

    med_dist = med_spd = None
    if median_lap is not None:
        d_col = _OUT_DIST if _OUT_DIST in median_lap.columns else _COL_DIST
        s_col = _OUT_SPEED if _OUT_SPEED in median_lap.columns else _COL_SPEED
        if d_col in median_lap.columns and s_col in median_lap.columns:
            med_dist = pd.to_numeric(median_lap[d_col], errors="coerce").values
            med_spd  = pd.to_numeric(median_lap[s_col], errors="coerce").values * 3.6

    plotted = False

    # --- Cornering-limited zone shading (background) -- -

    if (cornering_limited is not None and sim_distance is not None
            and len(cornering_limited) == len(sim_distance)):
        zones = np.where(cornering_limited)[0]
        if len(zones) > 0:
            # Find contiguous blocks

            breaks = np.where(np.diff(zones) > 1)[0] + 1
            blocks = np.split(zones, breaks)
            for block in blocks:
                if len(block) < 2:
                    continue
                ax.axvspan(
                    sim_distance[block[0]], sim_distance[block[-1]],
                    alpha=0.12, color="#2277aa", zorder=0,
                )

    # --- Plot lines

    if theo_dist is not None and theo_spd is not None:
        mask = np.isfinite(theo_dist) & np.isfinite(theo_spd)
        if mask.sum() > 1:
            ax.plot(theo_dist[mask], theo_spd[mask],
                    color=_ACCENT, linewidth=2.0, alpha=0.95,
                    label="Theoretical (physics)", zorder=3)
            plotted = True

    if best_dist is not None and best_spd is not None:
        mask = np.isfinite(best_dist) & np.isfinite(best_spd)
        if mask.sum() > 1:
            ax.plot(best_dist[mask], best_spd[mask],
                    color=_ACCENT_WARM, linewidth=1.5, alpha=0.90,
                    label="Best Lap", zorder=2)
            plotted = True

            # Gap shading between theoretical and best

            if theo_dist is not None and theo_spd is not None:
                try:
                    common_dist = best_dist[mask]
                    theo_interp = np.interp(common_dist, theo_dist, theo_spd)
                    best_vals = best_spd[mask]
                    ax.fill_between(
                        common_dist, best_vals, theo_interp,
                        where=theo_interp > best_vals,
                        alpha=0.18, color=_RED, zorder=1,
                        label="Opportunity gap",
                    )
                except Exception:
                    pass

    if med_dist is not None and med_spd is not None:
        mask = np.isfinite(med_dist) & np.isfinite(med_spd)
        if mask.sum() > 1:
            ax.plot(med_dist[mask], med_spd[mask],
                    color=_TEXT_MED, linewidth=1.0, alpha=0.55,
                    label="Median Lap", linestyle="--", zorder=1)
            plotted = True

    if not plotted:
        plt.close(fig)
        return ""

    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Speed (km/h)")
    ax.set_title("Physics Theoretical vs Driver Speed Trace", fontsize=11, fontweight="bold")
    ax.legend(loc="lower right", fontsize=7.5,
              facecolor=_BG_CARD, edgecolor="#444", labelcolor=_TEXT_LIGHT)
    ax.grid(True, alpha=0.15, color="#555")
    return _fig_to_base64(fig)




# ============================================================================

# Data-driven theoretical (delegates to friction_model + scoring)

# ============================================================================


def _try_compute_session_theoretical(
    resampled_laps: Optional[dict],
    lap_times: Optional[list[float]] = None,
) -> Any:
    """
    Attempt to compute the session theoretical by building a FrictionCircle
    from the data and running the point-mass simulation.

    Returns a ``SessionTheoreticalResult`` or None if the modules are
    unavailable or data is insufficient.
    """
    if not resampled_laps:
        return None

    try:
        from friction_model import (
            build_friction_model,
            compute_session_theoretical,
        )
    except ImportError:
        logger.debug("friction_model not available; skipping data theoretical.")
        return None

    try:
        fm = build_friction_model(resampled_laps, kart_traction_floor=True)
        result = compute_session_theoretical(
            fm, resampled_laps, lap_times=lap_times,
        )
        return result
    except Exception as exc:
        logger.warning("Data theoretical computation failed: %s", exc)
        return None



# ============================================================================

# Data-driven theoretical lap time (point-mass simulation)

# ============================================================================


_G_VAL_SIM: Final[float] = 9.80665


def _extract_peak_g_from_laps(
    resampled_laps: dict,
    percentile: float = 99.0,
) -> Optional[dict[str, float]]:
    """
    Extract peak lateral, braking and traction G from all laps' data.

    Uses the given *percentile* (default 99th) to avoid single-sample
    spikes.  Returns dict with ``lat_g``, ``brake_g``, ``traction_g``
    in G units, or None if insufficient data.
    """
    _LAT_COLS  = ("accel_lat_mps2", "Lateral acceleration (G) *calc")
    _LONG_COLS = ("accel_long_mps2", "Longitudinal acceleration (G) *calc")

    all_lat: list[float] = []
    all_lon: list[float] = []

    for df in resampled_laps.values():
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        lat_col = next((c for c in _LAT_COLS if c in df.columns), None)
        long_col = next((c for c in _LONG_COLS if c in df.columns), None)
        if lat_col is None or long_col is None:
            continue

        lat = pd.to_numeric(df[lat_col], errors="coerce").values.astype(float)
        lon = pd.to_numeric(df[long_col], errors="coerce").values.astype(float)

        # Convert to m/s^2 if in G

        if "mps2" not in lat_col:
            lat = lat * _G_VAL_SIM
            lon = lon * _G_VAL_SIM

        mask = np.isfinite(lat) & np.isfinite(lon)
        all_lat.extend(np.abs(lat[mask]).tolist())
        all_lon.extend(lon[mask].tolist())

    if len(all_lat) < 50:
        return None

    all_lat_arr = np.array(all_lat)
    all_lon_arr = np.array(all_lon)

    lat_peak   = float(np.percentile(all_lat_arr, percentile)) / _G_VAL_SIM
    brake_peak = float(np.percentile(np.abs(all_lon_arr[all_lon_arr < 0]), percentile)) / _G_VAL_SIM if np.any(all_lon_arr < 0) else 0.5
    trac_peak  = float(np.percentile(all_lon_arr[all_lon_arr > 0], percentile)) / _G_VAL_SIM if np.any(all_lon_arr > 0) else 0.3

    # Sanity checks

    if lat_peak < 0.05 or brake_peak < 0.05 or trac_peak < 0.02:
        return None

    return {"lat_g": lat_peak, "brake_g": brake_peak, "traction_g": trac_peak}


def _estimate_track_curvature(
    distance: np.ndarray,
    speed: np.ndarray,
    lat_accel: np.ndarray,
    smooth_window: int = 7,
) -> np.ndarray:
    """
    Estimate track curvature κ(s) from distance, speed and lateral accel.

    κ = |a_lat| / v^2.  Smoothed to reduce noise.  Returns array aligned
    with input arrays.  Units: 1/m.
    """
    v_safe = np.maximum(np.abs(speed), 2.0)  # avoid div-by-zero at pit
    kappa = np.abs(lat_accel) / (v_safe ** 2)

    # Smooth curvature to reduce noise

    if smooth_window > 1 and len(kappa) > smooth_window * 2:
        kernel = np.ones(smooth_window) / smooth_window
        padded = np.concatenate([
            kappa[:smooth_window][::-1], kappa, kappa[-smooth_window:][::-1]
        ])
        smoothed = np.convolve(padded, kernel, mode="same")
        kappa = smoothed[smooth_window:-smooth_window]

    return kappa


def _point_mass_forward_backward(
    distance: np.ndarray,
    curvature: np.ndarray,
    lat_g: float,
    brake_g: float,
    traction_g: float,
    v_max_cap: float = 100.0,
) -> tuple[np.ndarray, float]:
    """
    Point-mass lap simulation using forward-backward integration.

    Three constraints at every point:
    1. Cornering:  v_corner = sqrt(lat_g * g / κ)       [grip-limited]
    2. Forward:    v^2 <= v_prev^2 + 2 * traction_g * g * ds [accel-limited]
    3. Backward:   v^2 <= v_next^2 + 2 * brake_g * g * ds   [brake-limited]

    Returns (speed_profile, lap_time).
    """
    n = len(distance)
    if n < 10:
        return np.full(n, 20.0), 0.0

    ds = np.diff(distance)
    ds = np.append(ds, ds[-1])  # pad last element

    # 1. Cornering speed limit

    kappa_safe = np.maximum(curvature, 1e-6)
    v_corner = np.sqrt(lat_g * _G_VAL_SIM / kappa_safe)
    v_corner = np.minimum(v_corner, v_max_cap)

    # 2. Forward pass (acceleration-limited)

    v_fwd = np.zeros(n)
    v_fwd[0] = min(v_corner[0], v_max_cap)
    a_trac = traction_g * _G_VAL_SIM
    for i in range(1, n):
        v_sq = v_fwd[i - 1] ** 2 + 2.0 * a_trac * ds[i - 1]
        v_fwd[i] = min(math.sqrt(max(v_sq, 0.0)), v_corner[i])

    # 3. Backward pass (braking-limited)

    v_bwd = np.zeros(n)
    v_bwd[-1] = min(v_corner[-1], v_fwd[-1])
    a_brk = brake_g * _G_VAL_SIM
    for i in range(n - 2, -1, -1):
        v_sq = v_bwd[i + 1] ** 2 + 2.0 * a_brk * ds[i]
        v_bwd[i] = min(math.sqrt(max(v_sq, 0.0)), v_fwd[i])

    # Final speed profile = minimum of all constraints

    v_theo = np.minimum(v_fwd, v_bwd)
    v_theo = np.maximum(v_theo, 1.0)  # floor at 1 m/s (avoid /0)

    # Lap time = integral of ds / v

    dt = ds / v_theo
    lap_time = float(np.sum(dt))

    return v_theo, lap_time


def _build_track_profile_from_best_lap(
    resampled_laps: dict,
    lap_times: Optional[list[float]] = None,
) -> Optional[dict[str, np.ndarray]]:
    """
    Build a track profile (distance, curvature, speed reference) from the
    best lap in the session.  If lap_times are provided, uses the fastest;
    otherwise uses the lap with the most data points.

    Returns dict with keys: ``distance``, ``curvature``, ``speed``,
    ``lat_accel``, ``best_key``  --  or None if data insufficient.
    """
    _LAT_COLS  = ("accel_lat_mps2", "Lateral acceleration (G) *calc")
    _DIST_COLS = ("Distance (m)", "distance_m")
    _SPD_COLS  = ("Speed (m/s)", "v_env_mps")

    sorted_keys = sorted(resampled_laps.keys())
    if not sorted_keys:
        return None

    # Pick the best lap (fastest if lap_times available, else most data)

    best_key = sorted_keys[0]
    if lap_times and len(lap_times) >= len(sorted_keys):
        valid = [
            (k, lap_times[i]) for i, k in enumerate(sorted_keys)
            if i < len(lap_times) and math.isfinite(lap_times[i]) and lap_times[i] > 0
        ]
        if valid:
            best_key = min(valid, key=lambda x: x[1])[0]
    else:
        # Most data points

        best_key = max(
            sorted_keys,
            key=lambda k: len(resampled_laps[k]) if resampled_laps[k] is not None else 0,
        )

    df = resampled_laps[best_key]
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None

    # Extract columns

    dist_col = next((c for c in _DIST_COLS if c in df.columns), None)
    spd_col  = next((c for c in _SPD_COLS  if c in df.columns), None)
    lat_col  = next((c for c in _LAT_COLS  if c in df.columns), None)

    if dist_col is None or spd_col is None or lat_col is None:
        return None

    distance  = pd.to_numeric(df[dist_col], errors="coerce").values.astype(float)
    speed     = pd.to_numeric(df[spd_col],  errors="coerce").values.astype(float)
    lat_accel = pd.to_numeric(df[lat_col],  errors="coerce").values.astype(float)

    # Convert lat accel to m/s^2 if in G

    if "mps2" not in lat_col:
        lat_accel = lat_accel * _G_VAL_SIM

    mask = np.isfinite(distance) & np.isfinite(speed) & np.isfinite(lat_accel)
    if mask.sum() < 30:
        return None

    distance  = distance[mask]
    speed     = speed[mask]
    lat_accel = lat_accel[mask]

    # Ensure monotonic distance

    if not np.all(np.diff(distance) > 0):
        sort_idx = np.argsort(distance)
        distance  = distance[sort_idx]
        speed     = speed[sort_idx]
        lat_accel = lat_accel[sort_idx]
        # Remove duplicate distances

        uniq_mask = np.concatenate([[True], np.diff(distance) > 0.01])
        distance  = distance[uniq_mask]
        speed     = speed[uniq_mask]
        lat_accel = lat_accel[uniq_mask]

    if len(distance) < 30:
        return None

    curvature = _estimate_track_curvature(distance, speed, lat_accel)

    return {
        "distance":  distance,
        "curvature": curvature,
        "speed":     speed,
        "lat_accel": lat_accel,
        "best_key":  best_key,
    }


def _compute_data_theoretical_lap_time(
    resampled_laps: dict,
    lap_times: Optional[list[float]] = None,
) -> Optional[dict[str, Any]]:
    """
    Compute the theoretical optimal lap time from the session's own data.

    Steps:
    1. Extract peak G capabilities (lat, brake, traction) from all laps.
    2. Build a track curvature profile from the best lap.
    3. Run a point-mass forward-backward simulation.

    Returns dict with:
      ``theoretical_time``  -- optimal lap time [s]
      ``peak_capabilities`` -- dict with lat_g, brake_g, traction_g
      ``speed_profile``     -- np.ndarray of theoretical speed [m/s]
      ``distance``          -- np.ndarray of distance [m]
      ``track_length_m``    -- float
    Or None if data is insufficient.
    """
    if not resampled_laps:
        return None

    # Step 1: peak capabilities from all laps

    caps = _extract_peak_g_from_laps(resampled_laps)
    if caps is None:
        return None

    # Step 2: track profile from best lap

    profile = _build_track_profile_from_best_lap(resampled_laps, lap_times)
    if profile is None:
        return None

    distance  = profile["distance"]
    curvature = profile["curvature"]

    # Estimate a reasonable v_max cap from the data

    v_max_cap = float(np.percentile(profile["speed"], 99.5)) * 1.15
    v_max_cap = max(v_max_cap, 30.0)  # at least 108 km/h

    # Step 3: point-mass simulation

    v_theo, theo_time = _point_mass_forward_backward(
        distance, curvature,
        lat_g=caps["lat_g"],
        brake_g=caps["brake_g"],
        traction_g=caps["traction_g"],
        v_max_cap=v_max_cap,
    )

    if theo_time <= 0 or not math.isfinite(theo_time):
        return None

    track_len = float(distance[-1] - distance[0])

    return {
        "theoretical_time":  theo_time,
        "peak_capabilities": caps,
        "speed_profile":     v_theo,
        "distance":          distance,
        "track_length_m":    track_len,
    }


def _compute_per_lap_theoretical(
    resampled_laps: dict,
    session_caps: dict[str, float],
    lap_times: Optional[list[float]] = None,
) -> dict[Any, dict[str, float]]:
    """
    Compute a per-lap theoretical time by running the point-mass sim
    on each lap's own curvature profile with the session-wide peak
    capabilities.

    This captures how each individual lap's line (curvature) compares
    to what was achievable with the observed peak grip.

    Returns ``{lap_key: {"theo_time": ..., "actual_time": ..., "time_loss": ...}}``.
    """
    _LAT_COLS  = ("accel_lat_mps2", "Lateral acceleration (G) *calc")
    _DIST_COLS = ("Distance (m)", "distance_m")
    _SPD_COLS  = ("Speed (m/s)", "v_env_mps")

    sorted_keys = sorted(resampled_laps.keys())
    result: dict[Any, dict[str, float]] = {}

    # Build lap_time lookup

    lt_map: dict[Any, float] = {}
    if lap_times:
        for i, k in enumerate(sorted_keys):
            if i < len(lap_times):
                lt_map[k] = lap_times[i]

    for key in sorted_keys:
        df = resampled_laps[key]
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue

        dist_col = next((c for c in _DIST_COLS if c in df.columns), None)
        spd_col  = next((c for c in _SPD_COLS  if c in df.columns), None)
        lat_col  = next((c for c in _LAT_COLS  if c in df.columns), None)
        if dist_col is None or spd_col is None or lat_col is None:
            continue

        distance  = pd.to_numeric(df[dist_col], errors="coerce").values.astype(float)
        speed     = pd.to_numeric(df[spd_col],  errors="coerce").values.astype(float)
        lat_accel = pd.to_numeric(df[lat_col],  errors="coerce").values.astype(float)

        if "mps2" not in lat_col:
            lat_accel = lat_accel * _G_VAL_SIM

        mask = np.isfinite(distance) & np.isfinite(speed) & np.isfinite(lat_accel)
        if mask.sum() < 30:
            continue

        d, v, a_lat = distance[mask], speed[mask], lat_accel[mask]

        # Ensure monotonic

        if not np.all(np.diff(d) > 0):
            idx = np.argsort(d)
            d, v, a_lat = d[idx], v[idx], a_lat[idx]
            um = np.concatenate([[True], np.diff(d) > 0.01])
            d, v, a_lat = d[um], v[um], a_lat[um]

        if len(d) < 30:
            continue

        curv = _estimate_track_curvature(d, v, a_lat)
        v_cap = float(np.percentile(v, 99.5)) * 1.15
        v_cap = max(v_cap, 30.0)

        _, theo_time = _point_mass_forward_backward(
            d, curv,
            lat_g=session_caps["lat_g"],
            brake_g=session_caps["brake_g"],
            traction_g=session_caps["traction_g"],
            v_max_cap=v_cap,
        )

        actual_time = lt_map.get(key, float("nan"))
        time_loss = actual_time - theo_time if math.isfinite(actual_time) else float("nan")

        result[key] = {
            "theo_time": theo_time,
            "actual_time": actual_time,
            "time_loss": time_loss,
        }

    return result


def _compute_data_optimal_boundary(
    all_lat: list[np.ndarray],
    all_lon: list[np.ndarray],
    n_angular_bins: int = 72,
    percentile: float = 99.0,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """
    Compute the optimal G-G boundary from the best data points.

    Uses angular binning: for each angular slice around (0,0), take the
    *percentile*-th radial distance.  This gives a smooth envelope that
    represents the maximum observed capability from the CSV data itself.

    Returns (boundary_lat, boundary_lon) arrays or None if insufficient data.
    """
    if not all_lat or not all_lon:
        return None

    concat_lat = np.concatenate(all_lat)
    concat_lon = np.concatenate(all_lon)
    if len(concat_lat) < 20:
        return None

    angles = np.arctan2(concat_lon, concat_lat)
    radii  = np.sqrt(concat_lat ** 2 + concat_lon ** 2)

    bin_edges = np.linspace(-np.pi, np.pi, n_angular_bins + 1)
    bin_centres = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    boundary_r = np.zeros(n_angular_bins)
    for i in range(n_angular_bins):
        mask = (angles >= bin_edges[i]) & (angles < bin_edges[i + 1])
        if mask.sum() >= 3:
            boundary_r[i] = float(np.percentile(radii[mask], percentile))
        elif mask.sum() > 0:
            boundary_r[i] = float(np.max(radii[mask]))
        else:
            boundary_r[i] = 0.0

    # Interpolate gaps (bins with zero points)

    nonzero = boundary_r > 0
    if nonzero.sum() < 6:
        return None

    # Simple linear interpolation for empty bins

    if not nonzero.all():
        good_idx = np.where(nonzero)[0]
        bad_idx  = np.where(~nonzero)[0]
        boundary_r[bad_idx] = np.interp(
            bad_idx.astype(float), good_idx.astype(float),
            boundary_r[good_idx],
        )

    # Smooth slightly to avoid jagged edges

    kernel = np.array([0.15, 0.25, 0.35, 0.25, 0.15])
    # Circular convolution

    padded = np.concatenate([boundary_r[-2:], boundary_r, boundary_r[:2]])
    smoothed = np.convolve(padded, kernel / kernel.sum(), mode="same")[2:-2]

    boundary_lat = smoothed * np.cos(bin_centres)
    boundary_lon = smoothed * np.sin(bin_centres)

    # Close the loop

    boundary_lat = np.append(boundary_lat, boundary_lat[0])
    boundary_lon = np.append(boundary_lon, boundary_lon[0])

    return boundary_lat, boundary_lon


def _compute_gg_lap_utilisation(
    lap_lat: np.ndarray,
    lap_lon: np.ndarray,
    boundary_lat: np.ndarray,
    boundary_lon: np.ndarray,
) -> float:
    """
    Compute how much of the optimal G-G envelope a lap utilises (0-100%).

    For each data point in the lap, compute its radial distance as a fraction
    of the boundary radius at the same angle.  Return the mean utilisation.
    """
    if len(lap_lat) < 5 or len(boundary_lat) < 6:
        return float("nan")

    # Build boundary lookup: angle -> radius

    # boundary has n+1 points (closed loop), use first n

    n_bnd = len(boundary_lat) - 1
    bnd_angles = np.arctan2(boundary_lon[:n_bnd], boundary_lat[:n_bnd])
    bnd_radii  = np.sqrt(boundary_lat[:n_bnd] ** 2 + boundary_lon[:n_bnd] ** 2)

    # Sort by angle for interpolation

    sort_idx = np.argsort(bnd_angles)
    bnd_angles_sorted = bnd_angles[sort_idx]
    bnd_radii_sorted  = bnd_radii[sort_idx]

    # For each lap point, find its angle and interpolate boundary radius

    lap_angles = np.arctan2(lap_lon, lap_lat)
    lap_radii  = np.sqrt(lap_lat ** 2 + lap_lon ** 2)

    bnd_r_at_lap = np.interp(lap_angles, bnd_angles_sorted, bnd_radii_sorted)

    # Utilisation = lap_radius / boundary_radius (capped at 1.0)

    valid = bnd_r_at_lap > 1e-6
    if valid.sum() < 5:
        return float("nan")

    ratios = np.clip(lap_radii[valid] / bnd_r_at_lap[valid], 0.0, 1.5)
    return float(np.mean(ratios) * 100.0)


def _plot_gg_diagram(
    resampled_laps: Optional[dict],
    friction_circle: Any = None,
    lap_times: Optional[list[float]] = None,
    theoretical_lap_time: Optional[float] = None,
) -> str:
    """
    G-G diagram: scatter of (lateral, longitudinal) accel coloured by lap.

    The optimal boundary is calibrated from the **best data points in the
    CSV data** using angular-binned percentile envelope.  Each lap's
    utilisation of this envelope is computed and annotated.

    Edge-case handling
    ~~~~~~~~~~~~~~~~~~
    - Empty / None / all-NaN data -> returns ""
    - Single lap -> fixed colour (no degenerate colourbar normalisation)
    - Near-zero data range -> minimum axis extent of +/-0.1 G
    - Missing speed data for some laps -> skips those laps gracefully
    """
    if not resampled_laps:
        return ""

    fig, ax = plt.subplots(figsize=_GG_FIGSIZE)
    _apply_dark_style(fig, ax)

    _LAT_COLS  = ("accel_lat_mps2", "Lateral acceleration (G) *calc")
    _LONG_COLS = ("accel_long_mps2", "Longitudinal acceleration (G) *calc")
    _G_VAL = 9.80665

    sorted_keys = sorted(resampled_laps.keys())
    n_laps = len(sorted_keys)
    if n_laps == 0:
        plt.close(fig)
        return ""

    cmap = plt.cm.cool  # type: ignore[attr-defined]
    has_points = False
    all_lat: list[np.ndarray] = []
    all_lon: list[np.ndarray] = []
    per_lap_data: list[tuple[Any, np.ndarray, np.ndarray]] = []  # (key, lat, lon)

    for idx, key in enumerate(sorted_keys):
        df = resampled_laps[key]
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue

        # Lateral

        lat_col = next((c for c in _LAT_COLS if c in df.columns), None)
        long_col = next((c for c in _LONG_COLS if c in df.columns), None)
        if lat_col is None or long_col is None:
            continue

        lat = pd.to_numeric(df[lat_col], errors="coerce").values.astype(float)
        lon = pd.to_numeric(df[long_col], errors="coerce").values.astype(float)

        # Convert to G if in m/s^2

        if "mps2" in lat_col:
            lat = lat / _G_VAL
            lon = lon / _G_VAL

        mask = np.isfinite(lat) & np.isfinite(lon)
        if mask.sum() < 5:
            continue

        # Check for degenerate data (all values near zero)

        lat_range = float(np.ptp(lat[mask]))
        lon_range = float(np.ptp(lon[mask]))
        if lat_range < 1e-6 and lon_range < 1e-6:
            continue

        # Safe colour mapping: avoid division by zero for single lap

        if n_laps <= 1:
            colour = cmap(0.5)
        else:
            colour = cmap(idx / (n_laps - 1))

        ax.scatter(lat[mask], lon[mask], s=1.2, alpha=0.25,
                   color=colour, rasterized=True)
        has_points = True
        all_lat.append(lat[mask])
        all_lon.append(lon[mask])
        per_lap_data.append((key, lat[mask], lon[mask]))

    if not has_points:
        plt.close(fig)
        return ""

    # --- Compute and overlay data-derived optimal boundary -
    boundary = _compute_data_optimal_boundary(all_lat, all_lon)
    if boundary is not None:
        bnd_lat, bnd_lon = boundary
        ax.plot(bnd_lat, bnd_lon, color=_ACCENT, linewidth=2.0,
                alpha=0.9, linestyle="-",
                label="Optimal boundary (from data)")
        ax.fill(bnd_lat, bnd_lon, color=_ACCENT, alpha=0.04)

    ax.set_xlabel("Lateral acceleration (G)")
    ax.set_ylabel("Longitudinal acceleration (G)")
    ax.set_title("G-G Diagram  --  Data-Calibrated Optimal", fontsize=11, fontweight="bold")

    # Ensure minimum axis range to avoid degenerate aspect ratio

    concat_lat = np.concatenate(all_lat) if all_lat else np.array([0.0])
    concat_lon = np.concatenate(all_lon) if all_lon else np.array([0.0])
    data_range = max(
        float(np.ptp(concat_lat)),
        float(np.ptp(concat_lon)),
        0.2,  # minimum 0.2 G range
    )
    lat_mid = float(np.mean(concat_lat))
    lon_mid = float(np.mean(concat_lon))
    half_ext = data_range * 0.6
    ax.set_xlim(lat_mid - half_ext, lat_mid + half_ext)
    ax.set_ylim(lon_mid - half_ext, lon_mid + half_ext)

    ax.set_aspect("equal", adjustable="box")
    ax.axhline(0, color="#555", linewidth=0.5, alpha=0.5)
    ax.axvline(0, color="#555", linewidth=0.5, alpha=0.5)
    ax.grid(True, alpha=0.12, color="#555")

    # Colourbar for lap progression (safe normalisation for 1-2 laps)

    vmin, vmax = 1, max(n_laps, 2)
    try:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin, vmax))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.8)
        cbar.set_label("Lap #", color=_TEXT_LIGHT, fontsize=8)
        cbar.ax.tick_params(colors=_TEXT_MED, labelsize=7)
    except Exception:
        pass  # skip colourbar if it fails

    # Only show legend if we have entries

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="upper right", fontsize=7, facecolor=_BG_CARD,
                  edgecolor="#444", labelcolor=_TEXT_LIGHT)
    gg_main_img = _fig_to_base64(fig)

    return gg_main_img


def _build_gg_per_lap_table(
    resampled_laps: Optional[dict],
    lap_times: Optional[list[float]] = None,
    theoretical_lap_time: Optional[float] = None,
    session_theoretical: Any = None,
) -> str:
    """
    Build an HTML table showing per-lap G-G utilisation, theoretical lap
    time (from ``friction_model.compute_session_theoretical``), and time
    loss for every lap and across the whole stint.

    Parameters -- session_theoretical:
        A ``SessionTheoreticalResult`` from
        ``friction_model.compute_session_theoretical()``.  If not
        provided, the function will attempt to compute it on the fly.
    """
    if not resampled_laps:
        return ""

    _LAT_COLS  = ("accel_lat_mps2", "Lateral acceleration (G) *calc")
    _LONG_COLS = ("accel_long_mps2", "Longitudinal acceleration (G) *calc")
    _G_VAL = 9.80665

    sorted_keys = sorted(resampled_laps.keys())
    if not sorted_keys:
        return ""

    # --- Collect all lap accel data for G-G boundary -- -

    all_lat: list[np.ndarray] = []
    all_lon: list[np.ndarray] = []
    per_lap: list[tuple[Any, np.ndarray, np.ndarray]] = []

    for key in sorted_keys:
        df = resampled_laps[key]
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        lat_col = next((c for c in _LAT_COLS if c in df.columns), None)
        long_col = next((c for c in _LONG_COLS if c in df.columns), None)
        if lat_col is None or long_col is None:
            continue
        lat = pd.to_numeric(df[lat_col], errors="coerce").values.astype(float)
        lon = pd.to_numeric(df[long_col], errors="coerce").values.astype(float)
        if "mps2" in lat_col:
            lat = lat / _G_VAL
            lon = lon / _G_VAL
        mask = np.isfinite(lat) & np.isfinite(lon)
        if mask.sum() < 5:
            continue
        all_lat.append(lat[mask])
        all_lon.append(lon[mask])
        per_lap.append((key, lat[mask], lon[mask]))

    if not per_lap:
        return ""

    boundary = _compute_data_optimal_boundary(all_lat, all_lon)

    # --- Obtain per-lap theoretical from session_theoretical -- # Prefer the pipeline-computed result; fall back to on-the-fly computation

    if session_theoretical is None:
        session_theoretical = _try_compute_session_theoretical(
            resampled_laps, lap_times,
        )

    # Extract per-lap data from the SessionTheoreticalResult

    per_lap_theo_map: dict[Any, dict[str, float]] = {}
    session_theo_time: Optional[float] = None
    caps: Optional[dict[str, float]] = None

    if session_theoretical is not None:
        # Access as dataclass or dict

        _st = session_theoretical
        st_main = getattr(_st, "session_theoretical", None)
        if st_main is not None:
            session_theo_time = getattr(st_main, "lap_time_s", None)
            caps = {
                "lat_g":      getattr(st_main, "peak_lat_g", 0),
                "brake_g":    getattr(st_main, "peak_brake_g", 0),
                "traction_g": getattr(st_main, "peak_traction_g", 0),
            }

        per_lap_list = getattr(_st, "per_lap", [])
        for pl in per_lap_list:
            key = getattr(pl, "lap_key", None)
            if key is not None:
                per_lap_theo_map[key] = {
                    "theo_time":   getattr(pl, "theo_time", float("nan")),
                    "actual_time": getattr(pl, "actual_time", float("nan")),
                    "time_loss":   getattr(pl, "time_loss", float("nan")),
                }

    # Use external theoretical if provided, else our computed one

    ref_theo_time = theoretical_lap_time or session_theo_time

    # --- Build lap-time lookup -- -

    lap_time_map: dict[Any, float] = {}
    if lap_times:
        for i, key in enumerate(sorted_keys):
            if i < len(lap_times):
                lap_time_map[key] = lap_times[i]

    # --- Build rows ---
    rows: list[str] = []

    total_actual = 0.0
    total_theo   = 0.0
    total_loss   = 0.0
    n_valid_laps = 0

    for key, lat, lon in per_lap:
        # G-G utilisation

        util = float("nan")
        if boundary is not None:
            util = _compute_gg_lap_utilisation(lat, lon, boundary[0], boundary[1])

        lt = lap_time_map.get(key, float("nan"))

        # Per-lap theoretical time

        lap_theo = per_lap_theo_map.get(key, {})
        theo_t = lap_theo.get("theo_time", float("nan"))
        loss   = lap_theo.get("time_loss", float("nan"))

        # Accumulate stint totals

        if math.isfinite(lt) and math.isfinite(theo_t):
            total_actual += lt
            total_theo   += theo_t
            total_loss   += loss if math.isfinite(loss) else 0.0
            n_valid_laps += 1

        # --- Format theoretical time cell -
        theo_str = f"{theo_t:.3f}s" if math.isfinite(theo_t) else " -- "

        # --- Format time loss cell -
        loss_str = " -- "
        loss_class = ""
        if math.isfinite(loss):
            if abs(loss) < 0.005:
                loss_str = "+/-0.000s"
                loss_class = 'class="best-val"'
            elif loss > 0:
                loss_str = f"+{loss:.3f}s"
                if loss < 0.3:
                    loss_class = 'style="color:#ffd600;"'
                elif loss < 0.8:
                    loss_class = 'style="color:#ff9800;"'
                else:
                    loss_class = 'class="worst-val"'
            else:
                loss_str = f"{loss:.3f}s"
                loss_class = 'class="best-val"'

        # --- Utilisation colour -
        if math.isfinite(util):
            if util >= 85:
                util_class = 'class="best-val"'
            elif util >= 70:
                util_class = 'style="color:#ffd600;"'
            else:
                util_class = 'class="worst-val"'
            util_str = f"{util:.1f}%"
        else:
            util_class = ""
            util_str = " -- "

        lt_str = f"{lt:.3f}s" if math.isfinite(lt) else " -- "

        peak_lat = float(np.max(np.abs(lat)))
        peak_lon_brake = float(np.min(lon))
        peak_lon_accel = float(np.max(lon))

        rows.append(
            f'<tr>'
            f'<td><b>L{key}</b></td>'
            f'<td>{lt_str}</td>'
            f'<td>{theo_str}</td>'
            f'<td {loss_class}>{loss_str}</td>'
            f'<td {util_class}>{util_str}</td>'
            f'<td>{peak_lat:.2f}G</td>'
            f'<td>{abs(peak_lon_brake):.2f}G</td>'
            f'<td>{peak_lon_accel:.2f}G</td>'
            f'</tr>'
        )

    if not rows:
        return ""

    # --- Stint summary row -- -

    stint_row = ""
    if n_valid_laps >= 2:
        loss_col = "worst-val" if total_loss > 0 else ""
        stint_row = (
            f'<tr style="border-top:2px solid #555; font-weight:600;">'
            f'<td>Stint ({n_valid_laps} laps)</td>'
            f'<td>{total_actual:.3f}s</td>'
            f'<td>{total_theo:.3f}s</td>'
            f'<td class="{loss_col}">+{total_loss:.3f}s</td>'
            f'<td colspan="4" style="color:var(--text-med); font-weight:400;">'
            f'Avg loss/lap: +{total_loss / n_valid_laps:.3f}s'
            f'</td>'
            f'</tr>'
        )

    # --- Capabilities badge

    caps_html = ""
    if caps is not None:
        caps_html = (
            f'<div class="pills" style="margin-bottom:8px;">'
            f'<div class="pill"><b>Peak Lat:</b> {caps["lat_g"]:.2f}G</div>'
            f'<div class="pill"><b>Peak Brake:</b> {caps["brake_g"]:.2f}G</div>'
            f'<div class="pill"><b>Peak Traction:</b> {caps["traction_g"]:.2f}G</div>'
        )
        if session_theo_time is not None:
            caps_html += f'<div class="pill"><b>Data Theoretical:</b> {session_theo_time:.3f}s</div>'
        caps_html += '</div>'

    sim_note = (
        "Theoretical optimal per lap computed via point-mass forward-backward "
        "simulation (friction_model) using the session's own speed-dependent "
        "grip envelope applied to each lap's curvature profile."
    )

    return f"""{caps_html}
    <div style="overflow-x:auto; margin-top:8px;">
    <p class="section-note">{sim_note}</p>
    <table class="cmp-table">
      <thead><tr>
        <th>Lap</th><th>Actual</th><th>Theoretical</th><th>Time Loss</th>
        <th>G-G Util.</th><th>Peak Lat</th><th>Peak Brake</th><th>Peak Accel</th>
      </tr></thead>
      <tbody>{"".join(rows)}{stint_row}</tbody>
    </table></div>"""


def _plot_grip_evolution(
    grip_evolution: Any,
    lap_times: Optional[list[float]] = None,
) -> str:
    """
    Peak lateral g per lap overlaid with lap time (dual y-axes).
    Includes trend line for degradation.
    """
    if grip_evolution is None:
        return ""

    # Support both dict (from .to_dict()) and dataclass/object (direct)
    def _gev(key, default=None):
        if isinstance(grip_evolution, dict):
            return grip_evolution.get(key, default)
        return getattr(grip_evolution, key, default)

    lat_g = _gev("peak_lateral_g_per_lap", [])
    brk_g = _gev("peak_braking_g_per_lap", [])
    n = len(lat_g)
    if n < 3:
        return ""

    fig, ax1 = plt.subplots(figsize=_GRIP_FIGSIZE)
    _apply_dark_style(fig, ax1)

    x = np.arange(1, n + 1)

    # Left axis: g-force

    ax1.plot(x, lat_g, color=_ACCENT, linewidth=1.8, marker="o",
             markersize=4, label="Peak lateral G", zorder=3)
    if len(brk_g) == n:
        ax1.plot(x, brk_g, color=_YELLOW, linewidth=1.4, marker="s",
                 markersize=3, label="Peak braking G", alpha=0.8, zorder=2)

    # Trend line

    lat_arr = np.array(lat_g, dtype=float)
    finite = np.isfinite(lat_arr)
    grip_direction = _gev("grip_direction", "stable")
    if finite.sum() >= 3:
        z = np.polyfit(x[finite] - 1, lat_arr[finite], 1)
        trend_slope = z[0]
        if trend_slope > 0.001:
            trend_label = "Grip improvement trend"
            trend_color = "#10b981"  # green
        elif trend_slope < -0.001:
            trend_label = "Degradation trend"
            trend_color = _RED
        else:
            trend_label = "Grip trend (stable)"
            trend_color = "#8b949e"
        ax1.plot(x, np.polyval(z, x - 1), color=trend_color, linewidth=1.2,
                 linestyle="--", alpha=0.7, label=trend_label, zorder=1)

    ax1.set_xlabel("Lap")
    ax1.set_ylabel("Peak acceleration (G)", color=_ACCENT)
    ax1.tick_params(axis="y", labelcolor=_ACCENT)
    ax1.grid(True, alpha=0.12, color="#555")

    # Right axis: lap time

    if lap_times and len(lap_times) >= n:
        ax2 = ax1.twinx()
        _apply_dark_style(fig, ax2)
        times = [lap_times[i] for i in range(n)]
        ax2.plot(x, times, color=_ACCENT_WARM, linewidth=1.2,
                 marker="^", markersize=3, alpha=0.75, label="Lap time")
        ax2.set_ylabel("Lap time (s)", color=_ACCENT_WARM)
        ax2.tick_params(axis="y", labelcolor=_ACCENT_WARM)

        # Combined legend

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2,
                   loc="upper right", fontsize=7,
                   facecolor=_BG_CARD, edgecolor="#444", labelcolor=_TEXT_LIGHT)
    else:
        ax1.legend(loc="upper right", fontsize=7,
                   facecolor=_BG_CARD, edgecolor="#444", labelcolor=_TEXT_LIGHT)

    # Annotate degradation/improvement

    deg_rate = _gev("degradation_rate_pct_per_lap", 0.0)
    drop_pct = _gev("estimated_grip_drop_pct", 0.0)
    evo_pct = _gev("track_evolution_pct", 0.0)
    warmup = _gev("thermal_phase_laps", 0)

    if grip_direction == "improving":
        title_detail = f"improvement +{evo_pct:.1f}%"
    elif grip_direction == "mixed":
        title_detail = f"mixed: evolution +{evo_pct:.1f}%, wear -{drop_pct:.1f}%"
    elif grip_direction == "degrading":
        title_detail = f"drop {drop_pct:.1f}%, rate {deg_rate:.2f}%/lap"
    else:
        title_detail = f"stable (drop {drop_pct:.1f}%)"

    ax1.set_title(
        f"Grip Evolution ({title_detail}, warm-up {warmup} laps)",
        fontsize=10, fontweight="bold",
    )

    fig.tight_layout()
    return _fig_to_base64(fig)


# ============================================================================

# GPS trace map  — static rendering for HTML reports

# ============================================================================


def _plot_gps_trace_map(
    resampled_laps: Optional[dict] = None,
    best_lap_key: Optional[int] = None,
) -> str:
    """
    Render a static GPS track map with the best lap highlighted.

    Returns base64 data URI, or empty string if GPS data is unavailable.
    Colours the best lap in accent colour and draws other laps faintly to
    show the track outline.  The map uses equal-aspect x/y scaling so the
    track shape is not distorted.
    """
    if not resampled_laps:
        return ""

    # Detect GPS column names
    _LAT_NAMES = ("Latitude (deg)", "latitude_deg", "lat")
    _LON_NAMES = ("Longitude (deg)", "longitude_deg", "lon")

    def _find_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        for c in df.columns:
            cl = c.lower()
            if "latitude" in cl or "lat" == cl:
                return c
        return None

    def _find_lon_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        for c in df.columns:
            cl = c.lower()
            if "longitude" in cl or "lon" == cl:
                return c
        return None

    # Collect GPS coordinates from all laps
    all_lats: list[np.ndarray] = []
    all_lons: list[np.ndarray] = []
    all_keys: list[int] = []
    best_lat: Optional[np.ndarray] = None
    best_lon: Optional[np.ndarray] = None

    for lap_key in sorted(resampled_laps.keys()):
        df = resampled_laps[lap_key]
        if df is None or len(df) == 0:
            continue
        lat_col = _find_col(df, _LAT_NAMES)
        lon_col = _find_lon_col(df, _LON_NAMES)
        if lat_col is None or lon_col is None:
            continue
        lats = pd.to_numeric(df[lat_col], errors="coerce").values
        lons = pd.to_numeric(df[lon_col], errors="coerce").values
        mask = np.isfinite(lats) & np.isfinite(lons)
        if mask.sum() < 5:
            continue
        lats = lats[mask]
        lons = lons[mask]
        # Simple check for zero lat/lon (sometimes GPS not present)
        if np.all(np.abs(lats) < 0.01) or np.all(np.abs(lons) < 0.01):
            continue
        all_lats.append(lats)
        all_lons.append(lons)
        all_keys.append(lap_key)
        if lap_key == best_lap_key:
            best_lat = lats
            best_lon = lons

    if not all_lats:
        return ""

    # Use first lap as best if best_lap_key not found
    if best_lat is None:
        best_lat = all_lats[0]
        best_lon = all_lons[0]

    # Project lat/lon to local meters (simple equirectangular)
    ref_lat = float(np.mean(best_lat))
    cos_lat = math.cos(math.radians(ref_lat))

    def _to_xy(lats: np.ndarray, lons: np.ndarray):
        x = (lons - np.mean(best_lon)) * cos_lat * 111_320.0
        y = (lats - np.mean(best_lat)) * 111_320.0
        return x, y

    fig, ax = plt.subplots(figsize=(7.0, 7.0))
    _apply_dark_style(fig, ax)

    # Draw other laps faintly
    for lats, lons in zip(all_lats, all_lons):
        x, y = _to_xy(lats, lons)
        ax.plot(x, y, color="#333333", linewidth=0.5, alpha=0.4)

    # Draw best lap with speed colouring if speed data available
    bx, by = _to_xy(best_lat, best_lon)

    # Try to get speed data for colour mapping
    speed_arr = None
    if best_lap_key is not None and best_lap_key in resampled_laps:
        bdf = resampled_laps[best_lap_key]
        for sc in ("Speed (m/s)", "speed_mps", "Speed"):
            if sc in bdf.columns:
                sv = pd.to_numeric(bdf[sc], errors="coerce").values
                mask = np.isfinite(best_lat) & np.isfinite(best_lon)
                sv = sv[mask] if len(sv) == len(mask) else None
                if sv is not None and len(sv) == len(bx):
                    speed_arr = sv * 3.6  # m/s → km/h
                break

    if speed_arr is not None and len(speed_arr) == len(bx):
        # Speed-coloured polyline: blue (slow) → green → yellow → red (fast)
        from matplotlib.collections import LineCollection
        points = np.column_stack([bx, by]).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        spd_min = float(np.nanmin(speed_arr))
        spd_max = float(np.nanmax(speed_arr))
        if spd_max - spd_min < 1.0:
            spd_max = spd_min + 1.0
        norm = plt.Normalize(spd_min, spd_max)
        cmap = plt.cm.get_cmap("RdYlGn_r")
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=2.5)
        lc.set_array(speed_arr[:-1])
        ax.add_collection(lc)
        cbar = fig.colorbar(lc, ax=ax, pad=0.02, shrink=0.8)
        cbar.set_label("Speed (km/h)", color=_TEXT_LIGHT, fontsize=8)
        cbar.ax.tick_params(colors=_TEXT_MED, labelsize=7)
    else:
        ax.plot(bx, by, color=_ACCENT, linewidth=2.5, label="Best lap")

    # Start/Finish marker
    ax.plot(bx[0], by[0], "o", color=_ACCENT_WARM, markersize=8,
            markeredgecolor="white", markeredgewidth=1.2, zorder=5)
    ax.annotate("S/F", (bx[0], by[0]), fontsize=7, color=_ACCENT_WARM,
                ha="left", va="bottom", xytext=(5, 5),
                textcoords="offset points", fontweight="bold")

    ax.set_aspect("equal")
    ax.set_xlabel("← West  |  East →", fontsize=8)
    ax.set_ylabel("← South  |  North →", fontsize=8)
    ax.set_title("Track Map — Best Lap", fontsize=11, fontweight="bold")
    ax.grid(True, alpha=0.1, color="#555")
    # Remove tick labels (they're in raw metres, not meaningful)
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    fig.tight_layout()
    return _fig_to_base64(fig)


# ============================================================================

# HTML fragment builders  — physics sections

# ============================================================================


def _build_corner_table_html(
    corner_performances: Optional[list] = None,
) -> str:
    """Build HTML table for corner-by-corner performance."""
    if not corner_performances:
        return ""

    # Sort by time_loss descending

    sorted_perfs = sorted(
        corner_performances,
        key=lambda p: getattr(p, "time_loss_s", 0.0)
            if hasattr(p, "time_loss_s") else p.get("time_loss_s", 0.0),
        reverse=True,
    )

    def _get(p, key, default=0.0):
        if hasattr(p, key):
            return getattr(p, key)
        if isinstance(p, dict):
            return p.get(key, default)
        return default

    def _speed_class(actual, theoretical):
        if theoretical <= 0:
            return ""
        ratio = actual / theoretical
        if ratio >= 0.95:
            return 'class="best-val"'
        elif ratio >= 0.85:
            return 'style="color:#ffd600;"'
        else:
            return 'class="worst-val"'

    rows = []
    for p in sorted_perfs:
        cid = _get(p, "corner_id", 0)
        s_start = _get(p, "s_start", 0)
        loss = _get(p, "time_loss_s", 0)
        grip = _get(p, "grip_utilisation_pct", 0)
        hint = _get(p, "coaching_hint", "")

        theo_apex = _get(p, "theoretical_apex_speed_mps", 0)
        actual_apex = _get(p, "actual_apex_speed_mps", 0)
        theo_entry = _get(p, "theoretical_entry_speed_mps", 0)
        actual_entry = _get(p, "actual_entry_speed_mps", 0)
        bp_delta = _get(p, "braking_point_delta_m", 0)
        lf = _get(p, "limiting_factor", "")
        priority = _get(p, "corner_priority", "")
        coaching_txt = _get(p, "coaching_text", "")

        # Timeline mistakes
        mistakes_html = ""
        if isinstance(p, dict):
            timeline = p.get("timeline", {})
            if timeline:
                mistake_list = timeline.get("mistakes", [])
                if mistake_list:
                    top = mistake_list[0]
                    sev = top.get("severity", 0)
                    sev_color = "#ff4444" if sev > 0.6 else ("#ffd600" if sev > 0.3 else "#88ff88")
                    mistakes_html = (
                        f'<span style="color:{sev_color};font-size:0.75rem;">'
                        f'{top.get("type", "").replace("_", " ")}'
                        f' ({sev:.0%})</span>'
                    )

        apex_class = _speed_class(actual_apex, theo_apex) if theo_apex > 0 else ""
        entry_class = _speed_class(actual_entry, theo_entry) if theo_entry > 0 else ""

        # Grip colour

        if grip >= 90:
            grip_class = 'class="best-val"'
        elif grip >= 75:
            grip_class = 'style="color:#ffd600;"'
        else:
            grip_class = 'class="worst-val"'

        # Loss colour

        if loss < 0.05:
            loss_class = 'class="best-val"'
        elif loss < 0.2:
            loss_class = 'style="color:#ffd600;"'
        else:
            loss_class = 'class="worst-val"'

        row = f"""<tr>
          <td><b>C{cid}</b></td>
          <td>{s_start:.0f}m</td>
          <td {entry_class}>{actual_entry*3.6:.1f} / {theo_entry*3.6:.1f}</td>
          <td {apex_class}>{actual_apex*3.6:.1f} / {theo_apex*3.6:.1f}</td>
          <td {grip_class}>{grip:.0f}%</td>
          <td>{bp_delta:+.0f}m</td>
          <td {loss_class}>{loss:.3f}s</td>
          <td style="font-size:0.75rem;color:#9a9a9a;max-width:250px;white-space:normal;">{hint}</td>
          <td>{mistakes_html}</td>
          <td>{priority}</td>
          <td style="font-size:0.75rem;color:#9a9a9a;max-width:250px;white-space:normal;">{coaching_txt}</td>
        </tr>"""
        rows.append(row)

    return f"""<div style="overflow-x:auto;">
    <table class="cmp-table">
      <thead><tr>
        <th>Corner</th><th>Location</th>
        <th>Entry (km/h)</th><th>Apex (km/h)</th>
        <th>Grip</th><th>Brake Pt</th>
        <th>Time Loss</th><th>Coaching</th>
        <th>Mistakes</th><th>Priority</th><th>Why</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table></div>"""


def _build_quality_badge_html(
    score_result: Optional[dict] = None,
    data_quality: Any = None,
    session_meta: Optional[dict] = None,
) -> str:
    """Build a compact data quality indicator badge."""
    parts: list[str] = []

    # Confidence level

    confidence = 1.0
    if score_result:
        confidence = score_result.get("data_confidence", 1.0)
    elif data_quality is not None:
        confidence = getattr(data_quality, "overall_confidence", 1.0)

    if confidence >= 0.8:
        level, colour = "HIGH", _GREEN
    elif confidence >= 0.5:
        level, colour = "MEDIUM", _YELLOW
    else:
        level, colour = "LOW", _RED

    # Build context string

    context_parts = []
    if score_result:
        # Try to find n_laps from sub_scores

        rob = score_result.get("sub_scores", {}).get("robustness", {}).get("detail", {})
        n_laps = rob.get("n_laps")
        if n_laps:
            context_parts.append(f"{n_laps} laps")
    if session_meta:
        ts = session_meta.get("track_state", "")
        if ts:
            context_parts.append(ts)

    ctx_str = ", ".join(context_parts) if context_parts else ""
    if ctx_str:
        ctx_str = f" ({ctx_str})"

    parts.append(
        f'<span class="pill" style="border:1px solid {colour};">'
        f'<b style="color:{colour};">Analysis confidence: {level}</b>{ctx_str}'
        f'</span>'
    )

    return " ".join(parts)


def _build_sim_method_badge_html(
    score_result: Optional[dict] = None,
    using_data_theoretical: bool = False,
) -> str:
    """Build the simulation method badge shown next to the overall score."""
    # Data-driven point-mass takes priority when no external sim provided

    if using_data_theoretical:
        icon = "&#x1F3CE;"  # racing car
        label = "Data-driven point-mass simulation"
        colour = _GREEN
        return (
            f'<div class="pill" style="display:inline-block;margin-top:6px;'
            f'border:1px solid {colour};">'
            f'{icon} <b style="color:{colour};">{label}</b></div>'
        )

    if not score_result:
        return ""

    method = score_result.get("simulation_method", "percentile_envelope")
    if method == "hybrid":
        icon = "&#x1F9EC;"  # DNA helix
        label = "Hybrid simulation (telemetry-fitted physics)"
        colour = _ACCENT
    elif method == "physics":
        icon = "&#x1F52C;"  # microscope
        label = "Physics simulation"
        colour = _ACCENT
    elif "phase_aware" in method:
        icon = "&#x1F4CA;"  # chart
        label = "Phase-aware statistical envelope"
        colour = _YELLOW
    else:
        icon = "&#x1F4CA;"  # chart
        label = "Statistical envelope (limited data for physics model)"
        colour = _TEXT_MED

    return (
        f'<div class="pill" style="display:inline-block;margin-top:6px;'
        f'border:1px solid {colour};">'
        f'{icon} <b style="color:{colour};">{label}</b></div>'
    )



# ============================================================================

# Jinja2 HTML template

# ============================================================================


_HTML_TEMPLATE: Final[str] = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  :root {
    --bg:       {{ bg_dark }};
    --bg-card:  {{ bg_card }};
    --text:     {{ text_light }};
    --text-med: {{ text_med }};
    --accent:   {{ accent }};
    --green:    {{ green }};
    --red:      {{ red }};
    --yellow:   {{ yellow }};
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.55;
    padding: 24px;
    max-width: 1200px;
    margin: 0 auto;
  }
  h1 { font-size: 1.6rem; margin-bottom: 4px; }
  h2 {
    font-size: 1.15rem; margin: 28px 0 12px 0;
    border-bottom: 1px solid #333; padding-bottom: 6px;
    color: var(--accent);
  }
  .meta { color: var(--text-med); font-size: 0.82rem; margin-bottom: 20px; }
  .card {
    background: var(--bg-card);
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 18px;
    border: 1px solid #252830;
  }
  .grade-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 52px; height: 52px;
    border-radius: 50%;
    font-size: 1.6rem; font-weight: 800;
    margin-right: 16px;
    flex-shrink: 0;
  }
  .grade-S { background: linear-gradient(135deg, #3ddc84, #00bfa5); color: #000; }
  .grade-A { background: linear-gradient(135deg, #00d4ff, #0091ea); color: #000; }
  .grade-B { background: linear-gradient(135deg, #ffd600, #ffc107); color: #000; }
  .grade-C { background: linear-gradient(135deg, #ff9800, #f57c00); color: #000; }
  .grade-D { background: linear-gradient(135deg, #ff6b35, #e64a19); color: #fff; }
  .grade-F { background: linear-gradient(135deg, #ff4444, #c62828); color: #fff; }
  .score-row {
    display: flex; align-items: center;
    margin-bottom: 6px;
  }
  .score-num {
    font-size: 2.0rem; font-weight: 700;
    margin-right: 8px;
  }
  .score-max { color: var(--text-med); font-size: 1.0rem; }
  .strength  { color: var(--green); }
  .weakness  { color: var(--red);   }
  .plot-img  {
    width: 100%; border-radius: 8px;
    margin: 8px 0;
  }
  /* -- - Comparison table -- - */
  .cmp-table {
    width: 100%; border-collapse: collapse;
    font-size: 0.85rem;
  }
  .cmp-table th {
    text-align: left; padding: 8px 10px;
    background: #1d2028; color: var(--accent);
    border-bottom: 2px solid #333;
    white-space: nowrap;
  }
  .cmp-table td {
    padding: 7px 10px; border-bottom: 1px solid #252830;
    white-space: nowrap;
  }
  .cmp-table tr:hover td { background: #1a1d25; }
  .best-val  { color: var(--green); font-weight: 600; }
  .worst-val { color: var(--red);   font-weight: 600; }
  /* -- - Sub-score detail pills -- - */
  .pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .pill {
    background: #22252e; border-radius: 6px;
    padding: 5px 12px; font-size: 0.78rem;
    color: var(--text-med);
  }
  .pill b { color: var(--text); margin-right: 4px; }
  /* -- - Responsive -- - */
  @media (max-width: 700px) {
    body { padding: 12px; }
    .card { padding: 14px 16px; }
    .score-num { font-size: 1.5rem; }
  }
  .section-note {
    color: var(--text-med); font-size: 0.8rem;
    margin-bottom: 10px; font-style: italic;
  }
  .no-data {
    color: var(--text-med); font-style: italic;
    padding: 20px 0;
  }
  /* -- - Physics report badges -- - */
  .badge-row {
    display: flex; flex-wrap: wrap; gap: 8px;
    align-items: center; margin-top: 8px;
  }
  .corner-table td { vertical-align: top; }
</style>
</head>
<body>

<!-- ====== Header ====== -->
<h1>{{ title }}</h1>
<div class="meta">
  {% if session_meta.track_id %}Track: <b>{{ session_meta.track_id }}</b>  --  {% endif %}
  {% if session_meta.track_state %}Condition: <b>{{ session_meta.track_state }}</b>  --  {% endif %}
  {% if session_meta.driver_name %}Driver: <b>{{ session_meta.driver_name }}</b>  --  {% endif %}
  {% if session_meta.session_id %}Session: {{ session_meta.session_id }}  --  {% endif %}
  {% if session_meta.date %}{{ session_meta.date }}  --  {% endif %}
  Generated {{ generated_at }}
</div>

{% if conditions_html %}
<!-- ====== Conditions ====== -->
<h2>Conditions</h2>
<div class="card">
  {{ conditions_html }}
</div>
{% endif %}

{% if trimmed_laps_notice %}
<!-- ====== Trimmed Laps Notice ====== -->
<div class="card" style="border-left: 3px solid var(--yellow); margin-bottom:18px;">
  <p style="font-size:0.85rem; color:var(--yellow); font-weight:600; margin-bottom:4px;">Laps Excluded from Analysis</p>
  <p style="font-size:0.82rem; color:var(--text-med);">{{ trimmed_laps_notice }}</p>
</div>
{% endif %}

<!-- ====== Weather Conditions Banner (Section 1) ====== -->
{% if weather_banner_html %}
<h2>Session Weather</h2>
<div class="card">
  {{ weather_banner_html }}
</div>
{% endif %}

<!-- ====== Session Score ====== -->
<h2>Session Score</h2>
<div class="card">
{% if score_result %}
  <div class="score-row">
    <div class="grade-badge grade-{{ score_result.grade }}">{{ score_result.grade }}</div>
    <div>
      <span class="score-num">{{ "%.1f"|format(score_result.total_score) }}</span>
      <span class="score-max">/ 100</span>
    </div>
  </div>
  {% if score_result.session_type %}
    <div class="pill" style="display:inline-block; margin-top:4px;">
      Session type: <b>{{ score_result.session_type }}</b>
    </div>
  {% endif %}
  {% if sim_method_badge %}
    {{ sim_method_badge }}
  {% endif %}
  {% if quality_badge %}
    <div class="badge-row">{{ quality_badge }}</div>
  {% endif %}
  {% if score_result.strengths %}
    <p style="margin-top:10px;">Strengths:
      {% for s in score_result.strengths %}
        <span class="strength">{{ s }}{% if not loop.last %}, {% endif %}</span>
      {% endfor %}
    </p>
  {% endif %}
  {% if score_result.weaknesses %}
    <p>Weaknesses:
      {% for w in score_result.weaknesses %}
        <span class="weakness">{{ w }}{% if not loop.last %}, {% endif %}</span>
      {% endfor %}
    </p>
  {% endif %}
{% else %}
  <p class="no-data">No scoring data available.</p>
{% endif %}
</div>

<!-- ====== Sub-Scores ====== -->
<h2>Sub-Score Breakdown</h2>
<div class="card">
{% if sub_scores_img %}
  <img class="plot-img" src="{{ sub_scores_img }}" alt="Sub-score breakdown chart">
{% endif %}
{% if sub_scores %}
  <div class="pills">
    {% for cat, info in sub_scores.items() %}
      <div class="pill"><b>{{ cat|capitalize }}:</b> {{ "%.1f"|format(info.score) }}/{{ "%.0f"|format(info.max) }} ({{ "%.0f"|format(info.pct) }}%)</div>
    {% endfor %}
  </div>
  {% for cat, info in sub_scores.items() %}
    {% if info.detail and info.detail is mapping %}
      <div style="margin-top:10px;">
        <span style="color:{{ accent }}; font-size:0.85rem; font-weight:600;">{{ cat|capitalize }} detail</span>
        <div class="pills">
          {% for k, v in info.detail.items() %}
            <div class="pill"><b>{{ k }}:</b>
              {% if v is none %}n/a{% elif v is number %}{{ "%.3f"|format(v) }}{% else %}{{ v }}{% endif %}
            </div>
          {% endfor %}
        </div>
      </div>
    {% endif %}
  {% endfor %}
{% else %}
  <p class="no-data">No sub-score data available.</p>
{% endif %}
</div>

<!-- ====== Speed Trace ====== -->
<h2>Theoretical vs Best Lap</h2>
<div class="card">
{% if speed_trace_img %}
  <img class="plot-img" src="{{ speed_trace_img }}" alt="Theoretical vs best lap speed trace">
  {% if using_data_theoretical %}
    <p class="section-note">Cyan = data-derived theoretical (point-mass simulation{% if data_theoretical_time %}, {{ data_theoretical_time }}{% endif %}).  Orange = driver's best lap.</p>
  {% else %}
    <p class="section-note">Cyan = theoretical lap.  Orange = driver's best lap.</p>
  {% endif %}
{% else %}
  <p class="no-data">Insufficient lap data for speed trace plot.</p>
{% endif %}
</div>

<!-- ====== GPS Track Map ====== -->
{% if gps_trace_img %}
<h2>Track Map</h2>
<div class="card">
  <img class="plot-img" src="{{ gps_trace_img }}" alt="GPS track map">
  <p class="section-note">Best lap GPS trace colour-coded by speed.  Orange marker = Start/Finish.  Grey lines = other laps.  Equal-aspect projection preserves track shape.</p>
</div>
{% endif %}

<!-- ====== Condition Timeline Strip (Section 2) ====== -->
{% if condition_timeline_img %}
<h2>Condition Timeline</h2>
<div class="card">
  <img class="plot-img" src="{{ condition_timeline_img }}" alt="Condition timeline strip">
  <p class="section-note">Colour-coded lap-by-lap track condition. Dry = green, Greasy = yellow, Damp = light blue, Wet = blue. Numbers = air temperature.</p>
</div>
{% endif %}

<!-- ====== Delta Heatmap ====== -->
<h2>Segment Delta Heatmap</h2>
<div class="card">
{% if heatmap_img %}
  <img class="plot-img" src="{{ heatmap_img }}" alt="Segment delta heatmap">
  <p class="section-note">Green = time gained vs reference.  Red = time lost.  Values in milliseconds.  Cause labels along top: ENT=entry, MID=mid-corner, EXT=exit, INS=instability, LIN=line.</p>
{% else %}
  <p class="no-data">Insufficient segment data for delta heatmap.</p>
{% endif %}
</div>

<!-- ====== Driver Comparison ====== -->
<h2>Driver Comparison</h2>
<div class="card">
{% if driver_rows %}
  <div style="overflow-x:auto;">
  <table class="cmp-table">
    <thead>
      <tr>
        <th>Driver</th>
        <th>Sessions</th>
        <th>Avg Pace Δ (s)</th>
        <th>Consistency</th>
        <th>Aggression</th>
        <th>Smoothness</th>
        <th>Trend</th>
        <th>Avg Score</th>
      </tr>
    </thead>
    <tbody>
    {% for d in driver_rows %}
      <tr>
        <td style="font-weight:600;">{{ d.driver_name }}</td>
        <td>{{ d.n_sessions }}</td>
        <td class="{{ d.pace_class }}">{{ d.pace_delta }}</td>
        <td class="{{ d.consistency_class }}">{{ d.consistency }}</td>
        <td>{{ d.aggression }}</td>
        <td class="{{ d.smoothness_class }}">{{ d.smoothness }}</td>
        <td>{{ d.trend }}</td>
        <td class="{{ d.score_class }}">{{ d.avg_score }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
{% else %}
  <p class="no-data">No driver profile data available for comparison.</p>
{% endif %}
</div>

<!-- Physics Speed Overlay removed — covered by Theoretical vs Best Lap above -->

<!-- ====== G-G Diagram ====== -->
{% if gg_diagram_img %}
<h2>G-G Diagram</h2>
<div class="card">
  <img class="plot-img" src="{{ gg_diagram_img }}" alt="G-G diagram">
  <p class="section-note">Combined lateral vs longitudinal acceleration across all laps.  Colour gradient = lap progression (early &rarr; late).  Cyan boundary = optimal envelope derived from the best data points across the session.  Theoretical times computed via point-mass forward-backward simulation using the session's peak G-force capabilities.</p>
  {% if gg_per_lap_table %}
    {{ gg_per_lap_table }}
  {% endif %}
</div>
{% endif %}

<!-- ====== Corner Performance ====== -->
{% if corner_table_html %}
<h2>Corner-by-Corner Performance</h2>
<div class="card">
  <p class="section-note">Sorted by time loss (biggest opportunity first).  Speeds shown as actual / theoretical in km/h.  Green = &ge;95% of theoretical, yellow = 85&ndash;95%, red = &lt;85%.</p>
  {{ corner_table_html }}
</div>
{% endif %}

<!-- ====== Grip Evolution ====== -->
{% if grip_evolution_img %}
<h2>Grip Evolution</h2>
<div class="card">
  <img class="plot-img" src="{{ grip_evolution_img }}" alt="Grip evolution chart">
  <p class="section-note">Peak lateral and braking G per lap with degradation trend.  Orange triangles = lap time (right axis).</p>
</div>
{% endif %}

<!-- ====== Per-Phase Analysis (Section 3) ====== -->
{% if phase_cards_html %}
<h2>Per-Phase Analysis</h2>
{{ phase_cards_html }}
{% endif %}

<!-- ====== Adaptation Score (Section 4) ====== -->
{% if adaptation_score_html %}
<h2>Weather Adaptation Score</h2>
<div class="card">
  {{ adaptation_score_html }}
</div>
{% endif %}

<!-- ====== Weather Coaching (Section 5) ====== -->
{% if weather_coaching_html %}
<h2>Weather-Adjusted Coaching</h2>
<div class="card">
  {{ weather_coaching_html }}
</div>
{% endif %}

<!-- ====== Coaching Guide ====== -->
{% if coaching_guide %}
<h2>Your Coaching Guide</h2>

{% if coaching_guide.session_summary %}
<div class="card" style="border-left: 3px solid var(--accent); margin-bottom:16px">
  <p style="font-size:0.95rem">{{ coaching_guide.session_summary }}</p>
</div>
{% endif %}

{% if coaching_guide.focus_areas %}
<h3 style="margin-top:16px; color:var(--accent)">Top Focus Areas</h3>
{% for area in coaching_guide.focus_areas %}
<div class="card" style="margin-bottom:8px; border-left: 3px solid #ff9800">
  <div style="display:flex; justify-content:space-between; margin-bottom:4px">
    <span style="font-weight:600">Corner {{ area.corner_id }}</span>
    <span style="color:#ff9800; font-weight:600">+{{ area.potential_gain_s }}s potential</span>
  </div>
  <p style="font-size:0.85rem; color:var(--text-med)">{{ area.description }}</p>
  <p style="font-size:0.85rem; color:var(--green); margin-top:4px"><b>Action:</b> {{ area.action }}</p>
</div>
{% endfor %}
{% endif %}

{% if coaching_guide.corner_guide %}
<h3 style="margin-top:16px; color:var(--accent)">Corner Targets</h3>
<table class="cmp-table">
  <thead><tr>
    <th>Corner</th>
    <th>Entry (now / target)</th>
    <th>Apex (now / target)</th>
    <th>Exit (now / target)</th>
    <th>Loss</th>
  </tr></thead>
  <tbody>
  {% for cg in coaching_guide.corner_guide %}
  <tr>
    <td>C{{ cg.corner_id }}</td>
    <td>{{ cg.entry_speed_target_kph }} / <b>{{ cg.target_entry_kph if cg.target_entry_kph is not none else '\u2014' }}</b> km/h</td>
    <td>{{ cg.apex_speed_target_kph }} / <b>{{ cg.target_apex_kph if cg.target_apex_kph is not none else '\u2014' }}</b> km/h</td>
    <td>{{ cg.exit_speed_target_kph }} / <b>{{ cg.target_exit_kph if cg.target_exit_kph is not none else '\u2014' }}</b> km/h</td>
    <td style="color:var(--red)">{{ cg.time_loss_s }}s</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

{% if coaching_guide.adaptation_tips %}
<h3 style="margin-top:16px; color:var(--accent)">Condition Adaptation</h3>
<div class="card">
  {% for tip in coaching_guide.adaptation_tips %}
  <p style="font-size:0.85rem; margin:4px 0">&#x2022; {{ tip }}</p>
  {% endfor %}
</div>
{% endif %}

{% if coaching_guide.strengths or coaching_guide.weaknesses %}
<div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px">
  {% if coaching_guide.strengths %}
  <div class="card" style="border-left:3px solid var(--green)">
    <h4 style="color:var(--green); margin-bottom:6px">Strengths</h4>
    {% for s in coaching_guide.strengths %}
    <p style="font-size:0.85rem; margin:2px 0">&#x2713; {{ s }}</p>
    {% endfor %}
  </div>
  {% endif %}
  {% if coaching_guide.weaknesses %}
  <div class="card" style="border-left:3px solid var(--red)">
    <h4 style="color:var(--red); margin-bottom:6px">Areas to Improve</h4>
    {% for w in coaching_guide.weaknesses %}
    <p style="font-size:0.85rem; margin:2px 0">&#x25B6; {{ w }}</p>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endif %}

{% endif %}

<!-- ====== Traffic Detection & Lap Inclusion ====== -->
{% if traffic_html %}
{{ traffic_html }}
{% endif %}

<!-- ====== Confidence Assessment ====== -->
{% if confidence_html %}
{{ confidence_html }}
{% endif %}

<!-- ====== Grip Map ====== -->
{% if grip_map_html %}
{{ grip_map_html }}
{% endif %}

<!-- ====== Explainability Panel ====== -->
{% if explainability_html %}
{{ explainability_html }}
{% endif %}

<!-- ====== Uncertainty Bands ====== -->
{% if uncertainty_html %}
{{ uncertainty_html }}
{% endif %}

<!-- ====== Distance Quality Debug ====== -->
{% if distance_quality_html %}
{{ distance_quality_html }}
{% endif %}

<div style="text-align:center; color:var(--text-med); font-size:0.72rem; margin-top:32px; padding-bottom:16px;">
  Report generated by <b>reporting_html.py</b>  --  motorsport telemetry pipeline
</div>

</body>
</html>"""


# ============================================================================

# Driver comparison table builder

# ============================================================================


def _build_driver_rows(
    driver_profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Convert a list of driver profile dicts into table-ready row dicts with
    formatting and conditional CSS classes for best/worst highlighting.
    """
    if not driver_profiles:
        return []

    rows: list[dict[str, Any]] = []
    for dp in driver_profiles:
        summary = dp.get("summary", {}) if isinstance(dp.get("summary"), dict) else {}

        pace_val        = _safe_float(summary.get("mean_pace_delta_s"))
        consistency_val = _safe_float(summary.get("consistency_rating"))
        aggression_val  = _safe_float(summary.get("aggression_index"))
        smoothness_val  = _safe_float(summary.get("smoothness_index"))
        avg_score_val   = _safe_float(summary.get("mean_session_score"))
        trend_label     = summary.get("trend_label", " —")

        rows.append({
            "driver_name":  dp.get("driver_name", "Unknown"),
            "n_sessions":   dp.get("n_sessions", 0),
            "pace_delta":   f"{pace_val:+.3f}" if math.isfinite(pace_val) else " —",
            "consistency":  f"{consistency_val:.2f}" if math.isfinite(consistency_val) else " —",
            "aggression":   f"{aggression_val:.2f}" if math.isfinite(aggression_val) else " —",
            "smoothness":   f"{smoothness_val:.2f}" if math.isfinite(smoothness_val) else " —",
            "trend":        trend_label if trend_label else " —",
            "avg_score":    f"{avg_score_val:.1f}" if math.isfinite(avg_score_val) else " —",
            # Raw values for ranking

            "_pace":        pace_val,
            "_consistency": consistency_val,
            "_smoothness":  smoothness_val,
            "_score":       avg_score_val,
        })

    # Highlight best/worst for numeric columns

    _highlight_column(rows, "_pace",        "pace_class",        lower_is_better=True)
    _highlight_column(rows, "_consistency", "consistency_class", lower_is_better=False)
    _highlight_column(rows, "_smoothness",  "smoothness_class",  lower_is_better=False)
    _highlight_column(rows, "_score",       "score_class",       lower_is_better=False)

    return rows


def _highlight_column(
    rows: list[dict[str, Any]],
    raw_key: str,
    class_key: str,
    lower_is_better: bool,
) -> None:
    """
    Set ``class_key`` to ``'best-val'`` / ``'worst-val'`` on the
    best and worst rows for a numeric column.
    """
    vals = [(i, r[raw_key]) for i, r in enumerate(rows) if math.isfinite(r[raw_key])]
    if len(vals) < 2:
        for r in rows:
            r[class_key] = ""
        return

    sorted_v = sorted(vals, key=lambda x: x[1])
    best_i  = sorted_v[0][0]  if lower_is_better else sorted_v[-1][0]
    worst_i = sorted_v[-1][0] if lower_is_better else sorted_v[0][0]

    for i, r in enumerate(rows):
        if i == best_i:
            r[class_key] = "best-val"
        elif i == worst_i:
            r[class_key] = "worst-val"
        else:
            r[class_key] = ""


# ============================================================================

# Weather / Meteo section builders

# ============================================================================

# Condition colour mapping used by both the banner and the timeline strip.
_CONDITION_COLORS: Final[dict[str, str]] = {
    "dry":    "#3ddc84",
    "greasy": "#ffd600",
    "damp":   "#4fc3f7",
    "wet":    "#1565c0",
}


def _condition_color(label: str) -> str:
    """Return the hex colour for a track-condition label (case-insensitive)."""
    return _CONDITION_COLORS.get(str(label).strip().lower(), "#888888")


def _build_weather_conditions_banner(
    weather_timeline: pd.DataFrame,
) -> str:
    """
    **Section 1 -- Session Conditions Banner**

    Renders a compact banner summarising the session weather: condition
    transitions, temperature range, wind range, and grip range.

    Expects *weather_timeline* to have per-lap rows with columns such as
    ``condition`` (str), ``air_temp_c`` (float), ``track_temp_c`` (float),
    ``wind_speed_mps`` (float), ``grip_index`` (float).  All columns are
    optional; the banner degrades gracefully.
    """
    if weather_timeline is None or weather_timeline.empty:
        return ""

    parts: list[str] = []

    # --- Condition summary (e.g. "Dry -> Wet" or "Dry throughout") ---
    conditions: list[str] = []
    if "condition" in weather_timeline.columns:
        raw = weather_timeline["condition"].dropna().astype(str).str.strip().str.capitalize()
        # Deduplicate consecutive identical conditions
        prev = None
        for c in raw:
            if c != prev:
                conditions.append(c)
                prev = c

    if len(conditions) == 0:
        cond_text = "Unknown"
    elif len(conditions) == 1:
        cond_text = f"{conditions[0]} throughout"
    else:
        cond_text = " &rarr; ".join(conditions)

    # Colour badges for each unique condition
    badges = ""
    seen: set[str] = set()
    for c in conditions:
        if c.lower() not in seen:
            seen.add(c.lower())
            col = _condition_color(c)
            badges += (
                f'<span style="display:inline-block;width:12px;height:12px;'
                f'border-radius:3px;background:{col};margin-right:4px;'
                f'vertical-align:middle;"></span>'
            )
    parts.append(
        f'<div style="font-size:1.05rem;font-weight:700;margin-bottom:8px;">'
        f'{badges}{cond_text}</div>'
    )

    # --- Stat pills row ---
    pills: list[str] = []

    def _range_pill(label: str, col: str, unit: str, fmt: str = ".0f") -> None:
        if col in weather_timeline.columns:
            vals = pd.to_numeric(weather_timeline[col], errors="coerce").dropna()
            if len(vals):
                lo, hi = vals.min(), vals.max()
                if abs(hi - lo) < 0.05:
                    pills.append(f"<b>{label}:</b> {lo:{fmt}}{unit}")
                else:
                    pills.append(f"<b>{label}:</b> {lo:{fmt}}&ndash;{hi:{fmt}}{unit}")

    _range_pill("Air temp", "air_temp_c", "\u00b0C")
    _range_pill("Track temp", "track_temp_c", "\u00b0C")
    _range_pill("Wind", "wind_speed_mps", " m/s", ".1f")
    _range_pill("Grip", "grip_index", "", ".2f")

    if "humidity_pct" in weather_timeline.columns:
        hvals = pd.to_numeric(weather_timeline["humidity_pct"], errors="coerce").dropna()
        if len(hvals):
            pills.append(f"<b>Humidity:</b> {hvals.mean():.0f}%")

    if pills:
        pill_html = "".join(
            f'<span style="background:#22252e;border-radius:6px;padding:5px 12px;'
            f'font-size:0.82rem;color:#9a9a9a;">{p}</span>'
            for p in pills
        )
        parts.append(
            f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;">'
            f'{pill_html}</div>'
        )

    return "\n".join(parts)


def _plot_condition_timeline_strip(
    weather_timeline: pd.DataFrame,
) -> str:
    """
    **Section 2 -- Condition Timeline Strip**

    Returns a base64-encoded PNG of a horizontal colour-coded bar showing
    condition phases across laps, with temperature overlay text and rain
    indicators.

    Returns an empty string if the timeline is insufficient.
    """
    if weather_timeline is None or weather_timeline.empty:
        return ""
    if "condition" not in weather_timeline.columns:
        return ""

    n_laps = len(weather_timeline)
    if n_laps < 1:
        return ""

    fig, ax = plt.subplots(figsize=(10.0, 1.8), facecolor=_BG_DARK)
    ax.set_facecolor(_BG_DARK)

    conditions = weather_timeline["condition"].fillna("unknown").astype(str).str.strip().str.lower()

    # Draw colour bar segments
    for i, cond in enumerate(conditions):
        col = _condition_color(cond)
        ax.barh(0, 1, left=i, height=0.6, color=col, edgecolor="none")

    # Temperature overlay text (if available)
    has_temp = "air_temp_c" in weather_timeline.columns
    if has_temp:
        temps = pd.to_numeric(weather_timeline["air_temp_c"], errors="coerce")
        for i, t in enumerate(temps):
            if pd.notna(t):
                ax.text(
                    i + 0.5, 0, f"{t:.0f}\u00b0",
                    ha="center", va="center",
                    fontsize=7, color=_TEXT_LIGHT, fontweight="bold",
                )

    # Rain indicator triangles
    has_rain = "rain_intensity" in weather_timeline.columns
    if has_rain:
        rain = pd.to_numeric(weather_timeline["rain_intensity"], errors="coerce")
        for i, r in enumerate(rain):
            if pd.notna(r) and r > 0:
                ax.plot(i + 0.5, 0.45, marker="v", markersize=5,
                        color="#ffffff", markeredgecolor="none")

    # Axis formatting
    ax.set_xlim(0, n_laps)
    ax.set_ylim(-0.4, 0.6)
    ax.set_yticks([])
    ax.set_xticks([i + 0.5 for i in range(n_laps)])
    ax.set_xticklabels(
        [f"L{i+1}" for i in range(n_laps)],
        fontsize=7, color=_TEXT_MED,
    )
    ax.tick_params(axis="x", length=0, pad=4)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Legend
    legend_x = 0
    for label, col in _CONDITION_COLORS.items():
        ax.annotate(
            f"  {label.capitalize()}",
            xy=(legend_x, -0.35), fontsize=6.5, color=col,
            va="top", ha="left",
            annotation_clip=False,
        )
        legend_x += n_laps / 4

    fig.tight_layout(pad=0.3)
    return _fig_to_base64(fig)


def _build_phase_analysis_cards(
    weather_timeline: pd.DataFrame,
    phase_theoreticals: Optional[dict],
    lap_times: Optional[list[float]],
) -> str:
    """
    **Section 3 -- Per-Phase Analysis Cards**

    One card per contiguous condition phase showing: condition label,
    lap range, best lap time, and condition-adjusted theoretical (if
    available from *phase_theoreticals*).

    Returns empty string when no weather data is available.
    """
    if weather_timeline is None or weather_timeline.empty:
        return ""
    if "condition" not in weather_timeline.columns:
        return ""

    phase_theoreticals = phase_theoreticals or {}
    lap_times = lap_times or []
    conditions = (
        weather_timeline["condition"]
        .fillna("unknown").astype(str).str.strip().str.lower().tolist()
    )

    # Build contiguous phases
    phases: list[dict[str, Any]] = []
    start = 0
    for i in range(1, len(conditions) + 1):
        if i == len(conditions) or conditions[i] != conditions[start]:
            phases.append({
                "condition": conditions[start].capitalize(),
                "lap_start": start + 1,  # 1-indexed
                "lap_end": i,            # inclusive
            })
            start = i

    cards: list[str] = []
    for phase in phases:
        cond = phase["condition"]
        ls, le = phase["lap_start"], phase["lap_end"]
        col = _condition_color(cond)

        # Best lap in this phase range
        phase_laps = lap_times[ls - 1: le] if lap_times else []
        finite_laps = [t for t in phase_laps if isinstance(t, (int, float)) and math.isfinite(t)]
        best_lap_str = f"{min(finite_laps):.3f}s" if finite_laps else "n/a"

        # Condition-adjusted theoretical
        phase_key = cond.lower()
        theo = phase_theoreticals.get(phase_key)
        if theo is not None and isinstance(theo, (int, float)) and math.isfinite(theo):
            theo_str = f"{theo:.3f}s"
            # Delta from best to theoretical
            if finite_laps:
                delta = min(finite_laps) - theo
                delta_col = _GREEN if delta < 0.1 else (_YELLOW if delta < 0.5 else _RED)
                delta_str = (
                    f'<span style="color:{delta_col};font-weight:600;">'
                    f'{delta:+.3f}s</span>'
                )
            else:
                delta_str = ""
        else:
            theo_str = "n/a"
            delta_str = ""

        lap_range_str = f"L{ls}" if ls == le else f"L{ls}&ndash;L{le}"

        card = (
            f'<div class="card" style="border-left:4px solid {col};margin-bottom:10px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div>'
            f'<span style="font-weight:700;font-size:0.95rem;color:{col};">{cond}</span>'
            f'<span style="color:#9a9a9a;font-size:0.82rem;margin-left:10px;">{lap_range_str}</span>'
            f'</div>'
            f'<div style="text-align:right;font-size:0.85rem;">'
            f'Best: <b>{best_lap_str}</b>'
        )
        if theo_str != "n/a":
            card += f' &middot; Theoretical: <b>{theo_str}</b> {delta_str}'
        card += '</div></div></div>'
        cards.append(card)

    return "\n".join(cards)


def _build_adaptation_score_section(
    adaptation_result: Optional[dict[str, Any]],
) -> str:
    """
    **Section 4 -- Adaptation Score Breakdown**

    Renders the three sub-metric scores from the weather adaptation
    scorer: transition_speed, phase_pace, technique_adaptation.

    Expects *adaptation_result* to contain at least:
      - ``overall_score`` (float, 0--100)
      - ``grade`` (str)
      - ``sub_scores`` dict with keys ``transition_speed``,
        ``phase_pace``, ``technique_adaptation`` each having a
        ``score`` and ``max`` field.

    Returns empty string if adaptation_result is None.
    """
    if adaptation_result is None:
        return ""

    overall = adaptation_result.get("overall_score")
    grade = adaptation_result.get("grade", "")
    sub = adaptation_result.get("sub_scores", {})

    parts: list[str] = []

    # Overall score badge
    if overall is not None:
        grade_class = f"grade-{grade}" if grade else ""
        parts.append(
            f'<div style="display:flex;align-items:center;margin-bottom:12px;">'
            f'<div class="grade-badge {grade_class}" style="width:44px;height:44px;'
            f'font-size:1.3rem;margin-right:12px;">{grade}</div>'
            f'<div><span style="font-size:1.5rem;font-weight:700;">'
            f'{overall:.1f}</span>'
            f'<span style="color:#9a9a9a;font-size:0.9rem;"> / 100</span></div>'
            f'</div>'
        )

    # Sub-metric bars
    _METRIC_LABELS: dict[str, str] = {
        "transition_speed": "Transition Speed",
        "phase_pace": "Phase Pace",
        "technique_adaptation": "Technique Adaptation",
    }
    _METRIC_ICONS: dict[str, str] = {
        "transition_speed": "&#9201;",       # stopwatch
        "phase_pace": "&#127939;",           # runner
        "technique_adaptation": "&#128295;", # wrench
    }

    for key in ("transition_speed", "phase_pace", "technique_adaptation"):
        info = sub.get(key, {})
        score = info.get("score")
        max_score = info.get("max", 100)
        description = info.get("description", "")
        label = _METRIC_LABELS.get(key, key)
        icon = _METRIC_ICONS.get(key, "")

        if score is None:
            continue

        pct = min(100, max(0, (score / max_score * 100) if max_score else 0))
        bar_col = _GREEN if pct >= 75 else (_YELLOW if pct >= 50 else _RED)

        parts.append(
            f'<div style="margin-bottom:10px;">'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:0.85rem;margin-bottom:3px;">'
            f'<span>{icon} {label}</span>'
            f'<span style="font-weight:600;">{score:.1f} / {max_score:.0f}</span>'
            f'</div>'
            f'<div style="background:#22252e;border-radius:4px;height:8px;overflow:hidden;">'
            f'<div style="width:{pct:.0f}%;height:100%;background:{bar_col};'
            f'border-radius:4px;"></div>'
            f'</div>'
        )
        if description:
            parts.append(
                f'<div style="font-size:0.78rem;color:#9a9a9a;margin-top:2px;">'
                f'{description}</div>'
            )
        parts.append('</div>')

    return "\n".join(parts)


def _build_weather_coaching_section(
    weather_timeline: pd.DataFrame,
    adaptation_result: Optional[dict[str, Any]],
    lap_times: Optional[list[float]],
) -> str:
    """
    **Section 5 -- Enhanced Weather Coaching**

    Generates contextual coaching advice based on how the driver
    performed across different weather phases.

    Returns empty string when no weather data.
    """
    if weather_timeline is None or weather_timeline.empty:
        return ""
    if "condition" not in weather_timeline.columns:
        return ""

    lap_times = lap_times or []
    conditions = (
        weather_timeline["condition"]
        .fillna("unknown").astype(str).str.strip().str.lower().tolist()
    )

    tips: list[str] = []

    # --- Analyse per-phase performance ---
    # Build phases (contiguous condition blocks)
    phases: list[dict[str, Any]] = []
    start = 0
    for i in range(1, len(conditions) + 1):
        if i == len(conditions) or conditions[i] != conditions[start]:
            phase_laps = lap_times[start:i] if lap_times else []
            finite = [t for t in phase_laps if isinstance(t, (int, float)) and math.isfinite(t)]
            phases.append({
                "condition": conditions[start],
                "start": start,
                "end": i,
                "laps": finite,
            })
            start = i

    # Improvement within wet/damp phases
    for phase in phases:
        cond = phase["condition"]
        laps = phase["laps"]
        if cond in ("wet", "damp") and len(laps) >= 3:
            first_half = laps[: len(laps) // 2]
            second_half = laps[len(laps) // 2:]
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            if avg_first > 0:
                improvement_pct = (avg_first - avg_second) / avg_first * 100
                cond_cap = cond.capitalize()
                if improvement_pct > 1:
                    tips.append(
                        f'<div style="border-left:3px solid {_GREEN};padding:6px 12px;'
                        f'margin:6px 0;border-radius:4px;background:rgba(61,220,132,0.08);">'
                        f'In {cond_cap} phases (L{phase["start"]+1}&ndash;L{phase["end"]}), '
                        f'your lap times improved by <b>{improvement_pct:.1f}%</b> '
                        f'from early to late laps &mdash; good adaptation.</div>'
                    )
                elif improvement_pct < -1:
                    tips.append(
                        f'<div style="border-left:3px solid {_RED};padding:6px 12px;'
                        f'margin:6px 0;border-radius:4px;background:rgba(255,68,68,0.08);">'
                        f'In {cond_cap} phases (L{phase["start"]+1}&ndash;L{phase["end"]}), '
                        f'lap times degraded by <b>{abs(improvement_pct):.1f}%</b> &mdash; '
                        f'focus on maintaining tyre temperature and smooth inputs.</div>'
                    )
                else:
                    tips.append(
                        f'<div style="border-left:3px solid {_YELLOW};padding:6px 12px;'
                        f'margin:6px 0;border-radius:4px;background:rgba(255,214,0,0.08);">'
                        f'Consistent pace in {cond_cap} phase '
                        f'(L{phase["start"]+1}&ndash;L{phase["end"]}).</div>'
                    )

    # Transition analysis
    for i in range(1, len(phases)):
        prev_cond = phases[i - 1]["condition"]
        curr_cond = phases[i]["condition"]
        prev_laps = phases[i - 1]["laps"]
        curr_laps = phases[i]["laps"]
        if prev_laps and curr_laps:
            last_prev = prev_laps[-1]
            first_curr = curr_laps[0]
            # A big jump at a transition suggests slow adaptation
            if last_prev > 0:
                delta_pct = (first_curr - last_prev) / last_prev * 100
                p_cap = prev_cond.capitalize()
                c_cap = curr_cond.capitalize()
                if delta_pct > 5:
                    tips.append(
                        f'<div style="border-left:3px solid {_ACCENT_WARM};padding:6px 12px;'
                        f'margin:6px 0;border-radius:4px;background:rgba(255,107,53,0.08);">'
                        f'Transition {p_cap} &rarr; {c_cap}: first lap was '
                        f'<b>{delta_pct:.1f}%</b> slower. '
                        f'Try adjusting brake points and throttle application earlier '
                        f'when conditions change.</div>'
                    )

    # Adaptation result coaching (if available)
    if adaptation_result is not None:
        coaching_notes = adaptation_result.get("coaching_notes", [])
        for note in coaching_notes:
            tips.append(
                f'<div style="border-left:3px solid {_ACCENT};padding:6px 12px;'
                f'margin:6px 0;border-radius:4px;background:rgba(0,212,255,0.08);">'
                f'{note}</div>'
            )

    # Generic condition-specific tips when no specific analysis produced output
    if not tips:
        unique_conds = set(conditions)
        if "wet" in unique_conds or "damp" in unique_conds:
            tips.append(
                f'<div style="border-left:3px solid {_ACCENT};padding:6px 12px;'
                f'margin:6px 0;border-radius:4px;background:rgba(0,212,255,0.08);">'
                f'Session included changing conditions. Focus on smooth steering '
                f'inputs and progressive throttle application in low-grip phases.</div>'
            )
        else:
            tips.append(
                f'<div style="border-left:3px solid {_ACCENT};padding:6px 12px;'
                f'margin:6px 0;border-radius:4px;background:rgba(0,212,255,0.08);">'
                f'Conditions remained stable throughout the session. '
                f'Weather had minimal impact on performance.</div>'
            )

    return "\n".join(tips)


# ============================================================================

# Public API

# ============================================================================


def _build_conditions_section(
    context: Any,
    phases_df: "pd.DataFrame | None",
) -> str:
    """
    Build lightweight HTML for the Conditions section.

    Returns an empty string if no context is available.
    """
    if context is None:
        return ""

    parts: list[str] = []

    # Baseline track state + weather

    tstate = getattr(context, "baseline_track_state", None)
    if tstate is not None:
        tstate_str = tstate.value if hasattr(tstate, "value") else str(tstate)
        parts.append(f"<b>Track state:</b> {tstate_str}")

    weather = getattr(context, "weather", None)
    if weather is not None:
        wx_items: list[str] = []
        if getattr(weather, "air_temp_c", None) is not None:
            wx_items.append(f"Air {weather.air_temp_c:.0f}\u00b0C")
        if getattr(weather, "humidity_pct", None) is not None:
            wx_items.append(f"Humidity {weather.humidity_pct:.0f}%")
        if getattr(weather, "wind_speed_mps", None) is not None:
            wx_items.append(f"Wind {weather.wind_speed_mps:.1f} m/s")
        if wx_items:
            parts.append("<b>Weather:</b> " + " &middot; ".join(wx_items))

    # Phases table

    if phases_df is not None and not phases_df.empty and len(phases_df) > 1:
        rows = []
        for _, row in phases_df.iterrows():
            phase_id = row.get("phase_id", "?")
            lap_start = row.get("lap_start", "?")
            lap_end = row.get("lap_end", "?")
            state = row.get("phase_track_state", "")
            reason = row.get("label_reason", "")
            rows.append(
                f"<tr><td>{phase_id}</td><td>{lap_start}\u2013{lap_end}</td>"
                f"<td>{state}</td><td style=\"color:var(--text-med)\">{reason}</td></tr>"
            )
        table = (
            '<table class="cmp-table" style="margin-top:10px">'
            "<thead><tr><th>Phase</th><th>Laps</th>"
            "<th>State</th><th>Reason</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>"
        )
        parts.append(table)

    return "<br>".join(parts) if parts else ""


def _build_distance_quality_html(distance_quality: Optional[dict]) -> str:
    """Build HTML fragment for the distance quality debug section."""
    if not distance_quality:
        return ""

    status = distance_quality.get("status", "unknown")
    repair = distance_quality.get("repair_method") or "none"
    message = distance_quality.get("message", "")
    metrics = distance_quality.get("metrics", [])
    gate = distance_quality.get("gate_advanced", False)

    badge_map = {"ok": "#00d4aa", "repaired": "#ffd93d", "degraded": "#ff6b6b"}
    badge_color = badge_map.get(status, "#a0a4b0")

    parts = [
        '<div style="margin-top:2em; padding:1.5em; background:#1a1d26; border-radius:12px;">',
        '<h3 style="color:#e6e9ef; margin-bottom:0.5em;">Distance Quality Debug</h3>',
        f'<p><span style="display:inline-block; padding:2px 10px; border-radius:6px; '
        f'background:{badge_color}; color:#0e1117; font-weight:600;">{status.upper()}</span>',
        f' &nbsp; Repair: <code>{repair}</code></p>',
        f'<p style="color:#a0a4b0;">{message}</p>',
    ]

    if gate:
        parts.append(
            '<p style="color:#ff6b6b; font-weight:600;">'
            'Advanced analysis disabled due to distance quality issues.</p>'
        )

    if metrics:
        parts.append(
            '<table style="width:100%; border-collapse:collapse; margin-top:1em; font-size:0.9em;">'
            '<thead><tr style="border-bottom:1px solid #333;">'
            '<th style="text-align:left; padding:4px 8px; color:#a0a4b0;">Lap</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Mono Ratio</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Jumps</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Compression</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Length (m)</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Z-score</th>'
            '</tr></thead><tbody>'
        )
        for m in metrics:
            mono = m.get("monotonic_ratio", 0)
            row_color = "#ff6b6b" if mono < 0.95 else ("#ffd93d" if mono < 0.99 else "#e6e9ef")
            parts.append(
                f'<tr style="border-bottom:1px solid #222;">'
                f'<td style="padding:4px 8px; color:{row_color};">Lap {m.get("lap_number", "?")}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{mono:.4f}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("jump_count", 0)}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("compression_ratio", 0):.3f}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("lap_length", 0):.1f}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("lap_length_zscore", 0):.2f}</td>'
                f'</tr>'
            )
        parts.append('</tbody></table>')

    parts.append('</div>')
    return "\n".join(parts)


def _build_traffic_html(traffic: Optional[dict], lap_inclusion: Optional[dict]) -> str:
    """Build HTML for traffic detection and lap inclusion summary."""
    if traffic is None and lap_inclusion is None:
        return ""

    parts = [
        '<div style="margin-top:2em; padding:1.5em; background:#1a1d26; border-radius:12px;">',
        '<h3 style="color:#e6e9ef; margin-bottom:0.5em;">Traffic Detection &amp; Lap Inclusion</h3>',
    ]

    if lap_inclusion:
        n_learn = len(lap_inclusion.get("learning_laps", []))
        n_display = len(lap_inclusion.get("display_laps", []))
        n_excluded = len(lap_inclusion.get("exclusions", []))
        parts.append(
            f'<p style="color:#a0a4b0;"><strong style="color:#e6e9ef;">{n_learn}</strong> laps used for learning, '
            f'<strong style="color:#e6e9ef;">{n_display}</strong> displayed, '
            f'<strong style="color:#e6e9ef;">{n_excluded}</strong> excluded.</p>'
        )

        exclusions = lap_inclusion.get("exclusions", [])
        if exclusions:
            parts.append(
                '<table style="width:100%; border-collapse:collapse; margin-top:1em; font-size:0.9em;">'
                '<thead><tr style="border-bottom:1px solid #333;">'
                '<th style="text-align:left; padding:4px 8px; color:#a0a4b0;">Lap</th>'
                '<th style="text-align:left; padding:4px 8px; color:#a0a4b0;">Reason</th>'
                '<th style="text-align:left; padding:4px 8px; color:#a0a4b0;">Label</th>'
                '</tr></thead><tbody>'
            )
            for exc in exclusions:
                reasons = ", ".join(exc.get("reasons", []))
                parts.append(
                    f'<tr style="border-bottom:1px solid #222;">'
                    f'<td style="padding:4px 8px; color:#e6e9ef;">Lap {exc.get("lap_number", "?")}</td>'
                    f'<td style="padding:4px 8px; color:#a0a4b0;">{reasons}</td>'
                    f'<td style="padding:4px 8px;">'
                    f'<span style="display:inline-block; padding:2px 10px; border-radius:6px; '
                    f'background:#ffd93d; color:#0e1117; font-weight:600;">{reasons}</span></td></tr>'
                )
            parts.append('</tbody></table>')

    if traffic:
        n_affected = traffic.get("n_laps_affected", 0)
        if n_affected > 0:
            parts.append(
                f'<p style="color:#a0a4b0; margin-top:0.8em;">Traffic detected on '
                f'<strong style="color:#ff6b6b;">{n_affected}</strong> lap(s).</p>'
            )

    parts.append('</div>')
    return "\n".join(parts)


def _build_confidence_html(theo_metrics: Optional[dict]) -> str:
    """Build HTML for confidence assessment panel."""
    if theo_metrics is None:
        return ""
    confidence = theo_metrics.get("confidence")
    if confidence is None:
        return ""

    score = confidence.get("confidence_score", 0)
    level = confidence.get("confidence_level", "unknown")
    reasons = confidence.get("confidence_reasons", [])
    action = confidence.get("recommended_next_action", "")

    # Color based on level
    color_map = {"high": "#22c55e", "medium": "#f59e0b", "low": "#ef4444"}
    color = color_map.get(level, "#9ca3af")

    parts = [
        '<div class="section confidence-panel" '
        f'style="border-left: 4px solid {color}; padding: 12px; '
        'margin: 16px 0; background: rgba(0,0,0,0.02);">',
        f'<h3>Confidence: {score}/100 '
        f'<span style="color: {color}; text-transform: capitalize;">'
        f'({level})</span></h3>',
    ]

    if reasons:
        parts.append('<p><strong>Top blockers:</strong></p><ol>')
        for reason in reasons[:3]:
            parts.append(f'<li>{reason}</li>')
        parts.append('</ol>')

    if action:
        parts.append(
            f'<p style="margin-top: 8px;"><strong>&rarr;</strong> {action}</p>'
        )

    parts.append('</div>')
    return "\n".join(parts)


def _build_grip_map_html(grip_data: Optional[dict]) -> str:
    """Build HTML for grip map visualization."""
    if grip_data is None:
        return ""

    is_fallback = grip_data.get("is_global_fallback", True)
    global_mu = grip_data.get("global_mu", 1.0)
    source = grip_data.get("source", "unknown")
    warning = grip_data.get("warning")
    n_laps = grip_data.get("n_laps_used", 0)

    parts = [
        '<div class="section grip-map-panel" style="margin: 16px 0;">',
        f'<h3>Grip Map <span style="color: #9ca3af; font-size: 0.8em;">'
        f'({source}, {n_laps} laps)</span></h3>',
    ]

    if warning:
        parts.append(
            f'<p style="color: #f59e0b; margin: 4px 0;">'
            f'<strong>Warning:</strong> {warning}</p>'
        )

    if is_fallback:
        parts.append(
            f'<p>Global grip coefficient: <strong>{global_mu:.2f} G</strong></p>'
        )
    else:
        distances = grip_data.get("distance_bins", [])
        mu_mean = grip_data.get("mu_mean", [])
        mu_p95 = grip_data.get("mu_p95", [])
        if distances and mu_mean:
            n = len(distances)
            width = 600
            height = 120
            d_min, d_max = distances[0], distances[-1]
            mu_all = mu_mean + mu_p95
            mu_min = max(0, min(mu_all) - 0.1)
            mu_max = max(mu_all) + 0.1

            def _sx(d):
                return (d - d_min) / max(1, d_max - d_min) * width

            def _sy(mu):
                return height - (mu - mu_min) / max(0.01, mu_max - mu_min) * height

            mean_pts = " ".join(
                f"{_sx(distances[i]):.1f},{_sy(mu_mean[i]):.1f}"
                for i in range(n)
            )
            p95_pts = " ".join(
                f"{_sx(distances[i]):.1f},{_sy(mu_p95[i]):.1f}"
                for i in range(n)
            )

            parts.append(
                f'<svg viewBox="0 0 {width} {height}" '
                f'style="width: 100%; max-width: 600px; height: {height}px; '
                f'background: rgba(0,0,0,0.03); border-radius: 4px;">'
                f'<polyline points="{p95_pts}" fill="none" '
                f'stroke="#22c55e" stroke-width="1" stroke-dasharray="4,2" '
                f'opacity="0.6"/>'
                f'<polyline points="{mean_pts}" fill="none" '
                f'stroke="#3b82f6" stroke-width="2"/>'
                f'<text x="5" y="12" font-size="10" fill="#9ca3af">'
                f'mu (G) — blue: mean, green dashed: p95</text>'
                f'</svg>'
            )

        parts.append(
            f'<p style="font-size: 0.85em; color: #9ca3af;">'
            f'Global mu: {global_mu:.2f} G | '
            f'{len(distances)} bins</p>'
        )

    parts.append('</div>')
    return "\n".join(parts)


def _build_explainability_html(optimal_v2: Optional[dict]) -> str:
    """Build HTML panel showing solver limiting factor breakdown."""
    if optimal_v2 is None:
        return ""

    lf_summary = optimal_v2.get("limiting_factor_summary", {})
    if not lf_summary:
        return ""

    total = sum(lf_summary.values())
    if total == 0:
        return ""

    colors = {
        "cornering": "#ef4444",   # red
        "braking": "#f59e0b",     # amber
        "traction": "#22c55e",    # green
        "cap": "#3b82f6",         # blue
    }

    # Stacked bar
    width = 500
    height = 30
    parts = [
        '<div class="section explainability-panel" style="margin: 16px 0;">',
        '<h3>Solver Limiting Factors</h3>',
        f'<svg viewBox="0 0 {width} {height}" '
        f'style="width: 100%; max-width: {width}px; height: {height}px;">',
    ]

    x = 0
    for factor in ("cornering", "braking", "traction", "cap"):
        count = lf_summary.get(factor, 0)
        w = (count / total) * width
        if w > 0:
            color = colors.get(factor, "#9ca3af")
            pct = round(100 * count / total)
            parts.append(
                f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" '
                f'fill="{color}" />'
            )
            if w > 30:
                parts.append(
                    f'<text x="{x + w / 2:.1f}" y="{height / 2 + 4}" '
                    f'text-anchor="middle" fill="white" font-size="11">'
                    f'{factor} {pct}%</text>'
                )
            x += w

    parts.append('</svg>')

    # Legend
    parts.append('<div style="margin-top: 8px; font-size: 0.85em;">')
    for factor in ("cornering", "braking", "traction", "cap"):
        count = lf_summary.get(factor, 0)
        pct = round(100 * count / total)
        if pct > 0:
            color = colors.get(factor, "#9ca3af")
            parts.append(
                f'<span style="display: inline-block; margin-right: 12px;">'
                f'<span style="display: inline-block; width: 10px; height: 10px; '
                f'background: {color}; margin-right: 4px;"></span>'
                f'{factor}: {pct}%</span>'
            )
    parts.append('</div>')

    # Corner saturation table
    sat_list = optimal_v2.get("corner_saturation", [])
    if sat_list:
        parts.append('<h4 style="margin-top: 12px;">Per-Corner Saturation</h4>')
        parts.append(
            '<table class="data-table" style="font-size: 0.85em;">'
            '<tr><th>Corner</th><th>Cornering</th><th>Traction</th>'
            '<th>Braking</th><th>Dominant</th><th>Sat. &gt;98%</th></tr>'
        )
        for sat in sat_list:
            parts.append(
                f'<tr><td>{sat.get("corner_id", "?")}</td>'
                f'<td>{sat.get("cornering_pct", 0) * 100:.0f}%</td>'
                f'<td>{sat.get("traction_pct", 0) * 100:.0f}%</td>'
                f'<td>{sat.get("braking_pct", 0) * 100:.0f}%</td>'
                f'<td><strong>{sat.get("dominant_factor", "?")}</strong></td>'
                f'<td>{sat.get("saturation_98pct", 0) * 100:.0f}%</td></tr>'
            )
        parts.append('</table>')

    parts.append('</div>')
    return "\n".join(parts)


def _build_uncertainty_html(optimal_v2: Optional[dict]) -> str:
    """Build HTML panel showing uncertainty bands."""
    if optimal_v2 is None:
        return ""

    v_low = optimal_v2.get("v_opt_low_mps", [])
    v_high = optimal_v2.get("v_opt_high_mps", [])
    v_opt = optimal_v2.get("v_opt_mps", [])
    distances = optimal_v2.get("distance_m", [])

    if not v_low or not v_high or not distances:
        return ""

    lap_time = optimal_v2.get("lap_time_s", 0)
    lap_low = optimal_v2.get("lap_time_low_s", 0)
    lap_high = optimal_v2.get("lap_time_high_s", 0)

    parts = [
        '<div class="section uncertainty-panel" style="margin: 16px 0;">',
        '<h3>Uncertainty Bands</h3>',
        f'<p>Lap time: <strong>{lap_time:.2f}s</strong> '
        f'[{lap_low:.2f} \u2013 {lap_high:.2f}]</p>',
    ]

    # SVG sparkline with shaded band
    n = len(distances)
    width = 600
    height = 100
    d_min, d_max = distances[0], distances[-1]
    all_v = v_low + v_opt + v_high
    v_min = max(0, min(all_v) - 1)
    v_max_val = max(all_v) + 1

    def _sx(d):
        return (d - d_min) / max(1, d_max - d_min) * width

    def _sy(v):
        return height - (v - v_min) / max(0.01, v_max_val - v_min) * height

    # Band polygon (low -> high, reversed)
    band_pts_fwd = " ".join(
        f"{_sx(distances[i]):.1f},{_sy(v_high[i]):.1f}" for i in range(n)
    )
    band_pts_rev = " ".join(
        f"{_sx(distances[n - 1 - i]):.1f},{_sy(v_low[n - 1 - i]):.1f}" for i in range(n)
    )
    band_polygon = f"{band_pts_fwd} {band_pts_rev}"

    # Nominal line
    nom_pts = " ".join(
        f"{_sx(distances[i]):.1f},{_sy(v_opt[i]):.1f}" for i in range(n)
    )

    parts.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'style="width: 100%; max-width: {width}px; height: {height}px; '
        f'background: rgba(0,0,0,0.02);">'
        f'<polygon points="{band_polygon}" fill="rgba(59,130,246,0.15)" />'
        f'<polyline points="{nom_pts}" fill="none" stroke="#3b82f6" stroke-width="1.5" />'
        f'</svg>'
    )

    parts.append('</div>')
    return "\n".join(parts)


def generate_report(
    *,
    score_result:         Optional[dict[str, Any]]        = None,
    theoretical_lap:      Optional[pd.DataFrame]          = None,
    best_lap:             Optional[pd.DataFrame]          = None,
    delta_segments:       Optional[list[dict[str, Any]]]  = None,
    lap_times:            Optional[list[float]]           = None,
    segment_losses:       Optional[list[list[float]]]     = None,
    driver_profiles:      Optional[list[dict[str, Any]]]  = None,
    session_meta:         Optional[dict[str, Any]]         = None,
    context:              Any                              = None,
    phases_df:            Optional[pd.DataFrame]           = None,
    output_path:          str | Path                       = "index.html",
    # --- Physics-based analysis (all optional, backward-compatible) -
    median_lap:           Optional[pd.DataFrame]          = None,
    theoretical_result:   Any                              = None,
    resampled_laps:       Optional[dict]                   = None,
    friction_circle:      Any                              = None,
    corner_performances:  Optional[list]                   = None,
    grip_evolution:       Any                              = None,
    data_quality:         Any                              = None,
    coaching_guide:       Optional[dict[str, Any]]         = None,
    # --- Trimmed laps (excluded from analysis) -
    trimmed_laps:         Optional[list[dict[str, Any]]]  = None,
    theoretical_lap_time: Optional[float]                  = None,
    # --- Weather / meteo integration (all optional, backward-compatible) -
    weather_timeline:     Optional[pd.DataFrame]           = None,
    adaptation_result:    Optional[dict[str, Any]]         = None,
    phase_theoreticals:   Optional[dict]                   = None,
    # --- Distance quality debug section (all optional) -
    distance_quality:     Optional[dict[str, Any]]         = None,
    # --- Traffic detection & lap inclusion (all optional) -
    traffic:              Optional[dict[str, Any]]         = None,
    lap_inclusion:        Optional[dict[str, Any]]         = None,
    # --- Confidence assessment (all optional) -
    theoretical_metrics:  Optional[dict[str, Any]]         = None,
    # --- Grip map (all optional) -
    grip_map:             Optional[dict[str, Any]]         = None,
    # --- Optimal v2 solver output (explainability + uncertainty) -
    optimal_v2:           Optional[dict[str, Any]]         = None,
) -> Path:
    """
    Generate a self-contained HTML report and write it to *output_path*.

    All parameters are keyword-only and optional.  Missing data produces
    placeholder sections rather than exceptions.

    Parameters -- score_result:
        Output of ``scoring.score_session()``.
    theoretical_lap:
        DataFrame with ``distance_m`` + ``v_env_mps`` (from
        ``theoretical_engine.build_theoretical_lap()``).
    best_lap:
        Distance-resampled DataFrame with ``Distance (m)`` + ``Speed (m/s)``.
    delta_segments:
        Output of ``deltas.classify_time_loss_cause()``  — used for cause
        annotations on the heatmap.
    lap_times:
        List of lap times (seconds) for heatmap Y-axis labels.
    segment_losses:
        ``n_laps  — n_segments`` nested list of time-loss values (ms).
    driver_profiles:
        List of ``driver_profile.generate_driver_profile()`` outputs.
    session_meta:
        Dict with optional keys: ``session_id``, ``track_id``,
        ``track_state``, ``driver_name``, ``date``.
    output_path:
        Path for the generated HTML file.  Default: ``index.html``.

    Returns -- -
    Path
        Absolute path of the written file.

    Raises -- ReportError
        If the file cannot be written.
    """
    output_path = Path(output_path)
    session_meta = session_meta or {}

    title = _build_title(session_meta)
    sub_scores = score_result.get("sub_scores") if score_result else None

    # --- Build trimmed laps notice (shown once)

    trimmed_laps_notice = ""
    _trimmed_lap_numbers: set[Any] = set()
    if trimmed_laps:
        parts: list[str] = []
        for tl in trimmed_laps:
            lap_num = tl.get("lap") or tl.get("lap_number") or tl.get("lap_num")
            reason  = tl.get("reason", "flagged by trimming")
            if lap_num is not None:
                _trimmed_lap_numbers.add(lap_num)
                parts.append(f"Lap {lap_num} ({reason})")
            else:
                parts.append(str(reason))
        if parts:
            trimmed_laps_notice = (
                "The following laps were removed from all analysis and are "
                "not included in any section of this report: "
                + ", ".join(parts) + "."
            )

    # --- Filter trimmed laps from resampled_laps

    _clean_resampled = resampled_laps
    if resampled_laps and _trimmed_lap_numbers:
        _clean_resampled = {
            k: v for k, v in resampled_laps.items()
            if k not in _trimmed_lap_numbers
        }

    # --- Filter trimmed laps from lap_times & segment_losses

    _clean_lap_times = lap_times
    _clean_segment_losses = segment_losses
    if _trimmed_lap_numbers and lap_times:
        # Assume lap_times is indexed 0..n-1 corresponding to lap keys

        sorted_keys = sorted(resampled_laps.keys()) if resampled_laps else []
        keep_indices = [
            i for i, k in enumerate(sorted_keys) if k not in _trimmed_lap_numbers
        ] if sorted_keys else list(range(len(lap_times)))
        _clean_lap_times = [lap_times[i] for i in keep_indices if i < len(lap_times)]
        if segment_losses:
            _clean_segment_losses = [
                segment_losses[i] for i in keep_indices if i < len(segment_losses)
            ]

    # --- Data-driven theoretical (point-mass simulation) -- # When no external theoretical_lap is supplied, compute one from the

    # session's own resampled lap data so that speed-trace plots, physics

    # overlay, and the sim-method badge all reflect the data-derived model.

    _data_theo_result: Optional[dict] = None
    _effective_theoretical_lap = theoretical_lap      # may be replaced below
    _effective_theoretical_result = theoretical_result  # may be replaced below
    _using_data_theoretical = False

    if _clean_resampled:
        _data_theo_result = _compute_data_theoretical_lap_time(
            _clean_resampled, _clean_lap_times,
        )

    if _data_theo_result is not None:
        # Build a synthetic theoretical DataFrame for speed-trace plots

        _synth_theo_df = pd.DataFrame({
            "Distance (m)": _data_theo_result["distance"],
            "Speed (m/s)":  _data_theo_result["speed_profile"],
        })

        # Use it when the caller hasn't provided an external theoretical

        if theoretical_lap is None:
            _effective_theoretical_lap = _synth_theo_df
            _using_data_theoretical = True

        # Also fill the physics overlay when no external theoretical_result

        # (but only mark as "data theoretical" if theoretical_lap was also missing)

        if theoretical_result is None:
            _effective_theoretical_result = _data_theo_result  # dict, not object

        # Update the theoretical_lap_time if not explicitly given

        if theoretical_lap_time is None:
            theoretical_lap_time = _data_theo_result["theoretical_time"]

    # --- Generate plots -- -
    # Wrapped in try/finally so any exception during plot generation
    # won't leave open matplotlib figures (memory leak in long-running
    # server processes).

    try:
        speed_trace_img = _plot_speed_trace(_effective_theoretical_lap, best_lap)
        heatmap_img     = _plot_delta_heatmap(
            _clean_segment_losses,
            lap_labels=([f"L{i+1} ({t:.1f}s)" for i, t in enumerate(_clean_lap_times)]
                        if _clean_lap_times else None),
            cause_data=delta_segments,
        )
        sub_scores_img = _plot_sub_scores(sub_scores)

        # --- Physics-based plots (new, all optional) -- # Physics speed overlay

        cornering_mask = None
        sim_distance = None
        if theoretical_result is not None:
            # External theoretical_result (object with attributes)

            cornering_mask = getattr(theoretical_result, "cornering_limited", None)
            sim_distance = getattr(theoretical_result, "distance_m", None)
        elif _data_theo_result is not None:
            # Data-derived theoretical (dict with keys)

            sim_distance = _data_theo_result.get("distance")

        physics_speed_img = _plot_physics_speed_overlay(
            _effective_theoretical_lap, best_lap,
            median_lap=median_lap,
            cornering_limited=cornering_mask,
            sim_distance=sim_distance,
        )

        # G-G diagram (data-calibrated optimal boundary)

        gg_diagram_img = _plot_gg_diagram(
            _clean_resampled,
            friction_circle,
            lap_times=_clean_lap_times,
            theoretical_lap_time=theoretical_lap_time,
        )

        # G-G per-lap utilisation table

        gg_per_lap_table = _build_gg_per_lap_table(
            _clean_resampled,
            lap_times=_clean_lap_times,
            theoretical_lap_time=theoretical_lap_time,
        )

        # Corner performance table

        corner_table_html = _build_corner_table_html(corner_performances)

        # GPS track map (uses resampled_laps GPS columns)

        _best_key = None
        if _clean_resampled:
            # Identify the best lap key for highlighting
            if best_lap is not None and _clean_lap_times:
                sorted_k = sorted(_clean_resampled.keys())
                for k in sorted_k:
                    if _clean_resampled[k] is best_lap:
                        _best_key = k
                        break
                if _best_key is None and _clean_lap_times:
                    # Fallback: use fastest time
                    try:
                        pairs = list(zip(sorted_k, _clean_lap_times))
                        finite_pairs = [(k, t) for k, t in pairs if math.isfinite(t)]
                        if finite_pairs:
                            _best_key = min(finite_pairs, key=lambda x: x[1])[0]
                    except Exception:
                        pass
        gps_trace_img = _plot_gps_trace_map(_clean_resampled, _best_key)

        # Grip evolution chart

        grip_evolution_img = _plot_grip_evolution(grip_evolution, _clean_lap_times)
    except Exception:
        # Safety net: close all open figures on any plot failure,
        # then re-raise so the caller sees the real error.
        plt.close("all")
        raise

    # Quality and simulation badges

    quality_badge = _build_quality_badge_html(score_result, data_quality, session_meta)
    distance_quality_html = _build_distance_quality_html(distance_quality)
    traffic_html = _build_traffic_html(traffic, lap_inclusion)
    confidence_html = _build_confidence_html(theoretical_metrics)
    grip_map_html = _build_grip_map_html(grip_map)
    explainability_html = _build_explainability_html(optimal_v2)
    uncertainty_html = _build_uncertainty_html(optimal_v2)
    sim_method_badge = _build_sim_method_badge_html(
        score_result, using_data_theoretical=_using_data_theoretical,
    )

    # --- Build driver comparison rows

    driver_rows = _build_driver_rows(driver_profiles or [])

    # --- Build conditions section -- -

    conditions_html = _build_conditions_section(context, phases_df)

    # --- Weather / meteo sections (all guarded by weather_timeline) -- -

    weather_banner_html = ""
    condition_timeline_img = ""
    phase_cards_html = ""
    adaptation_score_html = ""
    weather_coaching_html = ""

    if weather_timeline is not None:
        weather_banner_html = _build_weather_conditions_banner(weather_timeline)
        condition_timeline_img = _plot_condition_timeline_strip(weather_timeline)
        phase_cards_html = _build_phase_analysis_cards(
            weather_timeline, phase_theoreticals, _clean_lap_times,
        )
        adaptation_score_html = _build_adaptation_score_section(adaptation_result)
        weather_coaching_html = _build_weather_coaching_section(
            weather_timeline, adaptation_result, _clean_lap_times,
        )

    # --- Render Jinja2 template -- -

    env = Environment(loader=BaseLoader(), autoescape=False)
    template = env.from_string(_HTML_TEMPLATE)

    html = template.render(
        title=title,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        session_meta=session_meta,
        score_result=score_result,
        sub_scores=sub_scores,
        sub_scores_img=sub_scores_img,
        speed_trace_img=speed_trace_img,
        gps_trace_img=gps_trace_img,
        heatmap_img=heatmap_img,
        driver_rows=driver_rows,
        conditions_html=conditions_html,
        trimmed_laps_notice=trimmed_laps_notice,
        # Physics-based sections

        physics_speed_img=physics_speed_img,
        gg_diagram_img=gg_diagram_img,
        gg_per_lap_table=gg_per_lap_table,
        coaching_guide=coaching_guide,
        corner_table_html=corner_table_html,
        grip_evolution_img=grip_evolution_img,
        quality_badge=quality_badge,
        sim_method_badge=sim_method_badge,
        has_cornering_zones=(cornering_mask is not None),
        using_data_theoretical=_using_data_theoretical,
        data_theoretical_time=(
            f"{theoretical_lap_time:.3f}s" if theoretical_lap_time and math.isfinite(theoretical_lap_time) else None
        ),
        # Weather / meteo sections
        weather_banner_html=weather_banner_html,
        condition_timeline_img=condition_timeline_img,
        phase_cards_html=phase_cards_html,
        adaptation_score_html=adaptation_score_html,
        weather_coaching_html=weather_coaching_html,
        distance_quality_html=distance_quality_html,
        traffic_html=traffic_html,
        confidence_html=confidence_html,
        grip_map_html=grip_map_html,
        explainability_html=explainability_html,
        uncertainty_html=uncertainty_html,
        # Colour variables for CSS

        bg_dark=_BG_DARK,
        bg_card=_BG_CARD,
        text_light=_TEXT_LIGHT,
        text_med=_TEXT_MED,
        accent=_ACCENT,
        green=_GREEN,
        red=_RED,
        yellow=_YELLOW,
    )

    # --- Write

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Could not write report: {exc}") from exc

    file_kb = output_path.stat().st_size / 1024
    logger.info("Report written: %s (%.0f KB)", output_path, file_kb)
    return output_path.resolve()


def _build_title(session_meta: dict[str, Any]) -> str:
    """Construct a meaningful report title from metadata."""
    parts = []
    if session_meta.get("track_id"):
        parts.append(str(session_meta["track_id"]))
    if session_meta.get("driver_name"):
        parts.append(str(session_meta["driver_name"]))
    if parts:
        return "Session Report — " + " — ".join(parts)
    return "Session Report"


# ============================================================================

# Inline tests

# ============================================================================



# ============================================================================

# Driver Head-to-Head Comparison Report

# ============================================================================


_COMPARISON_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>
  :root { --bg: #0e1117; --card: #1a1d26; --accent: #00d4aa;
          --text: #e6e9ef; --text-med: #a0a4b0; --red: #ff6b6b;
          --green: #00d4aa; --yellow: #ffd93d; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 1.6rem; color: var(--accent); margin-bottom: 8px; }
  h2 { font-size: 1.2rem; color: var(--text); margin: 24px 0 12px; }
  .subtitle { color: var(--text-med); font-size: 0.9rem; margin-bottom: 24px; }
  .card { background: var(--card); border-radius: 10px; padding: 20px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; }
  th { text-align: left; color: var(--text-med); font-size: 0.8rem;
       text-transform: uppercase; padding: 8px 12px; border-bottom: 1px solid #333; }
  td { padding: 8px 12px; border-bottom: 1px solid #222; font-size: 0.9rem; }
  .best { color: var(--green); font-weight: 600; }
  .worse { color: var(--red); }
  .strength { background: rgba(0,212,170,0.12); border-left: 3px solid var(--green);
              padding: 8px 12px; border-radius: 4px; margin: 4px 0; font-size: 0.9rem; }
  .weakness { background: rgba(255,107,107,0.12); border-left: 3px solid var(--red);
              padding: 8px 12px; border-radius: 4px; margin: 4px 0; font-size: 0.9rem; }
  .plot-img { max-width: 100%; border-radius: 8px; margin: 12px 0; }
  .radar-container { text-align: center; margin: 16px 0; }
  .radar-container img { max-width: 500px; border-radius: 8px; }
  .footer { text-align: center; color: var(--text-med); font-size: 0.75rem;
            margin-top: 32px; padding-top: 16px; border-top: 1px solid #333; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<p class="subtitle">Generated {{ generated_at }}</p>

<div class="card">
  <h2>Head-to-Head Summary</h2>
  <table>
    <tr><th>Metric</th>{% for d in drivers %}<th>{{ d.name }}</th>{% endfor %}</tr>
    <tr><td>Best Lap</td>{% for d in drivers %}<td class="{{ d.best_lap_class }}">{{ d.best_lap_s }}</td>{% endfor %}</tr>
    <tr><td>Average Lap</td>{% for d in drivers %}<td class="{{ d.avg_lap_class }}">{{ d.avg_lap_s }}</td>{% endfor %}</tr>
    <tr><td>Consistency (CV%)</td>{% for d in drivers %}<td class="{{ d.cv_class }}">{{ d.cv_pct }}</td>{% endfor %}</tr>
    <tr><td>Total Score</td>{% for d in drivers %}<td class="{{ d.score_class }}">{{ d.score_str }}</td>{% endfor %}</tr>
    <tr><td>Grade</td>{% for d in drivers %}<td>{{ d.grade }}</td>{% endfor %}</tr>
    <tr><td>Laps</td>{% for d in drivers %}<td>{{ d.n_laps }}</td>{% endfor %}</tr>
  </table>
</div>

{% if radar_img %}
<div class="card">
  <h2>Sub-Score Comparison</h2>
  <div class="radar-container">
    <img class="plot-img" src="{{ radar_img }}" alt="Radar comparison">
  </div>
</div>
{% endif %}

{% if corner_comparison %}
<div class="card">
  <h2>Corner-by-Corner</h2>
  <table>
    <tr><th>Corner</th>{% for d in drivers %}<th>{{ d.name }} Loss</th>{% endfor %}<th>Advantage</th></tr>
    {% for c in corner_comparison %}
    <tr><td>T{{ c.corner_id }}</td>
    {% for loss in c.losses %}<td class="{{ loss.cls }}">{{ loss.val }}</td>{% endfor %}
    <td>{{ c.advantage }}</td></tr>
    {% endfor %}
  </table>
</div>
{% endif %}

{% if speed_overlay_img %}
<div class="card">
  <h2>Speed Trace Overlay</h2>
  <img class="plot-img" src="{{ speed_overlay_img }}" alt="Speed overlay">
</div>
{% endif %}

{% if strengths_weaknesses %}
<div class="card">
  <h2>Relative Strengths</h2>
  {% for sw in strengths_weaknesses %}
  <div class="{{ sw.cls }}">{{ sw.text }}</div>
  {% endfor %}
</div>
{% endif %}

<div class="card">
  <h2>Gap Breakdown</h2>
  <p style="color: var(--text-med); font-size: 0.9rem;">
    Overall best-lap gap: <b>{{ gap_s }}</b> &mdash; {{ gap_summary }}
  </p>
</div>

<div class="footer">Telemetry Tool Driver Comparison {{ generated_at }}</div>
</body>
</html>"""


def _plot_radar_comparison(
    driver_results: list[dict[str, Any]],
) -> str:
    """Radar chart comparing sub-scores across drivers."""
    if len(driver_results) < 2:
        return ""

    categories = ["Pace", "Consistency", "Execution", "Robustness"]
    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(_BG_DARK)
    ax.set_facecolor(_BG_DARK)

    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    angles += angles[:1]

    colors = ["#00d4aa", "#ff6b6b", "#ffd93d", "#6bb5ff"]

    for i, dr in enumerate(driver_results):
        score = dr.get("score_result", {})
        subs = score.get("sub_scores", {})
        values = []
        for cat in ["pace", "consistency", "execution", "robustness"]:
            s = subs.get(cat, {})
            mx = s.get("max", 1.0)
            val = s.get("score", 0.0)
            values.append(val / mx * 100.0 if mx > 0 else 0.0)
        values += values[:1]

        color = colors[i % len(colors)]
        name = dr.get("session_meta", {}).get("driver_name", f"Driver {i+1}")
        ax.plot(angles, values, "o-", linewidth=2, color=color, label=name)
        ax.fill(angles, values, alpha=0.15, color=color)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, color=_TEXT_LIGHT, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], color=_TEXT_MED, fontsize=7)
    ax.tick_params(colors=_TEXT_MED)
    ax.grid(color="#444", alpha=0.3)
    ax.spines["polar"].set_color("#444")
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1),
              fontsize=8, facecolor=_BG_CARD, edgecolor="#444",
              labelcolor=_TEXT_LIGHT)

    return _fig_to_base64(fig)


def _plot_speed_overlay(
    driver_results: list[dict[str, Any]],
) -> str:
    """Overlay best-lap speed traces for all drivers."""
    if len(driver_results) < 2:
        return ""

    fig, ax = plt.subplots(figsize=(12, 4))
    _apply_dark_style(fig, ax)

    colors = ["#00d4aa", "#ff6b6b", "#ffd93d", "#6bb5ff"]
    has_data = False

    for i, dr in enumerate(driver_results):
        best_lap = dr.get("best_lap_df")
        if best_lap is None:
            continue

        dist_col = next((c for c in ("Distance (m)", "distance_m") if c in best_lap.columns), None)
        spd_col = next((c for c in ("Speed (m/s)", "speed_mps") if c in best_lap.columns), None)
        if dist_col is None or spd_col is None:
            continue

        dist = pd.to_numeric(best_lap[dist_col], errors="coerce").values
        speed = pd.to_numeric(best_lap[spd_col], errors="coerce").values
        mask = np.isfinite(dist) & np.isfinite(speed)
        if mask.sum() < 10:
            continue

        name = dr.get("session_meta", {}).get("driver_name", f"Driver {i+1}")
        color = colors[i % len(colors)]
        ax.plot(dist[mask], speed[mask] * 3.6, linewidth=1.2,
                color=color, alpha=0.85, label=name)
        has_data = True

    if not has_data:
        plt.close(fig)
        return ""

    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Speed (km/h)")
    ax.set_title("Best Lap Speed Comparison", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, facecolor=_BG_CARD, edgecolor="#444", labelcolor=_TEXT_LIGHT)
    ax.grid(True, alpha=0.12, color="#555")
    return _fig_to_base64(fig)


def generate_comparison_report(
    driver_results: list[dict[str, Any]],
    *,
    output_path: "str | Path" = "comparison.html",
    session_meta: Optional[dict[str, Any]] = None,
) -> "Path":
    """Generate head-to-head comparison HTML report for 2+ drivers."""
    output_path = Path(output_path)
    session_meta = session_meta or {}

    if len(driver_results) < 2:
        raise ReportError("Need at least 2 drivers for comparison report")

    drivers: list[dict[str, Any]] = []
    all_best: list[float] = []
    all_avg: list[float] = []
    all_cv: list[float] = []
    all_scores: list[float] = []

    for i, dr in enumerate(driver_results):
        score = dr.get("score_result") or {}
        meta = dr.get("session_meta") or {}
        name = meta.get("driver_name", f"Driver {i+1}")

        feat = dr.get("feature_dict") or dr.get("metrics_dict") or {}
        best_s = feat.get("best_s", float("nan"))
        avg_s = feat.get("mean_s", float("nan"))
        cv = feat.get("cv_pct", float("nan"))
        n_laps = int(feat.get("n_laps", 0))

        lt = dr.get("lap_times")
        if lt and (math.isnan(best_s) or n_laps == 0):
            arr = np.array([t for t in lt if isinstance(t, (int, float)) and math.isfinite(t)])
            if len(arr) > 0:
                best_s, avg_s = float(arr.min()), float(arr.mean())
                cv = float(arr.std() / arr.mean() * 100) if arr.mean() > 0 else 0.0
                n_laps = len(arr)

        total_score = score.get("total_score", 0.0)
        grade = score.get("grade", "-")

        drivers.append({
            "name": name,
            "best_lap_s": f"{best_s:.3f}" if math.isfinite(best_s) else "-",
            "avg_lap_s": f"{avg_s:.3f}" if math.isfinite(avg_s) else "-",
            "cv_pct": f"{cv:.2f}%" if math.isfinite(cv) else "-",
            "score_str": f"{total_score:.1f}", "grade": grade, "n_laps": n_laps,
        })
        all_best.append(best_s); all_avg.append(avg_s)
        all_cv.append(cv); all_scores.append(total_score)

    def _cls(vals, idx, lower_better=True):
        fin = [(j, v) for j, v in enumerate(vals) if math.isfinite(v)]
        if len(fin) < 2: return ""
        best_j = min(fin, key=lambda x: x[1])[0] if lower_better else max(fin, key=lambda x: x[1])[0]
        worst_j = max(fin, key=lambda x: x[1])[0] if lower_better else min(fin, key=lambda x: x[1])[0]
        return "best" if idx == best_j else ("worse" if idx == worst_j else "")

    for i, d in enumerate(drivers):
        d["best_lap_class"] = _cls(all_best, i, True)
        d["avg_lap_class"] = _cls(all_avg, i, True)
        d["cv_class"] = _cls(all_cv, i, True)
        d["score_class"] = _cls(all_scores, i, False)

    radar_img = _plot_radar_comparison(driver_results)
    speed_overlay_img = _plot_speed_overlay(driver_results)

    # Corner comparison

    corner_comparison = []
    all_corners = [dr.get("corner_performances") or [] for dr in driver_results]
    if all(len(c) > 0 for c in all_corners):
        corner_ids = sorted(set(
            cp.get("corner_id") for cps in all_corners for cp in cps if "corner_id" in cp
        ))
        for cid in corner_ids:
            losses = []
            loss_vals = []
            for cps in all_corners:
                cp = next((c for c in cps if c.get("corner_id") == cid), None)
                tl = cp.get("time_loss_s", 0.0) if cp else 0.0
                loss_vals.append(tl)
                losses.append({"val": f"{tl:.3f}s", "cls": ""})
            if len(loss_vals) >= 2:
                bi, wi = loss_vals.index(min(loss_vals)), loss_vals.index(max(loss_vals))
                if bi != wi:
                    losses[bi]["cls"] = "best"; losses[wi]["cls"] = "worse"
            adv = drivers[loss_vals.index(min(loss_vals))]["name"]
            delta = max(loss_vals) - min(loss_vals)
            corner_comparison.append({
                "corner_id": cid, "losses": losses,
                "advantage": f"{adv} by {delta:.3f}s" if delta > 0.01 else "Even",
            })

    sw_list = []
    if len(driver_results) == 2:
        for cat, label in [("pace", "Pace"), ("consistency", "Consistency"),
                           ("execution", "Execution"), ("robustness", "Robustness")]:
            s1 = driver_results[0].get("score_result", {}).get("sub_scores", {}).get(cat, {})
            s2 = driver_results[1].get("score_result", {}).get("sub_scores", {}).get(cat, {})
            p1, p2 = s1.get("pct", 50.0), s2.get("pct", 50.0)
            if abs(p1 - p2) > 5:
                better = drivers[0]["name"] if p1 > p2 else drivers[1]["name"]
                sw_list.append({"cls": "strength", "text": f"{better} has a {label.lower()} advantage ({abs(p1-p2):.0f}% difference)"})

    fin_best = [b for b in all_best if math.isfinite(b)]
    if len(fin_best) >= 2:
        gap = max(fin_best) - min(fin_best)
        gap_s = f"{gap:.3f}s"
        gap_summary = f"{drivers[all_best.index(min(fin_best))]['name']} is fastest overall"
    else:
        gap_s = "-"; gap_summary = "Insufficient data"

    title = "Driver Comparison: " + " vs ".join(d["name"] for d in drivers)

    env = Environment(loader=BaseLoader(), autoescape=False)
    template = env.from_string(_COMPARISON_TEMPLATE)
    html = template.render(
        title=title,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        drivers=drivers, radar_img=radar_img,
        speed_overlay_img=speed_overlay_img,
        corner_comparison=corner_comparison or None,
        strengths_weaknesses=sw_list or None,
        gap_s=gap_s, gap_summary=gap_summary,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Comparison report written to %s", output_path)
    return output_path.resolve()


def _run_tests() -> None:
    """Self-contained test suite  — run with ``python reporting_html.py``."""
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Synthetic data factories

    def _make_score_result() -> dict[str, Any]:
        return {
            "total_score": 78.5,
            "grade":       "B",
            "session_type": "practice",
            "strengths":   ["Pace", "Execution Quality"],
            "weaknesses":  ["Racecraft / Endurance Robustness"],
            "sub_scores": {
                "pace": {
                    "score": 28.5, "max": 35.0, "pct": 81.4,
                    "detail": {"raw_gap_s": 1.2, "gap_pct": 1.33},
                },
                "consistency": {
                    "score": 21.0, "max": 25.0, "pct": 84.0,
                    "detail": {
                        "cv_pct": 0.45, "best_to_median_s": 0.8,
                        "cv_ratio": 0.89, "btm_ratio": 0.81,
                    },
                },
                "execution": {
                    "score": 18.5, "max": 25.0, "pct": 74.0,
                    "detail": {
                        "speed_efficiency_ratio": 0.95,
                        "accel_efficiency_ratio": 0.85,
                        "braking_efficiency_ratio": 0.90,
                    },
                },
                "robustness": {
                    "score": 10.5, "max": 15.0, "pct": 70.0,
                    "detail": {
                        "pace_fade_frac": 0.015, "yaw_var_ratio": 1.3,
                        "fade_ratio": 0.78, "stability_ratio": 0.65,
                        "n_laps": 20,
                    },
                },
            },
        }

    def _make_theoretical_lap(n: int = 500) -> pd.DataFrame:
        dist = np.linspace(0, 4500, n)
        speed = 35 + 15 * np.sin(2 * np.pi * dist / 4500) + 5 * np.sin(6 * np.pi * dist / 4500)
        return pd.DataFrame({"distance_m": dist, "v_env_mps": speed})

    def _make_best_lap(n: int = 500) -> pd.DataFrame:
        dist  = np.linspace(0, 4500, n)
        speed = 33 + 14 * np.sin(2 * np.pi * dist / 4500) + 4 * np.sin(6 * np.pi * dist / 4500)
        speed += np.random.default_rng(42).normal(0, 0.5, n)
        return pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": speed})

    def _make_segment_losses(n_laps: int = 15, n_seg: int = 20) -> list[list[float]]:
        rng = np.random.default_rng(42)
        return (rng.normal(0, 25, (n_laps, n_seg))).tolist()

    def _make_delta_segments(n_seg: int = 20) -> list[dict[str, Any]]:
        causes = [
            "entry_loss", "mid_corner_loss", "exit_loss",
            "instability", "on_pace", "line_inefficiency",
        ]
        rng = np.random.default_rng(42)
        return [
            {
                "segment":      i + 1,
                "s_start_m":    i * 225.0,
                "s_end_m":      (i + 1) * 225.0,
                "time_loss_ms": float(rng.normal(0, 30)),
                "likely_cause": causes[i % len(causes)],
                "cause_details": {},
            }
            for i in range(n_seg)
        ]

    def _make_driver_profiles(n: int = 3) -> list[dict[str, Any]]:
        rng = np.random.default_rng(42)
        names = ["Alice", "Bob", "Charlie", "Diana", "Eve"][:n]
        profiles = []
        for name in names:
            profiles.append({
                "driver_name": name,
                "n_sessions":  int(rng.integers(3, 12)),
                "summary": {
                    "mean_pace_delta_s":  round(float(rng.uniform(0.5, 3.0)), 3),
                    "consistency_rating": round(float(rng.uniform(0.3, 1.0)), 2),
                    "aggression_index":   round(float(rng.uniform(0.2, 0.9)), 2),
                    "smoothness_index":   round(float(rng.uniform(0.4, 1.0)), 2),
                    "trend_label":        rng.choice(["improving", "stable", "declining"]),
                    "mean_session_score": round(float(rng.uniform(45, 92)), 1),
                },
            })
        return profiles

    def _make_session_meta() -> dict[str, Any]:
        return {
            "session_id":  "session_042",
            "track_id":    "spa_2024",
            "track_state": "dry",
            "driver_name": "Alice",
            "date":        "2024-09-15",
        }

    # ==================================================================

    # Test 1  --  full report generates valid HTML

    # ==================================================================

    def t_full_report() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "index.html"
            result = generate_report(
                score_result=_make_score_result(),
                theoretical_lap=_make_theoretical_lap(),
                best_lap=_make_best_lap(),
                delta_segments=_make_delta_segments(),
                lap_times=[90.0 + i * 0.3 for i in range(15)],
                segment_losses=_make_segment_losses(),
                driver_profiles=_make_driver_profiles(),
                session_meta=_make_session_meta(),
                output_path=path,
            )
            assert result.exists()
            content = path.read_text()
            assert "<!DOCTYPE html>" in content
            assert "78.5" in content           # total score
            assert "grade-B" in content        # grade badge
            assert "spa_2024" in content       # track
            assert "Alice" in content          # driver name
            assert "data:image/png;base64," in content  # embedded plots

    _test("full_report", t_full_report)

    # ==================================================================

    # Test 2  --  empty inputs produce valid HTML without crash

    # ==================================================================

    def t_empty_report() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "empty.html"
            result = generate_report(output_path=path)
            assert result.exists()
            content = path.read_text()
            assert "<!DOCTYPE html>" in content
            assert "No scoring data available" in content
            assert "No driver profile data" in content

    _test("empty_report", t_empty_report)

    # ==================================================================

    # Test 3  --  speed trace plot only with theoretical lap

    # ==================================================================

    def t_speed_trace_theoretical_only() -> None:
        img = _plot_speed_trace(_make_theoretical_lap(), None)
        assert img.startswith("data:image/png;base64,")
        assert len(img) > 100

    _test("speed_trace_theoretical_only", t_speed_trace_theoretical_only)

    # ==================================================================

    # Test 4  --  speed trace with both laps

    # ==================================================================

    def t_speed_trace_both() -> None:
        img = _plot_speed_trace(_make_theoretical_lap(), _make_best_lap())
        assert img.startswith("data:image/png;base64,")

    _test("speed_trace_both", t_speed_trace_both)

    # ==================================================================

    # Test 5  --  speed trace with no data returns empty

    # ==================================================================

    def t_speed_trace_empty() -> None:
        img = _plot_speed_trace(None, None)
        assert img == ""

    _test("speed_trace_empty", t_speed_trace_empty)

    # ==================================================================

    # Test 6  --  heatmap plot generates

    # ==================================================================

    def t_heatmap_plot() -> None:
        img = _plot_delta_heatmap(
            _make_segment_losses(),
            lap_labels=[f"L{i+1}" for i in range(15)],
            cause_data=_make_delta_segments(),
        )
        assert img.startswith("data:image/png;base64,")

    _test("heatmap_plot", t_heatmap_plot)

    # ==================================================================

    # Test 7  --  heatmap with no data returns empty

    # ==================================================================

    def t_heatmap_empty() -> None:
        assert _plot_delta_heatmap(None) == ""
        assert _plot_delta_heatmap([]) == ""

    _test("heatmap_empty", t_heatmap_empty)

    # ==================================================================

    # Test 8  --  sub-scores plot generates

    # ==================================================================

    def t_sub_scores_plot() -> None:
        sr = _make_score_result()
        img = _plot_sub_scores(sr["sub_scores"])
        assert img.startswith("data:image/png;base64,")

    _test("sub_scores_plot", t_sub_scores_plot)

    # ==================================================================

    # Test 9  --  sub-scores plot with no data returns empty

    # ==================================================================

    def t_sub_scores_empty() -> None:
        assert _plot_sub_scores(None) == ""
        assert _plot_sub_scores({}) == ""

    _test("sub_scores_empty", t_sub_scores_empty)

    # ==================================================================

    # Test 10  --  driver comparison table rows

    # ==================================================================

    def t_driver_rows() -> None:
        rows = _build_driver_rows(_make_driver_profiles(4))
        assert len(rows) == 4
        for r in rows:
            assert "driver_name" in r
            assert "pace_delta"  in r
            assert "pace_class"  in r

        # At least one best-val and one worst-val

        classes = [r["pace_class"] for r in rows]
        assert "best-val" in classes
        assert "worst-val" in classes

    _test("driver_rows", t_driver_rows)

    # ==================================================================

    # Test 11  --  driver rows with single driver

    # ==================================================================

    def t_driver_rows_single() -> None:
        rows = _build_driver_rows(_make_driver_profiles(1))
        assert len(rows) == 1
        # No best/worst with single driver

        assert rows[0]["pace_class"] == ""

    _test("driver_rows_single", t_driver_rows_single)

    # ==================================================================

    # Test 12  --  driver rows empty

    # ==================================================================

    def t_driver_rows_empty() -> None:
        assert _build_driver_rows([]) == []

    _test("driver_rows_empty", t_driver_rows_empty)

    # ==================================================================

    # Test 13  --  report title construction

    # ==================================================================

    def t_title_construction() -> None:
        assert "spa_2024" in _build_title({"track_id": "spa_2024"})
        assert "Alice" in _build_title({"driver_name": "Alice"})
        assert _build_title({}) == "Session Report"

    _test("title_construction", t_title_construction)

    # ==================================================================

    # Test 14  --  HTML contains all major sections

    # ==================================================================

    def t_sections_present() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.html"
            generate_report(
                score_result=_make_score_result(),
                theoretical_lap=_make_theoretical_lap(),
                best_lap=_make_best_lap(),
                segment_losses=_make_segment_losses(),
                driver_profiles=_make_driver_profiles(),
                session_meta=_make_session_meta(),
                output_path=path,
            )
            content = path.read_text()
            assert "Session Score" in content
            assert "Sub-Score Breakdown" in content
            assert "Theoretical vs Best Lap" in content
            assert "Segment Delta Heatmap" in content
            assert "Driver Comparison" in content

    _test("sections_present", t_sections_present)

    # ==================================================================

    # Test 15  --  file size is reasonable (<1 MB)

    # ==================================================================

    def t_file_size() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.html"
            generate_report(
                score_result=_make_score_result(),
                theoretical_lap=_make_theoretical_lap(),
                best_lap=_make_best_lap(),
                segment_losses=_make_segment_losses(),
                driver_profiles=_make_driver_profiles(),
                session_meta=_make_session_meta(),
                output_path=path,
            )
            size_kb = path.stat().st_size / 1024
            assert size_kb < 1024, f"Report too large: {size_kb:.0f} KB"
            assert size_kb > 10, f"Report suspiciously small: {size_kb:.0f} KB"

    _test("file_size", t_file_size)

    # ==================================================================

    # Test 16  --  NaN handling in driver profiles

    # ==================================================================

    def t_nan_driver_profiles() -> None:
        profiles = [{
            "driver_name": "NaNDriver",
            "n_sessions": 1,
            "summary": {
                "mean_pace_delta_s":  float("nan"),
                "consistency_rating": None,
                "aggression_index":   float("nan"),
                "smoothness_index":   float("nan"),
                "trend_label":        None,
                "mean_session_score": float("nan"),
            },
        }]
        rows = _build_driver_rows(profiles)
        assert len(rows) == 1
        assert rows[0]["pace_delta"]  == " —"
        assert rows[0]["consistency"] == " —"
        assert rows[0]["avg_score"]   == " —"

    _test("nan_driver_profiles", t_nan_driver_profiles)

    # ==================================================================

    # Test 17  --  report with score but no plots

    # ==================================================================

    def t_score_only() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "score_only.html"
            generate_report(
                score_result=_make_score_result(),
                output_path=path,
            )
            content = path.read_text()
            assert "78.5" in content
            assert "Insufficient lap data" in content   # no speed trace

    _test("score_only", t_score_only)

    # ==================================================================

    # Test 18  --  deterministic output

    # ==================================================================

    def t_deterministic() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "r1.html"
            p2 = Path(tmpdir) / "r2.html"
            kwargs: dict[str, Any] = dict(
                score_result=_make_score_result(),
                theoretical_lap=_make_theoretical_lap(),
                best_lap=_make_best_lap(),
                session_meta=_make_session_meta(),
            )
            generate_report(**kwargs, output_path=p1)
            generate_report(**kwargs, output_path=p2)

            c1 = p1.read_text()
            c2 = p2.read_text()
            # Strip generated-at timestamp line for comparison

            import re
            strip = lambda s: re.sub(r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", "", s)
            assert strip(c1) == strip(c2)

    _test("deterministic", t_deterministic)

    # ==================================================================

    # Test 19  --  grade badge classes for all grades

    # ==================================================================

    def t_grade_badges() -> None:
        for grade in ("S", "A", "B", "C", "D", "F"):
            sr = _make_score_result()
            sr["grade"] = grade
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "grade.html"
                generate_report(score_result=sr, output_path=path)
                content = path.read_text()
                assert f"grade-{grade}" in content

    _test("grade_badges", t_grade_badges)

    # ==================================================================

    # Test 20  --  large heatmap (many laps, many segments)

    # ==================================================================

    def t_large_heatmap() -> None:
        rng = np.random.default_rng(99)
        losses = rng.normal(0, 40, (40, 30)).tolist()
        img = _plot_delta_heatmap(losses)
        assert img.startswith("data:image/png;base64,")

    _test("large_heatmap", t_large_heatmap)

    # ==================================================================

    # Test 21  --  _safe_float edge cases

    # ==================================================================

    def t_safe_float() -> None:
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5
        assert math.isnan(_safe_float(None))
        assert math.isnan(_safe_float(float("nan")))
        assert math.isnan(_safe_float("not_a_number"))
        assert _safe_float(float("inf")) == float("nan") or math.isnan(_safe_float(float("inf")))

    _test("safe_float", t_safe_float)

    # ==================================================================

    # Test 22  --  sub-score detail rendering (dict values in template)

    # ==================================================================

    def t_sub_score_details_in_html() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "detail.html"
            generate_report(
                score_result=_make_score_result(),
                output_path=path,
            )
            content = path.read_text()
            assert "raw_gap_s" in content
            assert "cv_pct" in content
            assert "speed_efficiency_ratio" in content

    _test("sub_score_details_in_html", t_sub_score_details_in_html)

    # ==================================================================

    # Test 23  --  speed trace with alternative column names

    # ==================================================================

    def t_speed_trace_alt_cols() -> None:
        # Theoretical using output names, best_lap using raw telemetry names

        theo = pd.DataFrame({
            "distance_m": np.linspace(0, 4000, 300),
            "v_env_mps":  30 + 10 * np.sin(np.linspace(0, 6, 300)),
        })
        best = pd.DataFrame({
            "Distance (m)": np.linspace(0, 4000, 300),
            "Speed (m/s)":  28 + 9 * np.sin(np.linspace(0, 6, 300)),
        })
        img = _plot_speed_trace(theo, best)
        assert img.startswith("data:image/png;base64,")

    _test("speed_trace_alt_cols", t_speed_trace_alt_cols)

    # ==================================================================

    # Test 24  --  cause annotations on heatmap

    # ==================================================================

    def t_heatmap_cause_annotations() -> None:
        losses = [[10, -5, 20, 0, -15]] * 3
        causes = [
            {"segment": 1, "likely_cause": "entry_loss"},
            {"segment": 2, "likely_cause": "on_pace"},
            {"segment": 3, "likely_cause": "exit_loss"},
            {"segment": 4, "likely_cause": "instability"},
            {"segment": 5, "likely_cause": "line_inefficiency"},
        ]
        img = _plot_delta_heatmap(losses, cause_data=causes)
        assert img.startswith("data:image/png;base64,")

    _test("heatmap_cause_annotations", t_heatmap_cause_annotations)

    # ==================================================================

    # Test 25  --  output_path creates parent dirs

    # ==================================================================

    def t_creates_parent_dirs() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            deep = Path(tmpdir) / "a" / "b" / "c" / "report.html"
            generate_report(output_path=deep)
            assert deep.exists()

    _test("creates_parent_dirs", t_creates_parent_dirs)

    # -- Physics test fixtures -- -


    def _make_gg_laps(n_laps: int = 8) -> dict:
        rng = np.random.default_rng(42)
        laps = {}
        for i in range(n_laps):
            n = 200
            laps[i + 1] = pd.DataFrame({
                "accel_lat_mps2":  rng.normal(0, 5, n),
                "accel_long_mps2": rng.normal(0, 4, n),
                "Speed (m/s)":     rng.uniform(10, 40, n),
            })
        return laps

    class _MockGripEvolution:
        peak_lateral_g_per_lap = [1.2, 1.25, 1.23, 1.20, 1.18, 1.15, 1.12, 1.10, 1.08, 1.05]
        peak_braking_g_per_lap = [1.3, 1.32, 1.30, 1.28, 1.25, 1.22, 1.20, 1.18, 1.15, 1.12]
        degradation_rate_pct_per_lap = 1.5
        estimated_grip_drop_pct = 12.5
        thermal_phase_laps = 1

    def _make_corner_perfs():
        class CP:
            pass
        perfs = []
        for i in range(3):
            p = CP()
            p.corner_id = i + 1
            p.s_start = 100.0 * (i + 1)
            p.s_end = p.s_start + 80
            p.theoretical_entry_speed_mps = 30.0
            p.actual_entry_speed_mps = 28.0 - i
            p.theoretical_apex_speed_mps = 20.0
            p.actual_apex_speed_mps = 18.0 - i
            p.theoretical_exit_speed_mps = 25.0
            p.actual_exit_speed_mps = 23.0 - i
            p.braking_point_delta_m = 5.0 + i * 3
            p.grip_utilisation_pct = 90.0 - i * 10
            p.time_loss_s = 0.1 + i * 0.15
            p.time_loss_braking_s = 0.05
            p.time_loss_apex_speed_s = 0.03
            p.time_loss_exit_s = 0.02
            p.coaching_hint = f"Brake {5+i*3}m later, carry more apex speed."
            perfs.append(p)
        return perfs

    # ==================================================================

    # Test 26 -- physics speed overlay generates

    # ==================================================================

    def t_physics_speed_overlay() -> None:
        theo = _make_theoretical_lap()
        best = _make_best_lap()
        median = _make_best_lap()
        img = _plot_physics_speed_overlay(theo, best, median_lap=median)
        assert img.startswith("data:image/png;base64,")

    _test("physics_speed_overlay", t_physics_speed_overlay)

    # ==================================================================

    # Test 27 -- physics speed overlay with cornering zones

    # ==================================================================

    def t_physics_speed_with_zones() -> None:
        theo = _make_theoretical_lap()
        best = _make_best_lap()
        dist = np.linspace(0, 4500, 500)
        cornering = np.zeros(500, dtype=bool)
        cornering[50:100] = True
        cornering[250:300] = True
        img = _plot_physics_speed_overlay(
            theo, best,
            cornering_limited=cornering,
            sim_distance=dist,
        )
        assert img.startswith("data:image/png;base64,")

    _test("physics_speed_with_zones", t_physics_speed_with_zones)

    # ==================================================================

    # Test 28 -- physics speed overlay with no data returns empty

    # ==================================================================

    def t_physics_speed_empty() -> None:
        assert _plot_physics_speed_overlay(None, None) == ""

    _test("physics_speed_empty", t_physics_speed_empty)

    # ==================================================================

    # Test 29 -- G-G diagram generates

    # ==================================================================

    def t_gg_diagram() -> None:
        laps = _make_gg_laps()
        img = _plot_gg_diagram(laps)
        assert img.startswith("data:image/png;base64,")

    _test("gg_diagram", t_gg_diagram)

    # ==================================================================

    # Test 30 -- G-G diagram empty

    # ==================================================================

    def t_gg_diagram_empty() -> None:
        assert _plot_gg_diagram(None) == ""
        assert _plot_gg_diagram({}) == ""

    _test("gg_diagram_empty", t_gg_diagram_empty)

    def t_gg_diagram_single_lap() -> None:
        """Single-lap session must not crash on colorbar normalisation."""
        dist = np.linspace(0, 600, 300)
        rng = np.random.default_rng(42)
        laps = {1: pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": 20 + 10 * np.sin(2*np.pi*dist/600),
            "accel_lat_mps2": rng.normal(0, 5, 300),
            "accel_long_mps2": rng.normal(0, 4, 300),
        })}
        img = _plot_gg_diagram(laps)
        assert isinstance(img, str)
        assert len(img) > 10

    _test("gg_diagram_single_lap", t_gg_diagram_single_lap)

    def t_gg_diagram_all_nan() -> None:
        """All-NaN accel data should return empty string, not crash."""
        laps = {1: pd.DataFrame({
            "Distance (m)": np.linspace(0, 600, 100),
            "Speed (m/s)": np.full(100, 20.0),
            "accel_lat_mps2": np.full(100, np.nan),
            "accel_long_mps2": np.full(100, np.nan),
        })}
        assert _plot_gg_diagram(laps) == ""

    _test("gg_diagram_all_nan", t_gg_diagram_all_nan)

    def t_gg_diagram_near_zero() -> None:
        """Near-zero accel data should return empty (no useful info)."""
        laps = {1: pd.DataFrame({
            "Distance (m)": np.linspace(0, 600, 100),
            "Speed (m/s)": np.full(100, 20.0),
            "accel_lat_mps2": np.full(100, 0.001),
            "accel_long_mps2": np.full(100, 0.001),
        })}
        assert _plot_gg_diagram(laps) == ""

    _test("gg_diagram_near_zero", t_gg_diagram_near_zero)

    # ==================================================================

    # Test 31 -- grip evolution plot generates

    # ==================================================================

    def t_grip_evolution_plot() -> None:
        ge = _MockGripEvolution()
        img = _plot_grip_evolution(ge, lap_times=[30 + 0.1*i for i in range(10)])
        assert img.startswith("data:image/png;base64,")

    _test("grip_evolution_plot", t_grip_evolution_plot)

    # ==================================================================

    # Test 32 -- grip evolution plot empty

    # ==================================================================

    def t_grip_evolution_empty() -> None:
        assert _plot_grip_evolution(None) == ""

    _test("grip_evolution_empty", t_grip_evolution_empty)

    # ==================================================================

    # Test 33 -- corner table HTML generation

    # ==================================================================

    def t_corner_table() -> None:
        perfs = _make_corner_perfs()
        html = _build_corner_table_html(perfs)
        assert "<table" in html
        assert "C1" in html and "C2" in html
        assert "Brake" in html  # header present
        assert "Coaching" in html

    _test("corner_table", t_corner_table)

    # ==================================================================

    # Test 34 -- corner table sorted by time loss

    # ==================================================================

    def t_corner_table_sorted() -> None:
        perfs = _make_corner_perfs()
        html = _build_corner_table_html(perfs)
        # C3 has highest time loss (0.40s) and should appear first

        pos_c3 = html.index("C3")
        pos_c1 = html.index("C1")
        assert pos_c3 < pos_c1, "Corners should be sorted by time loss descending"

    _test("corner_table_sorted", t_corner_table_sorted)

    # ==================================================================

    # Test 35 -- corner table empty

    # ==================================================================

    def t_corner_table_empty() -> None:
        assert _build_corner_table_html(None) == ""
        assert _build_corner_table_html([]) == ""

    _test("corner_table_empty", t_corner_table_empty)

    # ==================================================================

    # Test 36 -- quality badge HIGH

    # ==================================================================

    def t_quality_badge_high() -> None:
        sr = {"data_confidence": 0.9, "simulation_method": "physics"}
        html = _build_quality_badge_html(sr, session_meta={"track_state": "dry"})
        assert "HIGH" in html
        assert "dry" in html

    _test("quality_badge_high", t_quality_badge_high)

    # ==================================================================

    # Test 37 -- quality badge LOW

    # ==================================================================

    def t_quality_badge_low() -> None:
        sr = {"data_confidence": 0.3}
        html = _build_quality_badge_html(sr)
        assert "LOW" in html

    _test("quality_badge_low", t_quality_badge_low)

    # ==================================================================

    # Test 38 -- sim method badge physics

    # ==================================================================

    def t_sim_badge_physics() -> None:
        sr = {"simulation_method": "physics"}
        html = _build_sim_method_badge_html(sr)
        assert "Physics simulation" in html

    _test("sim_badge_physics", t_sim_badge_physics)

    # ==================================================================

    # Test 39 -- sim method badge percentile

    # ==================================================================

    def t_sim_badge_percentile() -> None:
        sr = {"simulation_method": "percentile_envelope"}
        html = _build_sim_method_badge_html(sr)
        assert "Statistical envelope" in html

    _test("sim_badge_percentile", t_sim_badge_percentile)

    # ==================================================================

    # Test 40 -- full report with all physics data

    # ==================================================================

    def t_full_report_physics() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "physics.html"
            sr = _make_score_result()
            sr["simulation_method"] = "physics"
            sr["data_confidence"] = 0.85

            result = generate_report(
                score_result=sr,
                theoretical_lap=_make_theoretical_lap(),
                best_lap=_make_best_lap(),
                median_lap=_make_best_lap(),
                resampled_laps=_make_gg_laps(),
                corner_performances=_make_corner_perfs(),
                grip_evolution=_MockGripEvolution(),
                lap_times=[90.0 + i * 0.3 for i in range(15)],
                session_meta=_make_session_meta(),
                output_path=path,
            )
            assert result.exists()
            html = path.read_text()
            assert "Physics simulation" in html
            assert "Analysis confidence" in html
            assert "G-G Diagram" in html
            assert "Corner-by-Corner" in html
            assert "Grip Evolution" in html
            # Embedded plot images

            assert html.count("data:image/png;base64,") >= 4

    _test("full_report_physics", t_full_report_physics)

    # ==================================================================

    # Test 41 -- backward compat: no physics params still works

    # ==================================================================

    def t_backward_compat_no_physics() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "compat.html"
            result = generate_report(
                score_result=_make_score_result(),
                theoretical_lap=_make_theoretical_lap(),
                best_lap=_make_best_lap(),
                session_meta=_make_session_meta(),
                output_path=path,
            )
            assert result.exists()
            html = path.read_text()
            assert "<!DOCTYPE html>" in html
            assert "Session Score" in html
            # Physics-only sections should NOT render when data absent

            assert "<h2>G-G Diagram</h2>" not in html
            assert "<h2>Corner-by-Corner" not in html
            assert "<h2>Grip Evolution</h2>" not in html

    _test("backward_compat_no_physics", t_backward_compat_no_physics)

    # Summary

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nReporting HTML Tests: {len(passed)}/{total} passed [{status}]")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# ============================================================================

# Entry point

# ============================================================================


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()