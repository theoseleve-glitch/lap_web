"""Regression guard: the legacy Flask/Jinja2 race-strategy blueprint (1662
lines, 32 routes duplicating the JSON API + Next.js app) must stay retired.

Confirmed before deletion: nothing outside web/app.py's blueprint loader and
this file imports web.routes.race_strategy_v2. The *root* domain optimizer
module race_strategy_v2.py (imported by services/race_strategy.py) is a
different file and is untouched by this retirement. So is the standalone
web/templates/race_strategy.html, which belongs to web/routes/predictions.py
(a different, shared blueprint explicitly assigned to W1's cleanup scope) —
this file only removes race_strategy_v2_bp's own 5 templates.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_legacy_race_strategy_route_module_removed():
    """web/routes/race_strategy_v2.py must be deleted."""
    import importlib.util
    spec = importlib.util.find_spec("web.routes.race_strategy_v2")
    assert spec is None, "web/routes/race_strategy_v2.py should have been deleted"


def test_root_race_strategy_v2_domain_module_still_importable():
    """The ROOT race_strategy_v2.py (domain optimizer, used by
    services/race_strategy.py) must remain untouched by the retirement."""
    import importlib.util
    spec = importlib.util.find_spec("race_strategy_v2")
    assert spec is not None, "root race_strategy_v2.py must NOT be deleted"


def test_app_py_no_longer_registers_legacy_blueprint():
    """create_app() must not attempt to import/register race_strategy_v2_bp."""
    from web import app as app_module
    source = inspect.getsource(app_module.create_app)
    assert "race_strategy_v2" not in source, \
        "app.py's blueprint import list should no longer reference race_strategy_v2"


@pytest.mark.parametrize("relative_path", [
    "web/templates/race_strategy/index.html",
    "web/templates/race_strategy/config.html",
    "web/templates/race_strategy/detail.html",
    "web/templates/race_strategy/live.html",
    "web/templates/race_strategy/summary.html",
    "web/static/css/race_strategy.css",
    "web/static/js/race_strategy.js",
    "web/static/js/race_strategy_live.js",
])
def test_legacy_templates_and_static_assets_removed(relative_path):
    assert not (_PROJECT_ROOT / relative_path).exists(), \
        f"{relative_path} should have been deleted with the legacy blueprint"


def test_predictions_template_untouched():
    """web/templates/race_strategy.html belongs to predictions.py (W1's
    scope, a different blueprint) and must NOT be deleted by this task."""
    assert (_PROJECT_ROOT / "web/templates/race_strategy.html").exists(), \
        "race_strategy.html belongs to predictions.py — do not delete it here"
