"""
cause_ranking.py
----------------
Rank time-loss causes across all corners and generate human-readable
coaching summaries.  Supports **corner complexes** (chicanes, esses,
etc.) and **sector strategy** (which part of the track to prioritise
in practice).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.coaching.corner_coaching import CornerComplex, CornerPerformance
from kart_envelope.inference.session_scalars import SessionScalars

logger = logging.getLogger(__name__)


@dataclass
class TimeLossCause:
    """A single time-loss entry."""

    corner_id: int
    cause: str
    time_loss_ms: float
    coaching_hint: str
    complex_id: int = 0
    corner_type: str = "single"

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "cause": self.cause,
            "time_loss_ms": round(self.time_loss_ms, 1),
            "coaching_hint": self.coaching_hint,
            "complex_id": self.complex_id,
            "corner_type": self.corner_type,
        }


@dataclass
class SectorAnalysis:
    """Performance analysis for one sector of the track.

    Attributes
    ----------
    sector_id : int
        1-based sector number.
    s_start : float
        Start distance [m].
    s_end : float
        End distance [m].
    character : str
        Dominant sector character: ``"slow_corners"``, ``"fast_corners"``,
        ``"mixed"``, or ``"straights"``.
    time_loss_ms : float
        Total time loss vs theoretical in this sector.
    n_corners : int
        Number of corners in this sector.
    avg_corner_speed_mps : float
        Average theoretical apex speed of corners in sector.
    dominant_cause : str
        Most common time-loss cause in this sector.
    strategic_hint : str
        Sector-level coaching advice.
    corner_ids : list[int]
        Corner IDs contained in this sector.
    """
    sector_id: int
    s_start: float
    s_end: float
    character: str = "mixed"
    time_loss_ms: float = 0.0
    n_corners: int = 0
    avg_corner_speed_mps: float = 0.0
    dominant_cause: str = ""
    strategic_hint: str = ""
    corner_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sector_id": self.sector_id,
            "s_start": round(self.s_start, 1),
            "s_end": round(self.s_end, 1),
            "character": self.character,
            "time_loss_ms": round(self.time_loss_ms, 1),
            "n_corners": self.n_corners,
            "avg_corner_speed_mps": round(self.avg_corner_speed_mps, 2),
            "dominant_cause": self.dominant_cause,
            "strategic_hint": self.strategic_hint,
            "corner_ids": self.corner_ids,
        }


def analyze_sectors(
    corner_perfs: list[CornerPerformance],
    lap_length_m: float,
    n_sectors: int = 3,
) -> list[SectorAnalysis]:
    """Split the track into sectors and aggregate performance.

    Sectors are equal-distance divisions of the lap.  Each sector is
    classified by its corner character (slow/fast/mixed/straights) and
    assigned a strategic coaching hint based on where time is lost and why.

    Parameters
    ----------
    corner_perfs : list[CornerPerformance]
        Per-corner performance from ``analyze_corner_performance``.
    lap_length_m : float
        Total lap distance [m].
    n_sectors : int
        Number of sectors to divide the track into (default 3).

    Returns
    -------
    list[SectorAnalysis]
        One entry per sector, sorted by sector_id.
    """
    if lap_length_m <= 0 or n_sectors < 1:
        return []

    sector_length = lap_length_m / n_sectors
    sectors: list[SectorAnalysis] = []

    for sec_idx in range(n_sectors):
        s_lo = sec_idx * sector_length
        s_hi = (sec_idx + 1) * sector_length

        # Find corners in this sector (by apex location)
        sec_corners = [
            cp for cp in corner_perfs
            if s_lo <= cp.s_apex < s_hi
        ]

        # Aggregate time loss and causes
        total_loss_ms = sum(cp.time_loss_total_s * 1000 for cp in sec_corners)
        causes_in_sector: dict[str, float] = {}
        for cp in sec_corners:
            if cp.primary_cause:
                causes_in_sector[cp.primary_cause] = (
                    causes_in_sector.get(cp.primary_cause, 0.0)
                    + cp.time_loss_total_s * 1000
                )

        dominant_cause = ""
        if causes_in_sector:
            dominant_cause = max(causes_in_sector, key=causes_in_sector.get)  # type: ignore[arg-type]

        # Classify sector character by average apex speed
        apex_speeds = [cp.apex_speed_theory for cp in sec_corners if cp.apex_speed_theory > 0]
        avg_apex = float(np.mean(apex_speeds)) if apex_speeds else 0.0

        character = _classify_sector_character(
            n_corners=len(sec_corners),
            avg_apex_speed_mps=avg_apex,
            sector_length_m=sector_length,
        )

        hint = _sector_strategic_hint(
            sector_id=sec_idx + 1,
            character=character,
            total_loss_ms=total_loss_ms,
            dominant_cause=dominant_cause,
            n_corners=len(sec_corners),
        )

        sectors.append(SectorAnalysis(
            sector_id=sec_idx + 1,
            s_start=s_lo,
            s_end=s_hi,
            character=character,
            time_loss_ms=total_loss_ms,
            n_corners=len(sec_corners),
            avg_corner_speed_mps=avg_apex,
            dominant_cause=dominant_cause,
            strategic_hint=hint,
            corner_ids=[cp.corner_id for cp in sec_corners],
        ))

    return sectors


def _classify_sector_character(
    n_corners: int,
    avg_apex_speed_mps: float,
    sector_length_m: float,
) -> str:
    """Classify a sector's dominant character."""
    corners_per_100m = n_corners / max(sector_length_m / 100, 0.1)

    if n_corners == 0 or corners_per_100m < 0.15:
        return "straights"

    # Speed thresholds (m/s):  <15 = slow, 15-25 = medium, >25 = fast
    if avg_apex_speed_mps < 15.0:
        return "slow_corners"
    if avg_apex_speed_mps > 25.0:
        return "fast_corners"
    return "mixed"


_SECTOR_CHAR_LABELS = {
    "slow_corners": "slow corners",
    "fast_corners": "high-speed corners",
    "mixed": "mixed corners",
    "straights": "mostly straights",
}


def _sector_strategic_hint(
    sector_id: int,
    character: str,
    total_loss_ms: float,
    dominant_cause: str,
    n_corners: int,
) -> str:
    """Generate sector-level strategic coaching."""
    char_label = _SECTOR_CHAR_LABELS.get(character, character)

    if total_loss_ms < 10:
        return f"Sector {sector_id} ({char_label}): strong execution, minimal time loss."

    cause_label = dominant_cause.replace("_", " ") if dominant_cause else "general"

    if character == "slow_corners":
        return (
            f"Sector {sector_id} ({char_label}): {total_loss_ms:.0f} ms lost across "
            f"{n_corners} corners. Primary issue: {cause_label}. "
            f"Slow corners reward minimum speed — focus on carrying more "
            f"apex speed rather than late braking."
        )

    if character == "fast_corners":
        return (
            f"Sector {sector_id} ({char_label}): {total_loss_ms:.0f} ms lost across "
            f"{n_corners} corners. Primary issue: {cause_label}. "
            f"High-speed sections reward confidence and smooth inputs. "
            f"Build speed gradually — carry 1-2 km/h more each session."
        )

    if character == "straights":
        if total_loss_ms > 20:
            return (
                f"Sector {sector_id} ({char_label}): {total_loss_ms:.0f} ms lost. "
                f"Check corner exit speed from the preceding section — "
                f"straight-line time loss usually comes from slow exits."
            )
        return f"Sector {sector_id} ({char_label}): on pace."

    # mixed
    return (
        f"Sector {sector_id} ({char_label}): {total_loss_ms:.0f} ms lost across "
        f"{n_corners} corners. Primary issue: {cause_label}. "
        f"Focus on the highest-loss corner in this sector first."
    )


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
            complex_id=cp.complex_id,
            corner_type=cp.corner_type,
        ))

    causes.sort(key=lambda c: c.time_loss_ms, reverse=True)
    return causes[:top_n]


def generate_coaching_text(
    causes: list[TimeLossCause],
    scalars: SessionScalars | None = None,
    complexes: list[CornerComplex] | None = None,
    sectors: list[SectorAnalysis] | None = None,
    max_items: int = 5,
) -> str:
    """Generate a human-readable coaching summary.

    When ``complexes`` are provided, adds compound-strategy advice for
    corner complexes.  When ``sectors`` are provided, adds a sector
    strategy section that helps drivers prioritise practice focus areas.

    Parameters
    ----------
    causes : list[TimeLossCause]
    scalars : SessionScalars | None
    complexes : list[CornerComplex] | None
    sectors : list[SectorAnalysis] | None
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
        type_tag = ""
        if c.corner_type != "single":
            type_tag = f" [{c.corner_type.replace('_', ' ')}]"
        lines.append(f"{i}. Corner {c.corner_id}{type_tag}: {c.time_loss_ms:.0f} ms "
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

    # ── Complex strategy advice ──
    if complexes:
        # Collect complexes that contain corners with time loss
        loss_by_complex: dict[int, float] = {}
        for c in causes:
            if c.complex_id > 0:
                loss_by_complex[c.complex_id] = (
                    loss_by_complex.get(c.complex_id, 0.0) + c.time_loss_ms
                )

        multi_corner_complexes = [
            cx for cx in complexes
            if len(cx.corner_ids) > 1 and cx.complex_id in loss_by_complex
        ]
        if multi_corner_complexes:
            multi_corner_complexes.sort(
                key=lambda cx: loss_by_complex.get(cx.complex_id, 0.0),
                reverse=True,
            )
            lines.append("")
            lines.append("Corner complex strategy:")
            for cx in multi_corner_complexes[:3]:
                loss_ms = loss_by_complex.get(cx.complex_id, 0.0)
                lines.append(
                    f"  [{cx.corner_type.replace('_', ' ')}] "
                    f"Corners {cx.corner_ids[0]}-{cx.corner_ids[-1]} "
                    f"({loss_ms:.0f} ms combined loss):"
                )
                lines.append(f"    {cx.compound_hint}")

    # ── Sector strategy ──
    if sectors:
        sectors_with_loss = [s for s in sectors if s.time_loss_ms > 5]
        if sectors_with_loss:
            sectors_with_loss.sort(key=lambda s: s.time_loss_ms, reverse=True)
            lines.append("")
            lines.append("Sector strategy (practice priorities):")
            max_loss = max(s.time_loss_ms for s in sectors)
            for sec in sectors:
                loss_bar = _loss_bar(sec.time_loss_ms, max_loss)
                lines.append(
                    f"  S{sec.sector_id} {loss_bar} {sec.time_loss_ms:.0f} ms"
                )
            lines.append("")
            for sec in sectors_with_loss[:2]:
                lines.append(f"  {sec.strategic_hint}")

    return "\n".join(lines)


def _loss_bar(loss_ms: float, max_loss_ms: float, width: int = 15) -> str:
    """Render a simple ASCII bar showing relative time loss."""
    if max_loss_ms <= 0:
        return " " * width
    frac = min(loss_ms / max_loss_ms, 1.0)
    filled = int(frac * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"
