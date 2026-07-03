"""Robustness stability_basis provenance — measured vs neutral fallback.

Pure labelling: the degraded (0.5) neutral-stability path must stay
machine-readable without changing the score.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scoring.robustness import _score_robustness


def test_measured_when_yaw_present():
    score, detail = _score_robustness(
        {"n_laps": 20, "early_mean_s": 60.0, "late_mean_s": 60.3,
         "early_yaw_var": 0.01, "late_yaw_var": 0.012}, {},
    )
    assert detail["stability_basis"] == "measured"


def test_neutral_when_yaw_absent_and_score_unchanged():
    m = {"n_laps": 20, "early_mean_s": 60.0, "late_mean_s": 60.3}
    score, detail = _score_robustness(m, {})
    assert detail["stability_basis"] == "neutral_no_yaw"
    # Score must be identical to today's neutral-stability behaviour.
    from scoring.constants import MAX_ROBUSTNESS, ROBUST_W_FADE, ROBUST_W_STABILITY
    from scoring.helpers import _ratio_score
    from scoring.constants import ROBUST_FADE_FULL, ROBUST_FADE_ZERO
    fade_r = _ratio_score((60.3 - 60.0) / 60.0, ROBUST_FADE_FULL, ROBUST_FADE_ZERO,
                          higher_is_better=False)
    expected = round((ROBUST_W_FADE * fade_r + ROBUST_W_STABILITY * 0.5) * MAX_ROBUSTNESS, 4)
    assert score == expected
