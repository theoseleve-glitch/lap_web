"""Tests for corner coaching labels with physics-aware text."""
import numpy as np
import pytest


def test_corner_performance_has_coaching_fields():
    """CornerPerformance has limiting_factor, corner_priority, coaching_text."""
    from corner_analysis import CornerPerformance

    cp = CornerPerformance(
        corner_id=1,
        s_start=100.0,
        s_end=200.0,
        limiting_factor="cornering",
        corner_priority="balanced",
        coaching_text="Grip-limited through corner 1.",
    )
    assert cp.limiting_factor == "cornering"
    assert cp.corner_priority == "balanced"
    d = cp.to_dict()
    assert "limiting_factor" in d
    assert "corner_priority" in d
    assert "coaching_text" in d


def test_compute_corner_coaching_labels_traction_exit():
    """Traction-limited corner with long straight -> exit priority."""
    from corner_analysis import compute_corner_coaching_labels

    corners = [
        {"corner_id": 1, "s_start": 100.0, "s_end": 200.0},
        {"corner_id": 2, "s_start": 400.0, "s_end": 450.0},
    ]
    limiting_factors = np.full(500, "cap", dtype=object)
    limiting_factors[100:200] = "traction"
    limiting_factors[400:450] = "cornering"

    distance_m = np.linspace(0, 500, 500)

    labels = compute_corner_coaching_labels(
        corners=corners,
        limiting_factors=limiting_factors,
        distance_m=distance_m,
        lap_length_m=500.0,
    )

    assert len(labels) == 2
    assert labels[0]["corner_id"] == 1
    assert labels[0]["limiting_factor"] == "traction"
    assert labels[0]["corner_priority"] == "exit"
    assert "traction" in labels[0]["coaching_text"].lower()

    assert labels[1]["corner_id"] == 2
    assert labels[1]["limiting_factor"] == "cornering"


def test_compute_corner_coaching_labels_braking_entry():
    """Braking-limited corner with long straight -> entry priority."""
    from corner_analysis import compute_corner_coaching_labels

    corners = [
        {"corner_id": 1, "s_start": 200.0, "s_end": 300.0},
    ]
    limiting_factors = np.full(600, "cap", dtype=object)
    limiting_factors[200:300] = "braking"

    distance_m = np.linspace(0, 600, 600)

    labels = compute_corner_coaching_labels(
        corners=corners,
        limiting_factors=limiting_factors,
        distance_m=distance_m,
        lap_length_m=600.0,
    )

    assert len(labels) == 1
    assert labels[0]["limiting_factor"] == "braking"
    assert labels[0]["corner_priority"] == "entry"
    assert "brak" in labels[0]["coaching_text"].lower()


def test_compute_corner_coaching_empty_corners():
    """Empty corners list -> empty labels."""
    from corner_analysis import compute_corner_coaching_labels

    labels = compute_corner_coaching_labels(
        corners=[],
        limiting_factors=np.array([], dtype=object),
        distance_m=np.array([]),
        lap_length_m=0.0,
    )
    assert labels == []
