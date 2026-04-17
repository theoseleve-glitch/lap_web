"""Pattern: low minimum speed through apex."""
from __future__ import annotations

from track_surface.prescriptive._internal import Evidence, WeaknessContext
from track_surface.prescriptive.patterns._base import BasePattern


class LowMinimumSpeed(BasePattern):
    key = "low_minimum_speed"
    title = "Low minimum speed through apex"
    phase = "apex"
    required_fields = ("min_speed_delta_kph",)

    likely_causes = (
        "Over-rotating the kart before apex (too much steering input)",
        "Releasing brake too abruptly instead of trailing",
        "Turn-in point too early, tightening the radius mid-corner",
        "Insufficient confidence in the loaded phase of the corner",
    )

    coaching_action_templates = (
        "Protect minimum speed: aim to carry {target_kph} more through the middle of the corner",
        "Use a later, more patient turn-in — let the kart arc naturally rather than forcing rotation",
        "Trail the brake deeper: maintain light pressure past the initial turn-in point",
    )

    driver_cues = (
        'Feel: the kart should feel "loaded" through mid-corner, not "falling" off speed',
        "Look: pick up the exit reference earlier to give yourself confidence to carry speed",
        "Sound: engine note should not dip as sharply between braking and acceleration",
    )

    sensor_note = (
        "Minimum speed measured from GPS speed trace "
        "(speed-derived, no wheel speed sensor)"
    )

    def _compute_parameters(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> dict[str, str]:
        med = self._median_abs(
            [ev.min_speed_delta_kph for ev in evaluable
             if ev.min_speed_delta_kph is not None]
        )
        target_kph = max(2.0, med * 0.3)
        return {"target_kph": f"{target_kph:.0f}"}

    def _compute_measurable_targets(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> tuple[str, ...]:
        med = self._median_abs(
            [ev.min_speed_delta_kph for ev in evaluable
             if ev.min_speed_delta_kph is not None]
        )
        if med > 2:
            return (
                f"Minimum speed at affected corners rises by {med * 0.3:.0f}+ km/h",
            )
        return super()._compute_measurable_targets(context, evaluable)
