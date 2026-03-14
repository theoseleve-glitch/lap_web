"""
driver_diagnostics.py
---------------------
Session-level ML + physics diagnostics for kart driving behavior.

The module classifies recurrent time-loss patterns such as:
- underdriving / overdriving
- wrong line (early/late turn-in, apex timing drift)
- underbraking / overbraking (lock-up proxy)
- coasting
- yaw/countersteer instability (when yaw is available)
- crest/banking sensitivity from altitude + accelerometer traces
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_ALTITUDE,
    COL_DIST,
    COL_SPEED,
    COL_TIME,
    COL_YAW_RATE,
)
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.track.geometry import TrackGeometry

logger = logging.getLogger(__name__)

_G = 9.80665

try:
    from sklearn.ensemble import IsolationForest
except Exception:  # pragma: no cover - optional dependency
    IsolationForest = None  # type: ignore[assignment]


# ── Adaptive diagnostic thresholds by vehicle class ─────────────────────

@dataclass
class DiagnosticThresholds:
    """Scaling factors for diagnostic findings by vehicle class.

    All values are multiplicative adjustments to base thresholds.
    A kart has tighter tolerances (lower thresholds) than a road car
    because the vehicle is more direct and responsive.

    Attributes
    ----------
    vehicle_class : str
        Vehicle class label.
    underbrake_threshold : float
        Brake utilization p90 below which 'underbraking' triggers.
    overbrake_lockup_frac : float
        Lock-up fraction above which 'overbraking' triggers.
    coast_frac_threshold : float
        Coasting fraction above which 'excess coasting' triggers.
    gg_under_threshold : float
        G-G utilization below which driving is 'underdriving'.
    gg_over_threshold : float
        G-G over-limit fraction above which driving is 'overdriving'.
    abrupt_ramp_threshold_mps3 : float
        Brake ramp rate above which braking is 'abrupt'.
    trail_ratio_threshold : float
        Trail-brake ratio below which trail-braking is 'absent'.
    trust_drop_threshold : float
        G-G drop low-to-high above which trust deficit triggers.
    lap_time_std_threshold : float
        Lap time std [s] above which 'execution inconsistency' triggers.
    """
    vehicle_class: str = "kart"
    underbrake_threshold: float = 0.88
    overbrake_lockup_frac: float = 0.05
    coast_frac_threshold: float = 0.08
    gg_under_threshold: float = 0.90
    gg_over_threshold: float = 0.03
    abrupt_ramp_threshold_mps3: float = 50.0
    trail_ratio_threshold: float = 0.30
    trust_drop_threshold: float = 0.08
    lap_time_std_threshold: float = 0.9


# Vehicle class → threshold presets.
# Karts are the tightest (small, direct, responsive).
# Road cars are the loosest (heavy, compliant, forgiving).
_THRESHOLD_PRESETS: dict[str, DiagnosticThresholds] = {
    "kart": DiagnosticThresholds(
        vehicle_class="kart",
        underbrake_threshold=0.85,    # karts have less brake capacity — 0.85 is OK
        overbrake_lockup_frac=0.06,   # karts lock easier — slightly more tolerant
        coast_frac_threshold=0.06,    # very little coasting expected on a kart
        gg_under_threshold=0.90,
        gg_over_threshold=0.03,
        abrupt_ramp_threshold_mps3=40.0,  # shorter braking zones → naturally sharper
        trail_ratio_threshold=0.25,       # less trail-braking opportunity on karts
        trust_drop_threshold=0.10,
        lap_time_std_threshold=0.6,       # short laps → tighter consistency
    ),
    "formula": DiagnosticThresholds(
        vehicle_class="formula",
        underbrake_threshold=0.92,    # formula cars have ABS-free big brakes
        overbrake_lockup_frac=0.03,   # lockup is costly with slick tires
        coast_frac_threshold=0.05,    # should be on power or brake, rarely coasting
        gg_under_threshold=0.92,      # high downforce → should use more grip
        gg_over_threshold=0.02,
        abrupt_ramp_threshold_mps3=60.0,  # longer braking zones → expect more control
        trail_ratio_threshold=0.35,       # trail-braking is critical in formula
        trust_drop_threshold=0.06,        # downforce gives MORE grip at speed
        lap_time_std_threshold=0.5,
    ),
    "gt": DiagnosticThresholds(
        vehicle_class="gt",
        underbrake_threshold=0.90,
        overbrake_lockup_frac=0.04,
        coast_frac_threshold=0.08,
        gg_under_threshold=0.88,
        gg_over_threshold=0.03,
        abrupt_ramp_threshold_mps3=55.0,
        trail_ratio_threshold=0.30,
        trust_drop_threshold=0.08,
        lap_time_std_threshold=0.8,
    ),
    "touring": DiagnosticThresholds(
        vehicle_class="touring",
        underbrake_threshold=0.88,
        overbrake_lockup_frac=0.05,
        coast_frac_threshold=0.10,
        gg_under_threshold=0.85,
        gg_over_threshold=0.04,
        abrupt_ramp_threshold_mps3=50.0,
        trail_ratio_threshold=0.28,
        trust_drop_threshold=0.10,
        lap_time_std_threshold=0.9,
    ),
    "road_car": DiagnosticThresholds(
        vehicle_class="road_car",
        underbrake_threshold=0.82,    # road cars have ABS — less raw util expected
        overbrake_lockup_frac=0.08,   # ABS prevents real lockup
        coast_frac_threshold=0.15,    # more coasting is normal
        gg_under_threshold=0.80,      # lower grip → lower expectations
        gg_over_threshold=0.05,
        abrupt_ramp_threshold_mps3=45.0,
        trail_ratio_threshold=0.22,   # less trail-braking with ABS
        trust_drop_threshold=0.12,
        lap_time_std_threshold=1.2,
    ),
}


def _infer_vehicle_class(
    metadata: SessionMetadata,
    scalars: SessionScalars,
) -> str:
    """Infer vehicle class from metadata or session characteristics.

    Priority:
    1. Explicit metadata field (kart_class → kart)
    2. Peak lateral g from scalars (infers vehicle type from grip level)
    """
    # Check for explicit hints
    kart_class = str(getattr(metadata, "kart_class", "") or "").strip().lower()
    if kart_class in ("2t", "4t", "kz", "ok", "rotax", "x30"):
        return "kart"

    # Infer from peak grip (mu_session * peak lateral g of envelope)
    peak_lat_g = float(scalars.mu_session) if scalars else 1.0
    if peak_lat_g >= 1.6:
        return "formula"
    if peak_lat_g >= 1.25:
        return "gt"
    if peak_lat_g >= 1.05:
        return "touring"
    if peak_lat_g >= 0.85:
        return "road_car"
    return "kart"  # low grip could be a rental kart


def get_thresholds(vehicle_class: str) -> DiagnosticThresholds:
    """Return diagnostic thresholds for the given vehicle class."""
    return _THRESHOLD_PRESETS.get(
        vehicle_class.lower(),
        _THRESHOLD_PRESETS["kart"],
    )


@dataclass
class DiagnosticFinding:
    """Single driver-behavior finding."""

    code: str
    title: str
    severity: str
    score: float
    confidence: float
    evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity,
            "score": round(float(self.score), 4),
            "confidence": round(float(self.confidence), 4),
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class DriverDiagnostics:
    """Session-level diagnostics output."""

    dominant_pattern: str
    findings: list[DiagnosticFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    ml_summary: dict[str, Any] = field(default_factory=dict)
    yaw_summary: dict[str, Any] = field(default_factory=dict)
    lap_metrics: list[dict[str, Any]] = field(default_factory=list)
    corner_metrics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dominant_pattern": self.dominant_pattern,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": _json_safe_dict(self.metrics),
            "ml_summary": _json_safe_dict(self.ml_summary),
            "yaw_summary": _json_safe_dict(self.yaw_summary),
            "lap_metrics": [_json_safe_dict(r) for r in self.lap_metrics],
            "corner_metrics": [_json_safe_dict(r) for r in self.corner_metrics],
        }

    def to_text(self, max_items: int = 4) -> str:
        if not self.findings:
            return "No strong recurrent behavioral issue detected."
        lines = []
        for i, finding in enumerate(self.findings[:max_items], start=1):
            lines.append(
                f"{i}. {finding.title} ({finding.severity}, score {finding.score:.2f}) - "
                f"{finding.recommendation}"
            )
        return "\n".join(lines)


def analyze_driver_dynamics(
    resampled_laps: dict[int, pd.DataFrame],
    best_lap_df: pd.DataFrame,
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars,
    metadata: SessionMetadata,
    corners: list[dict[str, Any]],
    config: KartEnvelopeConfig,
) -> DriverDiagnostics:
    """
    Diagnose recurrent session-level time-loss behavior.

    Returns a model-style report with scores, confidence, and evidence.
    """
    if not resampled_laps:
        return DriverDiagnostics(dominant_pattern="insufficient_data")

    env_session = _session_envelope(envelope, scalars, metadata)
    ref = _build_reference(best_lap_df, geometry, corners)

    lap_rows: list[dict[str, Any]] = []
    corner_rows: list[dict[str, Any]] = []
    for lap_num, lap_df in resampled_laps.items():
        row, corner_detail = _analyze_lap(
            lap_num=lap_num,
            lap_df=lap_df,
            geometry=geometry,
            env=env_session,
            corner_ref=ref["corners"],
            ref_distance=ref["distance"],
            ref_speed=ref["speed"],
        )
        if row is not None:
            lap_rows.append(row)
            corner_rows.extend(corner_detail)

    if not lap_rows:
        return DriverDiagnostics(dominant_pattern="insufficient_data")

    # Infer vehicle class and select adaptive thresholds
    v_class = _infer_vehicle_class(metadata, scalars)
    thresholds = get_thresholds(v_class)
    logger.info("Driver diagnostics: vehicle_class=%s, thresholds=%s", v_class, thresholds.vehicle_class)

    lap_metrics_df = pd.DataFrame(lap_rows)
    ml_summary = _lap_outlier_model(lap_metrics_df)
    findings, metrics, yaw_summary = _classify_findings(
        lap_metrics_df=lap_metrics_df,
        corner_rows=corner_rows,
        ml_summary=ml_summary,
        thresholds=thresholds,
    )

    findings.sort(key=lambda f: f.score, reverse=True)
    dominant = findings[0].code if findings else "balanced_execution"
    return DriverDiagnostics(
        dominant_pattern=dominant,
        findings=findings,
        metrics=metrics,
        ml_summary=ml_summary,
        yaw_summary=yaw_summary,
        lap_metrics=lap_rows,
        corner_metrics=corner_rows,
    )


def _session_envelope(
    envelope: CapabilityEnvelope,
    scalars: SessionScalars,
    metadata: SessionMetadata,
) -> CapabilityEnvelope:
    tire = str(getattr(metadata, "tire_type", "slick") or "slick").strip().lower()
    cond = str(metadata.condition_label or scalars.condition_label or "dry").strip().lower()
    tire_table = {
        ("slick", "dry"): 1.00,
        ("slick", "damp"): 0.96,
        ("slick", "wet"): 0.88,
        ("slick", "greasy"): 0.92,
        ("wet", "dry"): 0.94,
        ("wet", "damp"): 1.00,
        ("wet", "wet"): 1.00,
        ("wet", "greasy"): 0.99,
    }
    tire_scale = float(tire_table.get((tire, cond), 1.00))
    return envelope.scaled(
        mu=float(scalars.mu_session) * tire_scale,
        p_drive=float(scalars.p_session) * tire_scale,
        b_brake=float(scalars.b_session) * tire_scale,
    )


def _build_reference(
    best_lap_df: pd.DataFrame,
    geometry: TrackGeometry,
    corners: list[dict[str, Any]],
) -> dict[str, Any]:
    s, v, ax, ay, yaw, kappa, alt, t = _extract_arrays(best_lap_df, geometry)
    corner_ref: dict[int, dict[str, float]] = {}
    for c in corners:
        corner_id = int(c.get("corner_id", 0))
        s_start = float(c.get("s_start", np.nan))
        s_end = float(c.get("s_end", np.nan))
        s_apex = float(c.get("s_apex", np.nan))
        if corner_id <= 0 or not np.isfinite(s_start) or not np.isfinite(s_end):
            continue
        turn_in = _estimate_turn_in_point(s, ay, s_start, s_apex if np.isfinite(s_apex) else 0.5 * (s_start + s_end))
        apex_s, apex_v = _estimate_apex_point(s, v, s_start, s_end)
        corner_ref[corner_id] = {
            "s_start": s_start,
            "s_end": s_end,
            "s_apex_ref": float(apex_s),
            "v_apex_ref": float(apex_v),
            "turn_in_ref": float(turn_in),
        }
    return {
        "distance": s,
        "speed": v,
        "corners": corner_ref,
    }


def _analyze_speed_dependent_gg(
    v: np.ndarray,
    gg_util: np.ndarray,
    ay_util: np.ndarray,
) -> dict[str, float]:
    """Compute G-G utilization in low / mid / high speed bins.

    A driver who uses 90% of grip at low speed but only 60% at high
    speed has a *speed-dependent trust deficit* — a psychological
    limitation, not a vehicle limitation.

    Speed bins are determined by the session's speed range:
      - Low:  bottom third of speed range
      - Mid:  middle third
      - High: top third

    Returns per-bin G-G utilization and the drop from low to high.
    """
    if len(v) < 20:
        return {
            "gg_util_low_speed": float("nan"),
            "gg_util_mid_speed": float("nan"),
            "gg_util_high_speed": float("nan"),
            "gg_drop_low_to_high": float("nan"),
            "ay_util_low_speed": float("nan"),
            "ay_util_high_speed": float("nan"),
        }

    # Determine speed terciles from the actual session data
    v_p10 = float(np.percentile(v, 10))
    v_p90 = float(np.percentile(v, 90))
    v_range = v_p90 - v_p10
    if v_range < 2.0:
        # Very narrow speed range — can't do meaningful split
        return {
            "gg_util_low_speed": float("nan"),
            "gg_util_mid_speed": float("nan"),
            "gg_util_high_speed": float("nan"),
            "gg_drop_low_to_high": float("nan"),
            "ay_util_low_speed": float("nan"),
            "ay_util_high_speed": float("nan"),
        }

    v_lo_cut = v_p10 + v_range / 3.0
    v_hi_cut = v_p10 + 2.0 * v_range / 3.0

    lo_mask = v <= v_lo_cut
    mid_mask = (v > v_lo_cut) & (v <= v_hi_cut)
    hi_mask = v > v_hi_cut

    # Only consider samples where the driver is actually cornering
    # (not cruising on a straight at low utilization)
    cornering_threshold = 0.20
    active = gg_util > cornering_threshold

    def _bin_util(mask: np.ndarray) -> float:
        sel = mask & active & np.isfinite(gg_util)
        if sel.sum() < 10:
            return float("nan")
        return float(np.percentile(gg_util[sel], 90))

    def _bin_ay(mask: np.ndarray) -> float:
        sel = mask & active & np.isfinite(ay_util)
        if sel.sum() < 10:
            return float("nan")
        return float(np.percentile(ay_util[sel], 90))

    gg_lo = _bin_util(lo_mask)
    gg_mid = _bin_util(mid_mask)
    gg_hi = _bin_util(hi_mask)

    drop = (gg_lo - gg_hi) if (np.isfinite(gg_lo) and np.isfinite(gg_hi)) else float("nan")

    return {
        "gg_util_low_speed": gg_lo,
        "gg_util_mid_speed": gg_mid,
        "gg_util_high_speed": gg_hi,
        "gg_drop_low_to_high": drop,
        "ay_util_low_speed": _bin_ay(lo_mask),
        "ay_util_high_speed": _bin_ay(hi_mask),
    }


def _analyze_brake_modulation(
    s: np.ndarray,
    ax: np.ndarray,
    dt: np.ndarray,
    ax_brake_lim: np.ndarray,
) -> dict[str, float]:
    """Extract brake modulation metrics from longitudinal acceleration.

    Identifies individual braking events (contiguous ax < -0.5 m/s²)
    and measures three modulation characteristics:

    1. **Ramp rate**: How quickly the driver reaches peak deceleration.
       High ramp rate → abrupt brake application → lockup risk.
    2. **Trail-brake ratio**: What fraction of the braking zone has
       gradually decreasing deceleration (trail-braking).
       Low ratio → driver releases brakes abruptly → misses trail-brake.
    3. **Peak position**: Where in the braking zone peak decel occurs.
       Late peak → driver is slow to build initial brake pressure.

    Returns dict with median values across all braking events in the lap.
    """
    brake_threshold = -0.5  # m/s² — threshold for "braking"
    min_event_samples = 5

    # Find braking events (contiguous regions of ax < threshold)
    braking = ax < brake_threshold
    events: list[tuple[int, int]] = []
    i = 0
    n = len(ax)
    while i < n:
        if braking[i]:
            start = i
            while i < n and braking[i]:
                i += 1
            end = i  # exclusive
            if (end - start) >= min_event_samples:
                events.append((start, end))
        else:
            i += 1

    if not events:
        return {
            "brake_ramp_rate_median_mps3": float("nan"),
            "trail_brake_ratio_median": float("nan"),
            "peak_brake_position_median": float("nan"),
            "n_braking_events": 0,
            "abrupt_event_frac": float("nan"),
            "no_trail_event_frac": float("nan"),
            "late_peak_event_frac": float("nan"),
        }

    ramp_rates: list[float] = []
    trail_ratios: list[float] = []
    peak_positions: list[float] = []

    for ev_start, ev_end in events:
        ax_event = ax[ev_start:ev_end]
        dt_event = dt[ev_start:ev_end]
        n_ev = len(ax_event)

        # ── 1. Ramp rate: d(ax)/dt from event start to peak decel ──
        peak_idx = int(np.argmin(ax_event))  # most negative = strongest braking
        if peak_idx > 0:
            # Time from event start to peak deceleration
            time_to_peak = float(np.sum(dt_event[:peak_idx]))
            if time_to_peak > 0.01:
                # Rate of deceleration onset [m/s³]
                ramp = abs(float(ax_event[peak_idx] - ax_event[0])) / time_to_peak
                ramp_rates.append(ramp)

        # ── 2. Trail-brake ratio: fraction of event after peak where
        #        deceleration is decreasing gradually ──
        if peak_idx < n_ev - 2:
            release_phase = ax_event[peak_idx:]
            # Trail-braking = deceleration magnitude decreasing (ax getting less negative)
            dax_release = np.diff(release_phase)
            n_release = len(dax_release)
            if n_release > 0:
                # Count samples where brake is being released (dax > 0 = less braking)
                trailing = float(np.mean(dax_release > 0.0))
                trail_ratios.append(trailing)

        # ── 3. Peak position: where in the event peak decel occurs ──
        peak_frac = float(peak_idx) / max(n_ev - 1, 1)
        peak_positions.append(peak_frac)

    ramp_arr = np.array(ramp_rates, dtype=float) if ramp_rates else np.array([float("nan")])
    trail_arr = np.array(trail_ratios, dtype=float) if trail_ratios else np.array([float("nan")])
    peak_arr = np.array(peak_positions, dtype=float) if peak_positions else np.array([float("nan")])

    n_events = len(events)

    # Fraction of events that are "abrupt" (ramp > 50 m/s³ ≈ 5g/s)
    abrupt_frac = float(np.mean(ramp_arr > 50.0)) if len(ramp_rates) > 0 else float("nan")
    # Fraction of events with no trail-braking (trail ratio < 0.3)
    no_trail_frac = float(np.mean(trail_arr < 0.30)) if len(trail_ratios) > 0 else float("nan")
    # Fraction of events with late peak (> 30% into braking zone)
    late_peak_frac = float(np.mean(peak_arr > 0.30)) if len(peak_positions) > 0 else float("nan")

    return {
        "brake_ramp_rate_median_mps3": float(np.nanmedian(ramp_arr)),
        "trail_brake_ratio_median": float(np.nanmedian(trail_arr)),
        "peak_brake_position_median": float(np.nanmedian(peak_arr)),
        "n_braking_events": n_events,
        "abrupt_event_frac": abrupt_frac,
        "no_trail_event_frac": no_trail_frac,
        "late_peak_event_frac": late_peak_frac,
    }


def _analyze_lap(
    lap_num: int,
    lap_df: pd.DataFrame,
    geometry: TrackGeometry,
    env: CapabilityEnvelope,
    corner_ref: dict[int, dict[str, float]],
    ref_distance: np.ndarray,
    ref_speed: np.ndarray,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    s, v, ax, ay, yaw, kappa, alt, t = _extract_arrays(lap_df, geometry)
    if len(s) < 20:
        return None, []

    ay_lim = np.maximum(np.asarray(env.lateral_max(v), dtype=float), 0.25)
    ax_drive_lim = np.maximum(np.asarray(env.traction_max(v), dtype=float), 0.25)
    ax_brake_lim = np.maximum(np.asarray(env.braking_max(v), dtype=float), 0.25)
    ax_lim = np.where(ax >= 0.0, ax_drive_lim, ax_brake_lim)
    ax_util = np.abs(ax) / ax_lim
    ay_util = np.abs(ay) / ay_lim
    p = float(max(getattr(env, "p_combined", 2.0), 1.0))
    gg_util = np.power(np.maximum(ax_util, 0.0) ** p + np.maximum(ay_util, 0.0) ** p, 1.0 / p)

    braking_mask = ax < -0.5
    coasting_mask = (np.abs(ax) < 0.35) & (ay_util < 0.35) & (v > 0.45 * _safe_percentile(v, 95))
    dt = _compute_dt(s, t, v)
    if len(ax) >= 3:
        dax = np.gradient(ax, edge_order=1)
        jerk = dax / np.maximum(dt, 1e-3)
    else:
        jerk = np.zeros_like(ax)
    lockup_mask = braking_mask & (ax_util > 1.02) & (ay_util < 0.30) & (np.abs(jerk) > 6.0)

    grade_pct = _estimate_grade_pct(s, alt)
    bank_deg = _estimate_bank_deg(v, ay, kappa)
    crest_mask = np.abs(grade_pct) > 4.0
    bank_mask = np.abs(bank_deg) > 2.0

    v_ref = np.interp(s, ref_distance, ref_speed, left=float(ref_speed[0]), right=float(ref_speed[-1]))
    crest_speed_loss = _safe_median(v_ref[crest_mask] - v[crest_mask]) if np.any(crest_mask) else 0.0
    bank_speed_loss = _safe_median(v_ref[bank_mask] - v[bank_mask]) if np.any(bank_mask) else 0.0

    corner_rows: list[dict[str, Any]] = []
    turn_deltas = []
    apex_deltas = []
    apex_speed_losses = []
    early_count = 0
    late_count = 0
    for corner_id, cref in corner_ref.items():
        s_start = cref["s_start"]
        s_end = cref["s_end"]
        s_apex_hint = cref["s_apex_ref"]
        turn_in = _estimate_turn_in_point(s, ay, s_start, s_apex_hint)
        apex_s, apex_v = _estimate_apex_point(s, v, s_start, s_end)
        turn_delta = float(turn_in - cref["turn_in_ref"])
        apex_delta = float(apex_s - cref["s_apex_ref"])
        apex_speed_loss = float(cref["v_apex_ref"] - apex_v)
        turn_deltas.append(turn_delta)
        apex_deltas.append(apex_delta)
        apex_speed_losses.append(apex_speed_loss)
        early_count += int(turn_delta < -1.5)
        late_count += int(turn_delta > 1.5)
        corner_rows.append({
            "lap_number": int(lap_num),
            "corner_id": int(corner_id),
            "turn_in_delta_m": round(turn_delta, 4),
            "apex_delta_m": round(apex_delta, 4),
            "apex_speed_loss_mps": round(apex_speed_loss, 4),
        })

    # Speed-dependent G-G utilization (trust deficit analysis)
    speed_gg = _analyze_speed_dependent_gg(v, gg_util, ay_util)

    # Brake modulation analysis (uses ax + dt only)
    brake_mod = _analyze_brake_modulation(s, ax, dt, ax_brake_lim)

    yaw_available = np.isfinite(yaw).sum() >= 20
    yaw_resid_std = float("nan")
    countersteer_rate = float("nan")
    oversteer_frac = float("nan")
    understeer_frac = float("nan")
    if yaw_available:
        yaw_expected = v * kappa * (180.0 / math.pi)
        yaw_residual = yaw - yaw_expected
        corner_mask = np.abs(kappa) > 0.003
        valid = np.isfinite(yaw_residual) & corner_mask
        if np.any(valid):
            yaw_resid_std = float(np.nanstd(yaw_residual[valid]))
            high = np.abs(yaw_residual[valid]) > 10.0
            lat_high = ay_util[valid] > 0.60
            sig_src = yaw_residual[valid][high & lat_high]
            sig = np.sign(sig_src)
            cross_idx = np.where((sig[1:] * sig[:-1]) < 0)[0] + 1 if len(sig) >= 2 else np.array([], dtype=int)
            if len(cross_idx) > 0:
                kept = [int(cross_idx[0])]
                for idx_raw in cross_idx[1:]:
                    if int(idx_raw) - kept[-1] >= 8:
                        kept.append(int(idx_raw))
                counter_events = len(kept)
            else:
                counter_events = 0
            lap_km = max(float((s[-1] - s[0]) / 1000.0), 0.1)
            countersteer_rate = float(counter_events / lap_km)
            yaw_exp_v = yaw_expected[valid]
            yaw_res_v = yaw_residual[valid]
            strong = np.abs(yaw_res_v) > 8.0
            if np.any(strong):
                oversteer_frac = float(np.mean((yaw_exp_v * yaw_res_v > 0.0) & strong))
                understeer_frac = float(np.mean((yaw_exp_v * yaw_res_v < 0.0) & strong))

    row = {
        "lap_number": int(lap_num),
        "lap_time_s": float(np.nansum(dt)),
        "gg_util_median": _safe_median(gg_util),
        "gg_util_p90": _safe_percentile(gg_util, 90),
        "gg_util_std": float(np.nanstd(gg_util)),
        "gg_under_frac": float(np.nanmean(gg_util < 0.65)),
        "gg_over_frac": float(np.nanmean(gg_util > 1.05)),
        "gg_near_limit_frac": float(np.nanmean(gg_util > 0.90)),
        "coast_frac": float(np.nanmean(coasting_mask)),
        "brake_util_p90": _safe_percentile(np.abs(ax[braking_mask]) / np.maximum(ax_brake_lim[braking_mask], 0.25), 90)
        if np.any(braking_mask) else float("nan"),
        "brake_util_p95": _safe_percentile(np.abs(ax[braking_mask]) / np.maximum(ax_brake_lim[braking_mask], 0.25), 95)
        if np.any(braking_mask) else float("nan"),
        "brake_g_p90": _safe_percentile(np.abs(ax[braking_mask]) / _G, 90) if np.any(braking_mask) else float("nan"),
        "lockup_frac": float(np.nanmean(lockup_mask)),
        "turn_in_delta_median_m": _safe_median(np.asarray(turn_deltas, dtype=float)),
        "turn_in_early_frac": float(early_count / max(len(turn_deltas), 1)),
        "turn_in_late_frac": float(late_count / max(len(turn_deltas), 1)),
        "apex_delta_median_m": _safe_median(np.asarray(apex_deltas, dtype=float)),
        "apex_speed_loss_mean_mps": _safe_mean(np.asarray(apex_speed_losses, dtype=float)),
        "crest_speed_loss_mps": float(crest_speed_loss),
        "bank_speed_loss_mps": float(bank_speed_loss),
        "crest_frac": float(np.nanmean(crest_mask)),
        "bank_frac": float(np.nanmean(bank_mask)),
        "yaw_available": bool(yaw_available),
        "yaw_resid_std": yaw_resid_std,
        "countersteer_events_per_km": countersteer_rate,
        "oversteer_frac": oversteer_frac,
        "understeer_frac": understeer_frac,
        # Speed-dependent G-G metrics
        "gg_util_low_speed": speed_gg["gg_util_low_speed"],
        "gg_util_mid_speed": speed_gg["gg_util_mid_speed"],
        "gg_util_high_speed": speed_gg["gg_util_high_speed"],
        "gg_drop_low_to_high": speed_gg["gg_drop_low_to_high"],
        "ay_util_low_speed": speed_gg["ay_util_low_speed"],
        "ay_util_high_speed": speed_gg["ay_util_high_speed"],
        # Brake modulation metrics
        "brake_ramp_rate_median_mps3": brake_mod["brake_ramp_rate_median_mps3"],
        "trail_brake_ratio_median": brake_mod["trail_brake_ratio_median"],
        "peak_brake_position_median": brake_mod["peak_brake_position_median"],
        "n_braking_events": brake_mod["n_braking_events"],
        "abrupt_event_frac": brake_mod["abrupt_event_frac"],
        "no_trail_event_frac": brake_mod["no_trail_event_frac"],
        "late_peak_event_frac": brake_mod["late_peak_event_frac"],
    }
    return row, corner_rows

def _classify_findings(
    lap_metrics_df: pd.DataFrame,
    corner_rows: list[dict[str, Any]],
    ml_summary: dict[str, Any],
    thresholds: DiagnosticThresholds | None = None,
) -> tuple[list[DiagnosticFinding], dict[str, Any], dict[str, Any]]:
    findings: list[DiagnosticFinding] = []
    th = thresholds or DiagnosticThresholds()

    m = _aggregate_metrics(lap_metrics_df)
    outlier_frac = float(ml_summary.get("outlier_fraction", 0.0))

    under_score = np.clip(
        0.45 * max(0.0, th.gg_under_threshold - m["gg_util_p90"]) / 0.35 +
        0.25 * m["gg_under_frac"] / 0.70 +
        0.30 * m["coast_frac"] / max(th.coast_frac_threshold * 3, 0.10),
        0.0, 1.0,
    )
    if under_score >= 0.45 and m["gg_over_frac"] < 0.08:
        findings.append(_make_finding(
            code="underdriving",
            title="Underdriving",
            score=under_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"G-G p90 utilization {m['gg_util_p90']:.2f}, under-limit share "
                f"{m['gg_under_frac']:.2%}, coasting {m['coast_frac']:.2%}."
            ),
            recommendation="Lean on grip earlier in corner entry and reduce long coasting phases.",
        ))

    over_score = np.clip(
        0.35 * m["gg_over_frac"] / 0.15 +
        0.25 * m["gg_util_std"] / 0.35 +
        0.20 * m["gg_under_frac"] / 0.60 +
        0.20 * outlier_frac / 0.25,
        0.0, 1.0,
    )
    if over_score >= 0.45 and m["gg_over_frac"] >= th.gg_over_threshold:
        findings.append(_make_finding(
            code="overdriving",
            title="Overdriving / inconsistency",
            score=over_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"Over-limit share {m['gg_over_frac']:.2%}, utilization std {m['gg_util_std']:.3f}, "
                f"lap outlier fraction {outlier_frac:.2%}."
            ),
            recommendation="Stabilize entry speed and avoid alternating over-attack and lift laps.",
        ))

    if np.isfinite(m["brake_util_p90"]):
        under_brake_score = float(np.clip((th.underbrake_threshold - m["brake_util_p90"]) / 0.28, 0.0, 1.0))
        if under_brake_score >= 0.40:
            findings.append(_make_finding(
                code="underbraking",
                title="Underbraking",
                score=under_brake_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=f"Brake utilization p90 is {m['brake_util_p90']:.2f} of expected capacity.",
                recommendation="Push peak brake pressure later and closer to expected decel capacity.",
            ))

        over_brake_score = float(np.clip(
            0.6 * m["lockup_frac"] / th.overbrake_lockup_frac +
            0.4 * max(0.0, m["brake_util_p95"] - 1.0) / 0.20,
            0.0, 1.0,
        ))
        if over_brake_score >= 0.40:
            findings.append(_make_finding(
                code="overbraking",
                title="Overbraking / lock-up proxy",
                score=over_brake_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"Lock-up proxy share {m['lockup_frac']:.2%}, brake utilization p95 "
                    f"{m['brake_util_p95']:.2f}."
                ),
                recommendation="Soften initial brake spike and bias release smoother into turn-in.",
            ))

    # ── Brake modulation findings (from accelerometer data) ──
    abrupt_frac = m.get("abrupt_event_frac", float("nan"))
    trail_ratio = m.get("trail_brake_ratio_median", float("nan"))
    no_trail_frac = m.get("no_trail_event_frac", float("nan"))
    peak_pos = m.get("peak_brake_position_median", float("nan"))
    late_peak_frac = m.get("late_peak_event_frac", float("nan"))
    ramp_rate = m.get("brake_ramp_rate_median_mps3", float("nan"))

    if np.isfinite(abrupt_frac) and np.isfinite(ramp_rate):
        abrupt_score = float(np.clip(
            0.55 * min(abrupt_frac / 0.40, 1.0) +
            0.45 * min(max(ramp_rate - (th.abrupt_ramp_threshold_mps3 * 0.6), 0.0) /
                       (th.abrupt_ramp_threshold_mps3 * 0.8), 1.0),
            0.0, 1.0,
        ))
        if abrupt_score >= 0.40:
            findings.append(_make_finding(
                code="abrupt_braking",
                title="Abrupt brake application",
                score=abrupt_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"Brake ramp rate {ramp_rate:.1f} m/s³, "
                    f"{abrupt_frac:.0%} of braking events are abrupt (>50 m/s³)."
                ),
                recommendation=(
                    "Squeeze the brake progressively — ramp to peak over 0.1-0.15s "
                    "instead of stomping. This prevents lockup and allows trail-braking."
                ),
            ))

    if np.isfinite(no_trail_frac) and np.isfinite(trail_ratio):
        trail_ref = th.trail_ratio_threshold + 0.10  # expect slightly above threshold
        no_trail_score = float(np.clip(
            0.55 * min(no_trail_frac / 0.50, 1.0) +
            0.45 * max(0.0, (trail_ref - trail_ratio) / 0.30),
            0.0, 1.0,
        ))
        if no_trail_score >= 0.40:
            findings.append(_make_finding(
                code="trailing_brake_absent",
                title="Missing trail-braking",
                score=no_trail_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"Trail-brake ratio {trail_ratio:.2f} (low), "
                    f"{no_trail_frac:.0%} of events have no gradual release."
                ),
                recommendation=(
                    "Release brake pressure gradually as you turn in — don't "
                    "release all at once. Trail-braking rotates the car and "
                    "carries more speed through the entry phase."
                ),
            ))

    if np.isfinite(late_peak_frac) and np.isfinite(peak_pos):
        late_peak_score = float(np.clip(
            0.55 * min(late_peak_frac / 0.50, 1.0) +
            0.45 * min(max(peak_pos - 0.20, 0.0) / 0.25, 1.0),
            0.0, 1.0,
        ))
        if late_peak_score >= 0.40:
            findings.append(_make_finding(
                code="late_peak_brake",
                title="Late peak braking",
                score=late_peak_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"Peak deceleration at {peak_pos:.0%} into braking zone, "
                    f"{late_peak_frac:.0%} of events have late peak (>30%)."
                ),
                recommendation=(
                    "Hit peak brake pressure within the first 15-20% of the "
                    "braking zone. Late peak means you're building pressure "
                    "too slowly and extending the braking distance."
                ),
            ))

    coast_score = float(np.clip((m["coast_frac"] - th.coast_frac_threshold) / 0.20, 0.0, 1.0))
    if coast_score >= 0.35:
        findings.append(_make_finding(
            code="coasting",
            title="Excess coasting",
            score=coast_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=f"Coasting share is {m['coast_frac']:.2%} of lap samples.",
            recommendation="Replace coast windows with decisive brake-to-rotation or early throttle.",
        ))

    early_turn = m["turn_in_early_frac"] > 0.60 and m["turn_in_delta_median_m"] < -1.5
    late_turn = m["turn_in_late_frac"] > 0.60 and m["turn_in_delta_median_m"] > 1.5
    if early_turn or late_turn:
        early_late = "early" if early_turn else "late"
        line_score = float(np.clip(
            0.6 * max(m["turn_in_early_frac"], m["turn_in_late_frac"]) +
            0.4 * min(abs(m["turn_in_delta_median_m"]) / 4.0, 1.0),
            0.0, 1.0,
        ))
        findings.append(_make_finding(
            code=f"line_turn_in_{early_late}",
            title=f"Recurrent {early_late} turn-in line",
            score=line_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"Median turn-in delta {m['turn_in_delta_median_m']:.2f} m, "
                f"early fraction {m['turn_in_early_frac']:.2%}, late fraction {m['turn_in_late_frac']:.2%}."
            ),
            recommendation="Re-anchor turn-in marker and validate with corner-by-corner replay.",
        ))

    if abs(m["apex_delta_median_m"]) > 1.5 and m["apex_speed_loss_mean_mps"] > 0.20:
        apex_score = float(np.clip(
            0.5 * min(abs(m["apex_delta_median_m"]) / 4.0, 1.0) +
            0.5 * min(m["apex_speed_loss_mean_mps"] / 0.9, 1.0),
            0.0, 1.0,
        ))
        findings.append(_make_finding(
            code="apex_timing",
            title="Apex timing inefficiency",
            score=apex_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"Median apex shift {m['apex_delta_median_m']:.2f} m, "
                f"apex speed loss {m['apex_speed_loss_mean_mps']:.2f} m/s."
            ),
            recommendation="Tune apex target and prioritize exit speed over entry aggression.",
        ))

    crest_bank_score = float(np.clip(
        0.6 * min(max(m["crest_speed_loss_mps"], 0.0) / 1.0, 1.0) +
        0.4 * min(max(m["bank_speed_loss_mps"], 0.0) / 0.8, 1.0),
        0.0, 1.0,
    ))
    if crest_bank_score >= 0.35 and (m["crest_frac"] > 0.02 or m["bank_frac"] > 0.02):
        findings.append(_make_finding(
            code="crest_banking_sensitivity",
            title="Crest / banking sensitivity",
            score=crest_bank_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"Crest speed loss {m['crest_speed_loss_mps']:.2f} m/s, "
                f"banking speed loss {m['bank_speed_loss_mps']:.2f} m/s."
            ),
            recommendation="Adapt line and release phase over grade/bank transitions to keep load stable.",
        ))

    # ── Speed-dependent trust deficit ──
    gg_drop = m.get("gg_drop_low_to_high", float("nan"))
    gg_lo_spd = m.get("gg_util_low_speed", float("nan"))
    gg_hi_spd = m.get("gg_util_high_speed", float("nan"))
    if np.isfinite(gg_drop) and np.isfinite(gg_lo_spd) and np.isfinite(gg_hi_spd):
        # Trust deficit = how much grip utilization drops from low to high speed
        # A drop of 0.15+ (e.g., 0.92 → 0.77) is significant
        trust_score = float(np.clip(
            0.55 * min(max(gg_drop, 0.0) / 0.20, 1.0) +
            0.45 * min(max(gg_lo_spd - gg_hi_spd, 0.0) / 0.25, 1.0),
            0.0, 1.0,
        ))
        if trust_score >= 0.40 and gg_drop > th.trust_drop_threshold:
            findings.append(_make_finding(
                code="speed_dependent_trust_deficit",
                title="Speed-dependent trust deficit",
                score=trust_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"G-G utilization drops from {gg_lo_spd:.2f} (low speed) to "
                    f"{gg_hi_spd:.2f} (high speed) — a {gg_drop:.2f} drop. "
                    f"You use less of the car's grip as speed increases."
                ),
                recommendation=(
                    "Your car has the same grip at high speed as low speed "
                    "(potentially more with downforce). Build high-speed "
                    "confidence gradually: carry 1-2 km/h more each session "
                    "through fast corners. Focus on smooth inputs — the car "
                    "can handle it."
                ),
            ))

    yaw_summary = {
        "yaw_available": bool(m["yaw_available"]),
        "yaw_resid_std": round(m["yaw_resid_std"], 4) if np.isfinite(m["yaw_resid_std"]) else None,
        "countersteer_events_per_km": (
            round(m["countersteer_events_per_km"], 4)
            if np.isfinite(m["countersteer_events_per_km"]) else None
        ),
        "oversteer_frac": round(m["oversteer_frac"], 4) if np.isfinite(m["oversteer_frac"]) else None,
        "understeer_frac": round(m["understeer_frac"], 4) if np.isfinite(m["understeer_frac"]) else None,
    }
    if m["yaw_available"]:
        yaw_score = float(np.clip(
            0.45 * min(max(m["countersteer_events_per_km"], 0.0) / 12.0, 1.0) +
            0.30 * min(max(m["oversteer_frac"], 0.0) / 0.20, 1.0) +
            0.25 * min(max(m["yaw_resid_std"], 0.0) / 18.0, 1.0),
            0.0, 1.0,
        ))
        if yaw_score >= 0.40:
            findings.append(_make_finding(
                code="yaw_countersteer_instability",
                title="Yaw / countersteer instability",
                score=yaw_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"Countersteer events {m['countersteer_events_per_km']:.2f}/km, "
                    f"yaw residual std {m['yaw_resid_std']:.2f} deg/s."
                ),
                recommendation="Reduce steering correction spikes; keep rotation smoother at peak lateral load.",
            ))

    consistency_score = float(np.clip(
        0.5 * outlier_frac / 0.25 +
        0.5 * min(np.nanstd(lap_metrics_df["lap_time_s"].to_numpy()) / th.lap_time_std_threshold, 1.0),
        0.0, 1.0,
    ))
    if consistency_score >= 0.45:
        findings.append(_make_finding(
            code="execution_inconsistency",
            title="Execution inconsistency",
            score=consistency_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"ML outlier laps {outlier_frac:.2%}, lap-time std "
                f"{float(np.nanstd(lap_metrics_df['lap_time_s'].to_numpy())):.3f} s."
            ),
            recommendation="Aim for repeatable brake release and same reference points lap-to-lap.",
        ))

    # Additional recurrent patterns for richer coaching classification.
    brake_var = float(np.nanstd(pd.to_numeric(lap_metrics_df["brake_util_p90"], errors="coerce").to_numpy(dtype=float)))
    coast_var = float(np.nanstd(pd.to_numeric(lap_metrics_df["coast_frac"], errors="coerce").to_numpy(dtype=float)))
    apex_loss_p90 = _safe_percentile(
        pd.to_numeric(lap_metrics_df["apex_speed_loss_mean_mps"], errors="coerce").to_numpy(dtype=float),
        90,
    )

    line_mix_score = float(np.clip(
        0.55 * min(m["turn_in_early_frac"] + m["turn_in_late_frac"], 1.0) +
        0.45 * min(outlier_frac / 0.22, 1.0),
        0.0, 1.0,
    ))
    if (
        line_mix_score >= 0.40
        and m["turn_in_early_frac"] > 0.22
        and m["turn_in_late_frac"] > 0.22
    ):
        findings.append(_make_finding(
            code="line_inconsistency",
            title="Inconsistent turn-in references",
            score=line_mix_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"Early turn-in {m['turn_in_early_frac']:.2%}, late turn-in "
                f"{m['turn_in_late_frac']:.2%}, outlier laps {outlier_frac:.2%}."
            ),
            recommendation="Lock one entry marker per corner and avoid lap-to-lap line drift.",
        ))

    if np.isfinite(brake_var):
        brake_var_score = float(np.clip(brake_var / 0.22, 0.0, 1.0))
        if brake_var_score >= 0.40:
            findings.append(_make_finding(
                code="brake_variability",
                title="Brake pressure variability",
                score=brake_var_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=f"Brake-utilization variability is high (std {brake_var:.3f}).",
                recommendation="Stabilize pedal build-up and release to repeat entry balance.",
            ))

    hesitation_score = float(np.clip(
        0.5 * max(m["coast_frac"] - 0.10, 0.0) / 0.20 +
        0.5 * max(m["gg_under_frac"] - 0.45, 0.0) / 0.40,
        0.0, 1.0,
    ))
    if hesitation_score >= 0.40 and np.isfinite(coast_var):
        findings.append(_make_finding(
            code="entry_hesitation",
            title="Entry hesitation",
            score=hesitation_score,
            confidence=_confidence(len(lap_metrics_df)),
            evidence=(
                f"Coast share {m['coast_frac']:.2%} (std {coast_var:.3f}), "
                f"under-limit share {m['gg_under_frac']:.2%}."
            ),
            recommendation="Replace hesitation windows with a cleaner brake-to-turn transition.",
        ))

    if np.isfinite(apex_loss_p90):
        apex_exit_score = float(np.clip(
            0.6 * min(max(apex_loss_p90, 0.0) / 1.2, 1.0) +
            0.4 * min(m["coast_frac"] / 0.20, 1.0),
            0.0, 1.0,
        ))
        if apex_exit_score >= 0.40:
            findings.append(_make_finding(
                code="poor_apex_exit_carry",
                title="Poor apex-to-exit speed carry",
                score=apex_exit_score,
                confidence=_confidence(len(lap_metrics_df)),
                evidence=(
                    f"Apex speed-loss p90 {apex_loss_p90:.2f} m/s, "
                    f"coasting {m['coast_frac']:.2%}."
                ),
                recommendation="Delay minimum speed slightly and prioritize earlier progressive throttle.",
            ))

    metrics = _json_safe_dict(m)
    metrics["n_laps_used"] = int(len(lap_metrics_df))
    metrics["n_corner_samples"] = int(len(corner_rows))
    metrics["brake_util_variability_std"] = brake_var if np.isfinite(brake_var) else None
    metrics["coast_variability_std"] = coast_var if np.isfinite(coast_var) else None
    metrics["apex_speed_loss_p90_mps"] = apex_loss_p90 if np.isfinite(apex_loss_p90) else None
    metrics["vehicle_class"] = th.vehicle_class
    return findings, metrics, yaw_summary


def _lap_outlier_model(lap_metrics_df: pd.DataFrame) -> dict[str, Any]:
    feature_cols = [
        "gg_util_median",
        "gg_util_p90",
        "gg_util_std",
        "gg_under_frac",
        "gg_over_frac",
        "coast_frac",
        "brake_util_p90",
        "lockup_frac",
        "turn_in_delta_median_m",
        "apex_delta_median_m",
        "apex_speed_loss_mean_mps",
    ]
    x = lap_metrics_df[feature_cols].apply(pd.to_numeric, errors="coerce")
    valid_idx = x.dropna().index
    if len(valid_idx) < 8 or IsolationForest is None:
        return {
            "enabled": False,
            "method": "isolation_forest",
            "reason": "insufficient_samples_or_missing_sklearn",
            "outlier_fraction": 0.0,
            "outlier_laps": [],
        }

    xv = x.loc[valid_idx].to_numpy(dtype=float)
    contamination = float(np.clip(max(0.08, 2.0 / len(valid_idx)), 0.08, 0.30))
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
    )
    pred = model.fit_predict(xv)
    out_mask = pred == -1
    out_idx = valid_idx[out_mask]
    out_laps = sorted(lap_metrics_df.loc[out_idx, "lap_number"].astype(int).tolist())
    return {
        "enabled": True,
        "method": "isolation_forest",
        "n_laps": int(len(valid_idx)),
        "outlier_fraction": float(np.mean(out_mask)),
        "outlier_laps": out_laps,
        "contamination": contamination,
    }


def _aggregate_metrics(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in df.columns:
        if c in {"lap_number", "yaw_available"}:
            continue
        vals = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        out[c] = float(np.nanmedian(vals)) if np.isfinite(vals).any() else float("nan")
    out["yaw_available"] = bool(np.nanmean(df.get("yaw_available", pd.Series([0])).astype(float)) > 0.5)
    out["turn_in_early_frac"] = _nanmean_series(df["turn_in_early_frac"])
    out["turn_in_late_frac"] = _nanmean_series(df["turn_in_late_frac"])
    out["coast_frac"] = _nanmean_series(df["coast_frac"])
    out["gg_under_frac"] = _nanmean_series(df["gg_under_frac"])
    out["gg_over_frac"] = _nanmean_series(df["gg_over_frac"])
    out["gg_near_limit_frac"] = _nanmean_series(df["gg_near_limit_frac"])
    out["lockup_frac"] = _nanmean_series(df["lockup_frac"])
    out["oversteer_frac"] = _nanmean_series(df["oversteer_frac"])
    out["understeer_frac"] = _nanmean_series(df["understeer_frac"])
    return out

def _extract_arrays(
    lap_df: pd.DataFrame,
    geometry: TrackGeometry,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    s = pd.to_numeric(lap_df.get(COL_DIST), errors="coerce").to_numpy(dtype=float)
    v = pd.to_numeric(lap_df.get(COL_SPEED), errors="coerce").to_numpy(dtype=float)
    t = pd.to_numeric(lap_df.get(COL_TIME), errors="coerce").to_numpy(dtype=float) if COL_TIME in lap_df.columns else np.full(len(s), np.nan)
    ax = pd.to_numeric(lap_df.get(COL_ACCEL_LONG), errors="coerce").to_numpy(dtype=float) if COL_ACCEL_LONG in lap_df.columns else np.full(len(s), np.nan)
    ay = pd.to_numeric(lap_df.get(COL_ACCEL_LAT), errors="coerce").to_numpy(dtype=float) if COL_ACCEL_LAT in lap_df.columns else np.full(len(s), np.nan)
    yaw = pd.to_numeric(lap_df.get(COL_YAW_RATE), errors="coerce").to_numpy(dtype=float) if COL_YAW_RATE in lap_df.columns else np.full(len(s), np.nan)
    alt = pd.to_numeric(lap_df.get(COL_ALTITUDE), errors="coerce").to_numpy(dtype=float) if COL_ALTITUDE in lap_df.columns else np.full(len(s), np.nan)

    valid = np.isfinite(s) & np.isfinite(v)
    if np.sum(valid) < 3:
        return (
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
        )
    s = s[valid]
    v = np.maximum(v[valid], 0.5)
    t = t[valid]
    ax = ax[valid]
    ay = ay[valid]
    yaw = yaw[valid]
    alt = alt[valid]

    order = np.argsort(s)
    s = s[order]
    v = v[order]
    t = t[order]
    ax = ax[order]
    ay = ay[order]
    yaw = yaw[order]
    alt = alt[order]
    s, keep = np.unique(s, return_index=True)
    v = v[keep]
    t = t[keep]
    ax = ax[keep]
    ay = ay[keep]
    yaw = yaw[keep]
    alt = alt[keep]

    kappa = np.interp(s, geometry.distance_m, geometry.curvature_1pm, left=0.0, right=0.0)
    if not np.isfinite(ax).any():
        dt = _compute_dt(s, t, v)
        ax = np.gradient(v, dt, edge_order=1) if len(v) >= 3 else np.zeros_like(v)
    if not np.isfinite(ay).any():
        ay = (v * v) * np.abs(kappa)

    ax = np.where(np.isfinite(ax), ax, 0.0)
    ay = np.where(np.isfinite(ay), ay, 0.0)
    return s, v, ax, ay, yaw, kappa, alt, t


def _compute_dt(s: np.ndarray, t: np.ndarray, v: np.ndarray) -> np.ndarray:
    if len(s) < 2:
        return np.array([1.0], dtype=float)
    if np.isfinite(t).sum() >= 3:
        dt = np.diff(t)
        dt = np.where(np.isfinite(dt) & (dt > 1e-4), dt, np.nan)
        if np.isfinite(dt).sum() >= 1:
            med = float(np.nanmedian(dt))
            dt = np.where(np.isfinite(dt), dt, med)
            return np.append(dt, dt[-1])
    ds = np.diff(s)
    v_mid = np.maximum(0.5 * (v[:-1] + v[1:]), 0.5)
    dt = ds / v_mid
    dt = np.where(np.isfinite(dt) & (dt > 1e-4), dt, np.nanmedian(dt[np.isfinite(dt)]))
    return np.append(dt, dt[-1])


def _estimate_grade_pct(s: np.ndarray, alt: np.ndarray) -> np.ndarray:
    if len(s) < 3 or np.isfinite(alt).sum() < 3:
        return np.zeros_like(s)
    a = np.asarray(alt, dtype=float).copy()
    idx = np.arange(len(a))
    m = np.isfinite(a)
    a[~m] = np.interp(idx[~m], idx[m], a[m])
    ds = np.diff(s)
    dz = np.diff(a)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = np.where(ds > 0.1, 100.0 * dz / ds, 0.0)
    g = np.append(g[0] if len(g) else 0.0, g)
    if len(g) >= 5:
        kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0], dtype=float)
        kernel /= kernel.sum()
        g = np.convolve(np.pad(g, (2, 2), mode="edge"), kernel, mode="valid")
    return np.clip(g, -30.0, 30.0)


def _estimate_bank_deg(v: np.ndarray, ay: np.ndarray, kappa: np.ndarray) -> np.ndarray:
    if len(v) == 0:
        return np.array([], dtype=float)
    expected = np.abs(v * v * kappa)
    residual = np.abs(ay) - expected
    ratio = np.clip(residual / _G, -0.26, 0.26)
    return np.degrees(np.arcsin(ratio))


def _estimate_turn_in_point(
    s: np.ndarray,
    ay: np.ndarray,
    s_start: float,
    s_apex: float,
) -> float:
    if len(s) == 0:
        return s_start
    mask = (s >= (s_start - 20.0)) & (s <= max(s_apex, s_start + 1.0))
    if not np.any(mask):
        return s_start
    s_zone = s[mask]
    ay_zone = np.abs(ay[mask])
    if len(ay_zone) == 0 or not np.isfinite(ay_zone).any():
        return s_start
    threshold = max(1.0, 0.35 * _safe_percentile(ay_zone, 90))
    idx = np.where(ay_zone >= threshold)[0]
    if len(idx) == 0:
        return s_start
    return float(s_zone[idx[0]])


def _estimate_apex_point(
    s: np.ndarray,
    v: np.ndarray,
    s_start: float,
    s_end: float,
) -> tuple[float, float]:
    mask = (s >= s_start) & (s <= s_end)
    if not np.any(mask):
        return float(s_start), _safe_percentile(v, 20)
    s_zone = s[mask]
    v_zone = v[mask]
    idx = int(np.nanargmin(v_zone))
    return float(s_zone[idx]), float(v_zone[idx])


def _make_finding(
    code: str,
    title: str,
    score: float,
    confidence: float,
    evidence: str,
    recommendation: str,
) -> DiagnosticFinding:
    if score >= 0.80:
        severity = "critical"
    elif score >= 0.60:
        severity = "high"
    elif score >= 0.40:
        severity = "medium"
    else:
        severity = "low"
    return DiagnosticFinding(
        code=code,
        title=title,
        severity=severity,
        score=float(score),
        confidence=float(confidence),
        evidence=evidence,
        recommendation=recommendation,
    )


def _confidence(n_laps: int) -> float:
    return float(np.clip((n_laps - 2) / 10.0, 0.25, 0.95))


def _safe_percentile(values: np.ndarray, p: float) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    return float(np.percentile(arr, p))


def _safe_mean(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    return float(np.mean(arr))


def _safe_median(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    return float(np.median(arr))


def _nanmean_series(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return float("nan")
    return float(np.mean(vals))


def _json_safe_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (np.floating, np.float32, np.float64)):
            out[k] = None if not np.isfinite(float(v)) else float(v)
        elif isinstance(v, (np.integer, np.int32, np.int64)):
            out[k] = int(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        else:
            out[k] = v
    return out
