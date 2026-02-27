"""
powertrain.py
-------------
Cycle-B runtime powertrain model:
- peak-power fallback
- optional full RPM/torque/power curve usage
- transmission ratio/shift policy
- rolling resistance
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.ingest.metadata import SessionMetadata

_G = 9.80665


@dataclass
class PowertrainRuntime:
    """Runtime powertrain model used by solver backends."""

    enabled_map: bool = True
    enabled_transmission: bool = True
    enabled_rolling_resistance: bool = True
    transmission_efficiency: float = 0.93
    rr_c0: float = 0.012
    rr_c1: float = 0.00008
    peak_power_w_per_kg: float | None = None
    source: str = "metadata"
    confidence: float = 0.5

    mass_kg: float = 180.0
    wheel_radius_m: float = 0.135
    final_drive_ratio: float = 1.0
    gear_ratios: tuple[float, ...] = (1.0,)
    auto_shift: bool = True
    shift_rpm_up: float | None = None
    shift_rpm_down: float | None = None
    shift_latency_s: float = 0.05

    rpm_curve: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    torque_curve_nm: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    power_curve_kw: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))

    def max_drive_accel(self, speed_mps: float, env_drive_accel_mps2: float) -> float:
        """Power/transmission-limited drive acceleration."""
        a_env = max(float(env_drive_accel_mps2), 0.0)
        if not self.enabled_map:
            return a_env
        a_map = self._map_drive_accel(speed_mps)
        if not np.isfinite(a_map) or a_map <= 0.0:
            return a_env
        return float(np.clip(min(a_env, a_map), 0.0, 20.0))

    def resistance_accel(
        self,
        speed_mps: float,
        *,
        condition_label: str = "",
        load_factor: float = 1.0,
    ) -> float:
        """Rolling resistance contribution [m/s^2]."""
        if not self.enabled_rolling_resistance:
            return 0.0
        v = max(float(speed_mps), 0.0)
        rr = max(float(self.rr_c0) + float(self.rr_c1) * v, 0.0)
        cond = str(condition_label or "").strip().lower()
        cond_factor = 1.0
        if "wet" in cond:
            cond_factor = 1.18
        elif "damp" in cond:
            cond_factor = 1.10
        elif "greasy" in cond:
            cond_factor = 1.12
        elif "green" in cond:
            cond_factor = 1.05
        lf = float(np.clip(load_factor, 0.75, 1.40))
        return float(rr * _G * cond_factor * lf)

    def engine_state(self, speed_mps: float) -> dict[str, float | int | None]:
        """Return selected gear/rpm/torque/power at this speed."""
        gear_i, total_ratio = self._select_ratio(speed_mps)
        rpm = self._rpm_from_speed(speed_mps, total_ratio)
        tq = self._interp(self.rpm_curve, self.torque_curve_nm, rpm)
        pw = self._interp(self.rpm_curve, self.power_curve_kw, rpm)
        return {
            "gear": int(gear_i + 1) if gear_i is not None else None,
            "rpm": float(rpm) if rpm is not None else None,
            "torque_nm": float(tq) if tq is not None else None,
            "power_kw": float(pw) if pw is not None else None,
        }

    def transmission_meta(self) -> dict[str, Any]:
        return {
            "enabled_transmission": bool(self.enabled_transmission),
            "auto_shift": bool(self.auto_shift),
            "gear_count": int(len(self.gear_ratios)),
            "gear_ratios": [round(float(v), 6) for v in self.gear_ratios],
            "final_drive_ratio": round(float(self.final_drive_ratio), 6),
            "shift_rpm_up": (
                round(float(self.shift_rpm_up), 2) if self.shift_rpm_up is not None else None
            ),
            "shift_rpm_down": (
                round(float(self.shift_rpm_down), 2) if self.shift_rpm_down is not None else None
            ),
            "shift_latency_s": round(float(self.shift_latency_s), 4),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled_map": bool(self.enabled_map),
            "enabled_transmission": bool(self.enabled_transmission),
            "enabled_rolling_resistance": bool(self.enabled_rolling_resistance),
            "transmission_efficiency": round(float(self.transmission_efficiency), 4),
            "rr_c0": round(float(self.rr_c0), 6),
            "rr_c1": round(float(self.rr_c1), 6),
            "peak_power_w_per_kg": (
                round(float(self.peak_power_w_per_kg), 4)
                if self.peak_power_w_per_kg is not None
                else None
            ),
            "source": self.source,
            "confidence": round(float(self.confidence), 4),
            "mass_kg": round(float(self.mass_kg), 3),
            "wheel_radius_m": round(float(self.wheel_radius_m), 5),
            "final_drive_ratio": round(float(self.final_drive_ratio), 6),
            "gear_count": int(len(self.gear_ratios)),
            "curve_points": int(len(self.rpm_curve)),
            "curve_available": bool(len(self.rpm_curve) >= 3 and len(self.power_curve_kw) == len(self.rpm_curve)),
            "transmission": self.transmission_meta(),
        }

    def _map_drive_accel(self, speed_mps: float) -> float:
        """Map-limited acceleration from curve or peak power fallback."""
        v = max(float(speed_mps), 0.5)
        m = max(float(self.mass_kg), 60.0)
        eff = (
            float(np.clip(self.transmission_efficiency, 0.60, 1.00))
            if self.enabled_transmission
            else 1.0
        )

        if len(self.rpm_curve) >= 3 and len(self.power_curve_kw) == len(self.rpm_curve):
            _, total_ratio = self._select_ratio(v)
            rpm = self._rpm_from_speed(v, total_ratio)
            torque = self._interp(self.rpm_curve, self.torque_curve_nm, rpm)
            power_kw = self._interp(self.rpm_curve, self.power_curve_kw, rpm)
            a_torque = None
            if torque is not None and np.isfinite(torque) and torque > 0.0:
                f_wheel = float(torque) * float(total_ratio) * eff / max(float(self.wheel_radius_m), 1e-3)
                a_torque = f_wheel / m
            a_power = None
            if power_kw is not None and np.isfinite(power_kw) and power_kw > 0.0:
                a_power = (float(power_kw) * 1000.0 * eff) / (m * max(v, 1.0))
            cand = [x for x in (a_torque, a_power) if x is not None and np.isfinite(x) and x > 0.0]
            if cand:
                return float(np.clip(min(cand), 0.0, 20.0))

        if self.peak_power_w_per_kg is not None and np.isfinite(self.peak_power_w_per_kg):
            return float(np.clip(float(self.peak_power_w_per_kg) * eff / max(v, 1.0), 0.0, 20.0))

        return float("nan")

    def _select_ratio(self, speed_mps: float) -> tuple[int | None, float]:
        if not self.enabled_transmission or len(self.gear_ratios) == 0:
            ratio = max(float(self.final_drive_ratio), 1e-6)
            return 0, ratio
        ratios = np.asarray(self.gear_ratios, dtype=float)
        ratios = np.clip(ratios, 1e-6, 100.0)

        if len(ratios) == 1 or not self.auto_shift:
            return 0, float(ratios[0] * self.final_drive_ratio)

        # Select gear by max map-accel proxy at current speed.
        best_i = 0
        best_score = -1e9
        for i, gr in enumerate(ratios):
            total = float(gr * self.final_drive_ratio)
            rpm = self._rpm_from_speed(speed_mps, total)
            if rpm is None:
                continue
            if self.shift_rpm_up is not None and rpm > float(self.shift_rpm_up) * 1.08:
                # Allow slight overshoot, but discourage heavily.
                rpm_pen = -0.15 * (rpm - float(self.shift_rpm_up))
            else:
                rpm_pen = 0.0
            pw = self._interp(self.rpm_curve, self.power_curve_kw, rpm)
            tq = self._interp(self.rpm_curve, self.torque_curve_nm, rpm)
            score = 0.0
            if pw is not None and np.isfinite(pw):
                score += float(pw)
            if tq is not None and np.isfinite(tq):
                score += 0.02 * float(tq) * float(total)
            score += rpm_pen
            if score > best_score:
                best_score = score
                best_i = i
        return int(best_i), float(ratios[best_i] * self.final_drive_ratio)

    def _rpm_from_speed(self, speed_mps: float, total_ratio: float) -> float | None:
        r = max(float(self.wheel_radius_m), 1e-3)
        v = max(float(speed_mps), 0.0)
        wheel_rpm = (v / (2.0 * np.pi * r)) * 60.0
        return float(max(wheel_rpm * max(total_ratio, 1e-6), 0.0))

    @staticmethod
    def _interp(x: np.ndarray, y: np.ndarray, xq: float | None) -> float | None:
        if xq is None:
            return None
        if len(x) < 2 or len(y) != len(x):
            return None
        xv = np.asarray(x, dtype=float)
        yv = np.asarray(y, dtype=float)
        if not np.isfinite(xq):
            return None
        if not np.all(np.isfinite(xv)) or not np.all(np.isfinite(yv)):
            return None
        return float(np.interp(float(xq), xv, yv, left=float(yv[0]), right=float(yv[-1])))


def build_powertrain_runtime(
    metadata: SessionMetadata | None,
    config: KartEnvelopeConfig,
    *,
    acd_engine: dict[str, Any] | None = None,
) -> PowertrainRuntime:
    """Build runtime powertrain model from metadata + optional ACD data."""
    runtime = PowertrainRuntime(
        enabled_map=bool(config.powertrain_enable_map),
        enabled_transmission=bool(config.powertrain_enable_transmission),
        enabled_rolling_resistance=bool(config.powertrain_enable_rolling_resistance),
        transmission_efficiency=float(config.powertrain_transmission_efficiency),
        rr_c0=float(config.powertrain_rr_c0),
        rr_c1=float(config.powertrain_rr_c1),
        source="config_default",
        confidence=0.35,
        wheel_radius_m=float(max(config.powertrain_wheel_radius_m, 0.05)),
        auto_shift=bool(config.powertrain_auto_shift),
        shift_latency_s=float(max(config.powertrain_shift_latency_s, 0.0)),
    )
    if metadata is None:
        return runtime

    driver_w = float(getattr(metadata, "driver_weight_kg", 85.0) or 85.0)
    kart_w = float(getattr(metadata, "kart_weight_kg", 0.0) or 0.0)
    if kart_w <= 0.0:
        kart_w = float(config.default_kart_weight_kg_4t)
    runtime.mass_kg = float(max(driver_w + kart_w, 80.0))

    # Transmission parameters.
    ratios = _parse_ratio_csv(getattr(metadata, "gear_ratios", None))
    if ratios:
        runtime.gear_ratios = tuple(ratios)
    elif getattr(metadata, "gear_count", None) and int(metadata.gear_count or 0) > 1:
        # Generic geometric ratio spread if only gear count is known.
        n = int(metadata.gear_count or 1)
        hi = 1.30
        lo = 0.78
        runtime.gear_ratios = tuple(np.geomspace(hi, lo, n).astype(float).tolist())
    runtime.final_drive_ratio = float(
        np.clip(
            getattr(metadata, "final_drive_ratio", None) if getattr(metadata, "final_drive_ratio", None) is not None else 1.0,
            0.2,
            20.0,
        )
    )
    if getattr(metadata, "shift_rpm_up", None) is not None:
        runtime.shift_rpm_up = float(np.clip(metadata.shift_rpm_up, 1000.0, 25000.0))
    if getattr(metadata, "shift_rpm_down", None) is not None:
        runtime.shift_rpm_down = float(np.clip(metadata.shift_rpm_down, 500.0, 20000.0))

    # Curve ingestion from ACD.
    rpm_curve = _as_float_array(acd_engine.get("rpm_curve") if isinstance(acd_engine, dict) else None)
    tq_curve = _as_float_array(acd_engine.get("torque_nm_curve") if isinstance(acd_engine, dict) else None)
    pw_curve = _as_float_array(acd_engine.get("power_kw_curve") if isinstance(acd_engine, dict) else None)
    if rpm_curve is not None and pw_curve is not None and len(rpm_curve) == len(pw_curve) and len(rpm_curve) >= 3:
        order = np.argsort(rpm_curve)
        rpm_curve = rpm_curve[order]
        pw_curve = pw_curve[order]
        if tq_curve is not None and len(tq_curve) == len(rpm_curve):
            tq_curve = tq_curve[order]
        else:
            tq_curve = (pw_curve * 9549.29658551372) / np.maximum(rpm_curve, 1.0)
        runtime.rpm_curve = rpm_curve.astype(float)
        runtime.power_curve_kw = np.clip(pw_curve.astype(float), 0.0, np.inf)
        runtime.torque_curve_nm = np.clip(tq_curve.astype(float), 0.0, np.inf)
        runtime.source = "acd_curve+metadata"
        runtime.confidence = 0.85

    # Peak-power fallback / complement.
    power_kw = _resolve_peak_power_kw(metadata, acd_engine, runtime)
    if power_kw is not None and power_kw > 0.0:
        runtime.peak_power_w_per_kg = float(np.clip(power_kw * 1000.0 / runtime.mass_kg, 5.0, 220.0))
        if runtime.source == "config_default":
            runtime.source = "metadata"
            runtime.confidence = 0.60
    if runtime.source == "config_default":
        runtime.source = "metadata"
        runtime.confidence = 0.45

    # Infer shift points from curve if not provided.
    if runtime.shift_rpm_up is None and len(runtime.rpm_curve) >= 3:
        runtime.shift_rpm_up = float(np.clip(np.nanmax(runtime.rpm_curve) * 0.96, 2500.0, 20000.0))
    if runtime.shift_rpm_down is None and runtime.shift_rpm_up is not None:
        runtime.shift_rpm_down = float(np.clip(runtime.shift_rpm_up * 0.72, 1200.0, runtime.shift_rpm_up))

    return runtime


def _resolve_peak_power_kw(
    metadata: SessionMetadata,
    acd_engine: dict[str, Any] | None,
    runtime: PowertrainRuntime,
) -> float | None:
    if len(runtime.power_curve_kw) >= 3:
        val = float(np.nanmax(runtime.power_curve_kw))
        if np.isfinite(val) and val > 0.0:
            return val
    if acd_engine and isinstance(acd_engine, dict):
        val = acd_engine.get("peak_power_kw")
        if _is_pos_num(val):
            return float(val)
    kw = getattr(metadata, "engine_peak_power_kw", None)
    if _is_pos_num(kw):
        return float(kw)
    hp = getattr(metadata, "engine_peak_power_hp", None)
    if _is_pos_num(hp):
        return float(hp) * 0.745699872
    return None


def _as_float_array(value: object) -> np.ndarray | None:
    if value is None:
        return None
    try:
        arr = np.asarray(value, dtype=float).reshape(-1)
    except Exception:
        return None
    if arr.size == 0:
        return None
    m = np.isfinite(arr)
    if np.sum(m) < 2:
        return None
    return arr[m]


def _parse_ratio_csv(value: object) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        vals = [float(v) for v in value if _is_pos_num(v)]
        return [float(np.clip(v, 0.2, 10.0)) for v in vals]
    s = str(value).strip()
    if not s:
        return []
    parts = [p.strip() for p in s.replace(";", ",").split(",")]
    vals: list[float] = []
    for p in parts:
        if not p:
            continue
        try:
            v = float(p)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v) and v > 0.0:
            vals.append(float(np.clip(v, 0.2, 10.0)))
    return vals


def _is_pos_num(value: object) -> bool:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(out) and out > 0.0)

