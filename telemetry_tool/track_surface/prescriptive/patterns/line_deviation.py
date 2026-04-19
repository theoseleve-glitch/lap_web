"""Pattern: inconsistent line / path deviation."""
from __future__ import annotations

from track_surface.prescriptive._internal import Evidence, WeaknessContext
from track_surface.prescriptive.patterns._base import BasePattern


class LineDeviation(BasePattern):
    key = "line_deviation"
    title = "Inconsistent line / path deviation"
    phase = "apex"
    required_fields = ("line_deviation_rms_m",)

    likely_causes = (
        "No fixed reference points for turn-in, apex, and exit",
        "Reacting to the kart instead of placing it deliberately",
        "Different entry speed on each lap causing different geometry",
    )

    coaching_action_templates = (
        "Pick ONE line and repeat it exactly for 5+ consecutive laps",
        "Use fixed visual markers: turn-in point, apex kerb contact, exit target",
        "Speed is secondary until the line is repeatable",
    )

    driver_cues = (
        "Feel: same steering input, same load, same timing each lap",
        "Look: same visual references every lap — track features, not feelings",
    )

    sensor_note = (
        "Line deviation = RMS of lateral offset difference from reference "
        "(GPS-derived)"
    )

    def _compute_parameters(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> dict[str, str]:
        # Templates for line_deviation have no placeholders.
        return {}

    def _compute_measurable_targets(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> tuple[str, ...]:
        med = self._median_abs(
            [ev.line_deviation_rms_m for ev in evaluable
             if ev.line_deviation_rms_m is not None]
        )
        if med > 1.0:
            target = max(0.5, med * 0.6)
            return (f"Line deviation drops below {target:.1f} m RMS",)
        return super()._compute_measurable_targets(context, evaluable)
