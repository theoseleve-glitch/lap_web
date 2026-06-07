"""Quest metric registry + calibration deltas — the guardrail for the
generic quest DSL. A quest may only reference a metric defined here; the
registry supplies scope, comparator direction, and the human-copy template,
so a data-driven {metric,comparator,target} quest can't be nonsensical.
Recalibration is a deploy, not a migration (vision spec §7)."""
from __future__ import annotations

METRICS: dict[str, dict] = {
    "corner.apex_speed_kmh": {
        "scope": "corner", "unit": "km/h", "direction": "higher",
        "label": "Carry {target} km/h minimum speed through T{corner_id}",
    },
    "corner.exit_speed_kmh": {
        "scope": "corner", "unit": "km/h", "direction": "higher",
        "label": "Get T{corner_id} exit speed to {target} km/h",
    },
    "corner.time_loss_ms": {
        "scope": "corner", "unit": "ms", "direction": "lower",
        "label": "Cut your time loss in T{corner_id} under {target} ms",
    },
    "corner.mastery_score": {
        "scope": "corner", "unit": "", "direction": "higher",
        "label": "Get T{corner_id} to a score of {target}",
    },
    "consistency_cv_pct": {
        "scope": "session", "unit": "%", "direction": "lower",
        "label": "Keep lap-time spread under {target}%",
    },
    "best_lap_improvement_pct": {
        "scope": "session", "unit": "%", "direction": "higher",
        "label": "Beat your best lap by {target}%",
    },
    "session.score": {
        "scope": "session", "unit": "", "direction": "higher",
        "label": "Post a session score of {target}+",
    },
    "laps_completed": {
        "scope": "session", "unit": "", "direction": "higher",
        "label": "Complete {target} clean laps",
    },
}

# Calibration deltas (provisional — tune against prod distributions, vision §7).
APEX_SPEED_DELTA_KMH = 3.0
EXIT_SPEED_DELTA_KMH = 3.0
TIME_LOSS_DELTA_MS = 200.0
MASTERY_TARGET_STEP = 15.0       # nudge corner score up by ~one band
CONSISTENCY_DELTA_PCT = 0.5      # tighten CV by half a point
BEST_LAP_TARGET_PCT = 1.0        # beat PB by 1%
LAPS_FALLBACK = 15               # activity fallback target
CLEAN_LAP_MAX_RATIO = 2.0        # a lap slower than this × the session's fastest is an out/cool-down lap, excluded from "clean laps"

# XP per quest (vision §4: 75–150).
QUEST_XP = {"corner": 150, "session": 100, "activity": 75}


def comparator_for(metric: str) -> str:
    return ">=" if METRICS[metric]["direction"] == "higher" else "<="


def render_label(metric: str, target, corner_id=None) -> str:
    tgt = int(target) if float(target).is_integer() else round(float(target), 1)
    return METRICS[metric]["label"].format(target=tgt, corner_id=corner_id)
