from __future__ import annotations

from dataclasses import replace

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.solver.aero import build_aero_runtime
from kart_envelope.solver.powertrain import build_powertrain_runtime


def test_aero_runtime_drag_and_downforce():
    cfg = replace(default_config(), aero_enable_drag=True, aero_enable_downforce=True)
    meta = SessionMetadata(session_file="s.csv", aero_cda=0.75, aero_cl=0.35, condition_label="dry")
    aero = build_aero_runtime(meta, cfg, condition_label="dry")
    drag = aero.drag_accel(20.0, 180.0)
    lf = aero.downforce_load_factor(20.0, 180.0)
    assert drag > 0.0
    assert lf >= 1.0


def test_powertrain_curve_and_transmission():
    cfg = replace(default_config(), powertrain_enable_transmission=True, powertrain_auto_shift=True)
    meta = SessionMetadata(
        session_file="s.csv",
        driver_weight_kg=85.0,
        kart_weight_kg=95.0,
        gear_ratios="1.3,1.1,0.95",
        final_drive_ratio=1.0,
    )
    acd_engine = {
        "peak_power_kw": 10.0,
        "rpm_curve": [1500, 2500, 3500, 4500, 5500, 6500],
        "torque_nm_curve": [18.0, 22.0, 24.0, 23.0, 21.0, 18.0],
        "power_kw_curve": [2.8, 5.8, 8.8, 10.8, 12.1, 12.2],
    }
    rt = build_powertrain_runtime(meta, cfg, acd_engine=acd_engine)
    low = rt.max_drive_accel(6.0, 8.0)
    high = rt.max_drive_accel(24.0, 8.0)
    assert low > 0.0
    assert high > 0.0
    assert low <= 8.0
    assert high <= 8.0
    assert rt.to_dict().get("curve_available") is True
