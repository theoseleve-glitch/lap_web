# Theoretical Overfitting Detection — Cross-Validation Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` theoretical lap pipeline (stage 10)

## Problem

The percentile envelope at p98 can be inflated by a single outlier lap (GPS glitch, drafting, missed corner cut). The solver produces a theoretical that no real lap can approach, giving the driver a false target. No mechanism exists to detect this.

## Approach

### 1. Deterministic Lap Split (`theoretical_engine.py`)

```python
def split_laps_train_holdout(
    laps: list[pd.DataFrame],
    holdout_fraction: float = 0.3,
    seed: int = 42,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame], list[int]]:
```

- Sort lap indices, assign every 3rd lap to holdout (deterministic modular selection, no randomness)
- Minimum: 4 laps required (3 train, 1 holdout). Below that, return `(laps, [], [])`
- Returns `(train_laps, holdout_laps, holdout_indices)`

### 2. Plausibility Scoring (`theoretical_engine.py`)

```python
@dataclass
class PlausibilityResult:
    segment_approach_ratios: np.ndarray   # (n_holdout, n_segments)
    mean_approach_ratio: float            # 0-1, how close holdout gets overall
    best_approach_ratio: float            # best holdout lap's mean ratio
    all_segments_exceeded: bool           # theoretical > all holdout everywhere
    segments_never_approached: int        # segments where no holdout reaches 85%
    plausibility_score: float             # 0-1 composite
    overfit_suspected: bool               # True if score < 0.5
```

```python
def compute_theoretical_plausibility(
    theoretical_df: pd.DataFrame,
    holdout_laps: list[pd.DataFrame],
    n_segments: int = 10,
    approach_threshold: float = 0.85,
) -> PlausibilityResult:
```

Splits the track into `n_segments` equal-distance bins. For each segment and each holdout lap:

- **Approach ratio**: `holdout_speed / theoretical_speed` per segment
- **Exceedance check**: Does theoretical exceed the fastest holdout in every segment?

**Plausibility score formula**:
- Start at 1.0
- Penalize: `segments_never_approached / n_segments * 0.5`
- Penalize: if `all_segments_exceeded`: −0.3
- Penalize: if `best_approach_ratio < 0.80`: −0.2
- Floor at 0.0

**Overfit threshold**: `plausibility_score < 0.5`

### 3. Pipeline Integration (`pipeline.py` stage 10)

After building the theoretical lap, before computing confidence:

1. Call `split_laps_train_holdout()` on `laps_for_theo`
2. Call `compute_theoretical_plausibility()` with the theoretical (built on all laps) against holdout
3. If `overfit_suspected`:
   - Add `"overfit_suspected"` to `confidence_reasons`
   - Apply penalty: `confidence_score *= plausibility_score`
   - Store `plausibility` dict in `summary["theoretical_metrics"]`

### 4. Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| < 4 laps | Skip validation, no penalty |
| Holdout empty after filtering | Skip, no penalty |
| Plausibility computation fails | Log, skip, no penalty |

### 5. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/theoretical_engine.py` | `split_laps_train_holdout()`, `PlausibilityResult`, `compute_theoretical_plausibility()` |
| `telemetry_tool/pipeline.py` | Wire plausibility check in stage 10, merge into confidence |
| `telemetry_tool/tests/test_theoretical_plausibility.py` | 4 tests |

### 6. Tests

1. **Deterministic split**: Same laps → same split every time
2. **Healthy envelope**: 8 realistic laps → `overfit_suspected=False`
3. **Outlier inflates envelope**: 7 normal + 1 outlier at 2x speed → `overfit_suspected=True`
4. **Few laps graceful skip**: 2 laps → validation skipped, no crash
