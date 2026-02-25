"""
cause_ranking.py
----------------
Rank time-loss causes across all corners and generate human-readable
coaching summaries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from kart_envelope.coaching.corner_coaching import CornerPerformance
from kart_envelope.inference.session_scalars import SessionScalars

logger = logging.getLogger(__name__)


@dataclass
class TimeLossCause:
    """A single time-loss entry."""

    corner_id: int
    cause: str
    time_loss_ms: float
    coaching_hint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "cause": self.cause,
            "time_loss_ms": round(self.time_loss_ms, 1),
            "coaching_hint": self.coaching_hint,
        }


def rank_time_loss_causes(
    corner_perfs: list[CornerPerformance],
    top_n: int = 10,
) -> list[TimeLossCause]:
    """Rank all corners by total time loss and return top-N causes.

    Parameters
    ----------
    corner_perfs : list[CornerPerformance]
    top_n : int

    Returns
    -------
    list[TimeLossCause]
        Sorted by time_loss_ms descending.
    """
    causes: list[TimeLossCause] = []
    for cp in corner_perfs:
        if cp.time_loss_total_s <= 0.001:
            continue
        causes.append(TimeLossCause(
            corner_id=cp.corner_id,
            cause=cp.primary_cause,
            time_loss_ms=cp.time_loss_total_s * 1000,
            coaching_hint=cp.coaching_hint,
        ))

    causes.sort(key=lambda c: c.time_loss_ms, reverse=True)
    return causes[:top_n]


def generate_coaching_text(
    causes: list[TimeLossCause],
    scalars: SessionScalars | None = None,
    max_items: int = 5,
) -> str:
    """Generate a human-readable coaching summary.

    Parameters
    ----------
    causes : list[TimeLossCause]
    scalars : SessionScalars | None
    max_items : int

    Returns
    -------
    str
        Multi-line coaching text.
    """
    lines: list[str] = []

    if scalars:
        lines.append(f"Session conditions: {scalars.condition_label} "
                       f"(grip {scalars.mu_session:.0%}, "
                       f"power {scalars.p_session:.0%}, "
                       f"braking {scalars.b_session:.0%})")
        lines.append("")

    if not causes:
        lines.append("No significant time-loss areas identified. Great driving!")
        return "\n".join(lines)

    total_loss = sum(c.time_loss_ms for c in causes)
    lines.append(f"Total time loss in top {min(max_items, len(causes))} areas: "
                  f"{total_loss:.0f} ms")
    lines.append("")

    for i, c in enumerate(causes[:max_items], 1):
        lines.append(f"{i}. Corner {c.corner_id}: {c.time_loss_ms:.0f} ms "
                       f"({c.cause.replace('_', ' ')})")
        lines.append(f"   -> {c.coaching_hint}")

    # Aggregate patterns
    cause_counts: dict[str, int] = {}
    cause_total: dict[str, float] = {}
    for c in causes:
        cause_counts[c.cause] = cause_counts.get(c.cause, 0) + 1
        cause_total[c.cause] = cause_total.get(c.cause, 0.0) + c.time_loss_ms

    lines.append("")
    lines.append("Pattern summary:")
    for cause, count in sorted(cause_counts.items(), key=lambda x: cause_total[x[0]],
                                 reverse=True):
        lines.append(f"  {cause.replace('_', ' ')}: {count} corners, "
                       f"{cause_total[cause]:.0f} ms total")

    return "\n".join(lines)
