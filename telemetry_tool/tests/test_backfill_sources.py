"""Idempotency contract for the backfill script (W9.T9.4).

Runs twice; asserts the second run touches zero rows. PG-gated via
TELEMETRY_PG_URL_TEST — SKIPs on non-PG dev boxes. CI must set the env
var against a disposable PG.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("TELEMETRY_PG_URL_TEST"),
    reason="needs disposable PG; set TELEMETRY_PG_URL_TEST",
)


def _run(args: list[str]) -> tuple[int, str]:
    env = {**os.environ, "TELEMETRY_PG_URL": os.environ["TELEMETRY_PG_URL_TEST"]}
    p = subprocess.run(
        [sys.executable, "scripts/backfill_session_sources.py", *args],
        capture_output=True, text=True, env=env, check=False,
    )
    return p.returncode, p.stdout + p.stderr


def test_backfill_is_idempotent(disposable_pg):  # fixture seeds 2 rows with source=NULL
    rc1, out1 = _run([])
    assert rc1 == 0, out1
    assert "updated 2 row(s)" in out1, out1

    rc2, out2 = _run([])
    assert rc2 == 0, out2
    assert "updated 0 row(s)" in out2, out2
