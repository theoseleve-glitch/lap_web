"""Phase 1 grip anchor — tier vocabulary and the pure decision function.

The anchor answers "you used X% of the available grip here" and ALWAYS says
what "available" was measured against. Fail-safe: any doubt degrades toward
the lower tier; an unknown signal never yields a physics tier.
"""
import numpy as np
import pytest


def test_tier_vocabulary_is_closed():
    import grip_anchor as ga

    assert ga.TIERS == frozenset({
        ga.TIER_PHYSICS_ELLIPSE_FITTED,
        ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
        ga.TIER_DRIVER_BEST_SESSION,
        ga.TIER_REFUSED,
    })
    # Cross-session tier must NOT exist yet — corner identity is not stable
    # across sessions, so a driver_best_track value would be a promise we
    # cannot keep. Phase 2 adds it as a NEW value, not a redefinition.
    assert not hasattr(ga, "TIER_DRIVER_BEST_TRACK")


def test_only_physics_tiers_are_quotable_as_physics():
    import grip_anchor as ga

    assert ga.is_quotable_as_physics(ga.TIER_PHYSICS_ELLIPSE_FITTED) is True
    assert ga.is_quotable_as_physics(ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2) is True
    assert ga.is_quotable_as_physics(ga.TIER_DRIVER_BEST_SESSION) is False
    assert ga.is_quotable_as_physics(ga.TIER_REFUSED) is False
    assert ga.is_quotable_as_physics(None) is False
    assert ga.is_quotable_as_physics("something_invented") is False


def test_reserved_reasons_exist_for_phase_2_prerequisites():
    """Reserving these now forces Phase 2 to handle them deliberately."""
    import grip_anchor as ga

    assert ga.REASON_CONDITION_UNKNOWN == "condition_unknown"
    assert ga.REASON_CORNER_IDENTITY_UNSTABLE == "corner_identity_unstable"


def test_channel_trust_ratio_is_one_for_a_perfectly_consistent_channel():
    """If a_lat exactly equals v^2 * kappa, the ratio must be 1.0."""
    import grip_anchor as ga

    v = np.full(200, 20.0)
    kappa = np.full(200, 0.02)          # v^2*kappa = 8.0 m/s^2, well above the gate
    a_lat = v ** 2 * kappa

    assert ga.channel_trust_ratio(a_lat, v, kappa) == pytest.approx(1.0)


def test_channel_trust_ratio_detects_a_systematically_low_channel():
    import grip_anchor as ga

    v = np.full(200, 20.0)
    kappa = np.full(200, 0.02)
    a_lat = 0.85 * v ** 2 * kappa       # reads 15% low

    assert ga.channel_trust_ratio(a_lat, v, kappa) == pytest.approx(0.85)


def test_channel_trust_ratio_ignores_near_straight_samples():
    """Straights are v^2*kappa ~ 0, so the ratio there is noise over noise.
    Averaging them in is exactly what makes the persisted sensor_quality
    signal read 0.531 instead of ~0.96."""
    import grip_anchor as ga

    v = np.full(400, 20.0)
    kappa = np.concatenate([np.full(200, 0.02), np.full(200, 1e-5)])
    a_lat = np.concatenate([
        v[:200] ** 2 * kappa[:200],          # honest cornering samples
        np.full(200, 5.0),                    # garbage on the straight
    ])

    # Only the cornering half is admitted, so the garbage cannot move it.
    assert ga.channel_trust_ratio(a_lat, v, kappa) == pytest.approx(1.0)


def test_channel_trust_ratio_returns_none_when_too_few_samples():
    import grip_anchor as ga

    v = np.full(5, 20.0)
    kappa = np.full(5, 0.02)
    assert ga.channel_trust_ratio(v ** 2 * kappa, v, kappa) is None


def test_channel_trust_ratio_returns_none_on_all_nan():
    import grip_anchor as ga

    n = 200
    v = np.full(n, 20.0)
    kappa = np.full(n, 0.02)
    assert ga.channel_trust_ratio(np.full(n, np.nan), v, kappa) is None


def test_channel_trust_ratio_median_rejects_outliers():
    """Median is chosen for robustness to outliers among cornering samples.
    100 honest samples at ratio 1.0 plus 10 extreme outliers at 50.0 must yield
    ~1.0 (median), not ~5.5 (mean). This protects against transient sensor spikes.
    """
    import grip_anchor as ga

    v = np.full(110, 20.0)
    kappa = np.full(110, 0.02)  # All above the min_geo_accel gate
    a_geo = v ** 2 * kappa

    # 100 honest samples, 10 extreme outliers
    a_lat = np.concatenate([
        np.full(100, a_geo[0]),       # ratio = 1.0
        np.full(10, 50.0 * a_geo[0]), # ratio = 50.0 (outliers)
    ])

    # Median must reject outliers and return ~1.0
    result = ga.channel_trust_ratio(a_lat, v, kappa)
    assert result == pytest.approx(1.0, abs=0.01)


def test_channel_is_trusted_comprehensive():
    """The fail-safe guard: None (not measurable) is NOT trusted.
    Guards against regressing to `None -> True` which would bypass later logic.
    """
    import grip_anchor as ga

    # None is the fail-safe: refusal to measure is not a pass
    assert ga.channel_is_trusted(None) is False

    # NaN is also a refusal
    assert ga.channel_is_trusted(float("nan")) is False

    # Real-data value (0.961 from kart data) is trusted
    assert ga.channel_is_trusted(0.96) is True

    # Near-straight-contaminated value (0.531 from sensor_quality) is not trusted
    assert ga.channel_is_trusted(0.531) is False

    # Band edges are inclusive
    assert ga.channel_is_trusted(0.80) is True
    assert ga.channel_is_trusted(1.25) is True

    # Just outside the band is not trusted
    assert ga.channel_is_trusted(0.799) is False
    assert ga.channel_is_trusted(1.251) is False

    # Typical good ranges
    assert ga.channel_is_trusted(0.90) is True
    assert ga.channel_is_trusted(1.10) is True
    assert ga.channel_is_trusted(1.20) is True
