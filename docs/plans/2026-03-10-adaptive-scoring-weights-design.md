# Adaptive Scoring Weights — Design Document

**Date:** 2026-03-10
**Status:** Approved

## Goal

Replace the flat session-type weight overrides with a 3-layer adaptive scoring system that accounts for session type (with category suppression), track conditions, and driver experience — all invisible to the user.

## Architecture

Three independent layers applied in order:

```
Raw sub-scores (Pace 25 / Consistency 25 / Execution 20 / Robustness 15 / Adaptation 15)
  → Layer 1: Session-type suppression + redistribution
  → Layer 2: Track-state weight modifiers (on surviving categories only)
  → Layer 3: Diminishing-returns multiplier (experience + session lap count)
  → Final total /100
```

### Layer 1 — Session-Type Suppression

Replaces `_SESSION_WEIGHT_OVERRIDES`. Suppressed categories score 0 and their budget redistributes proportionally to emphasized categories. Non-suppressed, non-emphasized categories keep base weight.

```python
_SESSION_CATEGORY_CONFIG = {
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
```

**Algorithm:**
1. Zero out suppressed categories
2. For surviving categories: multiply base_max by emphasis (default 1.0)
3. Normalize so surviving weights sum to TOTAL_MAX (100)
4. Scale each raw sub-score: `score * (new_max / base_max)`

### Layer 2 — Track-State Modifiers

Applied multiplicatively on surviving categories only, then re-normalized to 100.

```python
_TRACK_STATE_MODIFIERS = {
    "dry":      {},
    "damp":     {"adaptation": 1.10, "robustness": 1.05, "pace": 0.95},
    "wet":      {"adaptation": 1.15, "robustness": 1.10, "pace": 0.90, "execution": 0.95},
    "full_wet": {"adaptation": 1.20, "robustness": 1.15, "pace": 0.85, "execution": 0.90},
    "drying":   {"adaptation": 1.20, "pace": 0.90},
    "greasy":   {"adaptation": 1.10, "robustness": 1.05, "pace": 0.95},
}
```

### Layer 3 — Diminishing Returns

Asymptotic log curve applied to the total score. Two independent factors, stacked multiplicatively:

```python
experience_factor = max(0.96, 1.0 - 0.005 * ln(1 + total_laps / 1000))
session_factor    = max(0.96, 1.0 - 0.004 * ln(1 + n_laps / 30))
multiplier        = max(0.92, experience_factor * session_factor)
final_total       = raw_total * multiplier
```

| Scenario | experience_factor | session_factor | combined |
|---|---|---|---|
| New driver, 15 laps | 1.000 | 0.998 | 0.998 |
| 500 laps lifetime, 25 laps | 0.998 | 0.997 | 0.995 |
| 2,000 laps, 50 laps | 0.995 | 0.993 | 0.988 |
| 10,000 laps, 100 laps | 0.988 | 0.987 | 0.975 |
| 50,000 laps, 300 laps | 0.980 | 0.978 | 0.959 |
| 100,000 laps, 500 laps | 0.977 | 0.973 | 0.950 |
| Extreme (floor hit) | 0.960 | 0.960 | 0.920 |

Constants:
- `DR_EXP_K = 0.005` — experience decay rate
- `DR_EXP_L0 = 1000.0` — reference lap count
- `DR_EXP_FLOOR = 0.96` — per-factor floor
- `DR_SES_K = 0.004` — session laps decay rate
- `DR_SES_L0 = 30.0` — reference typical session
- `DR_SES_FLOOR = 0.96` — per-factor floor
- `DR_COMBINED_FLOOR = 0.92` — absolute floor

## Pipeline Integration

1. **Fetch driver experience** (orchestrator.py, before step 13): Query `driver_profiles.total_laps` using driver_id. Store as `meta["driver_total_laps"]`. Falls back to 0 if unavailable.
2. **Pass to scorer** (s13_scoring.py): Forward `track_state` and `driver_total_laps` from meta to `score_session()`.
3. **Backward compat**: `_apply_session_weights()` wraps `_apply_adaptive_weights()` with defaults.

## Files Changed

| File | Change |
|---|---|
| `scoring/constants.py` | Add `_SESSION_CATEGORY_CONFIG`, `_TRACK_STATE_MODIFIERS`, DR constants. Remove `_SESSION_WEIGHT_OVERRIDES`. |
| `scoring/scorer.py` | Replace `_apply_session_weights` with `_apply_adaptive_weights`. Add `track_state`, `driver_total_laps` params. |
| `scoring/__init__.py` | Update re-exports |
| `pipeline/stages/s13_scoring.py` | Pass `track_state` and `driver_total_laps` from meta |
| `pipeline/orchestrator.py` | Fetch `total_laps` from driver_profiles before step 13 |
| `tests/test_adaptive_scoring.py` | New: suppression, track modifiers, diminishing returns, combined, backward compat |

## Invariants

- Total always /100 after layers 1+2. Layer 3 reduces from there.
- Suppressed categories show `score: 0, max: 0` in sub_scores — not hidden.
- All weights/multipliers are internal-only, never exposed in API responses.
- Unknown session types default to practice config.
- Unknown track states default to dry (no modifier).
- `_apply_session_weights()` remains callable for backward compat.

## Test Plan

1. Qualifying suppresses consistency/robustness/adaptation → score 0, pace+execution split 100
2. Wet practice → adaptation weight higher than dry practice
3. 10,000-lap veteran < 50-lap newcomer (identical raw metrics)
4. 200-lap session < 15-lap session (identical raw metrics)
5. Combined floor: extreme inputs never drop below 0.92x
6. `_apply_session_weights` backward compat
7. Suppressed sub_scores show `{score: 0, max: 0}`
