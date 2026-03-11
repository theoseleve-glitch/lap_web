"""Tests for focus limiter — max 2 focus areas per session."""
import pytest
from telemetry_tool.coaching.composers.focus_limiter import limit_focus_areas
from telemetry_tool.coaching.models import FocusArea


def _fa(rank, category, time_loss):
    return FocusArea(
        rank=rank, category=category, time_loss_s=time_loss,
        corner_ids=[rank], summary=f"{category} issue", advice="Fix it",
    )


class TestFocusLimiter:
    def test_max_two_returned(self):
        areas = [_fa(1, "braking", 0.5), _fa(2, "cornering", 0.4),
                 _fa(3, "exit", 0.3), _fa(4, "consistency", 0.1)]
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) <= 2
        assert len(deferred) == len(set(fa.category for fa in areas)) - len(primary)

    def test_second_area_needs_30pct_of_first(self):
        areas = [_fa(1, "braking", 1.0), _fa(2, "cornering", 0.2)]  # 0.2 < 0.3*1.0
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 1  # second not significant enough

    def test_second_area_qualifies(self):
        areas = [_fa(1, "braking", 1.0), _fa(2, "cornering", 0.5)]  # 0.5 >= 0.3
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 2

    def test_merge_same_root_cause(self):
        areas = [_fa(1, "braking", 0.5), _fa(2, "braking", 0.4)]
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 1  # merged

    def test_single_area(self):
        areas = [_fa(1, "braking", 0.5)]
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 1
        assert len(deferred) == 0

    def test_empty_input(self):
        primary, deferred = limit_focus_areas([])
        assert primary == []
        assert deferred == []
