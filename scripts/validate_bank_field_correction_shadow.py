"""
validate_bank_field_correction_shadow.py
----------------------------------------
Shadow-only experiment: compare three lateral-demand channels against
GPS-derived centripetal (v²κ/g) on the real OK karting dataset.

   raw          = RaceChrono *calc lateral G (signed, unchanged)
   per_sample   = raw − sin(bank_per_sample) from the legacy estimator
   bank_field   = raw − sin(bank_field(s)) gated on bank_confidence(s) ≥ T

**This script is strictly additive.** It does not modify production or
enable any correction pathway. Its sole output is a report showing which
(if any) correction channel is better than raw.

Confidence-gated correction rule:

    if bank_confidence(s_i) ≥ BANK_CONFIDENCE_THRESHOLD
       and not mount_unstable:
        alat_shadow[i] = alat_raw[i] − sin(bank_field(s_i))
    else:
        alat_shadow[i] = alat_raw[i]

Outputs:
    docs/validation/bank_field_correction_shadow_report.md
    docs/validation/bank_field_correction_shadow_metrics.csv
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
from road_attitude_estimator import estimate_road_attitude              # noqa: E402
from track_surface.frenet import FrenetFrame                            # noqa: E402
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

# Confidence gate for the bank-field shadow correction. Informed by the
# plausibility audit: p50 confidence ≈ 0.70, so gating at 0.60 keeps the
# majority of the confident portion of the track in-scope while cutting
# off the uncertain half.
BANK_CONFIDENCE_THRESHOLD = 0.60


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _build_centerline_from_best_lap(bundles):
    from scipy.signal import savgol_filter
    best = max(bundles, key=lambda b: len(b.t))
    win = min(25, len(best.x) if len(best.x) % 2 == 1 else len(best.x) - 1)
    win = max(win, 5)
    cx = savgol_filter(best.x, win, polyorder=3, mode='nearest')
    cy = savgol_filter(best.y, win, polyorder=3, mode='nearest')
    dx = np.diff(cx)
    dy = np.diff(cy)
    s_cl = np.concatenate([[0.0], np.cumsum(np.sqrt(dx ** 2 + dy ** 2))])
    total = float(s_cl[-1])
    s_uniform = np.arange(0.0, total, 2.0)
    return np.column_stack([
        np.interp(s_uniform, s_cl, cx),
        np.interp(s_uniform, s_cl, cy),
    ])


@dataclass
class RegimeRow:
    n: int
    raw_cal: float
    raw_rmse: float
    raw_mae: float
    ps_cal: float
    ps_rmse: float
    ps_mae: float
    ps_applied_frac: float
    bf_cal: float
    bf_rmse: float
    bf_mae: float
    bf_applied_frac: float
    bf_conf_weighted_applied: float


def _cal_bias(a_abs: np.ndarray, cp_abs: np.ndarray) -> float:
    m = cp_abs > 0.05
    if not m.any():
        return float('nan')
    return float(np.median(a_abs[m] / cp_abs[m]))


def _metrics(a: np.ndarray, cp: np.ndarray) -> tuple[float, float, float]:
    a_abs = np.abs(a)
    cp_abs = np.abs(cp)
    cal = _cal_bias(a_abs, cp_abs)
    rmse = float(np.sqrt(np.mean((a_abs - cp_abs) ** 2))) if len(a) else float('nan')
    mae = float(np.mean(np.abs(a_abs - cp_abs))) if len(a) else float('nan')
    return cal, rmse, mae


def _load_field_from_json() -> dict | None:
    p = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')
    if not os.path.isfile(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    raf = data.get('road_attitude_field')
    if raf is None or not raf.get('s_bins'):
        return None
    return raf


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────


def main():
    raf = _load_field_from_json()
    if raf is None:
        print('road_attitude_field unavailable — run build_ok_raw.py first.')
        return

    s_bins = np.asarray(raf['s_bins'], dtype=float)
    bank_field = np.asarray(raf['bank_mean_deg'], dtype=float)
    bank_conf = np.asarray(raf['bank_confidence'], dtype=float)

    # Load raw data + mount per session.
    all_bundles = []
    for path in _FILES:
        abs_path = os.path.join(_REPO_ROOT, path)
        if not os.path.isfile(abs_path):
            continue
        bundles = load_session(abs_path)
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

    # Build shared centerline + Frenet.
    centerline = _build_centerline_from_best_lap([b for b, _ in all_bundles])
    frenet = FrenetFrame.from_centerline(centerline)
    total_length = float(frenet.total_length_m)

    # Per-sample collectors
    raw_parts = []
    ps_parts = []
    bf_parts = []
    cp_parts = []
    ps_applied_parts = []
    bf_applied_parts = []
    bf_conf_parts = []
    mask_parts = {k: [] for k in (
        'all_valid', 'straight', 'left_corner', 'right_corner',
        'braking', 'accelerating', 'steady_mid_corner',
    )}

    for bundle, mount in all_bundles:
        curv = _curvature_from_xy(bundle.x, bundle.y, bundle.speed)
        cp = bundle.speed ** 2 * curv / _G
        dt = float(np.median(np.diff(bundle.t))) if len(bundle.t) > 1 else 0.04
        dvdt = np.gradient(bundle.speed) / dt / _G
        alat_raw = bundle.alat_g_calc.copy()

        # ── Per-sample legacy correction ──
        try:
            att = estimate_road_attitude(
                bundle.accel_3d, bundle.gyro_3d, bundle.speed, bundle.t, mount,
                curvature=None,
            )
            q = np.asarray(att.attitude_quality, dtype=float)
            u = np.asarray(att.unstable_segments, dtype=bool)
            ps_apply = (q > 0.4) & ~u
            ps_bank_rad = np.deg2rad(np.asarray(att.bank_deg))
            alat_ps = alat_raw.copy()
            alat_ps[ps_apply] = alat_raw[ps_apply] - np.sin(ps_bank_rad[ps_apply])
        except Exception:
            alat_ps = alat_raw.copy()
            ps_apply = np.zeros_like(alat_raw, dtype=bool)

        # ── Bank-field shadow correction (confidence-gated) ──
        s_arr, _ = frenet.xy_to_sn(bundle.x, bundle.y)
        s_arr = np.mod(s_arr, total_length) if total_length > 0 else s_arr
        bank_at_sample = np.interp(s_arr, s_bins, bank_field)
        conf_at_sample = np.interp(s_arr, s_bins, bank_conf)
        bf_apply = (conf_at_sample >= BANK_CONFIDENCE_THRESHOLD) & (
            not bool(getattr(mount, 'mount_unstable', False))
        )
        alat_bf = alat_raw.copy()
        alat_bf[bf_apply] = alat_raw[bf_apply] - np.sin(np.deg2rad(bank_at_sample[bf_apply]))

        # Regime masks
        v_ok = bundle.speed > 5.0
        k_abs = np.abs(curv)
        mask_parts['all_valid'].append(v_ok)
        mask_parts['straight'].append((k_abs < _STRAIGHT_KAPPA) & v_ok)
        mask_parts['left_corner'].append((curv > _CORNER_KAPPA) & v_ok)
        mask_parts['right_corner'].append((curv < -_CORNER_KAPPA) & v_ok)
        mask_parts['braking'].append((dvdt < _HARD_BRAKE_G) & v_ok)
        mask_parts['accelerating'].append((dvdt > _HARD_ACCEL_G) & v_ok)
        mask_parts['steady_mid_corner'].append(
            (k_abs > _CORNER_KAPPA) & (np.abs(dvdt) < 0.1) & v_ok
        )

        raw_parts.append(alat_raw)
        ps_parts.append(alat_ps)
        bf_parts.append(alat_bf)
        cp_parts.append(cp)
        ps_applied_parts.append(ps_apply)
        bf_applied_parts.append(bf_apply)
        bf_conf_parts.append(conf_at_sample)

    raw = np.concatenate(raw_parts)
    ps = np.concatenate(ps_parts)
    bf = np.concatenate(bf_parts)
    cp = np.concatenate(cp_parts)
    ps_applied = np.concatenate(ps_applied_parts)
    bf_applied = np.concatenate(bf_applied_parts)
    bf_conf = np.concatenate(bf_conf_parts)

    # ── Per-regime metrics ──
    rows: dict[str, RegimeRow] = {}
    for name, mparts in mask_parts.items():
        mask = np.concatenate(mparts)
        n = int(mask.sum())
        if n == 0:
            rows[name] = RegimeRow(
                0, *([float('nan')] * 3), *([float('nan')] * 4), *([float('nan')] * 5)
            )
            continue
        r_cal, r_rmse, r_mae = _metrics(raw[mask], cp[mask])
        p_cal, p_rmse, p_mae = _metrics(ps[mask], cp[mask])
        b_cal, b_rmse, b_mae = _metrics(bf[mask], cp[mask])
        ps_frac = float(ps_applied[mask].mean())
        bf_frac = float(bf_applied[mask].mean())
        # Confidence-weighted applied fraction: sum of conf on applied samples
        # divided by total samples in regime.
        conf_weighted = float(np.sum(bf_conf[mask] * bf_applied[mask]) / max(n, 1))
        rows[name] = RegimeRow(
            n=n,
            raw_cal=r_cal, raw_rmse=r_rmse, raw_mae=r_mae,
            ps_cal=p_cal, ps_rmse=p_rmse, ps_mae=p_mae,
            ps_applied_frac=ps_frac,
            bf_cal=b_cal, bf_rmse=b_rmse, bf_mae=b_mae,
            bf_applied_frac=bf_frac,
            bf_conf_weighted_applied=conf_weighted,
        )

    # ── Build report ──
    out_md = os.path.join(_REPO_ROOT, 'docs', 'validation',
                          'bank_field_correction_shadow_report.md')
    out_csv = os.path.join(_REPO_ROOT, 'docs', 'validation',
                           'bank_field_correction_shadow_metrics.csv')
    os.makedirs(os.path.dirname(out_md), exist_ok=True)

    lines: list[str] = []
    lines.append("# Bank-Field Correction — Shadow Experiment")
    lines.append("")
    lines.append("**Purpose.** Measure whether confidence-gated correction using the "
                 "Gold-alpha-shadow bank field moves observed lateral demand toward "
                 "GPS centripetal better than either raw or the per-sample correction.")
    lines.append("")
    lines.append("**Three channels compared:**")
    lines.append("")
    lines.append("- `raw` — RaceChrono `*calc` lateral G (unchanged).")
    lines.append("- `per_sample` — raw − sin(bank_per_sample) using the legacy "
                 "`estimate_road_attitude` gated on its own per-sample quality.")
    lines.append(f"- `bank_field` — raw − sin(bank_field(s)) applied only where "
                 f"`bank_confidence(s) ≥ {BANK_CONFIDENCE_THRESHOLD}`. Elsewhere the "
                 f"raw value passes through unchanged.")
    lines.append("")
    lines.append("**Reference.** Signed GPS centripetal `v²κ/g`. `cal_bias` = "
                 "median(|channel| / |v²κ/g|) on in-corner samples. Closer to 1.0 "
                 "= better alignment with the one external reference we have.")
    lines.append("")
    lines.append("**Invariant.** No bronze/silver output is modified. No active "
                 "correction path is enabled.")
    lines.append("")

    # Headline
    r_all = rows['all_valid']
    better_raw_bf = r_all.bf_cal is not None and abs(r_all.bf_cal - 1.0) < abs(r_all.raw_cal - 1.0)
    better_ps_bf = r_all.bf_cal is not None and abs(r_all.bf_cal - 1.0) < abs(r_all.ps_cal - 1.0)
    rmse_bf_ok = r_all.bf_rmse <= r_all.raw_rmse + 0.01
    rmse_bf_vs_ps = r_all.bf_rmse <= r_all.ps_rmse

    lines.append("## 1. Headline numbers (all_valid regime)")
    lines.append("")
    lines.append("```")
    lines.append(f"  channel       cal_bias    rmse (G)    mae (G)     applied")
    lines.append(f"  raw           {r_all.raw_cal:>6.3f}     {r_all.raw_rmse:>6.3f}      {r_all.raw_mae:>6.3f}      100.0% (baseline)")
    lines.append(f"  per_sample    {r_all.ps_cal:>6.3f}     {r_all.ps_rmse:>6.3f}      {r_all.ps_mae:>6.3f}      {r_all.ps_applied_frac*100:>5.1f}%")
    lines.append(f"  bank_field    {r_all.bf_cal:>6.3f}     {r_all.bf_rmse:>6.3f}      {r_all.bf_mae:>6.3f}      {r_all.bf_applied_frac*100:>5.1f}% "
                 f"(conf-weighted {r_all.bf_conf_weighted_applied*100:.1f}%)")
    lines.append("```")
    lines.append("")

    # Per-regime tables
    lines.append("## 2. Per-regime comparison")
    lines.append("")
    lines.append("All numbers are on samples where `speed > 5 m/s`.")
    lines.append("")
    lines.append("| regime | n | cal_raw | cal_ps | cal_bf | rmse_raw | rmse_ps | rmse_bf | bf_applied | bf_conf_w |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in rows.items():
        lines.append(
            f"| {name} | {r.n} | "
            f"{r.raw_cal:.3f} | {r.ps_cal:.3f} | {r.bf_cal:.3f} | "
            f"{r.raw_rmse:.3f} | {r.ps_rmse:.3f} | {r.bf_rmse:.3f} | "
            f"{r.bf_applied_frac*100:.1f}% | {r.bf_conf_weighted_applied*100:.1f}% |"
        )
    lines.append("")

    # Regime-wise winners
    lines.append("### Which channel wins per regime?")
    lines.append("")
    lines.append("`win` = `|cal − 1.0|` is the metric; smaller is better.")
    lines.append("")
    lines.append("| regime | raw | per_sample | bank_field | winner |")
    lines.append("|---|---|---|---|---|")
    for name, r in rows.items():
        err_raw = abs(r.raw_cal - 1.0)
        err_ps = abs(r.ps_cal - 1.0)
        err_bf = abs(r.bf_cal - 1.0)
        best = min(err_raw, err_ps, err_bf)
        winner = ('bank_field' if err_bf == best
                  else 'per_sample' if err_ps == best
                  else 'raw')
        lines.append(f"| {name} | {err_raw:.3f} | {err_ps:.3f} | {err_bf:.3f} | "
                     f"**{winner}** |")
    lines.append("")

    # Verdict
    lines.append("## 3. Verdict")
    lines.append("")
    wins = sum(1 for r in rows.values()
               if abs(r.bf_cal - 1.0) <= min(abs(r.raw_cal - 1.0), abs(r.ps_cal - 1.0)))
    total = len(rows)

    # Summary judgment
    if better_raw_bf and better_ps_bf and rmse_bf_ok:
        judgment = 'BETTER_THAN_BOTH'
    elif better_raw_bf and rmse_bf_ok:
        judgment = 'BETTER_THAN_RAW'
    elif abs(r_all.bf_cal - r_all.raw_cal) < 0.02 and rmse_bf_ok:
        judgment = 'NEUTRAL'
    else:
        judgment = 'HARMFUL_OR_INCONCLUSIVE'

    lines.append(f"**Wins across regimes:** bank_field wins {wins}/{total} regimes.")
    lines.append("")
    lines.append(f"**all_valid summary:** cal_bias {r_all.raw_cal:.3f} (raw) → "
                 f"{r_all.ps_cal:.3f} (per-sample) → {r_all.bf_cal:.3f} (bank_field).")
    lines.append(f"**all_valid RMSE:** {r_all.raw_rmse:.3f} → {r_all.ps_rmse:.3f} → "
                 f"{r_all.bf_rmse:.3f} G.")
    lines.append("")

    recommendation: str
    if judgment == 'BETTER_THAN_BOTH':
        lines.append("**Verdict: BETTER THAN BOTH.** Confidence-gated bank-field "
                     "correction moves cal_bias closer to 1.0 than either raw or "
                     "per-sample, without increasing RMSE.")
        recommendation = (
            "Ship-candidate. Recommend: expose the corrected channel as an "
            "optional overlay in the viewer (still separate from canonical "
            "bronze). Run one more round of eyeball validation on the top "
            "plausible zones (§6 of the plausibility audit). If that passes, "
            "cut a PR to promote bank-field correction to an opt-in demand "
            "channel, leaving raw demand as the default."
        )
    elif judgment == 'BETTER_THAN_RAW':
        lines.append("**Verdict: BETTER THAN RAW, at least as good as per-sample.** "
                     "Correction helps overall.")
        recommendation = (
            "Ship as an opt-in overlay. Do not replace raw demand. A follow-up "
            "ticket should tighten the confidence gate and re-measure."
        )
    elif judgment == 'NEUTRAL':
        lines.append("**Verdict: NEUTRAL.** Confidence-gated correction neither helps "
                     "nor hurts overall cal_bias by a material amount, within ±0.02.")
        recommendation = (
            "Hold. Keep the field in shadow mode. The current bank field isn't "
            "wrong enough to be harmful, but it isn't clearly better than raw "
            "either. A tighter confidence gate or a longer-baseline field (more "
            "sessions) may be required before active promotion is justified."
        )
    else:
        lines.append("**Verdict: HARMFUL OR INCONCLUSIVE.** Either cal_bias moves "
                     "away from 1.0, or RMSE increases materially.")
        recommendation = (
            "Do NOT promote. Keep shadow visualization for operator inspection "
            "only. Investigate the suspicious zones flagged by the plausibility "
            "audit before any further experiments."
        )

    lines.append("")
    lines.append("## 4. Recommendation")
    lines.append("")
    lines.append(recommendation)
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated by `scripts/validate_bank_field_correction_shadow.py`. "
                 f"Confidence gate: {BANK_CONFIDENCE_THRESHOLD}.*")

    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'regime', 'n_samples',
            'cal_raw', 'rmse_raw', 'mae_raw',
            'cal_per_sample', 'rmse_per_sample', 'mae_per_sample', 'per_sample_applied_frac',
            'cal_bank_field', 'rmse_bank_field', 'mae_bank_field',
            'bank_field_applied_frac', 'bank_field_conf_weighted_applied',
        ])
        for name, r in rows.items():
            w.writerow([
                name, r.n,
                r.raw_cal, r.raw_rmse, r.raw_mae,
                r.ps_cal, r.ps_rmse, r.ps_mae, r.ps_applied_frac,
                r.bf_cal, r.bf_rmse, r.bf_mae,
                r.bf_applied_frac, r.bf_conf_weighted_applied,
            ])

    # Console summary
    print()
    print('=' * 72)
    print('Shadow correction experiment — all_valid summary')
    print('=' * 72)
    print(f'  cal_bias:   raw {r_all.raw_cal:.3f}  ->  per_sample {r_all.ps_cal:.3f}  '
          f'->  bank_field {r_all.bf_cal:.3f}   (target 1.0)')
    print(f'  rmse (G):   raw {r_all.raw_rmse:.3f}  ->  per_sample {r_all.ps_rmse:.3f}  '
          f'->  bank_field {r_all.bf_rmse:.3f}')
    print(f'  bf applied: {r_all.bf_applied_frac*100:.1f}%  '
          f'(conf-weighted {r_all.bf_conf_weighted_applied*100:.1f}%)')
    print(f'  judgment:   {judgment}')
    print()
    print('Per-regime winners:')
    for name, r in rows.items():
        err_raw = abs(r.raw_cal - 1.0)
        err_ps = abs(r.ps_cal - 1.0)
        err_bf = abs(r.bf_cal - 1.0)
        best = min(err_raw, err_ps, err_bf)
        winner = ('bank_field' if err_bf == best
                  else 'per_sample' if err_ps == best else 'raw')
        print(f'  {name:22s}  raw {err_raw:.3f}  ps {err_ps:.3f}  bf {err_bf:.3f}  -> {winner}')
    print()
    print(f'Report: {out_md}')
    print(f'CSV:    {out_csv}')


if __name__ == '__main__':
    main()
