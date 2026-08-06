"""``throttle_onset_delay_m`` must never be fabricated from an absolute position.

THE DEFECT THIS GUARDS (live in production until 2026-08-06).

``extract_style_features`` fell back to ``throttle_onset_m`` from the per-lap
corner metrics. That field is an ABSOLUTE distance along the lap (hundreds of
metres); the feature it fed is "distance after the apex before meaningful
throttle", normalised over 0-15 m. ``_normalise_01(hundreds, 0.0, 15.0)``
clamps to exactly 1.0, so the feature was the constant 1.0 for every driver.

That constant was not neutral. 1.0 falls inside "Smooth Precision"'s expected
0.4-1.0 band and outside "Aggressive Attack"'s 0.0-0.3, so every driver was
nudged toward the patient-on-exit profiles.

The honest value is NaN -- the dataclass default meaning "not measured",
which ``score_style`` skips. These tests assert the feature is either a
genuine measurement or absent, and NEVER a value derived from a lap position.
"""
import math

import numpy as np
import pandas as pd
import pytest

import driving_style


def _metrics_with_onsets(onsets: list[float]) -> list[dict]:
    """Per-lap corner metrics carrying absolute-position onsets, as the
    pipeline really emits them (``d_min + onset_norm * span``)."""
    return [
        {"corner_id": i + 1, "lap_number": 1, "throttle_onset_m": o}
        for i, o in enumerate(onsets)
    ]


def _resampled_laps() -> dict:
    """Two real laps.

    NOT optional, and not incidental: ``extract_style_features`` opens with
    ``if not resampled_laps: return features``, so passing ``{}`` returns an
    all-NaN dataclass without executing ANY feature code. An earlier draft of
    this file did exactly that -- every "must be NaN" assertion passed against
    the early return and would have passed just as well with the bug still in
    place. The bite-check at the bottom of this module exists to keep that
    from happening again.
    """
    dist = np.linspace(0.0, 400.0, 400)
    frac = dist / 400.0
    speed = 30.0 - 15.0 * np.exp(-((frac - 0.5) ** 2) / (2 * 0.08 ** 2))
    return {
        n: pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed + n * 0.1,
            "speed_mps": speed + n * 0.1,
        })
        for n in (1, 2)
    }


def _extract(per_lap_corner_metrics, corner_performances=None):
    return driving_style.extract_style_features(
        resampled_laps=_resampled_laps(),
        lap_metrics=None,
        corner_performances=corner_performances,
        per_lap_corner_metrics=per_lap_corner_metrics,
    )


def test_the_onset_block_is_actually_reached():
    """Pins the premise: this fixture must EXECUTE the onset code.

    ``extract_style_features`` early-returns on empty ``resampled_laps``, and
    an all-NaN dataclass from an early return is indistinguishable from an
    all-NaN dataclass produced by a correct refusal. The discriminator is a
    genuine delay: it can only come back finite if the block ran.
    """
    features = _extract(None, corner_performances=[
        {"corner_id": 1, "throttle_onset_delay_m": 7.5},
    ])
    assert math.isfinite(features.throttle_onset_delay_m), (
        "the onset block did not execute on this fixture -- every NaN "
        "assertion below would then pass vacuously"
    )


def test_absolute_onsets_do_not_produce_a_value():
    """Real production magnitudes: corners at 200 m, 450 m, 900 m."""
    features = _extract(_metrics_with_onsets([200.0, 450.0, 900.0]))
    assert math.isnan(features.throttle_onset_delay_m), (
        f"expected NaN (not measured), got "
        f"{features.throttle_onset_delay_m!r} -- an absolute lap position was "
        "normalised over a 0-15 m range and clamped"
    )


def test_it_is_not_the_saturated_constant():
    """The specific wrong answer the bug produced, named explicitly."""
    features = _extract(_metrics_with_onsets([200.0, 450.0, 900.0]))
    assert features.throttle_onset_delay_m != 1.0


def test_two_very_different_drivers_are_not_given_the_same_value():
    """The clearest statement of the harm: the feature could not discriminate.

    One driver's onsets sit early in the lap, the other's late. Under the bug
    both normalised to exactly 1.0, so the feature carried no information
    about either while still voting in the style classification.
    """
    early = _extract(_metrics_with_onsets([60.0, 80.0, 120.0]))
    late = _extract(_metrics_with_onsets([700.0, 900.0, 1100.0]))
    a, b = early.throttle_onset_delay_m, late.throttle_onset_delay_m
    assert not (a == b == 1.0), (
        "both drivers saturated to 1.0 -- the feature is a constant, not a "
        "measurement"
    )
    assert math.isnan(a) and math.isnan(b)


def test_a_real_delay_on_a_corner_performance_is_still_used():
    """The fix must not disable the feature where a genuine delay exists.

    ``throttle_onset_delay_m`` on a corner performance IS an apex-relative
    delay in metres, so it must still flow through and normalise sensibly.
    """
    perfs = [
        {"corner_id": 1, "throttle_onset_delay_m": 6.0},
        {"corner_id": 2, "throttle_onset_delay_m": 9.0},
    ]
    features = _extract(None, corner_performances=perfs)
    value = features.throttle_onset_delay_m
    assert math.isfinite(value), "a genuine delay must still be measured"
    # mean 7.5 m over the documented 0-15 m range
    assert value == pytest.approx(0.5, abs=1e-9)


def test_a_genuine_delay_is_not_clamped():
    """Distinguishes 'the feature works' from 'the feature saturates'."""
    small = _extract(None, [{"corner_id": 1, "throttle_onset_delay_m": 1.5}])
    large = _extract(None, [{"corner_id": 1, "throttle_onset_delay_m": 12.0}])
    assert small.throttle_onset_delay_m < large.throttle_onset_delay_m
    assert small.throttle_onset_delay_m == pytest.approx(0.1)
    assert large.throttle_onset_delay_m == pytest.approx(0.8)


def test_nan_is_skipped_by_the_style_classifier():
    """A refusal must cost a signal, not corrupt the scoring.

    If NaN were scored rather than skipped, refusing would trade one wrong
    answer for another.
    """
    features = _extract(_metrics_with_onsets([200.0, 450.0]))
    assert math.isnan(features.throttle_onset_delay_m)
    # Must not raise, and must still return a usable classification.
    result = driving_style.classify_style(features)
    assert result is not None
