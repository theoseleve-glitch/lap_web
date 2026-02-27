"""Tests for tier contracts: sensor validation and domain gating."""
from __future__ import annotations

from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_BRAKE_PCT,
    COL_DIST,
    COL_HEADING,
    COL_LAP,
    COL_LAT,
    COL_LON,
    COL_SPEED,
    COL_STEERING_ANGLE_DEG,
    COL_THROTTLE_PCT,
    COL_TIME,
    COL_YAW_RATE,
)
from kart_envelope.tiering import (
    PRODUCT_TIER_B2B_BASIC,
    PRODUCT_TIER_B2B_PREMIUM,
    PRODUCT_TIER_B2C,
    evaluate_domain_gate,
    normalize_product_tier,
    validate_sensor_contract,
)


def _base_columns() -> set[str]:
    return {
        COL_TIME,
        COL_SPEED,
        COL_DIST,
        COL_LAP,
        COL_LAT,
        COL_LON,
        COL_ACCEL_LONG,
        COL_ACCEL_LAT,
        COL_YAW_RATE,
    }


def test_validate_sensor_contract_b2c_requires_heading_proxy():
    cols = _base_columns()
    rep = validate_sensor_contract(cols, tier=PRODUCT_TIER_B2C, strict=True)
    assert rep.passed is False
    assert COL_HEADING in rep.missing_columns

    cols.add(COL_HEADING)
    rep2 = validate_sensor_contract(cols, tier=PRODUCT_TIER_B2C, strict=True)
    assert rep2.passed is True


def test_validate_sensor_contract_premium_requires_controls():
    cols = _base_columns()
    rep = validate_sensor_contract(cols, tier=PRODUCT_TIER_B2B_PREMIUM, strict=True)
    assert rep.passed is False
    assert COL_STEERING_ANGLE_DEG in rep.missing_columns
    assert COL_THROTTLE_PCT in rep.missing_columns
    assert COL_BRAKE_PCT in rep.missing_columns

    cols.update({COL_STEERING_ANGLE_DEG, COL_THROTTLE_PCT, COL_BRAKE_PCT})
    rep2 = validate_sensor_contract(cols, tier=PRODUCT_TIER_B2B_PREMIUM, strict=True)
    assert rep2.passed is True


def test_validate_sensor_contract_basic_passes_with_imu6_gps():
    cols = _base_columns()
    rep = validate_sensor_contract(cols, tier=PRODUCT_TIER_B2B_BASIC, strict=True)
    assert rep.passed is True


def test_domain_gate_soft_and_strict():
    soft = evaluate_domain_gate(
        tier=PRODUCT_TIER_B2B_BASIC,
        track_name="cks",
        kart_id="kart-x",
        layout_id="layout-a",
        whitelist_tracks_csv="cks",
        whitelist_karts_csv="kart-y",
        whitelist_layouts_csv="layout-a",
        soft_gate_enable=True,
    )
    assert soft.enabled is True
    assert soft.in_domain is False
    assert soft.soft_gate_triggered is True

    strict = evaluate_domain_gate(
        tier=PRODUCT_TIER_B2B_BASIC,
        track_name="cks",
        kart_id="kart-x",
        layout_id="layout-a",
        whitelist_tracks_csv="cks",
        whitelist_karts_csv="kart-y",
        whitelist_layouts_csv="layout-a",
        soft_gate_enable=False,
    )
    assert strict.enabled is True
    assert strict.in_domain is False
    assert strict.soft_gate_triggered is False


def test_normalize_product_tier_aliases():
    assert normalize_product_tier("premium") == PRODUCT_TIER_B2B_PREMIUM
    assert normalize_product_tier("B2B basic") == PRODUCT_TIER_B2B_BASIC
    assert normalize_product_tier("unknown") == PRODUCT_TIER_B2C

