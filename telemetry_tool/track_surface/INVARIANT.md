# Track Surface Pipeline — Signal Invariant

**This pipeline estimates observed vehicle demand from phone/GPS data. It does not estimate tire-road friction coefficient or surface grip potential.**

## What the outputs are

| Output | Is | Is NOT |
|--------|-----|--------|
| `lateral_demand.excited_p90` | 90th percentile of centripetal-corrected lateral acceleration from excited (near-limit) driving events | Surface friction coefficient (mu) |
| `lateral_demand.combined_p90` | p90 of `sqrt(a_lat^2 + a_lon^2)` — total acceleration demand | Normalized tire-force utilization |
| `lateral_demand.confidence` | Statistical confidence from sample count, excitation fraction, and IMU/GPS agreement | Probability that the surface has a specific friction value |
| `lateral_demand.bank_estimate_deg` | Sensitivity indicator for slope/roll contamination, NOT a measured bank angle | A solved road-bank estimate |
| `grip_map` (legacy key) | Same data as `lateral_demand.excited_p90`, kept for visualization compatibility | A friction map — deprecated, do not build new features on this key |

## Tier classification

**Bronze (current):** Observed demand product. Lateral demand, combined demand, sensor quality, confidence. No surface-friction claims.

**Silver (current):** 2D observed demand field via `demand_2d.py`. `excited_p90(s, n)` with occupancy, confidence, and racing-line mask. Separates on-line from off-line demand. Same invariant as bronze — demand product, not friction estimate. Grid: `s_bin_m=4.0, n_bin_m=1.0`.

**Gold (future):** Surface inference layer. Probabilistic, separate from demand, explicit uncertainty. Only added once the physics/estimation stack supports it (tire model, vehicle-state estimator, observability gating).

## Schema note

`excited_p90` means: the 90th percentile of observed demand from samples that passed the excitation gate (session-relative p70 threshold). It is **not** a physical ceiling, **not** a friction ceiling, **not** a tire limit estimate. It is the upper end of what the driver actually generated at this track station when they were pushing.

## What would break this invariant

- Labeling any output as "grip," "friction," "mu," or "surface coefficient" without a Tier Gold estimator
- Using `grip_map` in new features (use `lateral_demand.*` instead)
- Presenting confidence as "probability of friction value" rather than "statistical quality of the demand measurement"
- Claiming the bank estimate is a physical measurement of road banking
