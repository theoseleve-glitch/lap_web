# Silver Tier: 2D Demand Field — Design Spec

**Date**: 2026-04-14
**Status**: Approved
**Depends on**: Bronze tier (frozen, INVARIANT.md locked)
**Invariant**: This is a demand product, not a friction estimator.

## Goal

Add a 2D lateral-demand field `demand(s, n)` as a new silver-tier layer. Each cell in the (s, n) grid reports the observed lateral demand at that track station AND lateral position, with confidence and occupancy metadata. This separates on-line from off-line behavior without mutating bronze.

## Architecture

```
grip_2d.py (existing, unchanged)
    raw dynamics inversion: mu_grid(s,n), count_grid(s,n)
        ↓
demand_2d.py (NEW wrapper — applies bronze corrections in 2D)
    excitation gate (session-relative p70)
    centripetal substitution (where kappa > 0.1)
    confidence composite (count + excitation + calibration)
        ↓
DemandSurface2D dataclass
    excited_p90(s, n)      — silver core output
    occupancy(s, n)        — sample density
    confidence(s, n)       — per-cell quality
    racing_line_mask(s, n) — boolean on-line indicator
```

Bronze `lateral_demand.excited_p90(s)` continues unchanged. Silver adds `lateral_demand_2d.*` as a separate namespace.

## DemandSurface2D Dataclass

```python
@dataclass
class DemandSurface2D:
    s_bins: np.ndarray         # (M,) distance bin centers
    n_bins: np.ndarray         # (K,) lateral offset bin centers
    excited_p90: np.ndarray    # (M, K) p90 demand from excited samples
    occupancy: np.ndarray      # (M, K) sample count per cell
    confidence: np.ndarray     # (M, K) composite quality 0-1
    racing_line_mask: np.ndarray  # (M, K) boolean

    def demand_at(self, s: float, n: float) -> float:
        """Bilinear interpolation — same interface as GripSurface.mu_at()."""

    def on_line_mean(self) -> float:
        """Mean excited_p90 on the racing line."""

    def off_line_mean(self) -> float:
        """Mean excited_p90 off the racing line."""

    def to_dict(self) -> dict:
        """JSON-safe serialization."""
```

## Grid Resolution

`s_bin_m=4.0, n_bin_m=1.0, n_range_m=8.0`

For Ouest Karting (1203m, 43 laps):
- (M, K) = (300, 17) = 5,100 cells
- ~51,600 total samples → ~10 samples/cell average
- Coarser than bronze (2m) but statistically meaningful per cell

## Computation Pipeline (in demand_2d.py)

```python
def build_demand_surface_2d(
    frenet: FrenetFrame,
    laps: list[pd.DataFrame],
    excitation_thresholds: dict[str, float],
    curvature: np.ndarray,
    s_bin_m: float = 4.0,
    n_bin_m: float = 1.0,
    n_range_m: float = 8.0,
) -> DemandSurface2D:
```

Per sample:
1. Project (x, y) to (s, n) via `frenet.xy_to_sn()`
2. Compute `a_centripetal = v^2 * kappa(s) / g`
3. If `a_centripetal > 0.1`: use centripetal (curvature substitution)
4. Else: use `|a_lat_measured|`
5. Check excitation gate: `a_corrected > session_threshold`
6. Bin into (s_bin, n_bin)
7. Accumulate: all samples → occupancy; excited samples → demand_p90

Post-processing:
1. `excited_p90[si, ni] = np.percentile(excited_samples, 90)` per cell
2. `occupancy[si, ni] = len(all_samples)` per cell
3. `confidence = f(count, excitation_frac, centripetal_agreement)` per cell
4. `racing_line_mask = occupancy > np.percentile(occupancy[occupancy > 0], 75)`

## On-Line vs Off-Line

The occupancy grid is the key discriminator:
- **High occupancy cells** (top 25%) = racing line. The driver is here most of the time.
- **Low occupancy cells** = off-line excursions (traffic avoidance, mistakes, exploring).
- **Zero occupancy cells** = never driven. No demand data. Confidence = 0.

`racing_line_mask` is a boolean (M, K) array. It answers: "is this cell part of the usual driven path?"

## API Endpoint

```
GET /api/v1/sessions/{id}/demand-2d
```

Response:
```json
{
  "s_bins": [0, 4, 8, ...],
  "n_bins": [-8, -7, ..., 7, 8],
  "excited_p90": [[...], ...],
  "occupancy": [[...], ...],
  "confidence": [[...], ...],
  "racing_line_mask": [[...], ...],
  "on_line_mean_demand": 0.87,
  "off_line_mean_demand": 0.52,
  "grid_shape": [300, 17],
  "tier": "silver"
}
```

## Visualization

The Three.js ribbon mesh already has 8 lateral strips per row. Silver changes the per-vertex coloring:

- Bronze: all strips same color (from 1D demand)
- Silver: each strip colored from `demand_2d.excited_p90` at that (s, n) cell

Result: a **cross-track heatmap** where the racing line glows bright (high demand, well-sampled) and edges fade dark (low demand or no data).

For cells with `confidence < 0.3`, reduce opacity (faded/hatched) to show uncertainty.

## Files

| File | Action |
|------|--------|
| `telemetry_tool/track_surface/demand_2d.py` | Create: DemandSurface2D + build function |
| `telemetry_tool/web/routes/data_v2.py` | Modify: add `/demand-2d` endpoint |
| `scripts/build_ok_raw.py` | Modify: add `lateral_demand_2d` to JSON |
| `telemetry_tool/track_surface/INVARIANT.md` | Modify: add silver tier definition |
| `telemetry_tool/track_surface/grip_2d.py` | Unchanged |
| `telemetry_tool/track_surface/frenet.py` | Unchanged |

## Invariant Extension

Add to INVARIANT.md:

> **Silver (current):** 2D observed demand field. `demand(s, n)` with occupancy, confidence, and on-line/off-line separation. Honest labeling: `excited_p90`, not "surface grip." No tire model, no friction estimation.

## Out of Scope

- Gold tier (surface inference, tire model)
- Combined-slip 2D field (would need longitudinal binning too)
- External track geometry (user's separate Option B)
- Modifications to bronze outputs
