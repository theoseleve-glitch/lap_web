# Distance-Binned Grip Map + Friction Envelope Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline

## Problem

1. **Global mu assumption**: The physics simulation uses a single friction coefficient (or none) for the entire lap. Real circuits have vastly different grip at each point — fresh tarmac in one corner, dusty patch in another, camber changes. A global mu either over-estimates (impossible corners) or under-estimates (wasted straights).

2. **Lateral-only grip model**: Current `FrictionLike.grip(v)` returns a single friction coefficient. Real vehicles have asymmetric traction/braking limits and combined lateral+longitudinal constraints (friction ellipse). The solver can produce impossible states where lateral + longitudinal exceed the tyre's capability.

3. **No visibility into grip quality**: Users have no way to see where grip is strong vs weak around the circuit, or how confident the estimate is per section.

## Approach

### 1. Grip Map Module (`telemetry_tool/grip_map.py`)

**Per-distance-bin mu estimation** from observed laps:

**Primary method** (lateral accel available):
```
mu_lat(s) = |a_lat(s)| / g
```
where `a_lat` is from derived channels (`accel_lat_mps2` or `Lateral acceleration (G) *calc`).

**Fallback method** (curvature + speed):
```
mu_lat(s) = v(s)^2 * |curvature(s)| / g
```
where curvature comes from `curvature_profile` and speed from resampled laps.

**Robust percentile extraction**:
- For each distance bin, collect mu samples across all learning laps
- Apply outlier rejection: IQR fence (1.5× IQR)
- Compute `mu_p50(s)`, `mu_p90(s)`, `mu_p95(s)`, `mu_p99(s)`
- `mu_mean(s)` = trimmed mean (after outlier rejection)

**Per-bin confidence**:
```python
@dataclass
class GripBinStats:
    distance_m: float
    mu_mean: float
    mu_p50: float
    mu_p90: float
    mu_p95: float
    mu_p99: float
    sample_count: int
    variance: float
    confidence: float    # 0-1 based on sample_count + variance
    source: str          # "lat_accel" | "curvature_speed" | "global_fallback"
```

**Confidence formula**:
```
count_score = min(1.0, sample_count / 8)  # need 8+ samples for good estimate
variance_score = max(0, 1.0 - variance / 0.1)  # high variance = low confidence
confidence = 0.6 * count_score + 0.4 * variance_score
```

**Global fallback**: If fewer than 50% of bins have confidence >= 0.3, revert to global `mu_global` = median of all valid mu samples, with a warning reason.

**Data model**:
```python
@dataclass
class GripMap:
    distance_bins: np.ndarray        # distance grid [m]
    mu_mean: np.ndarray              # mean mu per bin
    mu_p90: np.ndarray               # 90th percentile mu
    mu_p95: np.ndarray               # 95th percentile
    bin_stats: list[GripBinStats]    # full stats per bin
    global_mu: float                 # session-wide median mu
    is_global_fallback: bool         # True if per-bin data too sparse
    source: str                      # "lat_accel" | "curvature_speed"
    warning: str | None              # fallback reason if applicable
    n_laps_used: int

    def mu_at(self, distance: float, percentile: str = "p95") -> float:
        """Interpolate mu at arbitrary distance."""

    def to_dict(self) -> dict
```

### 2. Friction Envelope Module (`telemetry_tool/friction_envelope.py`)

**Combined acceleration envelope** from observed laps:

For each speed bin, collect `(a_lat, a_long)` pairs, then fit:

**Friction circle** (symmetric):
```
sqrt(ax^2 + ay^2) <= friction_limit(v)
```

**Friction ellipse** (asymmetric braking vs traction):
```
(ax / ax_max)^2 + (ay / ay_max)^2 <= 1
```
where `ax_max` differs for positive (traction) and negative (braking).

**Per-speed-bin envelope**:
```python
@dataclass
class FrictionBin:
    speed_center_mps: float
    combined_g_p95: float        # sqrt(ax^2+ay^2) 95th percentile
    lat_max_g: float             # |ay| 95th percentile
    accel_max_g: float           # ax (positive) 95th percentile
    brake_max_g: float           # |ax| (negative) 95th percentile
    sample_count: int
    confidence: float

@dataclass
class FrictionEnvelope:
    speed_bins: np.ndarray
    friction_bins: list[FrictionBin]
    global_combined_g: float
    is_reliable: bool
    warning: str | None

    def is_feasible(self, speed_mps: float, a_lat: float, a_long: float) -> bool:
        """Check if (a_lat, a_long) is within envelope at given speed."""

    def max_lat_at_long(self, speed_mps: float, a_long: float) -> float:
        """Max lateral accel given longitudinal accel (ellipse constraint)."""

    def to_dict(self) -> dict
```

### 3. Integration Points

**Pipeline stage 9.9** — after clustering (09h), before theoretical (10):
```python
_grip_map = grip_map.compute_grip_map(resampled_laps, curvature_profile, learning_laps)
_friction_envelope = friction_envelope.compute_friction_envelope(resampled_laps, learning_laps)
summary["grip_map"] = _grip_map.to_dict()
summary["friction_envelope"] = _friction_envelope.to_dict()
```

**Stage 10** — pass to simulation:
- `GripMap` replaces or augments `FrictionLike` — the simulator uses `mu_at(s)` for cornering limits
- `FrictionEnvelope.is_feasible()` constrains solver outputs
- The `simulate_theoretical_lap()` call gets `grip_map` parameter

**lap_simulation.py** changes:
- `simulate_theoretical_lap()` gains `grip_map: GripMap | None` parameter
- Cornering speed limit: `v_corner = sqrt(mu_at(s, "p95") * g / |curvature(s)|)` instead of global mu
- After forward-backward pass, clamp combined accel to friction envelope

### 4. Reporting

**Grip map plot** in HTML report:
- X-axis: distance (m), Y-axis: mu
- Lines: mu_mean, mu_p90, mu_p95
- Color bands for confidence (green = high, yellow = medium, red = low)
- Fallback banner if global fallback active

### 5. API

**New endpoint** or extend existing:
```
GET /api/v1/sessions/<id>/grip-map
→ { distance: [...], mu_mean: [...], mu_p90: [...], mu_p95: [...], confidence: [...] }
```

**Scores endpoint** gains `grip_map_available: bool`, `friction_envelope_available: bool`.

### 6. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/grip_map.py` | New |
| `telemetry_tool/friction_envelope.py` | New |
| `telemetry_tool/lap_simulation.py` | Modified — grip_map parameter, envelope constraint |
| `telemetry_tool/pipeline.py` | Modified — stages 9.9, 10 |
| `telemetry_tool/reporting_html.py` | Modified — grip map plot |
| `telemetry_tool/web/routes/data_v2.py` | Modified — grip-map endpoint |
| `telemetry_tool/tests/test_grip_map.py` | New |
| `telemetry_tool/tests/test_friction_envelope.py` | New |
| `telemetry_tool/tests/test_grip_pipeline.py` | New |

### 7. Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No lateral accel channel | Fall back to `v^2 * curvature / g` |
| Curvature unreliable | Fall back to global mu from lateral accel only |
| < 3 laps | Global mu, `is_global_fallback=True` |
| < 50% bins with confidence >= 0.3 | Global mu, warning reason |
| Friction envelope < 50 samples | `is_reliable=False`, solver ignores |
| Solver produces infeasible state | Clamp to envelope, add reason code |
