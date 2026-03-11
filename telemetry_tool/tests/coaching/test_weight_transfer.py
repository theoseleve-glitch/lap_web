"""Tests for weight transfer analyzer."""
import pytest
from telemetry_tool.coaching.analyzers.weight_transfer import compute_weight_transfer
from telemetry_tool.coaching.models import WeightTransferInsight


class TestWeightTransfer:
    def test_car_defaults(self):
        result = compute_weight_transfer(
            corner_id=1, braking_decel_mps2=8.0, cornering_accel_mps2=6.0,
            exit_accel_mps2=4.0, vehicle_class="car",
        )
        assert isinstance(result, WeightTransferInsight)
        assert result.entry_front_load_pct > 50  # weight shifts forward under braking
        assert result.exit_rear_load_pct > 50     # weight shifts rearward under accel
        assert "%" in result.insight_text

    def test_kart_defaults(self):
        result = compute_weight_transfer(
            corner_id=1, braking_decel_mps2=6.0, cornering_accel_mps2=8.0,
            exit_accel_mps2=3.0, vehicle_class="kart",
        )
        assert result.entry_front_load_pct > 50

    def test_custom_vehicle_params(self):
        result = compute_weight_transfer(
            corner_id=1, braking_decel_mps2=8.0, cornering_accel_mps2=6.0,
            exit_accel_mps2=4.0, vehicle_class="car",
            wheelbase_m=2.8, cg_height_m=0.5, mass_kg=900.0,
        )
        assert isinstance(result, WeightTransferInsight)
