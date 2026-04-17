"""Pattern: late throttle pickup on exits."""
from __future__ import annotations

from track_surface.prescriptive._internal import Evidence, WeaknessContext
from track_surface.prescriptive.patterns._base import BasePattern


class LateThrottlePickup(BasePattern):
    key = "late_throttle_pickup"
    title = "Late throttle pickup on exits"
    phase = "exit"
    required_fields = ("throttle_pickup_delta_m",)

    likely_causes = (
        "Waiting for the kart to be fully straight before applying throttle",
        "Uncertainty about exit grip after a tight apex",
        'Habit of "completing the corner" mentally before transitioning to power',
    )

    coaching_action_templates = (
        "Begin partial throttle (30-50%) as soon as you start unwinding steering",
        "Target: move throttle application {throttle_adjust_m} m earlier",
        "Do NOT go to full throttle earlier — start with initial application point only",
    )

    driver_cues = (
        "Feel: throttle should overlap with the last bit of steering unwind",
        'Look: start thinking "power" when you see the apex, not when you see the exit',
    )

    sensor_note = (
        "Throttle proxy from GPS speed derivative "
        "(no CAN throttle position sensor)"
    )

    def _compute_parameters(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> dict[str, str]:
        med = self._median_abs(
            [ev.throttle_pickup_delta_m for ev in evaluable
             if ev.throttle_pickup_delta_m is not None]
        )
        throttle_adjust_m = max(2.0, med * 0.4)
        return {"throttle_adjust_m": f"{throttle_adjust_m:.0f}"}

    def _compute_measurable_targets(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> tuple[str, ...]:
        med = self._median_abs(
            [ev.throttle_pickup_delta_m for ev in evaluable
             if ev.throttle_pickup_delta_m is not None]
        )
        if med > 3:
            return (
                f"Throttle pickup moves {med * 0.3:.0f}+ m earlier (speed-derived proxy)",
            )
        return super()._compute_measurable_targets(context, evaluable)
