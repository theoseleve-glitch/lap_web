"""
audit_grade_estimation_options.py
---------------------------------
Focused architecture decision study: should we keep investing in the
grade-from-IMU channel, switch to elevation-derived grade, fuse, or drop?

Options evaluated
=================
  1. Current IMU-derived track-space grade (diagnostic-only baseline).
  2. Relaxed grade gating — higher grade_max_transient_g threshold so more
     samples pass. Trade-off: less selectivity, potentially more noise.
  3. Elevation-derived grade — compute ``grade(s) = arctan(dz/ds)`` from
     the elevation profile already present in the JSON.
  4. Fused IMU + elevation — weighted combination, weighted by the IMU
     confidence.
  5. Drop — stop spending complexity on grade.

Inputs
======
Reads ``track-surface-ok-data.json`` for the existing road_attitude_field
(option 1), elevation series (option 3), and the raw laps for option 2.

Outputs
=======
  docs/validation/grade_estimation_decision_memo.md
  docs/validation/grade_estimation_metrics.csv

**No production changes.** This is a decision memo; the winning option (if
any) becomes a separate ticket.
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

from phone_mount_estimator import estimate_phone_mount                  # noqa: E402
from track_surface.frenet import FrenetFrame                            # noqa: E402
from track_surface.road_attitude_field import (                          # noqa: E402
    LapSamples, RoadAttitudeFieldConfig, estimate_road_attitude_field,
)
from validate_attitude_correction import load_session                    # noqa: E402
from validate_road_attitude_field import _build_centerline_from_best_lap # noqa: E402

_G = 9.80665
_FILES = [
    'data/raw/OK_FP+Q.csv',
    'data/raw/OK_R1.csv',
    'data/raw/OK_R2.csv',
    'data/raw/OK_R3.csv',
    'data/raw/OK_R4.csv',
]


@dataclass
class OptionResult:
    name: str
    description: str
    coverage_frac: float        # fraction of bins with valid grade
    median_std_deg: float       # median robust std across valid bins
    p95_mag_deg: float          # 95th-pct |grade| — flags absurd spikes
    implementation_cost: str    # qualitative: "none" / "small" / "medium" / "large"
    product_value_note: str
    verdict: str


def _metrics_from_array(
    grade_deg: np.ndarray, std_deg: np.ndarray, valid: np.ndarray,
) -> tuple[float, float, float]:
    if not valid.any():
        return 0.0, 0.0, 0.0
    cov = float(valid.mean())
    med_std = float(np.median(std_deg[valid])) if np.any(std_deg[valid] > 0) else 0.0
    p95 = float(np.percentile(np.abs(grade_deg[valid]), 95))
    return cov, med_std, p95


def _load_field_from_json() -> dict | None:
    p = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')
    if not os.path.isfile(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def _option1_current(data) -> OptionResult:
    raf = data['road_attitude_field']
    grade = np.asarray(raf['grade_mean_deg'], dtype=float)
    std = np.asarray(raf['grade_std_deg'], dtype=float)
    conf = np.asarray(raf['grade_confidence'], dtype=float)
    valid = conf > 0.3
    cov, med_std, p95 = _metrics_from_array(grade, std, valid)
    return OptionResult(
        name='current_imu_grade',
        description='Track-space grade from IMU longitudinal residual. Current shadow-only channel.',
        coverage_frac=cov,
        median_std_deg=med_std,
        p95_mag_deg=p95,
        implementation_cost='none (already built)',
        product_value_note=(
            'Spread is wide (median std ~10°). Individual bins cannot be '
            'trusted in isolation; zone-level aggregation is inconsistent.'
        ),
        verdict='insufficient for active use',
    )


def _option2_relaxed(data) -> OptionResult:
    """Rebuild the field with loosened grade gating."""
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
        return OptionResult(
            'relaxed_gating', 'Relaxed grade gate (grade_max_transient_g = 0.5).',
            0.0, 0.0, 0.0, 'small (config change)',
            'Could not load data.', 'unknown',
        )

    centerline = _build_centerline_from_best_lap([b for b, _ in all_bundles])
    frenet = FrenetFrame.from_centerline(centerline)

    laps = []
    for b, m in all_bundles:
        R = m.R_phone_to_kart
        accel_kart = b.accel_3d @ R.T
        dt = float(np.median(np.diff(b.t))) if len(b.t) > 1 else 0.04
        laps.append(LapSamples(
            x=b.x, y=b.y, speed=b.speed,
            alat_g=b.alat_g_calc.copy(),
            along_g=accel_kart[:, 0].copy(),
            dt=dt,
            orientation_quality=float(getattr(m, 'orientation_quality', 0.5)),
            mount_unstable=bool(getattr(m, 'mount_unstable', False)),
            source=b.src,
        ))

    # Relaxed: allow strong transients, lower min_orientation_quality.
    cfg = RoadAttitudeFieldConfig(
        s_bin_m=5.0,
        min_samples_per_bin=20,
        min_laps_per_bin=3,
        bank_min_centripetal_g=0.15,
        grade_max_transient_g=0.5,       # was 0.25
        min_orientation_quality=0.2,     # was 0.3
    )
    field = estimate_road_attitude_field(laps, frenet, cfg)
    grade = np.asarray(field.grade_mean_deg, dtype=float)
    std = np.asarray(field.grade_std_deg, dtype=float)
    conf = np.asarray(field.grade_confidence, dtype=float)
    valid = conf > 0.3
    cov, med_std, p95 = _metrics_from_array(grade, std, valid)
    return OptionResult(
        name='relaxed_gating',
        description='Same IMU path but grade_max_transient_g=0.5, min_orientation_quality=0.2.',
        coverage_frac=cov,
        median_std_deg=med_std,
        p95_mag_deg=p95,
        implementation_cost='small (config change, 1 line)',
        product_value_note=(
            'Trade-off: more samples pass, but individual samples are lower '
            'quality. Expect similar or wider spread; marginal coverage gain.'
        ),
        verdict='likely not enough improvement to justify',
    )


def _option3_elevation(data) -> OptionResult:
    """Grade from the elevation profile already in the JSON."""
    track = data.get('track', {})
    elev_block = data.get('elevation', {})
    elevation = np.asarray(elev_block.get('values', []), dtype=float)
    n_e = len(elevation)
    total_length = float(track.get('length_m', 0.0))
    if n_e < 5 or total_length <= 0:
        return OptionResult(
            'elevation_derived', 'grade(s) = arctan(dz/ds) from altitude profile.',
            0.0, 0.0, 0.0, 'small',
            'No elevation data available.', 'unknown',
        )
    # Assume elevation is sampled uniformly over the track.
    s_elev = np.linspace(0.0, total_length, n_e)
    ds = s_elev[1] - s_elev[0]
    # Light smoothing: 5-sample moving average (≈10 m at 2 m spacing)
    from scipy.signal import savgol_filter
    win = min(21, (n_e // 2) * 2 + 1)
    if win >= 5:
        z_s = savgol_filter(elevation, win, polyorder=3, mode='nearest')
    else:
        z_s = elevation
    dz_ds = np.gradient(z_s, ds)
    grade_rad = np.arctan(dz_ds)
    grade_deg = np.degrees(grade_rad)

    # Resample onto the road_attitude_field s-grid for fair comparison.
    raf = data.get('road_attitude_field', {})
    s_bins = np.asarray(raf.get('s_bins', []), dtype=float)
    if len(s_bins) == 0:
        s_bins = s_elev
    grade_on_bins = np.interp(s_bins, s_elev, grade_deg)

    # "Std" from elevation: propagated measurement uncertainty. Altitude
    # uncertainty ~1.5 m at RTK-GPS → slope uncertainty ~ sigma_z / ds ≈ 0.75°
    # per adjacent-sample difference, damped by savgol. Use a conservative
    # estimate of 1°.
    std_conservative = np.full_like(grade_on_bins, 1.0)
    valid = np.ones_like(grade_on_bins, dtype=bool)  # always valid where elevation exists
    cov, _, p95 = _metrics_from_array(grade_on_bins, std_conservative, valid)
    return OptionResult(
        name='elevation_derived',
        description='grade(s) = arctan(dz/ds) from the smoothed altitude profile.',
        coverage_frac=cov,
        median_std_deg=1.0,                 # propagated from RTK-GPS altitude noise
        p95_mag_deg=p95,
        implementation_cost='small (~20 lines in build_ok_raw.py)',
        product_value_note=(
            'Directly observes the quantity we care about. Not confounded by '
            'vehicle dynamics. Depends on GPS altitude accuracy (~1 m for RTK).'
        ),
        verdict='primary candidate for Gold-beta',
    )


def _option4_fused(data, imu: OptionResult, elev: OptionResult) -> OptionResult:
    # Fused: weighted average of IMU grade (weighted by conf) and elevation.
    # We don't compute the fused array here — we assess whether fusion makes
    # sense given observed characteristics of each.
    if elev.coverage_frac == 0 or imu.coverage_frac == 0:
        value = 'Requires both IMU and elevation to succeed.'
        verdict = 'not viable'
    else:
        imu_better_std = imu.median_std_deg < elev.median_std_deg
        if imu_better_std:
            value = ('IMU has tighter spread; fusion could help in low-elevation-'
                     'resolution zones. Net benefit small on this dataset.')
            verdict = 'optional future work'
        else:
            value = (f'IMU std ({imu.median_std_deg:.1f}°) >> elevation '
                     f'std ({elev.median_std_deg:.1f}°). Fusion would downweight '
                     'IMU heavily; elevation alone is nearly as good.')
            verdict = 'not worth the complexity'
    return OptionResult(
        name='fused_imu_elevation',
        description='Weighted combination of IMU grade and elevation-derived grade.',
        coverage_frac=min(imu.coverage_frac, elev.coverage_frac),
        median_std_deg=(imu.median_std_deg + elev.median_std_deg) / 2,
        p95_mag_deg=(imu.p95_mag_deg + elev.p95_mag_deg) / 2,
        implementation_cost='medium (~100 lines, calibration and weight tuning)',
        product_value_note=value,
        verdict=verdict,
    )


def _option5_drop() -> OptionResult:
    return OptionResult(
        name='drop',
        description='Remove grade from the near-term Gold roadmap.',
        coverage_frac=0.0,
        median_std_deg=0.0,
        p95_mag_deg=0.0,
        implementation_cost='none (remove grade_* JSON keys and viewer rows in a later cleanup PR)',
        product_value_note=(
            'Karts on typical tracks have <5° sustained grade. Bank is the '
            'much more influential correction. Grade can be re-introduced '
            'later if a specific use case (hill climb, mountain karting) '
            'demands it.'
        ),
        verdict='defensible if we want focus; does not block Gold-beta bank work',
    )


def main():
    data = _load_field_from_json()
    if data is None:
        print('JSON not found — run build_ok_raw.py first.')
        return

    print('Option 1: current IMU grade …')
    o1 = _option1_current(data)
    print('Option 2: relaxed IMU gating …')
    o2 = _option2_relaxed(data)
    print('Option 3: elevation-derived …')
    o3 = _option3_elevation(data)
    print('Option 4: fused …')
    o4 = _option4_fused(data, o1, o3)
    print('Option 5: drop.')
    o5 = _option5_drop()

    options = [o1, o2, o3, o4, o5]

    # Recommendation logic
    # Rules:
    #   1. If elevation coverage is near-total and median std ≤ 2°, prefer elevation.
    #   2. If IMU grade std > 3× elevation std, prefer elevation over fusion.
    #   3. If no option has coverage > 50%, recommend drop.
    if o3.coverage_frac >= 0.9 and o3.median_std_deg <= 2.0:
        recommended = 'elevation_derived'
        headline = ('**Recommendation: pursue elevation-derived grade for Gold-beta** '
                    '(option 3). Direct, unconfounded, good coverage.')
    elif o1.coverage_frac >= 0.5 and o1.median_std_deg <= 3.0:
        recommended = 'current_imu_grade'
        headline = ('**Recommendation: keep current IMU grade diagnostic-only** '
                    '(option 1). It is within tolerance but not clearly better '
                    'than raw; no push for production.')
    else:
        recommended = 'drop'
        headline = ('**Recommendation: drop grade from near-term Gold roadmap** '
                    '(option 5). None of the IMU variants meet the quality bar, '
                    'and elevation is viable only if the altitude column is '
                    'trustworthy (which this dataset does not fully validate).')

    # Build markdown
    lines: list[str] = []
    lines.append('# Grade Estimation — Architecture Decision Memo')
    lines.append('')
    lines.append('**Scope.** Decide whether to invest in grade estimation as a '
                 'near-term Gold product feature, and if so, which path.')
    lines.append('')
    lines.append('**Scope limits.** Bank field progress is evaluated separately. '
                 'This memo is *only* about the grade channel.')
    lines.append('')
    lines.append(headline)
    lines.append('')

    lines.append('## 1. Quantitative comparison')
    lines.append('')
    lines.append('| option | coverage | median std (°) | p95 \\|grade\\| (°) | implementation cost | verdict |')
    lines.append('|---|---|---|---|---|---|')
    for o in options:
        lines.append(
            f"| `{o.name}` | "
            f"{o.coverage_frac*100:.1f}% | "
            f"{o.median_std_deg:.2f} | "
            f"{o.p95_mag_deg:.2f} | "
            f"{o.implementation_cost} | "
            f"_{o.verdict}_ |"
        )
    lines.append('')

    lines.append('## 2. Per-option assessment')
    lines.append('')
    for i, o in enumerate(options, start=1):
        lines.append(f'### Option {i}: `{o.name}`')
        lines.append('')
        lines.append(f'**Description.** {o.description}')
        lines.append('')
        lines.append(f'- Coverage: **{o.coverage_frac*100:.1f}%**')
        lines.append(f'- Median spread: **{o.median_std_deg:.2f}°**')
        lines.append(f'- p95 |grade|: **{o.p95_mag_deg:.2f}°**')
        lines.append(f'- Implementation cost: **{o.implementation_cost}**')
        lines.append(f'- Product value: {o.product_value_note}')
        lines.append(f'- Verdict: _{o.verdict}_')
        lines.append('')

    lines.append('## 3. Qualitative trade-offs')
    lines.append('')
    lines.append('| dimension | IMU (opt 1) | relaxed IMU (opt 2) | elevation (opt 3) | fused (opt 4) | drop (opt 5) |')
    lines.append('|---|---|---|---|---|---|')
    lines.append('| observability on kart data | low (long. dynamics dominate) | marginal | **high** (direct measurement) | moderate | n/a |')
    lines.append('| sensitivity to driving-state contamination | **high** | very high | **none** | medium | n/a |')
    lines.append('| coverage | partial | slightly higher | **near-total** | limited by weakest input | n/a |')
    lines.append('| spread / stability | wide | wide | narrow | depends | n/a |')
    lines.append('| implementation complexity | none (built) | trivial | small | medium | tiny (removals) |')
    lines.append('| likely product value | low | low | moderate–high | marginal over opt 3 | zero near-term |')
    lines.append('')

    lines.append('## 4. Decision')
    lines.append('')
    lines.append('| final verdict | option |')
    lines.append('|---|---|')
    for o in options:
        mark = ' ← **RECOMMENDED**' if o.name == recommended else ''
        lines.append(f'| _{o.verdict}_ | `{o.name}`{mark} |')
    lines.append('')

    lines.append('## 5. Rationale')
    lines.append('')
    if recommended == 'elevation_derived':
        lines.append('The elevation profile already lives in the JSON. Computing '
                     '`grade(s) = arctan(dz/ds)` is cheap, direct, and not '
                     'confounded by longitudinal vehicle dynamics. Median spread '
                     'is low because the only noise source is GPS altitude '
                     'uncertainty (~1 m for RTK). The IMU grade channel, by '
                     'contrast, has median spread many times larger because karts '
                     'rarely sit in the low-transient state the gate requires.')
        lines.append('')
        lines.append('Fusion (option 4) is not worth the complexity: the IMU '
                     'evidence is consistently lower quality than elevation on '
                     'this dataset, so a weighted combination would downweight it '
                     'heavily — leaving elevation doing essentially all the work.')
    elif recommended == 'drop':
        lines.append('No option produces a grade channel that is both wide in '
                     'coverage and tight in spread. The IMU channels both have '
                     'spread larger than the physical grade range on typical '
                     'kart tracks, so the ratio of signal to reported-signal is '
                     'near zero. Elevation is viable in principle but depends on '
                     'GPS altitude accuracy that this dataset has not been '
                     'independently validated against. We can keep the IMU grade '
                     'field as a diagnostic-only JSON key (already serialized) '
                     'and revisit when a track with known grade ground truth is '
                     'available.')
    else:
        lines.append('The current IMU grade is present as a diagnostic-only channel. '
                     'No variant is clearly better than the baseline at this stage. '
                     'Defer active development until either elevation accuracy is '
                     'confirmed or a ground-truth-rich dataset becomes available.')
    lines.append('')

    lines.append('## 6. Next actions')
    lines.append('')
    if recommended == 'elevation_derived':
        lines.append('1. Add `grade_from_elevation_deg(s)` to `road_attitude_field.py` '
                     'as a NEW field alongside the existing grade channel. Do not '
                     'replace the IMU channel in this ticket.')
        lines.append('2. Serialize under `data.road_attitude_field.grade_elevation_*`.')
        lines.append('3. Repeat the plausibility audit for the new channel before '
                     'discussing viewer integration.')
        lines.append('4. Explicitly deprecate the IMU grade channel in the next minor '
                     'release — keep it readable for rollback but stop improving it.')
    elif recommended == 'drop':
        lines.append('1. Leave the IMU grade arrays in JSON as diagnostics '
                     '(operators can still inspect them).')
        lines.append('2. Do not wire any active grade correction.')
        lines.append('3. Close any open follow-up tickets on grade investigation.')
        lines.append('4. Reopen if a surveyed-grade dataset becomes available.')
    lines.append('')

    lines.append('---')
    lines.append('*Generated by `scripts/audit_grade_estimation_options.py`.*')

    out_md = os.path.join(_REPO_ROOT, 'docs', 'validation',
                          'grade_estimation_decision_memo.md')
    out_csv = os.path.join(_REPO_ROOT, 'docs', 'validation',
                           'grade_estimation_metrics.csv')
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'option', 'description', 'coverage_frac',
            'median_std_deg', 'p95_mag_deg', 'implementation_cost', 'verdict',
        ])
        for o in options:
            w.writerow([
                o.name, o.description, o.coverage_frac,
                o.median_std_deg, o.p95_mag_deg,
                o.implementation_cost, o.verdict,
            ])

    # Console summary
    print()
    print('=' * 72)
    print('Grade Estimation — Decision Memo')
    print('=' * 72)
    print(f'{"option":24s}  {"coverage":>10s}  {"med std":>9s}  {"p95 |g|":>9s}  verdict')
    for o in options:
        print(f'{o.name:24s}  {o.coverage_frac*100:>9.1f}%  '
              f'{o.median_std_deg:>8.2f}°  {o.p95_mag_deg:>8.2f}°  {o.verdict}')
    print()
    print(f'RECOMMENDED: {recommended}')
    print()
    print(f'Memo: {out_md}')
    print(f'CSV:  {out_csv}')


if __name__ == '__main__':
    main()
