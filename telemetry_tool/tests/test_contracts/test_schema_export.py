import json
from pathlib import Path

import pytest

from telemetry_tool.web.schemas.contracts._scripts.export_json_schema import (
    export_all_schemas,
    SCHEMAS_DIR,
)
from telemetry_tool.web.schemas.contracts.session import SessionContract
from telemetry_tool.web.schemas.contracts.coaching import CoachingContract
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerContract


def test_export_produces_three_schemas(tmp_path: Path):
    out_dir = tmp_path / "schemas"
    written = export_all_schemas(out_dir)
    assert {p.name for p in written} == {
        "session.schema.json", "coaching.schema.json", "optimizer.schema.json",
    }
    for p in written:
        data = json.loads(p.read_text())
        assert "title" in data  # Pydantic v2 emits title for top-level models


@pytest.mark.parametrize("filename,contract", [
    ("session.schema.json", SessionContract),
    ("coaching.schema.json", CoachingContract),
    ("optimizer.schema.json", OptimizerContract),
])
def test_committed_schemas_up_to_date(filename, contract):
    """If this fails, run: python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema"""
    committed = json.loads((SCHEMAS_DIR / filename).read_text())
    fresh = contract.model_json_schema()
    assert committed == fresh, f"{filename} drifted — regenerate"
