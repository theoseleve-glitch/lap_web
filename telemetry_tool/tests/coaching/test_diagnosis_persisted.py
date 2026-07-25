"""P2-Task 4: the per-corner diagnosis map is persisted into analysis_json.

Both blob builders (PG `_build_analysis_blob` and the desktop `sessions_v2` path)
must carry `corner_diagnosis` so the composer (Task 5) + consumers can read it —
mirroring how `coaching_v3` is persisted.
"""
from tasks.pipeline_tasks import _build_analysis_blob

_DIAG = {"1": {"3": {"label": "early_throttle", "confidence": "high"}}}


def test_build_analysis_blob_persists_corner_diagnosis():
    blob = _build_analysis_blob({"corner_diagnosis": _DIAG})
    assert blob.get("corner_diagnosis") == _DIAG


def test_absent_diagnosis_is_not_written():
    blob = _build_analysis_blob({})
    assert "corner_diagnosis" not in blob


def test_non_dict_diagnosis_is_ignored():
    blob = _build_analysis_blob({"corner_diagnosis": "not-a-dict"})
    assert "corner_diagnosis" not in blob
