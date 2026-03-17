# Per-Corner OCP Solver — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-corner QSS solver that runs before full-lap OCP, produces 3 ranked actionables per corner, and feeds into a warm-started full-lap composition.

**Architecture:** Two-pass corner solve → boundary reconciliation → full-lap warm-start. Reuses existing QSS forward/backward sweep on corner sub-segments.

**Tech Stack:** Python, NumPy, existing kart_envelope solver infrastructure

**Spec:** `docs/superpowers/specs/2026-03-14-per-corner-ocp-pipeline-reorder-design.md`

---

## Chunk 1: Per-Corner QSS Solver

### Task 1: Corner Solver Module

**Files:**
- Create: `kart_envelope/solver/corner_solver.py`
- Test: `kart_envelope/tests/test_corner_solver.py`

- [ ] **Step 1: Write test for corner QSS solve**

```python
# kart_envelope/tests/test_corner_solver.py
import numpy as np
import pytest
from kart_envelope.solver.corner_solver import solve_corner_qss, CornerOCPResult

def test_corner_qss_hairpin():
    """A tight hairpin should produce a speed dip at the apex."""
    n = 50
    distances = np.linspace(0, 100, n)
    # Curvature: 0 on approach, peak at 50m (apex), 0 on exit
    curvature = np.zeros(n)
    curvature[15:35] = 0.02  # tight corner, radius ~50m

    result = solve_corner_qss(
        curvature=curvature,
        distances=distances,
        mu=1.2,
        v_entry=20.0,   # 72 km/h entry
        v_exit=20.0,     # 72 km/h exit
        mass_kg=180.0,
    )

    assert isinstance(result, CornerOCPResult)
    assert len(result.speeds) == n
    # Apex speed should be slower than entry/exit
    apex_idx = np.argmin(result.speeds)
    assert result.speeds[apex_idx] < 20.0
    assert result.optimal_apex_speed < 20.0
    assert result.optimal_time_s > 0
    # Entry and exit should be at boundary speeds
    assert abs(result.speeds[0] - 20.0) < 0.5
    assert abs(result.speeds[-1] - 20.0) < 0.5


def test_corner_qss_straight():
    """A straight section should maintain/increase speed."""
    n = 30
    distances = np.linspace(0, 50, n)
    curvature = np.zeros(n)  # no curvature

    result = solve_corner_qss(
        curvature=curvature,
        distances=distances,
        mu=1.2,
        v_entry=15.0,
        v_exit=25.0,
        mass_kg=180.0,
    )

    # Speed should increase from entry to exit
    assert result.speeds[-1] >= result.speeds[0]
    assert result.optimal_time_s > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest kart_envelope/tests/test_corner_solver.py -v`
Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Implement `corner_solver.py`**

```python
# kart_envelope/solver/corner_solver.py
"""Per-corner QSS (Quasi-Steady-State) min-time solver.

Solves the minimum-time speed profile through a single corner segment
using forward/backward sweep with friction-limited cornering.
"""
import numpy as np
from dataclasses import dataclass, field

@dataclass
class CornerActionable:
    rank: int
    action: str
    impact_ms: float
    category: str    # braking | apex_speed | exit_traction | entry_speed | line | trail_brake
    phase: str       # entry | mid | exit

    def to_dict(self) -> dict:
        return {"rank": self.rank, "action": self.action,
                "impact_ms": round(self.impact_ms, 1),
                "category": self.category, "phase": self.phase}

@dataclass
class CornerOCPResult:
    corner_id: int
    distances: list[float]
    speeds: list[float]             # optimal speed profile (m/s)
    optimal_apex_speed: float
    optimal_entry_speed: float
    optimal_exit_speed: float
    optimal_time_s: float
    actual_apex_speed: float = 0.0
    actual_entry_speed: float = 0.0
    actual_exit_speed: float = 0.0
    actual_time_s: float = 0.0
    time_delta_s: float = 0.0
    speed_delta_apex: float = 0.0
    actionables: list[CornerActionable] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "distances": [round(d, 2) for d in self.distances],
            "optimal_speeds": [round(s, 4) for s in self.speeds],
            "optimal_apex_speed": round(self.optimal_apex_speed, 4),
            "optimal_entry_speed": round(self.optimal_entry_speed, 4),
            "optimal_exit_speed": round(self.optimal_exit_speed, 4),
            "optimal_time_s": round(self.optimal_time_s, 4),
            "actual_apex_speed": round(self.actual_apex_speed, 4),
            "actual_entry_speed": round(self.actual_entry_speed, 4),
            "actual_exit_speed": round(self.actual_exit_speed, 4),
            "actual_time_s": round(self.actual_time_s, 4),
            "time_delta_s": round(self.time_delta_s, 4),
            "speed_delta_apex": round(self.speed_delta_apex, 4),
            "actionables": [a.to_dict() for a in self.actionables],
        }


def _max_cornering_speed(curvature: float, mu: float, g: float = 9.81) -> float:
    """Maximum speed through a corner given curvature and friction."""
    if abs(curvature) < 1e-6:
        return 200.0  # effectively unlimited on a straight
    return np.sqrt(mu * g / abs(curvature))


def solve_corner_qss(
    curvature: np.ndarray,
    distances: np.ndarray,
    mu: float,
    v_entry: float,
    v_exit: float,
    mass_kg: float = 180.0,
    g: float = 9.81,
    accel_g: float = 0.5,
    brake_g: float = 1.2,
) -> CornerOCPResult:
    """QSS forward/backward sweep on a corner sub-segment.

    Forward pass: start at v_entry, accelerate up to cornering limit.
    Backward pass: start at v_exit, reverse-accelerate (brake from corner).
    Take minimum of both passes at each point = optimal speed profile.
    """
    n = len(distances)
    ds = np.diff(distances)

    # Cornering speed limit at each point
    v_corner_max = np.array([_max_cornering_speed(curvature[i], mu, g) for i in range(n)])

    # Forward pass (accelerating from entry)
    v_fwd = np.zeros(n)
    v_fwd[0] = min(v_entry, v_corner_max[0])
    a_max = accel_g * g
    for i in range(1, n):
        # v² = v0² + 2*a*ds
        v_max_accel = np.sqrt(max(0, v_fwd[i-1]**2 + 2 * a_max * ds[i-1]))
        v_fwd[i] = min(v_max_accel, v_corner_max[i])

    # Backward pass (braking from exit)
    v_bwd = np.zeros(n)
    v_bwd[-1] = min(v_exit, v_corner_max[-1])
    a_brake = brake_g * g
    for i in range(n - 2, -1, -1):
        v_max_brake = np.sqrt(max(0, v_bwd[i+1]**2 + 2 * a_brake * ds[i]))
        v_bwd[i] = min(v_max_brake, v_corner_max[i])

    # Take minimum of both passes
    v_opt = np.minimum(v_fwd, v_bwd)

    # Compute time through corner
    time_s = 0.0
    for i in range(n - 1):
        v_avg = (v_opt[i] + v_opt[i+1]) / 2
        if v_avg > 0.1:
            time_s += ds[i] / v_avg

    apex_idx = int(np.argmin(v_opt))

    return CornerOCPResult(
        corner_id=0,  # set by caller
        distances=distances.tolist(),
        speeds=v_opt.tolist(),
        optimal_apex_speed=float(v_opt[apex_idx]),
        optimal_entry_speed=float(v_opt[0]),
        optimal_exit_speed=float(v_opt[-1]),
        optimal_time_s=float(time_s),
    )
```

- [ ] **Step 4: Run tests**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest kart_envelope/tests/test_corner_solver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kart_envelope/solver/corner_solver.py kart_envelope/tests/test_corner_solver.py
git commit -m "feat(solver): per-corner QSS min-time solver with actionable outputs"
```

---

## Chunk 2: Actionable Generation

### Task 2: 3 Ranked Actionables Per Corner

**Files:**
- Create: `telemetry_tool/pipeline/stages/s10a_actionables.py`
- Test: `telemetry_tool/tests/test_corner_actionables.py`

- [ ] **Step 1: Write test**

```python
# telemetry_tool/tests/test_corner_actionables.py
from pipeline.stages.s10a_actionables import generate_actionables

def test_generates_exactly_3():
    result = generate_actionables(
        optimal_entry=20.0, actual_entry=18.5,
        optimal_apex=14.0, actual_apex=12.8,
        optimal_exit=17.0, actual_exit=16.2,
        optimal_brake_dist=45.0, actual_brake_dist=40.0,
        optimal_throttle_dist=55.0, actual_throttle_dist=62.0,
        corner_length_m=100.0,
    )
    assert len(result) == 3
    assert result[0].rank == 1
    assert result[1].rank == 2
    assert result[2].rank == 3
    # Ranked by impact (descending)
    assert result[0].impact_ms >= result[1].impact_ms
    assert result[1].impact_ms >= result[2].impact_ms

def test_all_actions_are_concrete():
    result = generate_actionables(
        optimal_entry=20.0, actual_entry=18.0,
        optimal_apex=14.0, actual_apex=13.0,
        optimal_exit=17.0, actual_exit=16.0,
        optimal_brake_dist=45.0, actual_brake_dist=42.0,
        optimal_throttle_dist=55.0, actual_throttle_dist=58.0,
        corner_length_m=100.0,
    )
    for a in result:
        # Must contain a number (concrete delta)
        assert any(c.isdigit() for c in a.action), f"Action not concrete: {a.action}"
        assert a.category in ("braking", "apex_speed", "exit_traction", "entry_speed", "trail_brake", "line")
        assert a.phase in ("entry", "mid", "exit")
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement `s10a_actionables.py`**

Generate candidates for all 6 categories, compute time impact for each, sort by impact, take top 3. Time impact estimated as: `speed_delta_mps * segment_duration / corner_length * 1000` (ms).

Template strings with concrete numbers (km/h, meters). No abstract advice.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10a_actionables.py telemetry_tool/tests/test_corner_actionables.py
git commit -m "feat(coaching): 3 ranked actionables per corner with concrete deltas"
```

---

## Chunk 3: Pipeline Stage + Orchestrator Reorder

### Task 3: Per-Corner OCP Pipeline Stage

**Files:**
- Create: `telemetry_tool/pipeline/stages/s10a_corner_ocp.py`
- Modify: `telemetry_tool/pipeline/orchestrator.py`
- Modify: `telemetry_tool/pipeline/stages/s10_theoretical.py`

- [ ] **Step 1: Create `s10a_corner_ocp.py`**

Orchestrates per-corner OCP:
1. Extract curvature segment for each corner (±50m margin)
2. Get entry/exit speeds from best lap at corner boundaries
3. Call `solve_corner_qss()` for each corner
4. Call `generate_actionables()` for each corner
5. Reconcile boundary speeds between adjacent corners
6. Return list of `CornerOCPResult`

- [ ] **Step 2: Modify `s10_theoretical.py` to accept warm-start**

Add optional `corner_ocp_results` parameter to `run_theoretical()`. When provided:
- Build an initial speed profile from the per-corner results
- Pass as warm-start to the full-lap solver
- Tag `sim_method` as `"per_corner_warm_ocp"`

- [ ] **Step 3: Modify `orchestrator.py` to run S10a before S10**

In the orchestrator's step sequence, insert `run_corner_ocp()` before `run_theoretical()`. Pass the per-corner results to `run_theoretical()`.

- [ ] **Step 4: Run existing tests to verify no regression**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/ -v --tb=short`

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10a_corner_ocp.py telemetry_tool/pipeline/stages/s10_theoretical.py telemetry_tool/pipeline/orchestrator.py
git commit -m "feat(pipeline): reorder stages — per-corner OCP before full-lap composition"
```

---

## Chunk 4: API + Frontend Wiring

### Task 4: Update `/corners` API Response

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

- [ ] **Step 1: Include `actionables` in `/corners` response**

When `corner_coaching` dict has `actionables` key, include it in the corner response object. Map to API field name `actionables`.

- [ ] **Step 2: Deploy backend**

```bash
scp telemetry_tool/web/routes/data_v2.py root@46.225.227.24:/opt/lap-api/telemetry_tool/web/routes/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): include per-corner actionables in /corners response"
```

### Task 5: Update Frontend VerdictSection

**Files:**
- Modify: `lap-website/src/components/app/corners/useCornerData.ts`
- Modify: `lap-website/src/components/app/corners/VerdictSection.tsx`

- [ ] **Step 1: Add actionable types to `useCornerData.ts`**

```typescript
export interface CornerActionable {
  rank: number;
  action: string;
  impact_ms: number;
  category: string;
  phase: string;
}
```

Add `actionables?: CornerActionable[]` to `CornerData` interface.

- [ ] **Step 2: Update `VerdictSection.tsx` to show 3 actionables**

Replace the single `coaching_hint` text with 3 ranked actionable items. Each shows: rank number, action text, impact in ms. Fall back to `coaching_hint` if `actionables` is empty.

- [ ] **Step 3: Build and deploy frontend**

```bash
cd lap-website && npm run build && npm run cf:deploy
```

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/components/app/corners/
git commit -m "feat(corners): show 3 ranked actionables per corner in verdict section"
```

---

## Chunk 5: Full Pipeline Test + Deploy

### Task 6: End-to-End Verification

- [ ] **Step 1: Run full pipeline on a test session locally**

```bash
python telemetry_tool/main.py data/raw/TEST_SESSION.csv
```

Verify: `theoretical_data.corner_coaching_json` now contains `actionables` array with 3 items per corner.

- [ ] **Step 2: Deploy full backend**

```bash
scp -r telemetry_tool/ kart_envelope/ root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

- [ ] **Step 3: Re-upload a session to trigger pipeline re-run**

Upload a CSV through the web UI. Verify corners appear with 3 actionables each.

- [ ] **Step 4: Verify live**

Visit the session → Corners & Coaching → click a corner → see 3 ranked actionables in the verdict section.
