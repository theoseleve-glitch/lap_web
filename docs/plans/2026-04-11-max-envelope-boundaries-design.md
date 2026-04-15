# Max-Envelope Track Reconstruction — Design Spec

**Date**: 2026-04-11
**Status**: Approved
**Context**: Fix for OCP racing line overlap with driver's actual line

## Problem

The current track surface reconstruction from driven GPS laps produces a
centerline that IS the driver's racing line (because it's the mean of
all driven laps). When the OCP solver optimizes lateral offset from this
centerline, the result barely differs from the driver's actual line.
Combined with narrow scatter-based boundaries (~3m per side), the OCP
has no meaningful corridor to explore and produces a visually
overlapping optimal trajectory.

## Root Causes

1. **Centerline bias**: `centerline = mean(driven_laps)` converges to the racing line when the same driver is consistent.
2. **Narrow boundaries**: `width = lateral_scatter × 3, clamped 3-10m` produces ~6m total width, insufficient for a kart track that's actually 8-12m wide.
3. **Curvature from biased centerline**: The κ(s) profile reflects the racing line's curvature, not the track's geometric curvature.
4. **Zero initial guess**: The OCP starts at `N_lat = 0` (the centerline, which is already the racing line), stuck in a local minimum near its starting point.
5. **One-sided result**: Observed output `lateral_offset ∈ [-9, 0]` — solver hits one boundary but never explores the other.

## Solution: Max-Envelope Corridor

Replace the biased "mean of laps" approach with a **max-envelope corridor**:
for each distance bin, find the extreme lateral positions ever driven
across all laps. The centerline becomes the midpoint of this envelope,
not the mean of the racing lines.

### Data Flow

```
All driven laps → iterative (s,n) projection → per-bin envelope:
                                                  left_edge = max(n_offset)
                                                  right_edge = min(n_offset)
→ centerline = midpoint(left_edge, right_edge)
→ width = left_edge - right_edge (clamped to ≥ MIN_WIDTH)
→ recompute curvature κ(s) from NEW centerline
→ OCP solver with min-curvature warm-start
→ optimal trajectory (verified distinct from driver's line)
```

## The Six Concrete Changes

### Change 1: Envelope-Based Boundaries

Replace scatter-based width with per-bin min/max of driven lateral offsets.

```python
BUFFER = 1.0  # meters — assumes drivers go close to real edges in some laps

n_offsets_at_bin = [[] for _ in range(n_bins)]
for lap in all_valid:
    x, y = to_xy(lap.lat, lap.lon)
    for i in range(len(x)):
        bin_idx = nearest_s_bin(x[i], y[i], centerline)
        n_off = signed_perp_distance(x[i], y[i], centerline, bin_idx)
        n_offsets_at_bin[bin_idx].append(n_off)

left_edge  = np.array([max(ns) + BUFFER if ns else 4.0 for ns in n_offsets_at_bin])
right_edge = np.array([min(ns) - BUFFER if ns else -4.0 for ns in n_offsets_at_bin])
```

### Change 2: Minimum Width Floor

```python
MIN_TOTAL_WIDTH = 8.0  # meters — typical kart track minimum

for i in range(n_bins):
    total = left_edge[i] - right_edge[i]
    if total < MIN_TOTAL_WIDTH:
        mid = (left_edge[i] + right_edge[i]) / 2
        left_edge[i]  = mid + MIN_TOTAL_WIDTH / 2
        right_edge[i] = mid - MIN_TOTAL_WIDTH / 2
```

### Change 3: Iterative Centerline Refinement

The first pass must still use mean-of-laps (needed to define the normal
direction for projecting into (s, n)). Then iterate:

```python
# Pass 1: initial centerline = mean of laps (current approach)
centerline_v1 = mean_of_laps(all_valid, n_bins)

# Pass 2: compute envelope, take midpoint as new centerline
envelope_v1 = compute_envelope(centerline_v1, all_valid)
centerline_v2 = midpoint(envelope_v1.left, envelope_v1.right)

# Pass 3: one more iteration for convergence
envelope_v2 = compute_envelope(centerline_v2, all_valid)
centerline_final = midpoint(envelope_v2.left, envelope_v2.right)

# Smooth
centerline_final = gaussian_smooth(centerline_final, sigma=5)
```

Two iterations converge because the envelope width doesn't depend
strongly on the exact centerline (it's approximately rotation-invariant
over short distances).

### Change 4: Recompute Curvature

```python
dx = np.gradient(centerline_final.x)
dy = np.gradient(centerline_final.y)
heading = np.unwrap(np.arctan2(dy, dx))
ds = np.sqrt(np.diff(centerline_final.x)**2 + np.diff(centerline_final.y)**2)
ds = np.append(ds, ds[-1])
curvature = np.gradient(heading) / np.maximum(ds, 0.01)
curvature = uniform_filter1d(curvature, 10, mode='wrap')
```

### Change 5: Min-Curvature Warm-Start for OCP

Before calling `solve_minimum_time`, compute an initial `N_lat` guess
that shifts toward the inside of each corner proportional to curvature:

```python
def min_curvature_initial_guess(curvature, left_edge, right_edge, alpha=3.0):
    """Initial guess: shift toward inside of each corner.

    Positive curvature = left turn → shift toward inside (negative n_offset)
    Negative curvature = right turn → shift toward inside (positive n_offset)
    """
    n_init = -np.sign(curvature) * np.minimum(
        np.abs(curvature) * alpha,
        0.8 * np.minimum(np.abs(left_edge), np.abs(right_edge))
    )
    return np.clip(n_init, right_edge * 0.9, left_edge * 0.9)
```

Then in `ocp.py`, pass this as the initial guess:
```python
opti.set_initial(N_lat, min_curvature_initial_guess(kappa, tk.width_left, tk.width_right))
```

### Change 6: Post-Solve Validation

```python
def validate_optimal_line(driver_xy, optimal_xy):
    # Same-t comparison
    n = min(len(driver_xy), len(optimal_xy))
    t = np.linspace(0, 1, n)
    dx = np.interp(t, np.linspace(0, 1, len(driver_xy)), driver_xy[:, 0]) - \
         np.interp(t, np.linspace(0, 1, len(optimal_xy)), optimal_xy[:, 0])
    dy = np.interp(t, np.linspace(0, 1, len(driver_xy)), driver_xy[:, 1]) - \
         np.interp(t, np.linspace(0, 1, len(optimal_xy)), optimal_xy[:, 1])
    dist = np.sqrt(dx**2 + dy**2)

    mean_sep = float(dist.mean())
    max_sep = float(dist.max())

    if mean_sep < 2.0:
        logger.warning(
            "OCP optimal line is barely distinct from driver's line "
            f"(mean sep {mean_sep:.2f}m < 2m). Likely causes: narrow corridor, "
            "bad warm-start, or curvature sign issue."
        )
    if max_sep < 5.0:
        logger.warning(
            f"OCP didn't explore corridor width (max sep {max_sep:.2f}m < 5m)."
        )

    return {'mean_sep': mean_sep, 'max_sep': max_sep}
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `scripts/envelope_boundaries.py` | Create | Shared helper: iterative envelope extraction + centerline refinement |
| `scripts/build_ok_spa_data.py` | Modify | Use envelope helper, recompute curvature from new centerline |
| `scripts/build_kct_spa_data.py` | Modify | Same changes for KCT |
| `scripts/compute_optimal_line_ok.py` | Modify | Add min-curvature warm-start + validation |

Only scripts change — no production pipeline changes. The envelope
approach is a visualization-only fix for the per-session HTML viewer.

## Constants

```python
BUFFER_M = 1.0           # safety buffer added to envelope edges
MIN_TOTAL_WIDTH_M = 8.0  # floor for kart tracks
N_BINS = 600             # distance bins for OK, 500 for KCT
WARM_START_ALPHA = 3.0   # curvature → lateral offset gain for initial guess
SEP_THRESHOLD_MEAN = 2.0 # validation threshold
SEP_THRESHOLD_MAX = 5.0  # validation threshold
```

## Success Criteria

After the fix, re-running the OK pipeline should produce:

1. **Lateral offset range spans both sides** — `N_lat` is no longer one-sided
2. **Mean separation from driver's best > 2.0m**
3. **Max separation from driver's best > 5.0m**
4. **Visually distinct lines** in the 3D viz (no overlap)
5. **Realistic time gap** (target 1.5-4s; NOT 20s — that inflation is from vehicle params, out of scope for this fix)

## Out of Scope

- **Vehicle parameter calibration** — the 20s inflated time gain is a
  separate issue. This fix targets the line shape, not the time.
- **External track geometry (Option B)** — user is working on this
  separately. This fix is the Option A stopgap.
- **Pipeline code changes** — only visualization scripts touched.
- **Frontend HTML changes** — the Three.js tube rendering already handles
  meaningful separation correctly.

## Testing

Manual test after implementation:
1. Run `python scripts/build_ok_spa_data.py`
2. Run `python scripts/compute_optimal_line_ok.py`
3. Verify `validate_optimal_line` logs mean_sep > 2m, max_sep > 5m
4. Open `track-surface-ok.html` and visually confirm the red and green
   lines are clearly distinct across the track
