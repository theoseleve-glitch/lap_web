"""
validate_road_attitude_field.py
-------------------------------
Shadow-mode validation of the new multi-lap ``road_attitude_field``
estimator against the real OK karting dataset.

Reports:
  * per-sample bank/grade std (from the old per-sample estimator) vs
    per-bin bank/grade std (from the new field estimator)
  * confidence distribution
  * coverage distribution (evidence_count + lap_coverage)
  * provisional "would correction help?" metrics per driving regime
      — all_valid, straight, left_corner, right_corner, braking,
        accelerating, steady_mid_corner
    comparing raw lateral accel to GPS centripetal (signed), both before
    and after applying bank(s)/grade(s) from the new field.

Does NOT modify production. Writes outputs under docs/validation/.
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TELEMETRY_PKG = os.path.join(_REPO_ROOT, 'telemetry_tool')
if _TELEMETRY_PKG not in sys.path:
    sys.path.insert(0, _TELEMETRY_PKG)
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from phone_mount_estimator import estimate_phone_mount                  # noqa: E402
from road_attitude_estimator import estimate_road_attitude              # noqa: E402
from track_surface.frenet import FrenetFrame                            # noqa: E402
from track_surface.road_attitude_field import (                          # noqa: E402
    LapSamples,
    RoadAttitudeFieldConfig,
    estimate_road_attitude_field,
)
from validate_attitude_correction import (                               # noqa: E402
    _CORNER_KAPPA, _HARD_ACCEL_G, _HARD_BRAKE_G, _STRAIGHT_KAPPA,
    _curvature_from_xy, load_session,
)

_G = 9.80665
_FILES = [
    'data/raw/OK_FP+Q.csv',
    'data/raw/OK_R1.csv',
    'data/raw/OK_R2.csv',
    'data/raw/OK_R3.csv',
    'data/raw/OK_R4.csv',
]


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _build_centerline_from_best_lap(bundles) -> np.ndarray:
    """Use the longest lap's smoothed GPS trajectory as a centerline proxy."""
    from scipy.signal import savgol_filter
    best = max(bundles, key=lambda b: len(b.t))
    win = min(25, len(best.x) if len(best.x) % 2 == 1 else len(best.x) - 1)
    win = max(win, 5)
    cx = savgol_filter(best.x, win, polyorder=3, mode='nearest')
    cy = savgol_filter(best.y, win, polyorder=3, mode='nearest')
    # Uniform resample to 2 m intervals along arc length.
    dx = np.diff(cx)
    dy = np.diff(cy)
    s_cl = np.concatenate([[0.0], np.cumsum(np.sqrt(dx ** 2 + dy ** 2))])
    total = float(s_cl[-1])
    s_uniform = np.arange(0.0, total, 2.0)
    cx_u = np.interp(s_uniform, s_cl, cx)
    cy_u = np.interp(s_uniform, s_cl, cy)
    return np.column_stack([cx_u, cy_u])


def _as_lap_samples(bundle, mount) -> LapSamples:
    """Promote a validate_attitude_correction LapBundle into a LapSamples.

    The raw accel is in phone frame; kart-frame lateral/longitudinal come
    from applying the mount rotation. We prefer RaceChrono *calc for
    alat (it's already filtered) and gradient-of-speed for along.
    """
    R = mount.R_phone_to_kart
    accel_kart = bundle.accel_3d @ R.T
    dt = float(np.median(np.diff(bundle.t))) if len(bundle.t) > 1 else 0.04
    return LapSamples(
        x=bundle.x,
        y=bundle.y,
        speed=bundle.speed,
        # Signed kart-frame lateral: RaceChrono *calc is already in G and
        # preserves sign consistent with curvature (verified in the earlier
        # validation: 98% sign agreement).
        alat_g=bundle.alat_g_calc.copy(),
        along_g=accel_kart[:, 0].copy(),
        dt=dt,
        orientation_quality=float(getattr(mount, 'orientation_quality', 0.5)),
        mount_unstable=bool(getattr(mount, 'mount_unstable', False)),
        source=bundle.src,
    )


def _per_sample_bank_grade_from_legacy(bundle, mount):
    """Per-sample bank/grade from the existing ``estimate_road_attitude``
    — used only so we can report the std of its output alongside the
    field's std. No production change."""
    try:
        att = estimate_road_attitude(
            bundle.accel_3d, bundle.gyro_3d, bundle.speed, bundle.t, mount,
            curvature=None,
        )
        return np.asarray(att.bank_deg), np.asarray(att.grade_deg)
    except Exception:
        n = len(bundle.t)
        return np.zeros(n), np.zeros(n)


@dataclass
class RegimeStats:
    n: int
    median_ratio_raw: float
    median_ratio_cor: float
    rmse_raw_g: float
    rmse_cor_g: float
    signed_bias_raw_g: float
    signed_bias_cor_g: float


def _regime_metrics(
    alat_raw: np.ndarray,
    alat_cor: np.ndarray,
    centripetal: np.ndarray,
    mask: np.ndarray,
) -> RegimeStats:
    n = int(mask.sum())
    if n == 0:
        return RegimeStats(0, float('nan'), float('nan'),
                           float('nan'), float('nan'),
                           float('nan'), float('nan'))
    cp = centripetal[mask]
    ar = alat_raw[mask]
    ac = alat_cor[mask]
    nonzero = np.abs(cp) > 0.05
    if nonzero.any():
        mr_raw = float(np.median(np.abs(ar[nonzero]) / np.abs(cp[nonzero])))
        mr_cor = float(np.median(np.abs(ac[nonzero]) / np.abs(cp[nonzero])))
    else:
        mr_raw = float('nan')
        mr_cor = float('nan')
    rmse_raw = float(np.sqrt(np.mean((np.abs(ar) - np.abs(cp)) ** 2)))
    rmse_cor = float(np.sqrt(np.mean((np.abs(ac) - np.abs(cp)) ** 2)))
    bias_raw = float(np.mean(np.abs(ar) - np.abs(cp)))
    bias_cor = float(np.mean(np.abs(ac) - np.abs(cp)))
    return RegimeStats(n, mr_raw, mr_cor, rmse_raw, rmse_cor, bias_raw, bias_cor)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────


def main():
    all_bundles = []
    session_mount = {}
    for path in _FILES:
        abs_path = os.path.join(_REPO_ROOT, path)
        if not os.path.isfile(abs_path):
            print(f'skip {path} (not found)')
            continue
        print(f'Loading {path}…')
        bundles = load_session(abs_path)
        if not bundles:
            continue
        cal = max(bundles, key=lambda b: len(b.t))
        try:
            mount = estimate_phone_mount(cal.accel_3d, cal.gyro_3d, cal.speed, cal.t)
        except Exception as exc:
            print(f'  mount calibration failed: {exc}')
            continue
        print(f'  mount_unstable={mount.mount_unstable}, '
              f'orientation_quality={mount.orientation_quality:.2f}, '
              f'{len(bundles)} laps')
        for b in bundles:
            all_bundles.append((b, mount))
        session_mount[bundles[0].src] = mount

    if not all_bundles:
        print('No bundles — aborting.')
        return

    # Build a shared centerline + Frenet from the best lap across all sessions.
    print('Building shared centerline…')
    all_bundles_only = [b for b, _ in all_bundles]
    centerline = _build_centerline_from_best_lap(all_bundles_only)
    frenet = FrenetFrame.from_centerline(centerline)
    print(f'  centerline: {centerline.shape[0]} points, '
          f'total_length_m={frenet.total_length_m:.1f}')

    # Build LapSamples list.
    print('Building LapSamples…')
    lap_samples = [_as_lap_samples(b, m) for b, m in all_bundles]

    # Estimate the attitude field.
    print('Estimating road attitude field…')
    cfg = RoadAttitudeFieldConfig(
        s_bin_m=5.0,
        min_samples_per_bin=30,       # karting has plenty of samples; be conservative
        min_laps_per_bin=3,
        bank_min_centripetal_g=0.15,
        grade_max_transient_g=0.25,
        bank_clamp_deg=8.0,
        grade_clamp_deg=8.0,
        smooth_window_bins=3,
    )
    field = estimate_road_attitude_field(lap_samples, frenet, cfg)
    diag = field.diagnostics

    # ── Per-sample legacy std (from existing per-sample estimator) ──
    print('Collecting per-sample legacy bank/grade for comparison…')
    legacy_bank_samples: list[np.ndarray] = []
    legacy_grade_samples: list[np.ndarray] = []
    for b, m in all_bundles:
        bank, grade = _per_sample_bank_grade_from_legacy(b, m)
        legacy_bank_samples.append(bank)
        legacy_grade_samples.append(grade)
    legacy_bank = np.concatenate(legacy_bank_samples)
    legacy_grade = np.concatenate(legacy_grade_samples)

    # ── Summary: per-sample vs track-space ──
    per_sample_bank_std = float(np.std(legacy_bank))
    per_sample_grade_std = float(np.std(legacy_grade))
    valid_bank = field.bank_std_deg > 0
    valid_grade = field.grade_std_deg > 0
    track_bank_std = float(np.median(field.bank_std_deg[valid_bank])) if valid_bank.any() else float('nan')
    track_grade_std = float(np.median(field.grade_std_deg[valid_grade])) if valid_grade.any() else float('nan')

    # ── Provisional "corrected" demand using field bank at each sample's s ──
    # Build per-sample correction by looking up bank(s) at the sample's s.
    print('Applying field correction in shadow mode (no production change)…')
    total_raw_list, total_cor_list, total_cp_list = [], [], []
    total_mask_regime: dict[str, list[np.ndarray]] = {
        k: [] for k in (
            'all_valid', 'straight', 'left_corner', 'right_corner',
            'braking', 'accelerating', 'steady_mid_corner',
        )
    }

    for b, _m in all_bundles:
        # Re-compute curvature for centripetal (same as validate_attitude_correction)
        curv = _curvature_from_xy(b.x, b.y, b.speed)
        cp = b.speed ** 2 * curv / _G
        dt = float(np.median(np.diff(b.t))) if len(b.t) > 1 else 0.04
        dvdt = np.gradient(b.speed) / dt / _G

        # Per-sample bank/grade from the FIELD (track-space, NOT per-sample).
        s_arr, _ = frenet.xy_to_sn(b.x, b.y)
        s_arr = np.mod(s_arr, frenet.total_length_m) if frenet.total_length_m > 0 else s_arr
        bank_deg_sample = field.bank_at(s_arr)
        conf_sample = field.confidence_at(s_arr)

        # Apply correction ONLY on samples whose bin has high confidence.
        apply_mask = conf_sample > 0.5
        bank_rad = np.deg2rad(np.where(apply_mask, bank_deg_sample, 0.0))
        alat_cor = b.alat_g_calc - np.sin(bank_rad)

        total_raw_list.append(b.alat_g_calc.copy())
        total_cor_list.append(alat_cor)
        total_cp_list.append(cp)

        # Build regime masks per lap
        v_ok = b.speed > 5.0
        k_abs = np.abs(curv)
        straight = (k_abs < _STRAIGHT_KAPPA) & v_ok
        left = (curv > _CORNER_KAPPA) & v_ok
        right = (curv < -_CORNER_KAPPA) & v_ok
        braking = (dvdt < _HARD_BRAKE_G) & v_ok
        accelerating = (dvdt > _HARD_ACCEL_G) & v_ok
        mid = (k_abs > _CORNER_KAPPA) & (np.abs(dvdt) < 0.1) & v_ok

        total_mask_regime['all_valid'].append(v_ok)
        total_mask_regime['straight'].append(straight)
        total_mask_regime['left_corner'].append(left)
        total_mask_regime['right_corner'].append(right)
        total_mask_regime['braking'].append(braking)
        total_mask_regime['accelerating'].append(accelerating)
        total_mask_regime['steady_mid_corner'].append(mid)

    alat_raw = np.concatenate(total_raw_list)
    alat_cor = np.concatenate(total_cor_list)
    cp_all = np.concatenate(total_cp_list)
    regime_metrics: dict[str, RegimeStats] = {}
    for name, mask_list in total_mask_regime.items():
        mask = np.concatenate(mask_list)
        regime_metrics[name] = _regime_metrics(alat_raw, alat_cor, cp_all, mask)

    # ── Report ──
    out_md = os.path.join(_REPO_ROOT, 'docs', 'validation', 'road_attitude_field_report.md')
    out_csv = os.path.join(_REPO_ROOT, 'docs', 'validation', 'road_attitude_field_metrics.csv')
    os.makedirs(os.path.dirname(out_md), exist_ok=True)

    lines = []
    lines.append("# Track-space Road Attitude Field — Validation Report")
    lines.append("")
    lines.append("**Invariant:** observed demand, not friction. This report evaluates whether")
    lines.append("aggregating bank/grade evidence across laps in track space reduces spread")
    lines.append("enough to be useful for correction, and whether applying that field in")
    lines.append("shadow mode improves alignment with GPS-derived centripetal.")
    lines.append("")
    lines.append("## 1. Coverage")
    lines.append("")
    lines.append("```")
    lines.append(f"  centerline length: {frenet.total_length_m:.1f} m, "
                 f"s-bin width: {cfg.s_bin_m:.1f} m, n_bins: {diag['n_bins']}")
    lines.append(f"  bank_valid bins:   {diag['n_bins_bank_valid']}/{diag['n_bins']} "
                 f"({diag['bank_coverage_frac']*100:.1f}%)")
    lines.append(f"  grade_valid bins:  {diag['n_bins_grade_valid']}/{diag['n_bins']} "
                 f"({diag['grade_coverage_frac']*100:.1f}%)")
    lines.append(f"  laps total:        {diag['n_laps_total']}, "
                 f"used for bank: {diag['n_laps_used_bank']}, "
                 f"used for grade: {diag['n_laps_used_grade']}")
    lines.append(f"  mean lap_coverage bank:  {diag['mean_lap_coverage_bank']:.1f}")
    lines.append(f"  mean lap_coverage grade: {diag['mean_lap_coverage_grade']:.1f}")
    lines.append("```")
    lines.append("")

    lines.append("## 2. Spread: per-sample (legacy) vs track-space (new)")
    lines.append("")
    lines.append("```")
    lines.append(f"  per-sample bank  std (deg):  {per_sample_bank_std:.3f}")
    lines.append(f"  track-space bank std (deg):  {track_bank_std:.3f}   "
                 f"(median across valid bins)")
    lines.append(f"  reduction factor:            "
                 f"{per_sample_bank_std / max(track_bank_std, 1e-6):.2f}x")
    lines.append("")
    lines.append(f"  per-sample grade std (deg):  {per_sample_grade_std:.3f}")
    lines.append(f"  track-space grade std (deg): {track_grade_std:.3f}")
    lines.append(f"  reduction factor:            "
                 f"{per_sample_grade_std / max(track_grade_std, 1e-6):.2f}x")
    lines.append("```")
    lines.append("")

    lines.append("## 3. Field mean values on valid bins")
    lines.append("")
    lines.append("```")
    lines.append(f"  mean bank  (deg): {diag['mean_bank_on_valid_deg']:+.3f}  "
                 f"median std: {diag['median_bank_std_on_valid_deg']:.3f}")
    lines.append(f"  mean grade (deg): {diag['mean_grade_on_valid_deg']:+.3f}  "
                 f"median std: {diag['median_grade_std_on_valid_deg']:.3f}")
    lines.append("```")
    lines.append("")

    lines.append("## 4. Confidence + evidence distribution")
    lines.append("")
    lines.append("```")
    qs = [5, 25, 50, 75, 95]
    for q in qs:
        lines.append(
            f"  confidence    p{q:>2}: {float(np.percentile(field.confidence, q)):.2f}   "
            f"evidence p{q:>2}: {int(np.percentile(field.evidence_count, q))}   "
            f"coverage p{q:>2}: {int(np.percentile(field.lap_coverage, q))}"
        )
    lines.append("```")
    lines.append("")

    lines.append("## 5. Shadow-mode correction impact (vs GPS centripetal)")
    lines.append("")
    lines.append("`cal_bias` = median(|a_lat| / |v²κ/g|) on samples with |v²κ/g| > 0.05 G.")
    lines.append("Closer to 1.0 = better alignment with GPS-derived centripetal.")
    lines.append("")
    widths = [22, 8, 13, 13, 11, 11, 13, 13]
    header = ["regime", "n", "cal_raw", "cal_cor", "rmse_raw", "rmse_cor", "bias_raw_g", "bias_cor_g"]
    lines.append("```")
    lines.append(" | ".join(h.ljust(w) for h, w in zip(header, widths)))
    lines.append(" | ".join(['-' * w for w in widths]))
    for name, m in regime_metrics.items():
        lines.append(" | ".join([
            name.ljust(widths[0]),
            str(m.n).ljust(widths[1]),
            f"{m.median_ratio_raw:.3f}".ljust(widths[2]) if not np.isnan(m.median_ratio_raw) else "n/a".ljust(widths[2]),
            f"{m.median_ratio_cor:.3f}".ljust(widths[3]) if not np.isnan(m.median_ratio_cor) else "n/a".ljust(widths[3]),
            f"{m.rmse_raw_g:.3f}".ljust(widths[4]),
            f"{m.rmse_cor_g:.3f}".ljust(widths[5]),
            f"{m.signed_bias_raw_g:+.4f}".ljust(widths[6]),
            f"{m.signed_bias_cor_g:+.4f}".ljust(widths[7]),
        ]))
    lines.append("```")
    lines.append("")

    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'regime', 'n_samples',
            'cal_bias_raw', 'cal_bias_cor',
            'rmse_raw_g', 'rmse_cor_g',
            'signed_bias_raw_g', 'signed_bias_cor_g',
        ])
        for name, m in regime_metrics.items():
            w.writerow([name, m.n, m.median_ratio_raw, m.median_ratio_cor,
                        m.rmse_raw_g, m.rmse_cor_g,
                        m.signed_bias_raw_g, m.signed_bias_cor_g])

    # Console summary (ASCII only — Windows console is cp1252)
    print()
    print('=' * 72)
    print('Spread reduction: per-sample -> track-space')
    print('=' * 72)
    print(f'  bank  std:  {per_sample_bank_std:.2f} deg (per-sample) -> '
          f'{track_bank_std:.2f} deg (track-space)   '
          f'= {per_sample_bank_std / max(track_bank_std, 1e-6):.1f}x tighter')
    print(f'  grade std:  {per_sample_grade_std:.2f} deg (per-sample) -> '
          f'{track_grade_std:.2f} deg (track-space)  '
          f'= {per_sample_grade_std / max(track_grade_std, 1e-6):.1f}x tighter')
    print()
    print(f'  bank  valid coverage:  {diag["bank_coverage_frac"]*100:.1f}%')
    print(f'  grade valid coverage:  {diag["grade_coverage_frac"]*100:.1f}%')
    print(f'  mean lap_coverage bank:  {diag["mean_lap_coverage_bank"]:.1f}/{diag["n_laps_total"]} laps')
    print()
    print(f'  mean bank on valid bins:  {diag["mean_bank_on_valid_deg"]:+.2f} deg')
    print(f'  mean grade on valid bins: {diag["mean_grade_on_valid_deg"]:+.2f} deg')
    print()
    print('Per-regime cal_bias (raw -> corrected):')
    for name, m in regime_metrics.items():
        print(f'  {name:22s} {m.median_ratio_raw:5.3f} -> {m.median_ratio_cor:5.3f}   '
              f'rmse {m.rmse_raw_g:.3f} -> {m.rmse_cor_g:.3f}')
    print()
    print(f'Report: {out_md}')
    print(f'CSV:    {out_csv}')


if __name__ == '__main__':
    main()
