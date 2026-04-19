"""
validate_grade_field_correction_shadow.py
-----------------------------------------
Shadow-mode validation of the elevation-grade correction on longitudinal
demand. Per-regime comparison of three channels:

    raw_imu   — kart-frame IMU x-axis (after mount rotation).
    corrected — raw_imu + sin(grade_elevation_mean_deg(s_of_sample))
                applied only where grade_elevation_confidence(s) ≥ T.
    dvdt_ref  — GPS-derived dv/dt_g. External reference.

**No production correction is enabled.** Bronze and Silver are not touched.
The repo does not expose a canonical bronze longitudinal demand product,
so this script reports on a diagnostic aggregate computed from per-lap IMU.

Metric
======
``long_residual_rmse`` = RMSE(channel − dv/dt_g) in G.

Rationale: on flat ground, gravity-compensated IMU ≈ dv/dt_g. On grade,
raw differs from dv/dt_g by sin(grade); corrected should match. Smaller
residual = better alignment with the one external reference we have.

We also report ``signed_bias`` (mean(channel − dv/dt_g)) to detect
systematic over/under correction per regime.

Outputs
=======
    docs/validation/grade_field_correction_shadow_report.md
    docs/validation/grade_field_correction_shadow_metrics.csv
"""
from __future__ import annotations

import csv
import json
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

from phone_mount_estimator import estimate_phone_mount                 # noqa: E402
from track_surface.frenet import FrenetFrame                            # noqa: E402
from validate_attitude_correction import (                               # noqa: E402
    _CORNER_KAPPA, _HARD_ACCEL_G, _HARD_BRAKE_G, _STRAIGHT_KAPPA,
    _curvature_from_xy, load_session,
)
from validate_road_attitude_field import _build_centerline_from_best_lap  # noqa: E402

_G = 9.80665
_FILES = [
    'data/raw/OK_FP+Q.csv',
    'data/raw/OK_R1.csv',
    'data/raw/OK_R2.csv',
    'data/raw/OK_R3.csv',
    'data/raw/OK_R4.csv',
]
GRADE_CONFIDENCE_THRESHOLD = 0.60


@dataclass
class RegimeRow:
    n: int
    rmse_raw: float
    rmse_cor: float
    rmse_dvdt: float    # reference baseline: |dvdt - dvdt| = 0 (diagnostic)
    bias_raw: float
    bias_cor: float
    applied_frac: float


def _regime_stats(
    along_raw, along_cor, dvdt, mask, applied,
) -> RegimeRow:
    n = int(mask.sum())
    if n == 0:
        nan = float('nan')
        return RegimeRow(0, nan, nan, nan, nan, nan, nan)
    ar = along_raw[mask]
    ac = along_cor[mask]
    ref = dvdt[mask]
    ap = applied[mask]
    rmse_raw = float(np.sqrt(np.mean((ar - ref) ** 2)))
    rmse_cor = float(np.sqrt(np.mean((ac - ref) ** 2)))
    bias_raw = float(np.mean(ar - ref))
    bias_cor = float(np.mean(ac - ref))
    return RegimeRow(n, rmse_raw, rmse_cor, 0.0, bias_raw, bias_cor, float(ap.mean()))


def _load_field():
    p = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')
    if not os.path.isfile(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    raf = data.get('road_attitude_field')
    if not raf or not raf.get('grade_elevation_mean_deg'):
        return None
    return raf


def main():
    raf = _load_field()
    if raf is None:
        print('Elevation grade field missing — run build_ok_raw.py first.')
        return

    s_bins = np.asarray(raf['s_bins'], dtype=float)
    grade = np.asarray(raf['grade_elevation_mean_deg'], dtype=float)
    grade_conf = np.asarray(raf['grade_elevation_confidence'], dtype=float)

    # Load per-lap data + mount per session.
    all_bundles = []
    for path in _FILES:
        ab = os.path.join(_REPO_ROOT, path)
        if not os.path.isfile(ab):
            continue
        bundles = load_session(ab)
        if not bundles:
            continue
        cal = max(bundles, key=lambda b: len(b.t))
        try:
            mount = estimate_phone_mount(cal.accel_3d, cal.gyro_3d, cal.speed, cal.t)
        except Exception:
            continue
        for b in bundles:
            all_bundles.append((b, mount))

    if not all_bundles:
        print('No bundles loaded.')
        return

    centerline = _build_centerline_from_best_lap([b for b, _ in all_bundles])
    frenet = FrenetFrame.from_centerline(centerline)
    total_length = float(frenet.total_length_m)

    along_raw_parts, along_cor_parts, dvdt_parts = [], [], []
    applied_parts = []
    # Regime masks:
    mparts = {k: [] for k in (
        'all_valid', 'braking', 'accelerating', 'steady_throttle',
        'uphill', 'downhill', 'straight',
    )}

    for b, m in all_bundles:
        R = m.R_phone_to_kart
        accel_kart_x = (b.accel_3d @ R.T)[:, 0]
        dt = float(np.median(np.diff(b.t))) if len(b.t) > 1 else 0.04
        dvdt = np.gradient(b.speed) / max(dt, 1e-6) / _G
        curv = _curvature_from_xy(b.x, b.y, b.speed)

        s_arr, _ = frenet.xy_to_sn(b.x, b.y)
        s_arr = np.mod(s_arr, total_length) if total_length > 0 else s_arr
        grade_at_sample = np.interp(s_arr, s_bins, grade)
        conf_at_sample = np.interp(s_arr, s_bins, grade_conf)
        applied = conf_at_sample >= GRADE_CONFIDENCE_THRESHOLD
        along_cor = np.where(
            applied,
            accel_kart_x + np.sin(np.deg2rad(grade_at_sample)),
            accel_kart_x,
        )

        v_ok = b.speed > 5.0
        mparts['all_valid'].append(v_ok)
        mparts['braking'].append((dvdt < _HARD_BRAKE_G) & v_ok)
        mparts['accelerating'].append((dvdt > _HARD_ACCEL_G) & v_ok)
        mparts['steady_throttle'].append((np.abs(dvdt) < 0.1) & (np.abs(curv) < 0.01) & v_ok)
        mparts['uphill'].append((grade_at_sample > 1.0) & v_ok)
        mparts['downhill'].append((grade_at_sample < -1.0) & v_ok)
        mparts['straight'].append((np.abs(curv) < _STRAIGHT_KAPPA) & v_ok)

        along_raw_parts.append(accel_kart_x)
        along_cor_parts.append(along_cor)
        dvdt_parts.append(dvdt)
        applied_parts.append(applied)

    along_raw = np.concatenate(along_raw_parts)
    along_cor = np.concatenate(along_cor_parts)
    dvdt = np.concatenate(dvdt_parts)
    applied = np.concatenate(applied_parts)

    rows: dict[str, RegimeRow] = {}
    for name, lst in mparts.items():
        mask = np.concatenate(lst)
        rows[name] = _regime_stats(along_raw, along_cor, dvdt, mask, applied)

    # ── Report ──
    out_md = os.path.join(_REPO_ROOT, 'docs', 'validation',
                          'grade_field_correction_shadow_report.md')
    out_csv = os.path.join(_REPO_ROOT, 'docs', 'validation',
                           'grade_field_correction_shadow_metrics.csv')
    os.makedirs(os.path.dirname(out_md), exist_ok=True)

    lines: list[str] = []
    lines.append('# Elevation-Grade Correction — Longitudinal Shadow Experiment')
    lines.append('')
    lines.append('**Purpose.** Measure whether confidence-gated elevation-grade '
                 'correction moves IMU longitudinal accel toward GPS-derived '
                 '`dv/dt_g` by more than noise. No production correction is '
                 'enabled. Bronze and Silver are unchanged.')
    lines.append('')
    lines.append('**Product boundary.** The repo does not expose a bronze '
                 'longitudinal demand product analogous to '
                 '`lateral_demand.excited_p90`. These metrics are computed on '
                 'per-lap IMU samples directly; they are diagnostic, not '
                 'canonical.')
    lines.append('')
    lines.append('**Correction formula** (pinned by '
                 '`test_longitudinal_grade_shadow.py`):')
    lines.append('```')
    lines.append('corrected_along = raw_along_imu + sin(grade_elevation_rad)')
    lines.append('   applied where grade_elevation_confidence(s) ≥ '
                 f'{GRADE_CONFIDENCE_THRESHOLD}; else pass raw through.')
    lines.append('```')
    lines.append('')
    lines.append('**Metric.** `rmse` = RMSE(channel − dv/dt_g). Smaller is '
                 'better. `bias` = mean(channel − dv/dt_g). Closer to 0 is better.')
    lines.append('')
    lines.append('## 1. Per-regime results')
    lines.append('')
    lines.append('| regime | n | rmse_raw | rmse_cor | Δrmse | bias_raw | bias_cor | applied |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for name, r in rows.items():
        drmse = r.rmse_cor - r.rmse_raw
        sign = '−' if drmse < 0 else '+'
        lines.append(
            f'| {name} | {r.n} | {r.rmse_raw:.3f} | {r.rmse_cor:.3f} | '
            f'{sign}{abs(drmse):.3f} | {r.bias_raw:+.3f} | {r.bias_cor:+.3f} | '
            f'{r.applied_frac*100:.1f}% |'
        )
    lines.append('')

    lines.append('## 2. Per-regime winners')
    lines.append('')
    lines.append('| regime | winner (smaller rmse) | margin (G) |')
    lines.append('|---|---|---|')
    for name, r in rows.items():
        if r.rmse_cor < r.rmse_raw:
            winner = 'corrected'
            margin = r.rmse_raw - r.rmse_cor
        elif r.rmse_cor > r.rmse_raw:
            winner = 'raw'
            margin = r.rmse_cor - r.rmse_raw
        else:
            winner = 'tie'
            margin = 0.0
        lines.append(f'| {name} | **{winner}** | {margin:.3f} |')
    lines.append('')

    # Verdict
    r_all = rows['all_valid']
    corrected_helps = r_all.rmse_cor < r_all.rmse_raw - 0.005    # meaningful margin
    corrected_hurts = r_all.rmse_cor > r_all.rmse_raw + 0.005
    n_winning_regimes = sum(1 for r in rows.values() if r.rmse_cor < r.rmse_raw)

    lines.append('## 3. Verdict')
    lines.append('')
    if corrected_helps and n_winning_regimes >= 4:
        verdict = 'USEFUL — opt-in candidate'
        rec = ('Correction reduces residual-to-reference by a meaningful '
               'margin on most regimes. Consider promoting to opt-in after '
               'a viewer-mode review.')
    elif corrected_helps:
        verdict = 'MARGINAL'
        rec = ('Correction reduces residual overall but loses on several '
               'regimes. Keep shadow-only; do not ship a viewer mode.')
    elif corrected_hurts:
        verdict = 'HARMFUL'
        rec = ('Correction makes the residual worse. Do not ship. Investigate '
               'elevation signal quality or sign convention.')
    else:
        verdict = 'NEUTRAL'
        rec = ('Correction is neither clearly better nor worse than raw. Keep '
               'shadow-only; revisit when a track with verified grade ground '
               'truth is available.')

    lines.append(f'**Verdict: {verdict}**')
    lines.append('')
    lines.append(f'- all_valid rmse:  raw **{r_all.rmse_raw:.3f}** → corrected **{r_all.rmse_cor:.3f}** (Δ = {r_all.rmse_cor - r_all.rmse_raw:+.3f} G)')
    lines.append(f'- all_valid bias:  raw **{r_all.bias_raw:+.3f}** → corrected **{r_all.bias_cor:+.3f}** G')
    lines.append(f'- winning regimes: **{n_winning_regimes}/{len(rows)}**')
    lines.append('')
    lines.append('## 4. Recommendation')
    lines.append('')
    lines.append(rec)
    lines.append('')
    lines.append('---')
    lines.append(f'*Generated by `scripts/validate_grade_field_correction_shadow.py`. '
                 f'Confidence gate: {GRADE_CONFIDENCE_THRESHOLD}.*')

    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['regime', 'n', 'rmse_raw', 'rmse_cor', 'delta_rmse',
                    'bias_raw', 'bias_cor', 'applied_frac'])
        for name, r in rows.items():
            w.writerow([name, r.n, r.rmse_raw, r.rmse_cor,
                        r.rmse_cor - r.rmse_raw,
                        r.bias_raw, r.bias_cor, r.applied_frac])

    # Console
    print()
    print('=' * 72)
    print('Elevation-grade longitudinal shadow experiment — all_valid')
    print('=' * 72)
    print(f'  rmse (G):   raw {r_all.rmse_raw:.3f}  -> cor {r_all.rmse_cor:.3f}   '
          f'(delta {r_all.rmse_cor - r_all.rmse_raw:+.3f})')
    print(f'  bias (G):   raw {r_all.bias_raw:+.3f}  -> cor {r_all.bias_cor:+.3f}')
    print(f'  applied:    {r_all.applied_frac*100:.1f}%')
    print(f'  winning regimes: {n_winning_regimes}/{len(rows)}')
    print(f'  VERDICT: {verdict}')
    print()
    print('Per-regime:')
    for name, r in rows.items():
        print(f'  {name:18s}  n={r.n:>6d}  raw {r.rmse_raw:.3f}  cor {r.rmse_cor:.3f}  '
              f'delta {r.rmse_cor - r.rmse_raw:+.3f}')
    print()
    print(f'Report: {out_md}')


if __name__ == '__main__':
    main()
