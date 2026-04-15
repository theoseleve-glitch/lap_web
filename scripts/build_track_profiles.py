"""Step 4: Build F1 track handling profiles from 2022-2026 data.

Reads from zip archives without extracting. Processes qualifying sessions
for VER, HAM, NOR across available GPs.

Output: data/external/track_profiles.json
"""
import sys, pathlib, json, warnings, zipfile
import numpy as np

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adapters.f1_adapter import load_from_zip, list_laps_in_zip
from telemetry_tool.handling.runner import run_handling_analysis
from telemetry_tool.handling.cross_session import build_track_profile

DRIVERS = ["VER", "HAM", "NOR"]
ZIPS_DIR = pathlib.Path("c:/Users/Admin/Downloads")
MAX_TOTAL_LAPS = 200


def find_best_lap(zip_path, gp, session, driver):
    laps = list_laps_in_zip(zip_path, gp_name=gp, session=session, driver=driver)
    if not laps:
        return None
    best, best_size = None, 0
    with zipfile.ZipFile(zip_path) as z:
        for lp in laps:
            try:
                if z.getinfo(lp).file_size > best_size:
                    best_size = z.getinfo(lp).file_size
                    best = lp
            except KeyError:
                continue
    return best


def analyze_lap(zip_path, tel_path):
    try:
        data = load_from_zip(zip_path, tel_path)
    except Exception:
        return None
    if len(data.get("time_s", [])) < 100:
        return None
    try:
        return run_handling_analysis(
            time_s=data["time_s"], dist_m=data["dist_m"],
            speed_mps=data["speed_mps"], a_lat_g=data["a_lat_g"],
            a_lon_g=data["a_lon_g"], bearing_deg=data["bearing_deg"],
            lat_deg=data["lat_deg"], lon_deg=data["lon_deg"],
            lap_col=data["lap_col"], best_lap=1,
            wheelbase_m=3.6, vehicle_class="car",
        )
    except Exception:
        return None


def main():
    available_zips = {}
    for year in [2022, 2023, 2024, 2025, 2026]:
        zp = ZIPS_DIR / f"{year}-main.zip"
        if zp.exists():
            available_zips[year] = str(zp)

    print(f"Found {len(available_zips)} seasons: {sorted(available_zips.keys())}")

    # Discover all GPs
    all_gps = set()
    for year, zp in available_zips.items():
        with zipfile.ZipFile(zp) as z:
            for name in z.namelist():
                parts = name.split("/")
                if len(parts) >= 4 and "_tel.json" in name:
                    all_gps.add(parts[1])

    print(f"Found {len(all_gps)} Grand Prix events")

    # Process each GP
    track_results = {}  # {gp_name: [result_dicts]}
    n_processed = 0

    for gp in sorted(all_gps):
        if "Testing" in gp or "Pre-Season" in gp:
            continue
        track_results[gp] = []

        for year, zp in sorted(available_zips.items()):
            for driver in DRIVERS:
                if n_processed >= MAX_TOTAL_LAPS:
                    break
                lap_path = find_best_lap(zp, gp, "Qualifying", driver)
                if not lap_path:
                    continue

                result = analyze_lap(zp, lap_path)
                if result is None:
                    continue

                summary = result.get("summary", {})
                track_results[gp].append({
                    "year": year, "driver": driver,
                    "summary": summary, "events": result.get("events", []),
                })
                n_processed += 1

        n_laps = len(track_results[gp])
        if n_laps > 0:
            tendencies = [r["summary"].get("tendency", "?") for r in track_results[gp]]
            print(f"  {gp:30s}: {n_laps} laps, tendencies: {tendencies[:5]}")

    # Build profiles using cross_session module
    profiles = {}
    for gp, results in track_results.items():
        if len(results) < 2:
            continue

        # Aggregate events
        n_us = sum(r["summary"].get("n_understeer", 0) for r in results)
        n_os = sum(r["summary"].get("n_oversteer", 0) for r in results)
        avg_dir = np.mean([r["summary"].get("overall_direction", 0) for r in results])
        avg_conf = np.mean([r["summary"].get("avg_confidence", 0) for r in results])

        tendency = "understeer" if avg_dir > 0.05 else ("oversteer" if avg_dir < -0.05 else "balanced")

        profiles[gp] = {
            "n_sessions": len(results),
            "n_understeer_total": n_us,
            "n_oversteer_total": n_os,
            "avg_direction": round(float(avg_dir), 4),
            "avg_confidence": round(float(avg_conf), 4),
            "overall_tendency": tendency,
            "years": sorted(set(r["year"] for r in results)),
            "drivers": sorted(set(r["driver"] for r in results)),
        }

    # Save
    out_path = ROOT / "data" / "external" / "track_profiles.json"
    with open(out_path, "w") as f:
        json.dump(profiles, f, indent=2)

    print(f"\n{'='*60}")
    print(f"TRACK PROFILES SUMMARY")
    print(f"{'='*60}")
    print(f"Tracks with profiles: {len(profiles)}")
    print(f"Total laps processed: {n_processed}")
    for gp, p in sorted(profiles.items()):
        print(f"  {gp:30s}: {p['overall_tendency']:10s} dir={p['avg_direction']:+.3f} "
              f"({p['n_sessions']} laps, {p['n_understeer_total']}US/{p['n_oversteer_total']}OS)")

    print(f"\nSaved to {out_path}")

    # Also build driver benchmarks (Step 5)
    _build_driver_benchmarks(track_results)


def _build_driver_benchmarks(track_results):
    """Step 5: Aggregate per-driver handling stats."""
    driver_stats = {}

    for gp, results in track_results.items():
        for r in results:
            drv = r["driver"]
            if drv not in driver_stats:
                driver_stats[drv] = {"laps": 0, "events": 0, "us": 0, "os": 0,
                                     "directions": [], "confidences": [], "tracks": set()}
            s = r["summary"]
            driver_stats[drv]["laps"] += 1
            driver_stats[drv]["events"] += s.get("n_events", 0)
            driver_stats[drv]["us"] += s.get("n_understeer", 0)
            driver_stats[drv]["os"] += s.get("n_oversteer", 0)
            driver_stats[drv]["directions"].append(s.get("overall_direction", 0))
            driver_stats[drv]["confidences"].append(s.get("avg_confidence", 0))
            driver_stats[drv]["tracks"].add(gp)

    benchmarks = {}
    for drv, stats in driver_stats.items():
        n = stats["laps"]
        if n == 0:
            continue
        benchmarks[drv] = {
            "laps": n,
            "tracks": len(stats["tracks"]),
            "events_per_lap": round(stats["events"] / n, 2),
            "us_per_lap": round(stats["us"] / n, 2),
            "os_per_lap": round(stats["os"] / n, 2),
            "us_os_ratio": round(stats["us"] / (stats["os"] + 1), 2),
            "avg_direction": round(float(np.mean(stats["directions"])), 4),
            "avg_confidence": round(float(np.mean(stats["confidences"])), 4),
            "tendency": "understeer" if np.mean(stats["directions"]) > 0.05 else
                       ("oversteer" if np.mean(stats["directions"]) < -0.05 else "balanced"),
        }

    out_path = ROOT / "data" / "external" / "driver_benchmarks.json"
    with open(out_path, "w") as f:
        json.dump(benchmarks, f, indent=2)

    print(f"\n{'='*60}")
    print(f"DRIVER BENCHMARKS")
    print(f"{'='*60}")
    for drv, b in sorted(benchmarks.items()):
        print(f"  {drv}: {b['laps']} laps, {b['events_per_lap']:.1f} events/lap, "
              f"{b['tendency']}, US/OS={b['us_os_ratio']:.1f}")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
