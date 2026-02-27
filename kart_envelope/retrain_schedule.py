#!/usr/bin/env python3
"""
retrain_schedule.py
-------------------
Builds manual retrain job suggestions from drift trigger history.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_retrain_jobs(
    trigger_path: Path,
    output_path: Path,
    *,
    min_drift_sigma: float = 2.5,
) -> dict[str, Any]:
    if not trigger_path.exists():
        payload = {"jobs": [], "reason": "trigger file missing"}
        _write_json(output_path, payload)
        return payload

    raw = _read_json_list(trigger_path)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw:
        drift = _to_float(row.get("drift_sigma"))
        if drift < float(min_drift_sigma):
            continue
        key = (str(row.get("track_name") or ""), str(row.get("kart_id") or ""))
        grouped.setdefault(key, []).append(dict(row))

    jobs: list[dict[str, Any]] = []
    for (track, kart), rows in grouped.items():
        rows = sorted(rows, key=lambda r: _to_float(r.get("drift_sigma")), reverse=True)
        top = rows[0]
        jobs.append({
            "track_name": track,
            "kart_id": kart,
            "priority_drift_sigma": _to_float(top.get("drift_sigma")),
            "trigger_count": int(len(rows)),
            "latest_session_file": top.get("session_file"),
            "latest_condition_label": top.get("condition_label"),
            "recommended_command": (
                f"python -m kart_envelope.train_offline --metadata data/session_metadata.csv --three-tier"
            ),
        })

    payload = {
        "min_drift_sigma": float(min_drift_sigma),
        "jobs": sorted(jobs, key=lambda j: float(j["priority_drift_sigma"]), reverse=True),
    }
    _write_json(output_path, payload)
    return payload


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _to_float(v: Any) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return 0.0
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate retrain job suggestions from drift triggers.")
    parser.add_argument(
        "--trigger-file",
        type=Path,
        default=Path("data") / "models" / "kart_envelope" / "retrain_triggers.json",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=Path("data") / "models" / "kart_envelope" / "retrain_jobs.json",
    )
    parser.add_argument("--min-drift-sigma", type=float, default=2.5)
    args = parser.parse_args()

    payload = build_retrain_jobs(
        trigger_path=args.trigger_file,
        output_path=args.output_file,
        min_drift_sigma=args.min_drift_sigma,
    )
    logger.info("Retrain job suggestions written to %s (%d jobs)", args.output_file, len(payload.get("jobs", [])))


if __name__ == "__main__":
    main()
