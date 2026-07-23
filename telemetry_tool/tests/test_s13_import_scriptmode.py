"""Guard test: the coaching V3 stage must import cleanly under main.py's
script-mode sys.path.

main.py lives in telemetry_tool/ and is run as a script (or via
subprocess/`python main.py`), which puts telemetry_tool/ itself on
sys.path[0] -- NOT its parent. That means bare imports like
`from pipeline.stages import ...` and `from coaching...` resolve fine, but
`from telemetry_tool.coaching...` does NOT, because `telemetry_tool` is not
importable as a top-level package from within its own directory.

The pytest suite's conftest.py inserts a *different* sys.path entry (plus
pytest's own package-aware rootdir insertion), which happens to make
`telemetry_tool.coaching...` importable too -- masking the bug. This test
reproduces main.py's actual sys.path in a subprocess so the bug can't hide
behind the test suite's more permissive import environment.
"""
import subprocess
import sys
from pathlib import Path

TT_DIR = Path(__file__).resolve().parents[1]  # the telemetry_tool/ dir (== main.py's dir)


def test_coaching_stage_imports_under_scriptmode_syspath():
    """main.py puts telemetry_tool/ (not its parent) on sys.path. The coaching
    stage MUST import cleanly under that path, AND its in-function imports
    (inside run_coaching_analyzers / run_enhanced_coaching) must not use the
    `telemetry_tool.` prefix -- that raises ModuleNotFoundError there and
    silently degrades the stage to a near-empty v2 fallback."""
    code = (
        "import importlib;"
        "m = importlib.import_module('pipeline.stages.s13_coaching_v3');"
        # Exercise the in-function imports directly -- these are the ones
        # that actually crash under script-mode sys.path (the bad prefix is
        # inside the function bodies, not at module scope, so importing the
        # module alone does not trigger them).
        "bundle = m.run_coaching_analyzers(None, None, None, None, None, None);"
        "assert bundle == {"
        "'trail_brakes': [], 'exit_cascades': [], 'traction_budgets': [], "
        "'symptoms': [], 'throttle_lifts': [], 'weight_transfers': []"
        "}, bundle;"
        "import coaching.analyzers.trail_brake, coaching.composers.session_composer;"
        "print('OK')"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=str(TT_DIR),
        capture_output=True, text=True,
    )
    assert "ModuleNotFoundError" not in r.stderr, r.stderr
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
