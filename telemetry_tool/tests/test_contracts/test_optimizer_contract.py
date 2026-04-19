import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    OptimizerContract,
    OptimizerDepth,
    CornerDelta,
    ReconstructedInputs,
    TrajectoryDelta,
)


def _minimal_optimizer(**overrides) -> OptimizerContract:
    base = {
        "depth": OptimizerDepth.TRAJECTORY_ONLY,
        "method": "trajectory",
        "theoretical_lap_time_s": 90.123,
        "confidence": 0.82,
        "corner_deltas": [],
        "total_time_loss_s": 0.0,
    }
    base.update(overrides)
    return OptimizerContract(**base)


def test_optimizer_minimal():
    o = _minimal_optimizer()
    assert o.depth is OptimizerDepth.TRAJECTORY_ONLY
    assert o.reconstructed_inputs is None


def test_optimizer_confidence_range():
    _minimal_optimizer(confidence=0.0)
    _minimal_optimizer(confidence=1.0)
    with pytest.raises(ValidationError):
        _minimal_optimizer(confidence=1.5)


def test_full_fidelity_requires_reconstructed_inputs():
    """If depth is FULL_FIDELITY, reconstructed_inputs must be provided."""
    with pytest.raises(ValidationError):
        _minimal_optimizer(depth=OptimizerDepth.FULL_FIDELITY, reconstructed_inputs=None)

    _minimal_optimizer(
        depth=OptimizerDepth.FULL_FIDELITY,
        method="qss_enhanced",
        reconstructed_inputs=ReconstructedInputs(
            throttle=[], brake=[], steer=[], distance_m=[]
        ),
    )


def test_corner_delta_fields():
    cd = CornerDelta(corner_id="3", time_loss_s=0.42, root_cause="late_brake_release",
                    coaching_text="Release the brake ~10m earlier")
    assert cd.time_loss_s == 0.42
