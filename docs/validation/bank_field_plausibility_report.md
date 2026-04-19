# Bank Field Plausibility Audit

**Scope.** This is an *internal-consistency* audit of the `road_attitude_field.bank_*` channel. The OK track has no surveyed bank-angle ground truth, so we cannot claim correctness. What we can check is whether the estimate *behaves like a road* — spatially coherent, confident where evidence is dense, weak where it isn't, and correlated with visible track structure (curvature).

**Invariant.** Bronze/silver demand products are not consulted or modified here. No correction is applied.

## 1. Global statistics

```
  track length:           1203.5 m
  s-bin width:            5.0 m, n_bins: 241
  high confidence bins:   178 (73.9%)
  low confidence bins:    63 (26.1%)
  strongly-banked (|b| ≥ 3.0°): 103 (42.7%)
  tight & confident bins:  47 (19.5%)
  loose bins (std ≥ 3.0°): 105 (43.6%)
  mean bank (valid bins):  +0.07°
  median bank std (valid): 3.61°
  mean lap coverage:       39.9 laps
```

## 2. Distribution summary

- **bank_mean_deg**: p5=-7.365  p25=-2.279  p50=0.000  p75=2.600  p95=7.267
- **bank_std_deg**: p5=0.000  p25=0.000  p50=2.347  p75=4.459  p95=7.506
- **bank_confidence**: p5=0.150  p25=0.150  p50=0.700  p75=0.700  p95=1.000
- **bank_evidence_count**: p5=0.000  p25=0.000  p50=2696.000  p75=3534.000  p95=4963.000
- **bank_lap_coverage**: p5=0.000  p25=0.000  p50=41.000  p75=43.000  p95=43.000
- **|dbank/ds| (°/m)**: p5=0.000  p25=0.063  p50=0.265  p75=0.520  p95=0.831

## 3. Bank–curvature correlation

On a flat road with only side-cantering, bank should correlate weakly or not at all with centerline curvature. Strong correlation would suggest the estimator is still absorbing centripetal into bank.

  Pearson r(bank, κ) on high-confidence bins = **-0.260**
  → moderate correlation: some residual centripetal coupling may still be present.

## 4. Suspicious bins (flag for inspection)

These categories flag internal inconsistency. They are heuristic filters — some flagged bins may still be correct.

| category | n_bins | fraction | summary |
|---|---|---|---|
| high-conf & loose std (≥3.0°) | 105 | 43.6% | mean |bank| = 2.21° |
| |dbank/ds| ≥ 0.5 °/m | 66 | 27.4% | mean |bank| = 3.01° |
| strongly banked on nominal straight | 16 | 6.6% | mean |bank| = 6.09° |

### Top suspicious s-ranges to inspect

| s_start | s_end | n_bins | mean bank | max \|dbank/ds\| | min conf | reason |
|---|---|---|---|---|---|---|
| 948 | 1012 | 14 | +0.35° | 0.72 °/m | 0.70 | conf/spread, gradient |
| 458 | 478 | 5 | -6.37° | 0.80 °/m | 0.15 | gradient, bank on straight |
| 822 | 882 | 13 | -1.50° | 0.45 °/m | 0.70 | conf/spread |
| 1092 | 1138 | 10 | +0.84° | 0.76 °/m | 0.70 | conf/spread, gradient |
| 122 | 148 | 6 | -1.60° | 1.43 °/m | 0.15 | conf/spread, gradient, bank on straight |
| 488 | 548 | 13 | +0.16° | 0.67 °/m | 0.70 | conf/spread, gradient |
| 1022 | 1048 | 6 | +2.00° | 0.87 °/m | 0.70 | conf/spread, gradient, bank on straight |
| 722 | 762 | 9 | -1.33° | 0.64 °/m | 0.70 | conf/spread, gradient, bank on straight |
| 58 | 72 | 4 | +0.42° | 0.84 °/m | 0.70 | conf/spread, gradient |
| 32 | 42 | 3 | +5.33° | 0.80 °/m | 0.15 | gradient, bank on straight |

## 5. Strongest plausible bank zones

Contiguous same-sign, confident, consistent zones. These are the safest candidates for visual inspection in the Bank Field viewer mode.

| # | s_start | s_end | length | bank mean | mean std | mean conf | lap cov | κ̄ (1/m) |
|---|---|---|---|---|---|---|---|---|
| 1 | 42 | 62 | 25 m | +6.62° | 1.56° | 0.94 | 33.4 | 0.016 |
| 2 | 1058 | 1072 | 20 m | +6.24° | 1.07° | 0.93 | 34.5 | 0.019 |
| 3 | 348 | 372 | 30 m | -6.35° | 0.98° | 0.90 | 38.0 | 0.030 |
| 4 | 468 | 492 | 30 m | -6.29° | 1.89° | 0.89 | 40.7 | 0.016 |
| 5 | 612 | 628 | 20 m | +5.94° | 2.68° | 0.85 | 41.5 | 0.019 |
| 6 | 1082 | 1098 | 20 m | -5.40° | 1.40° | 0.92 | 38.8 | 0.023 |
| 7 | 288 | 322 | 40 m | -5.57° | 2.00° | 0.85 | 34.0 | 0.031 |
| 8 | 108 | 122 | 20 m | +5.05° | 3.53° | 0.85 | 38.8 | 0.013 |
| 9 | 932 | 948 | 20 m | +5.00° | 1.97° | 0.78 | 41.0 | 0.026 |
| 10 | 382 | 398 | 20 m | +5.23° | 2.30° | 0.71 | 43.0 | 0.013 |

## 6. Shortlist for viewer inspection

- **Plausible**: s ≈ 42–62 m, bank +6.62° (mean std 1.56°, conf 0.94) — 5 bins of consistent sign
- **Plausible**: s ≈ 1058–1072 m, bank +6.24° (mean std 1.07°, conf 0.93) — 4 bins of consistent sign
- **Plausible**: s ≈ 348–372 m, bank -6.35° (mean std 0.98°, conf 0.90) — 6 bins of consistent sign
- **Plausible**: s ≈ 468–492 m, bank -6.29° (mean std 1.89°, conf 0.89) — 6 bins of consistent sign
- **Plausible**: s ≈ 612–628 m, bank +5.94° (mean std 2.68°, conf 0.85) — 4 bins of consistent sign
- **Suspicious**: s ≈ 948–1012 m, mean bank +0.35°, max |dbank/ds| 0.72 °/m — worth a sanity pass
- **Suspicious**: s ≈ 458–478 m, mean bank -6.37°, max |dbank/ds| 0.80 °/m — worth a sanity pass
- **Suspicious**: s ≈ 822–882 m, mean bank -1.50°, max |dbank/ds| 0.45 °/m — worth a sanity pass
- **Suspicious**: s ≈ 1092–1138 m, mean bank +0.84°, max |dbank/ds| 0.76 °/m — worth a sanity pass
- **Suspicious**: s ≈ 122–148 m, mean bank -1.60°, max |dbank/ds| 1.43 °/m — worth a sanity pass

## 7. Verdict

**Not plausible enough yet.**

- Only 56.4% of bins have tight spread (need ≥70%).
- 27.4% of bins have steep dbank/ds.
- 16 confident 'banked straight' bins — too many.

Recommend: keep shadow visualization, do not run correction experiment yet.

---
*Audit generated by `scripts/audit_bank_field_plausibility.py`.*