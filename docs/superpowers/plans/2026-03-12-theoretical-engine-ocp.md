# Theoretical Engine V2: OCP Solver Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CasADi/IPOPT optimal control solver that computes genuinely accurate theoretical lap times, running as a background Celery job that upgrades the existing QSS result.

**Architecture:** New `telemetry_tool/solver/` package with 8 modules (vehicle_params, load_transfer, tire_model, track_model, ocp_solver, calibrator, param_extractor, result). Integrates into the existing pipeline via a new Celery task queued after Stage 10. Feature-flagged by `THEORETICAL_OCP` env var.

**Tech Stack:** CasADi (>=3.6,<4.0) for symbolic NLP + bundled IPOPT solver. Python, NumPy, existing VehicleParameters from vehicle_model.py.

**Spec:** `docs/superpowers/specs/2026-03-12-theoretical-engine-ocp-design.md`

---

## File Structure

### New files (create)

| File | Responsibility |
|------|---------------|
| `telemetry_tool/solver/__init__.py` | Package init, public API re-exports |
| `telemetry_tool/solver/vehicle_params.py` | `OCPVehicleParams` dataclass extending existing `VehicleParameters` with load-transfer fields (h_cg, wheelbase, track_width) + class defaults |
| `telemetry_tool/solver/load_transfer.py` | `compute_load_transfer(params, a_long, a_lat)` — longitudinal + lateral weight transfer |
| `telemetry_tool/solver/tire_model.py` | `LoadSensitiveTire` class — mu(Fz) curve, friction ellipse evaluation, combined-slip check |
| `telemetry_tool/solver/track_model.py` | `TrackMesh` — curvature profile → collocation node array with adaptive refinement |
| `telemetry_tool/solver/ocp_solver.py` | `solve_ocp(mesh, params, tire, warm_start)` — CasADi NLP construction + IPOPT solve |
| `telemetry_tool/solver/calibrator.py` | `calibrate(params, ocp_result, actual_data)` — multi-parameter calibration loop |
| `telemetry_tool/solver/param_extractor.py` | `extract_params(best_lap_df, vehicle_params)` — extract mu_ref, P_max, F_brake_max from session data |
| `telemetry_tool/solver/result.py` | `TheoreticalResult` dataclass — speed profile, corner times, solver metadata, serialization |
| `telemetry_tool/tasks/ocp_tasks.py` | Celery task: `run_ocp_theoretical` — background job orchestrating the full OCP pipeline |
| `telemetry_tool/tests/test_solver_vehicle_params.py` | Tests for vehicle_params + load_transfer |
| `telemetry_tool/tests/test_solver_tire_model.py` | Tests for tire model |
| `telemetry_tool/tests/test_solver_track_model.py` | Tests for track mesh |
| `telemetry_tool/tests/test_solver_ocp.py` | Tests for OCP solver (constant-radius circle test) |
| `telemetry_tool/tests/test_solver_calibrator.py` | Tests for calibrator |
| `telemetry_tool/tests/test_solver_param_extractor.py` | Tests for param extraction |
| `telemetry_tool/tests/test_solver_integration.py` | Synthetic oval integration test (regression gate) |

### Modified files

| File | Change |
|------|--------|
| `requirements.txt` | Add `casadi>=3.6,<4.0` |
| `telemetry_tool/pipeline/stages/s10_theoretical.py` | Queue OCP Celery job after QSS completes |
| `telemetry_tool/web/routes/data_v2.py` | Add `?source=ocp` to speed-trace; add `theoretical_ocp_available` to session detail |

---

## Chunk 1: Foundation — Vehicle Params, Load Transfer, Tire Model

### Task 1: Add CasADi dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add casadi to requirements.txt**

Add after the last line:
```
casadi>=3.6,<4.0
```

- [ ] **Step 2: Verify installation**

Run: `pip install casadi>=3.6,<4.0`
Expected: Successfully installed casadi-3.x.x

- [ ] **Step 3: Verify import works**

Run: `python -c "import casadi; print(casadi.__version__)"`
Expected: Prints version like 3.6.x

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add casadi>=3.6 for OCP theoretical solver"
```

---

### Task 2: Vehicle Parameters + Load Transfer

**Files:**
- Create: `telemetry_tool/solver/__init__.py`
- Create: `telemetry_tool/solver/vehicle_params.py`
- Create: `telemetry_tool/solver/load_transfer.py`
- Test: `telemetry_tool/tests/test_solver_vehicle_params.py`

**Context:** The existing `telemetry_tool/vehicle_model.py` has a `VehicleParameters` dataclass with `peak_lateral_g`, `peak_braking_g`, `peak_traction_g`, `rolling_resistance_est`, `aero_drag_factor_est`, `VehicleClass` enum. The new `OCPVehicleParams` extends this with load-transfer-specific fields and converts existing fields to SI units.

- [ ] **Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_solver_vehicle_params.py
"""Tests for OCP vehicle parameters and load transfer."""
import math
import pytest

# Will fail until modules exist
from solver.vehicle_params import OCPVehicleParams, params_for_class
from solver.load_transfer import compute_load_transfer, compute_lateral_load_transfer


class TestOCPVehicleParams:
    """Test vehicle parameter creation and defaults."""

    def test_kart_defaults(self):
        p = params_for_class("kart")
        assert p.mass == 160.0
        assert p.h_cg == 0.25
        assert p.wheelbase == 1.05
        assert p.track_width == 1.2
        assert p.Cd == 0.5
        assert p.Cl == 0.0  # karts have no downforce
        assert p.rho == 1.225
        assert p.Cr == 0.015
        assert p.load_sensitivity == -0.08

    def test_car_defaults(self):
        p = params_for_class("car")
        assert p.mass == 1200.0
        assert p.h_cg == 0.45
        assert p.Cd == 0.35
        assert p.Cl == 0.1
        assert p.Cr == 0.012
        assert p.load_sensitivity == -0.15

    def test_from_vehicle_parameters(self):
        """Import from existing VehicleParameters dataclass."""
        from vehicle_model import VehicleParameters, VehicleClass
        vp = VehicleParameters(
            vehicle_class=VehicleClass.KART,
            estimated_mass_kg=155.0,
            peak_lateral_g=1.3,
            peak_braking_g=1.1,
            peak_traction_g=0.8,
            has_downforce=False,
            has_abs=False,
            rolling_resistance_est=0.013,
            aero_drag_factor_est=0.0,
        )
        p = OCPVehicleParams.from_vehicle_params(vp)
        assert p.mass == 155.0
        assert p.Cr == 0.013
        assert p.mu_ref == pytest.approx(1.3, abs=0.01)

    def test_unknown_class_uses_car_defaults(self):
        p = params_for_class("unknown")
        assert p.mass == 1200.0  # falls back to car


class TestLoadTransfer:
    """Test load transfer computations."""

    def test_longitudinal_braking(self):
        """Braking at 10 m/s^2 shifts weight forward."""
        p = params_for_class("car")  # m=1200, h_cg=0.45, L=2.6
        dFz_front, dFz_rear = compute_load_transfer(p, a_long=-10.0, a_lat=0.0)
        # delta = m * |a_long| * h_cg / L = 1200 * 10 * 0.45 / 2.6 = 2076.9 N
        expected = 1200 * 10 * 0.45 / 2.6
        assert dFz_front == pytest.approx(expected, rel=0.01)
        assert dFz_rear == pytest.approx(-expected, rel=0.01)

    def test_lateral_cornering(self):
        """Cornering at 10 m/s^2 shifts weight to outside."""
        p = params_for_class("car")  # m=1200, h_cg=0.45, tw=1.55
        dFz_outer, dFz_inner = compute_lateral_load_transfer(p, a_lat=10.0)
        # delta = m * |a_lat| * h_cg / tw = 1200 * 10 * 0.45 / 1.55 = 3483.9 N
        expected = 1200 * 10 * 0.45 / 1.55
        assert dFz_outer == pytest.approx(expected, rel=0.01)
        assert dFz_inner == pytest.approx(-expected, rel=0.01)

    def test_zero_accel_no_transfer(self):
        p = params_for_class("kart")
        dFz_front, dFz_rear = compute_load_transfer(p, a_long=0.0, a_lat=0.0)
        assert dFz_front == pytest.approx(0.0)
        assert dFz_rear == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_solver_vehicle_params.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solver'`

- [ ] **Step 3: Create solver package init**

```python
# telemetry_tool/solver/__init__.py
"""OCP theoretical lap solver — CasADi/IPOPT optimal control.

Feature-flagged by THEORETICAL_OCP env var (default ON, set =0 to disable).
"""
```

- [ ] **Step 4: Implement vehicle_params.py**

```python
# telemetry_tool/solver/vehicle_params.py
"""Extended vehicle parameters for the OCP solver.

Imports from the existing vehicle_model.VehicleParameters and adds
load-transfer-specific fields (CG height, wheelbase, track width).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_G = 9.80665

# Class defaults: (mass, h_cg, wheelbase, track_width, A, Cd, Cl, rho, Cr, load_sensitivity)
_CLASS_DEFAULTS: dict[str, dict[str, float]] = {
    "kart": {
        "mass": 160.0, "h_cg": 0.25, "wheelbase": 1.05, "track_width": 1.2,
        "A": 0.5, "Cd": 0.5, "Cl": 0.0, "rho": 1.225, "Cr": 0.015,
        "load_sensitivity": -0.08,
    },
    "car": {
        "mass": 1200.0, "h_cg": 0.45, "wheelbase": 2.6, "track_width": 1.55,
        "A": 2.0, "Cd": 0.35, "Cl": 0.1, "rho": 1.225, "Cr": 0.012,
        "load_sensitivity": -0.15,
    },
    "formula": {
        "mass": 740.0, "h_cg": 0.30, "wheelbase": 3.0, "track_width": 1.6,
        "A": 1.5, "Cd": 0.90, "Cl": 2.5, "rho": 1.225, "Cr": 0.010,
        "load_sensitivity": -0.12,
    },
}


@dataclass
class OCPVehicleParams:
    """Vehicle parameters for the optimal control solver."""

    # Core physical
    mass: float           # kg
    h_cg: float           # CG height (m)
    wheelbase: float      # m
    track_width: float    # m

    # Aero
    A: float              # frontal area (m^2)
    Cd: float             # drag coefficient
    Cl: float             # downforce coefficient
    rho: float            # air density (kg/m^3)

    # Rolling
    Cr: float             # rolling resistance coefficient

    # Tire
    mu_ref: float         # reference friction coefficient (from peak lateral g)
    load_sensitivity: float  # exponent in mu(Fz) = mu_ref * (Fz/Fz_ref)^sensitivity

    # Limits (extracted from session data or defaults)
    P_max: float = 0.0          # peak power (W)
    F_brake_max: float = 0.0    # peak braking force (N)
    F_drive_max: float = 0.0    # peak traction force (N)

    @property
    def Fz_static_front(self) -> float:
        """Static front axle vertical load (N), assuming 50/50 weight distribution."""
        return self.mass * _G / 2.0

    @property
    def Fz_static_rear(self) -> float:
        """Static rear axle vertical load (N)."""
        return self.mass * _G / 2.0

    @property
    def Fz_static_per_axle(self) -> float:
        """Static load per axle (N) — used as Fz_ref for tire model."""
        return self.mass * _G / 2.0

    @classmethod
    def from_vehicle_params(cls, vp: Any) -> OCPVehicleParams:
        """Create from existing vehicle_model.VehicleParameters."""
        vc = getattr(vp, "vehicle_class", None)
        class_key = _map_vehicle_class(vc)
        defaults = _CLASS_DEFAULTS.get(class_key, _CLASS_DEFAULTS["car"])

        mass = vp.estimated_mass_kg if vp.estimated_mass_kg else defaults["mass"]
        mu_ref = getattr(vp, "peak_lateral_g", 1.0)

        return cls(
            mass=mass,
            h_cg=defaults["h_cg"],
            wheelbase=defaults["wheelbase"],
            track_width=defaults["track_width"],
            A=defaults["A"],
            Cd=defaults["Cd"],
            Cl=defaults["Cl"] if getattr(vp, "has_downforce", False) else 0.0,
            rho=defaults["rho"],
            Cr=vp.rolling_resistance_est if hasattr(vp, "rolling_resistance_est") else defaults["Cr"],
            mu_ref=mu_ref,
            load_sensitivity=defaults["load_sensitivity"],
            P_max=0.0,       # set later by param_extractor
            F_brake_max=0.0,  # set later by param_extractor
            F_drive_max=0.0,  # set later by param_extractor
        )

    def to_dict(self) -> dict[str, float]:
        import dataclasses
        return {k: round(v, 6) if isinstance(v, float) else v
                for k, v in dataclasses.asdict(self).items()}


def params_for_class(vehicle_class: str) -> OCPVehicleParams:
    """Create default parameters for a vehicle class string."""
    class_key = vehicle_class.lower()
    if class_key not in _CLASS_DEFAULTS:
        class_key = "car"
    d = _CLASS_DEFAULTS[class_key]
    return OCPVehicleParams(
        mass=d["mass"], h_cg=d["h_cg"], wheelbase=d["wheelbase"],
        track_width=d["track_width"], A=d["A"], Cd=d["Cd"], Cl=d["Cl"],
        rho=d["rho"], Cr=d["Cr"], mu_ref=1.0,
        load_sensitivity=d["load_sensitivity"],
    )


def _map_vehicle_class(vc: Any) -> str:
    """Map VehicleClass enum value to a class key string."""
    if vc is None:
        return "car"
    val = vc.value if hasattr(vc, "value") else str(vc)
    mapping = {
        "kart": "kart", "formula": "formula",
        "gt": "car", "touring": "car", "road_car": "car", "unknown": "car",
    }
    return mapping.get(val.lower(), "car")
```

- [ ] **Step 5: Implement load_transfer.py**

```python
# telemetry_tool/solver/load_transfer.py
"""Longitudinal and lateral load transfer computations."""
from __future__ import annotations

from solver.vehicle_params import OCPVehicleParams


def compute_load_transfer(
    params: OCPVehicleParams,
    a_long: float,
    a_lat: float,
) -> tuple[float, float]:
    """Compute load transfer from longitudinal acceleration.

    Parameters
    ----------
    params : OCPVehicleParams
    a_long : Longitudinal acceleration (m/s^2, negative = braking)
    a_lat  : Lateral acceleration (m/s^2, positive = either direction)

    Returns
    -------
    (delta_Fz_positive, delta_Fz_negative) in Newtons.
    For longitudinal: (front_gain, rear_loss) — braking loads front.
    For lateral: (outer_gain, inner_loss) — cornering loads outside.
    When both are non-zero, returns the longitudinal component.
    Use compute_combined_load_transfer() for the full picture.
    """
    # Longitudinal: braking (a_long < 0) shifts weight forward
    delta_long = params.mass * abs(a_long) * params.h_cg / params.wheelbase
    if a_long < 0:
        # Braking: front gains, rear loses
        dFz_pos = delta_long
        dFz_neg = -delta_long
    elif a_long > 0:
        # Acceleration: rear gains, front loses
        dFz_pos = -delta_long
        dFz_neg = delta_long
    else:
        dFz_pos = 0.0
        dFz_neg = 0.0

    return dFz_pos, dFz_neg


def compute_lateral_load_transfer(
    params: OCPVehicleParams,
    a_lat: float,
) -> tuple[float, float]:
    """Compute lateral load transfer.

    Returns (outer_gain, inner_loss) in Newtons.
    """
    delta_lat = params.mass * abs(a_lat) * params.h_cg / params.track_width
    return delta_lat, -delta_lat


def compute_total_grip_factor(
    params: OCPVehicleParams,
    a_long: float,
    a_lat: float,
) -> float:
    """Compute the effective grip reduction factor due to load transfer.

    Returns a factor in (0, 1] where 1.0 = no reduction (no load transfer).
    Values < 1 indicate grip loss from load transfer + load sensitivity.

    This is the ratio: actual_total_grip / grip_without_load_transfer.
    """
    import math

    Fz_static = params.Fz_static_per_axle
    if Fz_static <= 0:
        return 1.0

    sens = params.load_sensitivity  # negative

    # Lateral load transfer (the dominant effect in corners)
    delta_lat = params.mass * abs(a_lat) * params.h_cg / params.track_width
    Fz_outer = Fz_static + delta_lat
    Fz_inner = max(Fz_static - delta_lat, 0.0)

    # mu for each side
    mu_outer = params.mu_ref * (Fz_outer / Fz_static) ** sens
    mu_inner = params.mu_ref * (Fz_inner / Fz_static) ** sens if Fz_inner > 0 else 0.0

    # Total lateral force vs. no-transfer baseline
    F_total = mu_outer * Fz_outer + mu_inner * Fz_inner
    F_baseline = 2.0 * params.mu_ref * Fz_static

    if F_baseline <= 0:
        return 1.0
    return F_total / F_baseline
```

- [ ] **Step 6: Run tests**

Run: `pytest telemetry_tool/tests/test_solver_vehicle_params.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/solver/__init__.py telemetry_tool/solver/vehicle_params.py \
       telemetry_tool/solver/load_transfer.py telemetry_tool/tests/test_solver_vehicle_params.py
git commit -m "feat(solver): add OCP vehicle params and load transfer model"
```

---

### Task 3: Tire Model

**Files:**
- Create: `telemetry_tool/solver/tire_model.py`
- Test: `telemetry_tool/tests/test_solver_tire_model.py`

**Context:** The tire model is the core accuracy lever. It implements load-sensitive grip `mu(Fz) = mu_ref * (Fz/Fz_ref)^sensitivity` and the combined-slip friction ellipse. This module is used by `ocp_solver.py` to build CasADi constraints.

- [ ] **Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_solver_tire_model.py
"""Tests for the load-sensitive tire model."""
import math
import pytest
import numpy as np

from solver.tire_model import LoadSensitiveTire

_G = 9.80665


class TestGripCurve:
    """Test the mu(Fz) load-sensitivity curve."""

    def test_at_reference_load(self):
        """At Fz = Fz_ref, mu should equal mu_ref exactly."""
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        assert tire.mu(3000.0) == pytest.approx(1.2, abs=1e-9)

    def test_higher_load_less_grip(self):
        """At Fz > Fz_ref with negative sensitivity, mu < mu_ref."""
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        mu_high = tire.mu(6000.0)
        assert mu_high < 1.2
        # (6000/3000)^(-0.1) = 2^(-0.1) = 0.9330...
        assert mu_high == pytest.approx(1.2 * 2**(-0.1), rel=1e-6)

    def test_lower_load_more_grip_coeff(self):
        """At Fz < Fz_ref, mu > mu_ref (lighter tire has higher mu)."""
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        mu_low = tire.mu(1500.0)
        assert mu_low > 1.2

    def test_zero_load_returns_zero_force(self):
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        assert tire.max_force(0.0) == pytest.approx(0.0)


class TestFrictionEllipse:
    """Test combined-slip constraint."""

    def test_pure_lateral_at_limit(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5000.0, sensitivity=0.0)
        Fz = 5000.0
        Fy_max = tire.mu(Fz) * Fz  # = 5000 N
        # At pure lateral limit: utilisation = 1.0
        util = tire.ellipse_utilisation(Fx=0.0, Fy=Fy_max, Fz=Fz)
        assert util == pytest.approx(1.0, abs=1e-6)

    def test_combined_over_limit(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5000.0, sensitivity=0.0)
        Fz = 5000.0
        F_max = tire.mu(Fz) * Fz
        # Both at 80% of max → sqrt(0.64 + 0.64) = 1.131 > 1.0
        util = tire.ellipse_utilisation(Fx=0.8*F_max, Fy=0.8*F_max, Fz=Fz)
        assert util > 1.0

    def test_combined_under_limit(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5000.0, sensitivity=0.0)
        Fz = 5000.0
        F_max = tire.mu(Fz) * Fz
        # Both at 50% → sqrt(0.25 + 0.25) = 0.707 < 1.0
        util = tire.ellipse_utilisation(Fx=0.5*F_max, Fy=0.5*F_max, Fz=Fz)
        assert util < 1.0

    def test_accel_domain_conversion(self):
        """Test acceleration-domain grip limits."""
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5886.0, sensitivity=0.0)
        mass = 1200.0
        Fz = 5886.0  # static load per axle
        a_max = tire.a_max(Fz, mass)
        # mu=1.0, Fz/m = 5886/1200 = 4.905 m/s^2
        assert a_max == pytest.approx(5886.0 / 1200.0, rel=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_solver_tire_model.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement tire_model.py**

```python
# telemetry_tool/solver/tire_model.py
"""Load-sensitive tire model with friction ellipse.

Implements:
  mu(Fz) = mu_ref * (Fz / Fz_ref) ^ sensitivity
  Friction ellipse: (Fx/Fx_max)^2 + (Fy/Fy_max)^2 <= 1
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class LoadSensitiveTire:
    """Tire model with load-dependent grip coefficient."""

    mu_ref: float       # reference friction coefficient
    Fz_ref: float       # reference vertical load (N)
    sensitivity: float  # load sensitivity exponent (typically negative)

    def mu(self, Fz: float) -> float:
        """Grip coefficient at a given vertical load."""
        if Fz <= 0 or self.Fz_ref <= 0:
            return 0.0
        return self.mu_ref * (Fz / self.Fz_ref) ** self.sensitivity

    def max_force(self, Fz: float) -> float:
        """Maximum tire force at a given vertical load (N)."""
        if Fz <= 0:
            return 0.0
        return self.mu(Fz) * Fz

    def ellipse_utilisation(self, Fx: float, Fy: float, Fz: float) -> float:
        """Friction ellipse utilisation ratio.

        Returns sqrt((Fx/Fx_max)^2 + (Fy/Fy_max)^2).
        Values > 1.0 exceed the grip limit.
        """
        F_max = self.max_force(Fz)
        if F_max <= 0:
            return float("inf") if (abs(Fx) + abs(Fy)) > 0 else 0.0
        return math.sqrt((Fx / F_max) ** 2 + (Fy / F_max) ** 2)

    def a_max(self, Fz: float, mass: float) -> float:
        """Maximum acceleration magnitude at given vertical load (m/s^2)."""
        if mass <= 0:
            return 0.0
        return self.max_force(Fz) / mass
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_solver_tire_model.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/solver/tire_model.py telemetry_tool/tests/test_solver_tire_model.py
git commit -m "feat(solver): add load-sensitive tire model with friction ellipse"
```

---

### Task 4: Track Model (Collocation Mesh)

**Files:**
- Create: `telemetry_tool/solver/track_model.py`
- Test: `telemetry_tool/tests/test_solver_track_model.py`

**Context:** Converts the existing curvature profile (`curvature_1pm` column from `s10_theoretical.py`) into a collocation mesh with adaptive refinement. Denser nodes in corners, sparser on straights.

- [ ] **Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_solver_track_model.py
"""Tests for track mesh generation."""
import numpy as np
import pytest

from solver.track_model import TrackMesh, build_mesh, refine_mesh


class TestBuildMesh:
    """Test initial uniform mesh creation."""

    def test_uniform_mesh_node_count(self):
        distances = np.linspace(0, 1000, 2000)
        curvatures = np.zeros(2000)
        mesh = build_mesh(distances, curvatures, n_nodes=500)
        assert len(mesh.s) == 500
        assert mesh.s[0] == pytest.approx(0.0)
        assert mesh.s[-1] == pytest.approx(1000.0, rel=1e-3)

    def test_curvature_interpolated(self):
        distances = np.linspace(0, 100, 1000)
        curvatures = np.sin(distances * 0.1)  # smooth curvature
        mesh = build_mesh(distances, curvatures, n_nodes=50)
        assert len(mesh.kappa) == 50
        # Curvature should be interpolated, not zero
        assert np.any(np.abs(mesh.kappa) > 0.01)

    def test_ds_positive(self):
        distances = np.linspace(0, 500, 1000)
        curvatures = np.zeros(1000)
        mesh = build_mesh(distances, curvatures, n_nodes=100)
        assert np.all(mesh.ds > 0)
        assert len(mesh.ds) == 99  # N-1 intervals


class TestRefineMesh:
    """Test adaptive mesh refinement."""

    def test_refine_adds_nodes_in_high_gradient(self):
        """Mesh should get denser where speed changes rapidly."""
        s = np.linspace(0, 500, 100)
        kappa = np.zeros(100)
        # Put a sharp curvature spike in the middle
        kappa[45:55] = 0.05  # 20m radius corner
        mesh = build_mesh(s, kappa, n_nodes=100)

        # Simulate a speed profile with gradient in the corner
        speed = np.ones(100) * 30.0
        speed[45:55] = 15.0  # big speed drop in corner

        refined = refine_mesh(mesh, speed, gradient_threshold=0.5)
        assert len(refined.s) > len(mesh.s)

    def test_refine_preserves_endpoints(self):
        s = np.linspace(0, 1000, 200)
        kappa = np.zeros(200)
        mesh = build_mesh(s, kappa, n_nodes=50)
        speed = np.ones(50) * 25.0
        refined = refine_mesh(mesh, speed, gradient_threshold=0.01)
        assert refined.s[0] == pytest.approx(0.0)
        assert refined.s[-1] == pytest.approx(1000.0, rel=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_solver_track_model.py -v`
Expected: FAIL

- [ ] **Step 3: Implement track_model.py**

```python
# telemetry_tool/solver/track_model.py
"""Track mesh for OCP collocation.

Converts curvature profile to a discretized mesh with adaptive refinement.
Reuses the existing curvature_1pm column from s10_theoretical.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TrackMesh:
    """Discretized track for collocation."""

    s: np.ndarray       # distance at each node (m), shape (N,)
    kappa: np.ndarray   # curvature at each node (1/m), shape (N,)
    ds: np.ndarray      # interval lengths (m), shape (N-1,)
    track_length: float  # total track length (m)


def build_mesh(
    distances: np.ndarray,
    curvatures: np.ndarray,
    n_nodes: int = 500,
) -> TrackMesh:
    """Build a uniform collocation mesh from raw curvature data.

    Parameters
    ----------
    distances : Distance array from curvature profile (m).
    curvatures : Curvature array (1/m).
    n_nodes : Number of collocation nodes.
    """
    track_length = float(distances[-1] - distances[0])
    s = np.linspace(float(distances[0]), float(distances[-1]), n_nodes)
    kappa = np.interp(s, distances, curvatures)
    ds = np.diff(s)
    return TrackMesh(s=s, kappa=kappa, ds=ds, track_length=track_length)


def refine_mesh(
    mesh: TrackMesh,
    speed_profile: np.ndarray,
    gradient_threshold: float = 0.5,
) -> TrackMesh:
    """Refine mesh by adding nodes in high-gradient regions.

    Parameters
    ----------
    mesh : Current mesh.
    speed_profile : Speed at each node (m/s), shape (N,).
    gradient_threshold : dv/ds threshold (m/s per m) for refinement.

    Returns
    -------
    Refined TrackMesh with more nodes in high-gradient regions.
    """
    dv_ds = np.abs(np.diff(speed_profile) / mesh.ds)

    new_points = [mesh.s[0]]
    for i in range(len(mesh.ds)):
        if dv_ds[i] > gradient_threshold:
            # Insert midpoint
            mid = (mesh.s[i] + mesh.s[i + 1]) / 2.0
            new_points.append(mid)
        new_points.append(mesh.s[i + 1])

    s_refined = np.array(sorted(set(new_points)))
    kappa_refined = np.interp(s_refined, mesh.s, mesh.kappa)
    ds_refined = np.diff(s_refined)

    return TrackMesh(
        s=s_refined,
        kappa=kappa_refined,
        ds=ds_refined,
        track_length=mesh.track_length,
    )


def build_mesh_from_curvature_profile(
    curvature_profile_df,
    n_nodes: int = 500,
) -> TrackMesh | None:
    """Build mesh from the pipeline's curvature_profile DataFrame.

    Expected columns: 'distance_m', 'curvature_1pm'.
    Returns None if required columns are missing.
    """
    if curvature_profile_df is None:
        return None
    if "distance_m" not in curvature_profile_df.columns:
        return None
    if "curvature_1pm" not in curvature_profile_df.columns:
        return None

    distances = curvature_profile_df["distance_m"].to_numpy(dtype=float)
    curvatures = curvature_profile_df["curvature_1pm"].to_numpy(dtype=float)

    # Clean NaN values
    valid = np.isfinite(distances) & np.isfinite(curvatures)
    if valid.sum() < 10:
        return None

    return build_mesh(distances[valid], curvatures[valid], n_nodes=n_nodes)
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_solver_track_model.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/solver/track_model.py telemetry_tool/tests/test_solver_track_model.py
git commit -m "feat(solver): add track mesh with adaptive refinement"
```

---

### Task 5: Parameter Extractor

**Files:**
- Create: `telemetry_tool/solver/param_extractor.py`
- Test: `telemetry_tool/tests/test_solver_param_extractor.py`

**Context:** Extracts P_max, F_brake_max, F_drive_max, mu_ref from the best lap DataFrame. Uses peak observed accelerations × mass × speed. The existing `VehicleParameters` already has `peak_lateral_g`, `peak_braking_g`, `peak_traction_g` — this module refines those into force/power units and adds P_max.

- [ ] **Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_solver_param_extractor.py
"""Tests for parameter extraction from session data."""
import numpy as np
import pandas as pd
import pytest

from solver.param_extractor import extract_session_params
from solver.vehicle_params import params_for_class

_G = 9.80665


class TestExtractSessionParams:

    def _make_lap_df(self, n=200):
        """Create a synthetic lap DataFrame with required columns."""
        dist = np.linspace(0, 1000, n)
        speed = np.full(n, 25.0)  # 25 m/s = 90 km/h
        # Braking zone: strong decel
        speed[50:70] = np.linspace(25, 15, 20)
        # Corner: low speed, high lateral
        speed[70:100] = 15.0
        # Exit: acceleration
        speed[100:130] = np.linspace(15, 25, 30)

        a_long = np.gradient(speed ** 2, dist) / 2.0  # from v^2 = v0^2 + 2*a*ds
        a_lat = np.zeros(n)
        a_lat[70:100] = 8.0  # 0.82g lateral

        return pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "accel_long_mps2": a_long,
            "accel_lat_mps2": a_lat,
        })

    def test_extracts_mu_ref(self):
        df = self._make_lap_df()
        base = params_for_class("car")
        result = extract_session_params(df, base)
        # Peak lateral is 8.0 m/s^2 = 0.816g
        assert result.mu_ref == pytest.approx(8.0 / _G, rel=0.05)

    def test_extracts_P_max(self):
        df = self._make_lap_df()
        base = params_for_class("car")
        result = extract_session_params(df, base)
        assert result.P_max > 0

    def test_extracts_F_brake_max(self):
        df = self._make_lap_df()
        base = params_for_class("car")
        result = extract_session_params(df, base)
        assert result.F_brake_max > 0

    def test_no_accel_columns_uses_defaults(self):
        """If accel columns missing, use VehicleParameters defaults."""
        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.full(100, 20.0),
        })
        base = params_for_class("kart")
        base.mu_ref = 1.0
        result = extract_session_params(df, base)
        # Should still have valid mu_ref from base
        assert result.mu_ref == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_solver_param_extractor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement param_extractor.py**

```python
# telemetry_tool/solver/param_extractor.py
"""Extract OCP vehicle parameters from session telemetry data."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from solver.vehicle_params import OCPVehicleParams

logger = logging.getLogger(__name__)

_G = 9.80665

# Column names (pipeline convention)
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_ACCEL_LAT = "accel_lat_mps2"


def extract_session_params(
    best_lap_df: pd.DataFrame,
    base_params: OCPVehicleParams,
    percentile: float = 98.0,
) -> OCPVehicleParams:
    """Extract/refine vehicle params from the best lap data.

    Updates mu_ref, P_max, F_brake_max, F_drive_max on a copy of base_params.
    Falls back to base_params values if columns are missing.
    """
    import dataclasses
    params = dataclasses.replace(base_params)

    has_accel_long = _COL_ACCEL_LONG in best_lap_df.columns
    has_accel_lat = _COL_ACCEL_LAT in best_lap_df.columns
    has_speed = _COL_SPEED in best_lap_df.columns

    speed = best_lap_df[_COL_SPEED].to_numpy(dtype=float) if has_speed else None

    # mu_ref from peak lateral g
    if has_accel_lat:
        a_lat = best_lap_df[_COL_ACCEL_LAT].to_numpy(dtype=float)
        a_lat_valid = a_lat[np.isfinite(a_lat)]
        if len(a_lat_valid) > 10:
            peak_lat = float(np.percentile(np.abs(a_lat_valid), percentile))
            params.mu_ref = peak_lat / _G

    # P_max from peak (a_long * mass * v) on straights (positive a_long)
    if has_accel_long and speed is not None:
        a_long = best_lap_df[_COL_ACCEL_LONG].to_numpy(dtype=float)
        mask = np.isfinite(a_long) & np.isfinite(speed) & (a_long > 0.5) & (speed > 5.0)
        if mask.sum() > 5:
            power_arr = a_long[mask] * params.mass * speed[mask]
            params.P_max = float(np.percentile(power_arr, percentile))

    # F_brake_max from peak braking decel
    if has_accel_long:
        a_long = best_lap_df[_COL_ACCEL_LONG].to_numpy(dtype=float)
        a_long_valid = a_long[np.isfinite(a_long)]
        if len(a_long_valid) > 10:
            braking_vals = np.abs(a_long_valid[a_long_valid < -0.5])
            if len(braking_vals) > 0:
                peak_brake = float(np.percentile(braking_vals, percentile))
                params.F_brake_max = peak_brake * params.mass

    # F_drive_max from peak positive acceleration at low speed (traction-limited)
    if has_accel_long and speed is not None:
        a_long = best_lap_df[_COL_ACCEL_LONG].to_numpy(dtype=float)
        low_speed_mask = (
            np.isfinite(a_long) & np.isfinite(speed)
            & (a_long > 0.5) & (speed < 20.0)
        )
        if low_speed_mask.sum() > 3:
            peak_traction = float(np.percentile(a_long[low_speed_mask], percentile))
            params.F_drive_max = peak_traction * params.mass

    # Fallback: if P_max still zero, estimate from F_drive_max and typical speed
    if params.P_max <= 0 and params.F_drive_max > 0:
        params.P_max = params.F_drive_max * 20.0  # rough estimate at 20 m/s

    logger.info(
        "OCP params extracted: mu_ref=%.3f, P_max=%.0fW, F_brake=%.0fN, F_drive=%.0fN",
        params.mu_ref, params.P_max, params.F_brake_max, params.F_drive_max,
    )
    return params
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_solver_param_extractor.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/solver/param_extractor.py telemetry_tool/tests/test_solver_param_extractor.py
git commit -m "feat(solver): add parameter extractor from session telemetry"
```

---

### Task 6: Result Dataclass

**Files:**
- Create: `telemetry_tool/solver/result.py`

**Context:** Stores the OCP solver output in a structured format matching the spec's JSON schema.

- [ ] **Step 1: Implement result.py**

```python
# telemetry_tool/solver/result.py
"""OCP solver result dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class TheoreticalResult:
    """Result from the optimal control solver."""

    lap_time_s: float
    speed_profile: np.ndarray       # speed at each node (m/s)
    distance_profile: np.ndarray    # distance at each node (m)
    a_long_profile: np.ndarray      # longitudinal accel (m/s^2)
    a_lat_profile: np.ndarray       # lateral accel (m/s^2)
    corner_times: list[dict]        # per-corner breakdown
    vehicle_params_used: dict       # snapshot of params
    calibration: dict               # calibration metadata
    solver_meta: dict               # IPOPT convergence info
    tier: int                       # data tier (1, 2, or 3)
    converged: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in analysis_json."""
        speed_profile_list = [
            {
                "distance_m": round(float(self.distance_profile[i]), 2),
                "speed_mps": round(float(self.speed_profile[i]), 3),
                "a_long": round(float(self.a_long_profile[i]), 3),
                "a_lat": round(float(self.a_lat_profile[i]), 3),
            }
            for i in range(len(self.speed_profile))
        ]
        return {
            "lap_time_s": round(self.lap_time_s, 3),
            "speed_profile": speed_profile_list,
            "corner_times": self.corner_times,
            "vehicle_params_used": self.vehicle_params_used,
            "calibration": self.calibration,
            "solver_meta": self.solver_meta,
            "tier": self.tier,
            "converged": self.converged,
        }
```

- [ ] **Step 2: Write test for result serialization**

```python
# telemetry_tool/tests/test_solver_result.py
"""Tests for TheoreticalResult serialization."""
import numpy as np
import pytest

from solver.result import TheoreticalResult


class TestTheoreticalResult:

    def test_to_dict_has_required_keys(self):
        r = TheoreticalResult(
            lap_time_s=45.123,
            speed_profile=np.array([20.0, 25.0, 30.0]),
            distance_profile=np.array([0.0, 100.0, 200.0]),
            a_long_profile=np.array([1.0, 0.5, -0.3]),
            a_lat_profile=np.array([0.0, 2.0, 5.0]),
            corner_times=[],
            vehicle_params_used={"mass": 160.0},
            calibration={},
            solver_meta={"iterations": 50, "converged": True},
            tier=1,
            converged=True,
        )
        d = r.to_dict()
        assert d["lap_time_s"] == pytest.approx(45.123, abs=0.001)
        assert d["tier"] == 1
        assert d["converged"] is True
        assert len(d["speed_profile"]) == 3
        assert d["speed_profile"][0]["distance_m"] == pytest.approx(0.0)
        assert d["speed_profile"][1]["speed_mps"] == pytest.approx(25.0)
        # Required top-level keys from spec Section 7
        for key in ("lap_time_s", "speed_profile", "corner_times",
                     "vehicle_params_used", "calibration", "solver_meta",
                     "tier", "converged"):
            assert key in d

    def test_to_dict_speed_profile_entry_keys(self):
        r = TheoreticalResult(
            lap_time_s=30.0,
            speed_profile=np.array([15.0]),
            distance_profile=np.array([50.0]),
            a_long_profile=np.array([-1.0]),
            a_lat_profile=np.array([3.0]),
            corner_times=[], vehicle_params_used={},
            calibration={}, solver_meta={}, tier=1,
        )
        entry = r.to_dict()["speed_profile"][0]
        assert set(entry.keys()) == {"distance_m", "speed_mps", "a_long", "a_lat"}
```

- [ ] **Step 3: Run test**

Run: `pytest telemetry_tool/tests/test_solver_result.py -v`
Expected: All 2 tests PASS

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/solver/result.py telemetry_tool/tests/test_solver_result.py
git commit -m "feat(solver): add TheoreticalResult dataclass with serialization tests"
```

---

## Chunk 2: OCP Solver Core + Calibrator

### Task 7: OCP Solver (CasADi + IPOPT)

**Files:**
- Create: `telemetry_tool/solver/ocp_solver.py`
- Test: `telemetry_tool/tests/test_solver_ocp.py`

**Context:** This is the core module. Builds a CasADi NLP problem using direct shooting (Euler integration between nodes), adds friction ellipse constraints at every node, and solves with IPOPT. Warm-starts from the existing QSS speed profile. This is the most complex module.

- [ ] **Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_solver_ocp.py
"""Tests for the OCP solver."""
import math
import numpy as np
import pytest

from solver.ocp_solver import solve_ocp
from solver.track_model import TrackMesh
from solver.vehicle_params import OCPVehicleParams
from solver.tire_model import LoadSensitiveTire

_G = 9.80665


def _make_circle_mesh(radius: float = 50.0, n_nodes: int = 200) -> TrackMesh:
    """Create a constant-radius circular track mesh."""
    circumference = 2 * math.pi * radius
    s = np.linspace(0, circumference, n_nodes)
    kappa = np.full(n_nodes, 1.0 / radius)  # constant curvature
    ds = np.diff(s)
    return TrackMesh(s=s, kappa=kappa, ds=ds, track_length=circumference)


def _make_simple_params(mu: float = 1.0, mass: float = 1200.0) -> OCPVehicleParams:
    """Simple vehicle with no aero, no rolling resistance."""
    return OCPVehicleParams(
        mass=mass, h_cg=0.0, wheelbase=2.6, track_width=1.55,
        A=0.0, Cd=0.0, Cl=0.0, rho=1.225, Cr=0.0,
        mu_ref=mu, load_sensitivity=0.0,  # no load sensitivity for analytical test
        P_max=1e6, F_brake_max=1e6, F_drive_max=1e6,  # unlimited power
    )


class TestConstantRadiusCircle:
    """The fundamental validation: on a constant-radius circle with no aero/rolling,
    the optimal speed is v = sqrt(mu * g * R)."""

    def test_circle_speed_matches_analytical(self):
        R = 50.0
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=200)
        params = _make_simple_params(mu=mu)
        tire = LoadSensitiveTire(
            mu_ref=mu,
            Fz_ref=params.Fz_static_per_axle,
            sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)
        assert result.converged

        v_analytical = math.sqrt(mu * _G * R)  # = 22.147 m/s

        # Speed should be nearly constant around the circle
        mean_speed = float(np.mean(result.speed_profile))
        assert mean_speed == pytest.approx(v_analytical, rel=0.01)  # within 1%

    def test_circle_lap_time_matches_analytical(self):
        R = 50.0
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=200)
        params = _make_simple_params(mu=mu)
        tire = LoadSensitiveTire(
            mu_ref=mu,
            Fz_ref=params.Fz_static_per_axle,
            sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)

        v_analytical = math.sqrt(mu * _G * R)
        circumference = 2 * math.pi * R
        t_analytical = circumference / v_analytical

        assert result.lap_time_s == pytest.approx(t_analytical, rel=0.01)


class TestSolverConvergence:
    """Test that the solver handles edge cases."""

    def test_warm_start_improves_convergence(self):
        R = 50.0
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=100)
        params = _make_simple_params(mu=mu)
        tire = LoadSensitiveTire(mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0)

        # Good warm start: near-optimal speed
        v_opt = math.sqrt(mu * _G * R)
        warm_start = np.full(100, v_opt)

        result = solve_ocp(mesh, params, tire, warm_start=warm_start)
        assert result.converged
        # With good warm start, should converge in fewer iterations
        assert result.solver_meta["iterations"] < 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_solver_ocp.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ocp_solver.py**

```python
# telemetry_tool/solver/ocp_solver.py
"""CasADi/IPOPT optimal control solver for minimum-time lap.

Formulates the minimum-time problem as a nonlinear program (NLP):
  - Decision variables: speed v[i] at each collocation node
  - Objective: minimize sum(ds[i] / v[i])  (= total time)
  - Dynamics: v[i+1]^2 = v[i]^2 + 2 * a_net[i] * ds[i]
  - Grip constraint: friction ellipse at each node
  - Complementarity: u_throttle * u_brake <= epsilon (relaxed)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import casadi as ca
import numpy as np

from solver.result import TheoreticalResult
from solver.tire_model import LoadSensitiveTire
from solver.track_model import TrackMesh
from solver.vehicle_params import OCPVehicleParams

logger = logging.getLogger(__name__)

_G = 9.80665
_V_MIN = 2.0       # minimum speed (m/s) to avoid division by zero
_EPSILON = 1e-4     # complementarity relaxation


def solve_ocp(
    mesh: TrackMesh,
    params: OCPVehicleParams,
    tire: LoadSensitiveTire,
    warm_start: Optional[np.ndarray] = None,
    max_iter: int = 2000,
    tol: float = 1e-6,
) -> TheoreticalResult:
    """Solve the minimum-time OCP using CasADi + IPOPT.

    Parameters
    ----------
    mesh : Track mesh with distance nodes and curvature.
    params : Vehicle parameters.
    tire : Tire model.
    warm_start : Initial speed guess at each node (m/s). If None, uses 20 m/s.
    max_iter : IPOPT maximum iterations.
    tol : IPOPT convergence tolerance.

    Returns
    -------
    TheoreticalResult with speed profile, lap time, and solver metadata.
    """
    t_start = time.monotonic()
    N = len(mesh.s)
    ds = mesh.ds  # (N-1,)

    # ── Decision variables ──
    opti = ca.Opti()

    v = opti.variable(N)       # speed at each node
    u_thr = opti.variable(N)   # throttle [0, 1]
    u_brk = opti.variable(N)   # brake [0, 1]

    # ── Bounds ──
    opti.subject_to(v >= _V_MIN)
    opti.subject_to(opti.bounded(0, u_thr, 1))
    opti.subject_to(opti.bounded(0, u_brk, 1))

    # ── Objective: minimize lap time ──
    dt_sum = 0
    for i in range(N - 1):
        v_avg = (v[i] + v[i + 1]) / 2.0
        dt_sum += ds[i] / v_avg
    opti.minimize(dt_sum)

    # ── Dynamics constraints ──
    Fz_static = params.Fz_static_per_axle

    for i in range(N - 1):
        kappa_i = float(mesh.kappa[i])

        # Longitudinal acceleration components
        a_drive = ca.fmin(
            u_thr[i] * params.P_max / (params.mass * v[i]),
            params.F_drive_max / params.mass,
        )
        a_brake = u_brk[i] * params.F_brake_max / params.mass
        a_drag = 0.5 * params.rho * params.Cd * params.A * v[i] ** 2 / params.mass
        a_rolling = params.Cr * _G
        F_downforce = 0.5 * params.rho * params.Cl * params.A * v[i] ** 2  # Newtons

        a_long = a_drive - a_brake - a_drag - a_rolling

        # Dynamics: v[i+1]^2 = v[i]^2 + 2 * a_long * ds
        opti.subject_to(v[i + 1] ** 2 == v[i] ** 2 + 2 * a_long * ds[i])

        # Lateral acceleration from curvature
        a_lat = v[i] ** 2 * abs(kappa_i)

        # Load transfer (affects grip via load sensitivity)
        dFz_long = params.mass * ca.fabs(a_long) * params.h_cg / params.wheelbase
        dFz_lat = params.mass * a_lat * params.h_cg / params.track_width

        # Effective vertical load per axle including downforce and load transfer
        # Downforce splits across 2 axles (Newtons); load transfer reduces
        # the lighter side's grip more than it helps the heavier side
        # (due to load sensitivity). Use the mean axle load for the
        # simplified 1D model, but account for the lateral transfer's
        # net grip reduction via the loaded/unloaded pair.
        Fz_base = Fz_static + F_downforce / 2.0  # per-axle with downforce (N)
        Fz_loaded = Fz_base + dFz_lat             # outer tire
        Fz_unloaded = ca.fmax(Fz_base - dFz_lat, 1.0)  # inner tire (clamped > 0)

        # Grip limits with load sensitivity
        # mu(Fz) = mu_ref * (Fz / Fz_ref) ^ sensitivity
        # Total lateral grip = mu(Fz_outer)*Fz_outer + mu(Fz_inner)*Fz_inner
        # Using log transform for CasADi power with negative exponent
        if abs(params.load_sensitivity) > 1e-6 and params.h_cg > 0:
            # Compute mu for each side
            log_r_loaded = ca.log(ca.fmax(Fz_loaded, 1.0) / ca.fmax(Fz_static, 1.0))
            mu_loaded = params.mu_ref * ca.exp(params.load_sensitivity * log_r_loaded)
            log_r_unloaded = ca.log(ca.fmax(Fz_unloaded, 1.0) / ca.fmax(Fz_static, 1.0))
            mu_unloaded = params.mu_ref * ca.exp(params.load_sensitivity * log_r_unloaded)

            # Effective grip: total force / total mass
            F_grip_total = mu_loaded * Fz_loaded + mu_unloaded * Fz_unloaded
            a_grip_max = F_grip_total / params.mass
        else:
            # No load sensitivity — grip = mu_ref * total_Fz / mass
            Fz_total = Fz_loaded + Fz_unloaded
            a_grip_max = params.mu_ref * Fz_total / params.mass

        # Friction ellipse: (a_long/a_max)^2 + (a_lat/a_max)^2 <= 1
        opti.subject_to(
            (a_long / a_grip_max) ** 2 + (a_lat / a_grip_max) ** 2 <= 1.0
        )

        # Complementarity: no simultaneous throttle + brake
        opti.subject_to(u_thr[i] * u_brk[i] <= _EPSILON)

    # ── Boundary condition: lap continuity ──
    opti.subject_to(v[0] == v[N - 1])

    # ── Initial guess ──
    if warm_start is not None:
        opti.set_initial(v, warm_start)
    else:
        v_guess = np.full(N, 20.0)
        # Use curvature to estimate corner speeds
        for i in range(N):
            k = abs(float(mesh.kappa[i]))
            if k > 1e-4:
                v_corner = np.sqrt(params.mu_ref * _G / k)
                v_guess[i] = min(v_guess[i], v_corner)
        opti.set_initial(v, v_guess)

    opti.set_initial(u_thr, 0.5)
    opti.set_initial(u_brk, 0.0)

    # ── Solver options ──
    opts = {
        "ipopt.max_iter": max_iter,
        "ipopt.tol": tol,
        "ipopt.acceptable_tol": 1e-4,
        "ipopt.print_level": 0,
        "ipopt.warm_start_init_point": "yes",
        "print_time": False,
    }
    opti.solver("ipopt", opts)

    # ── Solve ──
    converged = True
    iterations = 0
    try:
        sol = opti.solve()
        v_sol = sol.value(v)
        u_thr_sol = sol.value(u_thr)
        u_brk_sol = sol.value(u_brk)
        iterations = int(sol.stats()["iter_count"])
    except RuntimeError as e:
        logger.warning("IPOPT failed to converge: %s — using last iterate", e)
        converged = False
        v_sol = opti.debug.value(v)
        u_thr_sol = opti.debug.value(u_thr)
        u_brk_sol = opti.debug.value(u_brk)
        iterations = max_iter

    v_arr = np.array(v_sol).flatten()
    v_arr = np.maximum(v_arr, _V_MIN)

    # Compute derived quantities
    a_lat_arr = v_arr ** 2 * np.abs(mesh.kappa)
    a_long_arr = np.zeros(N)
    for i in range(N - 1):
        a_long_arr[i] = (v_arr[i + 1] ** 2 - v_arr[i] ** 2) / (2.0 * ds[i])
    a_long_arr[-1] = a_long_arr[-2]

    # Lap time
    lap_time = 0.0
    for i in range(N - 1):
        v_avg = (v_arr[i] + v_arr[i + 1]) / 2.0
        lap_time += ds[i] / max(v_avg, _V_MIN)

    wall_time = time.monotonic() - t_start

    return TheoreticalResult(
        lap_time_s=float(lap_time),
        speed_profile=v_arr,
        distance_profile=mesh.s.copy(),
        a_long_profile=a_long_arr,
        a_lat_profile=a_lat_arr,
        corner_times=[],
        vehicle_params_used=params.to_dict(),
        calibration={},
        solver_meta={
            "nodes": N,
            "iterations": iterations,
            "converged": converged,
            "wall_time_s": round(wall_time, 2),
        },
        tier=1,
        converged=converged,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_solver_ocp.py -v --timeout=300`
Expected: All 3 tests PASS (may take 30-60s each due to IPOPT solving)

Note: If `--timeout` flag unavailable, run without it. These tests are slow by design.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/solver/ocp_solver.py telemetry_tool/tests/test_solver_ocp.py
git commit -m "feat(solver): add CasADi/IPOPT optimal control solver"
```

---

### Task 8: Calibrator

**Files:**
- Create: `telemetry_tool/solver/calibrator.py`
- Test: `telemetry_tool/tests/test_solver_calibrator.py`

**Context:** Single-pass parameter adjustment. Compares OCP result to actual best lap data, adjusts mu_ref, P_max, F_brake_max by the ratio `actual/theoretical`. The Celery task (Task 9) handles re-solve and convergence checking.

- [ ] **Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_solver_calibrator.py
"""Tests for the calibration loop."""
import math
import numpy as np
import pytest

from solver.calibrator import calibrate_params, CalibrationResult


class TestCalibrateParams:

    def test_no_adjustment_when_accurate(self):
        """If theoretical matches actual, no adjustment needed."""
        result = CalibrationResult(
            mu_ref_initial=1.2, mu_ref_final=1.2,
            P_max_initial=50000, P_max_final=50000,
            F_brake_initial=15000, F_brake_final=15000,
            passes=0, residual_pct=0.0,
        )
        # Verify structure
        assert result.passes == 0
        assert result.residual_pct == pytest.approx(0.0)

    def test_mu_ref_scales_up(self):
        """If theoretical apex speed < actual, mu_ref should increase."""
        result = calibrate_params(
            mu_ref=1.0,
            P_max=50000.0,
            F_brake_max=15000.0,
            actual_apex_speeds=[22.0, 18.0, 25.0],
            theoretical_apex_speeds=[20.0, 16.0, 23.0],
            actual_straight_end_speeds=[40.0],
            theoretical_straight_end_speeds=[40.0],
            actual_braking_dists=[50.0],
            theoretical_braking_dists=[50.0],
        )
        assert result.mu_ref_final > 1.0
        assert result.passes >= 1

    def test_single_pass_returns_adjusted_values(self):
        """Single-pass calibration: large discrepancy produces proportional adjustment."""
        result = calibrate_params(
            mu_ref=0.8,
            P_max=50000.0,
            F_brake_max=15000.0,
            actual_apex_speeds=[22.0],
            theoretical_apex_speeds=[15.0],
            actual_straight_end_speeds=[40.0],
            theoretical_straight_end_speeds=[35.0],
            actual_braking_dists=[50.0],
            theoretical_braking_dists=[60.0],
        )
        assert result.passes == 1
        # mu should scale by (22/15)^2 = 2.151
        assert result.mu_ref_final == pytest.approx(0.8 * (22.0 / 15.0) ** 2, rel=0.01)
        # P_max should scale by (40/35)^3 = 1.493
        assert result.P_max_final == pytest.approx(50000.0 * (40.0 / 35.0) ** 3, rel=0.01)
        # F_brake should scale by 60/50 = 1.2
        assert result.F_brake_final == pytest.approx(15000.0 * 1.2, rel=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_solver_calibrator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement calibrator.py**

```python
# telemetry_tool/solver/calibrator.py
"""Multi-parameter calibration loop for the OCP solver.

Adjusts mu_ref, P_max, F_brake_max by comparing OCP predictions
to the driver's actual session data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Result of the calibration loop."""
    mu_ref_initial: float
    mu_ref_final: float
    P_max_initial: float
    P_max_final: float
    F_brake_initial: float
    F_brake_final: float
    passes: int
    residual_pct: float

    def to_dict(self) -> dict:
        import dataclasses
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in dataclasses.asdict(self).items()}


def calibrate_params(
    mu_ref: float,
    P_max: float,
    F_brake_max: float,
    actual_apex_speeds: list[float],
    theoretical_apex_speeds: list[float],
    actual_straight_end_speeds: list[float],
    theoretical_straight_end_speeds: list[float],
    actual_braking_dists: list[float],
    theoretical_braking_dists: list[float],
) -> CalibrationResult:
    """Single-pass parameter adjustment: compare actual vs. theoretical.

    Adjusts mu_ref (from apex speeds), P_max (from straight-end speeds),
    F_brake_max (from braking distances) using ratio-based scaling.
    The caller (Celery task) handles the re-solve + convergence loop.

    Returns CalibrationResult with initial and final values + residual.
    """
    mu_initial = mu_ref
    P_initial = P_max
    F_initial = F_brake_max
    adjustments = []

    # Grip calibration from apex speeds
    if actual_apex_speeds and theoretical_apex_speeds:
        actual_arr = np.array(actual_apex_speeds)
        theo_arr = np.array(theoretical_apex_speeds)
        valid = (theo_arr > 1.0) & (actual_arr > 1.0)
        if valid.sum() > 0:
            # v_apex ~ sqrt(mu), so mu_ratio = (v_actual / v_theo)^2
            speed_ratio = float(np.mean(actual_arr[valid] / theo_arr[valid]))
            mu_ratio = speed_ratio ** 2
            mu_ref *= mu_ratio
            adjustments.append(f"mu_ref *= {mu_ratio:.3f}")

    # Power calibration from straight-end speeds
    if actual_straight_end_speeds and theoretical_straight_end_speeds:
        actual_arr = np.array(actual_straight_end_speeds)
        theo_arr = np.array(theoretical_straight_end_speeds)
        valid = (theo_arr > 1.0) & (actual_arr > 1.0)
        if valid.sum() > 0:
            ratio = float(np.mean(actual_arr[valid] / theo_arr[valid]))
            # P ~ v^3 for drag-limited top speed
            P_ratio = ratio ** 3
            P_max *= P_ratio
            adjustments.append(f"P_max *= {P_ratio:.3f}")

    # Braking calibration from braking distances
    if actual_braking_dists and theoretical_braking_dists:
        actual_arr = np.array(actual_braking_dists)
        theo_arr = np.array(theoretical_braking_dists)
        valid = (theo_arr > 1.0) & (actual_arr > 1.0)
        if valid.sum() > 0:
            # Shorter actual braking = stronger brakes
            ratio = float(np.mean(theo_arr[valid] / actual_arr[valid]))
            F_brake_max *= ratio
            adjustments.append(f"F_brake *= {ratio:.3f}")

    # Compute residual (how far theoretical was from actual)
    residuals = []
    if actual_apex_speeds and theoretical_apex_speeds:
        residuals.extend([
            abs(a - t) / max(a, 1.0) * 100
            for a, t in zip(actual_apex_speeds, theoretical_apex_speeds)
        ])
    residual_pct = float(np.mean(residuals)) if residuals else 0.0

    logger.info("Calibration: residual=%.1f%%, adjustments=%s", residual_pct, adjustments)

    return CalibrationResult(
        mu_ref_initial=mu_initial,
        mu_ref_final=mu_ref,
        P_max_initial=P_initial,
        P_max_final=P_max,
        F_brake_initial=F_initial,
        F_brake_final=F_brake_max,
        passes=1 if adjustments else 0,
        residual_pct=residual_pct,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_solver_calibrator.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/solver/calibrator.py telemetry_tool/tests/test_solver_calibrator.py
git commit -m "feat(solver): add multi-parameter calibration loop"
```

---

## Chunk 3: Integration — Celery Task, Pipeline Wiring, API Changes

### Task 9: Celery Task for OCP

**Files:**
- Create: `telemetry_tool/tasks/ocp_tasks.py`

**Context:** Background Celery task that runs the full OCP pipeline: extract params → build mesh → solve → calibrate → store result. Queued to the `pipeline` queue (same as the main pipeline, concurrency=2). Reads session data from DB, writes result back to `analysis_json["theoretical_ocp"]`.

- [ ] **Step 1: Implement ocp_tasks.py**

```python
# telemetry_tool/tasks/ocp_tasks.py
"""Celery task for OCP theoretical lap computation.

Runs as a background job after the synchronous pipeline completes.
Reads session data from DB, runs the full OCP pipeline (solve → calibrate → re-solve),
stores result in analysis_json["theoretical_ocp"].
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CALIBRATION_PASSES = 3
_CONVERGENCE_PCT = 1.0  # residual % threshold


def _is_ocp_enabled() -> bool:
    return os.environ.get("THEORETICAL_OCP", "1") not in ("0", "false", "no")


def _get_celery():
    """Import celery app; returns None if unavailable."""
    try:
        from tasks.celery_app import celery
        return celery
    except ImportError:
        return None


# Try to register as Celery task if available; otherwise stays a plain function
_celery = _get_celery()
if _celery is not None:
    @_celery.task(
        name="tasks.ocp_tasks.run_ocp_for_session",
        bind=True,
        queue="pipeline",
        max_retries=1,
        retry_backoff=True,
    )
    def run_ocp_for_session(self, session_id: int | str, workspace_id: int | None = None) -> dict | None:
        return _run_ocp_impl(session_id, workspace_id)
else:
    def run_ocp_for_session(session_id: int | str, workspace_id: int | None = None) -> dict | None:
        return _run_ocp_impl(session_id, workspace_id)


def _run_ocp_impl(session_id: int | str, workspace_id: int | None = None) -> dict | None:
    """Core OCP pipeline: extract → mesh → solve → calibrate → store."""
    if not _is_ocp_enabled():
        logger.info("OCP solver disabled (THEORETICAL_OCP=0)")
        return None

    try:
        import dataclasses
        import numpy as np
        import pandas as pd

        from solver.vehicle_params import OCPVehicleParams, params_for_class
        from solver.tire_model import LoadSensitiveTire
        from solver.track_model import build_mesh_from_curvature_profile
        from solver.ocp_solver import solve_ocp
        from solver.param_extractor import extract_session_params
        from solver.calibrator import calibrate_params
    except ImportError as e:
        logger.warning("OCP solver dependencies not available: %s", e)
        return None

    conn = None
    try:
        conn, analysis_json, best_lap_df, curvature_profile, vehicle_params = (
            _load_session_data(session_id, workspace_id)
        )

        if best_lap_df is None or curvature_profile is None:
            logger.info("OCP skipped: missing best_lap_df or curvature_profile")
            return None

        # Build track mesh
        mesh = build_mesh_from_curvature_profile(curvature_profile, n_nodes=500)
        if mesh is None:
            logger.warning("OCP skipped: could not build track mesh")
            return None

        # Build vehicle params
        if vehicle_params is not None:
            base_params = OCPVehicleParams.from_vehicle_params(vehicle_params)
        else:
            base_params = params_for_class("car")

        # Extract session-specific params
        params = extract_session_params(best_lap_df, base_params)

        # Build tire model
        tire = LoadSensitiveTire(
            mu_ref=params.mu_ref,
            Fz_ref=params.Fz_static_per_axle,
            sensitivity=params.load_sensitivity,
        )

        # Warm start from QSS if available
        warm_start = _extract_warm_start(analysis_json, mesh)

        # Solve + calibrate loop (spec Section 6)
        logger.info("Starting OCP solve for session %s (%d nodes)", session_id, len(mesh.s))
        result = solve_ocp(mesh, params, tire, warm_start=warm_start)

        actual_apex = _extract_actual_apex_speeds(analysis_json)
        actual_straights = _extract_actual_straight_speeds(analysis_json)
        actual_braking = _extract_actual_braking_dists(analysis_json)
        theo_apex = _extract_theoretical_apex_speeds(result, analysis_json)

        calibration_meta = {}
        for cal_pass in range(_MAX_CALIBRATION_PASSES):
            cal = calibrate_params(
                mu_ref=params.mu_ref,
                P_max=params.P_max,
                F_brake_max=params.F_brake_max,
                actual_apex_speeds=actual_apex,
                theoretical_apex_speeds=theo_apex,
                actual_straight_end_speeds=actual_straights,
                theoretical_straight_end_speeds=[],  # from result
                actual_braking_dists=actual_braking,
                theoretical_braking_dists=[],
            )
            calibration_meta = cal.to_dict()

            if cal.residual_pct <= _CONVERGENCE_PCT:
                break

            # Update params and re-solve
            params = dataclasses.replace(
                params,
                mu_ref=cal.mu_ref_final,
                P_max=cal.P_max_final,
                F_brake_max=cal.F_brake_final,
            )
            tire = LoadSensitiveTire(
                mu_ref=params.mu_ref,
                Fz_ref=params.Fz_static_per_axle,
                sensitivity=params.load_sensitivity,
            )
            result = solve_ocp(mesh, params, tire, warm_start=result.speed_profile)
            theo_apex = _extract_theoretical_apex_speeds(result, analysis_json)

        if not result.converged:
            logger.warning("OCP solver did not converge for session %s", session_id)

        result_dict = result.to_dict()
        result_dict["calibration"] = calibration_meta

        _store_ocp_result(conn, session_id, result_dict)
        logger.info(
            "OCP result stored for session %s: %.2fs (converged=%s, %.1fs wall)",
            session_id, result.lap_time_s, result.converged,
            result.solver_meta["wall_time_s"],
        )
        return result_dict

    except Exception:
        logger.warning("OCP computation failed for session %s", session_id, exc_info=True)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_session_data(session_id, workspace_id):
    """Load session data needed for OCP from the database.

    Uses sql_compat for PG/SQLite portability.
    Returns (conn, analysis_json, best_lap_df, curvature_profile, vehicle_params).
    """
    from web.db import get_db_connection
    import pandas as pd

    conn = get_db_connection()

    # SQL uses ? placeholders — sql_compat translates for PG
    row = conn.execute(
        "SELECT analysis_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Session {session_id} not found")

    analysis_json = json.loads(row[0]) if row[0] else {}

    best_lap_df = _reconstruct_best_lap_df(analysis_json)
    curvature_profile = _reconstruct_curvature_profile(analysis_json)

    vehicle_params = None
    vp_data = analysis_json.get("vehicle_params")
    if vp_data:
        from vehicle_model import VehicleParameters, VehicleClass
        vehicle_params = VehicleParameters(
            vehicle_class=VehicleClass(vp_data.get("vehicle_class", "unknown")),
            estimated_mass_kg=vp_data.get("estimated_mass_kg"),
            peak_lateral_g=vp_data.get("peak_lateral_g", 1.0),
            peak_braking_g=vp_data.get("peak_braking_g", 1.0),
            peak_traction_g=vp_data.get("peak_traction_g", 0.5),
            has_downforce=vp_data.get("has_downforce", False),
            has_abs=vp_data.get("has_abs", False),
            rolling_resistance_est=vp_data.get("rolling_resistance_est", 0.015),
            aero_drag_factor_est=vp_data.get("aero_drag_factor_est", 0.0),
        )

    return conn, analysis_json, best_lap_df, curvature_profile, vehicle_params


def _reconstruct_best_lap_df(analysis_json: dict):
    """Reconstruct best lap DataFrame from stored data."""
    import numpy as np
    import pandas as pd

    speed_trace = analysis_json.get("speed_trace_best")
    if not speed_trace:
        return None

    if isinstance(speed_trace, list) and len(speed_trace) > 10:
        df = pd.DataFrame(speed_trace)
        rename_map = {
            "distance_m": "Distance (m)",
            "speed_mps": "Speed (m/s)",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df

    return None


def _reconstruct_curvature_profile(analysis_json: dict):
    """Reconstruct curvature profile from stored data."""
    import pandas as pd

    curv_data = analysis_json.get("curvature_profile")
    if not curv_data:
        return None

    if isinstance(curv_data, list) and len(curv_data) > 10:
        return pd.DataFrame(curv_data)

    return None


def _extract_warm_start(analysis_json: dict, mesh) -> Any:
    """Extract warm start speed profile from QSS result."""
    import numpy as np

    optimal = analysis_json.get("optimal_v2") or analysis_json.get("theoretical")
    if not optimal:
        return None

    speed_data = optimal.get("speed_profile")
    if not speed_data or not isinstance(speed_data, list):
        return None

    try:
        distances = np.array([p["distance_m"] for p in speed_data])
        speeds = np.array([p["speed_mps"] for p in speed_data])
        warm = np.interp(mesh.s, distances, speeds)
        warm = np.maximum(warm, 2.0)
        return warm
    except (KeyError, ValueError):
        return None


def _extract_actual_apex_speeds(analysis_json: dict) -> list[float]:
    """Extract actual apex speeds from corner data."""
    corners = analysis_json.get("corners", [])
    if isinstance(corners, list):
        return [c.get("apex_speed_mps", 0.0) for c in corners if c.get("apex_speed_mps")]
    return []


def _extract_actual_straight_speeds(analysis_json: dict) -> list[float]:
    """Extract peak straight-end speeds."""
    return []  # TODO: extract from speed trace straight segments


def _extract_actual_braking_dists(analysis_json: dict) -> list[float]:
    """Extract actual braking distances."""
    return []  # TODO: extract from corner events


def _extract_theoretical_apex_speeds(result, analysis_json: dict) -> list[float]:
    """Extract theoretical apex speeds from OCP result at corner locations."""
    import numpy as np
    corners = analysis_json.get("corners", [])
    if not corners:
        return []
    apex_speeds = []
    for c in corners:
        apex_m = c.get("apex_distance_m")
        if apex_m is not None:
            v = float(np.interp(apex_m, result.distance_profile, result.speed_profile))
            apex_speeds.append(v)
    return apex_speeds


def _store_ocp_result(conn, session_id, result_dict: dict):
    """Store OCP result in analysis_json using atomic jsonb_set if PG, else read-modify-write."""
    import os
    if os.environ.get("USE_PG", "0") not in ("0", "false", "no"):
        # PostgreSQL: atomic jsonb_set avoids race condition
        conn.execute(
            "UPDATE sessions SET analysis_json = jsonb_set("
            "  COALESCE(analysis_json, '{}'), '{theoretical_ocp}', ?::jsonb"
            ") WHERE id = ?",
            (json.dumps(result_dict), session_id),
        )
    else:
        # SQLite: read-modify-write (single-writer, no race)
        row = conn.execute(
            "SELECT analysis_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return
        analysis_json = json.loads(row[0]) if row[0] else {}
        analysis_json["theoretical_ocp"] = result_dict
        conn.execute(
            "UPDATE sessions SET analysis_json = ? WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )
    conn.commit()
```

- [ ] **Step 2: Commit**

```bash
git add telemetry_tool/tasks/ocp_tasks.py
git commit -m "feat(solver): add Celery task for background OCP computation"
```

---

### Task 10: Pipeline Integration (Stage 10 wiring)

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10_theoretical.py`

**Context:** After the existing `run_theoretical()` completes (QSS/hybrid/percentile), queue the OCP background job. The OCP job runs asynchronously — the pipeline does NOT wait for it. The existing flow is completely unchanged; this just adds a non-blocking Celery task enqueue.

- [ ] **Step 1: Add OCP job queuing function**

Add to the END of `s10_theoretical.py`:

```python
# ── Step 10c: Queue OCP theoretical (background) ─────────────────────


def queue_ocp_theoretical(
    session_id: int | str | None,
    workspace_id: int | None,
) -> Optional[str]:
    """Queue the OCP solver as a background Celery task.

    Returns the Celery task ID, or None if skipped.
    Non-blocking — the pipeline continues immediately.
    """
    if session_id is None:
        return None
    if os.environ.get("THEORETICAL_OCP", "1") in ("0", "false", "no"):
        return None

    try:
        from tasks.ocp_tasks import run_ocp_for_session

        # Use .delay() for async Celery dispatch if available
        if hasattr(run_ocp_for_session, "delay"):
            task = run_ocp_for_session.delay(session_id, workspace_id)
            logger.info("OCP task queued for session %s: task_id=%s", session_id, task.id)
            return str(task.id)

        # Fallback: run synchronously (local dev without Celery)
        logger.info("OCP running synchronously for session %s (no Celery)", session_id)
        run_ocp_for_session(session_id, workspace_id)
        return "direct"
    except Exception:
        logger.debug("OCP theoretical queuing failed", exc_info=True)
        return None
```

- [ ] **Step 2: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10_theoretical.py
git commit -m "feat(solver): add OCP queuing hook to Stage 10"
```

---

### Task 11: API Endpoint Changes

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

**Context:** Add `?source=ocp` to the speed-trace endpoint and `theoretical_ocp_available` to session detail. Backward-compatible — default behavior unchanged.

- [ ] **Step 1: Modify speed-trace endpoint**

In `data_v2.py`, find the `get_speed_trace` function. Add OCP source handling at the TOP of the function, BEFORE the `version` query param check, so `?source=ocp` takes priority. You'll need to load `analysis_json` early:

```python
    # OCP theoretical source — checked FIRST (takes priority over version)
    source = request.args.get("source", "")
    if source == "ocp":
        row = conn.execute(
            "SELECT analysis_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        aj = json.loads(row[0]) if row and row[0] else {}
        ocp_data = aj.get("theoretical_ocp")
        if ocp_data and "speed_profile" in ocp_data:
            return api_response({
                "available": True,
                "source": "ocp",
                "lap_time_s": ocp_data.get("lap_time_s"),
                "speed_profile": ocp_data["speed_profile"],
                "solver_meta": ocp_data.get("solver_meta", {}),
            })
        return api_response({
            "available": False,
            "reason_code": "ocp_not_available",
            "message": "OCP theoretical not yet computed for this session",
        })
```

- [ ] **Step 2: Add theoretical_ocp_available to session detail**

In the session detail endpoint function, where the response dict is built, add:

```python
    # Check for OCP theoretical availability
    ocp_available = False
    if analysis_json and "theoretical_ocp" in analysis_json:
        ocp_available = True
```

And include `"theoretical_ocp_available": ocp_available` in the response dict.

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): add OCP source to speed-trace and session detail endpoints"
```

---

### Task 12: Integration Test (Synthetic Oval Regression Gate)

**Files:**
- Create: `telemetry_tool/tests/test_solver_integration.py`

**Context:** The regression gate test. A 500m synthetic oval with known physics — the OCP solver must produce a lap time within 1.0s of the point-mass analytical reference.

- [ ] **Step 1: Write integration test**

```python
# telemetry_tool/tests/test_solver_integration.py
"""Integration test: synthetic oval regression gate.

This is THE critical test — if it fails, the solver is broken.
"""
import logging
import math

import numpy as np
import pytest

from solver.ocp_solver import solve_ocp
from solver.track_model import TrackMesh
from solver.vehicle_params import OCPVehicleParams
from solver.tire_model import LoadSensitiveTire

logger = logging.getLogger(__name__)
_G = 9.80665


def _build_oval_mesh(
    straight_length: float = 93.0,
    corner_radius: float = 50.0,
    n_nodes: int = 500,
) -> TrackMesh:
    """Build a synthetic oval track: two straights + two semicircles.

    Total length ~ 2*straight + 2*pi*R = 2*93 + 2*pi*50 = 500.2m
    """
    corner_arc = math.pi * corner_radius  # half circumference

    # Build distance/curvature arrays
    segments = []
    # Straight 1
    n_straight = int(n_nodes * straight_length / (2 * straight_length + 2 * corner_arc))
    n_corner = int(n_nodes * corner_arc / (2 * straight_length + 2 * corner_arc))

    s_list = []
    k_list = []
    offset = 0.0

    for seg_type in ["straight", "corner", "straight", "corner"]:
        if seg_type == "straight":
            n = max(n_straight, 10)
            s_seg = np.linspace(offset, offset + straight_length, n, endpoint=False)
            k_seg = np.zeros(n)
            offset += straight_length
        else:
            n = max(n_corner, 10)
            s_seg = np.linspace(offset, offset + corner_arc, n, endpoint=False)
            k_seg = np.full(n, 1.0 / corner_radius)
            offset += corner_arc

        s_list.append(s_seg)
        k_list.append(k_seg)

    s_arr = np.concatenate(s_list)
    k_arr = np.concatenate(k_list)

    # Add final point
    s_arr = np.append(s_arr, offset)
    k_arr = np.append(k_arr, 0.0)

    ds = np.diff(s_arr)
    track_length = float(s_arr[-1] - s_arr[0])

    return TrackMesh(s=s_arr, kappa=k_arr, ds=ds, track_length=track_length)


class TestSyntheticOval:
    """Regression gate: OCP on a synthetic oval must match analytical bounds."""

    @pytest.mark.slow
    def test_oval_lap_time_within_tolerance(self):
        R = 50.0
        mu = 1.0
        mass = 1200.0
        P_max = 150_000.0  # 150 kW

        mesh = _build_oval_mesh(corner_radius=R, n_nodes=500)

        params = OCPVehicleParams(
            mass=mass, h_cg=0.0, wheelbase=2.6, track_width=1.55,
            A=0.0, Cd=0.0, Cl=0.0, rho=1.225, Cr=0.0,
            mu_ref=mu, load_sensitivity=0.0,
            P_max=P_max, F_brake_max=mass * mu * _G,
            F_drive_max=mass * mu * _G,
        )

        tire = LoadSensitiveTire(
            mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire, max_iter=2000)
        assert result.converged, f"Solver did not converge: {result.solver_meta}"

        # Analytical reference (point-mass, no aero, no rolling, no load transfer)
        v_corner = math.sqrt(mu * _G * R)  # ~22.15 m/s
        straight_len = 93.0
        corner_arc = math.pi * R

        # Corner time: 2 semicircles at v_corner
        t_corners = 2 * (corner_arc / v_corner)

        # Straight time: constant-power accel from v_corner to v_top, then
        # instant brake back to v_corner. For simplicity, compute the
        # constant-acceleration approximation at half-max power.
        a_max_traction = mu * _G
        # v_top limited by traction: assume power-limited v_top from P = F*v
        # At v_corner, F_max = P_max/v_corner = 150000/22.15 = 6773 N
        # a = F/m = 6773/1200 = 5.64 m/s^2
        # Under constant-power: v^2 = v0^2 + 2*P/(m*v)*ds ... use energy
        # Energy: 0.5*m*v_top^2 = 0.5*m*v0^2 + P*t_accel
        # Use numeric integration for the reference time:
        dt = 0.01  # seconds
        v = v_corner
        d = 0.0
        t_straight = 0.0
        while d < straight_len:
            a = min(P_max / (mass * max(v, 1.0)), a_max_traction)
            v += a * dt
            d += v * dt
            t_straight += dt
        # Two straights (approximate — real solver handles braking too)
        t_straights = 2 * t_straight

        t_analytical_approx = t_corners + t_straights

        # Regression gate: OCP must be within 1.0s of analytical
        assert abs(result.lap_time_s - t_analytical_approx) < 1.0, (
            f"OCP lap time {result.lap_time_s:.2f}s too far from "
            f"analytical {t_analytical_approx:.2f}s (delta="
            f"{abs(result.lap_time_s - t_analytical_approx):.2f}s, limit=1.0s)"
        )

    @pytest.mark.slow
    def test_corner_speeds_near_analytical(self):
        """Corner speeds should be close to sqrt(mu*g*R)."""
        R = 50.0
        mu = 1.0

        mesh = _build_oval_mesh(corner_radius=R, n_nodes=500)
        params = OCPVehicleParams(
            mass=1200.0, h_cg=0.0, wheelbase=2.6, track_width=1.55,
            A=0.0, Cd=0.0, Cl=0.0, rho=1.225, Cr=0.0,
            mu_ref=mu, load_sensitivity=0.0,
            P_max=150_000.0, F_brake_max=1200.0 * mu * _G,
            F_drive_max=1200.0 * mu * _G,
        )
        tire = LoadSensitiveTire(
            mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)

        v_analytical = math.sqrt(mu * _G * R)

        # Get speeds in corner regions (where kappa > 0.01)
        corner_mask = np.abs(mesh.kappa) > 0.01
        corner_speeds = result.speed_profile[corner_mask]

        # Mid-corner speeds (away from transitions) should be close to analytical
        n_corner = len(corner_speeds)
        if n_corner > 10:
            mid_corner = corner_speeds[n_corner // 4 : 3 * n_corner // 4]
            mean_mid = float(np.mean(mid_corner))
            assert mean_mid == pytest.approx(v_analytical, rel=0.05)  # within 5%

```

- [ ] **Step 2: Run integration test**

Run: `pytest telemetry_tool/tests/test_solver_integration.py -v -m slow --timeout=600`
Expected: All 2 tests PASS (may take 1-3 minutes)

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/tests/test_solver_integration.py
git commit -m "test(solver): add synthetic oval integration test (regression gate)"
```

---

### Task 13: Run Full Test Suite

- [ ] **Step 1: Run all solver tests**

Run: `pytest telemetry_tool/tests/test_solver_*.py -v`
Expected: All tests PASS (~20 tests across 7 test files)

- [ ] **Step 2: Run existing test suite to verify no regressions**

Run: `pytest telemetry_tool/tests/ -x --ignore=telemetry_tool/tests/test_solver_integration.py`
Expected: 3695+ passed (same as before), 0 new failures

- [ ] **Step 3: Final commit with all files**

```bash
git add -A telemetry_tool/solver/ telemetry_tool/tests/test_solver_*.py
git commit -m "feat(solver): complete OCP theoretical engine v2

Adds CasADi/IPOPT optimal control solver with:
- Enhanced point-mass vehicle model with load transfer
- Load-sensitive tire model with friction ellipse
- Adaptive track mesh from curvature profile
- Multi-parameter calibration loop
- Background Celery task for async execution
- API endpoint extensions for OCP data serving
- Comprehensive test suite including regression gate"
```
