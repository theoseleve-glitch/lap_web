"""Tests for distance_integrity module."""
import numpy as np
import pandas as pd
import pytest


def test_perfect_monotonic_distance():
    """Perfectly monotonic distance → ratio=1.0, jump_count=0."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 1000)
    m = compute_lap_metrics(d, lap_number=1)
    assert m.monotonic_ratio == 1.0
    assert m.jump_count == 0
    assert m.lap_length == pytest.approx(500.0)


def test_non_monotonic_distance():
    """Backward jumps reduce monotonic_ratio and increase jump_count."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 100)
    d[30] = d[20]  # backward jump
    d[60] = d[50]  # another
    m = compute_lap_metrics(d, lap_number=1)
    assert m.monotonic_ratio < 1.0
    assert m.jump_count >= 2


def test_compression_ratio_uniform():
    """Uniform spacing → compression_ratio close to 0."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 1000)
    m = compute_lap_metrics(d, lap_number=1)
    assert m.compression_ratio < 0.01


def test_compression_ratio_irregular():
    """Irregular spacing → higher compression_ratio."""
    from distance_integrity import compute_lap_metrics

    d = np.array([0, 1, 2, 3, 100, 101, 102, 200, 201, 500])
    m = compute_lap_metrics(d, lap_number=1)
    assert m.compression_ratio > 0.5


def test_lap_length():
    """lap_length = max - min."""
    from distance_integrity import compute_lap_metrics

    d = np.array([10, 20, 30, 40, 50])
    m = compute_lap_metrics(d, lap_number=1)
    assert m.lap_length == pytest.approx(40.0)
