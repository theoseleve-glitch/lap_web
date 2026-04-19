"""Phase 4: Cross-track validation using F1 TracingInsights data.

Reads directly from ZIP archives (18 GB total) without extracting.
Processes one lap at a time to stay within memory limits.

Validates:
- Detectors work across diverse track types
- Driver comparison (E2): VER vs HAM handling tendencies
- Track profile (E3): which tracks expose US vs OS
"""
import sys, pathlib, json, warnings, zipfile
import numpy as np

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adapters.f1_adapter import load_from_zip, list_laps_in_zip
from telemetry_tool.handling.runner import run_handling_analysis

# Tracks to validate (diverse mix: street, fast, slow, low-df, mixed)
TRACKS = {
    "Australian Grand Prix": "street",
    "British Grand Prix": "fast",
    "Italian Grand Prix": "low_downforce",
    "Japanese Grand Prix": "technical",
}

DRIVERS = ["VER", "HAM", "NOR"]
SESSIONS = ["Qualifying"]
ZIPS_DIR = pathlib.Path("c:/Users/Admin/Downloads")


def find_best_lap(zip_path: str, gp: str, session: str, driver: str) -> str | None:
    """Find the lap with the most data points (likely the hotlap)."""
    laps = list_laps_in_zip(zip_path, gp_name=gp, session=session, driver=driver)
    if not laps:
        return None
    # Pick the largest file (most data = hotlap)
    best = None
    best_size = 0
    with zipfile.ZipFile(zip_path) as z:
        for lap_path in laps:
            try:
                info = z.getinfo(lap_path)
                if info.file_size > best_size:
                    best_size = info.file_size
                    best = lap_path
            except KeyError:
                continue
    return best


def analyze_lap(zip_path: str, tel_path: str) -> dict | None:
    """Load one lap from zip and run handling analysis."""
    try:
        data = load_from_zip(zip_path, tel_path)
    except Exception as e:
        return None

    n = len(data.get("time_s", []))
    if n < 100:
        return None

    try:
        result = run_handling_analysis(
            time_s=data["time_s"],
            dist_m=data["dist_m"],
            speed_mps=data["speed_mps"],
            a_lat_g=data["a_lat_g"],
            a_lon_g=data["a_lon_g"],
            bearing_deg=data["bearing_deg"],
            lat_deg=data["lat_deg"],
            lon_deg=data["lon_deg"],
            lap_col=data["lap_col"],
            best_lap=1,
            wheelbase_m=3.6,  # F1 car wheelbase
            vehicle_class="car",
        )
        return result
    except Exception:
        return None


def main():
    # Find available zip files
    available_zips = {}
    for year in [2022, 2023, 2024, 2025, 2026]:
        zp = ZIPS_DIR / f"{year}-main.zip"
        if zp.exists():
            available_zips[year] = str(zp)

    if not available_zips:
        print("No F1 zip files found in Downloads!")
        return

    print(f"Found {len(available_zips)} season zips: {sorted(available_zips.keys())}")

    results = []  # list of {year, track, track_type, driver, summary}
    n_processed = 0

    for year, zip_path in sorted(available_zips.items()):
        print(f"\n--- Season {year} ---")

        for gp, track_type in TRACKS.items():
            for driver in DRIVERS:
                for session in SESSIONS:
                    if n_processed >= 50:
                        break

                    lap_path = find_best_lap(zip_path, gp, session, driver)
                    if not lap_path:
                        continue

                    lap_name = pathlib.Path(lap_path).stem
                    print(f"  {gp[:20]:20s} {session:10s} {driver:3s} {lap_name}...", end=" ", flush=True)

                    result = analyze_lap(zip_path, lap_path)
                    if result is None:
                        print("SKIP")
                        continue

                    summary = result.get("summary", {})
                    n_ev = summary.get("n_events", 0)
                    tend = summary.get("tendency", "?")
                    conf = summary.get("avg_confidence", 0)
                    print(f"{n_ev} events, {tend}, conf={conf:.0%}")

                    results.append({
                        "year": year,
                        "track": gp,
                        "track_type": track_type,
                        "driver": driver,
                        "session": session,
                        "n_corners": summary.get("n_corners", 0),
                        "n_events": n_ev,
                        "n_understeer": summary.get("n_understeer", 0),
                        "n_oversteer": summary.get("n_oversteer", 0),
                        "avg_confidence": round(conf, 3),
                        "tendency": tend,
                        "overall_direction": summary.get("overall_direction", 0),
                    })
                    n_processed += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"F1 CROSS-TRACK VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"Laps processed: {len(results)}")
    print(f"Seasons:        {len(available_zips)}")
    print(f"Tracks:         {len(set(r['track'] for r in results))}")
    print(f"Drivers:        {len(set(r['driver'] for r in results))}")

    # Per-driver tendency
    print(f"\nPer-driver:")
    for drv in DRIVERS:
        drv_results = [r for r in results if r["driver"] == drv]
        if drv_results:
            avg_dir = np.mean([r["overall_direction"] for r in drv_results])
            n_us = sum(r["n_understeer"] for r in drv_results)
            n_os = sum(r["n_oversteer"] for r in drv_results)
            print(f"  {drv}: avg_dir={avg_dir:+.3f}, {n_us} US events, {n_os} OS events")

    # Per-track tendency
    print(f"\nPer-track:")
    for track in TRACKS:
        track_results = [r for r in results if r["track"] == track]
        if track_results:
            avg_dir = np.mean([r["overall_direction"] for r in track_results])
            tend = "US" if avg_dir > 0.05 else ("OS" if avg_dir < -0.05 else "BAL")
            print(f"  {track:25s}: avg_dir={avg_dir:+.3f} ({tend})")

    # Save
    out_path = ROOT / "artifacts" / "validation_f1_cross_track.json"
    with open(out_path, "w") as f:
        json.dump({"laps": results, "n_processed": len(results)}, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
