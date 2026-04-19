"""Build per-corner handling baselines across kart sessions and detect tire degradation.

Part 1 -- Cross-session corner baseline:
  Load 5 Ouest Karting sessions, run handling analysis on each best lap,
  match corners across sessions by GPS apex proximity (haversine < 20 m),
  classify each corner as confirmed / likely / variable tendency.

Part 2 -- Tire degradation trend:
  Pick the session with the most laps, run handling analysis per-lap,
  compute direction-vs-lap-number correlation per corner to identify
  front or rear tire degradation.

Outputs:
  artifacts/kart_corner_baseline.json
  artifacts/kart_tire_degradation.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import butter, filtfilt

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telemetry_tool.handling.runner import run_handling_analysis  # noqa: E402

# -- Constants ----------------------------------------------------------------
SESSIONS = {
    "OK_FP+Q": ROOT / "data" / "raw" / "OK_FP+Q.csv",
    "OK_R1":   ROOT / "data" / "raw" / "OK_R1.csv",
    "OK_R2":   ROOT / "data" / "raw" / "OK_R2.csv",
    "OK_R3":   ROOT / "data" / "raw" / "OK_R3.csv",
    "OK_R4":   ROOT / "data" / "raw" / "OK_R4.csv",
}
MATCH_RADIUS_M = 20.0
LPF_HZ = 1.5
LPF_ORDER = 2
ARTIFACTS = ROOT / "artifacts"


# -- Helpers ------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2))
         * np.sin(dlon / 2) ** 2)
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def load_racechrono(csv_path: pathlib.Path) -> pd.DataFrame:
    """Load a RaceChrono CSV, skipping metadata rows."""
    header_row = None
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            if line.strip().startswith("Time (s)"):
                header_row = i
                break
    if header_row is None:
        raise ValueError(f"No header row found in {csv_path}")
    df = pd.read_csv(csv_path, skiprows=header_row, low_memory=False)
    df.columns = df.columns.str.strip()
    return df


def extract_channels(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Extract and coerce the channels needed for handling analysis."""
    def col(name, fallback=None):
        s = df.get(name) if name in df.columns else None
        if s is None and fallback:
            s = df.get(fallback)
        if s is None:
            raise KeyError(f"Column {name!r} (fallback {fallback!r}) not found")
        return pd.to_numeric(s, errors="coerce").values

    return {
        "time_s":  col("Time (s)"),
        "dist_m":  col("Distance (m)"),
        "speed":   col("Speed (m/s) *calc", "Speed (m/s)"),
        "a_lat":   col("Lateral acceleration (G) *calc"),
        "a_lon":   col("Longitudinal acceleration (G) *calc"),
        "bearing": col("Bearing (deg)"),
        "lat_deg": col("Latitude (deg)"),
        "lon_deg": col("Longitude (deg)"),
        "lap_col": col("Lap #"),
    }


def find_best_lap(ch: dict) -> tuple[int, float]:
    """Return (best_lap_number, lap_time) -- shortest valid lap."""
    laps = pd.Series(ch["lap_col"]).dropna()
    laps = laps[laps > 0].unique()
    best_lap, best_time = None, np.inf
    for ln in laps:
        m = ch["lap_col"] == ln
        t = ch["time_s"][m]
        if len(t) < 50:
            continue
        lt = t[-1] - t[0]
        if 10 < lt < best_time:
            best_time, best_lap = lt, int(ln)
    return best_lap, best_time


def valid_laps(ch: dict) -> list[int]:
    """Return sorted list of lap numbers with enough samples."""
    laps = pd.Series(ch["lap_col"]).dropna()
    laps = laps[laps > 0].unique()
    result = []
    for ln in laps:
        m = ch["lap_col"] == ln
        t = ch["time_s"][m]
        if len(t) < 50:
            continue
        lt = t[-1] - t[0]
        if lt > 10:
            result.append(int(ln))
    return sorted(result)


def run_for_lap(ch: dict, lap_num: int) -> dict | None:
    """Run handling analysis for a single lap. Returns result dict or None."""
    try:
        return run_handling_analysis(
            ch["time_s"], ch["dist_m"], ch["speed"],
            ch["a_lat"], ch["a_lon"], ch["bearing"],
            ch["lat_deg"], ch["lon_deg"], ch["lap_col"],
            best_lap=lap_num,
            wheelbase_m=1.0,
            vehicle_class="kart",
        )
    except Exception as e:
        print(f"  [WARN] lap {lap_num} failed: {e}")
        return None


# -- Part 1: Cross-session corner baseline ------------------------------------

def build_corner_baseline() -> dict:
    """Analyze best lap from each session, match corners, build baseline."""
    print("=" * 60)
    print("PART 1: Cross-Session Corner Baseline")
    print("=" * 60)

    # Collect per-session results
    session_corners: list[tuple[str, list[dict]]] = []

    for name, path in SESSIONS.items():
        print(f"\n--- {name} ({path.name}) ---")
        if not path.exists():
            print(f"  [SKIP] file not found")
            continue
        df = load_racechrono(path)
        ch = extract_channels(df)
        best_lap, best_time = find_best_lap(ch)
        if best_lap is None:
            print(f"  [SKIP] no valid laps")
            continue
        print(f"  Best lap: #{best_lap} ({best_time:.2f}s), {len(df)} rows")
        result = run_for_lap(ch, best_lap)
        if result is None or not result["corners"]:
            print(f"  [SKIP] no corners detected")
            continue
        print(f"  {len(result['corners'])} corners, "
              f"{result['summary'].get('tendency', '?')}")
        session_corners.append((name, result["corners"]))

    if not session_corners:
        print("\n[ERROR] No sessions produced corners.")
        return {"track": "Ouest Karting", "n_sessions": 0, "corners": []}

    # Use the first session's corners as the reference set
    ref_name, ref_corners = session_corners[0]
    print(f"\nReference session: {ref_name} ({len(ref_corners)} corners)")

    # Match corners across sessions by apex GPS proximity
    matched: list[dict] = []
    for ci, rc in enumerate(ref_corners):
        # Extract apex lat/lon from the corner's events or from corner summary
        apex_lat = _corner_apex_lat(rc)
        apex_lon = _corner_apex_lon(rc)
        if apex_lat == 0 and apex_lon == 0:
            continue

        group = {
            "corner_id": ci,
            "apex_lat": round(apex_lat, 6),
            "apex_lon": round(apex_lon, 6),
            "per_session": [],
        }

        # Add reference session's own data
        ref_events = rc.get("events", [])
        ref_dir, ref_zone = _dominant_event(ref_events)
        group["per_session"].append({
            "session": ref_name,
            "direction": ref_dir,
            "zone": ref_zone,
        })

        # Match against other sessions
        for other_name, other_corners in session_corners[1:]:
            best_match = _find_nearest_corner(
                apex_lat, apex_lon, other_corners, MATCH_RADIUS_M)
            if best_match is not None:
                other_events = best_match.get("events", [])
                od, oz = _dominant_event(other_events)
                group["per_session"].append({
                    "session": other_name,
                    "direction": od,
                    "zone": oz,
                })

        matched.append(group)

    # Classify each corner group
    output_corners = []
    for g in matched:
        n = len(g["per_session"])
        dirs = [p["direction"] for p in g["per_session"]]

        us_count = sum(1 for d in dirs if d > 0.15)
        os_count = sum(1 for d in dirs if d < -0.15)
        dominant_count = max(us_count, os_count)

        if n == 0:
            continue

        agreement = dominant_count / n
        if us_count >= os_count:
            tendency = "understeer"
            zone_votes = [p["zone"] for p in g["per_session"]
                          if p["direction"] > 0.15]
        else:
            tendency = "oversteer"
            zone_votes = [p["zone"] for p in g["per_session"]
                          if p["direction"] < -0.15]

        # Determine dominant zone
        if zone_votes:
            from collections import Counter
            zone_counter = Counter(zone_votes)
            dominant_zone = zone_counter.most_common(1)[0][0]
            tendency = f"{dominant_zone}_{tendency}"

        if agreement >= 0.80:
            confidence = "confirmed"
        elif agreement >= 0.60:
            confidence = "likely"
        else:
            confidence = "variable"
            tendency = "variable"

        output_corners.append({
            "corner_id": g["corner_id"],
            "apex_lat": g["apex_lat"],
            "apex_lon": g["apex_lon"],
            "sessions_with_data": n,
            "tendency": tendency,
            "agreement": round(agreement, 2),
            "confidence": confidence,
            "per_session": [
                {
                    "session": p["session"],
                    "direction": round(p["direction"], 3),
                    "zone": p["zone"],
                }
                for p in g["per_session"]
            ],
        })

    baseline = {
        "track": "Ouest Karting",
        "n_sessions": len(session_corners),
        "corners": output_corners,
    }

    # Print summary table
    print(f"\n{'='*60}")
    print(f"Corner Baseline Summary  ({len(output_corners)} corners, "
          f"{len(session_corners)} sessions)")
    print(f"{'='*60}")
    print(f"{'C#':>3}  {'Tendency':<22} {'Agree':>5}  {'Conf':<10} "
          f"{'Sess':>4}  {'Apex Lat':>10}  {'Apex Lon':>10}")
    print("-" * 75)
    for c in output_corners:
        print(f"{c['corner_id']:>3}  {c['tendency']:<22} "
              f"{c['agreement']:>5.0%}  {c['confidence']:<10} "
              f"{c['sessions_with_data']:>4}  "
              f"{c['apex_lat']:>10.5f}  {c['apex_lon']:>10.5f}")

    return baseline


def _corner_apex_lat(corner_summary: dict) -> float:
    """Extract apex latitude from a corner summary dict.

    The runner stores events with start/end dist but the CornerWindow's apex GPS
    is only available in the summary via the events.  We parse the first event's
    corner_id and reconstruct from the corner list.  As a reliable fallback we
    search events for GPS coords; if none, return 0.
    """
    # The runner.py corner summaries don't expose apex_lat/apex_lon directly,
    # but they're in the events' lat_deg array.  The simplest approach:
    # re-read the start_m/end_m as proxy, but we actually stored it
    # in the original CornerWindow.  Since we only get dicts back, we
    # embed the apex lat/lon into corner summaries inside our run_for_lap call.
    # -- For now, get from our enriched run wrapper --
    return corner_summary.get("_apex_lat", 0.0)


def _corner_apex_lon(corner_summary: dict) -> float:
    return corner_summary.get("_apex_lon", 0.0)


def _dominant_event(events: list[dict]) -> tuple[float, str]:
    """Return (direction, zone) of the highest-confidence event."""
    if not events:
        return 0.0, "mid"
    best = max(events, key=lambda e: e.get("confidence", 0))
    return best.get("direction", 0.0), best.get("corner_phase", "mid")


def _find_nearest_corner(
    lat: float, lon: float, corners: list[dict], radius_m: float
) -> dict | None:
    """Find the corner in the list whose apex is closest within radius."""
    best_d, best_c = radius_m + 1, None
    for c in corners:
        clat = c.get("_apex_lat", 0.0)
        clon = c.get("_apex_lon", 0.0)
        if clat == 0 and clon == 0:
            continue
        d = _haversine_m(lat, lon, clat, clon)
        if d < best_d:
            best_d, best_c = d, c
    return best_c


# -- Part 2: Tire degradation trend -------------------------------------------

def detect_tire_degradation() -> dict:
    """Run handling analysis on every lap of the longest session."""
    print(f"\n{'='*60}")
    print("PART 2: Tire Degradation Trend")
    print("=" * 60)

    # Find session with most laps
    best_session, best_laps, best_ch = None, [], None
    for name, path in SESSIONS.items():
        if not path.exists():
            continue
        df = load_racechrono(path)
        ch = extract_channels(df)
        laps = valid_laps(ch)
        print(f"  {name}: {len(laps)} valid laps")
        if len(laps) > len(best_laps):
            best_session, best_laps, best_ch = name, laps, ch

    if best_ch is None or len(best_laps) < 3:
        print("[ERROR] No session with >= 3 laps found.")
        return {"session": "", "n_laps_analyzed": 0, "corners": []}

    print(f"\nSelected: {best_session} ({len(best_laps)} laps: "
          f"{best_laps})")

    # Find best lap's sample count to filter incomplete laps
    bl, _ = find_best_lap(best_ch)
    best_count = int((best_ch["lap_col"] == bl).sum())
    min_count = int(best_count * 0.50)

    # Run analysis on each valid lap
    per_lap_corners: list[tuple[int, list[dict]]] = []
    for lap_num in best_laps:
        count = int((best_ch["lap_col"] == lap_num).sum())
        if count < min_count:
            print(f"  Lap {lap_num}: {count} samples < {min_count} min, "
                  f"skipping")
            continue
        result = run_for_lap(best_ch, lap_num)
        if result is None or not result["corners"]:
            print(f"  Lap {lap_num}: no corners detected, skipping")
            continue
        per_lap_corners.append((lap_num, result["corners"]))
        print(f"  Lap {lap_num}: {len(result['corners'])} corners")

    if len(per_lap_corners) < 3:
        print("[WARN] Fewer than 3 laps with corners, degradation unreliable.")

    # Match corners across laps (use first lap as reference)
    ref_lap, ref_corners = per_lap_corners[0]
    corner_trends: list[dict] = []

    for ci, rc in enumerate(ref_corners):
        apex_lat = rc.get("_apex_lat", 0.0)
        apex_lon = rc.get("_apex_lon", 0.0)
        if apex_lat == 0 and apex_lon == 0:
            continue

        per_lap_data = []
        for lap_num, lap_corners in per_lap_corners:
            match = _find_nearest_corner(
                apex_lat, apex_lon, lap_corners, MATCH_RADIUS_M)
            if match is not None:
                events = match.get("events", [])
                d, _ = _dominant_event(events)
                per_lap_data.append({"lap": lap_num, "direction": round(d, 3)})

        if len(per_lap_data) < 3:
            continue

        # Linear regression: direction vs lap index
        x = np.arange(len(per_lap_data), dtype=float)
        y = np.array([p["direction"] for p in per_lap_data])
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        if np.isnan(r_value):
            r_value = 0.0

        if abs(r_value) < 0.3:
            interp = "stable (no significant trend)"
        elif slope > 0:
            interp = "increasing understeer (front tire deg)"
        else:
            interp = "increasing oversteer (rear tire deg)"

        corner_trends.append({
            "corner_id": ci,
            "apex_lat": round(apex_lat, 6),
            "apex_lon": round(apex_lon, 6),
            "trend_slope": round(float(slope), 4),
            "trend_r": round(float(r_value), 3),
            "trend_p": round(float(p_value), 4),
            "interpretation": interp,
            "per_lap": per_lap_data,
        })

    # Overall trend: weighted average of slopes (weighted by |r|)
    if corner_trends:
        weights = np.array([abs(c["trend_r"]) for c in corner_trends])
        slopes = np.array([c["trend_slope"] for c in corner_trends])
        valid_w = ~np.isnan(weights)
        weights = np.where(valid_w, weights, 0.0)
        if weights.sum() > 0:
            avg_slope = float(np.average(slopes, weights=weights))
        else:
            avg_slope = float(np.mean(slopes))

        if abs(avg_slope) < 0.01:
            overall = "stable"
        elif avg_slope > 0:
            overall = "front_limited_degradation"
        else:
            overall = "rear_limited_degradation"
    else:
        avg_slope = 0.0
        overall = "insufficient_data"

    degradation = {
        "session": best_session,
        "n_laps_analyzed": len(per_lap_corners),
        "overall_trend": overall,
        "overall_slope": round(avg_slope, 4),
        "corners": corner_trends,
    }

    # Print summary
    print(f"\n{'='*60}")
    print(f"Tire Degradation Summary  ({best_session}, "
          f"{len(per_lap_corners)} laps)")
    print(f"{'='*60}")
    print(f"{'C#':>3}  {'Slope':>7}  {'R':>6}  {'Interpretation':<42}")
    print("-" * 65)
    for c in corner_trends:
        print(f"{c['corner_id']:>3}  {c['trend_slope']:>+7.4f}  "
              f"{c['trend_r']:>6.3f}  {c['interpretation']}")
    print("-" * 65)
    print(f"Overall: {overall} (weighted slope={avg_slope:+.4f})")

    return degradation


# -- Monkey-patch runner to expose apex lat/lon in corner summaries -----------

_orig_run = run_handling_analysis


def _enriched_run(*args, **kwargs) -> dict:
    """Wrapper that injects _apex_lat/_apex_lon into corner summary dicts.

    The original runner builds CornerWindows internally but only serializes
    start_m/end_m/events.  We need the apex GPS for cross-session matching,
    so we re-derive it from the session lat/lon arrays.
    """
    result = _orig_run(*args, **kwargs)

    # args: time_s, dist_m, speed_mps, a_lat_g, a_lon_g, bearing_deg,
    #        lat_deg, lon_deg, lap_col, best_lap
    lat_deg = args[6]
    lon_deg = args[7]
    a_lat_g = args[3]

    for csummary in result.get("corners", []):
        # Reconstruct apex index from start_m / end_m via distance array
        dist_m = args[1]
        s_m = csummary.get("start_m", 0)
        e_m = csummary.get("end_m", 0)

        # Find indices closest to start_m and end_m
        si = int(np.argmin(np.abs(dist_m - s_m)))
        ei = int(np.argmin(np.abs(dist_m - e_m)))
        if ei <= si:
            ei = si + 1

        # Apex = peak |a_lat_g| within this corner range
        seg = slice(si, ei)
        abs_alat = np.abs(a_lat_g[seg])
        if len(abs_alat) > 0:
            apex_local = int(np.argmax(abs_alat))
            apex_global = si + apex_local
            csummary["_apex_lat"] = float(lat_deg[apex_global])
            csummary["_apex_lon"] = float(lon_deg[apex_global])
        else:
            csummary["_apex_lat"] = 0.0
            csummary["_apex_lon"] = 0.0

    return result


# Replace the import with our enriched version
run_handling_analysis_enriched = _enriched_run


# Override the module-level function used by run_for_lap
def run_for_lap(ch: dict, lap_num: int) -> dict | None:  # noqa: F811
    """Run handling analysis for a single lap with apex GPS enrichment."""
    try:
        return _enriched_run(
            ch["time_s"], ch["dist_m"], ch["speed"],
            ch["a_lat"], ch["a_lon"], ch["bearing"],
            ch["lat_deg"], ch["lon_deg"], ch["lap_col"],
            lap_num,
            wheelbase_m=1.0,
            vehicle_class="kart",
        )
    except Exception as e:
        print(f"  [WARN] lap {lap_num} failed: {e}")
        return None


# -- Main ---------------------------------------------------------------------

def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    baseline = build_corner_baseline()
    baseline_path = ARTIFACTS / "kart_corner_baseline.json"
    with open(baseline_path, "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"\nSaved: {baseline_path}")

    degradation = detect_tire_degradation()
    deg_path = ARTIFACTS / "kart_tire_degradation.json"
    with open(deg_path, "w") as f:
        json.dump(degradation, f, indent=2)
    print(f"Saved: {deg_path}")


if __name__ == "__main__":
    main()
