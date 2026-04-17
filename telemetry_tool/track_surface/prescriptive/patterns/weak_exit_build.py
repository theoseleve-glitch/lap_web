"""Pattern: weak exit speed build."""
from __future__ import annotations

from track_surface.prescriptive._internal import Evidence, WeaknessContext
from track_surface.prescriptive.patterns._base import BasePattern


class WeakExitBuild(BasePattern):
    key = "weak_exit_build"
    title = "Weak exit speed build"
    phase = "exit"
    required_fields = ("exit_speed_delta_kph",)

    likely_causes = (
        "Exit line too tight — not using full track width on exit",
        "Maintaining too much steering angle while accelerating (scrubbing speed)",
        "Insufficient throttle commitment through the exit phase",
    )

    coaching_action_templates = (
        "Open the exit: begin straightening the wheel {exit_adjust_m} m earlier",
        "Use FULL track width on exit — every meter of straighter line adds exit speed",
        "If the kart pushes wide, reduce speed earlier rather than tightening exit",
    )

    driver_cues = (
        "Look: eyes to the exit kerb/edge EARLIER than you think you should",
        "Feel: the kart should be pulling you toward the outside of the track on exit",
    )

    sensor_note = "Exit speed from GPS speed at 30m after corner exit point"

    def _compute_parameters(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> dict[str, str]:
        med = self._median_abs(
            [ev.exit_speed_delta_kph for ev in evaluable
             if ev.exit_speed_delta_kph is not None]
        )
        exit_adjust_m = max(2.0, med * 0.3)
        return {"exit_adjust_m": f"{exit_adjust_m:.0f}"}

    def _compute_measurable_targets(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> tuple[str, ...]:
        med = self._median_abs(
            [ev.exit_speed_delta_kph for ev in evaluable
             if ev.exit_speed_delta_kph is not None]
        )
        if med > 2:
            return (f"Exit speed improves by {med * 0.3:.0f}+ km/h",)
        return super()._compute_measurable_targets(context, evaluable)
