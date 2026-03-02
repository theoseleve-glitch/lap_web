"""
Parity harness — compare local pipeline output with SaaS API responses.

Pure comparison functions (no I/O) plus a CLI wrapper that fetches from
the SaaS API and dumps baselines for offline diffing.

Usage:
    python scripts/parity_harness.py \
        --session-id <ID> --api-url <URL> \
        [--token <T>] [--dump] [--baseline-dir <DIR>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pure comparison helpers
# ---------------------------------------------------------------------------

def _numeric(val: Any) -> float | None:
    """Coerce a value to float, returning None if impossible."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _compare_field(
    field: str,
    local_val: Any,
    saas_val: Any,
    tolerance: float,
) -> dict | None:
    """Return a failure dict if *field* is outside tolerance, else None."""
    lv = _numeric(local_val)
    sv = _numeric(saas_val)
    if lv is None or sv is None:
        return {
            "field": field,
            "local": local_val,
            "saas": saas_val,
            "delta": None,
            "tolerance": tolerance,
            "reason": "missing_value",
        }
    delta = abs(lv - sv)
    if delta > tolerance:
        return {
            "field": field,
            "local": lv,
            "saas": sv,
            "delta": round(delta, 6),
            "tolerance": tolerance,
        }
    return None


# ---------------------------------------------------------------------------
# Score comparison
# ---------------------------------------------------------------------------

_SCORE_FIELDS = [
    "total_score",
    "pace",
    "consistency",
    "execution",
    "robustness",
    "adaptation",
]


def compare_scores(
    local: dict,
    saas: dict,
    tolerance: float = 0.1,
) -> dict:
    """Compare score pillars within *tolerance*.

    Fields checked: total_score, pace, consistency, execution, robustness,
    adaptation.

    Returns::

        {"pass": bool, "failures": [{"field", "local", "saas", "delta", "tolerance"}]}
    """
    failures: list[dict] = []
    for field in _SCORE_FIELDS:
        fail = _compare_field(
            field,
            local.get(field),
            saas.get(field),
            tolerance,
        )
        if fail is not None:
            failures.append(fail)
    return {"pass": len(failures) == 0, "failures": failures}


# ---------------------------------------------------------------------------
# Lap comparison
# ---------------------------------------------------------------------------

def compare_laps(
    local: list,
    saas: list,
    time_tolerance_ms: float = 5,
) -> dict:
    """Compare lap times and best-lap index.

    Each element is expected to have at least ``lap_time_s`` (or
    ``lap_time_ms``) and ``is_best`` (or ``best_lap``).

    * Lap counts must match exactly.
    * Best-lap index must match exactly.
    * Individual lap times must be within *time_tolerance_ms* milliseconds.

    Returns::

        {"pass": bool, "failures": [...]}
    """
    failures: list[dict] = []

    # --- count check ---
    if len(local) != len(saas):
        failures.append({
            "field": "lap_count",
            "local": len(local),
            "saas": len(saas),
            "delta": abs(len(local) - len(saas)),
            "tolerance": 0,
        })
        return {"pass": False, "failures": failures}

    # --- helper to get time in ms ---
    def _lap_ms(lap: dict) -> float | None:
        if "lap_time_ms" in lap and lap["lap_time_ms"] is not None:
            return float(lap["lap_time_ms"])
        if "lap_time_s" in lap and lap["lap_time_s"] is not None:
            return float(lap["lap_time_s"]) * 1000.0
        return None

    def _is_best(lap: dict) -> bool:
        return bool(lap.get("is_best") or lap.get("best_lap"))

    # --- best-lap index ---
    local_best = [i for i, lap in enumerate(local) if _is_best(lap)]
    saas_best = [i for i, lap in enumerate(saas) if _is_best(lap)]
    if local_best != saas_best:
        failures.append({
            "field": "best_lap_index",
            "local": local_best,
            "saas": saas_best,
            "delta": None,
            "tolerance": "exact",
        })

    # --- per-lap time comparison ---
    for idx, (ll, sl) in enumerate(zip(local, saas)):
        lt = _lap_ms(ll)
        st = _lap_ms(sl)
        if lt is None or st is None:
            failures.append({
                "field": f"lap[{idx}].time",
                "local": lt,
                "saas": st,
                "delta": None,
                "tolerance": time_tolerance_ms,
                "reason": "missing_value",
            })
            continue
        delta = abs(lt - st)
        if delta > time_tolerance_ms:
            failures.append({
                "field": f"lap[{idx}].time",
                "local": lt,
                "saas": st,
                "delta": round(delta, 4),
                "tolerance": time_tolerance_ms,
            })

    return {"pass": len(failures) == 0, "failures": failures}


# ---------------------------------------------------------------------------
# Corner comparison
# ---------------------------------------------------------------------------

_CORNER_BOUNDARY_FIELDS = ["s_start", "s_end", "s_apex"]


def compare_corners(
    local: list,
    saas: list,
    boundary_tolerance_m: float = 1.0,
) -> dict:
    """Compare corner boundaries (s_start, s_end, s_apex) within *boundary_tolerance_m*.

    Corner lists must have the same length.  Each element is a dict with at
    least ``s_start``, ``s_end``, ``s_apex``.

    Returns::

        {"pass": bool, "failures": [...]}
    """
    failures: list[dict] = []

    if len(local) != len(saas):
        failures.append({
            "field": "corner_count",
            "local": len(local),
            "saas": len(saas),
            "delta": abs(len(local) - len(saas)),
            "tolerance": 0,
        })
        return {"pass": False, "failures": failures}

    for idx, (lc, sc) in enumerate(zip(local, saas)):
        for bf in _CORNER_BOUNDARY_FIELDS:
            fail = _compare_field(
                f"corner[{idx}].{bf}",
                lc.get(bf),
                sc.get(bf),
                boundary_tolerance_m,
            )
            if fail is not None:
                failures.append(fail)

    return {"pass": len(failures) == 0, "failures": failures}


# ---------------------------------------------------------------------------
# Sector comparison
# ---------------------------------------------------------------------------

_SECTOR_TIME_FIELDS = ["best_time_s", "mean_time_s"]


def compare_sectors(
    local: list,
    saas: list,
    time_tolerance_s: float = 0.001,
) -> dict:
    """Compare sector times within *time_tolerance_s*.

    Each element is expected to have ``best_time_s`` and ``mean_time_s``
    (or equivalently ``best_s`` / ``mean_s``).

    Returns::

        {"pass": bool, "failures": [...]}
    """
    failures: list[dict] = []

    if len(local) != len(saas):
        failures.append({
            "field": "sector_count",
            "local": len(local),
            "saas": len(saas),
            "delta": abs(len(local) - len(saas)),
            "tolerance": 0,
        })
        return {"pass": False, "failures": failures}

    def _get_sector_field(sector: dict, primary: str, alt: str) -> Any:
        v = sector.get(primary)
        if v is not None:
            return v
        return sector.get(alt)

    for idx, (ls, ss) in enumerate(zip(local, saas)):
        for primary, alt in [("best_time_s", "best_s"), ("mean_time_s", "mean_s")]:
            fail = _compare_field(
                f"sector[{idx}].{primary}",
                _get_sector_field(ls, primary, alt),
                _get_sector_field(ss, primary, alt),
                time_tolerance_s,
            )
            if fail is not None:
                failures.append(fail)

    return {"pass": len(failures) == 0, "failures": failures}


# ---------------------------------------------------------------------------
# SaaS data fetcher (side-effecting — NOT tested in unit tests)
# ---------------------------------------------------------------------------

_ENDPOINTS = [
    ("detail", "/api/v1/sessions/{sid}"),
    ("laps", "/api/v1/sessions/{sid}/laps"),
    ("scores", "/api/v1/sessions/{sid}/scores"),
    ("corners", "/api/v1/sessions/{sid}/corners"),
    ("speed_trace", "/api/v1/sessions/{sid}/speed-trace"),
    ("gps_trace", "/api/v1/sessions/{sid}/gps-trace"),
    ("gg_data", "/api/v1/sessions/{sid}/gg-data"),
    ("sectors", "/api/v1/sessions/{sid}/compare/sectors"),
]


def fetch_saas_data(
    api_url: str,
    session_id: str,
    token: str | None = None,
) -> dict[str, Any]:
    """Call 8 SaaS endpoints and return a dict keyed by endpoint name.

    Each value is the parsed JSON response body (or an error dict if the
    request failed).
    """
    import requests  # lazy import — not needed for pure comparison functions

    base = api_url.rstrip("/")
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results: dict[str, Any] = {}
    for name, path_tmpl in _ENDPOINTS:
        url = base + path_tmpl.format(sid=session_id)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            results[name] = resp.json()
        except Exception as exc:
            results[name] = {"_error": str(exc), "_url": url}
    return results


# ---------------------------------------------------------------------------
# Baseline dump
# ---------------------------------------------------------------------------

def dump_baseline(data: dict, output_dir: str | Path) -> list[Path]:
    """Write each key of *data* as a separate JSON file in *output_dir*.

    Returns a list of paths written.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for key, value in data.items():
        p = out / f"{key}.json"
        p.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        written.append(p)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Parity harness — compare local vs SaaS telemetry output",
    )
    p.add_argument("--session-id", required=True, help="Session ID to compare")
    p.add_argument("--api-url", required=True, help="SaaS API base URL")
    p.add_argument("--token", default=None, help="Bearer token for auth")
    p.add_argument("--dump", action="store_true", help="Dump responses to baseline files")
    p.add_argument(
        "--baseline-dir",
        default="audit/baselines",
        help="Directory for baseline JSON dumps (default: audit/baselines)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    print(f"Fetching SaaS data for session {args.session_id} from {args.api_url} ...")
    saas = fetch_saas_data(args.api_url, args.session_id, args.token)

    errors = {k: v for k, v in saas.items() if isinstance(v, dict) and "_error" in v}
    if errors:
        print(f"\nWARN: {len(errors)} endpoint(s) returned errors:")
        for k, v in errors.items():
            print(f"  {k}: {v['_error']}")

    if args.dump:
        written = dump_baseline(saas, args.baseline_dir)
        print(f"\nDumped {len(written)} baseline file(s) to {args.baseline_dir}/")
        for p in written:
            print(f"  {p}")

    # Print summary
    ok_count = sum(1 for v in saas.values() if not (isinstance(v, dict) and "_error" in v))
    print(f"\nFetched {ok_count}/{len(saas)} endpoints successfully.")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
