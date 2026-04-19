#!/usr/bin/env python
"""Generate AC job queue for the Lap Oracle Lua app.

Creates varied combos of car × track × AI level × weather × temperature.
Each job drives ALL available pit spots worth of AI cars simultaneously.

Usage
-----
    python scripts/generate_ac_jobs.py
    python scripts/generate_ac_jobs.py --max-cars 5 --max-tracks 3
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.lap_oracle.config import ORACLE_DATA, SIM_PATHS

_SKIP_TRACKS = {"drift", "drag", "dragstrip", "hillclimb", "test", "showroom"}

# Weather presets: (label, graphics_key, ambient_temp, track_temp, wind_min, wind_max)
WEATHER_PRESETS = [
    ("clear_hot",    "3_clear",         30, 42, 0,  3),
    ("clear_mild",   "3_clear",         22, 30, 2,  6),
    ("cloudy",       "7_light_clouds",  18, 24, 5, 12),
    ("overcast",     "11_heavy_clouds", 14, 18, 8, 18),
    ("light_rain",   "16_light_rain",   16, 20, 5, 15),
    ("heavy_rain",   "18_heavy_rain",   12, 14, 10, 25),
]

AI_LEVELS = [60, 80, 95, 100]

# Max AI opponents per session (AC limit depends on track pit spots)
MAX_OPPONENTS = 23  # AC max is usually 24 total (1 player + 23 AI)


def _discover_cars(prefix: str = "", max_cars: int = 0) -> list[str]:
    """Discover all valid AC cars (any prefix, not just ks_)."""
    cars: list[str] = []
    for base in SIM_PATHS.get("ac", []):
        cars_dir = base / "content" / "cars"
        if not cars_dir.is_dir():
            continue
        for d in sorted(cars_dir.iterdir()):
            if not d.is_dir():
                continue
            if prefix and not d.name.startswith(prefix):
                continue
            if d.name in cars:
                continue
            has_model = any(d.glob("*.kn5"))
            has_data = (d / "data.acd").exists() or (d / "data").is_dir()
            # Must have AI data for opponents to drive
            has_ai = (d / "ai").is_dir() or (d / "data.acd").exists()
            if has_model and has_data:
                cars.append(d.name)
    if max_cars > 0:
        cars = cars[:max_cars]
    return cars


def _discover_tracks(max_tracks: int = 0) -> list[str]:
    tracks: list[str] = []
    for base in SIM_PATHS.get("ac", []):
        tracks_dir = base / "content" / "tracks"
        if not tracks_dir.is_dir():
            continue
        for d in sorted(tracks_dir.iterdir()):
            if not d.is_dir():
                continue
            if any(skip in d.name.lower() for skip in _SKIP_TRACKS):
                continue

            def _valid(td: Path) -> bool:
                return (
                    (td / "ui").is_dir()
                    and (td / "data").is_dir()
                    and (td / "ai").is_dir()
                    and (td / "ai" / "fast_lane.ai").exists()
                )

            has_layout = False
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and _valid(sub):
                    spec = d.name + "/" + sub.name
                    if spec not in tracks:
                        tracks.append(spec)
                        has_layout = True
            if not has_layout and _valid(d):
                if d.name not in tracks:
                    tracks.append(d.name)
    if max_tracks > 0:
        tracks = tracks[:max_tracks]
    return tracks


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AC job queue")
    parser.add_argument("--max-cars", type=int, default=10)
    parser.add_argument("--max-tracks", type=int, default=0)
    parser.add_argument("--ai-levels", type=str, default="60,80,95,100",
                        help="Comma-separated AI levels")
    parser.add_argument("--weather", type=str, default="all",
                        help="'all' or comma-separated: clear_hot,cloudy,heavy_rain")
    parser.add_argument("--laps", type=int, default=5)
    parser.add_argument("--max-opponents", type=int, default=MAX_OPPONENTS)
    args = parser.parse_args()

    cars = _discover_cars(max_cars=args.max_cars)
    tracks = _discover_tracks(max_tracks=args.max_tracks)
    ai_levels = [int(x) for x in args.ai_levels.split(",")]

    if args.weather == "all":
        weathers = WEATHER_PRESETS
    else:
        names = [w.strip() for w in args.weather.split(",")]
        weathers = [w for w in WEATHER_PRESETS if w[0] in names]

    print(f"Cars:     {len(cars)}")
    print(f"Tracks:   {len(tracks)}")
    print(f"AI lvls:  {ai_levels}")
    print(f"Weather:  {[w[0] for w in weathers]}")
    print(f"Laps:     {args.laps}")
    print(f"Max AI:   {args.max_opponents}")

    # Generate all combos
    lines = ["return {"]
    count = 0
    for track in tracks:
        for car in cars:
            for ai in ai_levels:
                for wlabel, wgfx, wamb, wtrk, wwmin, wwmax in weathers:
                    lines.append(
                        f'  {{car="{car}", track="{track}", '
                        f'ai_level={ai}, opponents={args.max_opponents}, '
                        f'laps={args.laps}, '
                        f'weather="{wlabel}", weather_gfx="{wgfx}", '
                        f'temp_ambient={wamb}, temp_track={wtrk}, '
                        f'wind_min={wwmin}, wind_max={wwmax}}},'
                    )
                    count += 1
    lines.append("}")

    total = len(cars) * len(tracks) * len(ai_levels) * len(weathers)
    print(f"Total:    {count} jobs ({total} combos)")
    print(f"Est time: ~{count * args.laps * 2:.0f} min ({count * args.laps * 2 / 60:.1f} hrs)")

    out_path = ORACLE_DATA / "ac_jobs.lua"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written:  {out_path}")

    state_path = ORACLE_DATA / "ac_state.lua"
    state_path.write_text("return {jobIndex=0, lapsDone=0}\n", encoding="utf-8")
    print(f"State:    reset")


if __name__ == "__main__":
    main()
