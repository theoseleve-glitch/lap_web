"""Fixtures for downstream workstreams — each JSON validates against its contract."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def load_fixture(name: str) -> dict:
    """Load a fixture by bare name (e.g. 'session_realife')."""
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))
