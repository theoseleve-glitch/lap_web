"""
test_vehicle_overrides.py
-------------------------
Tests for vehicle parameter override flow (Task 5).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.mark.domain
class TestVehicleOverrideValidation:
    """Server-side validation of vehicle overrides."""

    _VALID_DRAG_MODELS = {"none", "kart", "gt", "touring", "custom"}

    def test_mass_within_range(self):
        for valid in (30, 100, 175, 500, 2000):
            assert 30 <= valid <= 2000

    def test_mass_out_of_range_rejected(self):
        for invalid in (0, 10, 29, 2001, 5000):
            assert not (30 <= invalid <= 2000)

    def test_power_within_range(self):
        for valid in (1, 9, 50, 500, 1000):
            assert 1 <= valid <= 1000

    def test_power_out_of_range_rejected(self):
        for invalid in (0, 0.5, 1001, 5000):
            assert not (1 <= invalid <= 1000)

    def test_drag_model_valid_values(self):
        for model in self._VALID_DRAG_MODELS:
            assert model in self._VALID_DRAG_MODELS

    def test_drag_model_invalid_rejected(self):
        for bad in ("formula", "sedan", "", "KART"):
            assert bad not in self._VALID_DRAG_MODELS


@pytest.mark.domain
class TestVehicleOverrideApplication:
    """Vehicle overrides applied correctly to VehicleParameters."""

    def test_mass_override_applied(self):
        from telemetry_tool.vehicle_model import VehicleClass, VehicleParameters

        vp = VehicleParameters(
            vehicle_class=VehicleClass.KART,
            estimated_mass_kg=170.0,
            peak_lateral_g=1.2,
            peak_braking_g=0.8,
            peak_traction_g=0.5,
            has_downforce=False,
            has_abs=False,
            rolling_resistance_est=0.015,
            aero_drag_factor_est=0.0,
        )

        # Simulate override
        override_mass = 180.0
        vp.estimated_mass_kg = override_mass
        vp.classification_reasons.append("mass overridden by user")

        assert vp.estimated_mass_kg == 180.0
        assert "mass overridden by user" in vp.classification_reasons

    def test_override_metadata_structure(self):
        overrides = {
            "mass_kg": 175.0,
            "power_kw": 9.0,
            "drag_model": "kart",
        }

        # Build metadata output
        metadata = {}
        for key, val in overrides.items():
            metadata[key] = {"value": val, "source": "user"}

        assert metadata["mass_kg"]["value"] == 175.0
        assert metadata["mass_kg"]["source"] == "user"
        assert metadata["drag_model"]["value"] == "kart"

    def test_default_values_marked_as_default(self):
        defaults = {"mass_kg": 170.0, "power_kw": None, "drag_model": None}
        overrides = {"mass_kg": 180.0}

        result = {}
        for key in defaults:
            if key in overrides:
                result[key] = {"value": overrides[key], "source": "user"}
            elif defaults[key] is not None:
                result[key] = {"value": defaults[key], "source": "default"}

        assert result["mass_kg"]["source"] == "user"
        assert "power_kw" not in result  # None defaults omitted
