"""
anomaly_detection.py
--------------------
Track-aware anomaly detection for motorsport telemetry.

Key design decision -- **condition-normalised baselines**
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
An IsolationForest trained on dry Spa data will flag every wet lap as
anomalous because wet laps have systematically lower speed, higher jerk,
and higher yaw variance.  That is not a useful signal.

This module solves the problem by fitting one model per *condition group*
-- the combination of ``(track_id, track_state)``.  Each group gets its
own z-score normalisation and IsolationForest, so a wet lap is compared
against the wet baseline and only flagged if it deviates from *other wet
laps on the same track*.

When the condition group is too small (< ``MIN_GROUP_SAMPLES``), the
module falls back to the full-track baseline (ignoring ``track_state``).
When even that is too small, it falls back to the entire dataset.

Anomaly type classification
~~~~~~~~~~~~~~~~~~~~~~~~~~~
After IsolationForest flags a lap, the module examines *which feature
dimensions* deviate most from the group median (using z-scores) and maps
the dominant deviation to one of:

  ``braking_anomaly``     -- braking_max, accel_rms far from normal
  ``speed_anomaly``       -- speed profile columns far from normal
  ``stability_anomaly``   -- jerk, yaw, instability columns far from normal
  ``line_anomaly``        -- line_length far from normal
  ``entry_anomaly``       -- entry speed / loss columns far from normal
  ``exit_anomaly``        -- exit accel / loss columns far from normal
  ``general_anomaly``     -- no single category dominates
  ``pace_anomaly``        -- lap_time far from normal (but driving looks ok)

This classification is heuristic -- it is intended for coaching feedback,
not as a definitive root-cause diagnosis.

Segment-level detection
~~~~~~~~~~~~~~~~~~~~~~~
``detect_segment_anomalies()`` operates on rows where each row is one
segment of one lap.  This catches per-corner anomalies (e.g. "segment 7
in lap 14 has abnormal instability") while the lap-level function only
sees the aggregate.

Functions
~~~~~~~~~
``train_anomaly_model(feature_df, ...)``
    Build condition-normalised IsolationForest models.
``detect_anomalies(model, feature_df)``
    Score laps and classify anomaly type.
``detect_segment_anomalies(model, segment_df)``
    Score individual segments.
``save_anomaly_model(model, path)`` / ``load_anomaly_model(path)``
    Persist / restore via joblib.

Alignment with the rest of the pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Column names mirror ``feature_builder.py`` and ``ml_engine.py``.
Cause labels align with ``deltas.classify_time_loss_cause()``.
"""

from __future__ import annotations

import json
import logging
import traceback
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


# ============================================================================

# Column-name constants

# ============================================================================


COL_TRACK_ID:    Final[str] = "track_id"
COL_TRACK_STATE: Final[str] = "track_state"
COL_DRIVER_NAME: Final[str] = "driver_name"
COL_SESSION_ID:  Final[str] = "session_id"
COL_LAP_NUMBER:  Final[str] = "lap_number"
COL_LAP_TIME:    Final[str] = "lap_time_s"
COL_SEGMENT:     Final[str] = "segment"

METADATA_COLS: Final[list[str]] = [
    COL_TRACK_ID, COL_TRACK_STATE, COL_DRIVER_NAME,
    COL_SESSION_ID, COL_LAP_NUMBER,
]

# Numeric features consumed by the anomaly model.  Order matters -- it defines

# the model's input vector.  Grouped by semantic category for type classification.

SPEED_FEATURES: Final[list[str]] = [
    "speed_min_mps", "speed_max_mps", "speed_mean_mps",
    "speed_std_mps", "speed_p10_mps", "speed_p90_mps",
]
BRAKING_FEATURES: Final[list[str]] = [
    "braking_max_mps2", "accel_max_mps2", "accel_rms_mps2",
]
STABILITY_FEATURES: Final[list[str]] = [
    "jerk_rms_mps3", "jerk_max_mps3", "jerk_min_mps3",
    "lat_accel_max_mps2", "lat_accel_rms_mps2",
    "instability_loss_ms", "mean_yaw_var_ratio",
]
LINE_FEATURES: Final[list[str]] = [
    "line_length_m", "line_inefficiency_loss_ms",
]
ENTRY_FEATURES: Final[list[str]] = [
    "entry_loss_ms", "mean_entry_speed_diff_mps",
]
EXIT_FEATURES: Final[list[str]] = [
    "exit_loss_ms", "mean_exit_accel_diff_mps2",
]
PACE_FEATURES: Final[list[str]] = [
    "delta_to_theoretical_s", "total_time_loss_ms", "mid_corner_loss_ms",
    "mean_min_speed_diff_mps",
]

ALL_FEATURE_COLS: Final[list[str]] = (
    SPEED_FEATURES + BRAKING_FEATURES + STABILITY_FEATURES
    + LINE_FEATURES + ENTRY_FEATURES + EXIT_FEATURES + PACE_FEATURES
)

# Mapping from feature category -> anomaly type label

_CATEGORY_MAP: Final[dict[str, list[str]]] = {
    "speed_anomaly":     SPEED_FEATURES,
    "braking_anomaly":   BRAKING_FEATURES,
    "stability_anomaly": STABILITY_FEATURES,
    "line_anomaly":      LINE_FEATURES,
    "entry_anomaly":     ENTRY_FEATURES,
    "exit_anomaly":      EXIT_FEATURES,
    "pace_anomaly":      PACE_FEATURES,
}


# ============================================================================

# Model tuning constants

# ============================================================================


RANDOM_STATE:        Final[int]   = 42
ISO_N_ESTIMATORS:    Final[int]   = 150
ISO_CONTAMINATION:   Final[float] = 0.05
MIN_GROUP_SAMPLES:   Final[int]   = 15
ANOMALY_Z_THRESHOLD: Final[float] = 2.5   # |z| above which a feature counts as "extreme"

# Bump this whenever the model serialisation format or feature contract changes.

# ``load_anomaly_model`` will refuse to load models with a different version and

# ``load_or_retrain_anomaly_model`` will silently retrain from scratch.

MODEL_SCHEMA_VERSION: Final[str] = "2"


# ============================================================================

# Exceptions

# ============================================================================


class AnomalyDetectionError(Exception):
    """Base exception for anomaly_detection module."""


class InsufficientDataError(AnomalyDetectionError, ValueError):
    """Not enough samples to train a meaningful model."""


class ModelNotFittedError(AnomalyDetectionError, RuntimeError):
    """The model has not been trained yet."""


# ============================================================================

# Data structures

# ============================================================================


@dataclass
class ConditionModel:
    """One IsolationForest + scaler for a single condition group."""
    track_id:    str
    track_state: str           # "" means all-states fallback
    iso_forest:  IsolationForest
    scaler:      StandardScaler
    feature_cols: list[str]
    n_samples:   int
    median_vec:  np.ndarray    # group median for type classification


@dataclass
class AnomalyModel:
    """
    Container for all condition-specific sub-models.

    Lookup order for a given (track_id, track_state) pair:
      1. Exact match on (track_id, track_state)
      2. Track-only fallback (track_id, "")
      3. Global fallback ("__global__", "")
    """
    condition_models: dict[tuple[str, str], ConditionModel] = field(
        default_factory=dict,
    )
    created_at:     str  = ""
    feature_cols:   list[str] = field(default_factory=list)
    total_samples:  int  = 0
    model_version:  str  = ""   # MODEL_SCHEMA_VERSION at training time

    # -- - lookup with fallback chain

    def resolve(
        self, track_id: str, track_state: str,
    ) -> ConditionModel:
        """
        Return the best matching ConditionModel.

        Raises
        ------
        ModelNotFittedError
            If no model exists at any fallback level.
        """
        key_exact    = (track_id, track_state)
        key_track    = (track_id, "")
        key_global   = ("__global__", "")

        for key in (key_exact, key_track, key_global):
            if key in self.condition_models:
                return self.condition_models[key]

        raise ModelNotFittedError(
            f"No anomaly model found for track_id={track_id!r}, "
            f"track_state={track_state!r}, and no fallback exists.  "
            f"Available keys: {list(self.condition_models.keys())}"
        )


# ============================================================================

# Internal helpers

# ============================================================================


def _available_features(df: pd.DataFrame) -> list[str]:
    """Return the subset of ALL_FEATURE_COLS present in *df*."""
    return [c for c in ALL_FEATURE_COLS if c in df.columns]


def _prepare_numeric(
    df: pd.DataFrame, feature_cols: list[str],
) -> pd.DataFrame:
    """
    Coerce feature columns to numeric and return a clean copy.

    NaN cells are preserved (not dropped) so that row alignment with the
    original DataFrame is maintained.  The IsolationForest receives the
    z-scored matrix with NaN filled to 0 (the group mean).
    """
    out = df[feature_cols].copy()
    for col in feature_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


# Minimum number of usable features to proceed with IsolationForest fitting

_MIN_USABLE_FEATURES: Final[int] = 3


def _clean_features(
    X: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str], int]:
    """
    Preprocess feature matrix before fitting:
    1. Select only numeric columns.
    2. Drop all-NaN columns.
    3. Drop constant columns (std == 0).
    4. Impute remaining NaN values with column median.

    Returns
    -------
    (cleaned_df, dropped_all_nan, dropped_constant, n_imputed)
    """
    # 1. Ensure numeric

    X = X.apply(pd.to_numeric, errors="coerce")

    # Suppress "Mean of empty slice" / "Degrees of freedom <= 0" warnings

    # that fire when we inspect all-NaN or constant columns.  Dropping these

    # columns is the *intended* behaviour; the warnings are just noise.

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)

        # 2. Drop all-NaN columns

        all_nan_cols = [c for c in X.columns if X[c].isna().all()]
        if all_nan_cols:
            X = X.drop(columns=all_nan_cols)
            logger.info("Dropped %d all-NaN columns: %s", len(all_nan_cols), all_nan_cols)

        # 3. Drop constant columns (std == 0, no variation)

        constant_cols: list[str] = []
        for c in X.columns:
            vals = X[c].dropna()
            if len(vals) < 2 or vals.std() == 0.0:
                constant_cols.append(c)
        if constant_cols:
            X = X.drop(columns=constant_cols)
            logger.info("Dropped %d constant columns: %s", len(constant_cols), constant_cols)

        # 4. Impute remaining NaNs with column median

        n_imputed = 0
        for c in X.columns:
            na_count = int(X[c].isna().sum())
            if na_count > 0:
                median_val = X[c].median()
                X[c] = X[c].fillna(median_val)
                n_imputed += na_count
        if n_imputed > 0:
            logger.info("Imputed %d NaN cells with column medians.", n_imputed)

    return X, all_nan_cols, constant_cols, n_imputed


def _fit_condition_group(
    df: pd.DataFrame,
    feature_cols: list[str],
    track_id: str,
    track_state: str,
) -> ConditionModel:
    """
    Fit scaler + IsolationForest on a single condition slice.

    NaN handling: features are cleaned (all-NaN and constant columns dropped,
    remaining NaN imputed with median) before fitting to avoid RuntimeWarnings
    and division-by-zero in StandardScaler.

    The IsolationForest is always trained on the **full** ``feature_cols`` vector
    (with NaN-derived columns mapped to 0 after scaling).  This guarantees
    ``iso_forest.n_features_in_ == len(feature_cols)`` so that ``_score_rows``
    can pass the same-width matrix at inference time without a dimension mismatch.
    """
    X_raw = _prepare_numeric(df, feature_cols)

    # --- diagnostic pass: log which columns are degenerate
    # _clean_features is still called for its logging side-effects (tells the

    # user which columns were all-NaN or constant) but we do NOT use the

    # reduced matrix for iso_forest fitting.

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        _clean_features(X_raw.copy())

    if len([c for c in X_raw.columns
            if not X_raw[c].isna().all()]) < _MIN_USABLE_FEATURES:
        logger.warning(
            "Only %d usable features after cleaning (need >= %d); "
            "returning safe fallback model for %s/%s.",
            len([c for c in X_raw.columns if not X_raw[c].isna().all()]),
            _MIN_USABLE_FEATURES, track_id, track_state,
        )
        # Return a model that won't flag anything (neutral median, dummy forest)

        median_vec = np.zeros(len(feature_cols))
        scaler = StandardScaler()
        dummy_X = np.zeros((max(len(df), 2), len(feature_cols)))
        scaler.fit(dummy_X)
        iso = IsolationForest(
            n_estimators=ISO_N_ESTIMATORS,
            contamination=ISO_CONTAMINATION,
            random_state=RANDOM_STATE,
        )
        iso.fit(dummy_X)
        return ConditionModel(
            track_id=track_id, track_state=track_state,
            iso_forest=iso, scaler=scaler,
            feature_cols=feature_cols,
            n_samples=len(df), median_vec=median_vec,
        )

    # --- build the full-width imputed matrix
    X_full = _prepare_numeric(df, feature_cols)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for c in X_full.columns:
            na_mask = X_full[c].isna()
            if na_mask.any():
                med = X_full[c].median()         # may be NaN for all-NaN cols
                X_full.loc[na_mask, c] = med
    # All-NaN columns still have NaN after median imputation; zero-fill them.

    X_full = X_full.fillna(0.0)

    median_vec = np.zeros(len(feature_cols))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for i, c in enumerate(feature_cols):
            vals = X_raw[c].dropna()
            if len(vals) > 0:
                median_vec[i] = float(np.median(vals))

    full_scaler = StandardScaler()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        full_scaler.fit(X_full.values)

    X_scaled = full_scaler.transform(X_full.values)
    X_fit = np.where(np.isfinite(X_scaled), X_scaled, 0.0)

    iso = IsolationForest(
        n_estimators=ISO_N_ESTIMATORS,
        contamination=ISO_CONTAMINATION,
        random_state=RANDOM_STATE,
    )
    iso.fit(X_fit)

    return ConditionModel(
        track_id=track_id,
        track_state=track_state,
        iso_forest=iso,
        scaler=full_scaler,
        feature_cols=feature_cols,
        n_samples=len(df),
        median_vec=median_vec,
    )


def _score_rows(
    cm: ConditionModel,
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Return ``(anomaly_scores, labels, z_matrix)`` for each row.

    anomaly_scores: float, lower = more anomalous
    labels:         -1 (anomaly) or 1 (inlier)
    z_matrix:       (n_rows, n_features) z-scores for type classification
    """
    X_raw = _prepare_numeric(df, cm.feature_cols)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        X_scaled = cm.scaler.transform(X_raw.values)
    z_matrix = X_scaled.copy()                       # keep for type classification
    X_clean  = np.where(np.isfinite(X_scaled), X_scaled, 0.0)

    scores = cm.iso_forest.score_samples(X_clean)
    labels = cm.iso_forest.predict(X_clean)
    return scores, labels, z_matrix


def _classify_anomaly_type(
    z_row: np.ndarray,
    feature_cols: list[str],
) -> str:
    """
    Given a z-scored feature vector, identify which category has the
    largest total deviation and return the corresponding anomaly type.

    If no category exceeds ``ANOMALY_Z_THRESHOLD`` in any feature,
    returns ``"general_anomaly"``.
    """
    # Build col -> index map once

    col_idx = {c: i for i, c in enumerate(feature_cols)}

    best_category = "general_anomaly"
    best_score    = 0.0

    for atype, cols in _CATEGORY_MAP.items():
        indices = [col_idx[c] for c in cols if c in col_idx]
        if not indices:
            continue
        # Sum of absolute z-scores for this category

        z_vals = z_row[indices]
        finite = z_vals[np.isfinite(z_vals)]
        if len(finite) == 0:
            continue
        cat_score = float(np.abs(finite).sum())
        if cat_score > best_score:
            best_score    = cat_score
            best_category = atype

    # Require at least one feature exceeds the z-threshold to be specific

    if best_score < ANOMALY_Z_THRESHOLD:
        return "general_anomaly"

    return best_category


# ============================================================================

# Public API -- training

# ============================================================================


def train_anomaly_model(
    feature_df: pd.DataFrame,
    *,
    min_group_samples: int = MIN_GROUP_SAMPLES,
) -> AnomalyModel:
    """
    Train condition-normalised anomaly models from a feature dataset.

    For every ``(track_id, track_state)`` group with at least
    *min_group_samples* rows, a separate IsolationForest is fitted on
    z-scored features.  Smaller groups are absorbed into a track-only or
    global fallback model.

    Parameters
    ----------
    feature_df:
        Feature dataset (e.g. from ``feature_builder.build_feature_dataset``).
        Must contain numeric feature columns and at least ``track_id``.
    min_group_samples:
        Minimum rows for a condition group to receive its own model.

    Returns
    -------
    AnomalyModel
        Container holding all condition-specific sub-models.

    Raises
    ------
    InsufficientDataError
        If the entire dataset has fewer than *min_group_samples* rows.
    """
    df = feature_df.copy()
    feature_cols = _available_features(df)

    if not feature_cols:
        raise InsufficientDataError("No recognised feature columns in DataFrame.")

    n_total = len(df)
    if n_total < min_group_samples:
        # --- Graceful degradation: return an empty model instead of crashing.

        # Short sessions (< 15 laps) are common for sprint races, wet sessions,

        # and first outings.  The pipeline should still complete; anomaly

        # detection is simply not meaningful with this little data.

        logger.warning(
            "Anomaly detection skipped: need >= %d laps but only %d "
            "available.  Returning an empty (neutral) anomaly model.",
            min_group_samples, n_total,
        )
        return AnomalyModel(
            created_at=datetime.now(timezone.utc).isoformat(),
            feature_cols=feature_cols,
            total_samples=n_total,
            model_version=MODEL_SCHEMA_VERSION,
        )

    model = AnomalyModel(
        created_at=datetime.now(timezone.utc).isoformat(),
        feature_cols=feature_cols,
        total_samples=n_total,
        model_version=MODEL_SCHEMA_VERSION,
    )

    # --- 1. Per-(track_id, track_state) models
    has_track = COL_TRACK_ID in df.columns
    has_state = COL_TRACK_STATE in df.columns

    if has_track and has_state:
        for (tid, tst), grp in df.groupby([COL_TRACK_ID, COL_TRACK_STATE]):
            if len(grp) >= min_group_samples:
                cm = _fit_condition_group(grp, feature_cols, str(tid), str(tst))
                model.condition_models[(str(tid), str(tst))] = cm
                logger.info(
                    "Anomaly model fitted: track=%r state=%r  n=%d",
                    tid, tst, len(grp),
                )

    # --- 2. Per-track fallbacks -- -

    if has_track:
        for tid, grp in df.groupby(COL_TRACK_ID):
            key = (str(tid), "")
            if key not in model.condition_models and len(grp) >= min_group_samples:
                cm = _fit_condition_group(grp, feature_cols, str(tid), "")
                model.condition_models[key] = cm
                logger.info(
                    "Anomaly fallback fitted: track=%r (all states)  n=%d",
                    tid, len(grp),
                )

    # --- 3. Global fallback -- -

    cm_global = _fit_condition_group(df, feature_cols, "__global__", "")
    model.condition_models[("__global__", "")] = cm_global
    logger.info("Anomaly global fallback fitted: n=%d", n_total)

    return model


# ============================================================================

# Public API -- detection

# ============================================================================


def detect_anomalies(
    model: AnomalyModel,
    feature_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """
    Score each lap for anomalies using the best-matching condition model.

    Parameters
    ----------
    model:
        Trained ``AnomalyModel`` (from :func:`train_anomaly_model`).
    feature_df:
        DataFrame where each row is one lap with feature columns.

    Returns
    -------
    list[dict]
        One entry per row::

            {
                "lap_number":    int,
                "anomaly_score": float,   # lower = more anomalous
                "anomaly_flag":  bool,
                "anomaly_type":  str,     # category label if anomaly, else "normal"
                "condition_key": (track_id, track_state),
            }
    """
    if not model.condition_models:
        # Model was created with insufficient data -- return a neutral result

        # (no anomalies detected) instead of raising.

        logger.info(
            "Anomaly detection: model has no fitted sub-models "
            "(insufficient training data).  Returning empty results."
        )
        return []

    results: list[dict[str, Any]] = []

    # Group incoming data by (track_id, track_state) to batch-score

    groups = _group_by_condition(feature_df)

    for (tid, tst), grp_df in groups:
        cm = model.resolve(tid, tst)
        scores, labels, z_matrix = _score_rows(cm, grp_df)

        # Extract lap numbers

        if COL_LAP_NUMBER in grp_df.columns:
            lap_nums = grp_df[COL_LAP_NUMBER].tolist()
        else:
            lap_nums = list(range(1, len(grp_df) + 1))

        for i, (lap_num, score, label) in enumerate(zip(lap_nums, scores, labels)):
            is_anomaly = bool(label == -1)
            atype = (
                _classify_anomaly_type(z_matrix[i], cm.feature_cols)
                if is_anomaly else "normal"
            )
            results.append({
                "lap_number":    int(lap_num),
                "anomaly_score": round(float(score), 6),
                "anomaly_flag":  is_anomaly,
                "anomaly_type":  atype,
                "condition_key": (cm.track_id, cm.track_state),
            })

    logger.info(
        "Anomaly detection: %d laps scored, %d flagged.",
        len(results), sum(1 for r in results if r["anomaly_flag"]),
    )
    return results


def detect_segment_anomalies(
    model: AnomalyModel,
    segment_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """
    Score individual segments (one row per segment per lap).

    Expects ``segment_df`` to have a ``segment`` column (1-based) and
    ``lap_number``.  Uses the same condition-resolution logic as
    :func:`detect_anomalies`.

    Returns
    -------
    list[dict]
        One entry per row::

            {
                "lap_number":    int,
                "segment":       int,
                "anomaly_score": float,
                "anomaly_flag":  bool,
                "anomaly_type":  str,
                "condition_key": (track_id, track_state),
            }
    """
    if not model.condition_models:
        logger.info(
            "Segment anomaly detection: model has no fitted sub-models "
            "(insufficient training data).  Returning empty results."
        )
        return []

    results: list[dict[str, Any]] = []
    groups = _group_by_condition(segment_df)

    for (tid, tst), grp_df in groups:
        cm = model.resolve(tid, tst)
        scores, labels, z_matrix = _score_rows(cm, grp_df)

        lap_nums = (
            grp_df[COL_LAP_NUMBER].tolist()
            if COL_LAP_NUMBER in grp_df.columns
            else [0] * len(grp_df)
        )
        seg_nums = (
            grp_df[COL_SEGMENT].tolist()
            if COL_SEGMENT in grp_df.columns
            else list(range(1, len(grp_df) + 1))
        )

        for i, (lap, seg, score, label) in enumerate(
            zip(lap_nums, seg_nums, scores, labels)
        ):
            is_anomaly = bool(label == -1)
            atype = (
                _classify_anomaly_type(z_matrix[i], cm.feature_cols)
                if is_anomaly else "normal"
            )
            results.append({
                "lap_number":    int(lap),
                "segment":       int(seg),
                "anomaly_score": round(float(score), 6),
                "anomaly_flag":  is_anomaly,
                "anomaly_type":  atype,
                "condition_key": (cm.track_id, cm.track_state),
            })

    logger.info(
        "Segment anomaly detection: %d segments scored, %d flagged.",
        len(results), sum(1 for r in results if r["anomaly_flag"]),
    )
    return results


# ============================================================================

# Public API -- persistence

# ============================================================================


def save_anomaly_model(model: AnomalyModel, path: str | Path) -> Path:
    """
    Persist an ``AnomalyModel`` as a joblib file with sidecar metadata JSON.

    Returns the path written to.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)

    meta_path = path.with_suffix(".json")
    meta = {
        "model_version":   model.model_version or MODEL_SCHEMA_VERSION,
        "created_at":      model.created_at,
        "total_samples":   model.total_samples,
        "n_feature_cols":  len(model.feature_cols),
        "feature_cols":    model.feature_cols,
        "condition_keys":  [
            {"track_id": k[0], "track_state": k[1], "n_samples": cm.n_samples}
            for k, cm in model.condition_models.items()
        ],
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.info("Anomaly model saved: %s  (%d sub-models)", path, len(model.condition_models))
    return path


def load_anomaly_model(
    path: str | Path,
    *,
    expected_n_features: int | None = None,
) -> AnomalyModel:
    """
    Load an ``AnomalyModel`` previously saved with :func:`save_anomaly_model`.

    Parameters
    ----------
    path:
        Path to the ``.joblib`` file.
    expected_n_features:
        If given, the loaded model's ``feature_cols`` length is compared to
        this value.  A mismatch raises ``AnomalyDetectionError``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    TypeError
        If the deserialised object is not an ``AnomalyModel``.
    AnomalyDetectionError
        If the model's schema version or feature count does not match.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Anomaly model not found: {path}")
    model = joblib.load(path)
    if not isinstance(model, AnomalyModel):
        raise TypeError(f"Expected AnomalyModel, got {type(model).__name__}")

    # --- version gate -- -

    saved_version = getattr(model, "model_version", "") or ""
    if saved_version != MODEL_SCHEMA_VERSION:
        raise AnomalyDetectionError(
            f"Stale anomaly model: saved schema version {saved_version!r} "
            f"!= current {MODEL_SCHEMA_VERSION!r}.  Path: {path}"
        )

    # --- feature count gate -- -

    if expected_n_features is not None:
        model_n = len(model.feature_cols)
        if model_n != expected_n_features:
            raise AnomalyDetectionError(
                f"Feature count mismatch: model has {model_n} features "
                f"but current data has {expected_n_features}.  Path: {path}"
            )

    logger.info("Anomaly model loaded: %s  (%d sub-models)", path, len(model.condition_models))
    return model


class _StaleModelSentinel:                           # noqa: N801
    """Returned by :func:`load_or_retrain_anomaly_model` internally."""


def load_or_retrain_anomaly_model(
    path: str | Path | None,
    feature_df: pd.DataFrame,
    *,
    min_group_samples: int = MIN_GROUP_SAMPLES,
) -> tuple[AnomalyModel, bool]:
    """
    Load a persisted model if it is compatible, otherwise retrain from scratch.

    This is the recommended entry point for the pipeline.  It handles every
    failure mode gracefully:

    * Path is ``None`` or does not exist -> train from scratch.
    * Schema version mismatch -> log, discard, retrain.
    * Feature count mismatch -> log, discard, retrain.
    * Deserialisation error -> log, discard, retrain.

    Returns
    -------
    (model, retrained)
        *retrained* is ``True`` when the returned model was freshly trained
        rather than loaded from disk.
    """
    feature_cols = _available_features(feature_df)
    n_features = len(feature_cols)

    if path is not None:
        path = Path(path)
        if path.exists():
            try:
                model = load_anomaly_model(
                    path, expected_n_features=n_features,
                )
                return model, False
            except (AnomalyDetectionError, TypeError, Exception) as exc:
                logger.warning(
                    "Persisted anomaly model at %s is incompatible and will "
                    "be retrained from scratch.  Reason: %s", path, exc,
                )

    model = train_anomaly_model(feature_df, min_group_samples=min_group_samples)

    # Persist the freshly-trained model for next time.

    if path is not None:
        try:
            save_anomaly_model(model, path)
        except Exception as exc:              # noqa: BLE001
            logger.warning("Could not persist retrained anomaly model: %s", exc)

    return model, True


# ============================================================================

# Internal -- condition grouping

# ============================================================================


def _group_by_condition(
    df: pd.DataFrame,
) -> list[tuple[tuple[str, str], pd.DataFrame]]:
    """
    Partition *df* into ``((track_id, track_state), sub_df)`` pairs.

    If ``track_id`` or ``track_state`` columns are absent, uses defaults
    so that the grouping always succeeds.
    """
    has_track = COL_TRACK_ID in df.columns
    has_state = COL_TRACK_STATE in df.columns

    if has_track and has_state:
        groups = [
            ((str(tid), str(tst)), grp)
            for (tid, tst), grp in df.groupby([COL_TRACK_ID, COL_TRACK_STATE])
        ]
    elif has_track:
        groups = [
            ((str(tid), ""), grp)
            for tid, grp in df.groupby(COL_TRACK_ID)
        ]
    else:
        groups = [(("__global__", ""), df)]

    return groups


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """Self-contained test suite -- run with ``python anomaly_detection.py``."""
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Synthetic data factories -- -


    def _make_dataset(
        n: int = 600,
        seed: int = 42,
        *,
        tracks: Optional[list[str]] = None,
        states: Optional[list[str]] = None,
        drivers: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        Build a synthetic telemetry feature dataset.

        Wet laps are systematically different: slower speed, higher jerk,
        more yaw variance -- mimicking the real-world shift that must NOT
        be flagged as anomalous.
        """
        rng = np.random.default_rng(seed)
        tracks  = tracks  or ["spa_2024", "monza_2024"]
        states  = states  or ["dry", "wet"]
        drivers = drivers or ["DriverA", "DriverB", "DriverC"]

        track_ids  = rng.choice(tracks,  n)
        state_ids  = rng.choice(states,  n)
        driver_ids = rng.choice(drivers, n)

        is_wet = np.array([s == "wet" for s in state_ids])

        # Condition shift: wet laps are systematically slower / jerkier

        wet_speed_penalty = np.where(is_wet, -8.0, 0.0)
        wet_jerk_penalty  = np.where(is_wet,  6.0, 0.0)
        wet_yaw_penalty   = np.where(is_wet,  0.5, 0.0)

        speed_mean = 42.0 + rng.normal(0, 3, n) + wet_speed_penalty
        braking    = 12.0 + rng.normal(0, 1, n)
        jerk_rms   = 18.0 + rng.normal(0, 3, n) + wet_jerk_penalty

        data: dict[str, Any] = {
            COL_TRACK_ID:    track_ids.tolist(),
            COL_TRACK_STATE: state_ids.tolist(),
            COL_DRIVER_NAME: driver_ids.tolist(),
            COL_SESSION_ID:  [f"s{i // 20:03d}" for i in range(n)],
            COL_LAP_NUMBER:  (np.arange(n) % 20 + 1).tolist(),
        }

        # Speed features

        speed_std = np.abs(12.0 + rng.normal(0, 1, n))
        data["speed_min_mps"]  = (speed_mean - 2 * speed_std + rng.normal(0, 0.5, n)).tolist()
        data["speed_max_mps"]  = (speed_mean + 2 * speed_std + rng.normal(0, 0.5, n)).tolist()
        data["speed_mean_mps"] = speed_mean.tolist()
        data["speed_std_mps"]  = speed_std.tolist()
        data["speed_p10_mps"]  = (speed_mean - 1.3 * speed_std).tolist()
        data["speed_p90_mps"]  = (speed_mean + 1.3 * speed_std).tolist()

        # Braking / accel

        data["braking_max_mps2"] = braking.tolist()
        data["accel_max_mps2"]   = (6.0 + rng.normal(0, 0.5, n)).tolist()
        data["accel_rms_mps2"]   = (3.5 + rng.normal(0, 0.2, n)).tolist()

        # Stability

        data["jerk_rms_mps3"]        = jerk_rms.tolist()
        data["jerk_max_mps3"]        = (jerk_rms * 1.8 + rng.normal(0, 1, n)).tolist()
        data["jerk_min_mps3"]        = (-jerk_rms * 2.0 + rng.normal(0, 1, n)).tolist()
        data["lat_accel_max_mps2"]   = (10.0 + rng.normal(0, 1, n)).tolist()
        data["lat_accel_rms_mps2"]   = (5.0 + rng.normal(0, 0.5, n)).tolist()
        data["instability_loss_ms"]  = np.abs(5 + rng.normal(0, 3, n) + wet_jerk_penalty).tolist()
        data["mean_yaw_var_ratio"]   = (1.0 + np.abs(rng.normal(0, 0.3, n)) + wet_yaw_penalty).tolist()

        # Line

        data["line_length_m"]             = (4500.0 + rng.normal(0, 10, n)).tolist()
        data["line_inefficiency_loss_ms"] = np.abs(8 + rng.normal(0, 4, n)).tolist()

        # Entry / exit

        data["entry_loss_ms"]              = np.abs(15 + rng.normal(0, 8, n)).tolist()
        data["mean_entry_speed_diff_mps"]  = rng.normal(0.5, 1, n).tolist()
        data["exit_loss_ms"]               = np.abs(10 + rng.normal(0, 5, n)).tolist()
        data["mean_exit_accel_diff_mps2"]  = rng.normal(0.1, 0.3, n).tolist()

        # Pace

        data["delta_to_theoretical_s"] = np.abs(1.5 + rng.normal(0, 0.5, n)).tolist()
        data["total_time_loss_ms"]     = np.abs(100 + rng.normal(0, 30, n)).tolist()
        data["mid_corner_loss_ms"]     = np.abs(20 + rng.normal(0, 10, n)).tolist()
        data["mean_min_speed_diff_mps"] = rng.normal(0.3, 0.8, n).tolist()

        # Target (not used by anomaly model, but present in dataset)

        lap_time = 90.0 - 0.3 * speed_mean + 0.15 * braking + rng.normal(0, 0.5, n)
        data[COL_LAP_TIME] = lap_time.tolist()

        return pd.DataFrame(data)

    # ==================================================================

    # Test 1 -- basic training returns a valid model

    # ==================================================================

    def t_train_basic() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        assert isinstance(model, AnomalyModel)
        assert len(model.condition_models) >= 1
        assert ("__global__", "") in model.condition_models
        assert model.total_samples == 600
        assert len(model.feature_cols) > 0

    _test("train_basic", t_train_basic)

    # ==================================================================

    # Test 2 -- condition-specific models are created

    # ==================================================================

    def t_train_condition_models() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        # With 600 rows, ~2 tracks x 2 states = ~150 per group -> should fit

        condition_keys = list(model.condition_models.keys())
        exact_keys = [k for k in condition_keys if k[1] != "" and k[0] != "__global__"]
        assert len(exact_keys) >= 2, f"Expected >=2 condition models, got {len(exact_keys)}: {exact_keys}"

    _test("train_condition_models", t_train_condition_models)

    # ==================================================================

    # Test 3 -- detection returns correct structure

    # ==================================================================

    def t_detect_structure() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)
        results = detect_anomalies(model, df.head(50))

        assert isinstance(results, list)
        assert len(results) == 50
        for r in results:
            assert "lap_number"    in r
            assert "anomaly_score" in r
            assert "anomaly_flag"  in r
            assert "anomaly_type"  in r
            assert isinstance(r["anomaly_flag"], bool)
            assert isinstance(r["anomaly_score"], float)
            assert isinstance(r["anomaly_type"],  str)

    _test("detect_structure", t_detect_structure)

    # ==================================================================

    # Test 4 -- wet laps are NOT universally flagged

    # ==================================================================

    def t_wet_not_universally_flagged() -> None:
        df = _make_dataset(800, seed=99)
        model = train_anomaly_model(df)

        # Take only wet laps from a single track

        wet = df[(df[COL_TRACK_STATE] == "wet") & (df[COL_TRACK_ID] == "spa_2024")]
        assert len(wet) >= 20, "Need enough wet laps for a meaningful test"

        results = detect_anomalies(model, wet)
        flagged_pct = sum(1 for r in results if r["anomaly_flag"]) / len(results)

        # With contamination=5%, we expect ~5% flagged, NOT 100%

        assert flagged_pct < 0.30, (
            f"Wet session had {flagged_pct:.0%} anomalies -- track-state "
            f"normalisation is broken (expected <30%)"
        )

    _test("wet_not_universally_flagged", t_wet_not_universally_flagged)

    # ==================================================================

    # Test 5 -- extreme outliers ARE flagged

    # ==================================================================

    def t_outliers_flagged() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        # Create wildly abnormal laps

        outliers = df.head(5).copy()
        for col in _available_features(outliers):
            outliers[col] = outliers[col] * 50

        results = detect_anomalies(model, outliers)
        flagged = [r for r in results if r["anomaly_flag"]]
        assert len(flagged) >= 3, (
            f"Only {len(flagged)}/5 extreme outliers flagged"
        )

    _test("outliers_flagged", t_outliers_flagged)

    # ==================================================================

    # Test 6 -- anomaly type classification works

    # ==================================================================

    def t_anomaly_type_classification() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        # Create a braking anomaly: extreme braking features.

        # Must be extreme enough that IsolationForest flags it in 27-D space.

        braking_outlier = df.head(5).copy()
        braking_outlier["braking_max_mps2"]  = 500.0
        braking_outlier["accel_max_mps2"]    = 400.0
        braking_outlier["accel_rms_mps2"]    = 300.0

        results = detect_anomalies(model, braking_outlier)
        flagged = [r for r in results if r["anomaly_flag"]]
        assert len(flagged) > 0, "Braking outlier should be flagged"

        # At least one should be classified as braking_anomaly

        types = {r["anomaly_type"] for r in flagged}
        assert "braking_anomaly" in types, f"Expected braking_anomaly, got {types}"

    _test("anomaly_type_classification", t_anomaly_type_classification)

    # ==================================================================

    # Test 7 -- stability anomaly classification

    # ==================================================================

    def t_stability_anomaly_type() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        stability_outlier = df.head(3).copy()
        stability_outlier["jerk_rms_mps3"]       = 500.0
        stability_outlier["jerk_max_mps3"]        = 900.0
        stability_outlier["jerk_min_mps3"]        = -900.0
        stability_outlier["instability_loss_ms"]  = 500.0
        stability_outlier["mean_yaw_var_ratio"]   = 20.0

        results = detect_anomalies(model, stability_outlier)
        flagged = [r for r in results if r["anomaly_flag"]]
        assert len(flagged) > 0
        types = {r["anomaly_type"] for r in flagged}
        assert "stability_anomaly" in types, f"Expected stability_anomaly, got {types}"

    _test("stability_anomaly_type", t_stability_anomaly_type)

    # ==================================================================

    # Test 8 -- model fallback chain

    # ==================================================================

    def t_fallback_chain() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        # Query with an unknown track -> should resolve to global fallback

        unknown = df.head(5).copy()
        unknown[COL_TRACK_ID]    = "unknown_track"
        unknown[COL_TRACK_STATE] = "unknown_state"

        results = detect_anomalies(model, unknown)
        assert len(results) == 5
        for r in results:
            assert r["condition_key"] == ("__global__", "")

    _test("fallback_chain", t_fallback_chain)

    # ==================================================================

    # Test 9 -- normal inlier laps typed as "normal"

    # ==================================================================

    def t_inlier_type_normal() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        results = detect_anomalies(model, df.head(100))
        inliers = [r for r in results if not r["anomaly_flag"]]
        assert len(inliers) > 0
        for r in inliers:
            assert r["anomaly_type"] == "normal"

    _test("inlier_type_normal", t_inlier_type_normal)

    # ==================================================================

    # Test 10 -- segment-level detection

    # ==================================================================

    def t_segment_detection() -> None:
        df = _make_dataset(200)
        model = train_anomaly_model(df)

        # Build segment-level DataFrame (pretend each lap has 5 segments)

        rows = []
        for _, lap_row in df.head(10).iterrows():
            for seg in range(1, 6):
                row = lap_row.copy()
                row[COL_SEGMENT] = seg
                rows.append(row)
        seg_df = pd.DataFrame(rows).reset_index(drop=True)

        results = detect_segment_anomalies(model, seg_df)
        assert len(results) == 50   # 10 laps x 5 segments
        for r in results:
            assert "segment" in r
            assert "anomaly_type" in r

    _test("segment_detection", t_segment_detection)

    # ==================================================================

    # Test 11 -- save and load roundtrip

    # ==================================================================

    def t_save_load() -> None:
        df = _make_dataset(200)
        model = train_anomaly_model(df)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "anomaly_model.joblib"
            save_anomaly_model(model, path)

            assert path.exists()
            assert path.with_suffix(".json").exists()

            loaded = load_anomaly_model(path)
            assert isinstance(loaded, AnomalyModel)
            assert len(loaded.condition_models) == len(model.condition_models)

            # Verify predictions are identical

            sample = df.head(10)
            r_orig   = detect_anomalies(model,  sample)
            r_loaded = detect_anomalies(loaded, sample)
            for a, b in zip(r_orig, r_loaded):
                assert a["anomaly_score"] == b["anomaly_score"]
                assert a["anomaly_flag"]  == b["anomaly_flag"]

    _test("save_load", t_save_load)

    # ==================================================================

    # Test 12 -- deterministic output

    # ==================================================================

    def t_deterministic() -> None:
        df = _make_dataset(300, seed=77)
        model1 = train_anomaly_model(df)
        model2 = train_anomaly_model(df)

        sample = df.head(20)
        r1 = detect_anomalies(model1, sample)
        r2 = detect_anomalies(model2, sample)

        for a, b in zip(r1, r2):
            assert a["anomaly_score"] == b["anomaly_score"]
            assert a["anomaly_flag"]  == b["anomaly_flag"]
            assert a["anomaly_type"]  == b["anomaly_type"]

    _test("deterministic", t_deterministic)

    # ==================================================================

    # Test 13 -- insufficient data returns empty model (graceful degradation)

    # ==================================================================

    def t_insufficient_data() -> None:
        df = _make_dataset(5)
        model = train_anomaly_model(df)
        # Should return an empty model, not raise

        assert isinstance(model, AnomalyModel)
        assert len(model.condition_models) == 0
        assert model.total_samples == 5
        # detect_anomalies on an empty model should return an empty list

        results = detect_anomalies(model, df)
        assert results == []

    _test("insufficient_data", t_insufficient_data)

    # ==================================================================

    # Test 14 -- ModelNotFittedError on empty model

    # ==================================================================

    def t_not_fitted_error() -> None:
        empty_model = AnomalyModel()
        try:
            detect_anomalies(empty_model, _make_dataset(10))
            raise AssertionError("Expected ModelNotFittedError")
        except ModelNotFittedError:
            pass

    _test("not_fitted_error", t_not_fitted_error)

    # ==================================================================

    # Test 15 -- missing metadata columns handled gracefully

    # ==================================================================

    def t_no_metadata_cols() -> None:
        df = _make_dataset(200)
        df = df.drop(columns=[COL_TRACK_ID, COL_TRACK_STATE], errors="ignore")

        model = train_anomaly_model(df)
        # Only global model should exist

        assert ("__global__", "") in model.condition_models
        exact = [k for k in model.condition_models if k[0] != "__global__"]
        assert len(exact) == 0

        results = detect_anomalies(model, df.head(10))
        assert len(results) == 10

    _test("no_metadata_cols", t_no_metadata_cols)

    # ==================================================================

    # Test 16 -- wet vs dry: verify condition model is used

    # ==================================================================

    def t_condition_model_selection() -> None:
        df = _make_dataset(800, seed=55)
        model = train_anomaly_model(df)

        # Pick a wet subset from spa -- should resolve to (spa, wet) model

        wet_spa = df[(df[COL_TRACK_STATE] == "wet") & (df[COL_TRACK_ID] == "spa_2024")].head(10)
        if len(wet_spa) < 5:
            return  # skip if unlucky random draw

        results = detect_anomalies(model, wet_spa)
        for r in results:
            # Should use the exact or track-level model, not global

            assert r["condition_key"][0] == "spa_2024", (
                f"Expected spa_2024 model, got {r['condition_key']}"
            )

    _test("condition_model_selection", t_condition_model_selection)

    # ==================================================================

    # Test 17 -- JSON serialisability of results

    # ==================================================================

    def t_json_serialisable() -> None:
        df = _make_dataset(200)
        model = train_anomaly_model(df)
        results = detect_anomalies(model, df.head(20))

        # condition_key is a tuple -- convert for JSON

        for r in results:
            r["condition_key"] = list(r["condition_key"])
        json.dumps(results)  # should not raise

    _test("json_serialisable", t_json_serialisable)

    # ==================================================================

    # Test 18 -- NaN features handled without crash

    # ==================================================================

    def t_nan_features() -> None:
        df = _make_dataset(200)
        model = train_anomaly_model(df)

        # Inject NaNs into feature columns

        corrupt = df.head(10).copy()
        for col in _available_features(corrupt)[:5]:
            corrupt.loc[corrupt.index[:3], col] = float("nan")

        results = detect_anomalies(model, corrupt)
        assert len(results) == 10
        for r in results:
            assert np.isfinite(r["anomaly_score"])

    _test("nan_features", t_nan_features)

    # ==================================================================

    # Test 19 -- single-track single-state dataset

    # ==================================================================

    def t_single_condition() -> None:
        df = _make_dataset(200, tracks=["monza"], states=["dry"])
        model = train_anomaly_model(df)

        # Should have exact + global

        assert ("monza", "dry") in model.condition_models
        results = detect_anomalies(model, df.head(10))
        assert len(results) == 10

    _test("single_condition", t_single_condition)

    # ==================================================================

    # Test 20 -- contamination rate sanity check

    # ==================================================================

    def t_contamination_rate() -> None:
        df = _make_dataset(1000, seed=123)
        model = train_anomaly_model(df)
        results = detect_anomalies(model, df)

        flagged_pct = sum(1 for r in results if r["anomaly_flag"]) / len(results)
        # With 5% contamination, expect roughly 3--10% flagged

        assert 0.01 < flagged_pct < 0.15, (
            f"Flagged {flagged_pct:.1%} -- outside expected 1-15% range"
        )

    _test("contamination_rate", t_contamination_rate)

    # ==================================================================

    # Test 21 -- feature_cols consistency between model and metadata

    # ==================================================================

    def t_feature_cols_consistency() -> None:
        df = _make_dataset(200)
        model = train_anomaly_model(df)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.joblib"
            save_anomaly_model(model, path)

            meta = json.loads(path.with_suffix(".json").read_text())
            assert meta["feature_cols"] == model.feature_cols

    _test("feature_cols_consistency", t_feature_cols_consistency)

    # ==================================================================

    # Test 22 -- load nonexistent path raises

    # ==================================================================

    def t_load_missing() -> None:
        try:
            load_anomaly_model("/tmp/nonexistent_model.joblib")
            raise AssertionError("Expected FileNotFoundError")
        except FileNotFoundError:
            pass

    _test("load_missing", t_load_missing)

    # ==================================================================

    # Test 23 -- speed anomaly classification

    # ==================================================================

    def t_speed_anomaly_type() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        speed_outlier = df.head(3).copy()
        speed_outlier["speed_mean_mps"] = 200.0
        speed_outlier["speed_max_mps"]  = 300.0
        speed_outlier["speed_min_mps"]  = 150.0
        speed_outlier["speed_p10_mps"]  = 160.0
        speed_outlier["speed_p90_mps"]  = 280.0
        speed_outlier["speed_std_mps"]  = 100.0

        results = detect_anomalies(model, speed_outlier)
        flagged = [r for r in results if r["anomaly_flag"]]
        assert len(flagged) > 0
        types = {r["anomaly_type"] for r in flagged}
        assert "speed_anomaly" in types, f"Expected speed_anomaly, got {types}"

    _test("speed_anomaly_type", t_speed_anomaly_type)

    # ==================================================================

    # Test 24 -- resolve method fallback order

    # ==================================================================

    def t_resolve_order() -> None:
        df = _make_dataset(600)
        model = train_anomaly_model(df)

        # Exact match

        if ("spa_2024", "dry") in model.condition_models:
            cm = model.resolve("spa_2024", "dry")
            assert cm.track_id == "spa_2024"
            assert cm.track_state == "dry"

        # Track fallback

        cm = model.resolve("spa_2024", "snow")
        assert cm.track_id in ("spa_2024", "__global__")

        # Global fallback

        cm = model.resolve("nurburgring", "fog")
        assert cm.track_id == "__global__"

    _test("resolve_order", t_resolve_order)

    # ==================================================================

    # Test 25 -- large batch performance (no crash, finite scores)

    # ==================================================================

    def t_large_batch() -> None:
        df = _make_dataset(2000, seed=42)
        model = train_anomaly_model(df)
        results = detect_anomalies(model, df)

        assert len(results) == 2000
        for r in results:
            assert np.isfinite(r["anomaly_score"])

    _test("large_batch", t_large_batch)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nAnomaly Detection Tests: {len(passed)}/{total} passed [{status}]")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# ============================================================================

# Entry point

# ============================================================================


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()