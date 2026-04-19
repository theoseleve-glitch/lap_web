import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    FocusItem,
    StorylineItem,
    CornerCoachingItem,
    ValidationCheck,
    NextRunItem,
)


def test_coaching_contract_version_frozen_at_1_0():
    c = CoachingContract(
        storyline=[],
        global_focus=[],
        corner_coaching={},
        not_evaluable_corners=[],
        validation_checks=[],
        next_run=[],
    )
    assert c.version == "1.0"


def test_storyline_item_state_values():
    """State mirrors prescriptive refactor: Detected / NotTriggered / Insufficient / Unregistered."""
    valid = ["Detected", "NotTriggered", "Insufficient", "Unregistered"]
    for s in valid:
        StorylineItem(weakness_key="w.test", state=s, headline="hi")
    with pytest.raises(ValidationError):
        StorylineItem(weakness_key="w.test", state="Bogus", headline="hi")


def test_focus_item_severity_enum():
    FocusItem(rank=1, weakness_key="w.x", title="t", severity="high")
    FocusItem(rank=1, weakness_key="w.x", title="t", severity="low")
    with pytest.raises(ValidationError):
        FocusItem(rank=1, weakness_key="w.x", title="t", severity="critical")


def test_corner_coaching_map_accepts_string_ids():
    c = CoachingContract(
        storyline=[],
        global_focus=[],
        corner_coaching={"3": CornerCoachingItem(corner_id="3", items=[])},
        not_evaluable_corners=["5"],
        validation_checks=[],
        next_run=[],
    )
    assert "3" in c.corner_coaching
    assert c.not_evaluable_corners == ["5"]
