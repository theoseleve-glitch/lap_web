# Cross-Session Track Model Accumulation

## Problem

The track surface system (Frenet frame, boundaries, elevation, grip, vertical curvature) currently builds a model from a single session's data. Each session starts from scratch. A 1-lap session gets a "bronze" model; this never improves even if the same driver has 50 sessions at the same track.

## Goal

Every session that passes through the pipeline automatically enriches a persistent, cross-session track model. The solver uses the accumulated model — not just the current session — so coaching quality improves with every visit to a track.

## Approach: Hybrid DB + Parquet

1D per-metre properties (grip, elevation, slope, vert_curvature, width, camber) persist in the existing PG table `track_surfaces_global` via online weighted averaging.

Array data (centerline geometry, Frenet frame, 2D grip grid) persists as a Parquet sidecar per track, following the existing `parquet_manager.py` pattern.

## Data Flow

```
Session N pipeline
    → s10d_surface builds TrackSurface from this session's laps
    → upsert_global_surface(): merge 1D properties into PG (weighted avg)
    → merge_track_model(): merge geometry + 2D grip into Parquet sidecar

Session N+1 pipeline
    → load_track_model(): read accumulated TrackSurface from Parquet + PG
    → s10d_surface uses accumulated model as base, enriches with new laps
    → solver uses accumulated model (better boundaries, grip, elevation)
    → save updated model back
```

## Storage

### PG: `track_surfaces_global` (extend existing table)

New columns added to existing table via migration 053:

| Column | Type | Merge Strategy |
|--------|------|----------------|
| `elevation_m` | float | running weighted average |
| `slope_pct` | float | running weighted average |
| `vert_curvature_1pm` | float | running weighted average |
| `width_left_m` | float | running max |
| `width_right_m` | float | running max |
| `camber_rad` | float | running weighted average |

Existing columns (mu_lat_p95, mu_lat_mean, mu_lon_accel, mu_lon_brake, sample_count, session_count) unchanged.

### Parquet: `<SIDECAR_ROOT>/<track_id>/track_model.parquet`

| Field | Shape | Content |
|-------|-------|---------|
| `centerline_x` | (M,) | B-spline centerline x |
| `centerline_y` | (M,) | B-spline centerline y |
| `s_grid` | (M,) | cumulative arc length |
| `heading_rad` | (M,) | tangent angle |
| `curvature_1pm` | (M,) | signed horizontal curvature |
| `n_laps_accumulated` | scalar | total laps merged |
| `sim_sources` | list | contributing sim formats |

2D grip grid stored as separate `<SIDECAR_ROOT>/<track_id>/grip_2d.parquet` with columns: `s_bins`, `n_bins`, `mu_grid` (flattened), `count_grid` (flattened), `grid_shape_m`, `grid_shape_k`.

## Centerline Merge Algorithm

```
C_old = existing centerline, weight N_old
C_new = this session's centerline, weight N_new

1. Resample C_new to C_old's s-grid
2. Align start/finish via closest-point circular shift
3. Divergence check: reject if max deviation > 20m
4. Length check: reject if lap lengths differ > 10%
5. Weighted average: C_merged[i] = (C_old[i]*N_old + C_new[i]*N_new) / (N_old+N_new)
6. Re-fit B-spline, recompute heading + curvature, rebuild KD-tree
7. Save with N_merged = N_old + N_new
```

## New Code

### `track_surface/store.py` (~300 lines)

```python
def load_track_model(track_id: str, sidecar_root: str | None = None) -> TrackSurface | None:
    """Load accumulated TrackSurface from Parquet sidecar.
    sidecar_root defaults to path_manager.get_sidecar_dir() (same as sim_optimizer).
    Returns None if no model exists for this track."""

def merge_track_model(track_id: str, new_surface: TrackSurface, sidecar_root: str | None = None) -> None:
    """Merge a session's TrackSurface into the accumulated sidecar.
    sidecar_root defaults to path_manager.get_sidecar_dir().
    Creates sidecar from scratch if none exists (bootstrap).
    Applies divergence and length checks before merging."""

def upsert_global_surface(conn, track_id: str, surface: TrackSurface) -> int:
    """Upsert 1D surface properties into track_surfaces_global.
    Extends existing upsert_global_grip with elevation, width, camber, vert_curvature.
    Returns number of bins upserted."""
```

### `alembic/versions/053_track_surface_columns.py` (~40 lines)

Adds columns to `track_surfaces_global`: `elevation_m`, `slope_pct`, `vert_curvature_1pm`, `width_left_m`, `width_right_m`, `camber_rad`.

### `tests/test_track_store.py` (~200 lines)

- Bootstrap: first session creates sidecar from scratch
- Merge convergence: 5 sessions → centerline converges toward mean
- Divergence rejection: wildly different track rejected
- Length mismatch rejection: different layout rejected
- Load/save roundtrip: save then load recovers same data
- 1D upsert: PG columns updated with new surface properties

## Modified Files

| File | Change |
|------|--------|
| `track_surface/__init__.py` | Re-export `load_track_model`, `merge_track_model` |
| `track_surface/builder.py` | Accept optional `accumulated` TrackSurface to use as base |
| `pipeline/stages/s10d_surface.py` | Load accumulated before build, save after |
| `pipeline/orchestrator.py` | Wire load/save around s10d stage |

## Verification

```bash
# All new + existing tests pass
pytest telemetry_tool/tests/test_track_store.py -v
pytest telemetry_tool/tests/test_surface_builder.py -v
pytest telemetry_tool/tests/test_track_surface.py -v

# Full regression
pytest telemetry_tool/tests/test_track_surface.py telemetry_tool/tests/test_normalizer.py \
  telemetry_tool/tests/test_frenet.py telemetry_tool/tests/test_centerline.py \
  telemetry_tool/tests/test_surface_builder.py telemetry_tool/tests/test_line_delta.py \
  telemetry_tool/tests/adapters/test_lmu_adapter.py telemetry_tool/tests/adapters/test_f1_adapter.py -v
```
