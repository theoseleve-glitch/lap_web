"""Phase 1 grip anchor — tier vocabulary and the pure decision function.

The anchor answers "you used X% of the available grip here" and ALWAYS says
what "available" was measured against. Fail-safe: any doubt degrades toward
the lower tier; an unknown signal never yields a physics tier.
"""
import itertools
import math

import numpy as np
import pandas as pd
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


def test_friction_circle_reports_whether_its_exponent_was_fitted():
    """A fitted p that happens to land near 2.0 must be distinguishable from
    a silent fallback to the 2.0 hint — otherwise a 'fitted ellipse' tier is
    a claim we cannot support."""
    from friction_model import FrictionCircle

    fc = FrictionCircle(
        v_grid=np.linspace(5.0, 40.0, 8),
        traction_vals=np.full(8, 3.0),
        braking_vals=np.full(8, 9.0),
        lateral_vals=np.full(8, 12.0),
    )
    # Default construction has not fitted anything.
    assert fc.exponent_source == "hint"


def _make_boundary_saturating_laps(n_laps=8, n_pts=500, seed=42):
    """Synthetic laps with a genuine combined braking+cornering zone, so
    `_fit_ellipse_exponent` collects >= 20 qualifying boundary samples and
    takes its grid-search ("fitted") path rather than falling back to the
    hint. Shape borrowed from friction_model.py's own inline self-test
    fixture (`_make_circular_laps` inside `_run_tests`), since that fixture
    is the one already known to exercise the fit (its p lands at ~2.4, not
    the 2.0 hint)."""
    rng = np.random.default_rng(seed)
    radius = 50.0
    mu_lat, mu_trac, mu_brake = 1.2, 0.8, 1.5
    g = 9.80665
    a_lat_max = mu_lat * g
    a_trac_max = mu_trac * g
    a_brake_max = mu_brake * g
    v_corner = math.sqrt(a_lat_max * radius)
    track_len = 2 * math.pi * radius

    laps = {}
    for lap_num in range(1, n_laps + 1):
        dist = np.linspace(0, track_len, n_pts, endpoint=False)
        zone_len = track_len / 4
        zone = (dist / zone_len).astype(int) % 4

        speed = np.full(n_pts, v_corner)
        a_long = np.zeros(n_pts)
        a_lat = np.zeros(n_pts)

        # Pure cornering near the limit
        mask0 = zone == 0
        a_lat[mask0] = a_lat_max * (0.90 + 0.10 * rng.random(mask0.sum()))

        # Acceleration + some lateral
        mask1 = zone == 1
        n1 = int(mask1.sum())
        speed[mask1] = v_corner * (1.0 + np.linspace(0, 0.3, n1))
        a_long[mask1] = a_trac_max * (0.75 + 0.25 * rng.random(n1))
        a_lat[mask1] = a_lat_max * 0.3 * rng.random(n1)

        # Cornering near the limit again
        mask2 = zone == 2
        a_lat[mask2] = a_lat_max * (0.85 + 0.15 * rng.random(mask2.sum()))

        # Combined heavy braking + cornering -- this is the zone that
        # populates the boundary mask (both axes active at once).
        mask3 = zone == 3
        n3 = int(mask3.sum())
        speed[mask3] = v_corner * (1.3 - np.linspace(0, 0.3, n3))
        a_long[mask3] = -a_brake_max * (0.65 + 0.35 * rng.random(n3))
        a_lat[mask3] = a_lat_max * (0.3 + 0.4 * rng.random(n3))

        a_long += rng.normal(0, 0.05 * g, n_pts)
        a_lat += rng.normal(0, 0.05 * g, n_pts)

        dt = np.diff(dist) / np.maximum(speed[:-1], 1.0)
        t = np.concatenate([[0.0], np.cumsum(dt)])

        laps[lap_num] = pd.DataFrame({
            "Distance (m)":     dist,
            "Speed (m/s)":      speed,
            "accel_long_mps2":  a_long,
            "accel_lat_mps2":   a_lat,
            "Time (s)":         t,
        })
    return laps


def _make_pure_lateral_laps(n_laps=4, n_pts=200, seed=7):
    """Synthetic laps with lateral load only -- longitudinal accel is
    exactly zero throughout. `_fit_ellipse_exponent`'s boundary mask
    requires BOTH axes active (rx > 0.1 and ry > 0.1); with a_long == 0.0
    everywhere, rx is always 0.0, so n_boundary is guaranteed to be 0 --
    well under the ~20 needed to fit -- deterministically forcing the
    "hint" fallback path."""
    rng = np.random.default_rng(seed)
    laps = {}
    for lap_num in range(1, n_laps + 1):
        dist = np.linspace(0, 300.0, n_pts, endpoint=False)
        speed = np.full(n_pts, 20.0) + rng.normal(0, 0.1, n_pts)
        a_long = np.zeros(n_pts)
        a_lat = 9.0 + rng.normal(0, 0.2, n_pts)
        t = np.linspace(0, 15.0, n_pts)
        laps[lap_num] = pd.DataFrame({
            "Distance (m)":     dist,
            "Speed (m/s)":      speed,
            "accel_long_mps2":  a_long,
            "accel_lat_mps2":   a_lat,
            "Time (s)":         t,
        })
    return laps


def test_build_friction_model_reports_hint_when_boundary_data_is_insufficient():
    """Drives the real production entry point (`build_friction_model`), not
    just the dataclass default. This is the "hint" branch of
    `_fit_ellipse_exponent`: a pure-lateral dataset can never populate the
    boundary mask, so the fit is skipped and the hint is returned verbatim.

    The isinstance check is deliberate: a swapped tuple unpack at the
    `_fit_ellipse_exponent` call site (`exp_source, fitted_exp = ...`
    instead of `fitted_exp, exp_source = ...`) would put the string label
    into `.exponent`. A bare `== "hint"` on `exponent_source` alone would
    NOT catch that swap (it would just also be wrong in a way that could
    coincidentally look right), so the isinstance guard is what actually
    verifies the unpack order.
    """
    import friction_model as fm

    laps = _make_pure_lateral_laps()
    model = fm.build_friction_model(laps, speed_bins=4, min_samples_per_bin=5)

    assert model.exponent_source == "hint"
    assert isinstance(model.exponent, float)
    assert model.exponent == 2.0  # untouched default hint (kart_traction_floor=False)


def test_build_friction_model_reports_fitted_when_boundary_data_is_sufficient():
    """The "fitted" branch: a dataset with a genuine combined
    braking+cornering zone gives `_fit_ellipse_exponent` >= 20 boundary
    samples, so it actually runs the grid search instead of returning the
    hint unchanged.
    """
    import friction_model as fm

    laps = _make_boundary_saturating_laps()
    model = fm.build_friction_model(laps, speed_bins=10, percentile=95.0)

    assert model.exponent_source == "fitted"
    assert isinstance(model.exponent, float)
    assert 1.0 <= model.exponent <= 4.0


class _FakeFriction:
    """Minimal stand-in with the real FrictionCircle accessor names.

    Routed through np.interp over a 2-point grid purely to make a
    NON-FINITE speed observable -- NOT because it varies by speed value.
    Both grid endpoints share the same y-value, so every finite speed
    (in-range or out-of-range) still returns exactly the constructor's
    constant; only np.interp's flat-extrapolation behaviour at inf matters
    here. That mirrors the real FrictionCircle, which flat-extrapolates an
    out-of-range speed to the boundary grid value instead of returning NaN
    -- exactly the real danger the speed-finiteness guard in
    ellipse_fill_pct exists to catch. A fake that ignored its speed argument
    entirely could never make that guard's removal observable (every
    accessor would return the same constant regardless), which is exactly
    how all 6 original tests kept passing with the guard deleted.
    """

    _V_GRID = np.array([5.0, 45.0])

    def __init__(self, lat=12.0, brake=9.0, traction=3.0, exponent=2.0):
        self._lat, self._brake, self._trac, self.exponent = lat, brake, traction, exponent
        self.exponent_source = "fitted"

    def lateral_max(self, speed):
        return np.asarray(np.interp(speed, self._V_GRID, [self._lat, self._lat]), dtype=float)

    def braking_max(self, speed):
        return np.asarray(np.interp(speed, self._V_GRID, [self._brake, self._brake]), dtype=float)

    def traction_max(self, speed):
        return np.asarray(np.interp(speed, self._V_GRID, [self._trac, self._trac]), dtype=float)


def test_ellipse_fill_is_100_at_the_pure_lateral_boundary():
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0)
    assert ga.ellipse_fill_pct(12.0, 0.0, 25.0, f) == pytest.approx(100.0)


def test_ellipse_fill_is_100_at_the_pure_braking_boundary():
    import grip_anchor as ga

    f = _FakeFriction(brake=9.0)
    assert ga.ellipse_fill_pct(0.0, -9.0, 25.0, f) == pytest.approx(100.0)


def test_ellipse_fill_uses_the_braking_axis_for_deceleration():
    """Braking and traction limits are asymmetric (9.0 vs 3.0 here). Using the
    wrong axis silently mis-scales the longitudinal term."""
    import grip_anchor as ga

    f = _FakeFriction(brake=9.0, traction=3.0)
    braking = ga.ellipse_fill_pct(0.0, -3.0, 25.0, f)
    accelerating = ga.ellipse_fill_pct(0.0, 3.0, 25.0, f)

    assert braking == pytest.approx(100.0 * 3.0 / 9.0)
    assert accelerating == pytest.approx(100.0)


def test_ellipse_fill_combines_both_axes():
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0, brake=9.0, exponent=2.0)
    # Half of each axis: sqrt(0.5^2 + 0.5^2) = 0.7071
    assert ga.ellipse_fill_pct(6.0, -4.5, 25.0, f) == pytest.approx(70.71, abs=0.01)


def test_ellipse_fill_is_NOT_capped_at_100():
    """The envelope is a percentile, not a maximum, so exceeding it is expected
    and is the most diagnostic value we can report. Capping destroys the one
    signal that reveals over-driving or a wrong envelope."""
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0)
    assert ga.ellipse_fill_pct(18.0, 0.0, 25.0, f) == pytest.approx(150.0)


def test_ellipse_fill_returns_none_on_a_degenerate_envelope():
    import grip_anchor as ga

    assert ga.ellipse_fill_pct(5.0, 0.0, 25.0, _FakeFriction(lat=0.0)) is None
    assert ga.ellipse_fill_pct(np.nan, 0.0, 25.0, _FakeFriction()) is None


def test_ellipse_fill_does_not_raise_on_an_overflowing_tiny_limit():
    """A finite, strictly-positive, but vanishingly small envelope limit is
    NOT caught by the `<= 0` guard (it's not exactly zero, NaN, or inf).
    Reviewer's exact reproducer: raising a ~1e150 ratio to the exponent
    overflows float64 range. Python's native `float ** float` RAISES
    OverflowError there; only doing the arithmetic in numpy float64 (which
    silently saturates to inf) lets the existing isfinite(frac) guard run
    instead of the exception propagating. Reachable in production because
    FrictionCircle.from_dict() reconstructs a model WITHOUT re-applying
    build_friction_model's _FLOOR, so a corrupted/partial persisted envelope
    can supply a value this small without ever being exactly 0.
    """
    import grip_anchor as ga

    f = _FakeFriction(traction=1e-150, exponent=3.0)
    assert ga.ellipse_fill_pct(0.0, 1.0, 25.0, f) is None


def test_ellipse_fill_respects_a_non_default_exponent_1_6():
    """The real kart exponent is ~1.6, not the FrictionCircle default of 2.0.
    Uses a COMBINED sample (both axes active) because a pure-axis sample
    returns 100.0 at every p and would not discriminate a hardcoded p=2 --
    exactly the gap the brief warned about by name.

    rx = |a_long|/ax_max = 4.5/9.0 = 0.5, ry = a_lat/ay_max = 6.0/12.0 = 0.5
    frac = 0.5**1.6 + 0.5**1.6 = 0.659754...
    pct  = 100 * frac**(1/1.6) = 77.1105...  (a hardcoded p=2 would read 70.71)
    """
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0, brake=9.0, exponent=1.6)
    assert ga.ellipse_fill_pct(6.0, -4.5, 25.0, f) == pytest.approx(77.11, abs=0.01)


def test_ellipse_fill_respects_a_non_default_exponent_3_0():
    """Same combined sample as the 1.6 case above, at a sharper exponent.

    rx = ry = 0.5
    frac = 0.5**3.0 + 0.5**3.0 = 0.25
    pct  = 100 * frac**(1/3.0) = 62.996...  (a hardcoded p=2 would read 70.71)
    """
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0, brake=9.0, exponent=3.0)
    assert ga.ellipse_fill_pct(6.0, -4.5, 25.0, f) == pytest.approx(63.00, abs=0.01)


def test_ellipse_fill_returns_none_for_a_non_finite_speed():
    """A non-finite speed must be refused before it ever reaches the friction
    model. Against a REAL FrictionCircle, np.interp flat-extrapolates an
    out-of-range speed to the boundary grid value instead of NaN, so without
    this guard an infinite speed would silently produce a plausible-but-wrong
    percentage rather than a refusal. `_FakeFriction` mirrors that same
    flat-extrapolation via np.interp, so this test is only green because the
    guard fires before the fake is ever called.
    """
    import grip_anchor as ga

    assert ga.ellipse_fill_pct(5.0, 0.0, float("inf"), _FakeFriction()) is None


def test_ellipse_fill_does_not_leak_inf_from_the_second_power():
    """Reviewer's exact reproducer (round 2): frac itself is finite here
    (~1.9988 -- two axis ratios of 0.5 raised to a near-zero exponent, so
    each term is close to 1), but frac ** (1/p) with p=0.0009 means raising
    it to the ~1111th power, which overflows float64 on its OWN even though
    frac never did. p=0.0009 passes the `p <= 0` guard (it's not <= 0), and
    is reachable via FrictionCircle.from_dict()'s unclamped
    `exponent=d.get("exponent", _DEFAULT_ELLIPSE_EXP)`. Before this fix the
    function returned a silent `inf` (worse than the original OverflowError
    crash: this value is destined for a double-precision DB column and a
    JSON payload) -- it must return None instead.
    """
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0, brake=9.0, exponent=0.0009)
    assert ga.ellipse_fill_pct(6.0, -4.5, 25.0, f) is None


def test_ellipse_fill_never_leaks_inf_or_nan_across_extreme_exponents_and_limits():
    """Property sweep, not just a single point: across a grid of extreme
    exponents and axis limits, ellipse_fill_pct must never raise and must
    never return inf or nan -- only None or a finite float. Regression
    coverage for both leaks found in review: an uncaught OverflowError from
    the first power (round 1), then a silent inf leaking from the second,
    unchecked power (round 2).
    """
    import grip_anchor as ga

    exponents = [0.0009, 0.01, 1.0, 1.6, 2.0, 3.0, 1e6]
    limits = [1e-300, 1e-150, 1e-3, 1.0, 12.0]

    for exponent, limit in itertools.product(exponents, limits):
        f = _FakeFriction(lat=limit, brake=limit, traction=limit, exponent=exponent)
        result = ga.ellipse_fill_pct(6.0, -4.5, 25.0, f)
        ok = result is None or (isinstance(result, float) and math.isfinite(result))
        assert ok, f"exponent={exponent!r} limit={limit!r} -> {result!r}"
