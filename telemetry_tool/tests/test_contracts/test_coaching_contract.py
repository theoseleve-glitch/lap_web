import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    CornerCoachingItem,
    CornerCueItem,
    FocusItem,
    NextRunItem,
    StorylineItem,
    ValidationCheck,
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


def test_next_run_item_type_rejects_invalid():
    """NextRunItemType Literal rejects values outside the 4-member set."""
    NextRunItem(item_type="technical_focus", title="t", body="b")
    with pytest.raises(ValidationError):
        NextRunItem(item_type="bogus_type", title="t", body="b")


def test_phase_tag_rejects_invalid():
    """PhaseTag Literal rejects values outside the 5-member set."""
    CornerCueItem(weakness_key="w.x", phase="apex", severity="high", cue_text="…")
    with pytest.raises(ValidationError):
        CornerCueItem(weakness_key="w.x", phase="bogus_phase", severity="high", cue_text="…")


def test_coaching_contract_json_roundtrip():
    """Nested structure survives model_dump_json → model_validate_json."""
    c = CoachingContract(
        storyline=[StorylineItem(weakness_key="w.a", state="Detected", headline="h")],
        global_focus=[FocusItem(rank=1, weakness_key="w.a", title="t", severity="high")],
        corner_coaching={
            "3": CornerCoachingItem(
                corner_id="3",
                items=[CornerCueItem(weakness_key="w.a", phase="apex", severity="medium", cue_text="cue")],
            ),
        },
        not_evaluable_corners=["5"],
        validation_checks=[ValidationCheck(check_id="v1", description="d")],
        next_run=[NextRunItem(item_type="technical_focus", title="t", body="b")],
    )
    payload = c.model_dump_json()
    restored = CoachingContract.model_validate_json(payload)
    assert restored == c
    assert restored.version == "1.0"
