# Max-Envelope Track Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the racing line optimizer's visual overlap with the driver's actual line by rebuilding track boundaries from the max envelope of all driven laps (not statistical scatter) and decoupling the centerline from the racing line.

**Architecture:** A shared `envelope_boundaries.py` helper implements iterative centerline refinement and per-bin envelope extraction. The two data-build scripts use this helper. The OCP runner gets a min-curvature warm-start and post-solve validation.

**Tech Stack:** Python 3.14, NumPy, SciPy, CasADi (via lap_oracle).

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `scripts/envelope_boundaries.py` | Iterative envelope extraction + centerline refinement | Create |
| `scripts/build_ok_spa_data.py` | Ouest Karting data build using envelope helper | Modify |
| `scripts/build_kct_spa_data.py` | KCT data build using envelope helper | Modify |
| `scripts/compute_optimal_line_ok.py` | OCP runner with warm-start + validation | Modify |

---

## Task 1: Create envelope_boundaries.py helper

**Files:**
- Create: `scripts/envelope_boundaries.py`

- [ ] **Step 1: Write the helper module**

Create `scripts/envelope_boundaries.py` with the following content. This module provides: `compute_mean_centerline()`, `signed_perp_offset()`, `compute_envelope()`, `apply_min_width()`, `refine_centerline_iteratively()`, and `compute_curvature()`.

Full module source is provided in the design doc `docs/plans/2026-04-11-max-envelope-boundaries-design.md` under "The Six Concrete Changes" section. Key signatures:

```python
def compute_mean_centerline(all_laps_xy, n_bins, track_length):
    """Returns (center_x, center_y, s_grid) — first-pass centerline as mean of laps."""

def signed_perp_offset(x_lap, y_lap, dist_lap, center_x, center_y, s_grid):
    """Returns signed perpendicular offset per s-bin. Positive = left of heading."""

def compute_envelope(all_laps_xy, center_x, center_y, s_grid, track_length, buffer_m=1.0):
    """Returns (left_edge, right_edge) — max envelope + buffer."""

def apply_min_width(left_edge, right_edge, min_total_width=8.0):
    """Returns (left_edge, right_edge) expanded symmetrically to min_total_width if needed."""

def refine_centerline_iteratively(all_laps_xy, n_bins, track_length,
                                  n_iterations=2, buffer_m=1.0, min_total_width=8.0):
    """Iteratively refine centerline via envelope midpoint.
    Returns (center_x, center_y, s_grid, width_left, width_right).
    width_left and width_right are both positive (magnitudes per side)."""

def compute_curvature(center_x, center_y):
    """Returns (curvature_signed, heading_unwrapped) from a centerline."""
```

The implementation details are in the design doc. Each function uses numpy + scipy.ndimage.uniform_filter1d, no external deps beyond those already used by the build scripts.

- [ ] **Step 2: Verify it imports**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -c "import sys; sys.path.insert(0, 'scripts'); from envelope_boundaries import refine_centerline_iteratively, compute_curvature, signed_perp_offset; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/envelope_boundaries.py
git commit -m "feat(envelope): iterative max-envelope corridor extraction helper"
```

---

## Task 2: Update build_ok_spa_data.py to use envelope helper

**Files:**
- Modify: `scripts/build_ok_spa_data.py`

- [ ] **Step 1: Replace centerline + boundary block**

In `scripts/build_ok_spa_data.py`, find the block starting with `# Aggregate centerline` and ending before the `def build_driver` line. Replace everything in that range (centerline computation, curvature, grip map accumulation using old loop, width calculation) with:

```python
# Envelope-based centerline + boundaries
import sys as _sys
from pathlib import Path as _Path
if str(_Path(__file__).parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).parent))
from envelope_boundaries import (
    refine_centerline_iteratively,
    compute_curvature,
    signed_perp_offset,
)

all_laps_xy = []
for lap in all_valid:
    df = lap['df']
    lat = df['Latitude (deg)'].values
    lon = df['Longitude (deg)'].values
    dist = df['Distance (m)'].values
    x, y = to_xy(lat, lon)
    all_laps_xy.append((x, y, dist))

n_bins = 600
center_x, center_y, s_grid, width_left, width_right = refine_centerline_iteratively(
    all_laps_xy, n_bins, track_length,
    n_iterations=2, buffer_m=1.0, min_total_width=8.0,
)
print(f'Centerline: {n_bins} bins')
print(f'Width left:  {width_left.min():.1f}-{width_left.max():.1f}m')
print(f'Width right: {width_right.min():.1f}-{width_right.max():.1f}m')
total_w = width_left + width_right
print(f'Total width: {total_w.min():.1f}-{total_w.max():.1f}m')

curvature, heading_unwrapped = compute_curvature(center_x, center_y)

# Grip map from aggregated lateral G (unchanged logic, just rebuilt per new s_grid)
lat_accel_samples = [[] for _ in range(n_bins)]
for lap in all_valid:
    df = lap['df']
    dist_raw = df['Distance (m)'].values
    dist = dist_raw - dist_raw[0]
    if abs(dist[-1] - track_length) > track_length * 0.15:
        continue
    a_lat = (df['accel_lat_mps2'].values
             if 'accel_lat_mps2' in df.columns
             else np.zeros(len(df)))
    alat_interp = np.interp(s_grid, dist, np.abs(a_lat))
    for i in range(n_bins):
        lat_accel_samples[i].append(float(alat_interp[i] / _G))

grip_mu_p95 = np.array([
    float(np.percentile(samples, 95)) if len(samples) > 3 else 0.7
    for samples in lat_accel_samples
])
grip_mu_p95 = uniform_filter1d(grip_mu_p95, 5, mode='wrap')
print(f'Grip p95: min={grip_mu_p95.min():.3f}, '
      f'max={grip_mu_p95.max():.3f}, mean={grip_mu_p95.mean():.3f}')
```

- [ ] **Step 2: Update build_driver n_offset computation**

In the same file, find the `build_driver()` function. Locate the block that computes `n_offset` via a Python loop with `np.argmin`. Replace the entire loop (from the comment `# n_offset: signed perpendicular distance from centerline` through the loop body) with:

```python
    # n_offset from envelope helper
    dist_raw_drv = df['Distance (m)'].values
    dist_lap_drv = dist_raw_drv - dist_raw_drv[0]
    offsets_at_s = signed_perp_offset(
        x, y, dist_raw_drv, center_x, center_y, s_grid,
    )
    n_offset = np.interp(dist_lap_drv, s_grid, offsets_at_s)
```

- [ ] **Step 3: Run the updated script**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python scripts/build_ok_spa_data.py 2>&1 | tail -20`

Expected output includes:
- `Total valid laps: 42` (or similar)
- `Width left: X.X-Y.Ym` with max > 4.0
- `Width right: X.X-Y.Ym` with max > 4.0
- `Total width: Z.Z-W.Wm` with min >= 8.0
- `Saved track-surface-ok-data.json`

- [ ] **Step 4: Commit**

```bash
git add scripts/build_ok_spa_data.py
git commit -m "feat(ok): use envelope-based boundaries for Ouest Karting data"
```

---

## Task 3: Update build_kct_spa_data.py to use envelope helper

**Files:**
- Modify: `scripts/build_kct_spa_data.py`

- [ ] **Step 1: Apply the same replacement as Task 2**

In `scripts/build_kct_spa_data.py`, apply identical changes to those in Task 2 Step 1, but use `n_bins = 500` instead of 600 (KCT is a smaller track). The envelope helper import and replacement block are identical. The grip_map computation is identical.

- [ ] **Step 2: Update KCT's build_driver n_offset**

Apply the same `build_driver` replacement as Task 2 Step 2 — replace the inline `argmin` loop with the `signed_perp_offset` + `np.interp` pattern.

- [ ] **Step 3: Run the updated script**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python scripts/build_kct_spa_data.py 2>&1 | tail -15`

Expected: `Total width: Z.Z-W.Wm` with min >= 8.0, and `Saved track-surface-kct-data.json`.

- [ ] **Step 4: Commit**

```bash
git add scripts/build_kct_spa_data.py
git commit -m "feat(kct): use envelope-based boundaries for KCT data"
```

---

## Task 4: Add warm-start and validation to OCP runner

**Files:**
- Modify: `scripts/compute_optimal_line_ok.py`

- [ ] **Step 1: Add helper functions at the top of the script**

After the imports in `scripts/compute_optimal_line_ok.py`, add:

```python
def min_curvature_warm_start(curvature, width_left, width_right, alpha=3.0):
    """Initial N_lat guess: shift toward inside of each corner.

    Frenet convention: normal points LEFT, so positive n_offset = left of centerline.
    Left turn (curvature > 0) -> inside is LEFT -> positive n_offset.
    Right turn (curvature < 0) -> inside is RIGHT -> negative n_offset.
    """
    max_left = width_left * 0.8
    max_right = width_right * 0.8
    n_init = np.sign(curvature) * np.minimum(
        np.abs(curvature) * alpha,
        np.minimum(max_left, max_right),
    )
    return np.clip(n_init, -max_right, max_left)


def validate_optimal_line(driver_xy, optimal_xy):
    """Check if OCP optimal line is meaningfully different from driver's line."""
    n = min(len(driver_xy), len(optimal_xy))
    t_d = np.linspace(0, 1, len(driver_xy))
    t_o = np.linspace(0, 1, len(optimal_xy))
    t = np.linspace(0, 1, n)
    dx_d = np.interp(t, t_d, driver_xy[:, 0])
    dy_d = np.interp(t, t_d, driver_xy[:, 1])
    dx_o = np.interp(t, t_o, optimal_xy[:, 0])
    dy_o = np.interp(t, t_o, optimal_xy[:, 1])
    dist = np.sqrt((dx_d - dx_o) ** 2 + (dy_d - dy_o) ** 2)
    mean_sep = float(dist.mean())
    max_sep = float(dist.max())
    warnings = []
    if mean_sep < 2.0:
        warnings.append(f'Mean sep {mean_sep:.2f}m < 2.0m - optimal line barely distinct')
    if max_sep < 5.0:
        warnings.append(f'Max sep {max_sep:.2f}m < 5.0m - corridor not explored')
    return {'mean_sep': mean_sep, 'max_sep': max_sep, 'warnings': warnings}
```

- [ ] **Step 2: Monkey-patch the OCP solver to accept warm start**

Instead of modifying the lap_oracle OCP module, patch its internal `_solve_casadi` at runtime to use a precomputed warm start. Before the call to `solve_minimum_time(...)`, add:

```python
# Compute min-curvature warm start
warm_nlat = min_curvature_warm_start(
    curvature=track_model.curvature,
    width_left=track_model.width_left,
    width_right=track_model.width_right,
    alpha=3.0,
)
print(f'Warm start N_lat: [{warm_nlat.min():.2f}, {warm_nlat.max():.2f}]')

# Patch the solver to use this warm start via a module-level global
import lap_oracle.solver.ocp as _ocp_mod
_ocp_mod._WARM_START_NLAT = warm_nlat

# Patch set_initial to use the warm start when the variable is named N_lat
_original_build = _ocp_mod._solve_casadi
```

Then, copy the body of `_solve_casadi` from `telemetry_tool/lap_oracle/solver/ocp.py` (lines 92-231) into a local function `_patched_solve_casadi` in the script, with ONE change: after `opti.set_initial(N_lat, np.zeros(N))`, replace the zeros initialization with:

```python
    # Use precomputed warm start, interpolated to N solver points
    _warm = _ocp_mod._WARM_START_NLAT
    nlat_init = np.interp(
        np.linspace(0, 1, N),
        np.linspace(0, 1, len(_warm)),
        _warm,
    )
    opti.set_initial(N_lat, nlat_init)
```

Then: `_ocp_mod._solve_casadi = _patched_solve_casadi`.

The full patched function is long. Rather than embedding the entire copy here, the task-runner should: read `telemetry_tool/lap_oracle/solver/ocp.py` lines 92-231, copy that function into the script, rename it to `_patched_solve_casadi`, apply the single-line warm-start replacement described above, and assign it via the monkey patch.

- [ ] **Step 3: Add validation after solve**

Find the line that calls `solve_minimum_time(track_model, vehicle, ...)` and assigns to `sol`. After computing `optimal_x` and `optimal_y` (the world-space racing line), add:

```python
driver_best_xy = np.column_stack([
    np.array(d['drivers']['hamilton']['x']),
    np.array(d['drivers']['hamilton']['y']),
])
optimal_xy_arr = np.column_stack([optimal_x, optimal_y])
val = validate_optimal_line(driver_best_xy, optimal_xy_arr)
print('\nValidation:')
print(f'  Mean separation: {val["mean_sep"]:.2f}m')
print(f'  Max separation:  {val["max_sep"]:.2f}m')
for w in val['warnings']:
    print(f'  WARNING: {w}')
if val['mean_sep'] >= 2.0 and val['max_sep'] >= 5.0:
    print('  PASSED: optimal line is meaningfully different')
else:
    print('  FAILED: optimal line does not meet thresholds')
```

- [ ] **Step 4: Run the full pipeline**

Run the build script, then the OCP script:

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python scripts/build_ok_spa_data.py 2>&1 | tail -5
```

Then run the OCP runner via the script wrapper pattern that already exists:

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -c "import sys, os; sys.path.insert(0, os.path.abspath('.')); sys.path.insert(0, os.path.abspath('telemetry_tool')); import runpy; runpy.run_path('scripts/compute_optimal_line_ok.py', run_name='__main__')" 2>&1 | tail -25
```

Expected output:
- `Warm start N_lat: [X, Y]` with X < 0 < Y (spans both sides)
- `Optimal lap time: XX.XXXs`
- `Status: optimal`
- `Lateral offset range: [-A, +B]` with both A and B > 1
- `Mean separation: X.XXm` where X >= 2.0
- `Max separation: Y.YYm` where Y >= 5.0
- `PASSED: optimal line is meaningfully different`

- [ ] **Step 5: Rebuild HTML**

Run:
```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -c "
import re, json
with open('track-surface-spa.html','r',encoding='utf-8') as f:
    html = f.read()
with open('track-surface-ok-data.json','r') as f:
    data = json.load(f)
pat = re.compile(r'const INLINE_DATA = (\\{.*?\\});', re.DOTALL)
m = pat.search(html)
new_json = json.dumps(data, separators=(',', ':'))
new_html = html[:m.start(1)] + new_json + html[m.end(1):]
new_html = re.sub(r'>Hamilton<', '>Your best<', new_html)
new_html = re.sub(r'>Verstappen<', '>OCP optimal<', new_html)
with open('track-surface-ok.html','w',encoding='utf-8') as f:
    f.write(new_html)
print('Updated track-surface-ok.html')
"
```

- [ ] **Step 6: Commit**

```bash
git add scripts/compute_optimal_line_ok.py
git commit -m "feat(ocp): min-curvature warm-start + post-solve validation"
```

---

## Task 5: Visual verification

- [ ] **Step 1: Open the HTML in browser**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && start track-surface-ok.html`

Expected: The green (your best) and red (OCP optimal) tubes should be visually separated across most of the track. At corners, you should see the OCP line cutting apexes more aggressively than your line.

- [ ] **Step 2: If validation warnings appeared, diagnose**

If `mean_sep < 2.0` after the fix, possible causes and fixes:
- Curvature sign convention reversed: negate the sign in `min_curvature_warm_start` (change `np.sign(curvature)` to `-np.sign(curvature)`)
- Boundaries still too narrow: check `Width: ` output from Task 2. If total min < 10m, raise `min_total_width` to 10.0 in Task 2 Step 1 and Task 3 Step 1, then re-run
- Solver stuck at warm start: increase `alpha` to 5.0 in the `min_curvature_warm_start` call in Task 4 Step 2

- [ ] **Step 3: Final commit if adjustments were made**

```bash
git add scripts/
git commit -m "fix(ocp): tune warm-start parameters after visual verification"
```
