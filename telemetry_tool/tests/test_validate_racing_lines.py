"""Racing-line release gate (spec C, §5) — synthetic tests of the pure core.

The PG-backed gather is not exercised here; these cover the gate logic: a
green set passes, a single red fails the whole gate, a validator error is
fail-safe (counts as red), and the CLI maps green->0 / red->2.
"""
import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load by explicit file path: under pytest the bare ``scripts`` package name
# collides with another scripts/ dir on the collection path, so import the
# module directly (same pattern as the migration tests).
_MOD_PATH = _PROJECT_ROOT / "scripts" / "validate_racing_lines.py"
_spec = importlib.util.spec_from_file_location("validate_racing_lines_mod", _MOD_PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
sys.modules["validate_racing_lines_mod"] = m
evaluate_lines = m.evaluate_lines
sol_from_points = m.sol_from_points


class _Rep:
    def __init__(self, ok):
        self.passed = ok

    def to_dict(self):
        return {"passed": self.passed}


def test_all_green_gate_passes():
    items = [("KCT/dry", None, None), ("MKR/wet", None, None)]
    all_ok, rows = evaluate_lines(items, validate=lambda s, t: _Rep(True))
    assert all_ok is True
    assert all(r["passed"] for r in rows)


def test_one_red_fails_the_whole_gate():
    def v(sol, track):
        return _Rep(track != "BAD")

    items = [("KCT/dry", None, "GOOD"), ("MKR/wet", None, "BAD")]
    all_ok, rows = evaluate_lines(items, validate=v)
    assert all_ok is False
    assert [r["label"] for r in rows if not r["passed"]] == ["MKR/wet"]


def test_validator_exception_is_fail_safe():
    def v(sol, track):
        raise RuntimeError("boom")

    all_ok, rows = evaluate_lines([("X/dry", None, None)], validate=v)
    assert all_ok is False
    assert rows[0]["detail"]["error"].startswith("boom")


def test_sol_from_points_maps_fields():
    sol = sol_from_points([{"d": 0.0, "n": 0.1, "v": 30.0},
                           {"d": 1.0, "n": -0.2, "v": 31.0}])
    assert list(sol.distance_m) == [0.0, 1.0]
    assert list(sol.lateral_offset_m) == [0.1, -0.2]
    assert list(sol.speed_mps) == [30.0, 31.0]


def test_main_maps_green_to_0_and_red_to_2(monkeypatch):
    import web.db_pg as db

    monkeypatch.setattr(db, "get_maint_connection", lambda: object())
    monkeypatch.setattr(db, "return_pg_connection", lambda c: None)
    monkeypatch.setattr(m, "gather_gt_items", lambda conn, vc: [("T/dry", None, None)])

    monkeypatch.setattr(m, "evaluate_lines", lambda items: (True, [{"label": "T/dry", "passed": True, "detail": {}}]))
    assert m.main(["--json"]) == 0

    monkeypatch.setattr(m, "evaluate_lines", lambda items: (False, [{"label": "T/dry", "passed": False, "detail": {}}]))
    assert m.main(["--json"]) == 2
