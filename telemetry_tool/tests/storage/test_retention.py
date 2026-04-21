"""Tests for the sidecar retention task (W9.T9.3)."""
from __future__ import annotations

import os
import time

import pandas as pd

from tasks.retention_tasks import enforce_sidecar_retention
from telemetry_tool.storage.sidecar_store import SidecarStore
from telemetry_tool.web.schemas.contracts import SourceLiteral


def test_sidecars_older_than_retention_are_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDECAR_ROOT", str(tmp_path))
    monkeypatch.setenv("SIDECAR_RETENTION_DAYS", "30")
    store = SidecarStore(root=tmp_path)
    df = pd.DataFrame({"a": [1, 2, 3]})

    fresh_ref = store.save(
        session_id="sfresh", workspace_id="w1",
        source=SourceLiteral.REAL_LIFE, df=df,
    )
    stale_ref = store.save(
        session_id="sstale", workspace_id="w1",
        source=SourceLiteral.REAL_LIFE, df=df,
    )
    # Age the stale file by setting its mtime to 45 days ago.
    stale_path = tmp_path / stale_ref.object_key
    old_time = time.time() - 45 * 86400
    os.utime(stale_path, (old_time, old_time))

    deleted = enforce_sidecar_retention()  # runs synchronously — no Celery needed
    assert deleted == 1
    assert not stale_path.exists()
    assert (tmp_path / fresh_ref.object_key).exists()
