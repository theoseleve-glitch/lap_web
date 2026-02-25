"""
ml_engine.py
------------
Production-grade ML engine for motorsport telemetry.

Implements three layers:
  1. **Global performance model** — GradientBoostingRegressor predicting
     ``lap_time_s`` from telemetry features.  Optionally filtered by
     ``track_id`` / ``track_state``.
  2. **Driver-specific model** — Per-driver GradientBoostingRegressor trained
     on driver-filtered data with an additional ``deviation_from_global``
     feature computed as normalised Euclidean distance from the global
     optimal feature vector.
  3. **Anomaly detection** — IsolationForest trained per-driver to flag
     mechanically or behaviourally abnormal laps.

Storage layout (under ``Data/``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    Data/
    ├── processed/
    │   └── features.parquet          # canonical feature dataset
    └── models/
        ├── global/
        │   ├── model.joblib
        │   └── metadata.json
        └── drivers/
            └── <driver_name>/
                ├── regression.joblib
                ├── anomaly.joblib
                └── metadata.json

Design principles
~~~~~~~~~~~~~~~~~
- **Fully offline** — no network calls, no cloud dependencies.
- **Deterministic** — ``random_state=42`` everywhere; identical inputs
  produce identical outputs.
- **No global variables** — all state is passed explicitly or loaded
  from disk.
- **Structured logging** — no print statements.
- **NaN-robust** — rows with NaN features are dropped before training
  with a logged warning.
- **Parquet preferred, CSV fallback** — pyarrow is optional.
- **Joblib for models, JSON for metadata** — aligned with
  ``model_registry.py`` conventions.

Column contract
~~~~~~~~~~~~~~~
This module consumes the feature dataset produced by ``feature_builder.py``.
Column names are imported from there to eliminate magic strings.
"""

from __future__ import annotations

import json
import logging
import math
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# -- -

# Conditional pyarrow import

# -- -

try:
    import pyarrow.parquet as pq
    _HAS_PYARROW = True
except ImportError:
    pq = None  # type: ignore[assignment]
    _HAS_PYARROW = False


# ============================================================================

# Column-name constants  (mirror feature_builder.py — single source of truth)

# ============================================================================


# Metadata

COL_TRACK_ID:      Final[str] = "track_id"
COL_TRACK_STATE:   Final[str] = "track_state"
COL_DRIVER_NAME:   Final[str] = "driver_name"
COL_SESSION_ID:    Final[str] = "session_id"
COL_LAP_NUMBER:    Final[str] = "lap_number"

METADATA_COLS: Final[list[str]] = [
    COL_TRACK_ID, COL_TRACK_STATE, COL_DRIVER_NAME,
    COL_SESSION_ID, COL_LAP_NUMBER,
]

# Target

COL_LAP_TIME: Final[str] = "lap_time_s"

# Numeric features used by the ML models (subset of feature_builder columns

# that are meaningful predictors — excludes target and metadata).

FEATURE_COLS: Final[list[str]] = [
    "speed_min_mps",
    "speed_max_mps",
    "speed_mean_mps",
    "speed_std_mps",
    "speed_p10_mps",
    "speed_p90_mps",
    "accel_max_mps2",
    "braking_max_mps2",
    "accel_rms_mps2",
    "jerk_rms_mps3",
    "jerk_max_mps3",
    "jerk_min_mps3",
    "lat_accel_max_mps2",
    "lat_accel_rms_mps2",
    "line_length_m",
    "delta_to_theoretical_s",
    "total_time_loss_ms",
    "entry_loss_ms",
    "mid_corner_loss_ms",
    "exit_loss_ms",
    "instability_loss_ms",
    "line_inefficiency_loss_ms",
    "mean_entry_speed_diff_mps",
    "mean_min_speed_diff_mps",
    "mean_exit_accel_diff_mps2",
    "mean_yaw_var_ratio",
]

# Segment-loss columns (for secondary targets / diagnostics)

SEGMENT_LOSS_COLS: Final[list[str]] = [
    "total_time_loss_ms",
    "entry_loss_ms",
    "mid_corner_loss_ms",
    "exit_loss_ms",
    "instability_loss_ms",
    "line_inefficiency_loss_ms",
]

# Derived feature injected by this module

COL_DEVIATION: Final[str] = "deviation_from_global"

# ============================================================================

# Model constants

# ============================================================================


RANDOM_STATE:            Final[int]   = 42
TEST_SIZE:               Final[float] = 0.20
GBR_N_ESTIMATORS:        Final[int]   = 200
GBR_MAX_DEPTH:           Final[int]   = 5
GBR_LEARNING_RATE:       Final[float] = 0.05
GBR_MIN_SAMPLES_LEAF:    Final[int]   = 5
ISO_CONTAMINATION:       Final[float] = 0.05
ISO_N_ESTIMATORS:        Final[int]   = 150
RETRAIN_GROWTH_RATIO:    Final[float] = 1.10
MIN_DRIVER_SAMPLES:      Final[int]   = 10

# File names

_MODEL_FILENAME:         Final[str] = "model.joblib"
_REGRESSION_FILENAME:    Final[str] = "regression.joblib"
_ANOMALY_FILENAME:       Final[str] = "anomaly.joblib"
_SCALER_FILENAME:        Final[str] = "scaler.joblib"
_METADATA_FILENAME:      Final[str] = "metadata.json"
_FEATURES_PARQUET:       Final[str] = "features.parquet"
_FEATURES_CSV:           Final[str] = "features.csv"


# ============================================================================

# Exceptions

# ============================================================================


class MLEngineError(Exception):
    """Base exception for ml_engine errors."""


class DatasetError(MLEngineError, ValueError):
    """Raised when the dataset is missing, empty, or structurally invalid."""


class ModelNotFoundError(MLEngineError, FileNotFoundError):
    """Raised when a persisted model cannot be located on disk."""


class InsufficientDataError(MLEngineError, ValueError):
    """Raised when there are too few samples to train."""


# ============================================================================

# Internal helpers — I/O

# ============================================================================


def _resolve_dataset_path(data_dir: Path) -> Path:
    """Find the features file (parquet preferred, CSV fallback)."""
    parquet = data_dir / "processed" / _FEATURES_PARQUET
    csv     = data_dir / "processed" / _FEATURES_CSV
    if parquet.exists():
        return parquet
    if csv.exists():
        return csv
    raise DatasetError(
        f"Feature dataset not found.  Searched:\n"
        f"  {parquet}\n  {csv}"
    )


def _load_dataset(data_dir: Path) -> pd.DataFrame:
    """Load the feature dataset from disk."""
    path = _resolve_dataset_path(data_dir)
    if _HAS_PYARROW and path.suffix == ".parquet":
        df = pq.read_table(path).to_pandas()
    else:
        df = pd.read_csv(path)
    logger.info("Loaded dataset: %d rows x %d cols from %s", len(df), len(df.columns), path)
    return df


def _save_json(data: dict[str, Any], path: Path) -> None:
    """Write *data* as indented JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    """Read JSON from *path*."""
    return json.loads(path.read_text(encoding="utf-8"))


def _global_model_dir(data_dir: Path) -> Path:
    return data_dir / "models" / "global"


def _driver_model_dir(data_dir: Path, driver_name: str) -> Path:
    return data_dir / "models" / "drivers" / driver_name


# ============================================================================

# Internal helpers — data preparation

# ============================================================================


def _available_features(df: pd.DataFrame) -> list[str]:
    """Return the subset of FEATURE_COLS actually present in *df*."""
    return [c for c in FEATURE_COLS if c in df.columns]


def _prepare_features(
    df: pd.DataFrame,
    feature_cols: list[str],
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Extract numeric feature matrix and target vector, dropping NaN rows.

    Returns
    -------
    X:  Feature DataFrame (clean, numeric)
    y:  Target Series
    used_cols:  Feature columns actually used
    """
    if COL_LAP_TIME not in df.columns:
        raise DatasetError(f"Target column {COL_LAP_TIME!r} not found in dataset.")

    available = [c for c in feature_cols if c in df.columns]
    if not available:
        raise DatasetError("No feature columns found in dataset.")

    subset = df[available + [COL_LAP_TIME]].copy()
    for col in available:
        subset[col] = pd.to_numeric(subset[col], errors="coerce")
    subset[COL_LAP_TIME] = pd.to_numeric(subset[COL_LAP_TIME], errors="coerce")

    n_before = len(subset)
    subset = subset.dropna()
    n_dropped = n_before - len(subset)
    if n_dropped > 0:
        logger.warning("Dropped %d/%d rows with NaN values.", n_dropped, n_before)

    if subset.empty:
        raise DatasetError("No valid samples remain after NaN removal.")

    X = subset[available]
    y = subset[COL_LAP_TIME]
    return X, y, available


# ============================================================================

# Deviation from global optimal

# ============================================================================


def compute_deviation_from_global_optimal(
    feature_df: pd.DataFrame,
    global_reference_vector: np.ndarray,
    feature_cols: list[str],
    *,
    scaler: Optional[StandardScaler] = None,
) -> np.ndarray:
    """
    Compute normalised Euclidean distance from each row to the global
    optimal reference point in feature space.

    Parameters
    ----------
    feature_df:
        DataFrame with numeric feature columns.
    global_reference_vector:
        1-D array of the same length as *feature_cols* representing the
        optimal operating point (typically the feature-space centroid of the
        best N% of laps).
    feature_cols:
        Ordered list of feature column names corresponding to the
        reference vector.
    scaler:
        If provided, features are standardised before distance computation
        so that high-variance features do not dominate.

    Returns
    -------
    np.ndarray
        Per-row deviation scores (>= 0).  Lower is closer to optimal.
    """
    available = [c for c in feature_cols if c in feature_df.columns]
    if not available:
        return np.full(len(feature_df), float("nan"))

    X = feature_df[available].apply(pd.to_numeric, errors="coerce").values.copy()

    # Build aligned reference (only the available columns)

    ref_indices = [feature_cols.index(c) for c in available]
    ref = global_reference_vector[ref_indices]

    if scaler is not None:
        # Use scaler fitted on training data; only transform available columns.

        # If the scaler was fitted on a different column set, fall back to raw.

        try:
            X = scaler.transform(X)
            ref = scaler.transform(ref.reshape(1, -1)).flatten()
        except Exception:
            logger.debug("Scaler transform failed; using raw features for deviation.")

    # Replace remaining NaN with 0 (neutral) for distance computation

    X = np.where(np.isfinite(X), X, 0.0)
    ref = np.where(np.isfinite(ref), ref, 0.0)

    # Euclidean distance

    diff = X - ref
    raw_dist = np.sqrt(np.sum(diff ** 2, axis=1))

    # Normalise to [0, 1] range using the observed max (or 1 if all identical)

    max_dist = raw_dist.max()
    if max_dist > 0:
        return raw_dist / max_dist
    return raw_dist


# ============================================================================

# Global model

# ============================================================================


def train_global_model(
    data_dir: str | Path,
    *,
    track_id: Optional[str] = None,
    track_state: Optional[str] = None,
) -> dict[str, Any]:
    """
    Train the global GradientBoostingRegressor on the full feature dataset.

    Parameters
    ----------
    data_dir:
        Project data root containing ``processed/features.*`` and where
        ``models/global/`` will be created.
    track_id:
        If provided, filter dataset to this track only.
    track_state:
        If provided, filter dataset to this condition (e.g. "dry").

    Returns
    -------
    dict
        Training metadata including MAE, feature importance, sample count.

    Raises
    ------
    DatasetError
        If the dataset is missing or empty.
    InsufficientDataError
        If fewer than 2 samples remain after filtering.
    """
    data_dir = Path(data_dir)
    df = _load_dataset(data_dir)

    # -- Filter -- -

    if track_id is not None and COL_TRACK_ID in df.columns:
        df = df[df[COL_TRACK_ID] == track_id]
        logger.info("Filtered to track_id=%r: %d rows", track_id, len(df))

    if track_state is not None and COL_TRACK_STATE in df.columns:
        df = df[df[COL_TRACK_STATE] == track_state]
        logger.info("Filtered to track_state=%r: %d rows", track_state, len(df))

    # -- Prepare
    feature_cols = _available_features(df)
    X, y, used_cols = _prepare_features(df, feature_cols)

    if len(X) < 2:
        raise InsufficientDataError(
            f"Need at least 2 samples to train; got {len(X)} after filtering."
        )

    # -- Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE,
    )

    # -- Fit scaler (for deviation computation later) -- -

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    # -- Compute global reference vector (centroid of best 10% laps)
    best_threshold = y_train.quantile(0.10)  # lower lap time = better
    best_mask = y_train <= best_threshold
    if best_mask.sum() >= 1:
        global_ref = X_train[best_mask].mean(axis=0).values
    else:
        global_ref = X_train.mean(axis=0).values

    # -- Train
    model = GradientBoostingRegressor(
        n_estimators=GBR_N_ESTIMATORS,
        max_depth=GBR_MAX_DEPTH,
        learning_rate=GBR_LEARNING_RATE,
        min_samples_leaf=GBR_MIN_SAMPLES_LEAF,
        random_state=RANDOM_STATE,
    )
    model.fit(X_train_scaled, y_train)

    # -- Evaluate -- -

    y_pred = model.predict(X_test_scaled)
    mae = float(mean_absolute_error(y_test, y_pred))

    # -- Feature importance -- -

    importances = dict(zip(used_cols, model.feature_importances_.tolist()))

    # -- Persist
    model_dir = _global_model_dir(data_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(model,  model_dir / _MODEL_FILENAME)
    joblib.dump(scaler, model_dir / _SCALER_FILENAME)

    metadata = {
        "model_type":           "global_lap_time",
        "created_at":           datetime.now(timezone.utc).isoformat(),
        "training_samples":     int(len(X_train)),
        "test_samples":         int(len(X_test)),
        "total_samples":        int(len(X)),
        "mae":                  round(mae, 6),
        "feature_list":         used_cols,
        "feature_importance":   importances,
        "global_reference":     global_ref.tolist(),
        "track_id":             track_id,
        "track_state":          track_state,
        "hyperparameters": {
            "n_estimators":     GBR_N_ESTIMATORS,
            "max_depth":        GBR_MAX_DEPTH,
            "learning_rate":    GBR_LEARNING_RATE,
            "min_samples_leaf": GBR_MIN_SAMPLES_LEAF,
            "random_state":     RANDOM_STATE,
        },
    }
    _save_json(metadata, model_dir / _METADATA_FILENAME)

    logger.info(
        "Global model trained: %d samples, MAE=%.4f, features=%d",
        len(X_train), mae, len(used_cols),
    )
    return metadata


def predict_lap_time(
    features_df: pd.DataFrame,
    data_dir: str | Path,
) -> np.ndarray:
    """
    Predict lap times using the persisted global model.

    Parameters
    ----------
    features_df:
        DataFrame with numeric feature columns.
    data_dir:
        Project data root where the model was saved.

    Returns
    -------
    np.ndarray
        Predicted lap times (seconds).

    Raises
    ------
    ModelNotFoundError
        If the global model has not been trained.
    """
    data_dir  = Path(data_dir)
    model_dir = _global_model_dir(data_dir)
    model_path  = model_dir / _MODEL_FILENAME
    scaler_path = model_dir / _SCALER_FILENAME
    meta_path   = model_dir / _METADATA_FILENAME

    if not model_path.exists():
        raise ModelNotFoundError(f"Global model not found at {model_path}")

    model    = joblib.load(model_path)
    metadata = _load_json(meta_path)
    feature_list = metadata["feature_list"]

    # Align columns to what the model expects

    available = [c for c in feature_list if c in features_df.columns]
    if not available:
        raise DatasetError("No matching feature columns in input DataFrame.")

    X = features_df[available].apply(pd.to_numeric, errors="coerce").fillna(0.0).values

    # Scale if scaler exists

    if scaler_path.exists():
        scaler = joblib.load(scaler_path)
        try:
            X = scaler.transform(X)
        except Exception:
            logger.debug("Scaler transform failed during prediction; using raw features.")

    return model.predict(X)


def get_feature_importance(data_dir: str | Path) -> dict[str, float]:
    """
    Return feature importance from the persisted global model metadata.

    Returns
    -------
    dict[str, float]
        Feature name → importance score, sorted descending.

    Raises
    ------
    ModelNotFoundError
        If the global model metadata is not found.
    """
    meta_path = _global_model_dir(Path(data_dir)) / _METADATA_FILENAME
    if not meta_path.exists():
        raise ModelNotFoundError(f"Global metadata not found at {meta_path}")

    metadata = _load_json(meta_path)
    imp = metadata.get("feature_importance", {})
    return dict(sorted(imp.items(), key=lambda kv: kv[1], reverse=True))


# ============================================================================

# Driver model

# ============================================================================


def train_driver_model(
    driver_name: str,
    data_dir: str | Path,
) -> dict[str, Any]:
    """
    Train a driver-specific regression model and anomaly detector.

    Steps:
      1. Load dataset filtered to *driver_name*.
      2. Load the global reference vector (from global model metadata).
      3. Compute ``deviation_from_global`` for each lap.
      4. Train a ``GradientBoostingRegressor`` on features + deviation.
      5. Train an ``IsolationForest`` anomaly detector on the same space.
      6. Persist both models and metadata.

    Parameters
    ----------
    driver_name:
        Name of the driver to filter on.
    data_dir:
        Project data root.

    Returns
    -------
    dict
        Training metadata.

    Raises
    ------
    DatasetError / InsufficientDataError / ModelNotFoundError
    """
    data_dir = Path(data_dir)
    df = _load_dataset(data_dir)

    # -- Filter to driver -- -

    if COL_DRIVER_NAME not in df.columns:
        raise DatasetError(f"Column {COL_DRIVER_NAME!r} not in dataset.")

    driver_df = df[df[COL_DRIVER_NAME] == driver_name].copy()
    if driver_df.empty:
        raise InsufficientDataError(
            f"No data found for driver {driver_name!r}."
        )

    # -- Prepare features -- -

    feature_cols = _available_features(driver_df)
    X, y, used_cols = _prepare_features(driver_df, feature_cols)

    if len(X) < MIN_DRIVER_SAMPLES:
        raise InsufficientDataError(
            f"Driver {driver_name!r} has only {len(X)} samples; "
            f"need >= {MIN_DRIVER_SAMPLES}."
        )

    # -- Load global reference for deviation
    global_meta_path = _global_model_dir(data_dir) / _METADATA_FILENAME
    global_ref: np.ndarray | None = None
    global_scaler: StandardScaler | None = None

    if global_meta_path.exists():
        global_meta = _load_json(global_meta_path)
        ref_list = global_meta.get("global_reference")
        if ref_list is not None:
            global_ref = np.array(ref_list, dtype=float)
        scaler_path = _global_model_dir(data_dir) / _SCALER_FILENAME
        if scaler_path.exists():
            global_scaler = joblib.load(scaler_path)
    else:
        logger.warning(
            "Global model not found; training driver model without deviation feature."
        )

    # -- Compute deviation feature
    if global_ref is not None:
        global_feature_list = global_meta.get("feature_list", used_cols)
        deviation = compute_deviation_from_global_optimal(
            X, global_ref, global_feature_list, scaler=global_scaler,
        )
        X = X.copy()
        X[COL_DEVIATION] = deviation
        augmented_cols = used_cols + [COL_DEVIATION]
    else:
        augmented_cols = used_cols

    # -- Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE,
    )

    # -- Fit driver scaler
    driver_scaler = StandardScaler()
    X_train_scaled = driver_scaler.fit_transform(X_train)
    X_test_scaled  = driver_scaler.transform(X_test)

    # -- Train regression -- -

    reg_model = GradientBoostingRegressor(
        n_estimators=GBR_N_ESTIMATORS,
        max_depth=GBR_MAX_DEPTH,
        learning_rate=GBR_LEARNING_RATE,
        min_samples_leaf=min(GBR_MIN_SAMPLES_LEAF, max(1, len(X_train) // 4)),
        random_state=RANDOM_STATE,
    )
    reg_model.fit(X_train_scaled, y_train)

    y_pred = reg_model.predict(X_test_scaled)
    mae = float(mean_absolute_error(y_test, y_pred))

    # -- Train anomaly detector -- -

    iso_model = IsolationForest(
        n_estimators=ISO_N_ESTIMATORS,
        contamination=ISO_CONTAMINATION,
        random_state=RANDOM_STATE,
    )
    iso_model.fit(X_train_scaled)

    # -- Feature importance -- -

    importances = dict(zip(augmented_cols, reg_model.feature_importances_.tolist()))

    # -- Persist
    driver_dir = _driver_model_dir(data_dir, driver_name)
    driver_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(reg_model,      driver_dir / _REGRESSION_FILENAME)
    joblib.dump(iso_model,      driver_dir / _ANOMALY_FILENAME)
    joblib.dump(driver_scaler,  driver_dir / _SCALER_FILENAME)

    metadata = {
        "model_type":           "driver_lap_time",
        "driver_name":          driver_name,
        "created_at":           datetime.now(timezone.utc).isoformat(),
        "training_samples":     int(len(X_train)),
        "test_samples":         int(len(X_test)),
        "total_samples":        int(len(X)),
        "mae":                  round(mae, 6),
        "feature_list":         augmented_cols,
        "feature_importance":   importances,
        "has_deviation":        global_ref is not None,
        "hyperparameters": {
            "regression": {
                "n_estimators":     GBR_N_ESTIMATORS,
                "max_depth":        GBR_MAX_DEPTH,
                "learning_rate":    GBR_LEARNING_RATE,
                "random_state":     RANDOM_STATE,
            },
            "anomaly": {
                "n_estimators":     ISO_N_ESTIMATORS,
                "contamination":    ISO_CONTAMINATION,
                "random_state":     RANDOM_STATE,
            },
        },
    }
    _save_json(metadata, driver_dir / _METADATA_FILENAME)

    logger.info(
        "Driver model trained: driver=%r, %d samples, MAE=%.4f",
        driver_name, len(X_train), mae,
    )
    return metadata


# ============================================================================

# Anomaly detection

# ============================================================================


def detect_driver_anomalies(
    driver_name: str,
    feature_df: pd.DataFrame,
    data_dir: str | Path,
) -> list[dict[str, Any]]:
    """
    Score each lap in *feature_df* for anomalies using the driver's
    persisted IsolationForest.

    Parameters
    ----------
    driver_name:
        Driver whose model to load.
    feature_df:
        DataFrame with feature columns and ``lap_number``.
    data_dir:
        Project data root.

    Returns
    -------
    list[dict]
        One entry per row::

            {
                "lap_number": int,
                "anomaly_score": float,   # lower = more anomalous
                "anomaly_flag": bool,     # True = anomaly
            }

    Raises
    ------
    ModelNotFoundError
        If the driver model has not been trained.
    """
    data_dir   = Path(data_dir)
    driver_dir = _driver_model_dir(data_dir, driver_name)

    anomaly_path = driver_dir / _ANOMALY_FILENAME
    scaler_path  = driver_dir / _SCALER_FILENAME
    meta_path    = driver_dir / _METADATA_FILENAME

    if not anomaly_path.exists():
        raise ModelNotFoundError(
            f"Anomaly model not found for driver {driver_name!r} at {anomaly_path}"
        )

    iso_model = joblib.load(anomaly_path)
    metadata  = _load_json(meta_path)
    feature_list = metadata["feature_list"]

    # Align columns

    available = [c for c in feature_list if c in feature_df.columns]

    # Handle deviation_from_global if the model expects it

    working_df = feature_df.copy()
    if COL_DEVIATION in feature_list and COL_DEVIATION not in working_df.columns:
        global_meta_path = _global_model_dir(data_dir) / _METADATA_FILENAME
        if global_meta_path.exists():
            global_meta = _load_json(global_meta_path)
            ref = global_meta.get("global_reference")
            if ref is not None:
                global_scaler_path = _global_model_dir(data_dir) / _SCALER_FILENAME
                gs = joblib.load(global_scaler_path) if global_scaler_path.exists() else None
                dev = compute_deviation_from_global_optimal(
                    working_df, np.array(ref), global_meta.get("feature_list", []),
                    scaler=gs,
                )
                working_df[COL_DEVIATION] = dev
                available = [c for c in feature_list if c in working_df.columns]

    if not available:
        raise DatasetError("No matching feature columns for anomaly detection.")

    X = working_df[available].apply(pd.to_numeric, errors="coerce").fillna(0.0).values

    if scaler_path.exists():
        scaler = joblib.load(scaler_path)
        try:
            X = scaler.transform(X)
        except Exception:
            logger.debug("Scaler transform failed; using raw features.")

    # IsolationForest: score_samples returns negative for anomalies,

    # predict returns -1 for anomalies, 1 for inliers.

    scores = iso_model.score_samples(X)
    labels = iso_model.predict(X)

    # Extract lap numbers

    if COL_LAP_NUMBER in feature_df.columns:
        lap_numbers = feature_df[COL_LAP_NUMBER].tolist()
    else:
        lap_numbers = list(range(1, len(feature_df) + 1))

    results: list[dict[str, Any]] = []
    for i, (lap_num, score, label) in enumerate(zip(lap_numbers, scores, labels)):
        results.append({
            "lap_number":    int(lap_num) if not isinstance(lap_num, (int, np.integer)) else int(lap_num),
            "anomaly_score": round(float(score), 6),
            "anomaly_flag":  bool(label == -1),
        })

    n_anomalies = sum(1 for r in results if r["anomaly_flag"])
    logger.info(
        "Anomaly detection: driver=%r, %d laps, %d anomalies flagged.",
        driver_name, len(results), n_anomalies,
    )
    return results


# ============================================================================

# Drift management

# ============================================================================


def should_retrain(
    previous_metadata: dict[str, Any],
    new_sample_count: int,
    *,
    growth_ratio: float = RETRAIN_GROWTH_RATIO,
    mae_degradation_threshold: float = 0.0,
) -> bool:
    """
    Decide whether a model should be retrained.

    Triggers retrain if **either**:
      - New sample count increased by more than ``growth_ratio`` (default 10%)
        over the training set.
      - The MAE has degraded (caller passes a new MAE via metadata).

    Parameters
    ----------
    previous_metadata:
        Metadata dict from the existing model (must contain
        ``training_samples`` and ``mae``).
    new_sample_count:
        Current number of available training rows.
    growth_ratio:
        Multiplier threshold (default 1.10 = 10% growth triggers retrain).
    mae_degradation_threshold:
        If the previous MAE exceeds this value, retrain.  Set to 0 to
        disable MAE-based triggering.

    Returns
    -------
    bool
        True if retraining is recommended.
    """
    if "training_samples" not in previous_metadata:
        raise DatasetError("previous_metadata missing 'training_samples'.")

    old_count = previous_metadata["training_samples"]
    old_mae   = previous_metadata.get("mae", 0.0)

    # Rule 1: data growth

    threshold = old_count * growth_ratio
    data_growth = new_sample_count >= threshold

    # Rule 2: MAE degradation

    mae_degraded = (
        mae_degradation_threshold > 0
        and old_mae > mae_degradation_threshold
    )

    decision = data_growth or mae_degraded
    logger.debug(
        "should_retrain: old=%d new=%d threshold=%.1f growth=%s "
        "mae=%.4f mae_thresh=%.4f degraded=%s -> %s",
        old_count, new_sample_count, threshold, data_growth,
        old_mae, mae_degradation_threshold, mae_degraded,
        "RETRAIN" if decision else "SKIP",
    )
    return decision


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """Self-contained test suite — run with ``python ml_engine.py``."""
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Synthetic dataset factory -- -


    def _make_dataset(n: int = 1000, seed: int = 42) -> pd.DataFrame:
        """
        Generate a synthetic feature dataset with structured relationships.
        lap_time_s is modelled as a linear combination of features + noise.
        """
        rng = np.random.default_rng(seed)

        data: dict[str, Any] = {}

        # Metadata

        tracks = ["spa_2024", "monza_2024", "silverstone_2024"]
        states = ["dry", "wet"]
        drivers = ["DriverA", "DriverB", "DriverC"]

        data[COL_TRACK_ID]    = rng.choice(tracks, n).tolist()
        data[COL_TRACK_STATE] = rng.choice(states, n).tolist()
        data[COL_DRIVER_NAME] = rng.choice(drivers, n).tolist()
        data[COL_SESSION_ID]  = [f"sess_{i // 20:03d}" for i in range(n)]
        data[COL_LAP_NUMBER]  = (np.arange(n) % 20 + 1).tolist()

        # Features (with correlated structure)

        speed_mean = 42.0 + rng.normal(0, 3, n)
        speed_std  = 12.0 + rng.normal(0, 1, n)
        accel_max  = 6.0  + rng.normal(0, 0.5, n)
        braking    = 12.0 + rng.normal(0, 1, n)
        jerk_rms   = 18.0 + rng.normal(0, 3, n)

        data["speed_min_mps"]              = (speed_mean - 2 * speed_std + rng.normal(0, 0.5, n)).tolist()
        data["speed_max_mps"]              = (speed_mean + 2 * speed_std + rng.normal(0, 0.5, n)).tolist()
        data["speed_mean_mps"]             = speed_mean.tolist()
        data["speed_std_mps"]              = np.abs(speed_std).tolist()
        data["speed_p10_mps"]              = (speed_mean - 1.3 * speed_std).tolist()
        data["speed_p90_mps"]              = (speed_mean + 1.3 * speed_std).tolist()
        data["accel_max_mps2"]             = accel_max.tolist()
        data["braking_max_mps2"]           = braking.tolist()
        data["accel_rms_mps2"]             = (accel_max * 0.6 + rng.normal(0, 0.1, n)).tolist()
        data["jerk_rms_mps3"]              = jerk_rms.tolist()
        data["jerk_max_mps3"]              = (jerk_rms * 1.8 + rng.normal(0, 1, n)).tolist()
        data["jerk_min_mps3"]              = (-jerk_rms * 2.0 + rng.normal(0, 1, n)).tolist()
        data["lat_accel_max_mps2"]         = (10.0 + rng.normal(0, 1, n)).tolist()
        data["lat_accel_rms_mps2"]         = (5.0 + rng.normal(0, 0.5, n)).tolist()
        data["line_length_m"]              = (4500.0 + rng.normal(0, 10, n)).tolist()
        data["delta_to_theoretical_s"]     = np.abs(1.5 + rng.normal(0, 0.5, n)).tolist()
        data["total_time_loss_ms"]         = np.abs(100 + rng.normal(0, 30, n)).tolist()
        data["entry_loss_ms"]              = np.abs(15 + rng.normal(0, 8, n)).tolist()
        data["mid_corner_loss_ms"]         = np.abs(20 + rng.normal(0, 10, n)).tolist()
        data["exit_loss_ms"]               = np.abs(10 + rng.normal(0, 5, n)).tolist()
        data["instability_loss_ms"]        = np.abs(5 + rng.normal(0, 3, n)).tolist()
        data["line_inefficiency_loss_ms"]  = np.abs(8 + rng.normal(0, 4, n)).tolist()
        data["mean_entry_speed_diff_mps"]  = rng.normal(0.5, 1, n).tolist()
        data["mean_min_speed_diff_mps"]    = rng.normal(0.3, 0.8, n).tolist()
        data["mean_exit_accel_diff_mps2"]  = rng.normal(0.1, 0.3, n).tolist()
        data["mean_yaw_var_ratio"]         = (1.0 + np.abs(rng.normal(0, 0.3, n))).tolist()
        data["n_loss_segments"]            = rng.integers(0, 15, n).tolist()

        # Target: lap_time_s as linear combination + noise

        lap_time = (
            90.0
            - 0.3  * speed_mean
            + 0.15 * braking
            + 0.08 * jerk_rms
            + 0.05 * np.array(data["delta_to_theoretical_s"])
            + rng.normal(0, 0.5, n)
        )
        data[COL_LAP_TIME] = lap_time.tolist()

        return pd.DataFrame(data)

    def _save_dataset(df: pd.DataFrame, tmpdir: str) -> Path:
        """Save dataset to the expected location."""
        data_dir = Path(tmpdir)
        out_dir = data_dir / "processed"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / _FEATURES_CSV
        df.to_csv(path, index=False)
        return data_dir

    #
    # Test 1 — global model training

    #
    def t_global_model_training() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(1000)
            data_dir = _save_dataset(df, tmpdir)

            meta = train_global_model(data_dir)

            assert meta["training_samples"] > 0
            assert meta["mae"] >= 0
            assert len(meta["feature_list"]) > 0
            assert len(meta["feature_importance"]) > 0
            assert isinstance(meta["global_reference"], list)

            # Artefacts on disk

            gdir = _global_model_dir(data_dir)
            assert (gdir / _MODEL_FILENAME).exists()
            assert (gdir / _SCALER_FILENAME).exists()
            assert (gdir / _METADATA_FILENAME).exists()

    _test("global_model_training", t_global_model_training)

    #
    # Test 2 — global model with track/state filter

    #
    def t_global_model_filtered() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(1000)
            data_dir = _save_dataset(df, tmpdir)

            meta = train_global_model(data_dir, track_id="spa_2024", track_state="dry")
            assert meta["track_id"] == "spa_2024"
            assert meta["track_state"] == "dry"
            assert meta["training_samples"] > 0

    _test("global_model_filtered", t_global_model_filtered)

    #
    # Test 3 — prediction consistency

    #
    def t_prediction_consistency() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(500)
            data_dir = _save_dataset(df, tmpdir)
            train_global_model(data_dir)

            sample = df.head(10)
            pred1 = predict_lap_time(sample, data_dir)
            pred2 = predict_lap_time(sample, data_dir)

            np.testing.assert_array_equal(pred1, pred2)
            assert len(pred1) == 10
            assert all(np.isfinite(pred1))

    _test("prediction_consistency", t_prediction_consistency)

    #
    # Test 4 — feature importance

    #
    def t_feature_importance() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(500)
            data_dir = _save_dataset(df, tmpdir)
            train_global_model(data_dir)

            imp = get_feature_importance(data_dir)
            assert isinstance(imp, dict)
            assert len(imp) > 0
            # Should be sorted descending

            vals = list(imp.values())
            assert vals == sorted(vals, reverse=True)

    _test("feature_importance", t_feature_importance)

    #
    # Test 5 — driver model training

    #
    def t_driver_model_training() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(1000)
            data_dir = _save_dataset(df, tmpdir)

            # Train global first (needed for deviation)

            train_global_model(data_dir)

            meta = train_driver_model("DriverA", data_dir)
            assert meta["driver_name"] == "DriverA"
            assert meta["mae"] >= 0
            assert meta["training_samples"] > 0
            assert meta["has_deviation"] is True

            # Artefacts on disk

            ddir = _driver_model_dir(data_dir, "DriverA")
            assert (ddir / _REGRESSION_FILENAME).exists()
            assert (ddir / _ANOMALY_FILENAME).exists()
            assert (ddir / _SCALER_FILENAME).exists()
            assert (ddir / _METADATA_FILENAME).exists()

    _test("driver_model_training", t_driver_model_training)

    #
    # Test 6 — driver model without global model

    #
    def t_driver_model_no_global() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(500)
            data_dir = _save_dataset(df, tmpdir)

            # Train driver directly without global model

            meta = train_driver_model("DriverA", data_dir)
            assert meta["has_deviation"] is False
            assert meta["training_samples"] > 0

    _test("driver_model_no_global", t_driver_model_no_global)

    #
    # Test 7 — anomaly detection

    #
    def t_anomaly_detection() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(1000)
            data_dir = _save_dataset(df, tmpdir)

            train_global_model(data_dir)
            train_driver_model("DriverA", data_dir)

            # Normal laps

            driver_data = df[df[COL_DRIVER_NAME] == "DriverA"].head(20)
            results = detect_driver_anomalies("DriverA", driver_data, data_dir)

            assert isinstance(results, list)
            assert len(results) == 20
            for r in results:
                assert "lap_number" in r
                assert "anomaly_score" in r
                assert "anomaly_flag" in r
                assert isinstance(r["anomaly_flag"], bool)
                assert isinstance(r["anomaly_score"], float)

    _test("anomaly_detection", t_anomaly_detection)

    #
    # Test 8 — anomaly detection flags outliers

    #
    def t_anomaly_flags_outliers() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(1000)
            data_dir = _save_dataset(df, tmpdir)

            train_global_model(data_dir)
            train_driver_model("DriverA", data_dir)

            # Create extreme outlier laps

            driver_data = df[df[COL_DRIVER_NAME] == "DriverA"].head(5).copy()
            for col in _available_features(driver_data):
                driver_data[col] = driver_data[col] * 100

            results = detect_driver_anomalies("DriverA", driver_data, data_dir)
            flagged = [r for r in results if r["anomaly_flag"]]
            # At least some should be flagged as anomalies

            assert len(flagged) > 0

    _test("anomaly_flags_outliers", t_anomaly_flags_outliers)

    #
    # Test 9 — deviation computation

    #
    def t_deviation_computation() -> None:
        rng = np.random.default_rng(42)
        cols = ["a", "b", "c"]
        df = pd.DataFrame({
            "a": [1.0, 10.0, 1.0],
            "b": [1.0, 10.0, 1.0],
            "c": [1.0, 10.0, 1.0],
        })
        ref = np.array([1.0, 1.0, 1.0])

        dev = compute_deviation_from_global_optimal(df, ref, cols)

        assert len(dev) == 3
        # Row 0 and row 2 are at the reference → deviation = 0

        assert dev[0] == 0.0
        assert dev[2] == 0.0
        # Row 1 is far from reference → deviation = 1.0 (max normalised)

        np.testing.assert_allclose(dev[1], 1.0, atol=1e-10)

    _test("deviation_computation", t_deviation_computation)

    #
    # Test 10 — deviation with scaler

    #
    def t_deviation_with_scaler() -> None:
        cols = ["a", "b"]
        df = pd.DataFrame({"a": [0.0, 5.0, 10.0], "b": [0.0, 5.0, 10.0]})
        ref = np.array([0.0, 0.0])

        scaler = StandardScaler()
        scaler.fit(df[cols])

        dev = compute_deviation_from_global_optimal(df, ref, cols, scaler=scaler)
        assert len(dev) == 3
        assert dev[0] < dev[2]  # closer points have lower deviation

    _test("deviation_with_scaler", t_deviation_with_scaler)

    #
    # Test 11 — should_retrain (growth trigger)

    #
    def t_should_retrain_growth() -> None:
        meta = {"training_samples": 1000, "mae": 0.5}

        # 10% growth threshold (default)

        assert should_retrain(meta, 1100) is True
        assert should_retrain(meta, 1050) is False
        assert should_retrain(meta, 1099) is False
        assert should_retrain(meta, 1101) is True

    _test("should_retrain_growth", t_should_retrain_growth)

    #
    # Test 12 — should_retrain (MAE degradation)

    #
    def t_should_retrain_mae() -> None:
        meta = {"training_samples": 1000, "mae": 2.0}

        # MAE above threshold triggers retrain even without data growth

        assert should_retrain(meta, 500, mae_degradation_threshold=1.0) is True
        # MAE below threshold, no growth → no retrain

        meta2 = {"training_samples": 1000, "mae": 0.5}
        assert should_retrain(meta2, 500, mae_degradation_threshold=1.0) is False

    _test("should_retrain_mae", t_should_retrain_mae)

    #
    # Test 13 — ModelNotFoundError on prediction without training

    #
    def t_predict_without_model() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                predict_lap_time(pd.DataFrame({"speed_mean_mps": [42.0]}), tmpdir)
                raise AssertionError("Expected ModelNotFoundError")
            except ModelNotFoundError:
                pass

    _test("predict_without_model", t_predict_without_model)

    #
    # Test 14 — InsufficientDataError for driver with few samples

    #
    def t_driver_insufficient_data() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(30)
            # Force one driver to have very few rows

            df[COL_DRIVER_NAME] = "RareDriver"
            df.iloc[:5, df.columns.get_loc(COL_DRIVER_NAME)] = "TargetDriver"
            data_dir = _save_dataset(df, tmpdir)

            try:
                train_driver_model("TargetDriver", data_dir)
                raise AssertionError("Expected InsufficientDataError")
            except InsufficientDataError:
                pass

    _test("driver_insufficient_data", t_driver_insufficient_data)

    #
    # Test 15 — deterministic training

    #
    def t_deterministic_training() -> None:
        with tempfile.TemporaryDirectory() as tmpdir1, \
             tempfile.TemporaryDirectory() as tmpdir2:
            df = _make_dataset(500, seed=123)

            data1 = _save_dataset(df, tmpdir1)
            data2 = _save_dataset(df, tmpdir2)

            meta1 = train_global_model(data1)
            meta2 = train_global_model(data2)

            assert meta1["mae"] == meta2["mae"]
            assert meta1["training_samples"] == meta2["training_samples"]
            assert meta1["feature_importance"] == meta2["feature_importance"]

    _test("deterministic_training", t_deterministic_training)

    #
    # Test 16 — JSON serialisability of all metadata

    #
    def t_metadata_json_serialisable() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(500)
            data_dir = _save_dataset(df, tmpdir)

            meta_g = train_global_model(data_dir)
            json.dumps(meta_g)  # should not raise

            meta_d = train_driver_model("DriverA", data_dir)
            json.dumps(meta_d)  # should not raise

    _test("metadata_json_serialisable", t_metadata_json_serialisable)

    #
    # Test 17 — anomaly detection without global model

    #
    def t_anomaly_no_global() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(500)
            data_dir = _save_dataset(df, tmpdir)

            train_driver_model("DriverA", data_dir)
            driver_data = df[df[COL_DRIVER_NAME] == "DriverA"].head(10)
            results = detect_driver_anomalies("DriverA", driver_data, data_dir)
            assert len(results) == 10

    _test("anomaly_no_global", t_anomaly_no_global)

    #
    # Test 18 — deviation with missing columns

    #
    def t_deviation_missing_cols() -> None:
        df = pd.DataFrame({"a": [1.0, 2.0]})
        ref = np.array([1.0, 1.0, 1.0])
        cols = ["a", "b", "c"]

        dev = compute_deviation_from_global_optimal(df, ref, cols)
        assert len(dev) == 2
        assert all(np.isfinite(dev))

    _test("deviation_missing_cols", t_deviation_missing_cols)

    #
    # Test 19 — empty feature columns raises DatasetError

    #
    def t_empty_features_raises() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = pd.DataFrame({
                COL_TRACK_ID: ["spa"], COL_LAP_TIME: [90.0],
                "irrelevant_col": [42],
            })
            data_dir = _save_dataset(df, tmpdir)
            try:
                train_global_model(data_dir)
                raise AssertionError("Expected DatasetError")
            except DatasetError:
                pass

    _test("empty_features_raises", t_empty_features_raises)

    #
    # Test 20 — full end-to-end pipeline

    #
    def t_end_to_end() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = _make_dataset(1000)
            data_dir = _save_dataset(df, tmpdir)

            # 1. Train global

            g_meta = train_global_model(data_dir)
            assert g_meta["mae"] > 0

            # 2. Predict

            preds = predict_lap_time(df.head(5), data_dir)
            assert len(preds) == 5

            # 3. Feature importance

            imp = get_feature_importance(data_dir)
            assert len(imp) > 0

            # 4. Train driver

            d_meta = train_driver_model("DriverB", data_dir)
            assert d_meta["driver_name"] == "DriverB"

            # 5. Detect anomalies

            driver_b = df[df[COL_DRIVER_NAME] == "DriverB"].head(15)
            anom = detect_driver_anomalies("DriverB", driver_b, data_dir)
            assert len(anom) == 15

            # 6. Check drift

            retrain = should_retrain(g_meta, 1500)
            assert retrain is True

    _test("end_to_end", t_end_to_end)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    summary = f"\nML Engine Tests: {len(passed)}/{total} passed [{status}]"
    summary += f"  (pyarrow={'yes' if _HAS_PYARROW else 'no/CSV-fallback'})"
    print(summary)
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