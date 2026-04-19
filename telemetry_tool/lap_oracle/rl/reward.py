"""Reward shaping for the AC RL environment.

Simple reward function that encourages forward progress, speed, and
smooth driving.  Designed for dense-reward on-policy training.
"""
from __future__ import annotations

import numpy as np


def compute_reward(
    obs: np.ndarray,
    action: np.ndarray,
    prev_lap_dist: float,
) -> float:
    """Compute a scalar reward for one environment step.

    Parameters
    ----------
    obs : ndarray, shape (23,)
        Current observation vector.  Index 0 is speed (m/s), index 4
        is ``lap_dist_pct`` in [0, 1].
    action : ndarray, shape (3,)
        ``[steering, throttle, brake]`` in [-1,1], [0,1], [0,1].
    prev_lap_dist : float
        ``lap_dist_pct`` from the previous step, used to compute
        forward progress.

    Returns
    -------
    float
        Composite reward.
    """
    speed = float(obs[0]) if len(obs) > 0 else 0.0
    lap_dist_pct = float(obs[4]) if len(obs) > 4 else 0.0
    steering = float(action[0]) if len(action) > 0 else 0.0

    # 1. Progress reward: distance around the lap since last step
    delta = lap_dist_pct - prev_lap_dist
    # Handle lap boundary wrap-around (e.g. 0.99 -> 0.01)
    if delta < -0.5:
        delta += 1.0
    # Penalise going backward
    if delta < -0.1:
        delta = -0.1
    progress_reward = delta * 1000.0

    # 2. Speed reward: faster is better
    speed_reward = speed * 0.01

    # 3. Smoothness penalty: discourage jerky steering
    smoothness_penalty = -0.1 * abs(steering)

    return progress_reward + speed_reward + smoothness_penalty
