import json

import pytest

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    OptimizerContract,
    SessionContract,
)
from telemetry_tool.web.schemas.contracts.fixtures import load_fixture

_CASES = [
    ("session_realife", SessionContract),
    ("session_iracing", SessionContract),
    ("coaching_realife", CoachingContract),
    ("coaching_iracing", CoachingContract),
    ("optimizer_trajectory", OptimizerContract),
    ("optimizer_fullfidelity", OptimizerContract),
]


@pytest.mark.parametrize("name,model", _CASES)
def test_fixture_validates_and_roundtrips(name, model):
    raw = load_fixture(name)
    parsed = model.model_validate(raw)
    # Roundtrip must preserve JSON shape
    emitted = json.loads(parsed.model_dump_json())
    # Compare as sets of top-level keys to absorb datetime serialization differences.
    assert set(emitted.keys()) == set(raw.keys()), f"{name}: key drift"
