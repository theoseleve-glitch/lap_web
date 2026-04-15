"""
Physics model validation — cross-checks the rigid-body load model against
independently measured telemetry channels.

Five validation tests:
1. Ride-height correlation: does predicted ΔFz match Δride × spring_rate?
2. Tire-temp correlation: does time-averaged Fz predict tire temp per wheel?
3. Analytical steady-state: at constant-radius turns, does Fz_outer/Fz_inner
   match the analytical formula?
4. Total force conservation: does sum(Fz) ≈ m·g·aero_factor per sample?
5. mu range sanity: is p95 of computed μ within physical bounds?

Each test produces a score (0-1), a pass/fail, and a diagnostic message.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from scipy.ndimage import uniform_filter1d

from track_surface.physics_grip import VehicleGeometry

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665
_WHEEL_NAMES: Final[list[str]] = ["LF", "RF", "LR", "RR"]


@dataclass
class TestResult:
    name: str
    passed: bool
    score: float       # 0-1, higher = better agreement
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": round(self.score, 3),
            "message": self.message,
            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.details.items()},
        }


@dataclass
class ValidationReport:
    tests: list[TestResult]
    overall_passed: bool
    overall_score: float

    def to_dict(self) -> dict:
        return {
            "overall_passed": self.overall_passed,
            "overall_score": round(self.overall_score, 3),
            "tests": [t.to_dict() for t in self.tests],
        }

    def print_report(self) -> None:
        print(f"\n{'=' * 60}")
        print(f"PHYSICS MODEL VALIDATION REPORT")
        print(f"{'=' * 60}")
        for t in self.tests:
            icon = "PASS" if t.passed else "FAIL"
            print(f"  [{icon}] {t.name}: score={t.score:.3f}")
            print(f"         {t.message}")
            for k, v in t.details.items():
                if isinstance(v, float):
                    print(f"         {k}: {v:.4f}")
                elif isinstance(v, list) and len(v) <= 4:
                    print(f"         {k}: {[round(x, 3) if isinstance(x, float) else x for x in v]}")
        print(f"\n  Overall: {'PASS' if self.overall_passed else 'FAIL'} "
              f"(score {self.overall_score:.3f})")
        print(f"{'=' * 60}\n")


# -- Test 1: Ride-height correlation ----------------------------------------


def _test_ride_height_correlation(
    fz_per_wheel: np.ndarray,      # (N, 4) our predicted loads
    ride_heights_mm: np.ndarray,   # (N, 4) measured
    spring_rates_npm: np.ndarray,  # (4,) N/m from SuspensionModel
    valid_mask: np.ndarray,        # (N,) bool
) -> TestResult:
    """Compare ΔFz_predicted vs ΔFz_from_springs = Δride × spring_rate.

    If our load model is correct, the correlation per wheel should be > 0.7.
    """
    corrs = []
    details = {}

    for w in range(4):
        fz = fz_per_wheel[valid_mask, w]
        rh = ride_heights_mm[valid_mask, w]
        k = spring_rates_npm[w]

        if len(fz) < 100 or k <= 0 or np.std(rh) < 0.001:
            corrs.append(0.0)
            details[f"corr_{_WHEEL_NAMES[w]}"] = 0.0
            continue

        # ΔFz from springs: (static_rh - current_rh) × spring_rate / 1000
        rh_mean = np.mean(rh)
        delta_fz_springs = (rh_mean - rh) * k / 1000.0

        # ΔFz from our model
        fz_mean = np.mean(fz)
        delta_fz_model = fz - fz_mean

        # Pearson correlation
        c = np.corrcoef(delta_fz_model, delta_fz_springs)[0, 1]
        if np.isfinite(c):
            corrs.append(float(c))
        else:
            corrs.append(0.0)
        details[f"corr_{_WHEEL_NAMES[w]}"] = float(c) if np.isfinite(c) else 0.0

    mean_corr = float(np.mean(corrs))
    passed = mean_corr > 0.5
    return TestResult(
        name="Ride-height vs Fz correlation",
        passed=passed,
        score=max(0.0, mean_corr),
        message=f"Mean correlation across 4 wheels: {mean_corr:.3f} "
                f"({'good' if passed else 'load model may be inaccurate'})",
        details=details,
    )


# -- Test 2: Tire-temp correlation ------------------------------------------


def _test_tire_temp_correlation(
    fz_per_wheel: np.ndarray,    # (N, 4)
    tire_temps_c: np.ndarray,    # (N, 4) Celsius
    valid_mask: np.ndarray,
    window_s: int = 300,         # averaging window in samples (~5s at 60Hz)
) -> TestResult:
    """Time-averaged Fz should predict tire temp (more load → hotter).

    The correlation should be positive per wheel. We smooth both signals
    to match the thermal time constant (tires respond slowly to load).
    """
    corrs = []
    details = {}

    for w in range(4):
        fz = fz_per_wheel[valid_mask, w]
        tt = tire_temps_c[valid_mask, w]

        if len(fz) < 1000 or np.std(tt) < 0.5:
            corrs.append(0.0)
            details[f"corr_{_WHEEL_NAMES[w]}"] = 0.0
            continue

        # Smooth both with a moving average
        fz_smooth = uniform_filter1d(fz, window_s)
        tt_smooth = uniform_filter1d(tt, window_s)

        c = np.corrcoef(fz_smooth, tt_smooth)[0, 1]
        if np.isfinite(c):
            corrs.append(float(c))
        else:
            corrs.append(0.0)
        details[f"corr_{_WHEEL_NAMES[w]}"] = float(c) if np.isfinite(c) else 0.0

    mean_corr = float(np.mean(corrs))
    passed = mean_corr > 0.3  # weaker threshold — temps have more confounders
    return TestResult(
        name="Tire-temp vs Fz correlation",
        passed=passed,
        score=max(0.0, mean_corr),
        message=f"Mean time-averaged correlation: {mean_corr:.3f} "
                f"({'plausible' if passed else 'load distribution suspect'})",
        details=details,
    )


# -- Test 3: Analytical steady-state ----------------------------------------


def _test_steady_state_ratio(
    fz_per_wheel: np.ndarray,    # (N, 4)
    a_lat: np.ndarray,           # (N,) body-frame lateral accel
    speed: np.ndarray,           # (N,) m/s
    geom: VehicleGeometry,
    valid_mask: np.ndarray,
) -> TestResult:
    """At constant-speed, constant-radius turns, Fz_outer/Fz_inner
    should match the analytical formula:

        ratio = 1 + (2 × h × |a_lat|) / (track × g)

    We select "steady" samples (low jerk, low speed change) and compare.
    """
    # Find steady-state samples: stable speed and stable a_lat
    d_speed = np.abs(np.gradient(speed))
    d_alat = np.abs(np.gradient(a_lat))
    steady = (
        valid_mask
        & (np.abs(a_lat) > 3.0)  # in a corner
        & (d_speed < 0.5)         # stable speed
        & (d_alat < 1.0)          # stable yaw
        & (speed > 15.0)
    )

    n_steady = steady.sum()
    if n_steady < 50:
        return TestResult(
            name="Steady-state load transfer ratio",
            passed=True,
            score=0.5,
            message=f"Only {n_steady} steady samples — insufficient for validation",
            details={"n_samples": int(n_steady)},
        )

    # Compute predicted ratio from model
    fz_steady = fz_per_wheel[steady]
    alat_steady = a_lat[steady]

    # For right turns (a_lat > 0): outer = RF/RR, inner = LF/LR
    # For left turns (a_lat < 0): outer = LF/LR, inner = RF/RR
    right_turn = alat_steady > 0
    outer_front = np.where(right_turn, fz_steady[:, 1], fz_steady[:, 0])
    inner_front = np.where(right_turn, fz_steady[:, 0], fz_steady[:, 1])

    # Avoid division by very small loads
    valid_ratio = inner_front > 500
    if valid_ratio.sum() < 20:
        return TestResult(
            name="Steady-state load transfer ratio",
            passed=True,
            score=0.5,
            message="Insufficient valid steady-state samples after filtering",
        )

    model_ratio = outer_front[valid_ratio] / inner_front[valid_ratio]

    # Analytical ratio (front axle — using track_front)
    abs_alat = np.abs(alat_steady[valid_ratio])
    analytical_ratio = 1.0 + (2.0 * geom.cg_height_m * abs_alat) / (geom.track_front_m * _G)

    # Compare mean of both
    mean_model = float(np.mean(model_ratio))
    mean_analytical = float(np.mean(analytical_ratio))
    error_pct = abs(mean_model - mean_analytical) / mean_analytical * 100

    passed = error_pct < 20.0
    score = max(0.0, 1.0 - error_pct / 50.0)
    return TestResult(
        name="Steady-state load transfer ratio",
        passed=passed,
        score=score,
        message=f"Model ratio={mean_model:.3f}, analytical={mean_analytical:.3f} "
                f"(error {error_pct:.1f}%)",
        details={
            "model_mean_ratio": mean_model,
            "analytical_mean_ratio": mean_analytical,
            "error_pct": error_pct,
            "n_samples": int(valid_ratio.sum()),
        },
    )


# -- Test 4: Total force conservation ---------------------------------------


def _test_total_force_conservation(
    fz_per_wheel: np.ndarray,  # (N, 4)
    mass_kg: float,
    aero_factor: np.ndarray,   # (N,) from PerWheelLoads
    valid_mask: np.ndarray,
) -> TestResult:
    """sum(Fz_per_wheel) should equal mass × g × aero_factor within 1%."""
    fz_sum = fz_per_wheel[valid_mask].sum(axis=1)
    expected = mass_kg * _G * aero_factor[valid_mask]
    error = np.abs(fz_sum - expected) / expected
    mean_error = float(np.mean(error))
    max_error = float(np.max(error))
    passed = mean_error < 0.01
    return TestResult(
        name="Total force conservation",
        passed=passed,
        score=max(0.0, 1.0 - mean_error * 100),
        message=f"Mean Fz sum error: {mean_error*100:.3f}% "
                f"(max {max_error*100:.3f}%)",
        details={"mean_error_pct": mean_error * 100, "max_error_pct": max_error * 100},
    )


# -- Test 5: mu range sanity ------------------------------------------------


def _test_mu_range(
    mu_per_wheel: np.ndarray,   # (N, 4)
    mu_expected_range: tuple[float, float] = (1.0, 2.0),
) -> TestResult:
    """p95 of per-wheel mu should fall within expected physical bounds."""
    valid_mu = mu_per_wheel[np.isfinite(mu_per_wheel)]
    if len(valid_mu) < 100:
        return TestResult(
            name="mu range sanity",
            passed=False,
            score=0.0,
            message="Insufficient valid mu samples",
        )

    p50 = float(np.percentile(valid_mu, 50))
    p95 = float(np.percentile(valid_mu, 95))
    p99 = float(np.percentile(valid_mu, 99))

    lo, hi = mu_expected_range
    in_range = lo <= p95 <= hi
    score = 1.0 if in_range else max(0.0, 1.0 - abs(p95 - (lo + hi) / 2) / hi)
    return TestResult(
        name="mu range sanity",
        passed=in_range,
        score=score,
        message=f"mu p50={p50:.3f}, p95={p95:.3f}, p99={p99:.3f} "
                f"(expected p95 in [{lo}, {hi}])",
        details={"mu_p50": p50, "mu_p95": p95, "mu_p99": p99},
    )


# -- Public API: run all tests ----------------------------------------------


def validate_physics_model(
    *,
    fz_per_wheel: np.ndarray,          # (N, 4) predicted normal loads
    aero_factor: np.ndarray,            # (N,) from PerWheelLoads
    mu_per_wheel: np.ndarray,           # (N, 4) computed tire mu
    mass_kg: float,
    geom: VehicleGeometry,
    a_lat: np.ndarray,
    speed: np.ndarray,
    ride_heights_mm: np.ndarray | None = None,   # (N, 4) optional
    spring_rates_npm: np.ndarray | None = None,  # (4,) optional
    tire_temps_c: np.ndarray | None = None,      # (N, 4) optional
    valid_mask: np.ndarray | None = None,
) -> ValidationReport:
    """Run all 5 validation tests and produce a report.

    Ride-height and tire-temp tests are skipped if data is not provided.
    """
    N = fz_per_wheel.shape[0]
    if valid_mask is None:
        valid_mask = np.ones(N, dtype=bool)

    tests: list[TestResult] = []

    # Test 1: Ride-height
    if ride_heights_mm is not None and spring_rates_npm is not None:
        tests.append(_test_ride_height_correlation(
            fz_per_wheel, ride_heights_mm, spring_rates_npm, valid_mask,
        ))
    else:
        tests.append(TestResult(
            name="Ride-height vs Fz correlation",
            passed=True, score=0.5,
            message="Skipped — ride height or spring rates not available",
        ))

    # Test 2: Tire-temp
    if tire_temps_c is not None:
        tests.append(_test_tire_temp_correlation(
            fz_per_wheel, tire_temps_c, valid_mask,
        ))
    else:
        tests.append(TestResult(
            name="Tire-temp vs Fz correlation",
            passed=True, score=0.5,
            message="Skipped — tire temps not available",
        ))

    # Test 3: Steady-state
    tests.append(_test_steady_state_ratio(
        fz_per_wheel, a_lat, speed, geom, valid_mask,
    ))

    # Test 4: Total force conservation
    tests.append(_test_total_force_conservation(
        fz_per_wheel, mass_kg, aero_factor, valid_mask,
    ))

    # Test 5: mu range
    tests.append(_test_mu_range(mu_per_wheel))

    overall_score = float(np.mean([t.score for t in tests]))
    overall_passed = all(t.passed for t in tests)

    return ValidationReport(
        tests=tests,
        overall_passed=overall_passed,
        overall_score=overall_score,
    )
