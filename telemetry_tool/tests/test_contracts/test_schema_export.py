import json
from pathlib import Path

from telemetry_tool.web.schemas.contracts._scripts.export_json_schema import (
    export_all_schemas,
    SCHEMAS_DIR,
)


def test_export_produces_three_schemas(tmp_path: Path):
    out_dir = tmp_path / "schemas"
    written = export_all_schemas(out_dir)
    assert {p.name for p in written} == {
        "session.schema.json", "coaching.schema.json", "optimizer.schema.json",
    }
    for p in written:
        data = json.loads(p.read_text())
        assert "$schema" in data or "title" in data  # Pydantic v2 JSON Schema — at least one present


def test_committed_schemas_up_to_date():
    """If this fails, run: python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema"""
    from telemetry_tool.web.schemas.contracts.session import SessionContract
    committed = json.loads((SCHEMAS_DIR / "session.schema.json").read_text())
    fresh = SessionContract.model_json_schema()
    assert committed == fresh, "session.schema.json drifted — regenerate"
