# Beta Estimator Technical Note

## Purpose

Replace the `vy=0` approximation in the slip-angle computation with a physically
honest sideslip estimate, widening the trusted observation count for the surface
friction field without fabricating observability.

## Estimator: Complementary Filter (forward + backward)

### State vector

- `vy` — lateral velocity at the CG in the body frame [m/s]
- Derived: `beta = atan2(vy, vx)` — sideslip angle [rad]

### Two independent paths

**Path 1 — Kinematic (from yaw rate):**
```
vy_kin = -b × yaw_rate
```
where `b` is the CG-to-rear-axle distance. This is the linearized bicycle model
rear-axle relation. It is noisy (amplifies yaw-rate sensor noise) but unbiased —
no drift.

**Path 2 — Integrated (from lateral acceleration):**
```
d(vy)/dt = a_lat_tire - vx × yaw_rate
vy_int += (a_lat_tire - vx × yaw_rate) × dt
```
This is Newton's second law in the body lateral direction. It is smooth (low noise)
but drifts due to accelerometer bias and integration error.

### Blending

```
alpha = alpha_min + (alpha_max - alpha_min) × min(vx / v_blend, 1)
vy = alpha × vy_kin + (1 - alpha) × vy_int
```

At high speed, alpha → 0.7 (mostly kinematic, because noise/signal is low).
At low speed, alpha → 0.1 (mostly integral, because kinematic blows up).

### Drift correction

The integral path is slowly pulled toward the kinematic estimate:
```
vy_int -= drift_correction_rate × (vy_int - vy_kin) × dt
```
This prevents long-term accumulation of accelerometer bias.

### Offline smoothing (non-causal)

For offline replay, we run the filter both forward and backward, then blend
by inverse variance. The backward pass provides information about what happens
AFTER each sample, effectively smoothing transients.

## Assumptions

1. `vx ≈ Speed` (cos(beta) ≈ 1 for small beta)
2. The rear-axle kinematic relation `vy ≈ -b × r` holds at steady state
3. `a_lat_tire` from the road state estimator has banking gravity removed
4. No wheel-speed corrections (kappa remains None in v1)

## Failure modes

| Condition | Effect | Mitigation |
|-----------|--------|------------|
| Low speed (< 5 m/s) | Kinematic blows up, integral meaningless | Guard: set beta=0, quality=0, reset integral |
| High yaw + low speed | Large vy_kin | Clamped to ±5 m/s |
| Accelerometer bias | Integral drifts | Drift correction pulls toward kinematic |
| Banking transition | road_state error → a_lat_tire contaminated | Road quality propagates → reduced beta quality |
| Curb strike / bump | Transient a_lat spike | Clamped beta ±0.25 rad, uncertainty increases |

## Confidence computation

```
speed_factor = min(vx / 30, 1.0)
disagreement = |vy_kin - vy_int| / max(vx, 1)
quality = speed_factor × (1 - disagreement × 0.5) × road_quality
```

Higher speed, lower path disagreement, and better road state → higher confidence.

## Why this is safer than vy=0

The `vy=0` approximation gives:
```
alpha_f = (a × r) / vx - delta
alpha_r = -(b × r) / vx
```

These are the linearized bicycle model slip angles WITH THE ASSUMPTION that
beta = 0. At steady cornering with a real car that has beta ≈ -0.5° to -2°,
the error is:
- alpha_f is biased by +beta (wrong by up to 0.03 rad)
- alpha_r is biased by +beta (wrong by up to 0.03 rad)

0.03 rad of slip angle error, fed into the Pacejka model at B=10, produces:
```
delta_Fy ≈ D × B × 0.03 ≈ 1.4 × Fz × 10 × 0.03 = 0.42 × Fz
```
At Fz = 3000 N, that's 1,260 N of force error — a significant fraction of
the Fy residual we observed (1,678 N → 1,531 N improvement).

## Validated impact (Daytona v3 → v4)

| Metric | vy=0 | beta estimator | Change |
|--------|------|---------------|--------|
| Accepted blocks | 19,316 | 26,990 | +40% |
| Fy residual std | 1,678 N | 1,531 N | -9% |
| Observations fed | 81k | 132k | +63% |
| Cells observed | 4,080 | 4,729 | +16% |
| Confidence > 0.5 | 2,722 | 3,554 | +31% |
| Racing line preserved | Yes | Yes | — |
