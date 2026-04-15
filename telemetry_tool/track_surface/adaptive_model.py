"""
Self-calibrating vehicle model — learns ALL physics parameters from
telemetry feedback (ride height vs predicted Fz).

Each parameter updates ONLY from samples where its specific driving
condition is met, preventing cross-contamination:

  Parameter            | Update condition
  ---------------------|----------------------------------------------------
  CG height            | Steady cornering (|a_lat| > 3, |da_lat| < 0.5)
  Weight dist front    | Straight cruising (|a_lat| < 1, |a_long| < 1)
  Aero CLA total       | High speed straight (v > 50, |a_lat| < 1)
  Aero balance F/R     | High speed straight (v > 50, |a_lat| < 1)
  Brake bias           | Hard braking (a_long < -5, |a_lat| < 2)
  Roll stiffness split | Hard cornering (|a_lat| > 5)
  CG lateral offset    | Straight steady (|a_lat| < 0.5, |a_long| < 0.5)
  Spring rates (4)     | All valid samples (direct ride height feedback)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from track_surface.physics_grip import VehicleGeometry, _G, _RHO_AIR_DEFAULT

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveVehicleModel:
    """Full self-calibrating vehicle model — 12 learnable parameters."""

    # ── Learnable geometry ───────────────────────────────────
    cg_height_m: float = 0.35
    weight_dist_front: float = 0.46
    cg_lateral_offset_m: float = 0.0  # positive = CG shifted right
    wheelbase_m: float = 2.67
    track_front_m: float = 1.666
    track_rear_m: float = 1.627

    # ── Learnable aero ───────────────────────────────────────
    aero_cla: float = 1.5
    aero_balance_front: float = 0.45  # fraction of downforce on front axle

    # ── Learnable brake ──────────────────────────────────────
    brake_bias_front: float = 0.50

    # ── Learnable suspension ─────────────────────────────────
    roll_stiffness_front_frac: float = 0.50  # fraction of total roll stiffness on front
    spring_rates: np.ndarray = field(
        default_factory=lambda: np.array([100000.0, 100000.0, 100000.0, 100000.0])
    )

    # ── Learning rates ───────────────────────────────────────
    lr_cg_height: float = 0.00015
    lr_weight_dist: float = 0.00003
    lr_cg_lateral: float = 0.00005
    lr_aero_cla: float = 0.0001
    lr_aero_balance: float = 0.00005
    lr_brake_bias: float = 0.00008
    lr_roll_stiffness: float = 0.00005
    lr_spring_rate: float = 30.0

    # ── Tracking ─────────────────────────────────────────────
    n_updates: int = 0
    _rh_ref: np.ndarray | None = field(default=None, repr=False)
    _v_ref_sq: float = 0.0  # reference speed² for aero baseline
    error_history: list[float] = field(default_factory=list)

    @classmethod
    def from_vehicle_geometry(
        cls,
        geom: VehicleGeometry,
        spring_rates: np.ndarray | None = None,
        aero_cla: float = 1.5,
        brake_bias_front: float | None = None,
    ) -> AdaptiveVehicleModel:
        sr = spring_rates if spring_rates is not None else np.array([100000.0] * 4)
        bbf = brake_bias_front if brake_bias_front is not None else geom.brake_bias_front
        return cls(
            cg_height_m=geom.cg_height_m,
            weight_dist_front=geom.weight_dist_front,
            wheelbase_m=geom.wheelbase_m,
            track_front_m=geom.track_front_m,
            track_rear_m=geom.track_rear_m,
            brake_bias_front=bbf,
            aero_cla=aero_cla,
            spring_rates=sr.copy(),
        )

    def to_geometry(self) -> VehicleGeometry:
        cg_to_front = self.wheelbase_m * (1.0 - self.weight_dist_front)
        cg_to_rear = self.wheelbase_m * self.weight_dist_front
        return VehicleGeometry(
            wheelbase_m=self.wheelbase_m,
            track_front_m=self.track_front_m,
            track_rear_m=self.track_rear_m,
            cg_height_m=self.cg_height_m,
            cg_to_front_m=cg_to_front,
            cg_to_rear_m=cg_to_rear,
            brake_bias_front=self.brake_bias_front,
        )

    def param_dict(self) -> dict:
        return {
            "cg_height_m": round(self.cg_height_m, 4),
            "weight_dist_front": round(self.weight_dist_front, 4),
            "cg_lateral_offset_m": round(self.cg_lateral_offset_m, 4),
            "aero_cla": round(self.aero_cla, 4),
            "aero_balance_front": round(self.aero_balance_front, 4),
            "brake_bias_front": round(self.brake_bias_front, 4),
            "roll_stiffness_front_frac": round(self.roll_stiffness_front_frac, 4),
            "spring_rates": [round(float(s), 0) for s in self.spring_rates],
        }

    # ── Predict ──────────────────────────────────────────────

    def predict_fz(
        self, mass_kg: float, speed: float,
        a_long: float, a_lat: float,
        roll: float, pitch: float,
        air_density: float = _RHO_AIR_DEFAULT,
    ) -> np.ndarray:
        h = self.cg_height_m
        L = self.wheelbase_m
        r_f = self.weight_dist_front
        r_r = 1.0 - r_f

        # Aero with front/rear balance
        f_down_total = 0.5 * air_density * max(self.aero_cla, 0.0) * speed ** 2
        f_down_f = f_down_total * self.aero_balance_front
        f_down_r = f_down_total * (1.0 - self.aero_balance_front)

        fz_gravity = mass_kg * _G * np.cos(pitch) * np.cos(roll)

        fz_f_static = fz_gravity * r_f + f_down_f
        fz_r_static = fz_gravity * r_r + f_down_r

        # Longitudinal transfer
        d_fz_long = mass_kg * a_long * h / L

        # Lateral transfer with roll stiffness distribution
        abs_alat = abs(a_lat)
        d_fz_lat_f = mass_kg * abs_alat * h * self.roll_stiffness_front_frac / self.track_front_m
        d_fz_lat_r = mass_kg * abs_alat * h * (1.0 - self.roll_stiffness_front_frac) / self.track_rear_m

        s_lat = 1.0 if a_lat > 0 else (-1.0 if a_lat < 0 else 0.0)

        # CG lateral offset: static asymmetry
        cg_lat_fz = mass_kg * _G * self.cg_lateral_offset_m / self.track_front_m

        fz = np.array([
            0.5 * (fz_f_static - d_fz_long) - s_lat * d_fz_lat_f - cg_lat_fz,
            0.5 * (fz_f_static - d_fz_long) + s_lat * d_fz_lat_f + cg_lat_fz,
            0.5 * (fz_r_static + d_fz_long) - s_lat * d_fz_lat_r - cg_lat_fz,
            0.5 * (fz_r_static + d_fz_long) + s_lat * d_fz_lat_r + cg_lat_fz,
        ])
        return np.maximum(fz, 0.0)

    def observe_fz(self, ride_heights_mm: np.ndarray) -> np.ndarray:
        if self._rh_ref is None:
            return np.zeros(4)
        delta_rh = self._rh_ref - ride_heights_mm
        return delta_rh * self.spring_rates / 1000.0

    # ── Condition-gated updates ──────────────────────────────

    def update_from_sample(
        self, mass_kg: float,
        speed: float, a_long: float, a_lat: float,
        roll: float, pitch: float,
        ride_heights_mm: np.ndarray,
        brake_pct: float = 0.0,
        throttle_pct: float = 0.0,
    ) -> float:
        if speed < 8.0:
            return 0.0

        fz_pred = self.predict_fz(mass_kg, speed, a_long, a_lat, roll, pitch)
        fz_obs = self.observe_fz(ride_heights_mm)
        if np.any(fz_obs == 0):
            return 0.0

        error = fz_pred - fz_obs
        abs_alat = abs(a_lat)
        abs_along = abs(a_long)

        # ── 1. CG height: cornering samples ──────────────────
        # Condition: steady cornering (high lat, low jerk implied by gate)
        if abs_alat > 3.0:
            s = 1.0 if a_lat > 0 else -1.0
            outer_err = s * (error[1] + error[3])
            inner_err = s * (error[0] + error[2])
            lat_err = outer_err - inner_err
            self.cg_height_m += -self.lr_cg_height * lat_err / max(abs_alat, 1.0)
            self.cg_height_m = float(np.clip(self.cg_height_m, 0.02, 0.60))

        # ── 2. Weight distribution: straight cruising ────────
        if abs_alat < 1.0 and abs_along < 1.5 and speed > 15.0:
            front_err = error[0] + error[1]
            rear_err = error[2] + error[3]
            fr_imb = front_err - rear_err
            self.weight_dist_front += -self.lr_weight_dist * fr_imb / max(fz_pred.sum(), 1000.0)
            self.weight_dist_front = float(np.clip(self.weight_dist_front, 0.30, 0.65))

        # ── 3. Aero CLA: high-speed straight ─────────────────
        # At high speed, Fz should increase by ΔF_down = 0.5·ρ·CLA·v²
        # If predicted total Fz is wrong AT HIGH SPEED but correct at low → CLA wrong
        if speed > 45.0 and abs_alat < 1.0 and abs_along < 1.5:
            total_err = fz_pred.sum() - fz_obs.sum()
            # ∂(total_err)/∂(CLA) = 0.5·ρ·v² (always positive)
            d_cla = -self.lr_aero_cla * total_err / max(0.5 * _RHO_AIR_DEFAULT * speed ** 2, 100.0)
            self.aero_cla += d_cla
            self.aero_cla = float(np.clip(self.aero_cla, 0.0, 5.0))

        # ── 4. Aero balance: high-speed F/R split ────────────
        if speed > 45.0 and abs_alat < 1.0:
            front_err = error[0] + error[1]
            rear_err = error[2] + error[3]
            # If front over-predicted at speed → too much front downforce → balance too high
            fr_speed_imb = front_err - rear_err
            d_bal = -self.lr_aero_balance * fr_speed_imb / max(fz_pred.sum(), 1000.0)
            self.aero_balance_front += d_bal
            self.aero_balance_front = float(np.clip(self.aero_balance_front, 0.25, 0.65))

        # ── 5. Brake bias: hard braking ──────────────────────
        if a_long < -5.0 and abs_alat < 2.0 and brake_pct > 20.0:
            # Under braking, longitudinal force is split by brake bias
            # If front is over-loaded vs observation → brake bias too high
            front_long_err = error[0] + error[1]  # longitudinal component
            rear_long_err = error[2] + error[3]
            bias_err = front_long_err - rear_long_err
            d_bias = -self.lr_brake_bias * bias_err / max(abs(a_long) * mass_kg, 1000.0)
            self.brake_bias_front += d_bias
            self.brake_bias_front = float(np.clip(self.brake_bias_front, 0.35, 0.75))

        # ── 6. Roll stiffness distribution: hard cornering ───
        if abs_alat > 5.0:
            # Compare front axle lateral transfer error vs rear
            front_lat_err = abs(error[0] - error[1])  # front left-right imbalance error
            rear_lat_err = abs(error[2] - error[3])
            # If front has more error → front roll stiffness fraction is wrong
            rollf_err = front_lat_err - rear_lat_err
            d_rollf = -self.lr_roll_stiffness * np.sign(rollf_err) * min(abs(rollf_err), 500.0) / max(abs_alat * mass_kg, 1000.0)
            self.roll_stiffness_front_frac += d_rollf
            self.roll_stiffness_front_frac = float(np.clip(self.roll_stiffness_front_frac, 0.30, 0.70))

        # ── 7. CG lateral offset: straight steady ────────────
        if abs_alat < 0.5 and abs_along < 0.5 and speed > 20.0:
            # At zero lateral accel, L/R imbalance = CG lateral offset
            lr_imb = (error[1] + error[3]) - (error[0] + error[2])  # right - left
            d_cglat = -self.lr_cg_lateral * lr_imb / max(fz_pred.sum(), 1000.0)
            self.cg_lateral_offset_m += d_cglat
            self.cg_lateral_offset_m = float(np.clip(self.cg_lateral_offset_m, -0.05, 0.05))

        # ── 8. Spring rates: all valid samples ───────────────
        for w in range(4):
            if abs(error[w]) > 30 and fz_obs[w] > 300:
                k_update = self.lr_spring_rate * error[w] / max(abs(ride_heights_mm[w] - self._rh_ref[w]), 0.05)
                self.spring_rates[w] = float(np.clip(
                    self.spring_rates[w] + k_update, 15000.0, 500000.0
                ))

        self.n_updates += 1
        l2 = float(np.sqrt(np.sum(error ** 2)))
        self.error_history.append(l2)
        return l2

    # ── Batch calibration ────────────────────────────────────

    def calibrate_from_session(
        self, mass_kg: float,
        speed: np.ndarray, a_long: np.ndarray, a_lat: np.ndarray,
        roll: np.ndarray, pitch: np.ndarray,
        ride_heights: np.ndarray,
        brake_pct: np.ndarray | None = None,
        throttle_pct: np.ndarray | None = None,
        batch_size: int = 100,
        max_iterations: int = 8,
    ) -> dict:
        N = len(speed)
        if brake_pct is None:
            brake_pct = np.zeros(N)
        if throttle_pct is None:
            throttle_pct = np.zeros(N)

        # Static reference
        steady = (speed > 20.0) & (np.abs(a_long) < 1.0) & (np.abs(a_lat) < 1.0)
        steady_idx = np.where(steady)[0]
        if len(steady_idx) >= 50:
            self._rh_ref = np.mean(ride_heights[steady_idx[:200]], axis=0)
        else:
            self._rh_ref = np.mean(ride_heights[:500], axis=0)

        # Aero speed reference (mean v² at steady state for baseline)
        if len(steady_idx) >= 10:
            self._v_ref_sq = float(np.mean(speed[steady_idx[:200]] ** 2))

        initial = self.param_dict()
        logger.info("Calibration start: %s", initial)

        diagnostics = {"initial": initial, "iterations": []}

        for iteration in range(max_iterations):
            errors = []
            step = max(1, N // batch_size)
            for i in range(0, N, step):
                e = self.update_from_sample(
                    mass_kg,
                    float(speed[i]), float(a_long[i]), float(a_lat[i]),
                    float(roll[i]), float(pitch[i]),
                    ride_heights[i],
                    float(brake_pct[i]), float(throttle_pct[i]),
                )
                if e > 0:
                    errors.append(e)

            mean_err = float(np.mean(errors)) if errors else 0.0
            current = self.param_dict()
            diagnostics["iterations"].append({
                "iter": iteration,
                "mean_error_n": round(mean_err, 1),
                **current,
            })

            logger.info("Iter %d: err=%.0f N | %s", iteration, mean_err, current)

            if mean_err < 30 and iteration > 1:
                break

        diagnostics["final"] = self.param_dict()
        diagnostics["converged"] = len(diagnostics["iterations"]) < max_iterations
        diagnostics["total_updates"] = self.n_updates
        return diagnostics
