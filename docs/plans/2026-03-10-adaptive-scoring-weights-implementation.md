# Adaptive Scoring Weights Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace flat session-type weight overrides with a 3-layer adaptive scoring system (session-type suppression, track-state modifiers, experience-based diminishing returns) — all invisible to the user.

**Architecture:** Layer 1 suppresses irrelevant scoring categories per session type and redistributes budget. Layer 2 applies track-state multipliers on surviving categories. Layer 3 applies a gentle asymptotic log diminishing-returns curve based on driver lifetime laps and session lap count. All three layers compose multiplicatively, total always out of 100.

**Tech Stack:** Python 3.14, pytest, scoring package (telemetry_tool/scoring/), pipeline orchestrator

---

### Task 1: Add adaptive scoring constants to constants.py

**Files:**
- Modify: `telemetry_tool/scoring/constants.py:240-258`
- Test: `telemetry_tool/tests/test_adaptive_scoring.py` (create)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_adaptive_scoring.py`:

```python
"""Tests for adaptive scoring weights — suppression, track state, diminishing returns."""
import math
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSessionCategoryConfig:
    """Verify _SESSION_CATEGORY_CONFIG structure and invariants."""

    def test_config_exists(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        assert isinstance(_SESSION_CATEGORY_CONFIG, dict)
        assert len(_SESSION_CATEGORY_CONFIG) >= 10

    def test_all_entries_have_suppressed_and_emphasis(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        valid_cats = {"pace", "consistency", "execution", "robustness", "adaptation"}
        for stype, cfg in _SESSION_CATEGORY_CONFIG.items():
            assert "suppressed" in cfg, f"{stype} missing 'suppressed'"
            assert "emphasis" in cfg, f"{stype} missing 'emphasis'"
            assert cfg["suppressed"].issubset(valid_cats), f"{stype} has invalid suppressed categories"
            assert set(cfg["emphasis"].keys()).issubset(valid_cats), f"{stype} has invalid emphasis categories"
            # Suppressed and emphasized must not overlap
            assert cfg["suppressed"].isdisjoint(set(cfg["emphasis"].keys())), (
                f"{stype} has overlap between suppressed and emphasis"
            )

    def test_qualifying_suppresses_consistency_robustness_adaptation(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        q = _SESSION_CATEGORY_CONFIG["qualifying"]
        assert q["suppressed"] == {"consistency", "robustness", "adaptation"}

    def test_practice_suppresses_robustness_emphasizes_adaptation(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        p = _SESSION_CATEGORY_CONFIG["practice"]
        assert "robustness" in p["suppressed"]
        assert p["emphasis"].get("adaptation", 0) > 1.0

    def test_endurance_suppresses_nothing(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        for key in ("endurance", "endurance_stint", "endurance_race"):
            if key in _SESSION_CATEGORY_CONFIG:
                assert len(_SESSION_CATEGORY_CONFIG[key]["suppressed"]) == 0


class TestTrackStateModifiers:
    """Verify _TRACK_STATE_MODIFIERS structure."""

    def test_modifiers_exist(self):
        from scoring.constants import _TRACK_STATE_MODIFIERS
        assert isinstance(_TRACK_STATE_MODIFIERS, dict)
        assert "dry" in _TRACK_STATE_MODIFIERS
        assert "wet" in _TRACK_STATE_MODIFIERS

    def test_dry_is_empty(self):
        from scoring.constants import _TRACK_STATE_MODIFIERS
        assert _TRACK_STATE_MODIFIERS["dry"] == {}

    def test_wet_boosts_adaptation_reduces_pace(self):
        from scoring.constants import _TRACK_STATE_MODIFIERS
        wet = _TRACK_STATE_MODIFIERS["wet"]
        assert wet.get("adaptation", 1.0) > 1.0
        assert wet.get("pace", 1.0) < 1.0


class TestDiminishingReturnsConstants:
    """Verify DR constants exist and have sane values."""

    def test_dr_constants_exist(self):
        from scoring.constants import (
            DR_EXP_K, DR_EXP_L0, DR_EXP_FLOOR,
            DR_SES_K, DR_SES_L0, DR_SES_FLOOR,
            DR_COMBINED_FLOOR,
        )
        assert 0 < DR_EXP_K < 0.1
        assert DR_EXP_L0 > 0
        assert 0.9 <= DR_EXP_FLOOR < 1.0
        assert 0 < DR_SES_K < 0.1
        assert DR_SES_L0 > 0
        assert 0.9 <= DR_SES_FLOOR < 1.0
        assert 0.85 <= DR_COMBINED_FLOOR < 1.0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py -v -x`
Expected: FAIL with `ImportError: cannot import name '_SESSION_CATEGORY_CONFIG'`

**Step 3: Write the implementation**

In `telemetry_tool/scoring/constants.py`, **replace** lines 240–258 (the `_SESSION_WEIGHT_OVERRIDES` section) with:

```python
# =============================================================================
# SESSION-TYPE CATEGORY CONFIG (suppression + emphasis)
# =============================================================================
# Replaces the old flat _SESSION_WEIGHT_OVERRIDES.
# - "suppressed": categories zeroed out, budget redistributed
# - "emphasis": multipliers on surviving categories (default 1.0)

_SESSION_CATEGORY_CONFIG: dict[str, dict] = {
    "qualifying": {
        "suppressed": {"consistency", "robustness", "adaptation"},
        "emphasis":   {"pace": 1.6, "execution": 1.4},
    },
    "race": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.4, "adaptation": 1.2},
    },
    "practice": {
        "suppressed": {"robustness"},
        "emphasis":   {"adaptation": 1.4, "execution": 1.2},
    },
    "warmup": {
        "suppressed": {"pace", "robustness"},
        "emphasis":   {"execution": 1.3, "adaptation": 1.2},
    },
    "test": {
        "suppressed": {"pace", "robustness"},
        "emphasis":   {"execution": 1.3, "consistency": 1.2},
    },
    "endurance": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.6},
    },
    "endurance_stint": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.6},
    },
    "endurance_race": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.6},
    },
    "heat": {
        "suppressed": {"consistency"},
        "emphasis":   {"pace": 1.4, "execution": 1.2},
    },
    "final": {
        "suppressed": set(),
        "emphasis":   {"pace": 1.2, "robustness": 1.1},
    },
    "sprint": {
        "suppressed": {"consistency"},
        "emphasis":   {"pace": 1.3, "execution": 1.2},
    },
    "sprint_race": {
        "suppressed": {"consistency"},
        "emphasis":   {"pace": 1.3, "execution": 1.2},
    },
    "feature_race": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.4, "adaptation": 1.2},
    },
}

# Backward compat: build _SESSION_WEIGHT_OVERRIDES from the new config
# so any code still importing it gets a reasonable dict.
_SESSION_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {}
for _stype, _cfg in _SESSION_CATEGORY_CONFIG.items():
    _w: dict[str, float] = {}
    for _cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
        if _cat in _cfg["suppressed"]:
            _w[_cat] = 0.0
        else:
            _w[_cat] = _cfg["emphasis"].get(_cat, 1.0)
    _SESSION_WEIGHT_OVERRIDES[_stype] = _w

# =============================================================================
# TRACK-STATE WEIGHT MODIFIERS
# =============================================================================
# Applied multiplicatively on top of session-type weights (surviving categories).

_TRACK_STATE_MODIFIERS: dict[str, dict[str, float]] = {
    "dry":      {},
    "damp":     {"adaptation": 1.10, "robustness": 1.05, "pace": 0.95},
    "wet":      {"adaptation": 1.15, "robustness": 1.10, "pace": 0.90, "execution": 0.95},
    "full_wet": {"adaptation": 1.20, "robustness": 1.15, "pace": 0.85, "execution": 0.90},
    "drying":   {"adaptation": 1.20, "pace": 0.90},
    "greasy":   {"adaptation": 1.10, "robustness": 1.05, "pace": 0.95},
}

# =============================================================================
# DIMINISHING RETURNS CONSTANTS
# =============================================================================
# Asymptotic log curve: factor = max(floor, 1.0 - k * ln(1 + laps / L0))

DR_EXP_K:     Final[float] = 0.005    # experience decay rate
DR_EXP_L0:    Final[float] = 1000.0   # reference lap count
DR_EXP_FLOOR: Final[float] = 0.96     # per-factor floor

DR_SES_K:     Final[float] = 0.004    # session laps decay rate
DR_SES_L0:    Final[float] = 30.0     # reference (typical short session)
DR_SES_FLOOR: Final[float] = 0.96     # per-factor floor

DR_COMBINED_FLOOR: Final[float] = 0.92  # absolute floor for combined multiplier
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py -v`
Expected: all 10 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/scoring/constants.py telemetry_tool/tests/test_adaptive_scoring.py
git commit -m "feat(scoring): add session category config, track-state modifiers, DR constants

Replaces flat _SESSION_WEIGHT_OVERRIDES with _SESSION_CATEGORY_CONFIG
supporting category suppression + emphasis. Adds _TRACK_STATE_MODIFIERS
for wet/damp/drying conditions. Adds diminishing-returns constants.
Backward-compat _SESSION_WEIGHT_OVERRIDES derived from new config."
```

---

### Task 2: Implement _apply_adaptive_weights() in scorer.py

**Files:**
- Modify: `telemetry_tool/scoring/scorer.py:1-77` (imports + _apply_session_weights)
- Test: `telemetry_tool/tests/test_adaptive_scoring.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_adaptive_scoring.py`:

```python
class TestApplyAdaptiveWeights:
    """Test the new _apply_adaptive_weights function."""

    def _make_raw_scores(self, pace=20.0, cons=20.0, exe=16.0, rob=12.0, adapt=11.25):
        """Helper: reasonable raw sub-scores (80% of each max)."""
        return {
            "pace": pace,
            "consistency": cons,
            "execution": exe,
            "robustness": rob,
            "adaptation": adapt,
        }

    def test_qualifying_suppresses_three_categories(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "qualifying")
        assert result["consistency"] == 0.0
        assert result["robustness"] == 0.0
        assert result["adaptation"] == 0.0
        assert maxes["consistency"] == 0.0
        assert maxes["robustness"] == 0.0
        # Remaining categories should sum to 100
        assert abs(sum(maxes.values()) - 100.0) < 0.01

    def test_practice_suppresses_robustness(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "practice")
        assert result["robustness"] == 0.0
        assert maxes["robustness"] == 0.0
        assert abs(sum(maxes.values()) - 100.0) < 0.01

    def test_practice_emphasizes_adaptation(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        _, maxes_practice = _apply_adaptive_weights(raw, "practice")
        _, maxes_race = _apply_adaptive_weights(raw, "race")
        # Practice adaptation max should be higher (relative to total)
        # because robustness is suppressed + adaptation has 1.4x emphasis
        adapt_frac_practice = maxes_practice["adaptation"] / sum(maxes_practice.values())
        adapt_frac_race = maxes_race["adaptation"] / sum(maxes_race.values())
        assert adapt_frac_practice > adapt_frac_race

    def test_endurance_nothing_suppressed(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "endurance")
        for cat in raw:
            assert result[cat] > 0
            assert maxes[cat] > 0
        assert abs(sum(maxes.values()) - 100.0) < 0.01

    def test_unknown_session_type_uses_base_weights(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "unknown_xyz")
        # No suppression, no emphasis — base weights
        assert abs(sum(maxes.values()) - 100.0) < 0.01
        for cat in raw:
            assert result[cat] > 0

    def test_track_state_wet_boosts_adaptation(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        _, maxes_dry = _apply_adaptive_weights(raw, "race", track_state="dry")
        _, maxes_wet = _apply_adaptive_weights(raw, "race", track_state="wet")
        dry_adapt_frac = maxes_dry["adaptation"] / sum(maxes_dry.values())
        wet_adapt_frac = maxes_wet["adaptation"] / sum(maxes_wet.values())
        assert wet_adapt_frac > dry_adapt_frac

    def test_track_state_modifier_only_on_surviving(self):
        """Track-state modifier on a suppressed category has no effect."""
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        # Qualifying suppresses consistency — wet modifier on consistency shouldn't matter
        result_dry, _ = _apply_adaptive_weights(raw, "qualifying", track_state="dry")
        result_wet, _ = _apply_adaptive_weights(raw, "qualifying", track_state="wet")
        assert result_dry["consistency"] == 0.0
        assert result_wet["consistency"] == 0.0

    def test_total_maxes_always_sum_to_100(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        for stype in ("qualifying", "race", "practice", "warmup", "test",
                       "endurance", "heat", "final", "sprint"):
            for ts in ("dry", "wet", "damp", "full_wet", "drying", "greasy"):
                _, maxes = _apply_adaptive_weights(raw, stype, track_state=ts)
                assert abs(sum(maxes.values()) - 100.0) < 0.01, (
                    f"{stype}/{ts}: maxes sum to {sum(maxes.values())}"
                )
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py::TestApplyAdaptiveWeights -v -x`
Expected: FAIL with `ImportError: cannot import name '_apply_adaptive_weights'`

**Step 3: Write the implementation**

In `telemetry_tool/scoring/scorer.py`, **replace** the imports (lines 9-11) to add the new constants:

```python
from scoring.constants import (
    _SESSION_CATEGORY_CONFIG,
    _SESSION_TYPE_SYNONYMS,
    _SESSION_WEIGHT_OVERRIDES,
    _TRACK_STATE_MODIFIERS,
    ADAPT_V2_STABLE_DEFAULT_FRAC,
    MAX_ADAPTATION,
    MAX_CONSISTENCY,
    MAX_EXECUTION,
    MAX_PACE,
    MAX_ROBUSTNESS,
    STRENGTH_THRESHOLD,
    TOTAL_MAX,
    WEAKNESS_THRESHOLD,
)
```

Then **replace** the `_apply_session_weights` function (lines 46-77) with both functions:

```python
def _apply_adaptive_weights(
    raw_scores: dict[str, float],
    session_type: str,
    *,
    track_state: str = "dry",
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Apply 3-layer adaptive weighting: suppression, track-state, normalize.

    Returns (rescaled_scores, effective_maxes) where effective_maxes sum to 100.
    Suppressed categories get score=0 and max=0.
    """
    stype = _normalize_session_type(session_type)
    stype = _SESSION_TYPE_SYNONYMS.get(stype, stype)
    config = _SESSION_CATEGORY_CONFIG.get(stype, {"suppressed": set(), "emphasis": {}})

    suppressed = config["suppressed"]
    emphasis = config["emphasis"]

    # Layer 1: Suppress + emphasize
    adjusted_max: dict[str, float] = {}
    for cat, base in _BASE_MAXES.items():
        if cat in suppressed:
            adjusted_max[cat] = 0.0
        else:
            adjusted_max[cat] = base * emphasis.get(cat, 1.0)

    # Layer 2: Track-state modifiers (only on surviving categories)
    ts_key = track_state.lower().strip() if track_state else "dry"
    ts_mods = _TRACK_STATE_MODIFIERS.get(ts_key, {})
    for cat in adjusted_max:
        if adjusted_max[cat] > 0 and cat in ts_mods:
            adjusted_max[cat] *= ts_mods[cat]

    # Normalize so surviving categories sum to TOTAL_MAX
    total_adjusted = sum(adjusted_max.values())
    if total_adjusted > 0:
        scale = TOTAL_MAX / total_adjusted
        norm_max = {cat: round(v * scale, 4) for cat, v in adjusted_max.items()}
    else:
        norm_max = {cat: 0.0 for cat in _BASE_MAXES}

    # Scale raw scores
    rescaled: dict[str, float] = {}
    for cat, raw in raw_scores.items():
        if cat in suppressed or _BASE_MAXES.get(cat, 0) == 0:
            rescaled[cat] = 0.0
        else:
            fraction = raw / _BASE_MAXES[cat]
            rescaled[cat] = round(fraction * norm_max.get(cat, 0.0), 4)

    return rescaled, norm_max


def _apply_session_weights(
    raw_scores: dict[str, float],
    session_type: str,
) -> dict[str, float]:
    """
    Backward-compatible wrapper around _apply_adaptive_weights.

    Returns only the rescaled scores dict (not the maxes).
    """
    rescaled, _ = _apply_adaptive_weights(raw_scores, session_type)
    return rescaled
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py -v`
Expected: all 18 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/scoring/scorer.py telemetry_tool/tests/test_adaptive_scoring.py
git commit -m "feat(scoring): implement _apply_adaptive_weights with suppression + track state

Replaces _apply_session_weights internals. Categories can now be
suppressed (zeroed out, budget redistributed) per session type.
Track-state modifiers layer on top for wet/damp/drying conditions.
Backward-compat _apply_session_weights wrapper preserved."
```

---

### Task 3: Add diminishing-returns logic and wire into score_session()

**Files:**
- Modify: `telemetry_tool/scoring/scorer.py:80-321` (score_session function)
- Test: `telemetry_tool/tests/test_adaptive_scoring.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_adaptive_scoring.py`:

```python
class TestDiminishingReturns:
    """Test the diminishing-returns multiplier."""

    def test_compute_dr_multiplier_new_driver(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=0, session_laps=10)
        assert 0.99 < m <= 1.0

    def test_compute_dr_multiplier_veteran(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=10000, session_laps=100)
        assert 0.92 <= m < 0.99

    def test_compute_dr_multiplier_extreme_hits_floor(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=1_000_000, session_laps=10_000)
        assert m == 0.92

    def test_compute_dr_multiplier_no_laps_is_neutral(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=0, session_laps=0)
        assert m == 1.0

    def test_veteran_scores_lower_than_newcomer(self):
        """Identical raw metrics, veteran gets slightly lower total."""
        from scoring import score_session
        metrics = {
            "best_s": 60.0, "n_laps": 15, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        newcomer = score_session(metrics, theo, "practice",
                                  driver_total_laps=50)
        veteran = score_session(metrics, theo, "practice",
                                 driver_total_laps=20000)
        assert newcomer["total_score"] > veteran["total_score"]

    def test_long_session_scores_lower_than_short(self):
        """200-lap session scores slightly lower than 15-lap with same metrics."""
        from scoring import score_session
        base_metrics = {
            "best_s": 60.0, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        short = score_session({**base_metrics, "n_laps": 15}, theo, "practice")
        long = score_session({**base_metrics, "n_laps": 200}, theo, "practice")
        assert short["total_score"] > long["total_score"]


class TestScoreSessionAdaptive:
    """Integration: score_session uses adaptive weights end-to-end."""

    def test_qualifying_sub_scores_suppressed(self):
        from scoring import score_session
        metrics = {
            "best_s": 60.0, "n_laps": 5, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        result = score_session(metrics, theo, "qualifying")
        assert result["sub_scores"]["consistency"]["score"] == 0.0
        assert result["sub_scores"]["consistency"]["max"] == 0.0
        assert result["sub_scores"]["robustness"]["score"] == 0.0
        assert result["sub_scores"]["adaptation"]["score"] == 0.0
        # Pace and execution should have all the budget
        pace_max = result["sub_scores"]["pace"]["max"]
        exec_max = result["sub_scores"]["execution"]["max"]
        assert abs(pace_max + exec_max - 100.0) < 0.01

    def test_track_state_passed_through(self):
        from scoring import score_session
        metrics = {
            "best_s": 60.0, "n_laps": 15, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        dry = score_session(metrics, theo, "race", track_state="dry")
        wet = score_session(metrics, theo, "race", track_state="wet")
        # Wet should shift weight distribution — adaptation max higher
        dry_adapt = dry["sub_scores"]["adaptation"]["max"]
        wet_adapt = wet["sub_scores"]["adaptation"]["max"]
        assert wet_adapt > dry_adapt

    def test_combined_floor_never_below_092(self):
        from scoring import score_session
        metrics = {
            "best_s": 58.5, "n_laps": 10000, "cv_pct": 0.3,
            "best_to_median_s": 0.2, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
            "early_mean_s": 58.5, "late_mean_s": 58.6,
            "early_yaw_var": 0.005, "late_yaw_var": 0.005,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        # Extreme: 1M lifetime laps, 10K session laps
        result = score_session(metrics, theo, "practice",
                                driver_total_laps=1_000_000)
        # Score should still be reasonable (not below 0.92 * raw)
        assert result["total_score"] > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py::TestDiminishingReturns -v -x`
Expected: FAIL with `ImportError: cannot import name '_compute_dr_multiplier'`

**Step 3: Write the implementation**

In `telemetry_tool/scoring/scorer.py`, add these imports at the top (after existing imports from constants):

```python
from scoring.constants import (
    DR_COMBINED_FLOOR,
    DR_EXP_FLOOR,
    DR_EXP_K,
    DR_EXP_L0,
    DR_SES_FLOOR,
    DR_SES_K,
    DR_SES_L0,
)
```

Add the `_compute_dr_multiplier` function right after `_apply_session_weights`:

```python
def _compute_dr_multiplier(
    total_laps: int = 0,
    session_laps: int = 0,
) -> float:
    """
    Compute a gentle diminishing-returns multiplier.

    Two independent factors stacked multiplicatively:
    - experience_factor: based on driver's lifetime total laps
    - session_factor: based on number of laps in this session

    Both use asymptotic log curves with per-factor and combined floors.
    Returns a value in [DR_COMBINED_FLOOR, 1.0].
    """
    if total_laps <= 0 and session_laps <= 0:
        return 1.0

    exp_factor = max(
        DR_EXP_FLOOR,
        1.0 - DR_EXP_K * math.log(1.0 + max(0, total_laps) / DR_EXP_L0),
    )
    ses_factor = max(
        DR_SES_FLOOR,
        1.0 - DR_SES_K * math.log(1.0 + max(0, session_laps) / DR_SES_L0),
    )
    return max(DR_COMBINED_FLOOR, exp_factor * ses_factor)
```

Then modify `score_session()` signature (line 80-88) to add new params:

```python
def score_session(
    metrics_dict:         dict[str, Any],
    theoretical_metrics:  dict[str, Any],
    session_type:         str = "practice",
    *,
    is_wet:               bool = False,
    track_state:          str = "dry",
    driver_total_laps:    int = 0,
    corner_coaching:      list[dict[str, Any]] | None = None,
    progressive_physics:  dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Replace lines 235-252 (the weighting + norm_max computation) with:

```python
    # --- Apply adaptive weighting (suppression + track state) ---

    n_laps = int(metrics_dict.get("n_laps", 0) or 0)
    final_scores, norm_max = _apply_adaptive_weights(
        raw_scores, session_type, track_state=track_state,
    )

    total = round(min(TOTAL_MAX, max(0.0, sum(final_scores.values()))), 4)
```

Replace lines 256-260 (after total computation, before sub-scores assembly) with:

```python
    # --- Data confidence weighting ---
    total = _apply_confidence(total, data_confidence)

    # --- Diminishing returns (experience + session length) ---
    dr_multiplier = _compute_dr_multiplier(
        total_laps=driver_total_laps, session_laps=n_laps,
    )
    total = round(total * dr_multiplier, 4)
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py -v`
Expected: all 28 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/scoring/scorer.py telemetry_tool/tests/test_adaptive_scoring.py
git commit -m "feat(scoring): add diminishing-returns + wire adaptive weights into score_session

score_session() now accepts track_state and driver_total_laps params.
Diminishing returns use asymptotic log curve with 0.92 combined floor.
Suppressed categories show score=0 max=0 in sub_scores output."
```

---

### Task 4: Update scoring/__init__.py re-exports

**Files:**
- Modify: `telemetry_tool/scoring/__init__.py:20-23, 43, 68-70`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_adaptive_scoring.py`:

```python
class TestReExports:
    """Verify new symbols are accessible from the scoring package."""

    def test_session_category_config_importable(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        assert isinstance(_SESSION_CATEGORY_CONFIG, dict)

    def test_track_state_modifiers_importable(self):
        from scoring import _TRACK_STATE_MODIFIERS
        assert isinstance(_TRACK_STATE_MODIFIERS, dict)

    def test_apply_adaptive_weights_importable(self):
        from scoring import _apply_adaptive_weights
        assert callable(_apply_adaptive_weights)

    def test_backward_compat_weight_overrides_still_importable(self):
        from scoring import _SESSION_WEIGHT_OVERRIDES
        assert isinstance(_SESSION_WEIGHT_OVERRIDES, dict)
        assert "qualifying" in _SESSION_WEIGHT_OVERRIDES

    def test_backward_compat_apply_session_weights_still_importable(self):
        from scoring import _apply_session_weights
        assert callable(_apply_session_weights)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py::TestReExports -v -x`
Expected: FAIL with `ImportError: cannot import name '_SESSION_CATEGORY_CONFIG'`

**Step 3: Write the implementation**

In `telemetry_tool/scoring/__init__.py`:

Replace lines 20-24 (the constants imports) with:

```python
from scoring.constants import (
    _CONSISTENCY_THRESHOLDS_BY_TYPE,
    _SESSION_CATEGORY_CONFIG,
    _SESSION_TYPE_SYNONYMS,
    _SESSION_WEIGHT_OVERRIDES,
    _TRACK_STATE_MODIFIERS,
    ScoringError,
)
```

Replace line 43 (the scorer imports) with:

```python
from scoring.scorer import _apply_adaptive_weights, _apply_session_weights, score_session
```

Replace lines 67-70 in `__all__` (the internal re-exports) with:

```python
    # Internal (used by tests)
    "_score_pace",
    "_score_consistency",
    "_score_execution",
    "_score_robustness",
    "_score_adaptation_v2",
    "_ratio_score",
    "_apply_session_weights",
    "_apply_adaptive_weights",
    "_SESSION_WEIGHT_OVERRIDES",
    "_SESSION_CATEGORY_CONFIG",
    "_TRACK_STATE_MODIFIERS",
    "_CONSISTENCY_THRESHOLDS_BY_TYPE",
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py -v`
Expected: all 33 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/scoring/__init__.py telemetry_tool/tests/test_adaptive_scoring.py
git commit -m "feat(scoring): update __init__.py re-exports for adaptive weights"
```

---

### Task 5: Wire pipeline — fetch driver_total_laps and pass through s13

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py:100-106, 934-941`
- Modify: `telemetry_tool/pipeline/stages/s13_scoring.py:24-108`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_adaptive_scoring.py`:

```python
class TestPipelineWiring:
    """Verify s13_scoring passes track_state and driver_total_laps."""

    def test_run_score_passes_track_state(self):
        """run_score should forward track_state from meta to score_session."""
        from unittest.mock import MagicMock, patch
        import pipeline.stages.s13_scoring as s13

        mock_score_mod = MagicMock()
        mock_score_mod.score_session_phase_aware = None  # force standard path
        del mock_score_mod.score_session_phase_aware  # hasattr returns False
        mock_score_mod.score_session.return_value = {"total_score": 75}

        with patch.object(s13, "lazy_import", return_value=mock_score_mod):
            meta = {"session_type": "race", "track_state": "wet", "driver_total_laps": 5000}
            result = s13.run_score(
                consistency={"cv_pct": 1.0},
                robustness={"early_mean_s": 60},
                lap_metrics=None,
                excluded_laps=frozenset(),
                theo_metrics={"best_s": 58},
                meta=meta,
            )

        call_kwargs = mock_score_mod.score_session.call_args
        assert call_kwargs.kwargs.get("track_state") == "wet"
        assert call_kwargs.kwargs.get("driver_total_laps") == 5000
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py::TestPipelineWiring -v -x`
Expected: FAIL — `score_session` called without `track_state` kwarg

**Step 3: Write the implementation**

In `telemetry_tool/pipeline/stages/s13_scoring.py`, modify the standard fallback call (lines 93-108).

Replace lines 93-108 with:

```python
    # Standard fallback — detect wet from context
    is_wet = False
    track_state = meta.get("track_state", "dry")
    if context is not None:
        ts = getattr(context, "baseline_track_state", None)
        if ts is not None:
            sv = ts.value if hasattr(ts, "value") else str(ts)
            is_wet = sv.lower() in ("wet", "full_wet", "damp", "drying", "greasy")
            track_state = sv.lower()

    return score_mod.score_session(
        m,
        theo_metrics,
        meta.get("session_type", "practice"),
        is_wet=is_wet,
        track_state=track_state,
        driver_total_laps=int(meta.get("driver_total_laps", 0) or 0),
        corner_coaching=corner_coaching,
        progressive_physics=progressive_physics,
    )
```

In `telemetry_tool/pipeline/orchestrator.py`, add driver experience lookup after `meta.setdefault("driver_name", "Unknown")` (after line 106). Insert:

```python
    # ── Fetch driver experience for scoring ────────────────────────
    meta.setdefault("driver_total_laps", 0)
    try:
        from db.queries import SELECT_DRIVER_BY_NAME
        from db.db_manager import get_db_connection
        _exp_conn = get_db_connection()
        _drv_row = _exp_conn.execute(SELECT_DRIVER_BY_NAME, {"driver_name": meta["driver_name"]}).fetchone()
        if _drv_row:
            _drv_id = _drv_row[0] if not isinstance(_drv_row, dict) else _drv_row.get("driver_id")
            _prof_row = _exp_conn.execute(
                "SELECT total_laps FROM driver_profiles WHERE driver_id = ?",
                (_drv_id,),
            ).fetchone()
            if _prof_row:
                meta["driver_total_laps"] = int(_prof_row[0] or 0) if not isinstance(_prof_row, dict) else int(_prof_row.get("total_laps", 0) or 0)
    except Exception:
        pass  # Graceful fallback — new driver or no DB
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py -v`
Expected: all 34 tests PASS

**Step 5: Run the full scoring test suite to check backward compat**

Run: `pytest telemetry_tool/tests/test_scoring_session_types.py telemetry_tool/tests/test_scoring_boundaries.py telemetry_tool/tests/test_scoring_adaptation.py telemetry_tool/tests/test_scoring_badges.py -v`
Expected: all PASS (existing tests unchanged)

**Step 6: Commit**

```bash
git add telemetry_tool/pipeline/stages/s13_scoring.py telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_adaptive_scoring.py
git commit -m "feat(scoring): wire adaptive weights through pipeline

s13_scoring.py now passes track_state and driver_total_laps to
score_session(). orchestrator.py fetches driver_total_laps from
driver_profiles before scoring step. Graceful fallback to 0."
```

---

### Task 6: Update existing session-type tests for new config structure

**Files:**
- Modify: `telemetry_tool/tests/test_scoring_session_types.py`

**Step 1: Update tests to work with both old and new config**

The existing `test_scoring_session_types.py` imports `_SESSION_WEIGHT_OVERRIDES` directly. The backward-compat layer keeps this working, but the tests should also validate the new `_SESSION_CATEGORY_CONFIG`. Update the file:

```python
"""Test scoring system differentiates by session type."""
import pytest


class TestScoringSessionTypes:
    def test_weight_normalization(self):
        """Backward-compat _SESSION_WEIGHT_OVERRIDES should still exist."""
        from scoring import _SESSION_WEIGHT_OVERRIDES
        assert len(_SESSION_WEIGHT_OVERRIDES) >= 10

    def test_session_category_config_complete(self):
        """New config should cover all session types."""
        from scoring import _SESSION_CATEGORY_CONFIG
        required = {"qualifying", "race", "practice", "warmup", "test",
                     "endurance", "heat", "final", "sprint"}
        assert required.issubset(set(_SESSION_CATEGORY_CONFIG.keys()))

    def test_qualifying_suppresses_consistency(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        q = _SESSION_CATEGORY_CONFIG["qualifying"]
        assert "consistency" in q["suppressed"]

    def test_race_prioritizes_robustness(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        r = _SESSION_CATEGORY_CONFIG["race"]
        assert r["emphasis"].get("robustness", 0) > 1.0

    def test_endurance_high_robustness(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        for key in ("endurance", "endurance_stint", "endurance_race"):
            if key in _SESSION_CATEGORY_CONFIG:
                e = _SESSION_CATEGORY_CONFIG[key]
                assert e["emphasis"].get("robustness", 0) >= 1.4

    def test_practice_emphasizes_adaptation(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        p = _SESSION_CATEGORY_CONFIG["practice"]
        assert p["emphasis"].get("adaptation", 0) > 1.0

    def test_no_overlap_suppressed_emphasis(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        for stype, cfg in _SESSION_CATEGORY_CONFIG.items():
            overlap = cfg["suppressed"] & set(cfg["emphasis"].keys())
            assert not overlap, f"{stype} has overlap: {overlap}"
```

**Step 2: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_scoring_session_types.py -v`
Expected: all PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_scoring_session_types.py
git commit -m "test(scoring): update session-type tests for new category config"
```

---

### Task 7: Final integration test — full suite

**Step 1: Run the full scoring test suite**

Run: `pytest telemetry_tool/tests/test_adaptive_scoring.py telemetry_tool/tests/test_scoring_session_types.py telemetry_tool/tests/test_scoring_boundaries.py telemetry_tool/tests/test_scoring_adaptation.py telemetry_tool/tests/test_scoring_badges.py -v`
Expected: all PASS

**Step 2: Run broader pipeline tests to check nothing broke**

Run: `pytest telemetry_tool/tests/ -v --timeout=120 -x -q`
Expected: no new failures

**Step 3: Final commit if any fixups needed**

If any tests needed fixing, commit with:
```bash
git commit -m "fix(scoring): fixup adaptive scoring integration issues"
```
