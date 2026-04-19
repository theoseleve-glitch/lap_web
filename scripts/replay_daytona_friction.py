"""First real-data replay of the friction estimation pipeline on the
74-lap Daytona McLaren GT4 session.

Runs the full chain:
  .ibt → wheel_kinematics → tire_model → surface_inverse_solver → surface_field

Outputs diagnostics to stdout and a JSON report for inspection.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))

from lap_oracle.extractors.iracing_ibt import _parse_header, _parse_var_headers
from track_surface.surface_field import SurfaceField, SurfaceFieldConfig
from track_surface.surface_inverse_solver import (
    ExcitationConfig,
    solve_lambda_surface,
)
from track_surface.tire_model import TireInputs, TireParams, TireState
from track_surface.wheel_kinematics.dataclasses import CarGeometry, RoadFramePose
from track_surface.wheel_kinematics.slip_angles import compute_slip_angles

IBT_PATH = Path(
    "C:/Users/Admin/Documents/iRacing/telemetry/"
    "mclaren570sgt4_daytona 2011 road 2026-01-09 23-40-48.ibt"
)
OUT_PATH = _PROJECT_ROOT / "daytona_friction_report.json"

G = 9.80665
EARTH_R = 6371000.0
TYPE_DTYPE = {1: np.uint8, 2: np.int32, 3: np.uint32, 4: np.float32, 5: np.float64}
TYPE_SIZE = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


def extract_channels(path: Path) -> dict[str, np.ndarray]:
    with open(path, "rb") as f:
        header_bytes = f.read(max(4096, 144 * 500 + 200))
        hdr = _parse_header(header_bytes)
        vars_map = _parse_var_headers(header_bytes, hdr)
        file_size = os.path.getsize(path)
        num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
        f.seek(hdr["data_start"])
        raw = f.read(hdr["buf_len"] * num_samples)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(num_samples, hdr["buf_len"])

    data = {}
    for name, info in vars_map.items():
        if info.get("count", 1) != 1:
            continue
        t = info["type"]
        if t not in TYPE_SIZE:
            continue
        off, sz, dt = info["offset"], TYPE_SIZE[t], TYPE_DTYPE[t]
        data[name] = np.frombuffer(arr[:, off:off + sz].tobytes(), dtype=dt).astype(np.float64)
    return data


def extract_setup_yaml(path: Path) -> dict:
    """Parse the CarSetup section from the .ibt session info."""
    with open(path, "rb") as f:
        header = f.read(200)
        sil = struct.unpack_from("<i", header, 16)[0]
        sio = struct.unpack_from("<i", header, 20)[0]
        f.seek(sio)
        text = f.read(sil).decode("latin-1", errors="replace")

    setup = {}
    lines = text.split("\n")
    in_setup = False
    for line in lines:
        if "CarSetup:" in line:
            in_setup = True
            continue
        if in_setup:
            stripped = line.strip()
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                setup[key.strip()] = val.strip()
    return setup


def main() -> None:
    t_total = time.perf_counter()
    print(f"Processing: {IBT_PATH.name}")

    # ── 1. Extract ───────────────────────────────────────────
    t0 = time.perf_counter()
    ch = extract_channels(IBT_PATH)
    N = len(ch["Lat"])
    print(f"Extracted {N:,} samples in {time.perf_counter() - t0:.1f}s")

    # Valid mask
    valid = (
        ch["IsOnTrack"].astype(bool)
        & (ch["Lat"] != 0.0)
        & (ch["Lon"] != 0.0)
        & (ch["Speed"] > 5.0)
    )
    print(f"Valid on-track samples (v>5): {valid.sum():,}")

    # ── 2. Setup geometry ────────────────────────────────────
    # From the setup YAML we already discovered:
    geom = CarGeometry(
        wheelbase_m=2.67,
        track_front_m=1.666,
        track_rear_m=1.627,
        cg_to_front_m=2.67 * (1.0 - 0.435),  # NoseWeight 43.5%
        cg_to_rear_m=2.67 * 0.435,
        steer_ratio=14.0,
        max_steer_rad=0.5,
        camber_fl_rad=np.radians(-4.0),
        camber_fr_rad=np.radians(-4.0),
        camber_rl_rad=np.radians(-2.8),
        camber_rr_rad=np.radians(-2.8),
    )
    print(f"Geometry: wb={geom.wheelbase_m}, a={geom.cg_to_front_m:.3f}, "
          f"b={geom.cg_to_rear_m:.3f}")

    # Scale tire D to session data: the raw lambda distribution peaks at ~2.0,
    # meaning the default D (1.4) is ~2× too low. This is expected because:
    #   1. Daytona banking adds gravitational lateral force to a_lat
    #   2. GT4 on well-rubbered track can exceed "standard" tire peak
    #   3. Aero downforce increases effective grip beyond pure tire mu
    # A proper road_state_estimator would separate (1) and (3) from the
    # surface lambda. For now, scale D to center lambda near 1.0.
    tire_params = TireParams(
        d1_lat=2.8,   # scaled from 1.4 by ~2× to match session
        d1_long=2.7,  # scaled similarly
        d2_lat=-0.0001,  # slightly stronger load sensitivity
        d2_long=-0.0001,
    )
    excitation_config = ExcitationConfig()

    # ── 3. Per-wheel loads (from adaptive model) ─────────────
    # Reuse the simple load model (not the full adaptive — keep this diagnostic clean)
    from track_surface.physics_grip import (
        build_vehicle_geometry,
        compute_per_wheel_normal_loads,
        compute_per_wheel_tangential_forces,
    )

    phys_geom = build_vehicle_geometry(
        None,
        shock_defl_mean=None,
        cg_height_default=0.15,  # from adaptive calibration
        weight_dist_front_default=0.435,
    )

    speed = ch["Speed"][valid]
    a_long = ch["LongAccel"][valid]
    a_lat = ch["LatAccel"][valid]
    roll = ch["Roll"][valid]
    pitch = ch["Pitch"][valid]
    steer = ch["SteeringWheelAngle"][valid]
    vx = ch.get("VelocityX", np.zeros(N))[valid]
    vy = ch.get("VelocityY", np.zeros(N))[valid]
    yaw_rate = ch["YawRate"][valid]

    # ── Road state estimation (separate banking from tire forces) ──
    from track_surface.road_state_estimator import estimate_road_state_batch, RoadEstimatorConfig
    print(f"\nEstimating road state (bank/grade separation)...")
    t0 = time.perf_counter()
    road_config = RoadEstimatorConfig(
        roll_compliance_rad_per_mps2=0.005,
        pitch_compliance_rad_per_mps2=0.003,
        smooth_window=60,  # 1 second at 60 Hz
    )
    bank_est, grade_est, a_lat_tire, a_long_tire, road_quality = estimate_road_state_batch(
        speed=speed, a_lat=a_lat, a_long=a_long,
        yaw_rate=yaw_rate, roll=roll, pitch=pitch,
        config=road_config,
    )
    print(f"  Done in {time.perf_counter() - t0:.1f}s")
    print(f"  Banking range: [{np.degrees(bank_est.min()):+.1f}, {np.degrees(bank_est.max()):+.1f}] deg")
    print(f"  Grade range:   [{np.degrees(grade_est.min()):+.1f}, {np.degrees(grade_est.max()):+.1f}] deg")
    print(f"  a_lat raw mean:  {a_lat.mean():+.2f} m/s2")
    print(f"  a_lat tire mean: {a_lat_tire.mean():+.2f} m/s2  (banking gravity removed)")
    print(f"  Gravity component: mean={(G * np.sin(bank_est)).mean():+.2f} m/s2")

    # ── Build ride heights early (needed for roll compliance + validation) ─
    rh_available = all(k in ch for k in ["LFrideHeight", "RFrideHeight", "LRrideHeight", "RRrideHeight"])
    ride_heights = None
    if rh_available:
        ride_heights = np.column_stack([
            ch["LFrideHeight"][valid],
            ch["RFrideHeight"][valid],
            ch["LRrideHeight"][valid],
            ch["RRrideHeight"][valid],
        ])

    # ── Roll compliance fitting ────────────────────────────────
    from track_surface.roll_compliance_fit import fit_roll_compliance
    print(f"\nFitting roll compliance from ride height vs a_lat...")
    if ride_heights is not None:
        bank_grad_for_fit = np.abs(np.gradient(bank_est))
        rc_result = fit_roll_compliance(
            ride_heights=ride_heights,
            a_lat_tire=a_lat_tire,
            bank_rad=bank_est,
            bank_gradient=bank_grad_for_fit,
            speed=speed,
            transition_mask=np.abs(bank_grad_for_fit) > 0.008,
            road_quality=road_quality,
            current_compliance=road_config.roll_compliance_rad_per_mps2,
        )
        print(f"  Compliance: {road_config.roll_compliance_rad_per_mps2:.4f} → {rc_result.compliance_rad_per_mps2:.4f} rad/m/s²")
        print(f"  Flat residual:   {rc_result.flat_residual_before:.4f} → {rc_result.flat_residual_after:.4f}")
        print(f"  Banked residual: {rc_result.banked_residual_before:.4f} → {rc_result.banked_residual_after:.4f}")
        print(f"  Samples: flat={rc_result.n_samples_flat}, banked={rc_result.n_samples_banked}")
        print(f"  Recommendation: {rc_result.recommendation}")

        # Rerun road state estimator with fitted compliance
        road_config.roll_compliance_rad_per_mps2 = rc_result.compliance_rad_per_mps2
        print(f"\n  Rerunning road state estimator with fitted compliance...")
        bank_est, grade_est, a_lat_tire, a_long_tire, road_quality = estimate_road_state_batch(
            speed=speed, a_lat=a_lat, a_long=a_long,
            yaw_rate=yaw_rate, roll=roll, pitch=pitch,
            config=road_config,
        )
        print(f"  Banking range (refitted): [{np.degrees(bank_est.min()):+.1f}, {np.degrees(bank_est.max()):+.1f}] deg")
        print(f"  a_lat tire mean (refitted): {a_lat_tire.mean():+.2f} m/s2")
    else:
        print("  No ride height data — skipping roll compliance fit")

    # Use the tire-only accelerations for the rest of the pipeline
    a_lat_for_forces = a_lat_tire
    a_long_for_forces = a_long_tire

    # Transition quarantine: samples where bank gradient is high
    # get reduced confidence when fed into the surface field later
    bank_gradient = np.abs(np.gradient(bank_est))
    transition_mask = bank_gradient > 0.008  # ~0.46 deg/sample (only sharp transitions)
    n_transition = transition_mask.sum()
    print(f"  Transition-quarantined samples: {n_transition:,} ({n_transition/len(bank_est)*100:.1f}%)")

    print(f"\nComputing per-wheel loads ({valid.sum():,} samples)...")
    t0 = time.perf_counter()
    loads = compute_per_wheel_normal_loads(
        mass_kg=1222.5,
        speed_mps=speed,
        a_long_body=a_long_for_forces,  # tire-only (grade gravity removed)
        a_lat_body=a_lat_for_forces,    # tire-only (banking gravity removed)
        roll_rad=roll,
        pitch_rad=pitch,
        aero_cla=1.46,
        air_density=1.225,
        geom=phys_geom,
    )
    f_tang = compute_per_wheel_tangential_forces(
        mass_kg=1222.5,
        fz_per_wheel=loads.fz,
        a_long_body=a_long_for_forces,
        a_lat_body=a_lat_for_forces,
        brake_line_press=None,
        brake_bias_front=0.49,
        drive_rear_only=True,
    )
    print(f"  Done in {time.perf_counter() - t0:.1f}s")

    # Per-wheel observed forces (for the inverse solver)
    # Split total body force by Fz ratio (same as compute_per_wheel_tangential_forces
    # but we need Fx and Fy separately, not magnitude)
    fz_sum = np.maximum(loads.fz.sum(axis=1), 1.0)
    fx_obs = np.zeros_like(loads.fz)
    fy_obs = np.zeros_like(loads.fz)
    # Use TIRE-ONLY lateral accel (banking gravity already removed by road estimator).
    # Still negate for sign convention: iRacing → bicycle model.
    f_lat_total = 1222.5 * (-a_lat_for_forces)
    f_long_total = 1222.5 * a_long_for_forces
    for w in range(4):
        fy_obs[:, w] = f_lat_total * loads.fz[:, w] / fz_sum
        fx_obs[:, w] = f_long_total * loads.fz[:, w] / fz_sum

    # ── 4. Wheel kinematics (slip angles) ────────────────────
    print("\nComputing slip angles...")
    t0 = time.perf_counter()
    n_samples = valid.sum()

    # iRacing VelocityX/Y/Z are in WORLD frame, not body frame.
    # Rotate into body frame using Yaw angle:
    #   vx_body = Vx_world × cos(yaw) + Vy_world × sin(yaw)
    #   vy_body = -Vx_world × sin(yaw) + Vy_world × cos(yaw)
    yaw = ch["Yaw"][valid]
    if np.any(vx != 0):
        cos_y = np.cos(yaw)
        sin_y = np.sin(yaw)
        # iRacing: VelocityX = forward in world? No — check documentation.
        # Actually iRacing VelocityX/Y/Z appear to be in the SAE body frame:
        #   X = forward, Y = rightward, Z = downward
        # But the sign conventions need verification.
        # Safest approach: use Speed for vx, derive vy from a_lat integral or
        # from the sideslip implicit in Speed vs VelocityX/Y.
        #
        # For v1: use Speed as vx (reliable), estimate vy from
        # a_lat and yaw_rate via the relationship:
        #   a_lat_body ≈ vy_dot + vx × yaw_rate
        # At steady state: vy_dot ≈ 0, so vy ≈ (a_lat - vx × yaw_rate) × dt
        # More robustly: vy ≈ a_lat / yaw_rate - vx for small angles
        # But simplest: use the kinematic sideslip from Speed + yaw_rate:
        #   beta ≈ integral(a_lat / vx - yaw_rate) dt
        #
        # For now: use the most robust estimate — Speed for vx, and
        # compute a rough vy from the force balance at steady state.
        vx_body = speed

        # Beta estimator: complementary filter with offline smoothing
        from track_surface.beta_estimator import estimate_beta_offline_smooth
        print(f"  Running beta estimator (offline smoother)...")
        t_beta = time.perf_counter()
        vy_est, beta_est, beta_std, beta_quality = estimate_beta_offline_smooth(
            speed=speed,
            yaw_rate=yaw_rate,
            a_lat_tire=a_lat_tire,
            cg_to_rear_m=geom.cg_to_rear_m,
            dt=1.0 / 60.0,
            road_quality=road_quality,
        )
        vy_body = vy_est
        print(f"  Beta estimator done in {time.perf_counter() - t_beta:.1f}s")
        print(f"  beta range: [{beta_est.min():.4f}, {beta_est.max():.4f}] rad")
        print(f"  beta mean:  {beta_est.mean():.4f} rad")
        print(f"  vy range:   [{vy_est.min():.3f}, {vy_est.max():.3f}] m/s")
        print(f"  beta quality mean: {beta_quality.mean():.3f}")
        print(f"  beta std mean:     {beta_std.mean():.4f} rad")
    else:
        vx_body = speed
        vy_body = np.zeros_like(speed)

    # Per-sample slip angles (subsample for speed — every 10th sample)
    step = 10
    n_sub = n_samples // step
    alpha_per_wheel = np.zeros((n_samples, 4))
    kappa_per_wheel = None  # no wheel speeds available

    for i in range(0, n_samples, step):
        wk = compute_slip_angles(
            vx_body=float(vx_body[i]),
            vy_body=float(vy_body[i]),
            yaw_rate=float(yaw_rate[i]),
            steer_wheel_rad=float(steer[i]),
            geom=geom,
        )
        # Fill the step-sized block with the same value (cheaper than per-sample)
        end = min(i + step, n_samples)
        if wk.alpha_fl is not None:
            alpha_per_wheel[i:end, 0] = wk.alpha_fl
            alpha_per_wheel[i:end, 1] = wk.alpha_fr
            alpha_per_wheel[i:end, 2] = wk.alpha_rl
            alpha_per_wheel[i:end, 3] = wk.alpha_rr
        else:
            alpha_per_wheel[i:end, 0] = wk.alpha_f_axle
            alpha_per_wheel[i:end, 1] = wk.alpha_f_axle
            alpha_per_wheel[i:end, 2] = wk.alpha_r_axle
            alpha_per_wheel[i:end, 3] = wk.alpha_r_axle

    print(f"  Done in {time.perf_counter() - t0:.1f}s")
    print(f"  alpha_f range: [{alpha_per_wheel[:, 0].min():.4f}, {alpha_per_wheel[:, 0].max():.4f}] rad")
    print(f"  alpha_r range: [{alpha_per_wheel[:, 2].min():.4f}, {alpha_per_wheel[:, 2].max():.4f}] rad")

    # ── 5. Surface inverse solver ────────────────────────────
    print("\nRunning surface inverse solver...")
    t0 = time.perf_counter()

    lambda_per_sample = np.full(n_samples, np.nan)
    conf_per_sample = np.zeros(n_samples)
    excitation_per_sample = np.zeros(n_samples)
    n_accepted = 0
    n_rejected = 0
    reject_reasons_count: dict[str, int] = {}

    camber_arr = np.array([
        geom.camber_fl_rad, geom.camber_fr_rad,
        geom.camber_rl_rad, geom.camber_rr_rad,
    ])

    for i in range(0, n_samples, step):
        wheel_lambdas = []
        wheel_confs = []
        wheel_excitations = []

        for w in range(4):
            inp = TireInputs(
                alpha=float(alpha_per_wheel[i, w]),
                kappa=None,
                fz=float(loads.fz[i, w]),
                camber=float(camber_arr[w]),
                vx=float(speed[i]),
            )
            est = solve_lambda_surface(
                fx_obs=float(fx_obs[i, w]),
                fy_obs=float(fy_obs[i, w]),
                tire_input=inp,
                tire_params=tire_params,
                config=excitation_config,
            )

            if est.lambda_surface is not None:
                wheel_lambdas.append(est.lambda_surface)
                wheel_confs.append(est.confidence)
            wheel_excitations.append(est.excitation)

            if est.flags.get("rejected"):
                for reason in est.flags.get("reject_reasons", []):
                    reject_reasons_count[reason] = reject_reasons_count.get(reason, 0) + 1

        if wheel_lambdas:
            # Confidence-weighted mean across wheels
            w_arr = np.array(wheel_confs)
            l_arr = np.array(wheel_lambdas)
            lam = float(np.sum(l_arr * w_arr) / np.sum(w_arr))
            conf = float(np.mean(w_arr))

            end = min(i + step, n_samples)
            lambda_per_sample[i:end] = lam
            conf_per_sample[i:end] = conf
            n_accepted += 1
        else:
            n_rejected += 1

        if wheel_excitations:
            end = min(i + step, n_samples)
            excitation_per_sample[i:end] = np.mean(wheel_excitations)

    print(f"  Done in {time.perf_counter() - t0:.1f}s")
    print(f"  Accepted: {n_accepted:,} / {n_accepted + n_rejected:,} subsampled blocks")
    print(f"  Reject reasons: {reject_reasons_count}")

    valid_lambda = lambda_per_sample[np.isfinite(lambda_per_sample)]
    if len(valid_lambda) > 0:
        print(f"\n  lambda_surface statistics:")
        print(f"    count:  {len(valid_lambda):,}")
        print(f"    mean:   {valid_lambda.mean():.4f}")
        print(f"    std:    {valid_lambda.std():.4f}")
        print(f"    median: {np.median(valid_lambda):.4f}")
        print(f"    p5/p95: {np.percentile(valid_lambda, 5):.4f} / {np.percentile(valid_lambda, 95):.4f}")
        print(f"    min/max:{valid_lambda.min():.4f} / {valid_lambda.max():.4f}")
    else:
        print("  NO valid lambda recovered — estimator is fully rejecting. Check excitation gates.")
        return

    # ── 5c. Tire D scale fitting ────────────────────────────────
    from track_surface.tire_parameter_fit import (
        curate_calibration_set, fit_lateral_d_scale, apply_d_scale, CurationConfig
    )
    print("\nFitting tire lateral D scale factor...")

    bank_grad = np.abs(np.gradient(bank_est))
    curation = curate_calibration_set(
        bank_rad=bank_est,
        bank_gradient=bank_grad,
        a_lat_tire=a_lat_for_forces,
        speed=speed,
        beta_quality=beta_quality,
        road_quality=road_quality,
        fz_per_wheel=loads.fz,
        alpha_per_wheel=alpha_per_wheel,
        transition_mask=transition_mask,
    )
    print(f"  Curated: {curation.n_selected:,} / {curation.n_total:,} samples")
    for reason, count in sorted(curation.exclusion_reasons.items(), key=lambda x: -x[1])[:5]:
        print(f"    excluded by {reason}: {count:,}")

    fit = fit_lateral_d_scale(
        lambda_raw=lambda_per_sample,
        confidence=conf_per_sample,
        curation_mask=curation.mask,
        lap_numbers=ch["Lap"][valid].astype(int),
    )
    print(f"\n  FIT RESULT:")
    print(f"    k_lat:             {fit.k_lat:.4f} ± {fit.k_lat_std:.4f}")
    print(f"    D_lat new:         {apply_d_scale(tire_params.d1_lat, fit.k_lat):.4f}")
    print(f"    train median:      {fit.train_median_lambda_before:.3f} → {fit.train_median_lambda_after:.3f}")
    print(f"    validation median: {fit.validation_median_lambda_before:.3f} → {fit.validation_median_lambda_after:.3f}")
    print(f"    residual:          {fit.residual_before:.4f} → {fit.residual_after:.4f}")
    print(f"    n_train={fit.n_train:,}, n_val={fit.n_validation:,}")
    if fit.identifiability_note:
        print(f"    NOTE: {fit.identifiability_note}")

    # Apply the fitted D and rerun the inverse solver
    print(f"\n  Rerunning inverse solver with fitted D...")
    tire_params_fitted = TireParams(
        d1_lat=apply_d_scale(tire_params.d1_lat, fit.k_lat),
        d1_long=tire_params.d1_long,
        d2_lat=tire_params.d2_lat,
        d2_long=tire_params.d2_long,
        b_lat=tire_params.b_lat,
        c_lat=tire_params.c_lat,
        b_long=tire_params.b_long,
        c_long=tire_params.c_long,
    )
    print(f"  D_lat: {tire_params.d1_lat:.3f} → {tire_params_fitted.d1_lat:.3f}")

    # Redo the inverse solver with fitted params
    lambda_fitted = np.full(n_samples, np.nan)
    conf_fitted = np.zeros(n_samples)
    n_acc_fitted = 0
    for i in range(0, n_samples, step):
        wheel_lambdas = []
        wheel_confs = []
        for w in range(4):
            inp = TireInputs(
                alpha=float(alpha_per_wheel[i, w]),
                kappa=None,
                fz=float(loads.fz[i, w]),
                camber=float(camber_arr[w]),
                vx=float(speed[i]),
            )
            est = solve_lambda_surface(
                fx_obs=float(fx_obs[i, w]),
                fy_obs=float(fy_obs[i, w]),
                tire_input=inp,
                tire_params=tire_params_fitted,
                config=excitation_config,
            )
            if est.lambda_surface is not None:
                wheel_lambdas.append(est.lambda_surface)
                wheel_confs.append(est.confidence)
        if wheel_lambdas:
            w_arr = np.array(wheel_confs)
            l_arr = np.array(wheel_lambdas)
            lam = float(np.sum(l_arr * w_arr) / np.sum(w_arr))
            conf = float(np.mean(w_arr))
            end = min(i + step, n_samples)
            lambda_fitted[i:end] = lam
            conf_fitted[i:end] = conf
            n_acc_fitted += 1

    valid_lam_fitted = lambda_fitted[np.isfinite(lambda_fitted)]
    print(f"  Fitted lambda: mean={valid_lam_fitted.mean():.4f}, "
          f"median={np.median(valid_lam_fitted):.4f}, "
          f"p5/p95={np.percentile(valid_lam_fitted,5):.4f}/{np.percentile(valid_lam_fitted,95):.4f}")

    # Use the FITTED lambda for the field
    lambda_per_sample = lambda_fitted
    conf_per_sample = conf_fitted

    # ── 6. Build surface field ───────────────────────────────
    print("\nBuilding surface field...")
    t0 = time.perf_counter()

    # Project to local meters
    lat_rad = np.radians(ch["Lat"][valid])
    lon_rad = np.radians(ch["Lon"][valid])
    lat_ref = float(np.nanmean(lat_rad))
    lon_ref = float(np.nanmean(lon_rad))
    x_m = EARTH_R * (lon_rad - lon_ref) * np.cos(lat_ref)
    y_m = EARTH_R * (lat_rad - lat_ref)

    # Build Frenet frame from best lap for (s, n) projection
    from track_surface.centerline import extract_centerline
    from track_surface.frenet import FrenetFrame

    lap = ch["Lap"][valid]
    session_time = ch["SessionTime"][valid]
    lap_dist_pct = ch["LapDistPct"][valid]

    unique_laps = np.unique(lap[lap > 0])
    lap_times = {}
    for lnum in unique_laps:
        mask = lap == lnum
        if mask.sum() < 500:
            continue
        pct = lap_dist_pct[mask]
        if pct.max() - pct.min() < 0.95:
            continue
        lap_times[int(lnum)] = float(session_time[mask][-1] - session_time[mask][0])

    best_lap = min(lap_times.keys(), key=lambda k: lap_times[k])
    best_mask = lap == best_lap
    cl_xy = np.column_stack([x_m[best_mask], y_m[best_mask]])
    cl, total_length = extract_centerline([cl_xy], ds_m=2.0)
    frenet = FrenetFrame.from_centerline(cl)
    print(f"  Frenet: {frenet.n_points} pts, {total_length:.0f}m")

    # Project all samples to (s, n)
    s_proj, n_proj = frenet.xy_to_sn(x_m, y_m)

    # Build field
    ds_field = 5.0
    dn_field = 1.0
    n_range = 12.0
    s_bins = np.arange(0, total_length + ds_field, ds_field)
    n_bins = np.arange(-n_range, n_range + dn_field, dn_field)

    field = SurfaceField(s_bins, n_bins, SurfaceFieldConfig(
        condition_label="dry",
        compound_label="gt4_dry",
    ))

    # Feed lambda estimates into the field
    # Apply transition quarantine: reduce confidence for banking-transition samples
    conf_adjusted = conf_per_sample.copy()
    conf_adjusted[transition_mask] *= 0.2  # 80% penalty at transitions

    has_lambda = np.isfinite(lambda_per_sample)
    n_fed = field.update_batch(
        s_proj[has_lambda], n_proj[has_lambda],
        lambda_per_sample[has_lambda], conf_adjusted[has_lambda],
        obs_variance=0.04,
    )
    print(f"  Fed {n_fed:,} observations into field")

    # Spatial smoothing
    field.apply_spatial_smoothing()

    summary = field.summary()
    print(f"\n  Surface field summary:")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"    {k}: {v:.4f}")
        else:
            print(f"    {k}: {v}")

    # ── 7. Diagnostics ───────────────────────────────────────
    print("\n" + "=" * 60)
    print("DIAGNOSTIC CHECKS")
    print("=" * 60)

    # Check 1: lambda should be in a believable band
    print(f"\n[CHECK 1] Lambda range sanity")
    print(f"  Mean: {valid_lambda.mean():.3f} (expect ~0.8-1.3)")
    print(f"  Std:  {valid_lambda.std():.3f} (expect < 0.3)")
    in_band = (valid_lambda > 0.5) & (valid_lambda < 1.8)
    print(f"  In [0.5, 1.8]: {in_band.sum():,} / {len(valid_lambda):,} "
          f"({in_band.mean()*100:.1f}%)")

    # Check 2: Racing line structure
    print(f"\n[CHECK 2] Racing line structure")
    # Query lambda at n=0 (center) vs n=±5 (off-line)
    s_sample = np.linspace(100, total_length - 100, 50)
    center_lam = [field.query(float(s), 0.0)[0] for s in s_sample]
    left_lam = [field.query(float(s), 4.0)[0] for s in s_sample]
    right_lam = [field.query(float(s), -4.0)[0] for s in s_sample]
    print(f"  Center (n=0):  mean={np.mean(center_lam):.4f}")
    print(f"  Left (n=+4):   mean={np.mean(left_lam):.4f}")
    print(f"  Right (n=-4):  mean={np.mean(right_lam):.4f}")
    if np.mean(center_lam) > np.mean(left_lam):
        print(f"  -> Racing line (center) shows HIGHER lambda than off-line: GOOD")
    else:
        print(f"  -> Racing line NOT higher than off-line: check lateral decomposition")

    # Check 3: Confidence distribution
    print(f"\n[CHECK 3] Confidence distribution")
    conf_map = field.confidence_map
    print(f"  Cells with confidence > 0.5: {(conf_map > 0.5).sum()} / {conf_map.size}")
    print(f"  Cells with confidence > 0.1: {(conf_map > 0.1).sum()} / {conf_map.size}")
    print(f"  Cells with confidence = 0:   {(conf_map == 0).sum()} / {conf_map.size}")
    print(f"  Mean confidence: {conf_map.mean():.3f}")

    # Check 4: Per-lap consistency
    print(f"\n[CHECK 4] Per-lap lambda stability")
    lap_lambdas = {}
    for lnum in list(lap_times.keys())[:10]:
        mask = (lap == lnum) & has_lambda
        if mask.sum() > 50:
            lap_lambdas[lnum] = float(np.nanmean(lambda_per_sample[mask]))
    if lap_lambdas:
        vals = list(lap_lambdas.values())
        print(f"  Per-lap mean lambda (first 10 laps):")
        for lnum, lam in sorted(lap_lambdas.items()):
            print(f"    Lap {lnum:3d}: {lam:.4f}")
        print(f"  Lap-to-lap std: {np.std(vals):.4f} (expect < 0.1)")

    # ── 8. Residual diagnostics ────────────────────────────────
    print("\n" + "=" * 60)
    print("RESIDUAL DIAGNOSTICS")
    print("=" * 60)

    # Collect per-sample diagnostics for accepted blocks only
    diag_alpha = []
    diag_fy_pred = []
    diag_fy_obs = []
    diag_fx_pred = []
    diag_fx_obs = []
    diag_fz = []
    diag_lambda_raw = []
    diag_speed_at = []
    diag_a_lat_at = []

    from track_surface.tire_model import predict_tire_forces
    for i in range(0, n_samples, step):
        if not np.isfinite(lambda_per_sample[i]):
            continue
        # Use wheel 0 (FL) as the diagnostic reference
        w = 0
        inp = TireInputs(
            alpha=float(alpha_per_wheel[i, w]),
            kappa=None,
            fz=float(loads.fz[i, w]),
            camber=float(camber_arr[w]),
            vx=float(speed[i]),
        )
        pred = predict_tire_forces(inp, tire_params)
        diag_alpha.append(float(alpha_per_wheel[i, w]))
        diag_fy_pred.append(pred.fy)
        diag_fy_obs.append(float(fy_obs[i, w]))
        diag_fx_pred.append(pred.fx)
        diag_fx_obs.append(float(fx_obs[i, w]))
        diag_fz.append(float(loads.fz[i, w]))
        diag_speed_at.append(float(speed[i]))
        diag_a_lat_at.append(float(a_lat[i]))
        # Raw lambda (before clamp)
        fp = np.sqrt(pred.fx**2 + pred.fy**2)
        fo = np.sqrt(float(fx_obs[i, w])**2 + float(fy_obs[i, w])**2)
        dot_op = pred.fx * float(fx_obs[i, w]) + pred.fy * float(fy_obs[i, w])
        dot_pp = pred.fx**2 + pred.fy**2
        lam_raw = dot_op / max(dot_pp, 1.0)
        diag_lambda_raw.append(lam_raw)

    if diag_alpha:
        da = np.array(diag_alpha)
        dfyp = np.array(diag_fy_pred)
        dfyo = np.array(diag_fy_obs)
        dfxp = np.array(diag_fx_pred)
        dfxo = np.array(diag_fx_obs)
        dfz = np.array(diag_fz)
        dlr = np.array(diag_lambda_raw)
        dspd = np.array(diag_speed_at)
        dalat = np.array(diag_a_lat_at)

        residual_fy = dfyo - dfyp
        residual_fx = dfxo - dfxp

        print(f"\n  Accepted-sample residuals (FL wheel, N={len(da):,}):")
        print(f"  alpha:     [{da.min():.4f}, {da.max():.4f}] rad, mean={da.mean():.4f}")
        print(f"  Fy_pred:   [{dfyp.min():.0f}, {dfyp.max():.0f}] N, mean={dfyp.mean():.0f}")
        print(f"  Fy_obs:    [{dfyo.min():.0f}, {dfyo.max():.0f}] N, mean={dfyo.mean():.0f}")
        print(f"  Fy resid:  mean={residual_fy.mean():.0f} N, std={residual_fy.std():.0f}")
        print(f"  Fx_pred:   mean={dfxp.mean():.0f} N")
        print(f"  Fx_obs:    mean={dfxo.mean():.0f} N")
        print(f"  Fx resid:  mean={residual_fx.mean():.0f} N, std={residual_fx.std():.0f}")
        print(f"  Fz:        [{dfz.min():.0f}, {dfz.max():.0f}] N, mean={dfz.mean():.0f}")
        print(f"  lambda_raw (before clamp): [{dlr.min():.4f}, {dlr.max():.4f}], "
              f"mean={dlr.mean():.4f}, median={np.median(dlr):.4f}")

        # Lambda histogram before clamp
        print(f"\n  Lambda histogram (raw, before clamp):")
        bins = [0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0, 1.1, 1.3, 1.5, 2.0, 5.0]
        counts, _ = np.histogram(dlr, bins=bins)
        for j in range(len(counts)):
            bar = "#" * min(int(counts[j] / max(counts.max(), 1) * 30), 30)
            print(f"    [{bins[j]:5.1f}, {bins[j+1]:5.1f}): {counts[j]:>6} {bar}")

        # Residual vs Fz (load sensitivity check)
        print(f"\n  Fy residual vs Fz (load sensitivity):")
        fz_bins = [0, 2000, 3000, 4000, 5000, 7000, 10000]
        for j in range(len(fz_bins) - 1):
            mask = (dfz >= fz_bins[j]) & (dfz < fz_bins[j+1])
            if mask.sum() > 10:
                mean_res = residual_fy[mask].mean()
                mean_lam = dlr[mask].mean()
                print(f"    Fz [{fz_bins[j]:>5}, {fz_bins[j+1]:>5}): "
                      f"n={mask.sum():>5}, Fy_resid={mean_res:>+7.0f} N, "
                      f"lambda_raw={mean_lam:.3f}")

        # Residual vs |a_lat| (excitation level)
        print(f"\n  Lambda vs |a_lat| (excitation level):")
        alat_bins = [0, 2, 5, 8, 12, 20]
        for j in range(len(alat_bins) - 1):
            mask = (np.abs(dalat) >= alat_bins[j]) & (np.abs(dalat) < alat_bins[j+1])
            if mask.sum() > 10:
                mean_lam = dlr[mask].mean()
                med_lam = np.median(dlr[mask])
                print(f"    |a_lat| [{alat_bins[j]:>2}, {alat_bins[j+1]:>2}): "
                      f"n={mask.sum():>5}, lambda_mean={mean_lam:.3f}, "
                      f"lambda_median={med_lam:.3f}")

        # Rejection reason breakdown
        print(f"\n  Rejection reasons (subsampled blocks):")
        total_blocks = n_accepted + n_rejected
        for reason, count in sorted(reject_reasons_count.items(), key=lambda x: -x[1]):
            pct = count / max(total_blocks * 4, 1) * 100  # per-wheel basis
            print(f"    {reason:>20}: {count:>7} ({pct:>5.1f}% of wheel-samples)")

    # ── 9. Export report ─────────────────────────────────────
    report = {
        "session": IBT_PATH.name,
        "n_samples": int(n_samples),
        "n_accepted_blocks": n_accepted,
        "n_rejected_blocks": n_rejected,
        "reject_reasons": reject_reasons_count,
        "lambda_stats": {
            "count": len(valid_lambda),
            "mean": round(float(valid_lambda.mean()), 4),
            "std": round(float(valid_lambda.std()), 4),
            "median": round(float(np.median(valid_lambda)), 4),
            "p5": round(float(np.percentile(valid_lambda, 5)), 4),
            "p95": round(float(np.percentile(valid_lambda, 95)), 4),
        },
        "field_summary": summary,
        "diagnostics": {
            "center_mean_lambda": round(float(np.mean(center_lam)), 4),
            "left_mean_lambda": round(float(np.mean(left_lam)), 4),
            "right_mean_lambda": round(float(np.mean(right_lam)), 4),
            "lap_lambdas": {str(k): round(v, 4) for k, v in lap_lambdas.items()},
        },
        "metadata": {
            "car": "McLaren 570S GT4",
            "track": "Daytona Road Course",
            "condition": "dry",
            "total_laps": len(lap_times),
            "best_lap_s": round(lap_times[best_lap], 2),
        },
    }

    with open(OUT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to {OUT_PATH.name}")
    print(f"Total time: {time.perf_counter() - t_total:.1f}s")


if __name__ == "__main__":
    main()
