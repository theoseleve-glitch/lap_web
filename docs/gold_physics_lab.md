# Gold Physics Lab

> Experimental physics workspace for the telemetry viewer. Sits beside the canonical Bronze and Silver products; never replaces them.

## Why Gold Lab exists

The telemetry pipeline has a clean three-tier architecture:

| Tier | What it is | Status | Source of truth |
|---|---|---|---|
| **Bronze** | 1-D lateral demand (excited p90 along s) | **Canonical production.** Default on load. | `data.lateral_demand` |
| **Silver** | 2-D demand surface over (s, n) | **Canonical derived surface.** | `data.lateral_demand_2d` |
| **Gold Lab** | Experimental physics-based corrections + compare workspace | **Never canonical, never default.** | `data.gold_lab` |

Bronze and Silver are CI-enforced bit-identical — any Gold-Lab work that changed them would break tests. The Gold Lab is where we *experiment with* physics corrections (bank, grade, combined), *compare* them against Bronze, and *decide* whether a candidate is strong enough to promote. The decision flows: shadow → beta candidate → canonical — and most candidates stop at one of the first two.

## The three categories inside Gold Lab

### 1. Shadow channels

Pure diagnostic overlays. Never shown as an operator-facing mode unless the data justifies it.

- **Bank field (shadow)** — `data.road_attitude_field.bank_*`. Multi-lap aggregated track-space bank estimate. Shown in the viewer under *Bank Field (Shadow)* for operator inspection.
- **Grade field (elevation shadow)** — `data.road_attitude_field.grade_elevation_*`. Deterministic derivative of the altitude profile. Shown under *Grade Field (Elevation Shadow)* because it's high-coverage and low-noise.
- **Lat Demand + Bank (shadow)** — `data.lateral_demand_shadow_bank_corrected`. Bank-corrected lateral demand at threshold 0.60. Legacy shadow baseline.
- **Longitudinal grade shadow** — `data.longitudinal_demand_shadow_grade_corrected`. Results were NEUTRAL; engineer-only diagnostics; **no operator-facing mode**.

### 2. Beta candidate

A single first-class non-canonical product that has passed the opt-in promotion gate.

- **`lat_demand_bank_corrected_beta`** — bank-corrected lateral demand at threshold 0.50, scale 1.0. Default-off. Shown under *Lat Demand + Bank (Beta Candidate)*. Users select it explicitly; Bronze remains canonical.

### 3. Diagnostic HUD + compare workspace

The sidebar's *Gold Lab* section renders:

- **Promotion gate surface** — decision class, canonical recommendation (yes/no), exact reason strong status is blocked.
- **Engineering HUD** — recommended threshold/scale, applied fraction, conf-weighted applied, cal_bias raw vs corrected, RMSE raw vs corrected, regime wins, best regime gain, worst regime regression, safety warnings.
- **Zone counts** — breakdown of s-bins across the six zone classes.
- **Spatial overlay toggles** — applied bins, plausible zones, suspicious zones.

## How the Beta Candidate is computed

For each bronze s-bin `i` (600 bins across the lap):

```
conf_i   = interp(bank_confidence_field, s_i)
bank_i   = interp(bank_mean_deg_field, s_i)
applied_i = (conf_i ≥ 0.50)            # threshold
if applied_i:
    signed_raw_i    = sign(κ_i) · bronze_magnitude_i
    signed_corr_i   = signed_raw_i − 1.0 · sin(bank_i_rad)   # scale = 1.0
    corrected_i     = |signed_corr_i|
else:
    corrected_i     = bronze_magnitude_i                      # pass through
```

Where the sign of the track curvature `κ` re-signs Bronze's unsigned magnitude arrays so the gravity-removal is physically sensible. This formula is identical to the one used in `lateral_demand_shadow_bank_corrected`, just at a looser threshold (0.50 vs 0.60) — the evaluator sweep picked 0.50 as the optimum on the OK karting dataset.

Beta output lives at `data.gold_lab.candidate_products.lat_demand_bank_corrected_beta`. It carries `default_enabled: false` and `canonical: false` in the JSON so any programmatic consumer sees the status before reading data.

## Why grade correction is diagnostics-only

The grade channel went through the same evaluation:

- **Elevation-derived grade** has 100% coverage and ~1° propagated std. It looks clean.
- **Apply it to longitudinal IMU**: on the OK dataset, `rmse(corrected − dv/dt_g)` moves by less than 0.005 G in every regime. The correction is physically correct but the signal is an order of magnitude smaller than the 0.2 G baseline mismatch between gravity-compensated IMU and dv/dt (mount residuals, tire drag, GPS differentiation noise). Verdict was **NEUTRAL**.
- Consequently: the grade field is diagnosable (Grade Field (Elevation Shadow) mode), but the longitudinal correction is NOT given a map mode. Its output lives in `data.longitudinal_demand_shadow_grade_corrected` for engineers who want to pull the numbers.

If a track with surveyed grade ground truth becomes available, or if a lower-noise reference channel (e.g. wheel-speed based accel) joins the pipeline, we'd re-evaluate.

## How promotion decisions are made

The rubric lives in `scripts/evaluate_bank_corrected_opt_in_candidate.py`. It computes per-regime metrics across a threshold × scale sweep and classifies the best combo:

| Decision | Means |
|---|---|
| `NOT_CANDIDATE` | Any hard stop triggered (straights regression > 0.15, global RMSE ↑ > 0.03 G, broad harm > 55% of bins). Do not promote. |
| `SHADOW_ONLY` | Hard stops pass but opt-in criteria don't all pass. Keep as shadow diagnostic. |
| `OPT_IN_CANDIDATE` | All opt-in criteria pass. Eligible for Beta promotion in a future PR. |
| `STRONG_OPT_IN_CANDIDATE` | Opt-in plus all three strong criteria (global gain ≥ 0.05, ≥ 5/6 regime wins, ≥ 50% of improvements in audit-plausible zones). Closer to canonical. |

Opt-in criteria:
- global \|cal−1\| improvement ≥ 0.02
- ≥ 4/6 regimes win
- worst regime regression ≤ 0.05
- threshold stability: cal spread across tested thresholds ≤ 0.03

Strong-candidate additions (all three):
- global improvement ≥ 0.05
- ≥ 5/6 regimes win
- ≥ 50% of improvements in audit-plausible zones

The rubric deliberately heavily penalises straight-regime regressions (safety-critical), broad harm in high-confidence zones, and gains concentrated in already-noisy regions.

## Zone intelligence

Every s-bin is classified once, by one function (`telemetry_tool/track_surface/gold_lab.py`), into one of six categories. The viewer tooltip, legend, compare drawer, and JSON all read from the same output:

| Class | Meaning |
|---|---|
| `high_conf_plausible_applied` | Correction fired; audit flagged this zone plausible. Safest bins. |
| `high_conf_suspicious_applied` | Correction fired, but audit flagged this zone suspicious. Purple-tinted in the viewer as a warning. |
| `high_conf_neither_applied` | Correction fired; audit had nothing to say. |
| `low_conf_raw_passthrough` | Correction skipped; confidence below threshold, no suspicion. |
| `low_conf_suspicious` | Correction skipped; audit flagged the zone suspicious AND confidence low. |
| `neutral_unclassified` | Nothing notable. |

Serialized at `data.gold_lab.zones_on_bronze_grid` (one class per bronze s-bin, 600 entries).

## What a future canonical promotion would require

**Not in this ticket. Not planned for the next ticket either.** The bar is:

1. A dataset with surveyed bank-angle ground truth on at least one track (the OK dataset has none).
2. Corrected lateral demand matching true centripetal within a tight `cal_bias` distance (≤ 0.03 to 1.0) across the whole session.
3. A re-run of the plausibility audit showing ≥ 50% of improvements concentrating in audit-plausible zones — which is the gap currently keeping the Beta at `OPT_IN_CANDIDATE` rather than `STRONG_OPT_IN_CANDIDATE`.
4. A code review that explicitly removes the `canonical: false` flag and the `default_enabled: false` flag on the beta candidate block in a labelled "promote Beta to canonical" PR.

Until all four hold, Bronze stays canonical. The Gold Lab's job is to make that decision visible, reversible, and defensible — not to force it.
