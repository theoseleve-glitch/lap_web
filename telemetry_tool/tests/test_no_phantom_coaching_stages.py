import pathlib
TT = pathlib.Path(__file__).resolve().parents[1]

def test_no_debrief_engine_reference():
    src = (TT / "pipeline" / "stages" / "s13_scoring.py").read_text(encoding="utf-8")
    assert "debrief_engine" not in src, "phantom debrief_engine reference still present"

def test_practice_plan_route_removed():
    src = (TT / "web" / "routes" / "data_v2.py").read_text(encoding="utf-8")
    assert "/practice-plan" not in src, "dead practice-plan route still registered"

def test_persist_coaching_v3_removed():
    src = (TT / "pipeline" / "stages" / "s13_coaching_v3.py").read_text(encoding="utf-8")
    assert "def persist_coaching_v3" not in src, "orphaned persist_coaching_v3 still present"

def test_phase0_check_no_debrief_engine_reference():
    src = (TT / "phase0_check.py").read_text(encoding="utf-8")
    assert "debrief_engine" not in src, (
        "phantom debrief_engine module still required by phase0_check.py's "
        "check_core_imports() -- that module never existed, so run_phase0() "
        "always raises ImportError"
    )
