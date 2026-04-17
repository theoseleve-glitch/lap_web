"""
audit_bank_field_plausibility.py
--------------------------------
Spatial plausibility audit for the Gold-alpha-shadow bank field.

Reads ``track-surface-ok-data.json``, inspects ``road_attitude_field``,
and answers four questions:

    1. Does the bank field look structurally plausible?
    2. Where is it trustworthy?
    3. Where is it probably noise or underconstrained?
    4. Which s-ranges deserve manual viewer inspection?

Not a certification. Not a ground-truth check. We have no surveyed bank
data for the OK track, so this audit reasons purely about internal
consistency — spatial coherence, confidence/spread agreement, curvature
correlation, zone contiguity.

Output:
    docs/validation/bank_field_plausibility_report.md
    docs/validation/bank_field_plausibility_metrics.csv
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, asdict

import numpy as np


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JSON_PATH = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')
_OUT_MD = os.path.join(_REPO_ROOT, 'docs', 'validation', 'bank_field_plausibility_report.md')
_OUT_CSV = os.path.join(_REPO_ROOT, 'docs', 'validation', 'bank_field_plausibility_metrics.csv')


# ── Thresholds (conservative; used for flagging only, not gating) ──

HIGH_CONFIDENCE_T = 0.60       # "confident" bin
LOW_CONFIDENCE_T = 0.30        # "underconstrained" bin
TIGHT_STD_DEG = 1.5            # field is tight if MAD-std ≤ this
LOOSE_STD_DEG = 3.0            # field is loose if MAD-std ≥ this
STRONG_BANK_DEG = 3.0          # |bank_mean| above this counts as "structurally present"
SUSPICIOUS_GRADIENT_DEG_PER_M = 0.5   # |dbank/ds| above this at 5 m bins = >2.5° per bin
MIN_ZONE_BINS = 4              # min contiguous bins to form a zone
STRAIGHT_CURV_THRESHOLD = 0.01 # |κ| below this = "straight"
CORNER_CURV_THRESHOLD = 0.05   # |κ| above this = "hard corner"


@dataclass
class ZoneSummary:
    s_start: float
    s_end: float
    length_m: float
    n_bins: int
    bank_mean_deg: float
    bank_std_deg: float    # within-zone spread of bank_mean (not MAD)
    mean_std_deg: float    # mean of per-bin MAD stds
    min_confidence: float
    mean_confidence: float
    mean_lap_coverage: float
    mean_kappa_abs: float  # mean |curvature| in zone (from track.curvature)
    sign: str              # '+' / '-'


def _detect_zones(
    s_bins: np.ndarray,
    bank: np.ndarray,
    conf: np.ndarray,
    std: np.ndarray,
    coverage: np.ndarray,
    kappa_at_s: np.ndarray,
    *, min_bins: int = MIN_ZONE_BINS,
    min_magnitude_deg: float = 0.8,
) -> list[ZoneSummary]:
    """Contiguous runs of same-sign bank with |mean| above a small floor.

    Bins below the magnitude floor or with negligible confidence are
    excluded; adjacent qualifying bins with the same sign form a zone.
    """
    zones: list[ZoneSummary] = []
    n = len(s_bins)
    i = 0
    while i < n:
        # Find the start of a candidate zone.
        if conf[i] < LOW_CONFIDENCE_T or abs(bank[i]) < min_magnitude_deg:
            i += 1
            continue
        sign = 1 if bank[i] > 0 else -1
        j = i
        while (
            j < n
            and conf[j] >= LOW_CONFIDENCE_T
            and abs(bank[j]) >= min_magnitude_deg
            and ((1 if bank[j] > 0 else -1) == sign)
        ):
            j += 1
        n_bins = j - i
        if n_bins >= min_bins:
            sl = slice(i, j)
            zones.append(ZoneSummary(
                s_start=float(s_bins[i]),
                s_end=float(s_bins[j - 1]),
                length_m=float(s_bins[j - 1] - s_bins[i] + (s_bins[1] - s_bins[0] if n > 1 else 0)),
                n_bins=n_bins,
                bank_mean_deg=float(np.mean(bank[sl])),
                bank_std_deg=float(np.std(bank[sl])),
                mean_std_deg=float(np.mean(std[sl])),
                min_confidence=float(np.min(conf[sl])),
                mean_confidence=float(np.mean(conf[sl])),
                mean_lap_coverage=float(np.mean(coverage[sl])),
                mean_kappa_abs=float(np.mean(np.abs(kappa_at_s[sl]))),
                sign='+' if sign > 0 else '-',
            ))
        i = max(j, i + 1)
    return zones


def _format_pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _section(title: str) -> list[str]:
    return [f"## {title}", ""]


def main():
    if not os.path.isfile(_JSON_PATH):
        print(f'{_JSON_PATH} not found — run scripts/build_ok_raw.py first.')
        return

    with open(_JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    raf = data.get('road_attitude_field')
    if raf is None or not raf.get('s_bins'):
        print('road_attitude_field missing or empty — aborting.')
        return

    s_bins = np.asarray(raf['s_bins'], dtype=float)
    bank = np.asarray(raf['bank_mean_deg'], dtype=float)
    std = np.asarray(raf['bank_std_deg'], dtype=float)
    conf = np.asarray(raf['bank_confidence'], dtype=float)
    count = np.asarray(raf['bank_evidence_count'], dtype=int)
    coverage = np.asarray(raf['bank_lap_coverage'], dtype=int)

    # Track curvature, resampled to the field's s-grid.
    track = data.get('track', {})
    curv_track = np.asarray(track.get('curvature', []), dtype=float)
    if len(curv_track) > 0 and track.get('length_m', 0):
        s_track = np.linspace(0, float(track['length_m']), len(curv_track))
        kappa_at_s = np.interp(s_bins, s_track, curv_track)
    else:
        kappa_at_s = np.zeros_like(s_bins)

    # Spatial gradient of bank.
    ds = (s_bins[1] - s_bins[0]) if len(s_bins) > 1 else 1.0
    dbank_ds = np.gradient(bank) / max(ds, 1e-9)

    # ── Coverage stats ──
    n = len(s_bins)
    high_conf = conf >= HIGH_CONFIDENCE_T
    low_conf = conf < LOW_CONFIDENCE_T
    strongly_banked = np.abs(bank) >= STRONG_BANK_DEG
    loose = std >= LOOSE_STD_DEG
    tight = (std <= TIGHT_STD_DEG) & high_conf

    # ── Suspicious: high confidence but loose spread ──
    # If a bin claims high confidence yet its robust std is > LOOSE, that's
    # internally inconsistent and worth flagging for inspection.
    suspicious_conf_spread = high_conf & (std >= LOOSE_STD_DEG)

    # ── Suspicious: high spatial gradient ──
    suspicious_gradient = np.abs(dbank_ds) >= SUSPICIOUS_GRADIENT_DEG_PER_M

    # ── Suspicious: strong bank on a geometric straight ──
    # Straights should have near-zero bank on a kart track. If we see
    # strongly-banked, high-confidence bins on nominal straights, flag.
    on_straight = np.abs(kappa_at_s) < STRAIGHT_CURV_THRESHOLD
    suspicious_banked_straight = high_conf & strongly_banked & on_straight

    # ── Plausible: confident + tight + moderate magnitude + in a corner ──
    in_corner = np.abs(kappa_at_s) >= CORNER_CURV_THRESHOLD
    plausible_corner = high_conf & tight & (np.abs(bank) > 1.0) & in_corner

    # ── Zones ──
    zones = _detect_zones(s_bins, bank, conf, std, coverage, kappa_at_s)
    # Rank plausible zones by confidence × magnitude.
    zones_sorted = sorted(
        zones,
        key=lambda z: (z.mean_confidence * abs(z.bank_mean_deg)),
        reverse=True,
    )

    # ── Write markdown report ──
    lines: list[str] = []
    lines.append("# Bank Field Plausibility Audit")
    lines.append("")
    lines.append("**Scope.** This is an *internal-consistency* audit of the "
                 "`road_attitude_field.bank_*` channel. The OK track has no "
                 "surveyed bank-angle ground truth, so we cannot claim correctness. "
                 "What we can check is whether the estimate *behaves like a road* — "
                 "spatially coherent, confident where evidence is dense, weak where "
                 "it isn't, and correlated with visible track structure (curvature).")
    lines.append("")
    lines.append("**Invariant.** Bronze/silver demand products are not consulted or "
                 "modified here. No correction is applied.")
    lines.append("")

    # Section: global statistics
    lines += _section("1. Global statistics")
    total_len = track.get('length_m', 'unknown')
    diag = raf.get('diagnostics', {})
    lines.append("```")
    lines.append(f"  track length:           {total_len} m")
    lines.append(f"  s-bin width:            {ds:.1f} m, n_bins: {n}")
    lines.append(f"  high confidence bins:   {int(high_conf.sum())} ({_format_pct(high_conf.mean())})")
    lines.append(f"  low confidence bins:    {int(low_conf.sum())} ({_format_pct(low_conf.mean())})")
    lines.append(f"  strongly-banked (|b| ≥ {STRONG_BANK_DEG}°): "
                 f"{int(strongly_banked.sum())} ({_format_pct(strongly_banked.mean())})")
    lines.append(f"  tight & confident bins:  {int(tight.sum())} ({_format_pct(tight.mean())})")
    lines.append(f"  loose bins (std ≥ {LOOSE_STD_DEG}°): "
                 f"{int(loose.sum())} ({_format_pct(loose.mean())})")
    lines.append(f"  mean bank (valid bins):  {diag.get('mean_bank_on_valid_deg', 0):+.2f}°")
    lines.append(f"  median bank std (valid): {diag.get('median_bank_std_on_valid_deg', 0):.2f}°")
    lines.append(f"  mean lap coverage:       {diag.get('mean_lap_coverage_bank', 0):.1f} laps")
    lines.append("```")
    lines.append("")

    # Section: distributions
    lines += _section("2. Distribution summary")
    for name, arr in [
        ("bank_mean_deg", bank),
        ("bank_std_deg", std),
        ("bank_confidence", conf),
        ("bank_evidence_count", count),
        ("bank_lap_coverage", coverage),
        ("|dbank/ds| (°/m)", np.abs(dbank_ds)),
    ]:
        pcts = [np.percentile(arr, q) for q in (5, 25, 50, 75, 95)]
        lines.append(f"- **{name}**: p5={pcts[0]:.3f}  p25={pcts[1]:.3f}  "
                     f"p50={pcts[2]:.3f}  p75={pcts[3]:.3f}  p95={pcts[4]:.3f}")
    lines.append("")

    # Section: curvature correlation
    lines += _section("3. Bank–curvature correlation")
    lines.append("On a flat road with only side-cantering, bank should correlate "
                 "weakly or not at all with centerline curvature. Strong correlation "
                 "would suggest the estimator is still absorbing centripetal into bank.")
    lines.append("")
    # Compute correlation on confident bins only.
    conf_mask = conf >= HIGH_CONFIDENCE_T
    if conf_mask.sum() >= 10:
        r = float(np.corrcoef(bank[conf_mask], kappa_at_s[conf_mask])[0, 1])
        lines.append(f"  Pearson r(bank, κ) on high-confidence bins = **{r:+.3f}**")
        if abs(r) < 0.25:
            lines.append("  → weak correlation: consistent with a field that separated bank from centripetal.")
        elif abs(r) < 0.5:
            lines.append("  → moderate correlation: some residual centripetal coupling may still be present.")
        else:
            lines.append("  → high correlation: **bank still tracks curvature, which is a red flag.**")
    else:
        lines.append("  not enough confident bins for a meaningful correlation.")
    lines.append("")

    # Section: suspicious segments
    lines += _section("4. Suspicious bins (flag for inspection)")
    lines.append("These categories flag internal inconsistency. They are heuristic "
                 "filters — some flagged bins may still be correct.")
    lines.append("")
    lines.append("| category | n_bins | fraction | summary |")
    lines.append("|---|---|---|---|")
    for name, mask in [
        (f"high-conf & loose std (≥{LOOSE_STD_DEG}°)", suspicious_conf_spread),
        (f"|dbank/ds| ≥ {SUSPICIOUS_GRADIENT_DEG_PER_M} °/m", suspicious_gradient),
        ("strongly banked on nominal straight", suspicious_banked_straight),
    ]:
        fr = mask.mean()
        if mask.any():
            b_subset = bank[mask]
            stat = f"mean |bank| = {float(np.mean(np.abs(b_subset))):.2f}°"
        else:
            stat = "—"
        lines.append(f"| {name} | {int(mask.sum())} | {_format_pct(fr)} | {stat} |")
    lines.append("")

    # Top suspicious s-ranges (merge adjacent suspicious bins)
    suspicious_any = (
        suspicious_conf_spread | suspicious_gradient | suspicious_banked_straight
    )
    lines.append("### Top suspicious s-ranges to inspect")
    lines.append("")
    sus_zones = []
    i = 0
    while i < n:
        if not suspicious_any[i]:
            i += 1
            continue
        j = i
        while j < n and suspicious_any[j]:
            j += 1
        sus_zones.append((i, j))
        i = max(j, i + 1)
    sus_zones.sort(
        key=lambda rng: float(np.sum(np.abs(bank[rng[0]:rng[1]])) + np.sum(np.abs(dbank_ds[rng[0]:rng[1]]))),
        reverse=True,
    )
    lines.append("| s_start | s_end | n_bins | mean bank | max \\|dbank/ds\\| | min conf | reason |")
    lines.append("|---|---|---|---|---|---|---|")
    for rng in sus_zones[:10]:
        i0, i1 = rng
        s0, s1 = s_bins[i0], s_bins[i1 - 1]
        b_mean = float(np.mean(bank[i0:i1]))
        g_max = float(np.max(np.abs(dbank_ds[i0:i1])))
        c_min = float(np.min(conf[i0:i1]))
        reasons = []
        if suspicious_conf_spread[i0:i1].any(): reasons.append("conf/spread")
        if suspicious_gradient[i0:i1].any(): reasons.append("gradient")
        if suspicious_banked_straight[i0:i1].any(): reasons.append("bank on straight")
        lines.append(f"| {s0:.0f} | {s1:.0f} | {i1 - i0} | {b_mean:+.2f}° | {g_max:.2f} °/m | "
                     f"{c_min:.2f} | {', '.join(reasons)} |")
    if not sus_zones:
        lines.append("| — | — | — | — | — | — | _none_ |")
    lines.append("")

    # Section: plausible zones
    lines += _section("5. Strongest plausible bank zones")
    lines.append("Contiguous same-sign, confident, consistent zones. These are the "
                 "safest candidates for visual inspection in the Bank Field viewer mode.")
    lines.append("")
    lines.append("| # | s_start | s_end | length | bank mean | mean std | mean conf | lap cov | κ̄ (1/m) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for idx, z in enumerate(zones_sorted[:10], start=1):
        lines.append(
            f"| {idx} | {z.s_start:.0f} | {z.s_end:.0f} | {z.length_m:.0f} m | "
            f"{z.bank_mean_deg:+.2f}° | {z.mean_std_deg:.2f}° | "
            f"{z.mean_confidence:.2f} | {z.mean_lap_coverage:.1f} | {z.mean_kappa_abs:.3f} |"
        )
    if not zones_sorted:
        lines.append("| — | — | — | — | — | — | — | — | — |")
    lines.append("")

    # Section: shortlist for viewer inspection
    lines += _section("6. Shortlist for viewer inspection")
    short: list[str] = []
    for z in zones_sorted[:5]:
        short.append(
            f"- **Plausible**: s ≈ {z.s_start:.0f}–{z.s_end:.0f} m, bank "
            f"{z.bank_mean_deg:+.2f}° (mean std {z.mean_std_deg:.2f}°, "
            f"conf {z.mean_confidence:.2f}) — {z.n_bins} bins of consistent sign"
        )
    for rng in sus_zones[:5]:
        i0, i1 = rng
        s0, s1 = s_bins[i0], s_bins[i1 - 1]
        short.append(
            f"- **Suspicious**: s ≈ {s0:.0f}–{s1:.0f} m, mean bank "
            f"{float(np.mean(bank[i0:i1])):+.2f}°, max |dbank/ds| "
            f"{float(np.max(np.abs(dbank_ds[i0:i1]))):.2f} °/m — worth a sanity pass"
        )
    lines.extend(short)
    lines.append("")

    # Section: verdict
    lines += _section("7. Verdict")
    high_conf_frac = float(high_conf.mean())
    strong_plausible = len(zones_sorted) >= 3 and zones_sorted[0].mean_confidence > 0.6
    mostly_tight = float((std <= LOOSE_STD_DEG).mean())
    gradient_ok = float(suspicious_gradient.mean()) < 0.10
    banked_straight_ok = int(suspicious_banked_straight.sum()) < max(5, 0.03 * n)

    verdict_plausible = (
        high_conf_frac >= 0.50
        and strong_plausible
        and mostly_tight >= 0.70
        and gradient_ok
        and banked_straight_ok
    )

    if verdict_plausible:
        lines.append("**Plausible enough for a shadow correction experiment.**")
        lines.append("")
        lines.append("- Multi-lap evidence is dense (mean coverage near the session lap count).")
        lines.append("- High-confidence fraction is a majority of the track.")
        lines.append("- Spread is mostly tight.")
        lines.append("- Spatial gradients are mostly benign.")
        lines.append("- A small handful of suspicious bins remain; they should be inspected "
                     "manually in the viewer but do not disqualify the field.")
        lines.append("")
        lines.append("**Not a certification.** A shadow-correction experiment (no production "
                     "wiring) is the right next step to measure whether applying this bank "
                     "field moves corrected demand toward GPS centripetal without creating "
                     "per-regime regressions.")
    else:
        lines.append("**Not plausible enough yet.**")
        lines.append("")
        problems = []
        if high_conf_frac < 0.50:
            problems.append(f"- High-confidence coverage is only {_format_pct(high_conf_frac)} — below the 50% bar.")
        if not strong_plausible:
            problems.append("- No strong plausible zones found (need ≥3 confident same-sign zones).")
        if mostly_tight < 0.70:
            problems.append(f"- Only {_format_pct(mostly_tight)} of bins have tight spread (need ≥70%).")
        if not gradient_ok:
            problems.append(f"- {_format_pct(float(suspicious_gradient.mean()))} of bins have steep dbank/ds.")
        if not banked_straight_ok:
            problems.append(f"- {int(suspicious_banked_straight.sum())} confident 'banked straight' bins — too many.")
        lines.extend(problems)
        lines.append("")
        lines.append("Recommend: keep shadow visualization, do not run correction experiment yet.")

    lines.append("")
    lines.append("---")
    lines.append("*Audit generated by `scripts/audit_bank_field_plausibility.py`.*")

    os.makedirs(os.path.dirname(_OUT_MD), exist_ok=True)
    with open(_OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # CSV of per-bin metrics for downstream tooling.
    with open(_OUT_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['s_m', 'bank_mean_deg', 'bank_std_deg', 'bank_confidence',
                    'bank_evidence_count', 'bank_lap_coverage',
                    'dbank_ds_deg_per_m', 'kappa_at_s_1pm',
                    'flag_conf_spread', 'flag_gradient', 'flag_banked_straight'])
        for i in range(n):
            w.writerow([
                float(s_bins[i]), float(bank[i]), float(std[i]), float(conf[i]),
                int(count[i]), int(coverage[i]),
                float(dbank_ds[i]), float(kappa_at_s[i]),
                int(suspicious_conf_spread[i]),
                int(suspicious_gradient[i]),
                int(suspicious_banked_straight[i]),
            ])

    # Console summary
    print()
    print('=' * 70)
    print('Bank Field Plausibility Audit — summary')
    print('=' * 70)
    print(f'  high-conf bins:      {int(high_conf.sum())}/{n}  ({_format_pct(high_conf_frac)})')
    print(f'  tight bins:          {int((std <= TIGHT_STD_DEG).sum())}/{n}')
    print(f'  loose bins:          {int(loose.sum())}/{n}')
    print(f'  strong plausible zones: {len(zones_sorted)} (top {min(3, len(zones_sorted))} confidence '
          f'{" ".join(f"{z.mean_confidence:.2f}" for z in zones_sorted[:3])})')
    print(f'  suspicious bins (any flag): {int(suspicious_any.sum())}/{n}  ({_format_pct(float(suspicious_any.mean()))})')
    print()
    print(f"  Verdict: {'PLAUSIBLE for shadow correction experiment' if verdict_plausible else 'NOT plausible yet'}")
    print()
    print(f'Report: {_OUT_MD}')
    print(f'CSV:    {_OUT_CSV}')


if __name__ == '__main__':
    main()
