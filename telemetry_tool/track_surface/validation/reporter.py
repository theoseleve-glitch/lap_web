"""Report writer — JSON per-session + Markdown aggregate.

Two outputs:

  Per-session JSON  : full machine-readable record (one file per dataset)
  Aggregate Markdown: human-readable comparison table (one file per pass)

Both formats are write-only — the harness produces them, downstream
consumers parse them. The JSON is the source of truth; the Markdown
is for humans skimming the suite report.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_surface.validation.classifier import (
    ValidationWarning,
    WarningSeverity,
    overall_severity,
)
from track_surface.validation.harness import PipelineResult
from track_surface.validation.manifest import DatasetEntry
from track_surface.validation.metrics import SessionMetrics


# ── Per-session JSON ─────────────────────────────────────────


def _result_to_dict(result: PipelineResult) -> dict[str, Any]:
    """Convert a PipelineResult into a JSON-safe dict.

    Strips numpy types / converts tuples to lists.
    """
    d = asdict(result)
    # Tuples in dataclass fields render fine, but planner_sectors_most_tightened
    # is list[tuple] which json.dumps handles as nested lists — fine.
    # bucket_fallback_distribution has int keys — JSON wants strings.
    d["bucket_fallback_distribution"] = {
        str(k): int(v) for k, v in result.bucket_fallback_distribution.items()
    }
    d["lap_lambdas"] = {str(k): float(v) for k, v in result.lap_lambdas.items()}
    d["lap_times_s"] = {str(k): float(v) for k, v in result.lap_times_s.items()}
    return d


def write_session_report(
    out_path: Path,
    *,
    entry: DatasetEntry,
    result: PipelineResult,
    metrics: SessionMetrics,
    warnings: list[ValidationWarning],
    pass_label: str = "frozen",
) -> None:
    """Write one full per-session JSON report.

    Layout
    ------
    {
      "schema_version": 1,
      "generated_at": "ISO-8601",
      "pass": "frozen" | "adaptive",
      "entry": { id, group, ibt_path, track, vehicle, expected, ... },
      "result": { full PipelineResult contents },
      "metrics": { ... SessionMetrics ... },
      "warnings": [ ... ],
      "overall_severity": "ok" | "warn" | "fail"
    }
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pass": pass_label,
        "entry": {
            "id": entry.id,
            "ibt_path": entry.ibt_path,
            "group": entry.group,
            "track": asdict(entry.track),
            "vehicle": asdict(entry.vehicle),
            "session": asdict(entry.session),
            "expected": asdict(entry.expected),
        },
        "result": _result_to_dict(result),
        "metrics": metrics.to_dict(),
        "warnings": [w.to_dict() for w in warnings],
        "overall_severity": overall_severity(warnings).value,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=_json_safe)


def _json_safe(o: Any) -> Any:
    """Fallback for JSON-incompatible types (tuples, numpy scalars)."""
    if isinstance(o, tuple):
        return list(o)
    if hasattr(o, "item"):  # numpy scalar
        return o.item()
    return str(o)


# ── Aggregate Markdown ───────────────────────────────────────


def write_aggregate_report(
    out_path: Path,
    *,
    suite_results: list[dict[str, Any]],
    pass_label: str = "frozen",
    title_suffix: str = "",
) -> None:
    """Write a human-readable comparison report across all sessions.

    Each row in `suite_results` is a dict with at least:
      - entry      : DatasetEntry
      - metrics    : SessionMetrics
      - warnings   : list[ValidationWarning]
      - overall    : WarningSeverity
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# Cross-Track Validation Report — {pass_label}{title_suffix}")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"Datasets: {len(suite_results)}")
    lines.append("")

    # ── Headline summary ─────────────────────────────────────
    n_pass = sum(1 for r in suite_results if r["overall"] == WarningSeverity.OK)
    n_warn = sum(1 for r in suite_results if r["overall"] == WarningSeverity.WARN)
    n_fail = sum(1 for r in suite_results if r["overall"] == WarningSeverity.FAIL)
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- PASS: {n_pass}")
    lines.append(f"- WARN: {n_warn}")
    lines.append(f"- FAIL: {n_fail}")
    lines.append("")

    # ── Comparison table ─────────────────────────────────────
    lines.append("## Comparison")
    lines.append("")
    lines.append(
        "| Status | Dataset | Group | Track | Vehicle | λ med | λ p5/p95 | "
        "Cov% | RaceLine Δ | Robust Δ | Lap σ | FB%(cur) | FB%(acc) | Δ |"
    )
    lines.append(
        "|--------|---------|-------|-------|---------|-------|----------|"
        "------|------------|----------|-------|---------|---------|---|"
    )
    for r in suite_results:
        m: SessionMetrics = r["metrics"]
        sev: WarningSeverity = r["overall"]
        sev_str = {
            WarningSeverity.OK: "PASS",
            WarningSeverity.WARN: "WARN",
            WarningSeverity.FAIL: "FAIL",
        }[sev]
        acc_fb = (
            f"{m.accumulated_fallback_depth_2_pct:.1f}"
            if m.accumulated_fallback_depth_2_pct is not None else "—"
        )
        delta = (
            f"{m.fallback_reduction_pct:+.1f}"
            if m.fallback_reduction_pct is not None else "—"
        )
        lines.append(
            f"| {sev_str} | `{m.dataset_id}` | {m.group} | "
            f"{m.track_name} | {m.vehicle_name} | "
            f"{m.lambda_median:.3f} | "
            f"{m.lambda_p5:.2f}/{m.lambda_p95:.2f} | "
            f"{m.coverage_pct:.1f} | "
            f"{m.racing_line_lift:+.3f} | "
            f"{m.planner_robust_tightening:.3f} | "
            f"{m.lap_to_lap_std:.3f} | "
            f"{m.fallback_depth_2_pct:.1f} | {acc_fb} | {delta} |"
        )
    lines.append("")
    if any(r["metrics"].accumulator_key for r in suite_results):
        lines.append(
            "_FB%(cur) = bucket fallback depth-2 from current session only; "
            "FB%(acc) = same after layered query against accumulator; "
            "Δ = reduction (positive = better)._"
        )
        lines.append("")

    # ── Warnings detail per dataset ──────────────────────────
    lines.append("## Warnings")
    lines.append("")
    for r in suite_results:
        m: SessionMetrics = r["metrics"]
        warnings: list[ValidationWarning] = r["warnings"]
        if not warnings:
            continue
        lines.append(f"### `{m.dataset_id}` ({m.track_name} / {m.vehicle_name})")
        lines.append("")
        for w in warnings:
            sev_label = w.severity.value.upper()
            lines.append(
                f"- **{sev_label}** — {w.category} — {w.message}  "
                f"(`{w.metric}={w.value:.3f}` vs `{w.threshold:.3f}`)"
            )
        lines.append("")

    # ── Top regression causes ────────────────────────────────
    lines.append("## Top Regression Causes")
    lines.append("")
    cause_counts: dict[str, int] = {}
    for r in suite_results:
        for w in r["warnings"]:
            if w.severity in (WarningSeverity.WARN, WarningSeverity.FAIL):
                cause_counts[w.category] = cause_counts.get(w.category, 0) + 1
    if not cause_counts:
        lines.append("_(none — all sessions clean)_")
    else:
        ranked = sorted(cause_counts.items(), key=lambda kv: -kv[1])
        for cause, count in ranked:
            lines.append(f"- `{cause}` — {count} occurrence(s)")
    lines.append("")

    # ── Per-group summary ────────────────────────────────────
    lines.append("## Per-Group Summary")
    lines.append("")
    by_group: dict[str, list] = {}
    for r in suite_results:
        m: SessionMetrics = r["metrics"]
        by_group.setdefault(m.group, []).append(r)
    for group, group_rows in sorted(by_group.items()):
        if not group_rows:
            continue
        lambdas = [row["metrics"].lambda_median for row in group_rows]
        avg_lambda = sum(lambdas) / len(lambdas)
        lines.append(
            f"- **{group}** ({len(group_rows)} sessions) — "
            f"mean λ median = {avg_lambda:.3f}"
        )
    lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
