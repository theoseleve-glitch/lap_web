"""Pattern: early braking on entry."""
from __future__ import annotations

from track_surface.prescriptive._internal import Evidence, WeaknessContext
from track_surface.prescriptive.patterns._base import BasePattern


class EarlyBraking(BasePattern):
    key = "early_braking"
    title = "Early braking on entry"
    phase = "entry"
    required_fields = ("brake_point_delta_m",)

    likely_causes = (
        "Braking reference point is too far from the corner",
        "Defensive habit from an earlier session or unfamiliar track",
        "Approaching the corner off-line, requiring earlier braking to make the geometry",
    )

    coaching_action_templates = (
        "Move the braking reference closer by {brake_adjust_m} m (one kart-length at a time)",
        "Use a fixed visual marker for the brake point, not a feeling",
        "Keep the same peak brake force — the change is WHERE, not HOW HARD",
    )

    driver_cues = (
        "Feel: the kart should require you to brake, not just slow down voluntarily",
        "Look: identify a crack, kerb edge, or cone that is {brake_adjust_m} m closer than your current point",
    )

    sensor_note = (
        "Brake point derived from speed-based deceleration onset "
        "(no brake pressure sensor)"
    )

    def _compute_parameters(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> dict[str, str]:
        med = self._median_abs(
            [ev.brake_point_delta_m for ev in evaluable
             if ev.brake_point_delta_m is not None]
        )
        brake_adjust_m = max(2.0, med * 0.4)
        return {"brake_adjust_m": f"{brake_adjust_m:.0f}"}

    def _compute_measurable_targets(
        self, context: WeaknessContext, evaluable: list[Evidence],
    ) -> tuple[str, ...]:
        med = self._median_abs(
            [ev.brake_point_delta_m for ev in evaluable
             if ev.brake_point_delta_m is not None]
        )
        if med > 3:
            return (
                f"Brake point moves {med * 0.3:.0f}+ m later (speed-derived proxy)",
            )
        return super()._compute_measurable_targets(context, evaluable)
