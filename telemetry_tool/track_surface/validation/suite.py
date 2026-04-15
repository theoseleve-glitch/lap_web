"""Top-level orchestrator — runs the validation suite over a manifest.

Two-pass design (frozen and adaptive) is the load-bearing rule.

  Pass 1 (default): frozen-parameter transfer
      Runs every dataset with PipelineConfig defaults — adaptation flags off.
      This is the honest measurement of how the calibrated stack transfers.

  Pass 2 (opt-in via pass_2_adaptive=True):
      Re-runs every dataset with allow_roll_compliance_fit and
      allow_tire_d_scale_fit ON. Writes to a SEPARATE output directory
      so frozen results are never overwritten.

Outputs per pass:
  - {pass_dir}/sessions/{dataset_id}.json   (per-session full records)
  - {pass_dir}/aggregate.md                 (cross-session comparison)
  - {pass_dir}/suite_summary.json           (machine-readable headline)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_surface.validation.classifier import (
    WarningSeverity,
    classify_warnings,
    overall_severity,
)
from track_surface.validation.harness import (
    PipelineConfig,
    PipelineResult,
    run_pipeline,
)
from track_surface.validation.manifest import (
    DatasetEntry,
    ValidationManifest,
    load_manifest,
)
from track_surface.validation.metrics import SessionMetrics, compute_metrics
from track_surface.validation.reporter import (
    write_aggregate_report,
    write_session_report,
)

logger = logging.getLogger(__name__)


# ── Suite result ─────────────────────────────────────────────


@dataclass
class SuiteResult:
    """Top-level result of a single validation pass."""
    pass_label: str
    n_total: int
    n_pass: int
    n_warn: int
    n_fail: int
    out_dir: Path
    sessions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """The suite "succeeded" if at least one session ran. Caller
        decides whether n_fail > 0 means the calibration is broken or
        whether warnings are acceptable."""
        return self.n_total > 0


# ── Per-pass execution ───────────────────────────────────────


def _run_one_pass(
    *,
    manifest: ValidationManifest,
    out_dir: Path,
    config: PipelineConfig,
    pass_label: str,
    only_datasets: list[str] | None,
    skip_missing: bool,
) -> SuiteResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir = out_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    entries = manifest.filter(only_datasets)

    rows: list[dict[str, Any]] = []
    n_pass = n_warn = n_fail = 0

    for entry in entries:
        if not entry.file_exists:
            if skip_missing:
                logger.warning(
                    "Skipping %s — IBT file missing: %s",
                    entry.id, entry.ibt_path,
                )
                continue
            raise FileNotFoundError(
                f"Dataset {entry.id!r}: IBT file not found at {entry.ibt_path}"
            )

        logger.info("[%s] Running %s", pass_label, entry.id)
        result = run_pipeline(entry, config)
        metrics = compute_metrics(result, entry)
        warnings = classify_warnings(metrics, entry, result=result)
        sev = overall_severity(warnings)

        write_session_report(
            sessions_dir / f"{entry.id}.json",
            entry=entry, result=result, metrics=metrics,
            warnings=warnings, pass_label=pass_label,
        )

        rows.append({
            "entry": entry,
            "result": result,
            "metrics": metrics,
            "warnings": warnings,
            "overall": sev,
        })

        if sev == WarningSeverity.OK:
            n_pass += 1
        elif sev == WarningSeverity.WARN:
            n_warn += 1
        else:
            n_fail += 1

    # Aggregate report (markdown)
    write_aggregate_report(
        out_dir / "aggregate.md",
        suite_results=rows,
        pass_label=pass_label,
    )

    # Machine-readable summary
    summary_payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pass": pass_label,
        "n_total": len(rows),
        "n_pass": n_pass,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "headline_per_session": [
            {
                "dataset_id": r["metrics"].dataset_id,
                "group": r["metrics"].group,
                "severity": r["overall"].value,
                "lambda_median": r["metrics"].lambda_median,
                "coverage_pct": r["metrics"].coverage_pct,
                "racing_line_lift": r["metrics"].racing_line_lift,
                "n_warnings": len(r["warnings"]),
            }
            for r in rows
        ],
    }
    with open(out_dir / "suite_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    return SuiteResult(
        pass_label=pass_label,
        n_total=len(rows),
        n_pass=n_pass,
        n_warn=n_warn,
        n_fail=n_fail,
        out_dir=out_dir,
        sessions=rows,
    )


# ── Public entry point ───────────────────────────────────────


def run_validation_suite(
    manifest_path: Path | str,
    out_dir: Path | str,
    *,
    pass_2_adaptive: bool = False,
    only_datasets: list[str] | None = None,
    skip_missing: bool = True,
    calibration_registry_path: Path | str | None = None,
    accumulator_dir: Path | str | None = None,
    use_multi_criterion_gate: bool = True,
) -> dict[str, SuiteResult]:
    """Run the validation suite.

    Parameters
    ----------
    manifest_path   : path to the JSON manifest
    out_dir         : top-level output directory; sub-dirs created per pass
    pass_2_adaptive : if True, also run an adaptation-sensitivity pass
                      to a SEPARATE output dir
    only_datasets   : optional id allowlist (default: all)
    skip_missing    : skip dataset entries whose .ibt file is absent
                      (default True so the suite tolerates partial setups)

    Returns
    -------
    dict mapping pass_label -> SuiteResult
    """
    manifest_path = Path(manifest_path)
    out_dir = Path(out_dir)
    manifest = load_manifest(manifest_path)

    results: dict[str, SuiteResult] = {}

    # ── Pass 1: frozen ───────────────────────────────────────
    frozen_dir = out_dir / "pass_1_frozen"
    frozen_config = PipelineConfig(
        allow_roll_compliance_fit=False,
        allow_tire_d_scale_fit=False,
        calibration_registry_path=str(calibration_registry_path) if calibration_registry_path else None,
        accumulator_dir=str(accumulator_dir) if accumulator_dir else None,
        use_multi_criterion_gate=use_multi_criterion_gate,
    )
    results["frozen"] = _run_one_pass(
        manifest=manifest,
        out_dir=frozen_dir,
        config=frozen_config,
        pass_label="frozen",
        only_datasets=only_datasets,
        skip_missing=skip_missing,
    )

    # ── Pass 2: adaptive (optional) ──────────────────────────
    if pass_2_adaptive:
        adaptive_dir = out_dir / "pass_2_adaptive"
        adaptive_config = PipelineConfig(
            allow_roll_compliance_fit=True,
            allow_tire_d_scale_fit=True,
            calibration_registry_path=str(calibration_registry_path) if calibration_registry_path else None,
            accumulator_dir=str(accumulator_dir) if accumulator_dir else None,
            use_multi_criterion_gate=use_multi_criterion_gate,
        )
        results["adaptive"] = _run_one_pass(
            manifest=manifest,
            out_dir=adaptive_dir,
            config=adaptive_config,
            pass_label="adaptive",
            only_datasets=only_datasets,
            skip_missing=skip_missing,
        )

    return results
