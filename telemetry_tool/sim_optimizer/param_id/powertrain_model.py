"""Powertrain model identification from telemetry data."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

_G = 9.80665


@dataclass
class PowertrainModel:
    """Torque-map powertrain model with per-gear RPM-torque curves."""

    gear_torque_maps: dict[int, tuple[np.ndarray, np.ndarray]] = field(
        default_factory=dict
    )  # gear -> (rpm[], torque_nm[])
    gear_speed_ranges: dict[int, tuple[float, float]] = field(
        default_factory=dict
    )  # gear -> (speed_min_mps, speed_max_mps) observed during identification
    wheel_radius_m: float = 0.33
    transmission_efficiency: float = 0.93
    rr_c0: float = 0.012
    rr_c1: float = 0.00008

    def _speed_to_rpm(self, speed_mps: float, gear: int) -> float:
        """Map vehicle speed to engine RPM using observed speed-RPM relationship."""
        if gear not in self.gear_torque_maps:
            return 5000.0
        rpm_arr = self.gear_torque_maps[gear][0]
        rpm_min, rpm_max = float(rpm_arr[0]), float(rpm_arr[-1])

        if gear in self.gear_speed_ranges:
            s_min, s_max = self.gear_speed_ranges[gear]
            if s_max > s_min:
                t = (speed_mps - s_min) / (s_max - s_min)
                return float(np.clip(rpm_min + t * (rpm_max - rpm_min), rpm_min, rpm_max))

        # Fallback: use wheel_radius to estimate (RPM = speed / (wheel_radius * 2*pi) * 60 * ratio)
        # Without ratio, use a conservative mid-RPM
        return float(np.clip((rpm_min + rpm_max) / 2, rpm_min, rpm_max))

    def max_drive_accel(self, speed_mps: float, gear: int, mass_kg: float) -> float:
        """Torque-limited acceleration for a given speed, gear, and mass."""
        if gear not in self.gear_torque_maps:
            return 0.0
        rpm_arr, torque_arr = self.gear_torque_maps[gear]
        if len(rpm_arr) == 0:
            return 0.0

        rpm_query = self._speed_to_rpm(speed_mps, gear)
        torque = float(np.interp(rpm_query, rpm_arr, torque_arr))
        force = torque * self.transmission_efficiency / self.wheel_radius_m
        return max(force / max(mass_kg, 1.0), 0.0)

    def rolling_resistance_accel(self, speed_mps: float) -> float:
        """Rolling resistance deceleration: (c0 + c1 * |v|) * g."""
        return (self.rr_c0 + self.rr_c1 * abs(speed_mps)) * _G

    def optimal_gear(self, speed_mps: float, mass_kg: float) -> int:
        """Select the gear that maximizes drive acceleration at this speed.

        Only considers gears whose observed speed range includes the current speed
        (with 20% margin). Falls back to the gear with the closest speed range.
        """
        if not self.gear_torque_maps:
            return 1

        # First: try gears whose speed range covers this speed
        candidates = []
        for g in self.gear_torque_maps:
            if g in self.gear_speed_ranges:
                s_min, s_max = self.gear_speed_ranges[g]
                margin = (s_max - s_min) * 0.2
                if s_min - margin <= speed_mps <= s_max + margin:
                    candidates.append(g)

        if not candidates:
            # Fallback: pick gear with closest speed range midpoint
            best_g = min(self.gear_torque_maps.keys())
            best_dist = float("inf")
            for g in self.gear_torque_maps:
                if g in self.gear_speed_ranges:
                    s_min, s_max = self.gear_speed_ranges[g]
                    mid = (s_min + s_max) / 2
                    d = abs(speed_mps - mid)
                    if d < best_dist:
                        best_dist = d
                        best_g = g
            candidates = [best_g]

        best_gear = candidates[0]
        best_accel = -1.0
        for g in candidates:
            a = self.max_drive_accel(speed_mps, g, mass_kg)
            if a > best_accel:
                best_accel = a
                best_gear = g
        return best_gear

    def inverse_throttle(
        self, accel_mps2: float, speed_mps: float, gear: int, mass_kg: float
    ) -> float:
        """Estimate throttle position to achieve a target acceleration.

        Returns accel / max_drive_accel, clipped to [0, 1].
        """
        max_a = self.max_drive_accel(speed_mps, gear, mass_kg)
        if max_a <= 0:
            return 0.0
        return float(np.clip(accel_mps2 / max_a, 0.0, 1.0))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict (numpy arrays become lists)."""
        maps_serial: dict[str, Any] = {}
        for g, (rpm_arr, torque_arr) in self.gear_torque_maps.items():
            maps_serial[str(g)] = {
                "rpm": rpm_arr.tolist(),
                "torque_nm": torque_arr.tolist(),
            }
        return {
            "gear_torque_maps": maps_serial,
            "wheel_radius_m": self.wheel_radius_m,
            "transmission_efficiency": self.transmission_efficiency,
            "rr_c0": self.rr_c0,
            "rr_c1": self.rr_c1,
        }


def identify_powertrain_model(
    *,
    rpm: np.ndarray,
    gear: np.ndarray,
    throttle: np.ndarray,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    mass_kg: float,
    drag_accel_fn: Optional[Callable[[float], float]] = None,
    config: SimOptimizerConfig,
) -> PowertrainModel:
    """Identify a powertrain model from full-throttle telemetry.

    Strategy:
    - Find full-throttle samples (throttle >= config threshold, accel > 0.5).
    - Per unique gear with >= min_samples_per_gear samples:
        - Back-calculate torque: T = (accel + drag + rr) * mass * wheel_radius / eff
        - Bin RPM into up to 20 bins, take median torque per bin.
        - Require >= 3 bins with data.
    - Returns a PowertrainModel (possibly with empty maps on insufficient data).
    """
    wheel_radius = 0.33  # typical sim car
    eff = config.powertrain_transmission_efficiency

    # Full-throttle mask
    ft_mask = (throttle >= config.powertrain_full_throttle_min) & (long_accel > 0.5)

    gear_torque_maps: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    unique_gears = np.unique(gear[ft_mask]).astype(int)

    for g in unique_gears:
        if g <= 0:
            continue
        gear_ft_mask = ft_mask & (gear == g)
        n_samples = int(np.sum(gear_ft_mask))
        if n_samples < config.powertrain_min_samples_per_gear:
            continue

        g_rpm = rpm[gear_ft_mask]
        g_accel = long_accel[gear_ft_mask]
        g_speed = speed_mps[gear_ft_mask]

        # Back-calculate torque at wheel, then engine torque
        rr_accel = np.array([
            (config.powertrain_rr_c0 + config.powertrain_rr_c1 * abs(v)) * _G
            for v in g_speed
        ])

        if drag_accel_fn is not None:
            drag_accel = np.array([drag_accel_fn(v) for v in g_speed])
        else:
            drag_accel = np.zeros(len(g_speed))

        # Net force that engine must produce: (measured_accel + drag + rr) * mass
        net_accel = g_accel + drag_accel + rr_accel
        torque = net_accel * mass_kg * wheel_radius / eff

        # Bin by RPM (up to 20 bins)
        rpm_min, rpm_max = float(g_rpm.min()), float(g_rpm.max())
        if rpm_max - rpm_min < 100:
            # Too narrow RPM range
            continue

        n_bins = min(20, max(3, n_samples // 10))
        bin_edges = np.linspace(rpm_min, rpm_max, n_bins + 1)
        bin_centers = []
        bin_torques = []

        for i in range(n_bins):
            lo, hi = bin_edges[i], bin_edges[i + 1]
            if i == n_bins - 1:
                mask = (g_rpm >= lo) & (g_rpm <= hi)
            else:
                mask = (g_rpm >= lo) & (g_rpm < hi)
            if np.sum(mask) > 0:
                bin_centers.append((lo + hi) / 2.0)
                # Use 85th percentile instead of median — we want the car's
                # capability, not the average. Median underestimates because
                # many full-throttle samples are mid-gear-change or partial.
                bin_torques.append(float(np.percentile(torque[mask], 85)))

        if len(bin_centers) < 3:
            continue

        gear_torque_maps[g] = (
            np.array(bin_centers),
            np.array(bin_torques),
        )

    # Store observed speed ranges per gear for speed-to-RPM mapping
    gear_speed_ranges: dict[int, tuple[float, float]] = {}
    for g in gear_torque_maps:
        gear_ft_mask = ft_mask & (gear == g)
        if gear_ft_mask.sum() > 0:
            g_speed = speed_mps[gear_ft_mask]
            gear_speed_ranges[int(g)] = (float(g_speed.min()), float(g_speed.max()))

    return PowertrainModel(
        gear_torque_maps=gear_torque_maps,
        gear_speed_ranges=gear_speed_ranges,
        wheel_radius_m=wheel_radius,
        transmission_efficiency=eff,
        rr_c0=config.powertrain_rr_c0,
        rr_c1=config.powertrain_rr_c1,
    )
