"""Tests for ACD parsing and metadata enrichment."""
from __future__ import annotations

from pathlib import Path

import pytest

from kart_envelope.ingest.acd_parser import enrich_metadata_from_acd, load_acd_engine_data
from kart_envelope.ingest.metadata import SessionMetadata, parse_metadata


def _encrypt_payload(payload: bytes, key: str) -> bytes:
    key_bytes = key.encode("latin1")
    out = bytearray(len(payload) * 4)
    j = 0
    for i, val in enumerate(payload):
        enc = int(val) + int(key_bytes[j])
        if enc >= 256:
            enc -= 256
        out[i * 4] = enc
        j = 0 if j == len(key_bytes) - 1 else j + 1
    return bytes(out)


def _write_acd(path: Path, key: str, entries: dict[str, str]) -> None:
    blob = bytearray()
    for name, text in entries.items():
        name_b = name.encode("ascii")
        payload_b = text.encode("latin1")
        blob.extend(len(name_b).to_bytes(4, "little", signed=True))
        blob.extend(name_b)
        blob.extend(len(payload_b).to_bytes(4, "little", signed=True))
        blob.extend(_encrypt_payload(payload_b, key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(blob))


def test_load_acd_engine_data_parses_curve_and_mass(tmp_path: Path) -> None:
    key = "-" * 19
    aero_ini = "\n".join([
        "[HEADER]",
        "VERSION=2",
        "[WING_0]",
        "NAME=BODY",
        "CHORD=1.175",
        "SPAN=0.575",
    ]) + ("\n" + ("LUT_AOA_CL=wing_body_AOA_CL.lut\n" * 20))
    engine_ini = """
[HEADER]
VERSION=1
POWER_CURVE=power.lut

[ENGINE_DATA]
LIMITER=4000
MINIMUM=1000

[COAST_REF]
RPM=4000
TORQUE=16
""".strip()
    power_lut = "\n".join([
        "0|0",
        "1000|10",
        "2000|20",
        "3000|20",
        "4000|10",
    ])
    car_ini = """
[INFO]
SCREEN_NAME=Test Kart GX270

[BASIC]
TOTALMASS=180
""".strip()
    acd_path = tmp_path / "data.acd"
    _write_acd(
        acd_path,
        key,
        {
            "aero.ini": aero_ini,
            "engine.ini": engine_ini,
            "power.lut": power_lut,
            "car.ini": car_ini,
        },
    )

    acd = load_acd_engine_data(acd_path)
    assert acd.entry_count == 4
    assert acd.engine_curve_file == "power.lut"
    assert acd.total_mass_kg == pytest.approx(180.0)
    assert acd.displacement_cc == pytest.approx(270.0)
    assert acd.peak_torque_nm == pytest.approx(20.0)
    assert acd.peak_power_kw is not None
    assert acd.peak_power_kw > 6.2


def test_enrich_metadata_from_acd_updates_session_metadata(tmp_path: Path) -> None:
    key = "-" * 19
    aero_ini = "\n".join([
        "[HEADER]",
        "VERSION=2",
        "[WING_0]",
        "NAME=BODY",
        "CHORD=1.140",
        "SPAN=0.590",
    ]) + ("\n" + ("LUT_AOA_CD=wing_body_AOA_CD.lut\n" * 20))
    engine_ini = """
[HEADER]
VERSION=1
POWER_CURVE=power.lut

[ENGINE_DATA]
LIMITER=5000
MINIMUM=1200

[COAST_REF]
RPM=5000
TORQUE=24
""".strip()
    power_lut = "\n".join([
        "0|0",
        "1500|18",
        "2500|26",
        "3500|23",
        "5000|0",
    ])
    car_ini = """
[INFO]
SCREEN_NAME=Sodi RT10 GX390

[BASIC]
TOTALMASS=220
""".strip()
    acd_path = tmp_path / "kart_data" / "rt10" / "gx390cc" / "data.acd"
    _write_acd(
        acd_path,
        key,
        {
            "aero.ini": aero_ini,
            "engine.ini": engine_ini,
            "power.lut": power_lut,
            "car.ini": car_ini,
        },
    )

    meta = SessionMetadata(
        session_file="demo.csv",
        kart_model="Sodi RT10 390cc",
        engine_size_cc=390.0,
        driver_weight_kg=85.0,
        kart_data_acd=str(acd_path),
    )
    acd = enrich_metadata_from_acd(meta)
    assert acd is not None
    assert meta.kart_weight_kg == pytest.approx(135.0)
    assert meta.engine_peak_power_kw is not None
    assert meta.engine_peak_power_kw > 6.0
    assert meta.engine_peak_power_hp is not None
    assert meta.engine_peak_torque_nm is not None


def test_parse_metadata_time_and_numeric_aliases(tmp_path: Path) -> None:
    csv_path = tmp_path / "meta.csv"
    csv_path.write_text(
        "\n".join(
            [
                "session_file,track_record,engine_size_cc,engine_peak_power_hp,driver_weight,kart_data_acd,product_tier,layout_id,sensor_profile",
                "OK_R4.csv,1:03:097,390cc,30cv,85,data/kart_data/sr4-5/gx390cc/data.acd,b2b_basic,L1,imu6_gps",
            ]
        ),
        encoding="utf-8",
    )
    rows = parse_metadata(csv_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.track_record_s == pytest.approx(63.097)
    assert row.engine_size_cc == pytest.approx(390.0)
    assert row.engine_peak_power_hp == pytest.approx(30.0)
    assert row.driver_weight_kg == pytest.approx(85.0)
    assert row.kart_data_acd == "data/kart_data/sr4-5/gx390cc/data.acd"
    assert row.product_tier == "b2b_basic"
    assert row.layout_id == "L1"
    assert row.sensor_profile == "imu6_gps"
