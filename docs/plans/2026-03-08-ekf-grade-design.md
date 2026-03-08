# EKF Sensor Fusion + Grade Wiring Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline

## Problem

1. **No sensor fusion**: GPS position/velocity and IMU accel/gyro are consumed independently. Noisy yaw_rate causes unstable corner detection. Heading derived from GPS bearing is noisy at low speed.

2. **Grade correction not wired**: `derived_channels.py` already has `compute_elevation_profile()` (grade_pct) and `compute_longitudinal_accel(correct_for_slope=True)`, but the pipeline doesn't wire them together. No quality gate on altitude data. No confidence label in output.

## Approach: EKF First, Grade Consumes Fused Channels (Approach B)

### 1. EKF-Lite Module (`telemetry_tool/fusion_ekf.py`)

**State vector** (5 elements): `[x, y, v, heading, yaw_rate]`

**Prediction model** (constant-yaw-rate kinematic):
```
x' = x + v*cos(heading)*dt
y' = y + v*sin(heading)*dt
v' = v + a_long*dt
heading' = heading + yaw_rate*dt
yaw_rate' = yaw_rate
```

**Measurement sources**:
| Source | Measures | Typical noise |
|--------|----------|---------------|
| GPS position | x, y | 2-5m CEP |
| GPS speed | v | 0.1-0.5 m/s |
| GPS bearing | heading | 2-5 deg |
| IMU accel_long | used in prediction | 0.05-0.2 m/s2 |
| IMU accel_lat | validates v*yaw_rate | 0.05-0.2 m/s2 |
| IMU gyro (yaw) | yaw_rate | 0.5-2 deg/s |

**Adaptive noise**: Process noise Q scaled by speed (more IMU trust at high speed, more GPS trust at low speed). Measurement noise R estimated from first ~100 samples.

**Output**: Overwrites columns in-place. Stores metadata in FusionResult:

```python
@dataclass
class FusionResult:
    method: str           # "ekf" | "smoothing_only" | "passthrough"
    sensors_used: list[str]
    confidence: float     # 0-1
    n_samples: int
    innovation_rms: float
```

**Graceful degradation**:
- GPS + IMU -> full EKF
- GPS only -> smoothing-only (Gaussian filter), method="smoothing_only"
- Neither -> passthrough, method="passthrough"

### 2. Pipeline Integration

**Stage 2.5** — after GPS filter (stage 2), before derived channels (stage 3):

```python
fusion_result, err = _safe_step("02b_sensor_fusion", _fusion)
```

EKF overwrites raw GPS/IMU columns with fused versions. Then derived_channels computes grade_pct, accel_long_mps2, yaw_rate_dps from already-fused data.

**Summary injection**:
```python
summary["sensor_fusion"] = fusion_result.to_dict()
summary["grade_status"] = "grade_used" | "grade_unavailable" | "grade_low_confidence"
```

### 3. Grade Wiring

Small changes to `derived_channels.py`:

1. Ensure `compute_longitudinal_accel()` called with `correct_for_slope=True` when `grade_pct` available
2. Altitude quality check: if altitude range < 0.5m over session, skip grade and label "grade_unavailable"
3. If altitude noise (rolling std) > 5m, label "grade_low_confidence"
4. Store grade_status in return metadata

### 4. Data Quality Extension

Add `fusion_confidence: float` to `DataQualityReport`. Factor into `overall_confidence` weighted composite. `adaptive_percentile()` uses fusion quality.

### 5. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/fusion_ekf.py` | New — EKF, FusionResult, run_sensor_fusion() |
| `telemetry_tool/pipeline.py` | Modified — stage 2.5, summary injection, grade_status |
| `telemetry_tool/derived_channels.py` | Modified — wire correct_for_slope, altitude quality check, grade label |
| `telemetry_tool/data_quality.py` | Modified — fusion_confidence in DataQualityReport |
| `telemetry_tool/tests/test_fusion_ekf.py` | New — 8 EKF unit tests |
| `telemetry_tool/tests/test_grade_wiring.py` | New — 6 grade tests |
| `telemetry_tool/tests/test_fusion_pipeline.py` | New — 3 integration tests |

No database migration needed — fusion metadata lives in summary JSON.
