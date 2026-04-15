"""
validate_attitude_correction.py
-------------------------------
Standalone validation harness for the road-attitude correction path.

This script does NOT change production code or enable correction.
It loads the real OK karting dataset, runs the mount + attitude
estimators under a matrix of scenarios (with/without curvature,
original/flipped sign conventions), and emits structured diagnostics
so we can pinpoint the cause of the cal_bias divergence (1.096 raw
→ 1.518 corrected) observed after the detector fix.

Outputs (written to docs/validation/):
    attitude_correction_report.md   — human-readable summary tables
    attitude_correction_metrics.csv — machine-readable metric grid
    attitude_correction_plot.png    — raw/corrected/centripetal vs distance
                                      (if matplotlib is importable)

Invariant: demand cleaning, not friction estimation. This script reports
on observed-demand alignment with GPS-derived centripetal. It does not
claim to compute friction.
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np

# ── Paths and imports ──
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TELEMETRY_PKG = os.path.join(_REPO_ROOT, 'telemetry_tool')
if _TELEMETRY_PKG not in sys.path:
    sys.path.insert(0, _TELEMETRY_PKG)

from phone_mount_estimator import estimate_phone_mount             # noqa: E402
from road_attitude_estimator import estimate_road_attitude          # noqa: E402

_G = 9.80665

# ── RaceChrono column indices (must match build_ok_raw.py) ──
_COL_BEARING = 9
_COL_LAT_G_CALC = 19
_COL_LONG_G_CALC = 20
_COL_ACCEL_X = 24
_COL_ACCEL_Y = 25
_COL_ACCEL_Z = 26
_COL_GYRO_X = 32
_COL_GYRO_Y = 33
_COL_GYRO_Z = 34

_FILES = [
    'data/raw/OK_FP+Q.csv',
    'data/raw/OK_R1.csv',
    'data/raw/OK_R2.csv',
    'data/raw/OK_R3.csv',
    'data/raw/OK_R4.csv',
]

# Gating threshold that production uses (from track_surface.attitude_correction)
_MIN_Q = 0.4

# Segmentation thresholds
_STRAIGHT_KAPPA = 0.005      # |κ| below this = straight
_CORNER_KAPPA = 0.02         # |κ| above this = corner
_HARD_BRAKE_G = -0.25        # dv/dt (g) below this = hard braking
_HARD_ACCEL_G = 0.20         # dv/dt (g) above this = hard acceleration


# ─────────────────────────────────────────────────────────────────
# Loading helpers
# ─────────────────────────────────────────────────────────────────


def _safe_float(parts, idx, default=np.nan):
    if len(parts) <= idx:
        return default
    cell = parts[idx].strip()
    if not cell:
        return default
    try:
        return float(cell)
    except ValueError:
        return default


@dataclass
class LapBundle:
    src: str
    lap_num: int
    t: np.ndarray                  # (N,) seconds
    x: np.ndarray                  # (N,) meters (local XY)
    y: np.ndarray                  # (N,) meters
    speed: np.ndarray              # (N,) m/s
    alat_g_calc: np.ndarray        # (N,) RaceChrono *calc lateral G (signed)
    along_g_calc: np.ndarray       # (N,) RaceChrono *calc longitudinal G (signed)
    accel_3d: np.ndarray           # (N, 3) phone-frame, G
    gyro_3d: np.ndarray            # (N, 3) phone-frame, deg/s
    bearing_deg: np.ndarray        # (N,) degrees
    curvature: np.ndarray          # (N,) signed 1/m (derived from GPS)


def load_session(path: str) -> list[LapBundle]:
    """Read one RaceChrono CSV and return per-lap bundles."""
    rows_by_lap: dict[int, list[tuple]] = {}
    with open(path, 'r', encoding='latin-1') as f:
        for line in f:
            if not line.startswith('17'):
                continue
            parts = line.split(',')
            try:
                lap_str = parts[2].strip()
                if not lap_str:
                    continue
                lap_num = int(lap_str)
                lat = float(parts[12])
                lon = float(parts[13])
                spd = float(parts[7])
                t = float(parts[0])
                if abs(lat) < 1 or spd < 1:
                    continue
                row = (
                    t, lat, lon, spd,
                    _safe_float(parts, _COL_LAT_G_CALC),
                    _safe_float(parts, _COL_LONG_G_CALC),
                    _safe_float(parts, _COL_ACCEL_X),
                    _safe_float(parts, _COL_ACCEL_Y),
                    _safe_float(parts, _COL_ACCEL_Z),
                    _safe_float(parts, _COL_GYRO_X),
                    _safe_float(parts, _COL_GYRO_Y),
                    _safe_float(parts, _COL_GYRO_Z),
                    _safe_float(parts, _COL_BEARING),
                )
                rows_by_lap.setdefault(lap_num, []).append(row)
            except (ValueError, IndexError):
                continue

    if not rows_by_lap:
        return []

    # Session-scoped reference lat/lon for local XY projection
    all_lat = np.concatenate([
        np.array([r[1] for r in rows]) for rows in rows_by_lap.values()
    ])
    all_lon = np.concatenate([
        np.array([r[2] for r in rows]) for rows in rows_by_lap.values()
    ])
    lat0 = float(np.mean(all_lat))
    lon0 = float(np.mean(all_lon))
    cos_lat = np.cos(np.radians(lat0))

    bundles: list[LapBundle] = []
    src = os.path.basename(path).split('.')[0]
    for lap_num, rows in sorted(rows_by_lap.items()):
        rows.sort(key=lambda r: r[0])
        if len(rows) < 200:
            continue
        t_arr = np.array([r[0] for r in rows])
        lap_time = t_arr[-1] - t_arr[0]
        if not (30 < lap_time < 120):
            continue
        lats = np.array([r[1] for r in rows])
        lons = np.array([r[2] for r in rows])
        x = (lons - lon0) * cos_lat * 111320.0
        y = (lats - lat0) * 111320.0
        accel = np.column_stack([
            [r[6] for r in rows],
            [r[7] for r in rows],
            [r[8] for r in rows],
        ])
        gyro = np.column_stack([
            [r[9] for r in rows],
            [r[10] for r in rows],
            [r[11] for r in rows],
        ])
        if not (np.isfinite(accel).all(axis=1).mean() > 0.5):
            continue
        if not (np.isfinite(gyro).all(axis=1).mean() > 0.5):
            continue
        bundles.append(LapBundle(
            src=src,
            lap_num=lap_num,
            t=t_arr,
            x=x,
            y=y,
            speed=np.array([r[3] for r in rows]),
            alat_g_calc=np.array([r[4] for r in rows]),
            along_g_calc=np.array([r[5] for r in rows]),
            accel_3d=accel,
            gyro_3d=gyro,
            bearing_deg=np.array([r[12] for r in rows]),
            curvature=_curvature_from_xy(x, y, np.array([r[3] for r in rows])),
        ))
    return bundles


def _curvature_from_xy(
    x: np.ndarray, y: np.ndarray, speed: np.ndarray,
) -> np.ndarray:
    """Per-sample *signed* curvature (1/m) from GPS XY in time domain.

    Positive curvature = left turn (counter-clockwise) in a standard
    right-handed XY frame. This matches ``road_attitude_estimator``'s
    documented convention.

    GPS jitter dominates naive pointwise differentiation, so we:
      1. Heavily smooth the XY trajectory (savgol, ~2 s window).
      2. Use savgol with ``deriv=1`` and ``deriv=2`` for clean derivatives.
      3. Compute signed curvature with the parametric formula:
            κ = (x' y'' − y' x'') / (x'² + y'²)^(3/2)
      4. Clamp to ensure v²|κ|/g ≤ 2.0 G — a physics-based sanity gate
         against residual noise spikes. A kart does not pull 5+ G.
    """
    from scipy.signal import savgol_filter
    n = len(x)
    # ~2 second smoothing at 25 Hz. Savgol window must be odd and <= n.
    win = min(51, n if n % 2 == 1 else n - 1)
    win = max(win, 5)
    x_d1 = savgol_filter(x, win, polyorder=3, deriv=1, mode='nearest')
    y_d1 = savgol_filter(y, win, polyorder=3, deriv=1, mode='nearest')
    x_d2 = savgol_filter(x, win, polyorder=3, deriv=2, mode='nearest')
    y_d2 = savgol_filter(y, win, polyorder=3, deriv=2, mode='nearest')
    denom = (x_d1 ** 2 + y_d1 ** 2) ** 1.5
    denom = np.where(denom < 1e-9, 1e-9, denom)
    kappa = (x_d1 * y_d2 - y_d1 * x_d2) / denom
    # Physics-based speed-adaptive clamp: |v²κ/g| ≤ 2.0 G
    v_safe = np.maximum(speed, 1.0)
    max_kappa = 2.0 * _G / (v_safe ** 2)
    return np.clip(kappa, -max_kappa, max_kappa)


# ─────────────────────────────────────────────────────────────────
# Scenario runner
# ─────────────────────────────────────────────────────────────────


@dataclass
class ScenarioResult:
    name: str
    alat_g_raw: np.ndarray
    alat_g_corrected: np.ndarray
    bank_deg: np.ndarray
    grade_deg: np.ndarray
    applied_mask: np.ndarray
    centripetal_g: np.ndarray      # signed v²κ/g
    dvdt_g: np.ndarray             # signed
    kappa: np.ndarray              # signed
    speed: np.ndarray


def _run_scenario(
    bundle: LapBundle,
    mount,
    *,
    with_curvature: bool,
    bank_sign: int = 1,
    grade_sign: int = 1,
) -> ScenarioResult:
    curv_arg = bundle.curvature if with_curvature else None
    attitude = estimate_road_attitude(
        bundle.accel_3d, bundle.gyro_3d, bundle.speed, bundle.t, mount,
        curvature=curv_arg,
    )

    # Signed kart-frame lateral/longitudinal from RaceChrono *calc.
    # We preserve the original RaceChrono sign here (no abs()), so we can
    # audit sign consistency against GPS centripetal.
    alat_raw = bundle.alat_g_calc.copy()

    # Apply correction with optional sign flips (FOR VALIDATION ONLY — never
    # written back to production).
    bank_rad = np.deg2rad(attitude.bank_deg) * bank_sign
    grade_rad = np.deg2rad(attitude.grade_deg) * grade_sign
    quality = np.asarray(attitude.attitude_quality, dtype=float)
    unstable = np.asarray(attitude.unstable_segments, dtype=bool)
    applied = (quality > _MIN_Q) & ~unstable

    alat_corrected = alat_raw.copy()
    alat_corrected[applied] = alat_raw[applied] - np.sin(bank_rad[applied])

    centripetal = (bundle.speed ** 2) * bundle.curvature / _G
    dt = np.median(np.diff(bundle.t))
    dvdt = np.gradient(bundle.speed) / max(dt, 1e-6) / _G

    return ScenarioResult(
        name=f"{'curv' if with_curvature else 'nocurv'}_b{'+' if bank_sign > 0 else '-'}g{'+' if grade_sign > 0 else '-'}",
        alat_g_raw=alat_raw,
        alat_g_corrected=alat_corrected,
        bank_deg=np.asarray(attitude.bank_deg) * bank_sign,
        grade_deg=np.asarray(attitude.grade_deg) * grade_sign,
        applied_mask=applied,
        centripetal_g=centripetal,
        dvdt_g=dvdt,
        kappa=bundle.curvature,
        speed=bundle.speed,
    )


# ─────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────


def _metrics_for_mask(res: ScenarioResult, mask: np.ndarray) -> dict:
    """Compute cal_bias / RMSE / bias / sign-consistency on a sample subset.

    cal_bias: median(|alat| / |centripetal|) over in-corner samples
    sign_consistency: fraction of samples where sign(alat) == sign(-centripetal)
        (NB: IMU convention vs kart-y convention is where sign ambiguity lives)
    """
    n_total = int(mask.sum())
    if n_total == 0:
        return {
            'n_samples': 0,
            'cal_bias_raw': np.nan,
            'cal_bias_cor': np.nan,
            'signed_bias_raw_g': np.nan,
            'signed_bias_cor_g': np.nan,
            'rmse_raw_g': np.nan,
            'rmse_cor_g': np.nan,
            'sign_consistency_raw': np.nan,
            'sign_consistency_cor': np.nan,
            'n_applied_corrections': 0,
        }

    cp = res.centripetal_g[mask]
    ar = res.alat_g_raw[mask]
    ac = res.alat_g_corrected[mask]
    applied = res.applied_mask[mask]

    # Magnitude ratios — only for in-corner samples where centripetal is meaningful
    nonzero_cp = np.abs(cp) > 0.05
    if nonzero_cp.any():
        cal_bias_raw = float(np.median(np.abs(ar[nonzero_cp]) / np.abs(cp[nonzero_cp])))
        cal_bias_cor = float(np.median(np.abs(ac[nonzero_cp]) / np.abs(cp[nonzero_cp])))
    else:
        cal_bias_raw = np.nan
        cal_bias_cor = np.nan

    # Signed bias and RMSE — magnitude error vs centripetal magnitude
    signed_bias_raw = float(np.mean(np.abs(ar) - np.abs(cp)))
    signed_bias_cor = float(np.mean(np.abs(ac) - np.abs(cp)))
    rmse_raw = float(np.sqrt(np.mean((np.abs(ar) - np.abs(cp)) ** 2)))
    rmse_cor = float(np.sqrt(np.mean((np.abs(ac) - np.abs(cp)) ** 2)))

    # Sign consistency: IMU lateral reading vs *negated* centripetal direction.
    # Rationale: a_lat_imu = reaction force on phone = toward center of turn = +y
    # when curvature > 0 (left turn in our convention). But RaceChrono *calc
    # may use the opposite sign. We report BOTH signs of agreement so the
    # convention is unambiguous.
    if nonzero_cp.any():
        sign_agree_raw = float(np.mean(np.sign(ar[nonzero_cp]) == np.sign(cp[nonzero_cp])))
        sign_agree_cor = float(np.mean(np.sign(ac[nonzero_cp]) == np.sign(cp[nonzero_cp])))
    else:
        sign_agree_raw = np.nan
        sign_agree_cor = np.nan

    return {
        'n_samples': n_total,
        'cal_bias_raw': cal_bias_raw,
        'cal_bias_cor': cal_bias_cor,
        'signed_bias_raw_g': signed_bias_raw,
        'signed_bias_cor_g': signed_bias_cor,
        'rmse_raw_g': rmse_raw,
        'rmse_cor_g': rmse_cor,
        'sign_consistency_raw': sign_agree_raw,
        'sign_consistency_cor': sign_agree_cor,
        'n_applied_corrections': int(applied.sum()),
    }


def segment_masks(res: ScenarioResult) -> dict[str, np.ndarray]:
    """Build per-sample boolean masks for driving regimes."""
    k_abs = np.abs(res.kappa)
    k = res.kappa
    dvdt = res.dvdt_g
    # Exclude low-speed crawl samples.
    v_ok = res.speed > 5.0
    straight = (k_abs < _STRAIGHT_KAPPA) & v_ok
    left = (k > _CORNER_KAPPA) & v_ok
    right = (k < -_CORNER_KAPPA) & v_ok
    braking = (dvdt < _HARD_BRAKE_G) & v_ok
    accelerating = (dvdt > _HARD_ACCEL_G) & v_ok
    mid_corner = (k_abs > _CORNER_KAPPA) & (np.abs(dvdt) < 0.1) & v_ok
    return {
        'all_valid': v_ok,
        'straight': straight,
        'left_corner': left,
        'right_corner': right,
        'braking': braking,
        'accelerating': accelerating,
        'steady_mid_corner': mid_corner,
    }


# ─────────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────────


def _aggregate_scenario_metrics(
    scenario_name: str,
    per_lap_results: list[ScenarioResult],
) -> tuple[dict[str, dict], dict[str, float]]:
    """Stack samples across laps and compute per-segment metrics for one scenario."""
    if not per_lap_results:
        return {}, {}

    # Concatenate per-lap arrays
    def _cat(attr: str) -> np.ndarray:
        return np.concatenate([getattr(r, attr) for r in per_lap_results])

    merged = ScenarioResult(
        name=scenario_name,
        alat_g_raw=_cat('alat_g_raw'),
        alat_g_corrected=_cat('alat_g_corrected'),
        bank_deg=_cat('bank_deg'),
        grade_deg=_cat('grade_deg'),
        applied_mask=_cat('applied_mask'),
        centripetal_g=_cat('centripetal_g'),
        dvdt_g=_cat('dvdt_g'),
        kappa=_cat('kappa'),
        speed=_cat('speed'),
    )
    masks = segment_masks(merged)
    per_seg = {seg: _metrics_for_mask(merged, m) for seg, m in masks.items()}

    summary = {
        'mean_bank_deg': float(np.mean(merged.bank_deg)),
        'std_bank_deg': float(np.std(merged.bank_deg)),
        'p5_bank_deg': float(np.percentile(merged.bank_deg, 5)),
        'p95_bank_deg': float(np.percentile(merged.bank_deg, 95)),
        'mean_grade_deg': float(np.mean(merged.grade_deg)),
        'std_grade_deg': float(np.std(merged.grade_deg)),
        'applied_frac': float(merged.applied_mask.mean()),
    }
    return per_seg, summary


def _format_table_row(values: list[str], widths: list[int]) -> str:
    return ' | '.join(v.ljust(w) for v, w in zip(values, widths))


def write_report(
    per_scenario: dict[str, tuple[dict[str, dict], dict[str, float]]],
    conventions_text: str,
    out_md_path: str,
    out_csv_path: str,
) -> None:
    lines: list[str] = []
    lines.append("# Attitude Correction Validation Report")
    lines.append("")
    lines.append("**Invariant:** observed demand, not friction. This report checks whether")
    lines.append("the attitude correction moves the corrected lateral demand *toward* or")
    lines.append("*away from* GPS-derived centripetal (v²κ/g) — our one external reference.")
    lines.append("")
    lines.append("## 1. Conventions audited")
    lines.append("")
    lines.append(conventions_text)
    lines.append("")
    lines.append("## 2. Scenario matrix — session-wide magnitude alignment")
    lines.append("")
    lines.append("`cal_bias` = median(|a_lat| / |v²κ/g|) on in-corner samples (|v²κ/g| > 0.05 g)")
    lines.append("Closer to 1.0 = better agreement with GPS-derived centripetal.")
    lines.append("")

    header = ["scenario", "mean_bank°", "std_bank°", "mean_grade°",
              "applied_frac", "cal_bias_raw", "cal_bias_cor", "sign_cons_cor"]
    widths = [38, 10, 9, 11, 12, 12, 12, 13]
    lines.append("```")
    lines.append(_format_table_row(header, widths))
    lines.append(_format_table_row(['-' * w for w in widths], widths))
    for name, (per_seg, summary) in per_scenario.items():
        all_row = per_seg.get('all_valid', {})
        lines.append(_format_table_row([
            name,
            f"{summary['mean_bank_deg']:+.2f}",
            f"{summary['std_bank_deg']:.2f}",
            f"{summary['mean_grade_deg']:+.2f}",
            f"{summary['applied_frac']*100:.1f}%",
            f"{all_row.get('cal_bias_raw', float('nan')):.3f}",
            f"{all_row.get('cal_bias_cor', float('nan')):.3f}",
            f"{all_row.get('sign_consistency_cor', float('nan')):.3f}",
        ], widths))
    lines.append("```")
    lines.append("")

    # Per-segment breakdown for the CURRENT-PRODUCTION scenario
    lines.append("## 3. Per-segment breakdown — current production scenario")
    lines.append("")
    lines.append("This mirrors what build_ok_raw.py is doing today (no curvature, original signs).")
    lines.append("")

    cur_name = 'nocurv_b+g+'
    if cur_name in per_scenario:
        per_seg, _ = per_scenario[cur_name]
        seg_hdr = ["segment", "n", "cal_bias_raw", "cal_bias_cor",
                   "rmse_raw_g", "rmse_cor_g", "sign_agree_raw", "sign_agree_cor"]
        seg_widths = [20, 8, 12, 12, 11, 11, 14, 14]
        lines.append("```")
        lines.append(_format_table_row(seg_hdr, seg_widths))
        lines.append(_format_table_row(['-' * w for w in seg_widths], seg_widths))
        for seg, m in per_seg.items():
            lines.append(_format_table_row([
                seg,
                str(m['n_samples']),
                f"{m['cal_bias_raw']:.3f}" if not np.isnan(m['cal_bias_raw']) else "n/a",
                f"{m['cal_bias_cor']:.3f}" if not np.isnan(m['cal_bias_cor']) else "n/a",
                f"{m['rmse_raw_g']:.3f}",
                f"{m['rmse_cor_g']:.3f}",
                f"{m['sign_consistency_raw']:.2f}" if not np.isnan(m['sign_consistency_raw']) else "n/a",
                f"{m['sign_consistency_cor']:.2f}" if not np.isnan(m['sign_consistency_cor']) else "n/a",
            ], seg_widths))
        lines.append("```")
        lines.append("")

    # Per-segment breakdown for WITH-CURVATURE scenario
    lines.append("## 4. Per-segment breakdown — WITH curvature (what production SHOULD do)")
    lines.append("")
    if 'curv_b+g+' in per_scenario:
        per_seg, _ = per_scenario['curv_b+g+']
        lines.append("```")
        lines.append(_format_table_row(seg_hdr, seg_widths))
        lines.append(_format_table_row(['-' * w for w in seg_widths], seg_widths))
        for seg, m in per_seg.items():
            lines.append(_format_table_row([
                seg,
                str(m['n_samples']),
                f"{m['cal_bias_raw']:.3f}" if not np.isnan(m['cal_bias_raw']) else "n/a",
                f"{m['cal_bias_cor']:.3f}" if not np.isnan(m['cal_bias_cor']) else "n/a",
                f"{m['rmse_raw_g']:.3f}",
                f"{m['rmse_cor_g']:.3f}",
                f"{m['sign_consistency_raw']:.2f}" if not np.isnan(m['sign_consistency_raw']) else "n/a",
                f"{m['sign_consistency_cor']:.2f}" if not np.isnan(m['sign_consistency_cor']) else "n/a",
            ], seg_widths))
        lines.append("```")
        lines.append("")

    # Write markdown
    os.makedirs(os.path.dirname(out_md_path), exist_ok=True)
    with open(out_md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # Write CSV
    with open(out_csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'scenario', 'segment', 'n_samples',
            'cal_bias_raw', 'cal_bias_cor',
            'signed_bias_raw_g', 'signed_bias_cor_g',
            'rmse_raw_g', 'rmse_cor_g',
            'sign_consistency_raw', 'sign_consistency_cor',
            'mean_bank_deg', 'std_bank_deg',
            'mean_grade_deg', 'applied_frac',
        ])
        for name, (per_seg, summary) in per_scenario.items():
            for seg, m in per_seg.items():
                w.writerow([
                    name, seg, m['n_samples'],
                    m['cal_bias_raw'], m['cal_bias_cor'],
                    m['signed_bias_raw_g'], m['signed_bias_cor_g'],
                    m['rmse_raw_g'], m['rmse_cor_g'],
                    m['sign_consistency_raw'], m['sign_consistency_cor'],
                    summary['mean_bank_deg'], summary['std_bank_deg'],
                    summary['mean_grade_deg'], summary['applied_frac'],
                ])


def maybe_write_plot(
    representative_result_current: Optional[ScenarioResult],
    representative_result_with_curv: Optional[ScenarioResult],
    out_png: str,
) -> bool:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        return False
    if representative_result_current is None or representative_result_with_curv is None:
        return False

    r0 = representative_result_current
    r1 = representative_result_with_curv
    dist = np.cumsum(np.maximum(0.0, r0.speed * 0.04))   # integrate at 25 Hz
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

    axes[0].plot(dist, r0.alat_g_raw, label='alat raw (RaceChrono *calc)',
                 color='#949494', alpha=0.7, lw=0.8)
    axes[0].plot(dist, r0.alat_g_corrected, label='alat corrected (NO curvature)',
                 color='#C9A84C', lw=1.0)
    axes[0].plot(dist, r1.alat_g_corrected, label='alat corrected (WITH curvature)',
                 color='#22C55E', lw=1.0, alpha=0.85)
    axes[0].plot(dist, r0.centripetal_g, label='v²κ/g (signed)',
                 color='#FF2A2A', lw=0.8, alpha=0.7)
    axes[0].set_ylabel('Lateral G (signed)')
    axes[0].legend(loc='upper right', fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].plot(dist, r0.bank_deg, label='bank (NO curvature)', color='#C9A84C')
    axes[1].plot(dist, r1.bank_deg, label='bank (WITH curvature)', color='#22C55E')
    axes[1].set_ylabel('Estimated bank (deg)')
    axes[1].legend(loc='upper right', fontsize=8)
    axes[1].grid(alpha=0.3)

    axes[2].plot(dist, r0.kappa, color='#8B5CF6', lw=0.8)
    axes[2].set_ylabel('Signed curvature (1/m)')
    axes[2].set_xlabel('Distance (m)')
    axes[2].grid(alpha=0.3)
    axes[2].axhline(0, color='#949494', lw=0.5)

    fig.suptitle('Attitude correction validation — representative lap')
    fig.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return True


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────


_CONVENTIONS_TEXT = """
| Quantity                           | Source                          | Sign convention found                     |
|------------------------------------|---------------------------------|-------------------------------------------|
| RaceChrono lateral *calc (col 19)  | data/raw/*.csv                  | unspecified by file; interpreted per test |
| Kart-frame y axis                  | road_attitude_estimator.py:258  | +y = LEFT                                 |
| Positive curvature κ               | _curvature_from_xy + road_att.  | left turn (CCW in XY)                     |
| GPS centripetal v²κ/g              | validation harness              | signed: positive on left turns            |
| Bank sign (road_attitude)          | road_attitude_estimator.py:215  | +bank = left side high → gravity_y = +sin |
| Bank correction (attitude_corr.)   | attitude_correction.py:182      | alat_cor = alat_raw − sin(bank)           |
| Grade sign (road_attitude)         | road_attitude_estimator.py:188  | +grade = uphill → a_x_gravity = −sin      |
| Grade correction (attitude_corr.)  | attitude_correction.py:183      | along_cor = along_raw + sin(grade)        |
| build_ok_raw.py use of alat        | scripts/build_ok_raw.py:232-243 | **takes abs() — sign information discarded** |
| curvature passed to correction     | scripts/build_ok_raw.py:228-236 | **None — ESTIMATOR SEES NO CURVATURE**    |

Observations:
  * The attitude estimator, without curvature, computes bank from
    ``a_y_residual = g_lp[:,1]`` — i.e., the low-passed lateral accel.
    In a sustained corner this signal equals *centripetal + bank*,
    so the estimator absorbs the corner's centripetal into "bank".
  * Per-sample bank is clamped to ±12°. ``sin(12°) ≈ 0.21 g`` — large
    enough to swing corrected |alat| by 20-30% every time we enter a corner.
  * build_ok_raw.py takes abs() of corrected alat before computing cal_bias,
    so the cal_bias metric sees **magnitude swings**, not sign inversions.
"""


def main():
    all_results_by_scenario: dict[str, list[ScenarioResult]] = {}
    first_lap_r0: Optional[ScenarioResult] = None
    first_lap_r1: Optional[ScenarioResult] = None

    scenarios = [
        dict(name='nocurv_b+g+', with_curvature=False, bank_sign=+1, grade_sign=+1),
        dict(name='curv_b+g+',   with_curvature=True,  bank_sign=+1, grade_sign=+1),
        dict(name='nocurv_b-g+', with_curvature=False, bank_sign=-1, grade_sign=+1),
        dict(name='curv_b-g+',   with_curvature=True,  bank_sign=-1, grade_sign=+1),
        dict(name='nocurv_b+g-', with_curvature=False, bank_sign=+1, grade_sign=-1),
        dict(name='curv_b+g-',   with_curvature=True,  bank_sign=+1, grade_sign=-1),
        dict(name='curv_b-g-',   with_curvature=True,  bank_sign=-1, grade_sign=-1),
    ]
    for sc in scenarios:
        all_results_by_scenario[sc['name']] = []

    for path in _FILES:
        abs_path = os.path.join(_REPO_ROOT, path)
        if not os.path.isfile(abs_path):
            print(f'skip {path} (not found)')
            continue
        print(f'Loading {path}…')
        bundles = load_session(abs_path)
        if not bundles:
            print(f'  no valid laps')
            continue
        # Session-scoped mount calibration: longest lap
        cal_lap = max(bundles, key=lambda b: len(b.t))
        try:
            mount = estimate_phone_mount(
                cal_lap.accel_3d, cal_lap.gyro_3d, cal_lap.speed, cal_lap.t,
            )
        except Exception as exc:
            print(f'  mount calibration failed: {exc}')
            continue
        print(f'  mount_unstable={mount.mount_unstable}, '
              f'orientation_quality={mount.orientation_quality:.2f}, {len(bundles)} laps')

        for bundle in bundles:
            for sc in scenarios:
                try:
                    res = _run_scenario(
                        bundle, mount,
                        with_curvature=sc['with_curvature'],
                        bank_sign=sc['bank_sign'],
                        grade_sign=sc['grade_sign'],
                    )
                    all_results_by_scenario[sc['name']].append(res)
                    if first_lap_r0 is None and sc['name'] == 'nocurv_b+g+':
                        first_lap_r0 = res
                    if first_lap_r1 is None and sc['name'] == 'curv_b+g+':
                        first_lap_r1 = res
                except Exception as exc:
                    print(f'  scenario {sc["name"]} failed on lap {bundle.lap_num}: {exc}')

    # Aggregate metrics per scenario
    per_scenario_metrics: dict[str, tuple[dict, dict]] = {}
    for name, per_lap in all_results_by_scenario.items():
        per_scenario_metrics[name] = _aggregate_scenario_metrics(name, per_lap)

    # Outputs
    out_md = os.path.join(_REPO_ROOT, 'docs', 'validation', 'attitude_correction_report.md')
    out_csv = os.path.join(_REPO_ROOT, 'docs', 'validation', 'attitude_correction_metrics.csv')
    out_png = os.path.join(_REPO_ROOT, 'docs', 'validation', 'attitude_correction_plot.png')

    write_report(per_scenario_metrics, _CONVENTIONS_TEXT, out_md, out_csv)
    plot_ok = maybe_write_plot(first_lap_r0, first_lap_r1, out_png)

    # Console summary
    print()
    print('=' * 70)
    print('Scenario summary (all in-corner samples)')
    print('=' * 70)
    print(f"{'scenario':38} {'mean_bank°':>10} {'cal_bias_raw':>14} {'cal_bias_cor':>14} {'sign_cons_cor':>14}")
    for name, (per_seg, summary) in per_scenario_metrics.items():
        row = per_seg.get('all_valid', {})
        print(f"{name:38} {summary['mean_bank_deg']:>+10.2f} "
              f"{row.get('cal_bias_raw', float('nan')):>14.3f} "
              f"{row.get('cal_bias_cor', float('nan')):>14.3f} "
              f"{row.get('sign_consistency_cor', float('nan')):>14.3f}")

    print()
    print(f'Report:  {out_md}')
    print(f'CSV:     {out_csv}')
    if plot_ok:
        print(f'Plot:    {out_png}')
    else:
        print('Plot:    (matplotlib not available — skipped)')


if __name__ == '__main__':
    main()
