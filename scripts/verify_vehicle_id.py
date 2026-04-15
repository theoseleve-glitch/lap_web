"""Step 1 verification: fit VehicleModel from the Daytona .ibt session.

Produces:
  1. Fitted vehicle parameters (mass, aero, brake bias, etc.)
  2. Mean shock deflection ratio → infer weight distribution
  3. Roll-angle samples at known right/left turns → confirm lateral sign convention

This is a read-only diagnostic — no files are written.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))  # for kart_envelope / telemetry_tool packages
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))  # for lap_oracle shortcut

from lap_oracle.extractors.iracing_ibt import _parse_header, _parse_var_headers

IBT_PATH = Path(
    "C:/Users/Admin/Documents/iRacing/telemetry/"
    "mclaren570sgt4_daytona 2011 road 2026-01-09 23-40-48.ibt"
)

TYPE_DTYPE = {1: np.uint8, 2: np.int32, 3: np.uint32, 4: np.float32, 5: np.float64}
TYPE_SIZE = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


def extract_as_dataframe(path: Path) -> pd.DataFrame:
    """Extract all float channels into a DataFrame with irsdk__<Name> columns."""
    with open(path, "rb") as f:
        header_bytes = f.read(max(4096, 144 * 500 + 200))
        hdr = _parse_header(header_bytes)
        vars_map = _parse_var_headers(header_bytes, hdr)
        file_size = os.path.getsize(path)
        num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
        f.seek(hdr["data_start"])
        raw = f.read(hdr["buf_len"] * num_samples)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(num_samples, hdr["buf_len"])

    data: dict[str, np.ndarray] = {}
    for name, info in vars_map.items():
        if info.get("count", 1) != 1:
            continue
        t = info["type"]
        if t not in TYPE_SIZE:
            continue
        off = info["offset"]
        sz = TYPE_SIZE[t]
        dt = TYPE_DTYPE[t]
        data[f"irsdk__{name}"] = np.frombuffer(
            arr[:, off : off + sz].tobytes(), dtype=dt
        ).astype(np.float64)

    return pd.DataFrame(data)


def main() -> None:
    print(f"Processing: {IBT_PATH.name}")
    print(f"Size: {os.path.getsize(IBT_PATH) / 1e6:.0f} MB\n")

    df = extract_as_dataframe(IBT_PATH)
    print(f"Loaded {len(df):,} samples, {len(df.columns)} channels")

    # Run optimize_session
    try:
        from sim_optimizer.pipeline import optimize_session
    except ImportError as exc:
        print(f"FAILED to import optimize_session: {exc}")
        return

    print("\nRunning optimize_session() ...")
    try:
        result = optimize_session(df)
    except Exception as exc:
        print(f"optimize_session FAILED: {exc}")
        import traceback
        traceback.print_exc()
        return

    print(f"\nSuccess: {result.success}")
    print(f"Errors: {result.errors}")

    vm = result.vehicle_model
    if vm is None:
        print("VehicleModel is None — cannot proceed with physics grip")
        return

    print("\n" + "=" * 60)
    print("FITTED VEHICLE MODEL")
    print("=" * 60)

    # Mass
    if hasattr(vm, "mass") and vm.mass is not None:
        print(f"Mass base:         {vm.mass.base_mass_kg:.1f} kg")
        print(f"Mass @ 30L fuel:   {vm.total_mass_kg(30.0):.1f} kg")
        print(f"Fuel density:      {vm.mass.fuel_density_kg_l} kg/L")

    # Aero
    if hasattr(vm, "aero") and vm.aero is not None:
        print(f"Aero CLA:          {getattr(vm.aero, 'cla', '—')}")
        print(f"Aero CDA:          {getattr(vm.aero, 'cda', '—')}")

    # Brake
    if hasattr(vm, "brake") and vm.brake is not None:
        print(f"Brake max decel:   {getattr(vm.brake, 'max_decel_mps2', '—')} m/s²")
        print(f"Brake bias front:  {getattr(vm.brake, 'brake_bias_front', '—')}")

    # Powertrain
    if hasattr(vm, "powertrain") and vm.powertrain is not None:
        print(f"Max power:         {getattr(vm.powertrain, 'max_power_w', '—')} W")

    # Tyre (Pacejka: F_y = D × sin(C × arctan(B × α)))
    if hasattr(vm, "tyre") and vm.tyre is not None:
        print(f"Tyre mu_lat (peak):  {vm.tyre.mu_lat:.3f}")
        print(f"Tyre d_lat:          {vm.tyre.d_lat:.3f}  (Pacejka D lateral)")
        print(f"Tyre mu_long (peak): {vm.tyre.mu_long:.3f}")
        print(f"Tyre d_long:         {vm.tyre.d_long:.3f}")
        print(f"Tyre source:         {vm.tyre.source}")
        print(f"p_combined:          {vm.p_combined}")

    # Suspension
    if hasattr(vm, "suspension") and vm.suspension is not None:
        for attr in ("spring_lf", "spring_rf", "spring_lr", "spring_rr",
                     "spring_rate_lf", "spring_rate_rf", "spring_rate_lr", "spring_rate_rr"):
            val = getattr(vm.suspension, attr, None)
            if val is not None:
                print(f"Susp {attr:<22}= {val}")

    # Shock deflection ratio → weight distribution proxy
    print("\n" + "=" * 60)
    print("WEIGHT DISTRIBUTION (from shock deflection)")
    print("=" * 60)
    needed = ["irsdk__LFshockDefl", "irsdk__RFshockDefl",
              "irsdk__LRshockDefl", "irsdk__RRshockDefl",
              "irsdk__IsOnTrack"]
    if all(c in df.columns for c in needed):
        on_track = df["irsdk__IsOnTrack"].values.astype(bool)
        # Steady-state: speed > 20, |a_long| < 1, |a_lat| < 1
        speed = df.get("irsdk__Speed", pd.Series(np.zeros(len(df)))).values
        a_long = df.get("irsdk__LongAccel", pd.Series(np.zeros(len(df)))).values
        a_lat = df.get("irsdk__LatAccel", pd.Series(np.zeros(len(df)))).values
        steady = on_track & (speed > 20) & (np.abs(a_long) < 1.5) & (np.abs(a_lat) < 1.5)
        if steady.sum() > 100:
            lf = df["irsdk__LFshockDefl"].values[steady].mean()
            rf = df["irsdk__RFshockDefl"].values[steady].mean()
            lr = df["irsdk__LRshockDefl"].values[steady].mean()
            rr = df["irsdk__RRshockDefl"].values[steady].mean()
            total = lf + rf + lr + rr
            print(f"Mean shock defl (steady state, N={steady.sum()}):")
            print(f"  LF={lf:.2f}  RF={rf:.2f}  LR={lr:.2f}  RR={rr:.2f} mm")
            print(f"  Sum={total:.2f} mm")
            if total > 0:
                front_ratio = (lf + rf) / total
                print(f"  Front shock deflection fraction: {front_ratio:.3f}")
                print(f"  (Higher fraction = more weight on front)")

    # Lateral sign convention check
    print("\n" + "=" * 60)
    print("LATERAL SIGN CONVENTION CHECK")
    print("=" * 60)
    if "irsdk__LatAccel" in df.columns and "irsdk__Roll" in df.columns:
        lat_a = df["irsdk__LatAccel"].values
        roll = df["irsdk__Roll"].values
        on_track = df.get("irsdk__IsOnTrack", pd.Series(np.ones(len(df)))).values.astype(bool)

        # At high lateral accel, roll angle should tilt the car
        # Positive roll typically = right side down (right turn)
        strong_right = on_track & (lat_a > 5.0)
        strong_left = on_track & (lat_a < -5.0)
        if strong_right.sum() > 10:
            mean_roll_right = roll[strong_right].mean()
            print(f"LatAccel > +5 (N={strong_right.sum()}):")
            print(f"  mean Roll = {np.degrees(mean_roll_right):+.2f}°")
        if strong_left.sum() > 10:
            mean_roll_left = roll[strong_left].mean()
            print(f"LatAccel < -5 (N={strong_left.sum()}):")
            print(f"  mean Roll = {np.degrees(mean_roll_left):+.2f}°")
        print("Interpretation:")
        print("  If LatAccel > 0 correlates with positive Roll → right turn = +a_lat")
        print("  If LatAccel > 0 correlates with negative Roll → left turn = +a_lat")


if __name__ == "__main__":
    main()
