"""Predicted-vs-real lap report (spec C, Task 6) — non-gating diagnostic.

Covers the pure comparison (physics-smell detection) and the exit-0 contract:
the report must ALWAYS succeed, even when a prediction is slower than a real
lap. Loaded by file path to dodge the pytest scripts-package collision.
"""
import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MOD_PATH = _PROJECT_ROOT / "scripts" / "report_vs_real_laps.py"
_spec = importlib.util.spec_from_file_location("report_vs_real_laps_mod", _MOD_PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
sys.modules["report_vs_real_laps_mod"] = m
compare_lap = m.compare_lap


def test_compare_flags_predicted_slower_as_smell():
    r = compare_lap("KCT", predicted_s=90.0, best_real_s=88.0)
    assert r["predicted_slower"] is True
    assert r["delta_s"] == 2.0


def test_compare_predicted_faster_is_clean():
    r = compare_lap("KCT", predicted_s=85.0, best_real_s=88.0)
    assert r["predicted_slower"] is False
    assert r["delta_s"] == -3.0


def test_compare_missing_real_is_not_a_smell():
    r = compare_lap("KCT", predicted_s=85.0, best_real_s=None)
    assert r["predicted_slower"] is False
    assert r["delta_s"] is None


def test_main_always_exits_0_even_on_smell(monkeypatch, tmp_path):
    import web.db_pg as db

    monkeypatch.setattr(db, "get_maint_connection", lambda: object())
    monkeypatch.setattr(db, "return_pg_connection", lambda c: None)
    # A worst-case row: prediction slower than real (a smell) must NOT fail the run.
    monkeypatch.setattr(
        m, "gather_rows",
        lambda conn, vc: [compare_lap("KCT", 90.0, 88.0)],
    )
    rc = m.main(["--json", "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "vs_real_laps.json").exists()
