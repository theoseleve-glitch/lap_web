"""Day-12 Phase F — combined spatial factor + condition-aware clamping.

Spec §7 combined formula:
    mu_spatial_factor(s) = clamp(
        1.0 / (drainage(s) × sun(s) × wind(s)),
        lower, upper,
    )

    For label == "dry":  clamp = [0.9, 1.1]   (variance muted)
    For wet/damp/greasy: clamp = [0.6, 1.5]   (full spatial story)

Inversion: factors > 1 (wetter) become < 1 (lower effective μ).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from telemetry_tool.conditions.spatial_factors import compute_spatial_factor


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("label", ["dry", "damp", "wet", "greasy"])
def test_all_neutral_returns_one(label):
    """All three factors at 1.0 → spatial_factor = 1.0 regardless of clamp."""
    n = 5
    drainage = np.ones(n)
    sun = np.ones(n)
    wind = np.ones(n)
    result = compute_spatial_factor(drainage, sun, wind, label)
    np.testing.assert_allclose(result, 1.0, atol=1e-9)


def test_spec_worked_example_wet_section_unclamped():
    """Spec §7 worked example: drainage 1.30, sun 1.15, wind 1.10 →
    1/(1.30 · 1.15 · 1.10) ≈ 0.608. Spec text says "clamped to 0.60"
    but mathematically 0.608 > 0.60 — clamp doesn't actually fire on
    these inputs. Real clamp firing tested below with more extreme inputs.
    """
    drainage = np.array([1.30])
    sun = np.array([1.15])
    wind = np.array([1.10])
    result = compute_spatial_factor(drainage, sun, wind, "wet")
    expected = 1.0 / (1.30 * 1.15 * 1.10)  # ≈ 0.6081
    assert result[0] == pytest.approx(expected, abs=0.001), (
        f"Spec worked-example inputs should compute unclamped 0.608 "
        f"(spec text approximated this as 'clamped to 0.6'); got {result[0]}"
    )


def test_extreme_wet_clamp_fires_at_lower_bound():
    """Max-realistic wet factor product = 1.30 × (1.15·1.10) × 1.15 ≈ 1.892.
    1/1.892 ≈ 0.529 → CLAMPS to 0.60 floor (wet clamp lower bound).
    """
    # 1.265 ≈ shaded sun × low-altitude modifier
    result = compute_spatial_factor(
        np.array([1.30]), np.array([1.265]), np.array([1.15]), "wet"
    )
    assert result[0] == pytest.approx(0.60, abs=0.001)


def test_spec_worked_example_wet_section_clamps_in_dry():
    """Same spec inputs (0.608 unclamped) but label=dry → clamps to dry
    lower [0.9, 1.1] → 0.9."""
    drainage = np.array([1.30])
    sun = np.array([1.15])
    wind = np.array([1.10])
    result = compute_spatial_factor(drainage, sun, wind, "dry")
    assert result[0] == pytest.approx(0.90, abs=0.001)


def test_heavy_dry_section_clamps_high_in_wet():
    """Drainage 0.85, sun 0.85, wind 0.85 → 1/0.614 = 1.629 → clamp 1.5."""
    drainage = np.array([0.85])
    sun = np.array([0.85])
    wind = np.array([0.85])
    result = compute_spatial_factor(drainage, sun, wind, "wet")
    assert result[0] == pytest.approx(1.50, abs=0.001)


def test_heavy_dry_section_clamps_tighter_in_dry():
    """Same inputs but label=dry → upper-clamp 1.1."""
    drainage = np.array([0.85])
    sun = np.array([0.85])
    wind = np.array([0.85])
    result = compute_spatial_factor(drainage, sun, wind, "dry")
    assert result[0] == pytest.approx(1.10, abs=0.001)


def test_mid_range_unclamped():
    """Modest factors → result within both clamp ranges, unchanged."""
    drainage = np.array([1.10])
    sun = np.array([0.95])
    wind = np.array([1.00])
    # product = 1.045; factor = 1/1.045 ≈ 0.957
    expected = 1.0 / (1.10 * 0.95 * 1.00)
    for label in ("dry", "damp", "wet", "greasy"):
        result = compute_spatial_factor(drainage, sun, wind, label)
        # Both clamps allow this value (0.957 ∈ [0.6, 1.5] and [0.9, 1.1])
        assert result[0] == pytest.approx(expected, abs=0.001), (
            f"mid-range expected unclamped {expected:.3f} but got "
            f"{result[0]:.3f} under label={label}"
        )


def test_vectorized_per_segment():
    """Vector inputs → per-segment output of same shape.
    Bin 0: neutral mid (1.0). Bin 1: extreme wet (clamps low). Bin 2:
    extreme dry (clamps high)."""
    drainage = np.array([1.00, 1.30, 0.85])
    sun = np.array([1.00, 1.265, 0.85])  # 1.265 = shaded × low-altitude
    wind = np.array([1.00, 1.15, 0.85])
    result = compute_spatial_factor(drainage, sun, wind, "wet")
    expected = np.array([1.00, 0.60, 1.50])  # mid / low-clamp / high-clamp
    np.testing.assert_allclose(result, expected, atol=0.001)


def test_unknown_label_raises():
    """Spec §8 label set is fixed; invalid label → ValueError."""
    drainage = np.ones(3)
    sun = np.ones(3)
    wind = np.ones(3)
    with pytest.raises(ValueError, match="condition_label"):
        compute_spatial_factor(drainage, sun, wind, "soaking")


def test_output_dtype_and_shape():
    drainage = np.array([1.0, 1.2, 0.9])
    sun = np.array([1.0, 1.0, 1.0])
    wind = np.array([1.0, 1.0, 1.0])
    result = compute_spatial_factor(drainage, sun, wind, "damp")
    assert result.shape == (3,)
    assert np.issubdtype(result.dtype, np.floating)


def test_dry_clamp_range_is_tighter_than_wet():
    """For the SAME (extreme) factor inputs, dry clamps tighter than wet.
    Worked example from spec §7 wet OK_R1:
        sheltered (1.30, 1.15, 1.10) → wet=0.60 / dry=0.90
        exposed   (1.00, 0.85, 0.85) → wet=1.38 / dry=1.10 (clamp)
    Verify ratio: wet has 2.3× spread; dry has 1.22× spread.
    """
    sheltered = compute_spatial_factor(
        np.array([1.30]), np.array([1.15]), np.array([1.10]), "wet"
    )[0]
    exposed = compute_spatial_factor(
        np.array([1.00]), np.array([0.85]), np.array([0.85]), "wet"
    )[0]
    wet_ratio = exposed / sheltered

    sheltered_d = compute_spatial_factor(
        np.array([1.30]), np.array([1.15]), np.array([1.10]), "dry"
    )[0]
    exposed_d = compute_spatial_factor(
        np.array([1.00]), np.array([0.85]), np.array([0.85]), "dry"
    )[0]
    dry_ratio = exposed_d / sheltered_d

    assert wet_ratio > 2.0, (
        f"Wet spread should be > 2× across the extremes (spec worked example); "
        f"got {wet_ratio:.2f}"
    )
    assert dry_ratio < 1.3, (
        f"Dry spread should be < 1.3× (tight clamp); got {dry_ratio:.2f}"
    )
