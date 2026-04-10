"""
corner_coaching_aggregate.py
----------------------------
Per-corner aggregate coaching: computes proven limits from the track
surface, classifies root causes, and generates narrative coaching text.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.80665
_BRAKE_THRESHOLD_G = 0.3
_BRAKE_SEARCH_M = 80


@dataclass
class CornerProven:
    """Proven limits for one corner from aggregate data."""
    corner_id: int
    entry_kph: float
    apex_kph: float
    exit_kph: float
    brake_point_m: float | None

    def to_dict(self) -> dict:
        return {
            "entry_kph": round(self.entry_kph, 1),
            "apex_kph": round(self.apex_kph, 1),
            "exit_kph": round(self.exit_kph, 1),
            "brake_point_m": round(self.brake_point_m, 1) if self.brake_point_m else None,
        }


@dataclass
class CornerActual:
    """Actual performance for one corner from this session."""
    corner_id: int
    entry_kph: float
    apex_kph: float
    exit_kph: float
    brake_point_m: float | None

    def to_dict(self) -> dict:
        return {
            "entry_kph": round(self.entry_kph, 1),
            "apex_kph": round(self.apex_kph, 1),
            "exit_kph": round(self.exit_kph, 1),
            "brake_point_m": round(self.brake_point_m, 1) if self.brake_point_m else None,
        }


def _speed_at_grip(mu: float, kappa: float) -> float:
    """v_kph = sqrt(mu * g / kappa) * 3.6, capped at 360kph."""
    if kappa < 1e-6:
        return 100.0 * 3.6
    v_mps = math.sqrt(mu * _G / kappa)
    return min(v_mps * 3.6, 360.0)


def compute_proven_limits(aggregate_grip, corners: list[dict]) -> list[CornerProven]:
    """Compute proven entry/apex/exit speeds from aggregate grip + curvature."""
    results = []
    for c in corners:
        cid = c.get("corner_id", 0)
        s_start = c.get("s_start", 0.0)
        s_apex = c.get("s_apex", s_start)
        s_end = c.get("s_end", s_apex)
        kappa = abs(c.get("curvature_1pm", 0.01))
        kappa = max(kappa, 1e-4)

        mu_entry = aggregate_grip.mu_at(s_start, "p95")
        mu_apex = aggregate_grip.mu_at(s_apex, "p95")
        mu_exit = aggregate_grip.mu_at(s_end, "p95")

        kappa_entry = kappa * 0.4
        kappa_exit = kappa * 0.6

        entry_kph = _speed_at_grip(mu_entry, kappa_entry)
        apex_kph = _speed_at_grip(mu_apex, kappa)
        exit_kph = _speed_at_grip(mu_exit, kappa_exit)

        results.append(CornerProven(
            corner_id=cid, entry_kph=entry_kph, apex_kph=apex_kph,
            exit_kph=exit_kph, brake_point_m=None,
        ))
    return results


def compute_actual_metrics(
    distances: np.ndarray, speeds_mps: np.ndarray,
    accel_mps2: np.ndarray, corners: list[dict],
) -> list[CornerActual]:
    """Extract actual entry/apex/exit speeds and brake points."""
    results = []
    for c in corners:
        cid = c.get("corner_id", 0)
        s_start = c.get("s_start", 0.0)
        s_apex = c.get("s_apex", s_start)
        s_end = c.get("s_end", s_apex)

        entry_kph = float(np.interp(s_start, distances, speeds_mps)) * 3.6
        apex_kph = float(np.interp(s_apex, distances, speeds_mps)) * 3.6
        exit_kph = float(np.interp(s_end, distances, speeds_mps)) * 3.6

        brake_point = None
        search_start = s_start - _BRAKE_SEARCH_M
        pre_mask = (distances >= search_start) & (distances < s_start)
        if pre_mask.any():
            pre_dist = distances[pre_mask]
            pre_accel = accel_mps2[pre_mask]
            braking = pre_accel < -(_BRAKE_THRESHOLD_G * _G)
            if braking.any():
                first_brake_idx = np.argmax(braking)
                brake_point = float(pre_dist[first_brake_idx])

        results.append(CornerActual(
            corner_id=cid, entry_kph=entry_kph, apex_kph=apex_kph,
            exit_kph=exit_kph, brake_point_m=brake_point,
        ))
    return results


def classify_root_cause(
    proven: CornerProven, actual: CornerActual, *,
    handling_events: list[str] | None = None,
    grip_headroom_pct: float = 0.0,
) -> list[str]:
    """Classify root causes of time loss at a corner."""
    causes: list[str] = []
    events = handling_events or []

    if proven.brake_point_m is not None and actual.brake_point_m is not None:
        brake_delta = actual.brake_point_m - proven.brake_point_m
        if brake_delta < -3:
            causes.append("early_brake")
        elif brake_delta > 3:
            causes.append("late_brake")

    entry_excess = actual.entry_kph - proven.entry_kph
    if entry_excess > 3 and any(e in events for e in ("understeer", "oversteer")):
        causes.append("entry_too_hot")

    apex_delta = proven.apex_kph - actual.apex_kph
    if apex_delta > 2 and entry_excess < 3:
        causes.append("apex_deficit")

    exit_delta = proven.exit_kph - actual.exit_kph
    if exit_delta > 3 and grip_headroom_pct > 10 and not any(
        e in events for e in ("oversteer", "understeer")
    ):
        causes.append("exit_under_application")

    return causes


def compute_time_loss(
    distances: np.ndarray, v_actual_mps: np.ndarray, v_proven_mps: np.ndarray,
) -> float:
    """Time loss integral. Positive = driver slower than proven."""
    v_a = np.maximum(v_actual_mps, 1.0)
    v_p = np.maximum(v_proven_mps, 1.0)
    ds = np.diff(distances)
    dt_actual = ds / v_a[:-1]
    dt_proven = ds / v_p[:-1]
    return float(np.sum(dt_actual - dt_proven))


def generate_narrative(
    corner_name: str, direction: str,
    proven: CornerProven, actual: CornerActual,
    causes: list[str], n_sessions: int, time_loss_s: float,
) -> str:
    """Generate coaching narrative from template based on root causes."""
    if not causes or time_loss_s < 0.02:
        return (
            f"{corner_name} looks clean — you're within "
            f"{abs(proven.apex_kph - actual.apex_kph):.0f}kph of the "
            f"proven apex speed across {n_sessions} sessions."
        )

    primary = causes[0]

    if primary == "early_brake":
        delta = abs((actual.brake_point_m or 0) - (proven.brake_point_m or 0))
        return (
            f"You're braking {delta:.0f}m too early for {corner_name}. "
            f"The track supports {proven.apex_kph:.0f}kph at the apex across "
            f"{n_sessions} sessions — you have margin to brake at the "
            f"{proven.brake_point_m:.0f}m mark instead of {actual.brake_point_m:.0f}m. "
            f"This costs {time_loss_s:.2f}s per lap."
        )
    elif primary == "late_brake":
        delta = abs((actual.brake_point_m or 0) - (proven.brake_point_m or 0))
        return (
            f"You're braking {delta:.0f}m too late for {corner_name}, "
            f"overshooting the apex. "
            f"Brake at {proven.brake_point_m:.0f}m to set up a "
            f"{proven.apex_kph:.0f}kph apex. "
            f"This costs {time_loss_s:.2f}s per lap."
        )
    elif primary == "apex_deficit":
        apex_delta = proven.apex_kph - actual.apex_kph
        return (
            f"Your entry speed is right at {actual.entry_kph:.0f}kph, "
            f"but you're scrubbing {apex_delta:.0f}kph at the {corner_name} apex. "
            f"The track supports {proven.apex_kph:.0f}kph here across {n_sessions} sessions. "
            f"Trail-brake deeper into the corner to maintain speed — the grip is there."
        )
    elif primary == "entry_too_hot":
        excess = actual.entry_kph - proven.entry_kph
        return (
            f"You're carrying {excess:.0f}kph too much into {corner_name}. "
            f"The proven entry is {proven.entry_kph:.0f}kph — fast enough to set up a "
            f"{proven.apex_kph:.0f}kph apex without losing the rear. "
            f"Scrub {excess:.0f}kph on approach."
        )
    elif primary == "exit_under_application":
        return (
            f"You're only reaching {actual.exit_kph:.0f}kph at the {corner_name} exit "
            f"vs the {proven.exit_kph:.0f}kph the track supports. "
            f"Get on throttle earlier — the surface can take it. "
            f"This costs {time_loss_s:.2f}s per lap."
        )
    else:
        return (
            f"{corner_name}: losing {time_loss_s:.2f}s vs the track's "
            f"proven {proven.apex_kph:.0f}kph apex across {n_sessions} sessions."
        )


def compute_corner_coaching_v4(
    aggregate_grip, corners: list[dict], speed_trace: dict, *,
    handling_events: list[dict] | None = None,
) -> dict:
    """Compute full corner coaching response."""
    distances = np.array(speed_trace.get("distances", []), dtype=float)
    speeds_mps = np.array(speed_trace.get("speeds", []), dtype=float)

    if len(distances) < 2 or len(speeds_mps) < 2:
        return {"corners": [], "summary": {
            "total_time_loss_s": 0, "top_3_corners": [],
            "aggregate_sessions": aggregate_grip.session_count,
            "narrative": "Insufficient speed data.",
        }}

    ds = np.diff(distances)
    ds[ds < 0.01] = 0.01
    dv = np.diff(speeds_mps)
    accel = np.append(dv / ds * speeds_mps[:-1], 0.0)

    proven_list = compute_proven_limits(aggregate_grip, corners)
    actual_list = compute_actual_metrics(distances, speeds_mps, accel, corners)

    coaching_corners = []
    for i, c in enumerate(corners):
        if i >= len(proven_list) or i >= len(actual_list):
            break
        proven = proven_list[i]
        actual = actual_list[i]

        s_start = c.get("s_start", 0)
        s_end = c.get("s_end", 0)
        mask = (distances >= s_start) & (distances <= s_end)
        if mask.sum() < 2:
            continue

        corner_dist = distances[mask]
        corner_v_actual = speeds_mps[mask]
        kappa = abs(c.get("curvature_1pm", 0.01))
        corner_v_proven = np.array([
            _speed_at_grip(aggregate_grip.mu_at(float(d), "p95"), kappa) / 3.6
            for d in corner_dist
        ])
        time_loss = compute_time_loss(corner_dist, corner_v_actual, corner_v_proven)

        mu_apex = aggregate_grip.mu_at(c.get("s_apex", s_start), "p95")
        v_proven_sq = mu_apex * _G / max(kappa, 1e-6)
        v_actual_sq = (actual.apex_kph / 3.6) ** 2 * max(kappa, 1e-6)
        headroom_pct = max(0, (v_proven_sq - v_actual_sq) / v_proven_sq * 100) if v_proven_sq > 0 else 0

        corner_events = []
        if handling_events:
            for he in handling_events:
                if isinstance(he, dict):
                    he_d = he.get("distance_m", 0)
                    if s_start <= he_d <= s_end:
                        corner_events.append(he.get("type", ""))

        causes = classify_root_cause(
            proven, actual, handling_events=corner_events,
            grip_headroom_pct=headroom_pct,
        )

        corner_name = c.get("corner_name", f"T{c.get('corner_id', i+1)}")
        direction = c.get("direction", "?")
        narrative = generate_narrative(
            corner_name, direction, proven, actual, causes,
            aggregate_grip.session_count, time_loss,
        )

        radius_m = 1.0 / max(kappa, 1e-6)
        coaching_corners.append({
            "corner_id": c.get("corner_id", i + 1),
            "corner_name": corner_name,
            "direction": direction,
            "radius_m": round(radius_m, 1),
            "time_loss_s": round(time_loss, 3),
            "proven": proven.to_dict(),
            "actual": actual.to_dict(),
            "root_causes": causes,
            "narrative": narrative,
            "aggregate_sessions": aggregate_grip.session_count,
            "grip_headroom_pct": round(headroom_pct, 1),
        })

    coaching_corners.sort(key=lambda x: x["time_loss_s"], reverse=True)
    total_loss = sum(c["time_loss_s"] for c in coaching_corners)
    top_3 = [c["corner_id"] for c in coaching_corners[:3]]

    if coaching_corners:
        top_desc = ", ".join(
            f"{c['corner_name']} ({c['time_loss_s']:.2f}s)" for c in coaching_corners[:3]
        )
        top_pct = sum(c["time_loss_s"] for c in coaching_corners[:3]) / max(total_loss, 0.01) * 100
        summary_text = (
            f"You're leaving {total_loss:.2f}s on the table across "
            f"{len(coaching_corners)} corners. Focus on {top_desc} "
            f"— these account for {top_pct:.0f}% of your total loss."
        )
    else:
        summary_text = "All corners look clean against the track's aggregate data."

    return {
        "corners": coaching_corners,
        "summary": {
            "total_time_loss_s": round(total_loss, 3),
            "top_3_corners": top_3,
            "aggregate_sessions": aggregate_grip.session_count,
            "narrative": summary_text,
        },
    }
