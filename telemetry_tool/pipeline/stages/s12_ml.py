"""
Stage 12 — ML Training + Anomaly Detection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Train global and per-driver ML models on the feature dataset,
then run anomaly detection to flag unusual laps.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_ml_training(feature_df: pd.DataFrame, meta: dict[str, Any]) -> dict[str, Any]:
    """Train ML models on the feature dataset.

    Parameters
    ----------
    feature_df : pd.DataFrame
        Feature dataset from stage 11.
    meta : dict
        Session metadata (must contain ``driver_name``).

    Returns
    -------
    dict
        Keys ``global_model``, ``driver_model`` (or ``*_error`` on failure),
        or ``skipped`` if insufficient data.
    """
    ml_mod = lazy_import("ml_engine")
    res: dict[str, Any] = {}

    if ml_mod is None or len(feature_df) < 10:
        res["skipped"] = "insufficient data or module absent"
        return res

    try:
        res["global_model"] = ml_mod.train_global_model(feature_df)
    except Exception as exc:
        res["global_model_error"] = str(exc)
        logger.debug("Global ML model training failed: %s", exc)

    try:
        driver = meta.get("driver_name", "Unknown")
        res["driver_model"] = ml_mod.train_driver_model(feature_df, driver)
    except Exception as exc:
        res["driver_model_error"] = str(exc)
        logger.debug("Driver ML model training failed: %s", exc)

    return res


def run_anomaly_detection(feature_df: pd.DataFrame) -> dict[str, Any]:
    """Run anomaly detection on the feature dataset.

    Parameters
    ----------
    feature_df : pd.DataFrame
        Feature dataset from stage 11.

    Returns
    -------
    dict
        Keys ``condition_keys``, ``detections``, ``n_anomalies``,
        or ``skipped`` if the module is absent.
    """
    ad_mod = lazy_import("anomaly_detection")
    if ad_mod is None:
        return {"skipped": "anomaly_detection absent"}

    model = ad_mod.train_anomaly_model(feature_df)
    detections = ad_mod.detect_anomalies(model, feature_df)

    result = {
        "condition_keys": list(model.condition_models.keys()),
        "detections": detections,
        "n_anomalies": sum(1 for d in detections if d.get("anomaly_flag")),
    }
    logger.info(
        "Anomaly detection: %d detections, %d anomalies",
        len(detections),
        result["n_anomalies"],
    )
    return result
