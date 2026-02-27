"""
tiering.py
----------
Tier contracts for sensor validation, feature routing, and B2B domain gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

PRODUCT_TIER_B2C = "b2c"
PRODUCT_TIER_B2B_BASIC = "b2b_basic"
PRODUCT_TIER_B2B_PREMIUM = "b2b_premium"
PRODUCT_TIER_DEFAULT = PRODUCT_TIER_B2C
KNOWN_PRODUCT_TIERS = {
    PRODUCT_TIER_B2C,
    PRODUCT_TIER_B2B_BASIC,
    PRODUCT_TIER_B2B_PREMIUM,
}


def normalize_product_tier(value: object) -> str:
    if value is None:
        return PRODUCT_TIER_DEFAULT
    s = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if s in {"premium", "b2bpremium"}:
        return PRODUCT_TIER_B2B_PREMIUM
    if s in {"basic", "b2bbasic", "b2b"}:
        return PRODUCT_TIER_B2B_BASIC
    if s in KNOWN_PRODUCT_TIERS:
        return s
    return PRODUCT_TIER_DEFAULT


def resolve_product_tier(config_tier: object, metadata_tier: object) -> str:
    if metadata_tier is not None and str(metadata_tier).strip():
        return normalize_product_tier(metadata_tier)
    return normalize_product_tier(config_tier)


def parse_csv_set(value: object) -> set[str]:
    if value is None:
        return set()
    text = str(value).strip()
    if not text:
        return set()
    parts = [p.strip().lower() for p in text.split(",")]
    return {p for p in parts if p}


def required_columns_for_tier(tier: str) -> set[str]:
    base = {
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
    if tier == PRODUCT_TIER_B2C:
        # Magnetometer proxy: heading channel from GPS/phone fusion.
        return set(base) | {COL_HEADING}
    if tier == PRODUCT_TIER_B2B_PREMIUM:
        return set(base) | {COL_STEERING_ANGLE_DEG, COL_THROTTLE_PCT, COL_BRAKE_PCT}
    return base


def infer_sensor_profile(columns: set[str]) -> str:
    has_base = all(c in columns for c in (COL_ACCEL_LONG, COL_ACCEL_LAT, COL_YAW_RATE))
    has_heading = COL_HEADING in columns
    has_controls = all(
        c in columns for c in (COL_STEERING_ANGLE_DEG, COL_THROTTLE_PCT, COL_BRAKE_PCT)
    )
    if has_base and has_controls:
        return "imu6_gps_plus_controls"
    if has_base and has_heading:
        return "imu9_gps_proxy"
    if has_base:
        return "imu6_gps"
    return "unknown"


@dataclass
class SensorValidationResult:
    product_tier: str
    strict: bool
    passed: bool
    required_columns: list[str]
    missing_columns: list[str]
    available_columns: list[str]
    inferred_sensor_profile: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_tier": self.product_tier,
            "strict": bool(self.strict),
            "passed": bool(self.passed),
            "required_columns": list(self.required_columns),
            "missing_columns": list(self.missing_columns),
            "available_columns": list(self.available_columns),
            "inferred_sensor_profile": self.inferred_sensor_profile,
            "reason": self.reason,
        }


def validate_sensor_contract(
    columns: set[str],
    *,
    tier: str,
    strict: bool,
) -> SensorValidationResult:
    required = required_columns_for_tier(tier)
    missing = sorted(required - set(columns))
    passed = len(missing) == 0 or not strict
    reason = "ok" if len(missing) == 0 else f"missing channels: {', '.join(missing)}"
    return SensorValidationResult(
        product_tier=tier,
        strict=bool(strict),
        passed=bool(passed),
        required_columns=sorted(required),
        missing_columns=missing,
        available_columns=sorted(columns),
        inferred_sensor_profile=infer_sensor_profile(set(columns)),
        reason=reason,
    )


@dataclass
class DomainGateResult:
    product_tier: str
    enabled: bool
    in_domain: bool
    soft_gate_triggered: bool
    reason: str
    whitelist_tracks: list[str]
    whitelist_karts: list[str]
    whitelist_layouts: list[str]
    track_match: bool
    kart_match: bool
    layout_match: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_tier": self.product_tier,
            "enabled": bool(self.enabled),
            "in_domain": bool(self.in_domain),
            "soft_gate_triggered": bool(self.soft_gate_triggered),
            "reason": self.reason,
            "whitelist_tracks": list(self.whitelist_tracks),
            "whitelist_karts": list(self.whitelist_karts),
            "whitelist_layouts": list(self.whitelist_layouts),
            "track_match": bool(self.track_match),
            "kart_match": bool(self.kart_match),
            "layout_match": bool(self.layout_match),
        }


def evaluate_domain_gate(
    *,
    tier: str,
    track_name: object,
    kart_id: object,
    layout_id: object,
    whitelist_tracks_csv: object,
    whitelist_karts_csv: object,
    whitelist_layouts_csv: object,
    soft_gate_enable: bool,
) -> DomainGateResult:
    t = normalize_product_tier(tier)
    if t not in {PRODUCT_TIER_B2B_BASIC, PRODUCT_TIER_B2B_PREMIUM}:
        return DomainGateResult(
            product_tier=t,
            enabled=False,
            in_domain=True,
            soft_gate_triggered=False,
            reason="domain gate disabled for tier",
            whitelist_tracks=[],
            whitelist_karts=[],
            whitelist_layouts=[],
            track_match=True,
            kart_match=True,
            layout_match=True,
        )

    wl_tracks = parse_csv_set(whitelist_tracks_csv)
    wl_karts = parse_csv_set(whitelist_karts_csv)
    wl_layouts = parse_csv_set(whitelist_layouts_csv)
    track_key = str(track_name or "").strip().lower()
    kart_key = str(kart_id or "").strip().lower()
    layout_key = str(layout_id or "").strip().lower()

    track_match = (not wl_tracks) or (track_key in wl_tracks)
    kart_match = (not wl_karts) or (kart_key in wl_karts)
    layout_match = (not wl_layouts) or (layout_key in wl_layouts)
    in_domain = bool(track_match and kart_match and layout_match)
    soft = bool((not in_domain) and soft_gate_enable)
    if in_domain:
        reason = "in-domain whitelist match"
    elif soft:
        reason = "out-of-domain: soft gate fallback to global bundle"
    else:
        reason = "out-of-domain: strict reject"

    return DomainGateResult(
        product_tier=t,
        enabled=True,
        in_domain=in_domain,
        soft_gate_triggered=soft,
        reason=reason,
        whitelist_tracks=sorted(wl_tracks),
        whitelist_karts=sorted(wl_karts),
        whitelist_layouts=sorted(wl_layouts),
        track_match=bool(track_match),
        kart_match=bool(kart_match),
        layout_match=bool(layout_match),
    )

