"""
evaluate_bank_corrected_opt_in_candidate.py
-------------------------------------------
Promotion-gate evaluator for the bank-corrected lateral shadow channel.

This script answers one question honestly:
    "Is the bank-corrected lateral shadow channel good enough to deserve
     opt-in status in a future PR?"

It does this by:
  • Sweeping (confidence_threshold × correction_scale) combinations.
  • Computing per-regime cal_bias, RMSE, signed bias, applied fractions.
  • Counting improvements / regressions against raw at the bin level.
  • Cross-referencing against the prior bank-field plausibility audit.
  • Running a rubric that heavily penalises regressions on straights,
    broad harm in high-confidence zones, threshold sensitivity, and
    gains concentrated in already-noisy regions.

No production changes. Bronze and Silver are not touched. This is
evaluation + compare infrastructure only.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import Iterable

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

# Sweep axes
_CONF_THRESHOLDS = (0.50, 0.60, 0.70, 0.80)
_SCALES = (1.0, 0.75, 0.50)
_BASELINE_COMBO = (0.60, 1.0)          # what shadow currently ships with


# ── Rubric thresholds (explicit, documented) ─────────────────────
#
# All thresholds are in cal_bias units (unitless ratio) or G (RMSE)
# unless noted. They are chosen so a "neutral" correction ends up in
# SHADOW_ONLY and only clear wins reach OPT_IN_CANDIDATE.

# Hard stops → NOT_CANDIDATE if ANY fire
RUB_STRAIGHTS_REGRESSION_HARD_CAP = 0.15   # cal_cor worsens straights by ≥ 15pp
RUB_GLOBAL_RMSE_HARD_CAP_G        = 0.03   # corrected rmse ≥ raw rmse + 0.03 G
RUB_BROAD_HARM_FRACTION           = 0.55   # > 55% of bins see residual worsen by > 0.05 G

# Soft thresholds → gate opt-in candidacy
RUB_GLOBAL_CAL_IMPROVEMENT        = 0.02   # |cal_cor - 1| ≤ |cal_raw - 1| - 0.02
RUB_REGIME_WIN_COUNT_OPT_IN       = 4      # out of 6 regimes
RUB_REGIME_REGRESSION_CAP         = 0.05   # worst regime: cal_cor worsens by ≤ 5pp
RUB_STABILITY_WINDOW              = 0.03   # best combo's global-cal advantage within 3pp across thresholds

# Strong candidate thresholds (above base opt-in)
RUB_STRONG_GLOBAL_CAL_IMPROVEMENT = 0.05
RUB_STRONG_REGIME_WIN_COUNT       = 5
RUB_STRONG_SPATIAL_CONCENTRATION  = 0.50   # ≥ 50% of improvements in plausible zones


REGIMES = (
    'all_valid', 'straight', 'left_corner', 'right_corner',
    'braking', 'accelerating', 'steady_mid_corner',
)


# ─────────────────────────────────────────────────────────────────
# Data loading helpers
# ─────────────────────────────────────────────────────────────────


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


def _load_plausibility() -> dict | None:
    """Load the per-bin plausibility CSV produced by
    audit_bank_field_plausibility.py. Returns a dict keyed by s_m with
    flags, or None if missing."""
    p = os.path.join(_REPO_ROOT, 'docs', 'validation',
                     'bank_field_plausibility_metrics.csv')
    if not os.path.isfile(p):
        return None
    rows = {}
    with open(p, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                s = float(row['s_m'])
            except (KeyError, ValueError):
                continue
            rows[s] = row
    return rows


def _classify_s_bin(s: float, bank: float, std: float, conf: float,
                    plaus: dict | None) -> str:
    """Return 'plausible', 'suspicious', or 'neither' for a given s-bin.

    Uses the plausibility CSV if available; otherwise derives from the
    bank-field values directly.
    """
    # Try CSV first (it was built with the audit's heuristics)
    if plaus:
        # Find the nearest s in the CSV.
        nearest_s = min(plaus.keys(), key=lambda k: abs(k - s))
        if abs(nearest_s - s) <= 10.0:
            row = plaus[nearest_s]
            suspicious = any(int(row.get(k, 0)) for k in (
                'flag_conf_spread', 'flag_gradient', 'flag_banked_straight',
            ))
            if suspicious:
                return 'suspicious'
            # Plausible if: confident, tight, not trivially small
            if (float(row.get('bank_confidence', 0)) >= 0.60
                    and float(row.get('bank_std_deg', 99)) <= 2.0
                    and abs(float(row.get('bank_mean_deg', 0))) >= 1.0):
                return 'plausible'
            return 'neither'

    # Fall back to on-the-fly classification
    if conf >= 0.60 and std <= 2.0 and abs(bank) >= 1.0:
        return 'plausible'
    return 'neither'


# ─────────────────────────────────────────────────────────────────
# Correction + metrics
# ─────────────────────────────────────────────────────────────────


def _cal_bias(a: np.ndarray, cp: np.ndarray) -> float:
    a_abs = np.abs(a)
    cp_abs = np.abs(cp)
    m = cp_abs > 0.05
    if not m.any():
        return float('nan')
    return float(np.median(a_abs[m] / cp_abs[m]))


def _rmse(a: np.ndarray, cp: np.ndarray) -> float:
    if len(a) == 0:
        return float('nan')
    return float(np.sqrt(np.mean((np.abs(a) - np.abs(cp)) ** 2)))


@dataclass
class RegimeMetrics:
    n: int
    cal_raw: float
    cal_cor: float
    rmse_raw: float
    rmse_cor: float
    bias_raw: float
    bias_cor: float
    applied_frac: float
    conf_weighted_applied: float


def _regime(a_raw, a_cor, cp, mask, applied, bank_conf) -> RegimeMetrics:
    n = int(mask.sum())
    if n == 0:
        nan = float('nan')
        return RegimeMetrics(0, nan, nan, nan, nan, nan, nan, nan, nan)
    ar = a_raw[mask]
    ac = a_cor[mask]
    cm = cp[mask]
    am = applied[mask]
    bc = bank_conf[mask]
    cw = float(np.sum(bc * am) / max(n, 1))
    return RegimeMetrics(
        n=n,
        cal_raw=_cal_bias(ar, cm),
        cal_cor=_cal_bias(ac, cm),
        rmse_raw=_rmse(ar, cm),
        rmse_cor=_rmse(ac, cm),
        bias_raw=float(np.mean(np.abs(ar) - np.abs(cm))),
        bias_cor=float(np.mean(np.abs(ac) - np.abs(cm))),
        applied_frac=float(am.mean()),
        conf_weighted_applied=cw,
    )


@dataclass
class ComboResult:
    threshold: float
    scale: float
    regime_metrics: dict[str, RegimeMetrics]
    bin_improved_frac: float
    bin_worsened_frac: float
    broad_harm_frac: float                # fraction of bins with residual worsen > 0.05 G
    max_regime_regression: float          # max of (|cal_cor-1| - |cal_raw-1|) across regimes
    max_regression_regime: str
    improvements_in_plausible_frac: float
    regressions_in_suspicious_frac: float


def _evaluate_combo(
    bundles, frenet, field, threshold, scale, plausibility,
) -> ComboResult:
    s_bins = np.asarray(field['s_bins'], dtype=float)
    bank = np.asarray(field['bank_mean_deg'], dtype=float)
    std = np.asarray(field['bank_std_deg'], dtype=float)
    conf = np.asarray(field['bank_confidence'], dtype=float)
    total_length = s_bins[-1] - s_bins[0] + (s_bins[1] - s_bins[0])

    raw_parts, cor_parts, cp_parts, applied_parts, conf_parts = [], [], [], [], []
    mparts = {k: [] for k in REGIMES}

    for bundle, mount in bundles:
        curv = _curvature_from_xy(bundle.x, bundle.y, bundle.speed)
        cp = bundle.speed ** 2 * curv / _G
        dt = float(np.median(np.diff(bundle.t))) if len(bundle.t) > 1 else 0.04
        dvdt = np.gradient(bundle.speed) / dt / _G
        alat_raw = bundle.alat_g_calc.copy()

        s_arr, _ = frenet.xy_to_sn(bundle.x, bundle.y)
        s_arr = np.mod(s_arr, total_length) if total_length > 0 else s_arr
        bank_at_sample = np.interp(s_arr, s_bins, bank)
        conf_at_sample = np.interp(s_arr, s_bins, conf)

        apply_mask = conf_at_sample >= threshold
        if bool(getattr(mount, 'mount_unstable', False)):
            apply_mask &= False

        correction = scale * np.sin(np.deg2rad(bank_at_sample))
        alat_cor = alat_raw.copy()
        alat_cor[apply_mask] = alat_raw[apply_mask] - correction[apply_mask]

        v_ok = bundle.speed > 5.0
        k_abs = np.abs(curv)
        mparts['all_valid'].append(v_ok)
        mparts['straight'].append((k_abs < _STRAIGHT_KAPPA) & v_ok)
        mparts['left_corner'].append((curv > _CORNER_KAPPA) & v_ok)
        mparts['right_corner'].append((curv < -_CORNER_KAPPA) & v_ok)
        mparts['braking'].append((dvdt < _HARD_BRAKE_G) & v_ok)
        mparts['accelerating'].append((dvdt > _HARD_ACCEL_G) & v_ok)
        mparts['steady_mid_corner'].append(
            (k_abs > _CORNER_KAPPA) & (np.abs(dvdt) < 0.1) & v_ok
        )

        raw_parts.append(alat_raw)
        cor_parts.append(alat_cor)
        cp_parts.append(cp)
        applied_parts.append(apply_mask)
        conf_parts.append(conf_at_sample)

    raw = np.concatenate(raw_parts)
    cor = np.concatenate(cor_parts)
    cp = np.concatenate(cp_parts)
    applied = np.concatenate(applied_parts)
    cfs = np.concatenate(conf_parts)

    metrics = {}
    for name, lst in mparts.items():
        mask = np.concatenate(lst)
        metrics[name] = _regime(raw, cor, cp, mask, applied, cfs)

    # Bin-level improvement / worsening vs v²κ/g
    resid_raw = np.abs(np.abs(raw) - np.abs(cp))
    resid_cor = np.abs(np.abs(cor) - np.abs(cp))
    improvements = resid_cor < resid_raw - 1e-6
    regressions = resid_cor > resid_raw + 1e-6
    broad_harm = (resid_cor - resid_raw) > 0.05

    # Spatial concentration: which s-bins see net improvements / regressions?
    # We bucket per-sample by nearest s-bin in the field.
    n_bin = len(s_bins)
    # Average residual delta per s-bin
    bin_idx = np.clip(np.searchsorted(s_bins, np.concatenate([
        np.mod(*_xy_to_s_lengths(bundle, frenet, total_length))
        for bundle, _ in bundles
    ])), 0, n_bin - 1)
    delta_per_sample = resid_cor - resid_raw
    bin_sum = np.zeros(n_bin)
    bin_count = np.zeros(n_bin)
    for b, d in zip(bin_idx, delta_per_sample):
        bin_sum[b] += d
        bin_count[b] += 1
    bin_mean_delta = np.zeros(n_bin)
    nz = bin_count > 0
    bin_mean_delta[nz] = bin_sum[nz] / bin_count[nz]

    # Classify each s-bin once as plausible/suspicious/neither
    bin_class = np.array([
        _classify_s_bin(float(s_bins[i]), float(bank[i]), float(std[i]),
                        float(conf[i]), plausibility)
        for i in range(n_bin)
    ], dtype=object)

    improved_bins = bin_mean_delta < -1e-3
    worsened_bins = bin_mean_delta > +1e-3
    improvements_plausible = (
        improved_bins & (bin_class == 'plausible')
    ).sum()
    improvements_total = int(improved_bins.sum())
    regressions_suspicious = (
        worsened_bins & (bin_class == 'suspicious')
    ).sum()
    regressions_total = int(worsened_bins.sum())

    improvements_in_plausible_frac = (
        improvements_plausible / improvements_total
        if improvements_total > 0 else 0.0
    )
    regressions_in_suspicious_frac = (
        regressions_suspicious / regressions_total
        if regressions_total > 0 else 0.0
    )

    # Max regression by regime (in cal_bias distance-to-1 terms)
    max_regression = float('-inf')
    max_regression_regime = 'n/a'
    for name in REGIMES:
        m = metrics[name]
        if np.isnan(m.cal_raw) or np.isnan(m.cal_cor):
            continue
        err_raw = abs(m.cal_raw - 1.0)
        err_cor = abs(m.cal_cor - 1.0)
        delta = err_cor - err_raw
        if delta > max_regression:
            max_regression = delta
            max_regression_regime = name
    if max_regression == float('-inf'):
        max_regression = 0.0

    return ComboResult(
        threshold=threshold,
        scale=scale,
        regime_metrics=metrics,
        bin_improved_frac=float(improvements.mean()),
        bin_worsened_frac=float(regressions.mean()),
        broad_harm_frac=float(broad_harm.mean()),
        max_regime_regression=max_regression,
        max_regression_regime=max_regression_regime,
        improvements_in_plausible_frac=improvements_in_plausible_frac,
        regressions_in_suspicious_frac=regressions_in_suspicious_frac,
    )


def _xy_to_s_lengths(bundle, frenet, total_length):
    """Helper to avoid re-computing s_arr twice per combo."""
    s_arr, _ = frenet.xy_to_sn(bundle.x, bundle.y)
    if total_length > 0:
        s_arr = np.mod(s_arr, total_length)
    return s_arr, total_length


# ─────────────────────────────────────────────────────────────────
# Rubric
# ─────────────────────────────────────────────────────────────────


@dataclass
class RubricVerdict:
    decision: str              # NOT_CANDIDATE / SHADOW_ONLY / OPT_IN_CANDIDATE / STRONG_OPT_IN_CANDIDATE
    hard_stops_triggered: list[str]
    opt_in_criteria_passed: list[str]
    opt_in_criteria_failed: list[str]
    strong_criteria_passed: list[str]
    strong_criteria_failed: list[str]
    notes: list[str]


def classify(combo: ComboResult, sweep: dict[tuple, ComboResult]) -> RubricVerdict:
    """Run the full rubric over one ComboResult, using ``sweep`` for stability."""
    v = RubricVerdict('', [], [], [], [], [], [])
    all_ = combo.regime_metrics['all_valid']
    straight = combo.regime_metrics['straight']

    # ── Hard stops ──
    if not np.isnan(straight.cal_raw) and not np.isnan(straight.cal_cor):
        straight_regression = abs(straight.cal_cor - 1.0) - abs(straight.cal_raw - 1.0)
        if straight_regression > RUB_STRAIGHTS_REGRESSION_HARD_CAP:
            v.hard_stops_triggered.append(
                f'straights regressed by {straight_regression:.3f} '
                f'(cap {RUB_STRAIGHTS_REGRESSION_HARD_CAP})'
            )
    if not np.isnan(all_.rmse_raw) and not np.isnan(all_.rmse_cor):
        if (all_.rmse_cor - all_.rmse_raw) > RUB_GLOBAL_RMSE_HARD_CAP_G:
            v.hard_stops_triggered.append(
                f'global RMSE regressed by {all_.rmse_cor - all_.rmse_raw:+.3f} G '
                f'(cap +{RUB_GLOBAL_RMSE_HARD_CAP_G} G)'
            )
    if combo.broad_harm_frac > RUB_BROAD_HARM_FRACTION:
        v.hard_stops_triggered.append(
            f'broad harm: {combo.broad_harm_frac*100:.1f}% of bins worsen by > 0.05 G '
            f'(cap {RUB_BROAD_HARM_FRACTION*100:.0f}%)'
        )

    # ── Opt-in criteria ──
    # 1. Global cal_bias improvement
    err_raw = abs(all_.cal_raw - 1.0)
    err_cor = abs(all_.cal_cor - 1.0)
    global_improvement = err_raw - err_cor
    if global_improvement >= RUB_GLOBAL_CAL_IMPROVEMENT:
        v.opt_in_criteria_passed.append(
            f'global |cal−1| improved by {global_improvement:.3f} '
            f'(bar {RUB_GLOBAL_CAL_IMPROVEMENT})'
        )
    else:
        v.opt_in_criteria_failed.append(
            f'global |cal−1| improved by {global_improvement:.3f} < {RUB_GLOBAL_CAL_IMPROVEMENT}'
        )
    # 2. Regime win count
    winning_regimes = 0
    all_regimes = [n for n in REGIMES if n != 'all_valid']
    for name in all_regimes:
        m = combo.regime_metrics[name]
        if np.isnan(m.cal_raw) or np.isnan(m.cal_cor):
            continue
        if abs(m.cal_cor - 1.0) < abs(m.cal_raw - 1.0):
            winning_regimes += 1
    if winning_regimes >= RUB_REGIME_WIN_COUNT_OPT_IN:
        v.opt_in_criteria_passed.append(
            f'regimes won: {winning_regimes}/{len(all_regimes)} (bar {RUB_REGIME_WIN_COUNT_OPT_IN})'
        )
    else:
        v.opt_in_criteria_failed.append(
            f'regimes won: {winning_regimes}/{len(all_regimes)} < {RUB_REGIME_WIN_COUNT_OPT_IN}'
        )
    # 3. No catastrophic regime regression
    if combo.max_regime_regression <= RUB_REGIME_REGRESSION_CAP:
        v.opt_in_criteria_passed.append(
            f'max regime regression: {combo.max_regime_regression:+.3f} '
            f'({combo.max_regression_regime}) ≤ {RUB_REGIME_REGRESSION_CAP}'
        )
    else:
        v.opt_in_criteria_failed.append(
            f'max regime regression {combo.max_regime_regression:+.3f} in '
            f'{combo.max_regression_regime} exceeds cap {RUB_REGIME_REGRESSION_CAP}'
        )
    # 4. Stability across thresholds (scale held fixed at combo.scale)
    per_thresh_global_err_cor = []
    for (th, sc), cr in sweep.items():
        if sc != combo.scale:
            continue
        ac = cr.regime_metrics['all_valid']
        if not np.isnan(ac.cal_cor):
            per_thresh_global_err_cor.append(abs(ac.cal_cor - 1.0))
    if per_thresh_global_err_cor:
        spread = max(per_thresh_global_err_cor) - min(per_thresh_global_err_cor)
        if spread <= RUB_STABILITY_WINDOW:
            v.opt_in_criteria_passed.append(
                f'stability across thresholds: spread {spread:.3f} ≤ {RUB_STABILITY_WINDOW}'
            )
        else:
            v.opt_in_criteria_failed.append(
                f'stability across thresholds: spread {spread:.3f} > {RUB_STABILITY_WINDOW}'
            )

    # ── Strong criteria ──
    if global_improvement >= RUB_STRONG_GLOBAL_CAL_IMPROVEMENT:
        v.strong_criteria_passed.append(
            f'global |cal−1| improved by {global_improvement:.3f} ≥ {RUB_STRONG_GLOBAL_CAL_IMPROVEMENT}'
        )
    else:
        v.strong_criteria_failed.append(
            f'global improvement {global_improvement:.3f} < {RUB_STRONG_GLOBAL_CAL_IMPROVEMENT}'
        )
    if winning_regimes >= RUB_STRONG_REGIME_WIN_COUNT:
        v.strong_criteria_passed.append(
            f'regimes won: {winning_regimes}/{len(all_regimes)} ≥ {RUB_STRONG_REGIME_WIN_COUNT}'
        )
    else:
        v.strong_criteria_failed.append(
            f'regimes won: {winning_regimes}/{len(all_regimes)} < {RUB_STRONG_REGIME_WIN_COUNT}'
        )
    if combo.improvements_in_plausible_frac >= RUB_STRONG_SPATIAL_CONCENTRATION:
        v.strong_criteria_passed.append(
            f'improvements in plausible zones: {combo.improvements_in_plausible_frac*100:.1f}% '
            f'≥ {RUB_STRONG_SPATIAL_CONCENTRATION*100:.0f}%'
        )
    else:
        v.strong_criteria_failed.append(
            f'improvements in plausible zones: {combo.improvements_in_plausible_frac*100:.1f}% '
            f'< {RUB_STRONG_SPATIAL_CONCENTRATION*100:.0f}%'
        )

    # ── Final classification ──
    if v.hard_stops_triggered:
        v.decision = 'NOT_CANDIDATE'
    elif not v.opt_in_criteria_failed:
        # All opt-in criteria passed
        if not v.strong_criteria_failed:
            v.decision = 'STRONG_OPT_IN_CANDIDATE'
        else:
            v.decision = 'OPT_IN_CANDIDATE'
    else:
        v.decision = 'SHADOW_ONLY'

    return v


def pick_best_combo(sweep: dict[tuple, ComboResult]) -> tuple:
    """Best = minimize |cal_all - 1.0|, break ties by lower global RMSE."""
    best = None
    best_score = None
    for key, cr in sweep.items():
        ac = cr.regime_metrics['all_valid']
        if np.isnan(ac.cal_cor):
            continue
        # Penalty for straights regression so we don't pick a combo that
        # wins globally by sacrificing straights.
        st = cr.regime_metrics['straight']
        straight_pen = max(0.0, abs(st.cal_cor - 1.0) - abs(st.cal_raw - 1.0))
        score = abs(ac.cal_cor - 1.0) + 2.0 * straight_pen + ac.rmse_cor * 0.1
        if best_score is None or score < best_score:
            best = key
            best_score = score
    return best


# ─────────────────────────────────────────────────────────────────
# Report writer
# ─────────────────────────────────────────────────────────────────


def _fmt(x, nd=3):
    return f'{x:.{nd}f}' if not np.isnan(x) else 'n/a'


def write_report(
    sweep: dict[tuple, ComboResult],
    best_key: tuple,
    baseline_key: tuple,
    baseline_verdict: RubricVerdict,
    best_verdict: RubricVerdict,
    out_md: str,
    out_csv: str,
) -> None:
    lines = []
    lines.append('# Bank-Corrected Lateral Shadow — Opt-in Promotion Gate')
    lines.append('')
    lines.append('**Question.** Is the bank-corrected lateral shadow channel good '
                 'enough to deserve opt-in status in a future PR?')
    lines.append('')
    lines.append('**Scope.** This ticket is evaluation infrastructure only. Bronze '
                 'and Silver canonical outputs are untouched. No promotion happens '
                 'in this ticket.')
    lines.append('')
    lines.append(f'**Executive verdict (best combo = threshold {best_key[0]}, '
                 f'scale {best_key[1]}):**')
    lines.append('')
    lines.append(f'> **{best_verdict.decision}**')
    lines.append('')
    ac = sweep[best_key].regime_metrics['all_valid']
    ar = sweep[baseline_key].regime_metrics['all_valid']
    lines.append(
        f'Best combo moves global cal_bias from {_fmt(ar.cal_raw)} (raw) to '
        f'{_fmt(ac.cal_cor)} (corrected), a {_fmt(abs(ar.cal_raw - 1.0) - abs(ac.cal_cor - 1.0))} '
        f'move toward 1.0. RMSE {_fmt(ar.rmse_raw)} → {_fmt(ac.rmse_cor)} G. '
        f'Applied on {ac.applied_frac*100:.1f}% of samples '
        f'(conf-weighted {ac.conf_weighted_applied*100:.1f}%).'
    )
    lines.append('')

    # Rubric
    lines.append('## 1. Rubric (documented thresholds)')
    lines.append('')
    lines.append('Hard stops (any → NOT_CANDIDATE):')
    lines.append(f'- straight-regime regression > {RUB_STRAIGHTS_REGRESSION_HARD_CAP} cal_bias units')
    lines.append(f'- global RMSE increase > {RUB_GLOBAL_RMSE_HARD_CAP_G} G')
    lines.append(f'- broad harm: > {RUB_BROAD_HARM_FRACTION*100:.0f}% of bins worsen by > 0.05 G')
    lines.append('')
    lines.append('Opt-in requirements (all four must pass):')
    lines.append(f'- global |cal−1| improvement ≥ {RUB_GLOBAL_CAL_IMPROVEMENT}')
    lines.append(f'- regime wins ≥ {RUB_REGIME_WIN_COUNT_OPT_IN}/6')
    lines.append(f'- worst-regime regression ≤ {RUB_REGIME_REGRESSION_CAP}')
    lines.append(f'- threshold stability: cal spread across {len(_CONF_THRESHOLDS)} thresholds ≤ {RUB_STABILITY_WINDOW}')
    lines.append('')
    lines.append('Strong-candidate requirements (opt-in + all three):')
    lines.append(f'- global improvement ≥ {RUB_STRONG_GLOBAL_CAL_IMPROVEMENT}')
    lines.append(f'- regime wins ≥ {RUB_STRONG_REGIME_WIN_COUNT}/6')
    lines.append(f'- ≥ {RUB_STRONG_SPATIAL_CONCENTRATION*100:.0f}% of improvements in plausible zones')
    lines.append('')

    # Threshold sweep
    lines.append('## 2. Threshold × scale sweep')
    lines.append('')
    lines.append('| threshold | scale | cal_cor (all) | rmse_cor | applied | bins better | bins worse | broad harm | max reg. regime |')
    lines.append('|---|---|---|---|---|---|---|---|---|')
    for (th, sc), cr in sorted(sweep.items()):
        ac = cr.regime_metrics['all_valid']
        lines.append(
            f'| {th:.2f} | {sc:.2f} | {_fmt(ac.cal_cor)} | {_fmt(ac.rmse_cor)} | '
            f'{ac.applied_frac*100:.1f}% | {cr.bin_improved_frac*100:.1f}% | '
            f'{cr.bin_worsened_frac*100:.1f}% | {cr.broad_harm_frac*100:.1f}% | '
            f'{cr.max_regression_regime} ({cr.max_regime_regression:+.3f}) |'
        )
    lines.append('')

    # Regime winner table
    lines.append('## 3. Regime winner table (best combo)')
    lines.append('')
    best_cr = sweep[best_key]
    lines.append('| regime | n | cal_raw | cal_cor | winner | Δ|cal−1| |')
    lines.append('|---|---|---|---|---|---|')
    for name in REGIMES:
        m = best_cr.regime_metrics[name]
        err_raw = abs(m.cal_raw - 1.0) if not np.isnan(m.cal_raw) else float('nan')
        err_cor = abs(m.cal_cor - 1.0) if not np.isnan(m.cal_cor) else float('nan')
        if np.isnan(err_raw) or np.isnan(err_cor):
            winner = 'n/a'
            delta_str = 'n/a'
        else:
            winner = 'corrected' if err_cor < err_raw else 'raw' if err_cor > err_raw else 'tie'
            delta_str = f'{err_cor - err_raw:+.3f}'
        lines.append(
            f'| {name} | {m.n} | {_fmt(m.cal_raw)} | {_fmt(m.cal_cor)} | **{winner}** | {delta_str} |'
        )
    lines.append('')

    # Harm table
    lines.append('## 4. Harm analysis (best combo)')
    lines.append('')
    lines.append('| metric | value |')
    lines.append('|---|---|')
    lines.append(f'| bins improved (residual to v²κ/g) | {best_cr.bin_improved_frac*100:.1f}% |')
    lines.append(f'| bins worsened | {best_cr.bin_worsened_frac*100:.1f}% |')
    lines.append(f'| broad harm (worsen by > 0.05 G) | {best_cr.broad_harm_frac*100:.1f}% |')
    lines.append(f'| max regime regression | {best_cr.max_regime_regression:+.3f} ({best_cr.max_regression_regime}) |')
    lines.append(f'| improvements in plausible zones | {best_cr.improvements_in_plausible_frac*100:.1f}% |')
    lines.append(f'| regressions in suspicious zones | {best_cr.regressions_in_suspicious_frac*100:.1f}% |')
    lines.append('')

    # Verdicts
    lines.append('## 5. Rubric outcome (best combo)')
    lines.append('')
    if best_verdict.hard_stops_triggered:
        lines.append('**Hard stops triggered:**')
        for h in best_verdict.hard_stops_triggered:
            lines.append(f'- {h}')
        lines.append('')
    lines.append(f'**Opt-in criteria passed ({len(best_verdict.opt_in_criteria_passed)}):**')
    for c in best_verdict.opt_in_criteria_passed:
        lines.append(f'- {c}')
    lines.append('')
    lines.append(f'**Opt-in criteria failed ({len(best_verdict.opt_in_criteria_failed)}):**')
    for c in best_verdict.opt_in_criteria_failed:
        lines.append(f'- {c}')
    lines.append('')
    lines.append(f'**Strong-candidate criteria passed ({len(best_verdict.strong_criteria_passed)}):**')
    for c in best_verdict.strong_criteria_passed:
        lines.append(f'- {c}')
    lines.append('')
    lines.append(f'**Strong-candidate criteria failed ({len(best_verdict.strong_criteria_failed)}):**')
    for c in best_verdict.strong_criteria_failed:
        lines.append(f'- {c}')
    lines.append('')
    lines.append(f'**Decision class: `{best_verdict.decision}`**')
    lines.append('')

    # Recommendation
    lines.append('## 6. Recommendation for future action')
    lines.append('')
    if best_verdict.decision == 'NOT_CANDIDATE':
        lines.append('**Do not promote. Remain shadow-only.** One or more hard stops '
                     'were triggered; the correction is actively harmful under the '
                     'current configuration. Investigate root causes before any '
                     'further evaluation.')
    elif best_verdict.decision == 'SHADOW_ONLY':
        lines.append('**Remain shadow-only for now.** The correction does not meet '
                     'the opt-in bar; it is not demonstrably harmful but neither is '
                     'it demonstrably better. A future ticket could re-evaluate with '
                     '(a) more sessions for a tighter bank field or (b) a narrower '
                     'scope such as "corners only".')
    elif best_verdict.decision == 'OPT_IN_CANDIDATE':
        lines.append(f'**Promote to opt-in (non-canonical) in a future PR.** The '
                     f'correction meets opt-in criteria at threshold '
                     f'{best_key[0]}, scale {best_key[1]}. Label: '
                     f'`lat_demand_bank_corrected_beta`. Keep Bronze canonical; '
                     f'the opt-in mode is a viewer/user choice only. Require one '
                     f'more safety gate (engineer sign-off on a visual inspection) '
                     f'before merging.')
    else:  # STRONG_OPT_IN_CANDIDATE
        lines.append(f'**Strong candidate for opt-in promotion.** At threshold '
                     f'{best_key[0]}, scale {best_key[1]}, the correction wins on '
                     f'most regimes, has broad spatial support, and is stable '
                     f'across threshold sweeps. Label: '
                     f'`lat_demand_bank_corrected_opt_in`. Still keep Bronze '
                     f'canonical.')
    lines.append('')

    lines.append(f'**Best threshold/scale pair:** `({best_key[0]}, {best_key[1]})`')
    lines.append('')
    lines.append('---')
    lines.append(f'*Generated by `scripts/evaluate_bank_corrected_opt_in_candidate.py`. '
                 f'Baseline combo (current shadow): {baseline_key}.*')

    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # CSV — flat per-(threshold, scale, regime) row
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'threshold', 'scale', 'regime', 'n',
            'cal_raw', 'cal_cor', 'rmse_raw', 'rmse_cor',
            'bias_raw', 'bias_cor', 'applied_frac', 'conf_weighted_applied',
            'bin_improved_frac', 'bin_worsened_frac', 'broad_harm_frac',
            'max_regime_regression', 'max_regression_regime',
            'improvements_in_plausible_frac', 'regressions_in_suspicious_frac',
            'decision_at_combo', 'is_best_combo',
        ])
        for (th, sc), cr in sorted(sweep.items()):
            verdict = classify(cr, sweep)
            is_best = (th, sc) == best_key
            for name, m in cr.regime_metrics.items():
                w.writerow([
                    th, sc, name, m.n,
                    m.cal_raw, m.cal_cor, m.rmse_raw, m.rmse_cor,
                    m.bias_raw, m.bias_cor, m.applied_frac, m.conf_weighted_applied,
                    cr.bin_improved_frac, cr.bin_worsened_frac, cr.broad_harm_frac,
                    cr.max_regime_regression, cr.max_regression_regime,
                    cr.improvements_in_plausible_frac, cr.regressions_in_suspicious_frac,
                    verdict.decision, is_best,
                ])


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────


def main():
    field = _load_field_from_json()
    if field is None:
        print('Bank field not available — run build_ok_raw.py first.')
        return

    plausibility = _load_plausibility()
    if plausibility is None:
        print('Plausibility CSV not found — spatial linkage will use on-the-fly classification.')

    # Load real data
    print('Loading sessions…')
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
    print(f'  {len(all_bundles)} bundles, centerline length '
          f'{frenet.total_length_m:.0f} m')

    # Sweep
    print('Running threshold × scale sweep…')
    sweep: dict[tuple, ComboResult] = {}
    for th in _CONF_THRESHOLDS:
        for sc in _SCALES:
            print(f'  threshold={th:.2f}, scale={sc:.2f} …')
            sweep[(th, sc)] = _evaluate_combo(
                all_bundles, frenet, field, th, sc, plausibility,
            )

    best_key = pick_best_combo(sweep)
    best_verdict = classify(sweep[best_key], sweep)
    baseline_verdict = classify(sweep[_BASELINE_COMBO], sweep)

    out_md = os.path.join(_REPO_ROOT, 'docs', 'validation',
                          'bank_corrected_opt_in_candidate_report.md')
    out_csv = os.path.join(_REPO_ROOT, 'docs', 'validation',
                           'bank_corrected_opt_in_candidate_metrics.csv')
    write_report(sweep, best_key, _BASELINE_COMBO, baseline_verdict, best_verdict,
                 out_md, out_csv)

    # Console summary
    print()
    print('=' * 72)
    print('Bank-Corrected Opt-in Promotion Gate')
    print('=' * 72)
    print(f'  Best (threshold, scale): {best_key}')
    print(f'  Decision class:          {best_verdict.decision}')
    ac = sweep[best_key].regime_metrics['all_valid']
    st = sweep[best_key].regime_metrics['straight']
    print(f'  Best cal_cor (all):      {ac.cal_cor:.3f}')
    print(f'  Best cal_cor (straight): {st.cal_cor:.3f}')
    print(f'  Applied fraction:        {ac.applied_frac*100:.1f}%')
    print(f'  Bins improved:           {sweep[best_key].bin_improved_frac*100:.1f}%')
    print(f'  Bins worsened:           {sweep[best_key].bin_worsened_frac*100:.1f}%')
    print()
    print(f'  Report: {out_md}')
    print(f'  CSV:    {out_csv}')

    # Return values so build_ok_raw.py can consume compact summary.
    return {
        'best_threshold': best_key[0],
        'best_scale': best_key[1],
        'decision_class': best_verdict.decision,
        'global_cal_cor': ac.cal_cor,
        'global_rmse_cor': ac.rmse_cor,
    }


if __name__ == '__main__':
    main()
