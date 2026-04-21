"""Tests for SidecarStore — round-trip, missing-ref, idempotency."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd
import pytest

from telemetry_tool.storage.sidecar_store import SidecarMissing, SidecarStore
from telemetry_tool.web.schemas.contracts import SidecarRef, SourceLiteral


@pytest.fixture
def store(tmp_path) -> SidecarStore:
    return SidecarStore(root=tmp_path)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "time_s": [0.0, 0.1, 0.2],
        "speed_mps": [12.0, 12.5, 13.0],
        "lat": [43.1, 43.1, 43.2],
        "lon": [5.6, 5.6, 5.6],
    })


def test_save_then_load_roundtrips(store):
    sid, ws = uuid4().hex, "ws-1"
    ref = store.save(
        session_id=sid, workspace_id=ws,
        source=SourceLiteral.REAL_LIFE, df=_sample_df(),
    )
    assert isinstance(ref, SidecarRef)
    assert ref.format == "parquet"
    assert ref.object_key.endswith(f"{ws}/{sid}/raw.parquet")
    assert ref.sha256 and len(ref.sha256) == 64
    assert ref.size_bytes and ref.size_bytes > 0

    df2 = store.load(ref)
    pd.testing.assert_frame_equal(df2, _sample_df())


def test_load_missing_raises(store):
    bogus = SidecarRef(object_key="nope/nope/raw.parquet")
    with pytest.raises(SidecarMissing):
        store.load(bogus)


def test_save_is_idempotent_on_identical_df(store):
    sid, ws = uuid4().hex, "ws-1"
    ref1 = store.save(
        session_id=sid, workspace_id=ws,
        source=SourceLiteral.REAL_LIFE, df=_sample_df(),
    )
    ref2 = store.save(
        session_id=sid, workspace_id=ws,
        source=SourceLiteral.REAL_LIFE, df=_sample_df(),
    )
    # Same content → same sha256, same path, same size.
    assert ref1.sha256 == ref2.sha256
    assert ref1.object_key == ref2.object_key
    assert ref1.size_bytes == ref2.size_bytes
