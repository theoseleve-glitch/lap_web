"""Snapshot regression -- freeze contract JSON per summary fixture.

Running on a fresh machine for the first time writes the golden files.
After that, each run diffs the adapter output against the stored golden.

To regenerate after an intentional contract change:
    UPDATE_CONTRACT_SNAPSHOTS=1 pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from telemetry_tool.pipeline.contract_adapter import ContextRef, to_contracts

_FIXT = Path(__file__).parent / "fixtures"
_SNAP = Path(__file__).parent / "snapshots"


def _fixtures():
    return sorted(_FIXT.glob("summary_*.json"))


def _normalize(obj):
    """Normalize fields that carry set-backed data for deterministic diffs.

    ``SessionContract.capabilities.channels`` is a frozenset in the W1
    Pydantic model — its JSON-list serialisation order is non-deterministic
    across Python processes (hash randomisation). Sorting it here makes
    the snapshot stable without changing the contract itself.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "capabilities" and isinstance(v, dict) and isinstance(v.get("channels"), list):
                out[k] = {**v, "channels": sorted(v["channels"])}
            else:
                out[k] = _normalize(v)
        return out
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    return obj


@pytest.mark.parametrize("fixture_path", _fixtures(), ids=lambda p: p.stem)
def test_snapshot(fixture_path: Path):
    summary = json.loads(fixture_path.read_text(encoding="utf-8"))
    ctx = ContextRef(
        session_id=f"sid-{fixture_path.stem}",
        workspace_id="wid-test",
    )
    tup = to_contracts(summary, ctx)

    golden_key = fixture_path.stem.replace("summary_", "")
    want_dir = _SNAP / golden_key
    update = os.environ.get("UPDATE_CONTRACT_SNAPSHOTS") == "1"

    session_dict = _normalize(json.loads(tup.session.model_dump_json()))
    coaching_dict = _normalize(json.loads(tup.coaching.model_dump_json()))
    optimizer_dict = _normalize(json.loads(tup.optimizer.model_dump_json()))

    if update or not want_dir.exists():
        want_dir.mkdir(parents=True, exist_ok=True)
        (want_dir / "session.json").write_text(json.dumps(session_dict, indent=2), encoding="utf-8")
        (want_dir / "coaching.json").write_text(json.dumps(coaching_dict, indent=2), encoding="utf-8")
        (want_dir / "optimizer.json").write_text(json.dumps(optimizer_dict, indent=2), encoding="utf-8")
        if not update:
            pytest.skip(f"wrote initial golden for {golden_key}")
        return

    want_session = json.loads((want_dir / "session.json").read_text(encoding="utf-8"))
    assert session_dict == want_session, "SessionContract snapshot drift"

    want_coaching = json.loads((want_dir / "coaching.json").read_text(encoding="utf-8"))
    assert coaching_dict == want_coaching, "CoachingContract snapshot drift"

    want_opt = json.loads((want_dir / "optimizer.json").read_text(encoding="utf-8"))
    assert optimizer_dict == want_opt, "OptimizerContract snapshot drift"
