"""Tests for endurance analytics: traffic losses, risk/reward, team coaching."""

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.stint_analysis import (
    detect_traffic_losses,
    classify_risk_reward_passes,
    generate_team_coaching,
)


# ── detect_traffic_losses ────────────────────────────────────────────────


def test_no_traffic_clean_lap():
    """Smooth acceleration throughout => no losses detected."""
    n = 200
    df = pd.DataFrame({
        "Distance (m)": np.linspace(0, 1000, n),
        "Time (s)": np.linspace(0, 60, n),
        "accel_long (m/s2)": np.full(n, 0.3),  # gentle positive accel
    })
    ref_df = df.copy()
    corners = [{"entry_s": 200, "exit_s": 250}]
    losses = detect_traffic_losses(df, ref_df, corners)
    assert losses == []


def test_micro_lift_detected():
    """An artificial accel dip outside braking zones is detected as micro_lift."""
    n = 200
    accel = np.full(n, 0.3)
    # Insert a sharp dip at samples 100-105 (outside any braking zone)
    accel[100:103] = -0.8  # 3 samples ~ 0.9s at 60s/200 samples
    time_arr = np.linspace(0, 60, n)
    dist_arr = np.linspace(0, 1000, n)

    df = pd.DataFrame({
        "Distance (m)": dist_arr,
        "Time (s)": time_arr,
        "accel_long (m/s2)": accel,
    })
    ref_df = df.copy()
    # Braking zone far from the dip location
    corners = [{"entry_s": 10, "exit_s": 30}]

    losses = detect_traffic_losses(df, ref_df, corners)
    assert len(losses) >= 1
    assert losses[0]["type"] == "micro_lift"
    assert losses[0]["peak_decel"] < -0.5


# ── classify_risk_reward_passes ──────────────────────────────────────────


def test_empty_input_risk_reward():
    """Empty corner_performances list returns empty results."""
    results = classify_risk_reward_passes([], [], [])
    assert results == []


def test_high_variance_classified():
    """Corner with high std is classified as risky or rewarding."""
    perfs = [
        {"corner_id": 1, "time_loss_s": 0.05, "time_loss_std": 0.20},
    ]
    results = classify_risk_reward_passes(perfs, [], [])
    assert len(results) == 1
    assert results[0]["corner_id"] == 1
    assert results[0]["classification"] in ("risky", "rewarding")


# ── generate_team_coaching ───────────────────────────────────────────────


def test_single_stint_coaching():
    """Single stint generates at least one coaching objective."""
    metrics = [
        {
            "stint_id": 1,
            "mean_pace_s": 62.5,
            "consistency_cv": 0.03,
            "pace_fade_s": 0.1,
        }
    ]
    objectives = generate_team_coaching(metrics)
    assert len(objectives) >= 1
    assert objectives[0]["stint_id"] == 1
    assert objectives[0]["rank"] == 1


def test_multi_stint_weakest_identified():
    """The stint with worst (highest) mean_pace_s is tagged as weakest."""
    metrics = [
        {
            "stint_id": 1,
            "mean_pace_s": 61.0,
            "consistency_cv": 0.02,
            "pace_fade_s": 0.1,
        },
        {
            "stint_id": 2,
            "mean_pace_s": 63.5,
            "consistency_cv": 0.05,
            "pace_fade_s": 0.6,
        },
    ]
    objectives = generate_team_coaching(metrics)
    assert len(objectives) >= 1
    # Weakest stint (highest mean_pace_s) should be stint 2
    assert objectives[0]["stint_id"] == 2
