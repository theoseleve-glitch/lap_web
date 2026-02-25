"""
test_bug_fixes.py
-----------------
Unit tests covering all six bug fixes.  Uses stdlib ``unittest`` only.

FIX-1: Scoring consistency – wet-session thresholds  (score range 0–25)
FIX-2: Theoretical distance mismatch – median grid   (cols: distance_m, speed_mps)
FIX-3: Anomaly detection NaN warnings – feature cleaning
FIX-4: io_racechrono ParserWarning – ragged CSV       (header: "Time (s)")
FIX-5: Corner detection under-detection               (cols: yaw_rate_dps)
FIX-6: .spec hidden imports
"""

from __future__ import annotations

import inspect
import math
import os
import sys
import tempfile
import textwrap
import unittest
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

# -- -

# FIX-1  –  Scoring consistency (wet sessions)

#   _score_consistency returns score in [0, MAX_CONSISTENCY=25]

# -- -

from scoring import _ratio_score, _score_consistency, MAX_CONSISTENCY


class TestScoringConsistencyDry(unittest.TestCase):
    """FIX-1: Dry-session consistency scoring (0–25 scale)."""

    @staticmethod
    def _m(cv_pct: float, btm_s: float, n_laps: int = 10) -> dict[str, Any]:
        return {"cv_pct": cv_pct, "best_to_median_s": btm_s, "n_laps": n_laps}

    _th: dict[str, Any] = {}

    def test_stable_laps_high_score(self):
        score, _ = _score_consistency(self._m(0.3, 0.2), self._th, is_wet=False)
        self.assertGreaterEqual(score, 0.80 * MAX_CONSISTENCY)

    def test_moderate_variability_mid_score(self):
        score, _ = _score_consistency(self._m(1.5, 1.0), self._th, is_wet=False)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, MAX_CONSISTENCY)

    def test_high_variability_low_score(self):
        score, _ = _score_consistency(self._m(2.8, 3.5), self._th, is_wet=False)
        self.assertLessEqual(score, 0.20 * MAX_CONSISTENCY)

    def test_insufficient_laps_zero(self):
        score, dbg = _score_consistency(self._m(0.5, 0.1, n_laps=1), self._th)
        self.assertEqual(score, 0.0)
        self.assertIn("insufficient", str(dbg).lower())


class TestScoringConsistencyWet(unittest.TestCase):
    """FIX-1: Wet-session consistency should NOT collapse to 0."""

    @staticmethod
    def _m(cv_pct: float, btm_s: float, n_laps: int = 10) -> dict[str, Any]:
        return {"cv_pct": cv_pct, "best_to_median_s": btm_s, "n_laps": n_laps}

    _th: dict[str, Any] = {}

    def test_wet_high_variability_not_zero(self):
        """THE BUG: cv=4.0, btm=5.0 wet -> score was 0, should be > 0."""
        score, _ = _score_consistency(self._m(4.0, 5.0), self._th, is_wet=True)
        self.assertGreater(score, 0.0,
                           "Wet score collapsed to 0 (the original bug)")

    def test_wet_moderate_variability_reasonable(self):
        score, _ = _score_consistency(self._m(2.5, 2.5), self._th, is_wet=True)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, MAX_CONSISTENCY)

    def test_wet_more_lenient_than_dry(self):
        """Same variability -> wet score >= dry score."""
        cv, btm = 2.5, 3.0
        dry, _ = _score_consistency(self._m(cv, btm), self._th, is_wet=False)
        wet, _ = _score_consistency(self._m(cv, btm), self._th, is_wet=True)
        self.assertGreaterEqual(wet, dry,
                                f"Wet {wet:.3f} < dry {dry:.3f} for same variability")


class TestRatioScore(unittest.TestCase):
    def test_at_full_mark(self):
        self.assertAlmostEqual(_ratio_score(1.0, 1.0, 0.0), 1.0)

    def test_at_zero_mark(self):
        self.assertAlmostEqual(_ratio_score(0.0, 1.0, 0.0), 0.0)

    def test_below_zero_clamps(self):
        self.assertEqual(_ratio_score(-5.0, 1.0, 0.0), 0.0)

    def test_inverse_at_full(self):
        self.assertAlmostEqual(
            _ratio_score(0.5, full_mark=0.5, zero_mark=3.0, higher_is_better=False),
            1.0,
        )


# -- -

# FIX-2  –  Theoretical distance mismatch

#   Internal columns: distance_m, speed_mps

# -- -

from theoretical_engine import compute_speed_percentile_envelope


class TestTheoreticalDistance(unittest.TestCase):
    """FIX-2: Envelope distance should use median lap length, not min."""

    @staticmethod
    def _make_lap(length_m: float, n: int = 500) -> pd.DataFrame:
        d = np.linspace(0, length_m, n)
        s = 20.0 + 3.0 * np.sin(d / length_m * 4 * np.pi)
        return pd.DataFrame({"distance_m": d, "speed_mps": s})

    def test_grid_uses_median_not_min(self):
        laps = [self._make_lap(l) for l in (617, 741, 738, 740)]
        env = compute_speed_percentile_envelope(laps, percentile=98.0)
        total = env["distance_m"].iloc[-1] - env["distance_m"].iloc[0]
        self.assertGreater(total, 700.0,
                           f"Grid {total:.0f}m still truncated to 617m min")

    def test_uniform_laps_within_2pct(self):
        target = 741.0
        laps = [self._make_lap(target) for _ in range(5)]
        env = compute_speed_percentile_envelope(laps, percentile=98.0)
        total = env["distance_m"].iloc[-1] - env["distance_m"].iloc[0]
        dev = abs(total - target) / target
        self.assertLess(dev, 0.02,
                        f"Grid {total:.1f}m deviates {dev*100:.1f}% from {target}m")


# -- -

# FIX-3  –  Anomaly detection NaN / constant column handling

# -- -

from anomaly_detection import _clean_features


class TestCleanFeatures(unittest.TestCase):
    """FIX-3: _clean_features drops NaN/constant cols without warnings."""

    def test_all_nan_column_dropped(self):
        df = pd.DataFrame({"a": [1, 2, 3.0], "b": [np.nan]*3, "c": [4, 5, 6.0]})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            cleaned, nan_cols, _, _ = _clean_features(df)
        self.assertIn("b", nan_cols)
        self.assertNotIn("b", cleaned.columns)

    def test_constant_column_dropped(self):
        df = pd.DataFrame({"a": [1, 2, 3.0], "b": [5.0]*3, "c": [4, 5, 6.0]})
        cleaned, _, const_cols, _ = _clean_features(df)
        self.assertIn("b", const_cols)
        self.assertNotIn("b", cleaned.columns)

    def test_sparse_nan_imputed(self):
        df = pd.DataFrame({
            "a": [1.0, np.nan, 3.0, 4.0],
            "b": [10.0, 20.0, 30.0, 40.0],
            "c": [2.0, 4.0, np.nan, 8.0],
        })
        cleaned, _, _, n_imp = _clean_features(df)
        self.assertFalse(cleaned.isna().any().any())
        self.assertEqual(n_imp, 2)

    def test_no_runtime_warnings(self):
        """Mixed all-NaN + constant + good columns -> zero warnings."""
        rng = np.random.RandomState(42)
        df = pd.DataFrame({
            "ok1": rng.randn(20), "ok2": rng.randn(20), "ok3": rng.randn(20),
            "all_nan": [np.nan]*20, "const": [7.0]*20,
        })
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            cleaned, _, _, _ = _clean_features(df)
        self.assertEqual(set(cleaned.columns), {"ok1", "ok2", "ok3"})

    def test_empty_after_cleaning(self):
        df = pd.DataFrame({"a": [np.nan]*2, "b": [5.0]*2})
        cleaned, _, _, _ = _clean_features(df)
        self.assertEqual(len(cleaned.columns), 0)


# -- -

# FIX-4  –  io_racechrono ParserWarning on ragged CSV

#   Header sentinel: "Time (s)"

# -- -

from io_racechrono import read_racechrono_csv


class TestRacechronoRaggedCSV(unittest.TestCase):
    """FIX-4: Ragged CSV rows silently skipped, no ParserWarning."""

    def test_ragged_row_no_warning(self):
        csv = textwrap.dedent("""\
            # RaceChrono Pro export

            # Columns defined below

            Time (s),Latitude,Longitude,Speed (m/s),Distance (m)
            0.00,51.500,-0.100,10.0,0.0
            0.10,51.501,-0.101,10.1,1.0
            0.20,51.502,-0.102,10.2,2.0,extra_field
            0.30,51.503,-0.103,10.3,3.0
        """)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(csv)
            path = f.name
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                df = read_racechrono_csv(path)
            self.assertGreaterEqual(len(df), 3)
        finally:
            os.unlink(path)

    def test_clean_csv_all_rows(self):
        csv = textwrap.dedent("""\
            # RaceChrono Pro export

            # Columns defined below

            Time (s),Latitude,Longitude,Speed (m/s),Distance (m)
            0.00,51.500,-0.100,10.0,0.0
            0.10,51.501,-0.101,10.1,1.0
            0.20,51.502,-0.102,10.2,2.0
        """)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(csv)
            path = f.name
        try:
            df = read_racechrono_csv(path)
            self.assertEqual(len(df), 3)
        finally:
            os.unlink(path)


# -- -

# FIX-5  –  Corner detection under-detection

#   Needs: "Distance (m)", "Speed (m/s)", "yaw_rate_dps"

#   We synthesise yaw_rate from curvature: yaw_rate = curvature * speed * (180/pi)

# -- -

from corner_detection import detect_corners


class TestCornerDetection(unittest.TestCase):
    """FIX-5: Short tracks detect more corners with adaptive defaults."""

    @staticmethod
    def _curvy_lap(length_m: float = 741.0, n: int = 1000,
                   n_corners: int = 8) -> pd.DataFrame:
        d = np.linspace(0, length_m, n)
        curv = np.zeros(n)
        spacing = length_m / (n_corners + 1)
        for i in range(1, n_corners + 1):
            curv += 0.04 * np.exp(-0.5 * ((d - i * spacing) / 8.0) ** 2)
        curv += 0.001 * np.abs(np.random.RandomState(42).randn(n))
        speed = 20.0 - 5.0 * (curv / max(curv.max(), 1e-9))
        # Convert curvature to yaw_rate_dps: yaw_rate = curvature * speed * 180/pi

        yaw_rate = curv * speed * (180.0 / np.pi)
        lat = np.linspace(51.50, 51.507, n)
        lon = np.linspace(-0.10, -0.093, n)
        return pd.DataFrame({
            "Distance (m)": d,
            "Speed (m/s)": speed,
            "yaw_rate_dps": yaw_rate,
            "Latitude": lat,
            "Longitude": lon,
        })

    def test_short_track_detects_multiple_corners(self):
        corners = detect_corners(self._curvy_lap(741.0, n_corners=8))
        self.assertGreaterEqual(len(corners), 4,
                                f"Only {len(corners)} corners on 741m track (expect >=4)")

    def test_adaptive_default_is_none(self):
        sig = inspect.signature(detect_corners)
        default = sig.parameters["curvature_threshold"].default
        self.assertIsNone(default,
                          f"curvature_threshold default should be None, got {default}")

    def test_long_track_still_works(self):
        corners = detect_corners(self._curvy_lap(3000.0, n=3000, n_corners=12))
        self.assertGreaterEqual(len(corners), 6,
                                f"Only {len(corners)} corners on 3 km track")


# -- -

# FIX-6  –  .spec hidden imports

# -- -



class TestSpecHiddenImports(unittest.TestCase):
    """FIX-6: telemetry_tool.spec includes new module hidden imports."""

    def setUp(self):
        spec_path = Path(__file__).resolve().parent.parent / "telemetry_tool.spec"
        self.spec_text = spec_path.read_text(encoding="utf-8")

    def test_session_context_in_spec(self):
        self.assertIn("'session_context'", self.spec_text)

    def test_condition_tracking_in_spec(self):
        self.assertIn("'condition_tracking'", self.spec_text)

    def test_debrief_engine_in_spec(self):
        self.assertIn("'debrief_engine'", self.spec_text)


# -- -

if __name__ == "__main__":
    unittest.main(verbosity=2)
