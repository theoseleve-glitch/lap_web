"""Focus limiter — enforces max 2 focus areas per session (coaching book rule)."""
from __future__ import annotations

from coaching.models import FocusArea

_SIGNIFICANCE_RATIO = 0.30  # 2nd area must be ≥30% of 1st area's time loss


def limit_focus_areas(
    areas: list[FocusArea],
) -> tuple[list[FocusArea], list[FocusArea]]:
    """Select max 2 primary focus areas, defer the rest.

    Rules:
    1. First area always selected (highest time loss)
    2. Second area selected only if ≥30% of first area's time loss
    3. Same-category areas are merged into one
    4. Remaining areas go to deferred list
    """
    if not areas:
        return [], []

    # Sort by time_loss descending
    sorted_areas = sorted(areas, key=lambda fa: fa.time_loss_s, reverse=True)

    # Merge same-category areas
    merged: list[FocusArea] = []
    seen_categories: set[str] = set()
    for fa in sorted_areas:
        if fa.category in seen_categories:
            # Merge into existing
            for i, existing in enumerate(merged):
                if existing.category == fa.category:
                    merged[i] = FocusArea(
                        rank=existing.rank,
                        category=existing.category,
                        time_loss_s=existing.time_loss_s + fa.time_loss_s,
                        corner_ids=existing.corner_ids + fa.corner_ids,
                        summary=existing.summary,
                        advice=existing.advice,
                        progressive_steps=existing.progressive_steps,
                        symptom_diagnosis=existing.symptom_diagnosis,
                    )
                    break
        else:
            merged.append(fa)
            seen_categories.add(fa.category)

    # Re-sort merged list
    merged.sort(key=lambda fa: fa.time_loss_s, reverse=True)

    # Select primary areas
    primary: list[FocusArea] = [merged[0]]

    if len(merged) > 1:
        second = merged[1]
        if second.time_loss_s >= merged[0].time_loss_s * _SIGNIFICANCE_RATIO:
            primary.append(second)

    # Re-rank
    for i, fa in enumerate(primary):
        primary[i] = FocusArea(
            rank=i + 1,
            category=fa.category,
            time_loss_s=fa.time_loss_s,
            corner_ids=fa.corner_ids,
            summary=fa.summary,
            advice=fa.advice,
            progressive_steps=fa.progressive_steps,
            symptom_diagnosis=fa.symptom_diagnosis,
        )

    # Deferred = everything not in primary
    primary_categories = {fa.category for fa in primary}
    deferred = [fa for fa in merged if fa.category not in primary_categories]
    for i, fa in enumerate(deferred):
        deferred[i] = FocusArea(
            rank=len(primary) + i + 1,
            category=fa.category,
            time_loss_s=fa.time_loss_s,
            corner_ids=fa.corner_ids,
            summary=fa.summary,
            advice=fa.advice,
            progressive_steps=fa.progressive_steps,
            symptom_diagnosis=fa.symptom_diagnosis,
        )

    return primary, deferred
