# Grade Estimation — Architecture Decision Memo

**Scope.** Decide whether to invest in grade estimation as a near-term Gold product feature, and if so, which path.

**Scope limits.** Bank field progress is evaluated separately. This memo is *only* about the grade channel.

**Recommendation: pursue elevation-derived grade for Gold-beta** (option 3). Direct, unconfounded, good coverage.

## 1. Quantitative comparison

| option | coverage | median std (°) | p95 \|grade\| (°) | implementation cost | verdict |
|---|---|---|---|---|---|
| `current_imu_grade` | 67.2% | 4.59 | 4.86 | none (already built) | _insufficient for active use_ |
| `relaxed_gating` | 66.0% | 10.68 | 1.86 | small (config change, 1 line) | _likely not enough improvement to justify_ |
| `elevation_derived` | 100.0% | 1.00 | 2.65 | small (~20 lines in build_ok_raw.py) | _primary candidate for Gold-beta_ |
| `fused_imu_elevation` | 67.2% | 2.79 | 3.75 | medium (~100 lines, calibration and weight tuning) | _not worth the complexity_ |
| `drop` | 0.0% | 0.00 | 0.00 | none (remove grade_* JSON keys and viewer rows in a later cleanup PR) | _defensible if we want focus; does not block Gold-beta bank work_ |

## 2. Per-option assessment

### Option 1: `current_imu_grade`

**Description.** Track-space grade from IMU longitudinal residual. Current shadow-only channel.

- Coverage: **67.2%**
- Median spread: **4.59°**
- p95 |grade|: **4.86°**
- Implementation cost: **none (already built)**
- Product value: Spread is wide (median std ~10°). Individual bins cannot be trusted in isolation; zone-level aggregation is inconsistent.
- Verdict: _insufficient for active use_

### Option 2: `relaxed_gating`

**Description.** Same IMU path but grade_max_transient_g=0.5, min_orientation_quality=0.2.

- Coverage: **66.0%**
- Median spread: **10.68°**
- p95 |grade|: **1.86°**
- Implementation cost: **small (config change, 1 line)**
- Product value: Trade-off: more samples pass, but individual samples are lower quality. Expect similar or wider spread; marginal coverage gain.
- Verdict: _likely not enough improvement to justify_

### Option 3: `elevation_derived`

**Description.** grade(s) = arctan(dz/ds) from the smoothed altitude profile.

- Coverage: **100.0%**
- Median spread: **1.00°**
- p95 |grade|: **2.65°**
- Implementation cost: **small (~20 lines in build_ok_raw.py)**
- Product value: Directly observes the quantity we care about. Not confounded by vehicle dynamics. Depends on GPS altitude accuracy (~1 m for RTK).
- Verdict: _primary candidate for Gold-beta_

### Option 4: `fused_imu_elevation`

**Description.** Weighted combination of IMU grade and elevation-derived grade.

- Coverage: **67.2%**
- Median spread: **2.79°**
- p95 |grade|: **3.75°**
- Implementation cost: **medium (~100 lines, calibration and weight tuning)**
- Product value: IMU std (4.6°) >> elevation std (1.0°). Fusion would downweight IMU heavily; elevation alone is nearly as good.
- Verdict: _not worth the complexity_

### Option 5: `drop`

**Description.** Remove grade from the near-term Gold roadmap.

- Coverage: **0.0%**
- Median spread: **0.00°**
- p95 |grade|: **0.00°**
- Implementation cost: **none (remove grade_* JSON keys and viewer rows in a later cleanup PR)**
- Product value: Karts on typical tracks have <5° sustained grade. Bank is the much more influential correction. Grade can be re-introduced later if a specific use case (hill climb, mountain karting) demands it.
- Verdict: _defensible if we want focus; does not block Gold-beta bank work_

## 3. Qualitative trade-offs

| dimension | IMU (opt 1) | relaxed IMU (opt 2) | elevation (opt 3) | fused (opt 4) | drop (opt 5) |
|---|---|---|---|---|---|
| observability on kart data | low (long. dynamics dominate) | marginal | **high** (direct measurement) | moderate | n/a |
| sensitivity to driving-state contamination | **high** | very high | **none** | medium | n/a |
| coverage | partial | slightly higher | **near-total** | limited by weakest input | n/a |
| spread / stability | wide | wide | narrow | depends | n/a |
| implementation complexity | none (built) | trivial | small | medium | tiny (removals) |
| likely product value | low | low | moderate–high | marginal over opt 3 | zero near-term |

## 4. Decision

| final verdict | option |
|---|---|
| _insufficient for active use_ | `current_imu_grade` |
| _likely not enough improvement to justify_ | `relaxed_gating` |
| _primary candidate for Gold-beta_ | `elevation_derived` ← **RECOMMENDED** |
| _not worth the complexity_ | `fused_imu_elevation` |
| _defensible if we want focus; does not block Gold-beta bank work_ | `drop` |

## 5. Rationale

The elevation profile already lives in the JSON. Computing `grade(s) = arctan(dz/ds)` is cheap, direct, and not confounded by longitudinal vehicle dynamics. Median spread is low because the only noise source is GPS altitude uncertainty (~1 m for RTK). The IMU grade channel, by contrast, has median spread many times larger because karts rarely sit in the low-transient state the gate requires.

Fusion (option 4) is not worth the complexity: the IMU evidence is consistently lower quality than elevation on this dataset, so a weighted combination would downweight it heavily — leaving elevation doing essentially all the work.

## 6. Next actions

1. Add `grade_from_elevation_deg(s)` to `road_attitude_field.py` as a NEW field alongside the existing grade channel. Do not replace the IMU channel in this ticket.
2. Serialize under `data.road_attitude_field.grade_elevation_*`.
3. Repeat the plausibility audit for the new channel before discussing viewer integration.
4. Explicitly deprecate the IMU grade channel in the next minor release — keep it readable for rollback but stop improving it.

---
*Generated by `scripts/audit_grade_estimation_options.py`.*