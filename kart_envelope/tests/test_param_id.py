from __future__ import annotations

from dataclasses import replace

from kart_envelope.config import default_config
from kart_envelope.inference.calibration import build_calibration_report
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.metadata import SessionMetadata


def test_calibration_report_contains_constrained_param_id():
    cfg = replace(default_config(), calibration_enable_param_id=True)
    meta = SessionMetadata(session_file="s.csv", track_name="TEST", condition_label="dry")
    scalars = SessionScalars(mu_session=1.0, p_session=1.0, b_session=1.0, confidence=0.8, condition_label="dry")
    rep = build_calibration_report(
        metadata=meta,
        config=cfg,
        lap_times={1: 45.0, 2: 45.4, 3: 44.9},
        scalars=scalars,
        quality_metrics={"score": 0.75},
        sensitivity_result=None,
        bundle_v2_result=None,
    )
    pid = rep.get("parameter_identification", {})
    assert pid.get("enabled") is True
    assert "base_estimator" in pid
    assert "residual_learner" in pid
    conf = float(pid.get("confidence", 0.0))
    assert 0.0 <= conf <= 1.0

