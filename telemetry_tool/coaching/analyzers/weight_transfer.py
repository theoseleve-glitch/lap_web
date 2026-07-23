"""Weight transfer analyzer — computes load transfer under braking, cornering, and acceleration."""
from __future__ import annotations

from coaching.models import WeightTransferInsight

# Vehicle class defaults
_DEFAULTS = {
    "kart": {"wheelbase_m": 1.04, "cg_height_m": 0.25, "mass_kg": 165.0},
    "car":  {"wheelbase_m": 2.5,  "cg_height_m": 0.45, "mass_kg": 750.0},
}
_G = 9.81


def compute_weight_transfer(
    corner_id: int,
    braking_decel_mps2: float,
    cornering_accel_mps2: float,
    exit_accel_mps2: float,
    vehicle_class: str = "car",
    wheelbase_m: float | None = None,
    cg_height_m: float | None = None,
    mass_kg: float | None = None,
) -> WeightTransferInsight:
    """Compute load transfer percentages for a corner.

    Formula: delta_F_front = (mass * decel * cg_height) / wheelbase
    Front load % = 50 + (delta_F / (mass * g)) * 100
    """
    defaults = _DEFAULTS.get(vehicle_class, _DEFAULTS["car"])
    wb = wheelbase_m or defaults["wheelbase_m"]
    cg = cg_height_m or defaults["cg_height_m"]
    m = mass_kg or defaults["mass_kg"]

    weight = m * _G

    # Entry (under braking): weight shifts forward
    delta_f_brake = (m * abs(braking_decel_mps2) * cg) / wb
    entry_front_pct = 50.0 + (delta_f_brake / weight) * 100
    entry_rear_pct = 100.0 - entry_front_pct

    # Front grip bonus from weight transfer
    front_grip_bonus = (delta_f_brake / weight) * 100

    # Trail brake bonus (additional front loading during trail phase)
    # Approximation: trail brake adds ~60% of the straight-line brake transfer
    trail_brake_front_bonus = front_grip_bonus * 0.6

    # Exit (under acceleration): weight shifts rearward
    delta_f_accel = (m * abs(exit_accel_mps2) * cg) / wb
    exit_rear_pct = 50.0 + (delta_f_accel / weight) * 100
    rear_grip_bonus = (delta_f_accel / weight) * 100

    # Build insight text
    insight = (
        f"Under braking at {braking_decel_mps2:.1f} m/s², "
        f"{front_grip_bonus:.1f}% extra load transfers to the front tyres "
        f"(front carries {entry_front_pct:.0f}% of total weight). "
        f"Trail braking adds ~{trail_brake_front_bonus:.1f}% front grip bonus. "
        f"On exit at {exit_accel_mps2:.1f} m/s² acceleration, "
        f"the rear tyres gain {rear_grip_bonus:.1f}% extra load "
        f"(rear carries {exit_rear_pct:.0f}%)."
    )

    return WeightTransferInsight(
        corner_id=corner_id,
        entry_front_load_pct=entry_front_pct,
        entry_rear_load_pct=entry_rear_pct,
        front_grip_bonus_pct=front_grip_bonus,
        trail_brake_front_bonus_pct=trail_brake_front_bonus,
        exit_rear_load_pct=exit_rear_pct,
        rear_grip_bonus_pct=rear_grip_bonus,
        insight_text=insight,
    )
