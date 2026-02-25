"""
session_scalars.py
------------------
Infer per-session condition scalars (μ, P, B) by comparing the
observed acceleration cloud to a trained capability envelope.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig, default_config
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_ACCEL_LONG, COL_SPEED

logger = logging.getLogger(__name__)


@dataclass
class SessionScalars:
    """Per-session condition estimates."""

    mu_session: float = 1.0     # grip scale (lateral + partial traction)
    p_session: float = 1.0      # power / drive scale
    b_session: float = 1.0      # brake scale
    confidence: float = 0.0     # 0-1 quality metric
    condition_label: str = "nominal"


class InferenceError(ValueError):
    """Raised when scalar inference fails."""


def infer_session_scalars(
    resampled_laps: dict[int, pd.DataFrame],
    envelope: CapabilityEnvelope,
    config: KartEnvelopeConfig | None = None,
) -> SessionScalars:
    """Estimate session-specific scalars from observed vs envelope limits.

    Algorithm
    ---------
    1. Pool (v, ax, ay) from all laps in this session.
    2. Trim bottom ``scalar_outlier_percentile`` of each bin to remove
       traffic / lift-off points.
    3. Per speed-bin: compute observed quantiles.
    4. Compute ratios: ``mu = median(ay_obs / envelope.ay_max)``, etc.
    5. Regularise toward 1.0, clip to bounds.
    6. Compute confidence from populated bins and consistency.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
    envelope : CapabilityEnvelope
    config : KartEnvelopeConfig | None

    Returns
    -------
    SessionScalars
    """
    if config is None:
        config = default_config()

    # --- Pool samples ---
    frames = []
    for lap_df in resampled_laps.values():
        cols = [c for c in (COL_SPEED, COL_ACCEL_LONG, COL_ACCEL_LAT)
                if c in lap_df.columns]
        if COL_SPEED in cols:
            frames.append(lap_df[cols])

    if not frames:
        logger.warning("No data for scalar inference; returning defaults.")
        return SessionScalars()

    pool = pd.concat(frames, ignore_index=True).dropna(subset=[COL_SPEED])
    v = pool[COL_SPEED].values
    ax = pool[COL_ACCEL_LONG].values if COL_ACCEL_LONG in pool.columns else np.zeros_like(v)
    ay = pool[COL_ACCEL_LAT].values if COL_ACCEL_LAT in pool.columns else np.zeros_like(v)

    valid = np.isfinite(v) & np.isfinite(ax) & np.isfinite(ay) & (v > 0.5)
    v, ax, ay = v[valid], ax[valid], ay[valid]

    if len(v) < 50:
        logger.warning("Only %d samples; returning default scalars.", len(v))
        return SessionScalars()

    # --- Speed bins (same grid as envelope) ---
    v_grid = envelope.v_grid
    n_bins = len(v_grid)
    bin_width = (v_grid[-1] - v_grid[0]) / max(n_bins - 1, 1) * 0.6

    q_lat = config.scalar_obs_quantile_lat
    q_trac = config.scalar_obs_quantile_trac
    q_brake = config.scalar_obs_quantile_brake
    min_samp = max(5, config.envelope_min_samples_per_bin)

    mu_ratios = []
    p_ratios = []
    b_ratios = []

    for i, vc in enumerate(v_grid):
        in_bin = np.abs(v - vc) <= bin_width
        if in_bin.sum() < min_samp:
            continue

        # Lateral
        ay_bin = np.abs(ay[in_bin])
        ay_bin = ay_bin[np.isfinite(ay_bin)]
        env_lat = float(envelope.lateral_max(vc))
        if len(ay_bin) >= min_samp and env_lat > 0:
            obs_lat = float(np.percentile(ay_bin, q_lat * 100))
            mu_ratios.append(obs_lat / env_lat)

        # Traction
        ax_pos = ax[in_bin]
        ax_pos = ax_pos[ax_pos > 0.1]
        env_trac = float(envelope.traction_max(vc))
        if len(ax_pos) >= min_samp and env_trac > 0:
            obs_trac = float(np.percentile(ax_pos, q_trac * 100))
            p_ratios.append(obs_trac / env_trac)

        # Braking
        ax_neg = ax[in_bin]
        ax_neg = np.abs(ax_neg[ax_neg < -0.1])
        env_brake = float(envelope.braking_max(vc))
        if len(ax_neg) >= min_samp and env_brake > 0:
            obs_brake = float(np.percentile(ax_neg, q_brake * 100))
            b_ratios.append(obs_brake / env_brake)

    # --- Compute scalars ---
    lam = config.scalar_regularisation

    mu_raw = float(np.median(mu_ratios)) if mu_ratios else 1.0
    p_raw = float(np.median(p_ratios)) if p_ratios else 1.0
    b_raw = float(np.median(b_ratios)) if b_ratios else 1.0

    # Regularise toward 1.0
    mu_reg = (1.0 - lam) * mu_raw + lam * 1.0
    p_reg = (1.0 - lam) * p_raw + lam * 1.0
    b_reg = (1.0 - lam) * b_raw + lam * 1.0

    # Clip to bounds
    mu_final = float(np.clip(mu_reg, config.scalar_mu_lo, config.scalar_mu_hi))
    p_final = float(np.clip(p_reg, config.scalar_p_lo, config.scalar_p_hi))
    b_final = float(np.clip(b_reg, config.scalar_b_lo, config.scalar_b_hi))

    # --- Confidence ---
    total_bins = n_bins
    populated = len(mu_ratios) + len(p_ratios) + len(b_ratios)
    max_populated = 3 * total_bins
    fill_ratio = populated / max_populated if max_populated > 0 else 0.0

    # Consistency: lower std of ratios → higher confidence
    all_ratios = mu_ratios + p_ratios + b_ratios
    if len(all_ratios) > 2:
        ratio_std = float(np.std(all_ratios))
        consistency = max(0.0, 1.0 - ratio_std)
    else:
        consistency = 0.3

    confidence = float(np.clip(0.5 * fill_ratio + 0.5 * consistency, 0.0, 1.0))

    scalars = SessionScalars(
        mu_session=mu_final,
        p_session=p_final,
        b_session=b_final,
        confidence=confidence,
    )

    logger.info(
        "Session scalars: μ=%.3f, P=%.3f, B=%.3f (confidence=%.2f, "
        "bins: lat=%d, trac=%d, brake=%d).",
        mu_final, p_final, b_final, confidence,
        len(mu_ratios), len(p_ratios), len(b_ratios),
    )
    return scalars
