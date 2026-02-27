"""
cleaning.py
-----------
Wrapper combining GPS quality filtering and derived-channel computation
from ``telemetry_tool``, tuned for kart telemetry.

The input DataFrame uses **RaceChrono raw column names** (because the
upstream telemetry_tool functions expect them).  Callers should invoke
this *before* normalising to canonical names, or convert back temporarily.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.gps_filtering import filter_gps_quality  # noqa: E402
from telemetry_tool.derived_channels import (                  # noqa: E402
    compute_bank_angle_estimate,
    compute_combined_g,
    compute_distance,
    compute_elevation_profile,
    compute_longitudinal_accel,
    compute_lateral_accel_from_xy,
    compute_yaw_rate_from_heading,
)

from kart_envelope.config import KartEnvelopeConfig  # noqa: E402

logger = logging.getLogger(__name__)


class CleaningError(ValueError):
    """Raised when cleaning produces an unusable result."""


def clean_and_derive(
    df: pd.DataFrame,
    config: KartEnvelopeConfig,
) -> pd.DataFrame:
    """Filter GPS quality and compute derived channels.

    Parameters
    ----------
    df : pd.DataFrame
        Raw DataFrame with **RaceChrono column names** (output of
        ``read_racechrono_csv``).
    config : KartEnvelopeConfig
        Pipeline configuration.

    Returns
    -------
    pd.DataFrame
        Enriched copy with derived acceleration / yaw-rate columns.

    Raises
    ------
    CleaningError
        If all rows are filtered out.
    """
    out = df.copy()

    # --- 1. GPS quality gate ---
    try:
        out = filter_gps_quality(
            out,
            min_satellites=config.gps_min_satellites,
            max_accuracy_m=config.gps_max_accuracy_m,
            max_speed_mps=config.gps_max_speed_mps,
            max_accel_mps2=config.gps_max_accel_mps2,
        )
    except Exception as exc:
        logger.warning("GPS filter failed (%s); continuing unfiltered.", exc)

    if len(out) < 10:
        raise CleaningError("Fewer than 10 rows survive GPS filtering.")

    # --- 2. Synthesise Distance if absent ---
    if "Distance (m)" not in out.columns:
        try:
            out = compute_distance(out)
            logger.info("Synthesised Distance (m) from speed×dt.")
        except Exception as exc:
            logger.warning("compute_distance failed: %s", exc)

    # --- 3. Derived acceleration channels ---
    sw = config.smooth_window_samples
    for fn, label in [
        (lambda d: compute_longitudinal_accel(d, smoothing_window=sw),
         "longitudinal accel"),
        (lambda d: compute_lateral_accel_from_xy(d, smoothing_window=sw),
         "lateral accel"),
        (lambda d: compute_yaw_rate_from_heading(d, smoothing_window=sw),
         "yaw rate"),
    ]:
        try:
            out = fn(out)
        except Exception as exc:
            logger.debug("Derived channel '%s' unavailable: %s", label, exc)

    # --- 4. Additional channels used by lap optimization + diagnostics ---
    try:
        out = compute_combined_g(out)
    except Exception as exc:
        logger.debug("Derived channel 'combined_g' unavailable: %s", exc)

    try:
        out["grade_pct"] = compute_elevation_profile(
            out,
            smoothing_window=max(int(sw * 3), 9),
        )
    except Exception as exc:
        logger.debug("Derived channel 'grade_pct' unavailable: %s", exc)

    try:
        out["bank_angle_deg"] = compute_bank_angle_estimate(
            out,
            smoothing_window=max(int(sw), 3),
        )
    except Exception as exc:
        logger.debug("Derived channel 'bank_angle_deg' unavailable: %s", exc)

    logger.info("Cleaning complete: %d rows, derived channels added.", len(out))
    return out
