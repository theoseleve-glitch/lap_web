"""Lap Oracle final report generator.

Produces a markdown report summarising the oracle run: vehicles
identified, tracks extracted, solutions computed, and job breakdown.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake

logger = logging.getLogger(__name__)


def generate_final_report(lake: DataLake, config: OracleConfig) -> Path:
    """Generate a markdown report summarising the oracle run.

    Parameters
    ----------
    lake : DataLake
        The data lake with all job/asset state.
    config : OracleConfig
        Runtime configuration (used for data_dir).

    Returns
    -------
    Path
        Path to the written ``final_report.md``.
    """
    summary: Dict = lake.get_progress_summary()

    lines = [
        "# Lap Oracle -- Final Report",
        "",
        "## Summary",
        "",
        f"- Solutions computed: {summary['solutions']}",
        f"- Vehicle models: {summary['vehicles']}",
        f"- Track models: {summary['tracks']}",
        "",
        "## Job Breakdown",
        "",
    ]

    jobs: Dict = summary.get("jobs", {})
    if jobs:
        for jt, statuses in sorted(jobs.items()):
            parts = [f"{st}: {cnt}" for st, cnt in sorted(statuses.items())]
            lines.append(f"- **{jt}**: {', '.join(parts)}")
    else:
        lines.append("- No jobs recorded.")

    # -- Vehicles ----------------------------------------------------------
    lines.append("")
    lines.append("## Vehicles Identified")
    lines.append("")
    vehicles = lake.list_vehicles()
    if vehicles:
        for sim, car in vehicles:
            lines.append(f"- [{sim}] {car}")
    else:
        lines.append("- None.")

    # -- Tracks ------------------------------------------------------------
    lines.append("")
    lines.append("## Tracks Extracted")
    lines.append("")
    tracks = lake.list_tracks()
    if tracks:
        for sim, track in tracks:
            lines.append(f"- [{sim}] {track}")
    else:
        lines.append("- None.")

    lines.append("")

    report_path = config.data_dir / "reports" / "final_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(
        "Final report: %d vehicles, %d tracks, %d solutions",
        summary["vehicles"], summary["tracks"], summary["solutions"],
    )
    return report_path
