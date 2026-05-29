# Track-Surface Renderer — Ship Readiness (EXEC-1 … EXEC-10)

**Branch:** `feat/track-surface-render-finish` (off `lap_web` `main`)
**Flag:** gated FE feature (not a launch-promised surface; shipped clean).

**Verification model**
- FE: `tsc --noEmit` (clean for all track-surface files; the only 4 errors are pre-existing `*-showcase` TS1382, unrelated).
- Backend: `py_compile` + a synthetic `_per_vertex_speed` unit check.
- **Eyeball gates** = human via `npm run dev` (deferred — see Pending).
- **SPEED integration gate** = post-deploy `curl` (deferred — needs backend deploy).

## Commits (in order)
| Commit | Step |
|---|---|
| `085f4ae` | checkpoint EXEC-1..4 (oracle / iso camera / lit relief / GRIP buffers) |
| `47e04e4` | EXEC-5 floating control bar + A-lap selector |
| `5d90c43` | EXEC-6 GRADIENT mode |
| `b9abb46` | EXEC-8 Line2 driven line |
| `06c5a97` | EXEC-9 no-gt provisional fallback |
| `2fc189e` | EXEC-7 SPEED (backend binning + FE buffer) |
| _(this)_ | EXEC-10 cleanup + ship readiness |

## Target end-state

### 1. Renders for ALL tracks (gt + no-gt graceful, no crash) — ✅ code / 🟡 eyeball
- **gt** (KCT): constrained-Delaunay path (`mesh_tri_*`). EXEC-1 oracle (`DebugAsserts`) asserts `tris>0`, per-mesh `zspan>0`, no NaN, logs `[SURF-OK] tris=… zspan=… verts=…`.
- **no-gt provisional**: GPS-centreline ribbon + "Provisional — no ground-truth trace" badge; SPEED/GRIP disabled; `COLORS` made total over `HeatmapMode` so a gradient-default provisional surface can't crash on `COLORS[mode].high`. (EXEC-9)
- **no spatial trace**: bins without gt geometry *and* without GPS → clean empty state, not the degenerate straight-X ribbon. (EXEC-9 guard)
- **Eyeball status**: no renderable non-gt session exists in the data (`rt3_test` 404s, no bins) — provisional path verified by reading + the COLORS/guard fixes, not pixels.

### 2. Clean 3D, real elevation ×2 (no flat look / z-fight / tearing) — ✅ code / ⏳ eyeball
- `ELEVATION_SCALE = 2.0`; `computeVertexNormals()` + `computeBoundingBox()`; `MeshLambertMaterial({vertexColors, DoubleSide, polygonOffset})`; `ambientLight 0.55` + `directionalLight [0.4,0.6,1] 1.15`. (EXEC-3)
- Oracle's `zspan>0` assert guards the flat-look regression. polygonOffset (surface) + `depthWrite:false`/`renderOrder:1` (Line2) guard z-fighting.

### 3. Isometric default camera + intuitive orbit/pan/zoom — ✅ code / ⏳ eyeball
- `<Canvas orthographic>`; `camera.up=(0,0,1)`; imperative `OrbitControls` (damping 0.08, `screenSpacePanning`, polar clamps, `dispose()` cleanup); fit-to-bbox 3/4-iso. (EXEC-2)
- `fitKey = mesh_tri_sha256 ?? bins.length` → a **lap switch rebuilds geometry without re-framing** the camera. (EXEC-5)

### 4. Floating control bar: GRIP / SPEED / GRADIENT + A-lap dropdown — ✅ code / 🟡 eyeball
- Floating overlay over the canvas; `pointer-events` scoped to the pills (orbit/pan survive the gaps); ≥44px tap targets. (EXEC-5)
- **GRIP**: degenerate μ → grey + disabled (`isGripAvailable`, shared FE↔mesh); default mode = grip-if-real-else-gradient.
- **GRADIENT**: unscaled `d(elev)/d(dist)`, blue↓/grey/red↑, ±G % legend. (EXEC-6)
- **SPEED**: backend `mesh_tri_speed` (selected lap's max binned into grip_2d's `(s,n)` grid, NaN-empty); FE blue→green→yellow→red over `[min,max]`; km/h legend. (EXEC-7) — **integration gate PENDING deploy.**
- **A-lap dropdown**: best ★, invalid greyed; `?lap=N` → surface + gps-trace fetches.
- **Line2** driven line for the selected lap, normal-lifted, no z-fight. (EXEC-8)

## Numeric gates (run)
- **FE** `tsc --noEmit`: clean across all track-surface files.
- **Backend** `py_compile`: OK.
- **`_per_vertex_speed` synthetic unit**: own-cell hit, ±1-cell fallback, undriven→`None`, `len==vertex_count`, max in 8–35 m/s, `<5`-point guard → all pass.

## Pending to fully close (requires operator)
- [ ] **Backend deploy** → `api.lap-coach.racing`: `scp` `api_edge_payload.py` + `data_v2.py` to the VPS, then `docker compose -f docker-compose.prod.yml build api && up -d api`; `curl /healthz`. *(Behaviour additive + backward-compatible: `?lap` absent → best lap = prior behaviour; new fields ignored by old clients; `mesh_grid_*` removal only drops unread payload.)*
- [ ] **Post-deploy curl** (SPEED integration gate): `GET /sessions/<KCT>/track-surface?lap=N` → `mesh_tri_speed.length === mesh_tri_vertex_count`, `mesh_tri_speed_max_mps` ∈ [8,35], driven cells non-null / undriven null.
- [ ] **FE deploy**: `npm run cf:deploy`.
- [ ] **Eyeball** (`npm run dev`): KCT 3 modes + lap switch (no re-frame); OK (μ=0) GRIP greyed/disabled + SPEED/GRADIENT correct; relief shaded; Line2 floats clean.

## Cleanup notes (EXEC-10)
- `mesh_grid_xy` / `mesh_grid_sn`: removed from served payload + FE type (grep-confirmed zero consumers — FE renders `mesh_tri_*`; M×K fallback derives its grid from `mesh_spine/L/R`).
- `_seal_diag`: already absent from the served payload (computed + cached in the tri dict only) — verified, no change needed.
- Stale `MeshBasicMaterial is unlit` comment → corrected to Lambert/lit.
- Hand-rolled pointer/wheel listener leak: gone (replaced by addons `OrbitControls` + `dispose()`, EXEC-2).
- `kerb_buffer_iters`: left in place (dead param, `del`'d inside the validated `triangulated_surface` producer — not touched, to avoid disturbing the byte-identical-validated geometry; flag for a later producer-only cleanup).
