"""Tests for track-record calibration."""
from __future__ import annotations

import numpy as np
import pytest

from kart_envelope.config import default_config
from kart_envelope.solver.min_time import compute_theoretical_lap
from kart_envelope.solver.record_cal import CalibrationError, calibrate_to_record


class TestRecordCalibration:
    def test_calibration_converges(self, known_envelope, small_oval_geometry):
        """Calibration should get close to the target record time."""
        cfg = default_config()
        # First compute a baseline
        baseline = compute_theoretical_lap(small_oval_geometry, known_envelope, config=cfg)
        # Use a record time 5% faster than baseline
        record_time = baseline.lap_time_s * 0.95

        cal = calibrate_to_record(
            small_oval_geometry, known_envelope, record_time, cfg,
            data_theoretical_time_s=baseline.lap_time_s,
        )

        # Calibrated time should be close to record
        assert cal.residual_s < 0.5  # within 0.5 s
        # Alphas should be within bounds
        assert cfg.cal_alpha_lo <= cal.alpha_lat <= cfg.cal_alpha_hi
        assert cfg.cal_alpha_lo <= cal.alpha_drive <= cfg.cal_alpha_hi
        assert cfg.cal_alpha_lo <= cal.alpha_brake <= cfg.cal_alpha_hi

    def test_invalid_record_raises(self, known_envelope, small_oval_geometry):
        with pytest.raises(CalibrationError):
            calibrate_to_record(small_oval_geometry, known_envelope, -1.0)

    def test_serialisation(self, known_envelope, small_oval_geometry, tmp_path):
        cfg = default_config()
        baseline = compute_theoretical_lap(small_oval_geometry, known_envelope, config=cfg)
        record_time = baseline.lap_time_s * 0.98

        cal = calibrate_to_record(small_oval_geometry, known_envelope, record_time, cfg)
        path = tmp_path / "cal.json"
        cal.save(path)

        from kart_envelope.solver.record_cal import RecordCalibration
        loaded = RecordCalibration.load(path)
        assert loaded.alpha_lat == pytest.approx(cal.alpha_lat, abs=1e-3)
