"""Analyze Dallara 100K dataset for setup-performance correlations.

Computes per-circuit and global correlations between aero balance,
grip, downforce ratio, and lap/sector times.  Saves structured
results to data/external/setup_correlations.json.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CSV = os.path.join(_ROOT, "data", "external", "kaggle_dallara", "dallara_100k.csv")
_OUT = os.path.join(_ROOT, "data", "external", "setup_correlations.json")

MIN_N = 20
MIN_R = 0.1


def _corr(x: np.ndarray, y: np.ndarray) -> float | None:
    """Pearson r if both arrays have enough valid points, else None."""
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < MIN_N:
        return None
    r = np.corrcoef(x[mask], y[mask])[0, 1]
    return round(float(r), 4) if abs(r) >= MIN_R else None


def _optimal_balance(grp: pd.DataFrame) -> float:
    """Median aero_balance_pct of the fastest 10% laps."""
    q10 = grp["lap_time_s"].quantile(0.10)
    fast = grp.loc[grp["lap_time_s"] <= q10, "aero_balance_pct"]
    return round(float(fast.median()), 2) if len(fast) > 0 else float("nan")


def _fastest_config(grp: pd.DataFrame) -> str | None:
    """aero_config with lowest median lap time (must have >= MIN_N rows)."""
    med = grp.groupby("aero_config")["lap_time_s"].agg(["median", "count"])
    med = med[med["count"] >= MIN_N]
    return str(med["median"].idxmin()) if len(med) > 0 else None


def analyze(csv_path: str = _CSV) -> dict:
    df = pd.read_csv(csv_path)
    needed = ["circuit", "aero_balance_pct", "grip_mult", "lap_time_s",
              "df_front_kg", "df_rear_kg", "aero_config",
              "slow_corners", "fast_corners",
              "sector1_s", "sector2_s", "sector3_s"]
    df = df.dropna(subset=["lap_time_s", "aero_balance_pct"])
    df["df_ratio"] = df["df_front_kg"] / df["df_rear_kg"].replace(0, np.nan)

    # ── Per-circuit analysis ─────────────────────────────────────────
    per_circuit: dict[str, dict] = {}
    for circuit, grp in df.groupby("circuit"):
        if len(grp) < MIN_N:
            continue
        entry: dict = {
            "n": int(len(grp)),
            "optimal_aero_balance": _optimal_balance(grp),
            "balance_lap_time_corr": _corr(
                grp["aero_balance_pct"].values, grp["lap_time_s"].values),
            "grip_lap_time_corr": _corr(
                grp["grip_mult"].values, grp["lap_time_s"].values),
            "fastest_config": _fastest_config(grp),
        }
        # Does lower balance help in slow vs fast corners?
        for sec, col in [("sector1_s", "sector1_s"), ("sector2_s", "sector2_s"),
                         ("sector3_s", "sector3_s")]:
            entry[f"balance_{sec}_corr"] = _corr(
                grp["aero_balance_pct"].values, grp[col].values)
        per_circuit[str(circuit)] = {k: v for k, v in entry.items() if v is not None}

    # ── Global cross-circuit analysis ────────────────────────────────
    circ_agg = df.groupby("circuit").agg(
        median_balance=("aero_balance_pct", "median"),
        best_balance=("aero_balance_pct", lambda s: s[df.loc[s.index, "lap_time_s"] <= df.loc[s.index, "lap_time_s"].quantile(0.1)].median()),
        slow_corners=("slow_corners", "first"),
        fast_corners=("fast_corners", "first"),
        median_lap=("lap_time_s", "median"),
        n=("lap_time_s", "count"),
    ).dropna()

    slow_corr = _corr(circ_agg["slow_corners"].values,
                       circ_agg["best_balance"].values)
    fast_corr = _corr(circ_agg["fast_corners"].values,
                       circ_agg["best_balance"].values)

    # DF ratio vs sector times (global)
    df_ratio_sector = {}
    for sec in ["sector1_s", "sector2_s", "sector3_s"]:
        r = _corr(df["df_ratio"].values, df[sec].values)
        if r is not None:
            df_ratio_sector[sec] = r

    # Grip sensitivity (global)
    grip_sens = _corr(df["grip_mult"].values, df["lap_time_s"].values)

    # Optimal balance range (across circuits)
    opt_vals = [v["optimal_aero_balance"] for v in per_circuit.values()
                if "optimal_aero_balance" in v and np.isfinite(v["optimal_aero_balance"])]
    opt_range = [round(float(np.percentile(opt_vals, 25)), 2),
                 round(float(np.percentile(opt_vals, 75)), 2)] if opt_vals else None

    # Fastest config per circuit_type
    config_by_type = {}
    for ctype, grp in df.groupby("circuit_type"):
        fc = _fastest_config(grp)
        if fc:
            config_by_type[str(ctype)] = fc

    # Interpret slow/fast corner preference
    slow_pref = ("lower (more front)" if (slow_corr and slow_corr < 0)
                 else "higher (more rear)" if (slow_corr and slow_corr > 0)
                 else "no clear preference")
    fast_pref = ("lower (more front)" if (fast_corr and fast_corr < 0)
                 else "higher (more rear)" if (fast_corr and fast_corr > 0)
                 else "no clear preference")

    global_findings = {
        "slow_corner_tracks_prefer_balance": slow_pref,
        "slow_corner_balance_corr": slow_corr,
        "fast_corner_tracks_prefer_balance": fast_pref,
        "fast_corner_balance_corr": fast_corr,
        "optimal_balance_range": opt_range,
        "grip_sensitivity": grip_sens,
        "df_ratio_vs_sectors": df_ratio_sector,
        "fastest_config_by_circuit_type": config_by_type,
    }
    global_findings = {k: v for k, v in global_findings.items() if v is not None}

    return {"per_circuit": per_circuit, "global_findings": global_findings}


def _print_summary(results: dict) -> None:
    pc = results["per_circuit"]
    gf = results["global_findings"]

    print(f"\n{'='*72}")
    print(f"  Dallara 100K Setup-Performance Correlation Analysis")
    print(f"  {len(pc)} circuits analyzed")
    print(f"{'='*72}\n")

    # Per-circuit table
    hdr = f"{'Circuit':<22} {'N':>5} {'Opt.Bal%':>8} {'Bal-LT r':>9} {'Grip-LT r':>10} {'Best Config':<16}"
    print(hdr)
    print("-" * len(hdr))
    for circ in sorted(pc):
        c = pc[circ]
        print(f"{circ:<22} {c.get('n',''):>5} "
              f"{c.get('optimal_aero_balance','--'):>8} "
              f"{c.get('balance_lap_time_corr','--'):>9} "
              f"{c.get('grip_lap_time_corr','--'):>10} "
              f"{c.get('fastest_config','--'):<16}")

    print(f"\n--- Global Findings ---")
    print(f"  Slow-corner tracks prefer: {gf.get('slow_corner_tracks_prefer_balance','?')}"
          f" (r={gf.get('slow_corner_balance_corr','--')})")
    print(f"  Fast-corner tracks prefer: {gf.get('fast_corner_tracks_prefer_balance','?')}"
          f" (r={gf.get('fast_corner_balance_corr','--')})")
    if "optimal_balance_range" in gf:
        print(f"  Optimal aero balance IQR:  {gf['optimal_balance_range'][0]}-{gf['optimal_balance_range'][1]}%")
    if "grip_sensitivity" in gf:
        print(f"  Grip-mult vs lap time:     r={gf['grip_sensitivity']}")
    if "fastest_config_by_circuit_type" in gf:
        print(f"  Fastest config by type:    {gf['fastest_config_by_circuit_type']}")
    print()


if __name__ == "__main__":
    results = analyze()
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    with open(_OUT, "w") as f:
        json.dump(results, f, indent=2, allow_nan=False, default=str)
    print(f"Results saved to {_OUT}")
    _print_summary(results)
