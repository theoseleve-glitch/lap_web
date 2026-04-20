"""Export Pydantic contracts to JSON Schema files.

Run as module:
    python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema

The output files are checked in under ``_schemas/`` so frontend builds do
not require a Python step. CI enforces freshness via
``test_committed_schemas_up_to_date``.
"""
from __future__ import annotations

import json
from pathlib import Path

from telemetry_tool.web.schemas.contracts.coaching import CoachingContract
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerContract
from telemetry_tool.web.schemas.contracts.session import SessionContract

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "_schemas"

_TARGETS = {
    "session.schema.json": SessionContract,
    "coaching.schema.json": CoachingContract,
    "optimizer.schema.json": OptimizerContract,
}


def export_all_schemas(out_dir: Path = SCHEMAS_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fname, model in _TARGETS.items():
        schema = model.model_json_schema()
        # Ensure deterministic ordering for diffable commits.
        text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        path = out_dir / fname
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in export_all_schemas():
        print(f"wrote {p}")
