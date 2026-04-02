#!/usr/bin/env python3
"""Run the sim optimizer on a LapCoach Logger session and serve an interactive preview.

Usage:
    python scripts/run_sim_optimizer_preview.py [SESSION_DIR]

If no session dir provided, uses the Red Bull Ring session as default.
Opens localhost:8899 with interactive charts.
"""
from __future__ import annotations

import http.server
import json
import logging
import math
import os
import sys
import threading
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd

# Project root setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig, default_config
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel, identify_tyre_model
from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel, identify_aero_model
from telemetry_tool.sim_optimizer.param_id.powertrain_model import PowertrainModel, identify_powertrain_model
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel, identify_brake_model
from telemetry_tool.sim_optimizer.param_id.suspension_model import SuspensionModel, identify_suspension_model
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel, identify_mass_model
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel
from telemetry_tool.sim_optimizer.solver.qss_enhanced import compute_sim_theoretical_lap, SimTheoreticalResult
from telemetry_tool.sim_optimizer.reconstruction.input_trace import reconstruct_inputs, TheoreticalInputTrace
from telemetry_tool.sim_optimizer.analysis.delta import compute_lap_delta, LapDelta

from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sim_optimizer_preview")

_G = 9.80665


def export_ghost_json(trace, session_meta: dict, lap_df, output_dir: str):
    """Export theoretical trace as theoretical_ghost.json for the logger overlay.

    Format:
    {
        "version": 1,
        "track_name": str,
        "car_name": str,
        "theoretical_lap_time_s": float,
        "generated_at": ISO timestamp,
        "n_points": int,
        "distance_pct": [...],  # 0.0 to 1.0
        "speed_kph": [...],
        "throttle_pct": [...],
        "brake_pct": [...],
        "steering_deg": [...]
    }

    Downsample to ~500 points. Convert distance_m to distance_pct (0-1).
    """
    if trace is None:
        log.warning("No trace available, skipping ghost export")
        return None

    n = len(trace.distance_m)
    step = max(1, n // 500)
    idx = np.arange(0, n, step)

    track_length = float(lap_df["lap_distance_m"].max())
    if track_length <= 0:
        track_length = float(trace.distance_m[-1]) if n > 0 else 1.0

    # Compute theoretical lap time from distance and speed
    dist = trace.distance_m
    speed = trace.speed_mps
    speed_safe = np.maximum(speed, 0.5)
    ds = np.diff(dist)
    avg_speed = (speed_safe[:-1] + speed_safe[1:]) / 2.0
    dt = ds / avg_speed
    theoretical_lap_time_s = float(np.sum(dt))

    ghost = {
        "version": 1,
        "track_name": session_meta.get("track_name", "Unknown"),
        "car_name": session_meta.get("car_name", "Unknown"),
        "theoretical_lap_time_s": round(theoretical_lap_time_s, 3),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_points": len(idx),
        "distance_pct": np.clip(trace.distance_m[idx] / track_length, 0.0, 1.0).round(6).tolist(),
        "speed_kph": (trace.speed_mps[idx] * 3.6).round(2).tolist(),
        "throttle_pct": trace.throttle_pct[idx].round(4).tolist(),
        "brake_pct": trace.brake_pct[idx].round(4).tolist(),
        "steering_deg": trace.steering_deg[idx].round(2).tolist(),
    }

    out_path = Path(output_dir) / "theoretical_ghost.json"
    with open(out_path, "w") as f:
        json.dump(ghost, f, indent=2)
    log.info("Ghost exported: %s (%d points, %.3fs)", out_path, len(idx), theoretical_lap_time_s)
    return str(out_path)

DEFAULT_SESSION = (
    r"C:\Users\Admin\Documents\LapCoachLogger_sessions"
    r"\2026-03-26_16-07-25__iRacing__Red_Bull_Ring__Offline_Testing"
)


def load_session(session_dir: str) -> tuple[pd.DataFrame, dict, list]:
    p = Path(session_dir)
    df = pd.read_csv(p / "telemetry.csv")
    with open(p / "session.json") as f:
        session = json.load(f)
    with open(p / "laps.json") as f:
        laps = json.load(f)
    return df, session, laps


def find_best_lap(df: pd.DataFrame, laps: list) -> int:
    candidates = []
    for lap in laps:
        lt = lap.get("lap_time_s", 9999)
        ln = lap.get("lap_number", -1)
        if ln > 0 and lt < 200:
            candidates.append((lt, ln))
    if not candidates:
        counts = df.groupby("lap_number").size()
        return int(counts.idxmax())
    candidates.sort()
    return candidates[0][1]


def build_track_geometry_from_normalized(lap_df: pd.DataFrame):
    from kart_envelope.track.geometry import TrackGeometry
    from scipy.ndimage import uniform_filter1d

    dist = lap_df["lap_distance_m"].values.astype(float)
    speed_mps = lap_df["speed_kmh"].values.astype(float) / 3.6
    lat_g = lap_df["lateral_g"].values.astype(float)

    sort_idx = np.argsort(dist)
    dist = dist[sort_idx]
    speed_mps = speed_mps[sort_idx]
    lat_g = lat_g[sort_idx]

    mask = np.diff(dist, prepend=-1) > 0.01
    dist = dist[mask]
    speed_mps = speed_mps[mask]
    lat_g = lat_g[mask]

    speed_safe = np.maximum(speed_mps, 3.0)
    # lat_g is already in m/s^2 — do NOT multiply by G
    lat_g = np.clip(lat_g, -30.0, 30.0)  # clamp outlier spikes
    kappa = np.abs(lat_g) / (speed_safe ** 2)
    kappa = uniform_filter1d(kappa, size=15)
    kappa = np.clip(kappa, 0.0, 0.1)

    ds = np.diff(dist, prepend=dist[0])
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)
    lap_length = float(dist[-1] - dist[0]) if len(dist) > 1 else 1000.0

    return TrackGeometry(
        distance_m=dist, curvature_1pm=kappa, heading_rad=heading,
        x_ref_m=x, y_ref_m=y, lap_length_m=lap_length, track_id="from_telemetry",
    )


def identify_vehicle_from_normalized(df: pd.DataFrame, config: SimOptimizerConfig) -> VehicleModel:
    n = len(df)
    speed_mps = (df["speed_kmh"].values / 3.6).astype(float)
    throttle = df["throttle"].values.astype(float)
    brake = df["brake"].values.astype(float)
    # NOTE: lateral_g / longitudinal_g columns are ALREADY in m/s^2 despite the name
    long_accel = np.clip(df["longitudinal_g"].values.astype(float), -30.0, 30.0)  # clamp outlier spikes
    lat_accel = np.clip(df["lateral_g"].values.astype(float), -30.0, 30.0)
    gear = df["gear"].values.astype(float)
    rpm = df["rpm"].values.astype(float)
    fuel = df["fuel_level"].values.astype(float)

    mass_model = identify_mass_model(
        speed_mps=speed_mps, long_accel=long_accel,
        throttle=throttle, fuel_level_l=fuel,
        bop_penalty_kg=np.zeros(n), config=config,
    )
    mass_kg = mass_model.total_mass_kg(float(np.median(fuel)))

    speed_safe = np.maximum(speed_mps, 1.0)
    curvature_est = np.abs(lat_accel) / (speed_safe ** 2)
    # Coast-down CdA identification is unreliable with engine braking contamination.
    # Use speed-squared regression on high-speed coast-down only, or fallback to
    # a reasonable GT3 default (CdA ~ 1.1-1.3 for modern GT3 cars).
    aero_model = identify_aero_model(
        speed_mps=speed_mps, long_accel=long_accel,
        throttle=throttle, brake=brake, curvature=curvature_est,
        air_density=np.full(n, 1.18), car_dist_ahead=np.full(n, 500.0),
        mass_kg=mass_kg, config=config,
    )
    # Pre-compute G values (needed for ClA estimation below)
    lat_g_g = np.abs(lat_accel) / _G
    long_g_g = long_accel / _G

    # Override: coast-down CdA is contaminated by engine braking.
    # Instead, estimate CdA from top-speed equilibrium:
    # At the highest speed where the car is barely accelerating (accel ~ 0),
    # drive_force = drag + rr. We know the drive force from the powertrain model.
    # CdA = 2 * (drive - rr) * m / (rho * v^2)
    top_speed_mask = (speed_mps > speed_mps.max() * 0.95) & (throttle > 0.9)
    if top_speed_mask.sum() > 20:
        v_top = float(np.median(speed_mps[top_speed_mask]))
        a_top = float(np.median(long_accel[top_speed_mask]))
        # At near-top-speed: a_measured = drive - drag - rr
        # So drive = a_measured + drag + rr
        # And at equilibrium (a=0): CdA = 2 * (drive_at_top) * m / (rho * v^2)
        # But we still need drive. Use the observed accel: at top speed, net accel = drive - drag - rr
        # If we had CdA, we could solve. Instead, iterate:
        rr_top = (config.powertrain_rr_c0 + config.powertrain_rr_c1 * v_top) * _G
        # Start from reasonable CdA, compute drive, check consistency
        # Simpler: use the fact that at the ACTUAL top speed (where accel ~ 0):
        # CdA = 2 * rr * m / (rho * v^2) would give only rolling resistance
        # But we're still accelerating, so the car hasn't topped out.
        # Best approach: find speed where accel crosses zero
        # For now, use a reasonable default based on car class
        cda_estimate = 0.85  # GT3 cars typically 0.8-1.0
        log.info("Using CdA=%.2f (GT3 default, top speed %.0f kph still accelerating at %.2f m/s^2)",
                 cda_estimate, v_top * 3.6, a_top)
    else:
        cda_estimate = 0.85

    # Estimate ClA from speed-dependent BRAKING grip increase.
    # Braking is always near-max-effort, unlike cornering where the driver
    # may not push at high speed. So braking G vs speed is the best aero signal.
    # grip(v) = mu_base * g * (1 + 0.5*rho*ClA*v^2 / (m*g))
    # At low speed: grip_lo = mu_base * g
    # At high speed: grip_hi = mu_base * g * (1 + downforce_factor)
    # ratio = grip_hi / grip_lo = 1 + 0.5*rho*ClA*v_hi^2 / (m*g)
    # ClA = (ratio - 1) * m * g / (0.5 * rho * v_hi^2)
    braking_mask = long_g_g < -0.3
    brake_g_abs = np.abs(long_g_g[braking_mask])
    brake_speed = speed_mps[braking_mask]

    lo_brake = (brake_speed > 15) & (brake_speed < 25)
    hi_brake = (brake_speed > 50) & (brake_speed < 65)
    if lo_brake.sum() > 20 and hi_brake.sum() > 20:
        grip_lo = float(np.percentile(brake_g_abs[lo_brake], 95))
        grip_hi = float(np.percentile(brake_g_abs[hi_brake], 95))
        v_hi_med = float(np.median(brake_speed[hi_brake]))
        if grip_lo > 0.5:
            ratio = grip_hi / grip_lo
            cla_est = max(0.0, (ratio - 1.0) * mass_kg * _G / (0.5 * 1.18 * v_hi_med**2))
            # Braking ratio overestimates ClA because brake temp, tyre temp,
            # and bias also contribute. Scale down by ~0.6 to compensate.
            cla_est = cla_est * 0.6
            cla_est = float(np.clip(cla_est, 0.0, 4.0))
            log.info("ClA from braking grip ratio: %.2f (lo=%.2fG @%dkph, hi=%.2fG @%dkph, ratio=%.2f)",
                     cla_est, grip_lo, int(20*3.6), grip_hi, int(v_hi_med*3.6), ratio)
        else:
            cla_est = 1.5
    else:
        cla_est = 1.5  # GT3 default

    if aero_model.cda > 1.5 or aero_model.source == "default":
        aero_model = AeroModel(cda=cda_estimate, cla=cla_est, air_density=aero_model.air_density, source="estimated")

    powertrain_model = identify_powertrain_model(
        rpm=rpm, gear=gear, throttle=throttle,
        speed_mps=speed_mps, long_accel=long_accel,
        mass_kg=mass_kg, config=config,
    )

    # Cross-check: compute observed peak power from telemetry.
    # Use a simple CdA estimate (0.85) for drag subtraction.
    cda_for_power = 0.85
    ft_mask = (throttle >= 0.95) & (long_accel > 0.5) & (speed_mps > 15)
    if ft_mask.sum() > 100:
        v_ft = speed_mps[ft_mask]
        a_ft = long_accel[ft_mask]
        drag_ft = 0.5 * 1.18 * cda_for_power * v_ft**2 / mass_kg
        rr_ft = (config.powertrain_rr_c0 + config.powertrain_rr_c1 * v_ft) * _G
        observed_power_w = (a_ft + drag_ft + rr_ft) * mass_kg * v_ft
        observed_peak_kw = float(np.percentile(observed_power_w, 95)) / 1000.0

        # Check model power at several representative speeds and take the max ratio
        max_ratio = 1.0
        for test_v in [30.0, 40.0, 50.0, 55.0]:
            test_g = powertrain_model.optimal_gear(test_v, mass_kg)
            model_a = powertrain_model.max_drive_accel(test_v, test_g, mass_kg)
            model_drag = 0.5 * 1.18 * cda_for_power * test_v**2 / mass_kg
            model_rr = (config.powertrain_rr_c0 + config.powertrain_rr_c1 * test_v) * _G
            model_power_kw = (model_a + model_drag + model_rr) * mass_kg * test_v / 1000.0
            if model_power_kw > 50:
                ratio = observed_peak_kw / model_power_kw
                max_ratio = max(max_ratio, ratio)

        if max_ratio > 1.05:
            log.info("Power scaling: observed_peak=%.0f kW, scaling torque by %.2f",
                     observed_peak_kw, max_ratio)
            for g_key in powertrain_model.gear_torque_maps:
                rpm_arr, torque_arr = powertrain_model.gear_torque_maps[g_key]
                powertrain_model.gear_torque_maps[g_key] = (rpm_arr, torque_arr * max_ratio)
        else:
            log.info("Power check: model matches observed (ratio=%.2f)", max_ratio)

    # Build observed acceleration envelope as a fallback/override.
    # The torque-map model underestimates at high speed (gears 3-5 have
    # sparse RPM data). Use the actual observed p90 full-throttle accel
    # per speed bin as a direct lookup, and override the model when it's lower.
    if ft_mask.sum() > 200:
        v_ft = speed_mps[ft_mask]
        a_ft = long_accel[ft_mask]
        # Build envelope: speed bins -> p90 accel
        bin_edges = np.arange(10, 70, 2.5)  # 10 to 67.5 m/s in 2.5 m/s bins
        env_speed = []
        env_accel = []
        for i in range(len(bin_edges) - 1):
            mask = (v_ft >= bin_edges[i]) & (v_ft < bin_edges[i + 1])
            if mask.sum() >= 10:
                env_speed.append((bin_edges[i] + bin_edges[i + 1]) / 2)
                env_accel.append(float(np.percentile(a_ft[mask], 80)))
        if len(env_speed) >= 5:
            env_speed_arr = np.array(env_speed)
            env_accel_arr = np.array(env_accel)
            # Monkey-patch the model: override max_drive_accel to use the envelope
            # when it produces more than the torque-map model
            _original_max_drive = powertrain_model.max_drive_accel
            def _patched_max_drive(speed_mps_val, gear_val, mass_kg_val,
                                    _orig=_original_max_drive,
                                    _env_s=env_speed_arr, _env_a=env_accel_arr):
                model_a = _orig(speed_mps_val, gear_val, mass_kg_val)
                # Observed envelope (includes drag+rr, so add those back for apples-to-apples)
                drag = 0.5 * 1.18 * 0.85 * speed_mps_val**2 / mass_kg_val
                rr = (0.012 + 0.00008 * speed_mps_val) * 9.80665
                env_net = float(np.interp(speed_mps_val, _env_s, _env_a))
                env_gross = env_net + drag + rr  # gross drive accel
                return max(model_a, env_gross)
            powertrain_model.max_drive_accel = _patched_max_drive
            log.info("Installed observed acceleration envelope (%d speed bins, %.0f-%.0f kph)",
                     len(env_speed), env_speed_arr[0]*3.6, env_speed_arr[-1]*3.6)

    brake_model = identify_brake_model(
        speed_mps=speed_mps, long_accel=long_accel,
        brake=brake, brake_raw=brake,
        abs_active=np.zeros(n, dtype=bool),
        brake_bias=np.full(n, 56.0), config=config,
    )

    suspension_model = SuspensionModel(
        spring_rate_lf=60000, spring_rate_rf=60000,
        spring_rate_lr=55000, spring_rate_rr=55000, static_defl_m=0.04,
    )

    # Lateral mu: use p95 — sustained peak cornering grip, excluding transient
    # spikes from kerbs/bumps. The alien lap IS the car limit; the theoretical
    # should match the alien, not exceed it.
    # Braking mu: use p97 — braking is more consistent and repeatable than cornering.
    mu_lat = float(np.percentile(lat_g_g[lat_g_g > 0.3], 95)) if np.sum(lat_g_g > 0.3) > 100 else 1.2
    long_brake_g = np.abs(long_g_g[long_g_g < -0.3])
    mu_long_brake = float(np.percentile(long_brake_g, 97)) if len(long_brake_g) > 100 else 1.2
    long_drive_g = long_g_g[(long_g_g > 0.2) & (throttle > 0.9)]
    mu_long_drive = float(np.percentile(long_drive_g, 97)) if len(long_drive_g) > 50 else 0.8
    mu_long = max(mu_long_drive, mu_long_brake)

    # Sim cars with downforce can exceed 2G — real GT3s do 1.8-2.2G lateral
    # with aero. The 1.8 clamp in config is for non-aero karts. Override here.
    tyre_model = TyreModel(
        mu_lat=float(np.clip(mu_lat, 0.8, 2.5)),
        mu_long=float(np.clip(mu_long, 0.8, 2.5)),
    )

    vehicle = VehicleModel(
        tyre=tyre_model, aero=aero_model, powertrain=powertrain_model,
        brake=brake_model, suspension=suspension_model, mass=mass_model,
    )

    log.info("Vehicle: mu_lat=%.2f, mu_long=%.2f, CdA=%.2f, mass=%.0fkg, brake=%.1f m/s2",
             tyre_model.mu_lat, tyre_model.mu_long, aero_model.cda,
             mass_kg, brake_model.max_decel_mps2)
    return vehicle


def run_optimizer(session_dir: str) -> dict:
    log.info("Loading session from %s", session_dir)
    df, session_meta, laps = load_session(session_dir)
    config = default_config()

    best_lap_num = find_best_lap(df, laps)
    log.info("Best lap: %d", best_lap_num)

    lap_df = df[df["lap_number"] == best_lap_num].copy().sort_values("lap_distance_m")
    lap_df = lap_df.drop_duplicates(subset="lap_distance_m", keep="first")
    lap_df = lap_df[lap_df["lap_distance_m"] > 0].reset_index(drop=True)
    log.info("Lap %d: %d samples, %.0f-%.0fm", best_lap_num, len(lap_df),
             lap_df["lap_distance_m"].min(), lap_df["lap_distance_m"].max())

    on_track = df[df["is_on_track"] == True].copy()
    vehicle = identify_vehicle_from_normalized(on_track, config)

    geometry = build_track_geometry_from_normalized(lap_df)
    log.info("Track: %.0fm, %d points", geometry.lap_length_m, len(geometry.distance_m))

    fuel = float(np.median(lap_df["fuel_level"].values))
    theoretical = compute_sim_theoretical_lap(geometry, vehicle, fuel_level_l=fuel, config=config)
    log.info("Theoretical lap: %.3fs", theoretical.lap_time_s)

    trace = reconstruct_inputs(theoretical, vehicle, geometry, fuel_level_l=fuel)

    # Fix steering: the reconstruction outputs road-wheel angle but the actual
    # telemetry is steering-wheel angle. Multiply by the steering ratio.
    # Also fix sign: the geometry has unsigned curvature, so the reconstruction
    # produces all-positive steering. Use the actual lateral G to determine turn direction.
    if trace is not None:
        # Steering ratio: compare actual steering range to theoretical
        actual_steer_range = np.degrees(np.abs(lap_df["steering"].values)).max()
        theo_steer_range = np.abs(trace.steering_deg).max()
        if theo_steer_range > 0.1:
            steering_ratio = actual_steer_range / theo_steer_range
            steering_ratio = np.clip(steering_ratio, 5.0, 25.0)  # GT3 typically 12-17:1
        else:
            steering_ratio = 14.0  # default GT3

        # Apply ratio
        trace.steering_deg = trace.steering_deg * steering_ratio

        # Fix sign: interpolate actual lateral G onto theoretical distance grid
        # and use its sign to determine turn direction
        actual_lat_g = np.interp(
            trace.distance_m,
            lap_df["lap_distance_m"].values,
            lap_df["lateral_g"].values,
        )
        # Positive lateral G = right turn = negative steering (convention)
        sign = np.where(actual_lat_g > 0.5, -1.0, np.where(actual_lat_g < -0.5, 1.0, 0.0))
        # Smooth the sign to avoid jitter near zero-crossings
        from scipy.ndimage import uniform_filter1d
        sign_smooth = uniform_filter1d(sign, size=11)
        sign_final = np.sign(sign_smooth)
        # Where sign is ambiguous (near straight), keep positive
        sign_final[sign_final == 0] = 1.0
        trace.steering_deg = np.abs(trace.steering_deg) * sign_final

        log.info("Steering fix: ratio=%.1f:1, range after=%.1f to %.1f deg",
                 steering_ratio, trace.steering_deg.min(), trace.steering_deg.max())

    actual_dist = lap_df["lap_distance_m"].values
    actual_speed_mps = lap_df["speed_kmh"].values / 3.6
    actual_throttle = lap_df["throttle"].values
    actual_brake = lap_df["brake"].values
    actual_steering_deg = np.degrees(lap_df["steering"].values)
    actual_gear = lap_df["gear"].values

    delta = compute_lap_delta(
        actual_dist, actual_speed_mps, actual_throttle, actual_brake, actual_steering_deg,
        trace.distance_m, trace.speed_mps, trace.throttle_pct, trace.brake_pct, trace.steering_deg,
    )

    n_theo = len(trace.distance_m)
    n_actual = len(actual_dist)
    step_theo = max(1, n_theo // 500)
    step_actual = max(1, n_actual // 500)

    # Export ghost trace for logger overlay
    export_ghost_json(trace, session_meta, lap_df, session_dir)

    actual_lap_time = 0.0
    if best_lap_num < len(laps):
        actual_lap_time = float(laps[best_lap_num].get("lap_time_s", 0))

    return {
        "session": {
            "track": session_meta.get("track_name", "Unknown"),
            "car": session_meta.get("car_name", "Unknown"),
            "best_lap": best_lap_num,
            "actual_lap_time_s": actual_lap_time,
            "theoretical_lap_time_s": round(theoretical.lap_time_s, 3),
        },
        "vehicle": vehicle.to_dict(),
        "theoretical": {
            "distance_m": trace.distance_m[::step_theo].tolist(),
            "speed_kph": (trace.speed_mps[::step_theo] * 3.6).tolist(),
            "throttle": trace.throttle_pct[::step_theo].tolist(),
            "brake": trace.brake_pct[::step_theo].tolist(),
            "steering_deg": trace.steering_deg[::step_theo].tolist(),
            "gear": trace.gear[::step_theo].tolist(),
        },
        "actual": {
            "distance_m": actual_dist[::step_actual].tolist(),
            "speed_kph": (actual_speed_mps[::step_actual] * 3.6).tolist(),
            "throttle": actual_throttle[::step_actual].tolist(),
            "brake": actual_brake[::step_actual].tolist(),
            "steering_deg": actual_steering_deg[::step_actual].tolist(),
            "gear": actual_gear[::step_actual].tolist(),
        },
        "delta": {
            "distance_m": delta.distance_m[::max(1, len(delta.distance_m)//500)].tolist(),
            "time_delta_s": delta.time_delta_s[::max(1, len(delta.time_delta_s)//500)].tolist(),
            "speed_delta_kph": (delta.speed_delta_mps[::max(1, len(delta.speed_delta_mps)//500)] * 3.6).tolist(),
            "total_time_loss_s": round(delta.total_time_loss_s, 3),
        },
    }


def serve_preview(result: dict, port: int = 8899):
    from telemetry_tool.sim_optimizer._preview_html import build_preview_html

    html = build_preview_html(result)
    output_path = PROJECT_ROOT / "scripts" / "optimizer_preview.html"
    output_path.write_text(html, encoding="utf-8")
    log.info("Preview saved to %s", output_path)

    os.chdir(str(output_path.parent))
    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    url = f"http://localhost:{port}/optimizer_preview.html"
    log.info("Serving at %s", url)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    session_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION
    result = run_optimizer(session_dir)
    dt = result["session"]["actual_lap_time_s"] - result["session"]["theoretical_lap_time_s"]
    print(f"\n{'='*60}")
    print(f"Track:       {result['session']['track']}")
    print(f"Car:         {result['session']['car']}")
    print(f"Your lap:    {result['session']['actual_lap_time_s']:.3f}s")
    print(f"Theoretical: {result['session']['theoretical_lap_time_s']:.3f}s")
    print(f"Delta:       {'+' if dt > 0 else ''}{dt:.3f}s")
    print(f"{'='*60}\n")
    serve_preview(result)
