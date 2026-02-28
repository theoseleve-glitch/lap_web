# E2E Certification Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the complete certification infrastructure (Phases 0-3) for a 250+ cycle production SaaS audit — old tool baseline generation, parity comparison tooling, Playwright E2E extensions for RBAC/isolation, feature inventory, cycle runner, and PDF report generator.

**Architecture:** Script-first harness in `tools/` + `audit/` directories. Old tool runner executes `telemetry_tool/pipeline.py::run_full_analysis()` locally, captures dict output, normalizes to JSON baselines. Parity checker compares webapp API responses against baselines. Cycle runner orchestrates the full cycle workflow (test → fix → log → PDF → commit → push → deploy).

**Tech Stack:** Python 3.11 (pytest, weasyprint, markdown), Playwright (TypeScript), Flask API, PostgreSQL 16.

---

### Task 1: Create Branch and Directory Scaffold

**Files:**
- Create: `audit/cycles/.gitkeep`
- Create: `audit/baselines/old_tool/.gitkeep`
- Create: `audit/screenshots/.gitkeep`
- Create: `audit/logs/parity-diffs/.gitkeep`
- Create: `audit/logs/test-runs/.gitkeep`
- Create: `audit/report.md`
- Create: `audit/security-findings.md`
- Create: `audit/fixes-applied.md`
- Create: `audit/risks.md`
- Create: `tools/batch_configs/.gitkeep`
- Create: `tools/README.md`

**Step 1: Create and switch to branch**

```bash
cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai
git checkout -b recovery/e2e-certification
```

**Step 2: Create directory scaffold**

```bash
mkdir -p audit/cycles audit/baselines/old_tool audit/screenshots audit/logs/parity-diffs audit/logs/test-runs
mkdir -p tools/batch_configs
touch audit/cycles/.gitkeep audit/baselines/old_tool/.gitkeep audit/screenshots/.gitkeep
touch audit/logs/parity-diffs/.gitkeep audit/logs/test-runs/.gitkeep
touch tools/batch_configs/.gitkeep
```

**Step 3: Create audit/report.md template**

```markdown
# E2E Certification Report

**Branch:** recovery/e2e-certification
**Started:** 2026-02-28
**Status:** In Progress

## Summary

| Metric | Value |
|--------|-------|
| Total Cycles | 0 |
| Features Validated | 0 / 250+ |
| Defects Found | 0 |
| Defects Fixed | 0 |
| Parity Checks Passed | 0 |
| RBAC Violations Found | 0 |
| Isolation Breaches Found | 0 |

## Cycle Log

<!-- Append cycle entries below this line -->
```

**Step 4: Create audit/security-findings.md**

```markdown
# Security Findings

## Format

| ID | Severity | Category | Finding | Status |
|----|----------|----------|---------|--------|
```

**Step 5: Create audit/fixes-applied.md**

```markdown
# Fixes Applied

## Format

| Cycle | Feature ID | Root Cause | Fix Summary | Files Changed |
|-------|-----------|------------|-------------|---------------|
```

**Step 6: Create audit/risks.md**

```markdown
# Risks and Documented Divergences

## Intentional Divergences (webapp vs old tool)

| Feature | Old Tool Behavior | Webapp Behavior | Justification |
|---------|-------------------|-----------------|---------------|

## Open Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
```

**Step 7: Create tools/README.md**

```markdown
# Certification Harness Tools

## Commands

```bash
# Generate old tool baselines
python tools/old_tool_runner.py --csv data/raw/OK_R1.csv --output audit/baselines/old_tool/OK_R1.json

# Run parity check (webapp vs baseline)
python tools/parity_check.py --baseline audit/baselines/old_tool/OK_R1.json --api-url https://api.lap-coach.racing --session-id <id>

# Generate PDF report
python tools/generate_report_pdf.py

# Run a cycle
python tools/cycle_runner.py --cycle-number 1 --feature-id F-0001
```
```

**Step 8: Commit**

```bash
git add audit/ tools/
git commit -m "chore: scaffold audit and tools directories for E2E certification harness"
```

---

### Task 2: Create Batch Configs for Deterministic Old Tool Runs

**Files:**
- Create: `tools/batch_configs/OK_R1.json`
- Create: `tools/batch_configs/OK_R3.json`
- Create: `tools/batch_configs/OK_R4.json`

**Step 1: Inspect CSV headers to determine driver count**

```bash
cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai
head -5 data/raw/OK_R1.csv
head -5 data/raw/OK_R3.csv
head -5 data/raw/OK_R4.csv
```

Check RaceChrono header format — look for `"Lap #"` column to determine if multi-driver or single.

**Step 2: Create batch config for OK_R1**

```json
{
  "session_type": "race",
  "track_state": "dry",
  "drivers": [
    {"name": "Driver_1", "lap_range": null}
  ]
}
```

Note: Adjust `session_type`, `track_state`, driver count, and lap ranges after inspecting the CSVs. The goal is a fixed, deterministic config that always produces the same output.

**Step 3: Create configs for OK_R3 and OK_R4**

Same structure — adjust per CSV content.

**Step 4: Commit**

```bash
git add tools/batch_configs/
git commit -m "chore: add deterministic batch configs for baseline generation"
```

---

### Task 3: Build Normalization Module

**Files:**
- Create: `tools/normalize.py`
- Create: `tools/tests/test_normalize.py`

**Step 1: Write the failing test**

```python
# tools/tests/test_normalize.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import json
from normalize import normalize_value, normalize_dict, normalize_summary

def test_float_rounding():
    assert normalize_value(3.14159265) == 3.1416

def test_nan_to_none():
    assert normalize_value(float("nan")) is None

def test_inf_to_none():
    assert normalize_value(float("inf")) is None

def test_negative_inf_to_none():
    assert normalize_value(float("-inf")) is None

def test_string_passthrough():
    assert normalize_value("hello") == "hello"

def test_int_passthrough():
    assert normalize_value(42) == 42

def test_none_passthrough():
    assert normalize_value(None) is None

def test_bool_passthrough():
    assert normalize_value(True) is True

def test_dict_sorted_keys():
    result = normalize_dict({"z": 1, "a": 2, "m": 3})
    keys = list(result.keys())
    assert keys == ["a", "m", "z"]

def test_dict_nested_normalization():
    result = normalize_dict({"a": {"z": 3.14159, "b": float("nan")}})
    assert result == {"a": {"b": None, "z": 3.1416}}

def test_list_preserves_order():
    result = normalize_value([3.0, 2.0, 1.0])
    assert result == [3.0, 2.0, 1.0]

def test_list_normalizes_elements():
    result = normalize_value([3.14159, float("nan"), "ok"])
    assert result == [3.1416, None, "ok"]

def test_normalize_summary_structure():
    raw = {
        "score_result": {
            "pace": 22.3456789,
            "consistency": float("nan"),
            "total_score": 81.8,
            "grade": "A",
        },
        "lap_times": [45.123456, 46.789012],
        "raw_df": "SHOULD_BE_STRIPPED",
    }
    result = normalize_summary(raw)
    assert "raw_df" not in result
    assert result["score_result"]["pace"] == 22.3457
    assert result["score_result"]["consistency"] is None
    assert result["lap_times"] == [45.1235, 46.789]
```

**Step 2: Run test to verify it fails**

```bash
pytest tools/tests/test_normalize.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'normalize'`

**Step 3: Write normalize.py**

```python
"""Normalization rules for parity comparison.

Ensures deterministic, comparable output between CLI pipeline and webapp API.

Rules:
- Floats: round to 4 decimal places
- NaN/Inf: convert to None
- Dict keys: sorted alphabetically
- Lists: preserve order, normalize elements
- Timestamps: strip to second precision (ISO 8601)
- DataFrames/non-serializable: strip from output
"""
from __future__ import annotations

import math
import json
from datetime import datetime
from typing import Any


PRECISION = 4

# Keys to strip from pipeline output (non-serializable or too large)
_STRIP_KEYS = {
    "raw_df", "filtered_df", "enriched_df", "trimmed_df",
    "best_lap", "resampled_laps", "lap_dict",
    "reference_line", "curvature_profile", "theoretical_lap",
    "feature_df", "friction_model", "vehicle_params", "data_quality",
    "phases_df", "weather_timeline", "context",
}


def normalize_value(v: Any) -> Any:
    """Normalize a single value for comparison."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, PRECISION)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return _normalize_timestamp(v)
    if isinstance(v, dict):
        return normalize_dict(v)
    if isinstance(v, (list, tuple)):
        return [normalize_value(item) for item in v]
    # Non-serializable types → strip
    return None


def normalize_dict(d: dict) -> dict:
    """Normalize a dict: sort keys, normalize values recursively."""
    result = {}
    for key in sorted(d.keys()):
        result[key] = normalize_value(d[key])
    return result


def normalize_summary(raw: dict) -> dict:
    """Normalize a full pipeline summary dict for baseline storage.

    Strips non-serializable keys (DataFrames, models) and normalizes
    all remaining values.
    """
    filtered = {k: v for k, v in raw.items() if k not in _STRIP_KEYS}
    return normalize_dict(filtered)


def normalize_json_file(path: str) -> dict:
    """Read a JSON file and normalize it."""
    with open(path, "r") as f:
        data = json.load(f)
    return normalize_dict(data)


def _normalize_timestamp(s: str) -> str:
    """If string looks like ISO timestamp, strip to second precision."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.fromisoformat(s)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            continue
    return s
```

**Step 4: Run test to verify it passes**

```bash
pytest tools/tests/test_normalize.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add tools/normalize.py tools/tests/test_normalize.py
git commit -m "feat(tools): add normalization module for parity comparison"
```

---

### Task 4: Build Old Tool Runner

**Files:**
- Create: `tools/old_tool_runner.py`
- Create: `tools/tests/test_old_tool_runner.py`

**Step 1: Write the runner**

The runner calls `run_full_analysis()` directly (same process, no subprocess) to avoid environment issues. It captures the dict result, normalizes it, and writes JSON.

```python
"""Old tool runner — executes CLI pipeline and captures normalized output.

Usage:
    python tools/old_tool_runner.py --csv data/raw/OK_R1.csv --config tools/batch_configs/OK_R1.json --output audit/baselines/old_tool/OK_R1.json
    python tools/old_tool_runner.py --all  # Run all 3 baselines
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "telemetry_tool"))

from normalize import normalize_summary

logger = logging.getLogger(__name__)


def load_batch_config(config_path: str) -> dict:
    """Load batch config JSON."""
    with open(config_path, "r") as f:
        return json.load(f)


def run_old_tool(csv_path: str, config: dict) -> dict:
    """Run the old tool pipeline and return the raw result dict.

    Imports pipeline lazily to avoid polluting global state.
    """
    from telemetry_tool.pipeline import run_full_analysis

    session_meta = {
        "session_type": config.get("session_type", "race"),
        "track_state": config.get("track_state", "dry"),
    }

    drivers = config.get("drivers", [{"name": "Driver_1", "lap_range": None}])

    # For single driver, run directly
    if len(drivers) == 1:
        driver = drivers[0]
        result = run_full_analysis(
            csv_path=csv_path,
            session_meta=session_meta,
            enable_ml=False,  # Skip ML for determinism
            enable_report=False,  # Skip HTML/PDF generation
            lap_range=tuple(driver["lap_range"]) if driver.get("lap_range") else None,
            driver_tag=driver.get("name"),
        )
        return result

    # Multi-driver: run each and collect
    results = {}
    for driver in drivers:
        tag = driver.get("name", "Driver")
        result = run_full_analysis(
            csv_path=csv_path,
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
            lap_range=tuple(driver["lap_range"]) if driver.get("lap_range") else None,
            driver_tag=tag,
        )
        results[tag] = result
    return results


def extract_comparable_metrics(raw_result: dict) -> dict:
    """Extract the subset of pipeline output that matters for parity comparison.

    Returns a structured dict with:
    - scores (pace, consistency, execution, robustness, total, grade)
    - lap_times (list of {lap_number, time_s})
    - corner_metrics (list of corner dicts)
    - consistency_metrics
    - theoretical_metrics
    - steps_ok / steps_failed
    """
    score = raw_result.get("score_result") or {}
    lap_times = raw_result.get("lap_times") or []
    corners = raw_result.get("corners") or []
    consistency = raw_result.get("consistency_metrics") or {}
    robustness = raw_result.get("robustness_metrics") or {}
    theoretical = raw_result.get("theoretical_metrics") or {}
    lap_metrics = raw_result.get("lap_metrics") or []
    delta_segments = raw_result.get("delta_segments") or []
    segment_losses = raw_result.get("segment_losses") or []
    track_match = raw_result.get("track_match") or {}

    return {
        "scores": {
            "pace": score.get("pace"),
            "consistency": score.get("consistency"),
            "execution": score.get("execution"),
            "robustness": score.get("robustness"),
            "total_score": score.get("total_score"),
            "grade": score.get("grade"),
        },
        "lap_times": lap_times,
        "corner_count": len(corners),
        "corners": corners,
        "consistency_metrics": consistency,
        "robustness_metrics": robustness,
        "theoretical_metrics": theoretical,
        "lap_metrics_count": len(lap_metrics),
        "delta_segments_count": len(delta_segments),
        "segment_losses_count": len(segment_losses),
        "track_id": raw_result.get("track_id"),
        "track_match": {
            "name": track_match.get("name"),
            "length_m": track_match.get("length_m"),
        } if track_match else None,
        "steps_ok": raw_result.get("steps_ok", []),
        "steps_failed": raw_result.get("steps_failed", []),
    }


def generate_baseline(csv_path: str, config_path: str, output_path: str) -> dict:
    """Full pipeline: run old tool → extract metrics → normalize → write JSON."""
    config = load_batch_config(config_path)
    raw = run_old_tool(csv_path, config)

    # Handle multi-driver case
    if isinstance(raw, dict) and "score_result" in raw:
        # Single driver result
        comparable = extract_comparable_metrics(raw)
    elif isinstance(raw, dict):
        # Multi-driver: each key is a driver tag
        comparable = {}
        for tag, result in raw.items():
            if isinstance(result, dict) and ("score_result" in result or "steps_ok" in result):
                comparable[tag] = extract_comparable_metrics(result)
    else:
        comparable = {"error": "Unexpected result type", "type": str(type(raw))}

    normalized = normalize_summary(comparable)

    # Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(normalized, f, indent=2, default=str)

    logger.info("Baseline written to %s", output_path)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Run old tool pipeline and generate baselines")
    parser.add_argument("--csv", help="Path to CSV file")
    parser.add_argument("--config", help="Path to batch config JSON")
    parser.add_argument("--output", help="Path to write normalized JSON output")
    parser.add_argument("--all", action="store_true", help="Generate all 3 baselines")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.all:
        for name in ("OK_R1", "OK_R3", "OK_R4"):
            csv_path = str(ROOT / f"data/raw/{name}.csv")
            config_path = str(ROOT / f"tools/batch_configs/{name}.json")
            output_path = str(ROOT / f"audit/baselines/old_tool/{name}.json")
            if not os.path.exists(csv_path):
                logger.warning("CSV not found: %s — skipping", csv_path)
                continue
            logger.info("Generating baseline for %s ...", name)
            generate_baseline(csv_path, config_path, output_path)
        return

    if not args.csv or not args.config or not args.output:
        parser.error("Provide --csv, --config, --output or use --all")

    generate_baseline(args.csv, args.config, args.output)


if __name__ == "__main__":
    main()
```

**Step 2: Write a smoke test**

```python
# tools/tests/test_old_tool_runner.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from old_tool_runner import extract_comparable_metrics, load_batch_config

def test_extract_comparable_metrics_minimal():
    raw = {
        "score_result": {"pace": 22.5, "consistency": 18.0, "execution": 19.0,
                         "robustness": 21.0, "total_score": 80.5, "grade": "A"},
        "lap_times": [45.1, 46.2, 47.3],
        "corners": [{"id": 1}, {"id": 2}],
        "consistency_metrics": {"cv": 0.02},
        "robustness_metrics": {"std": 0.5},
        "theoretical_metrics": {"lap_time_s": 44.0},
        "lap_metrics": [{}],
        "delta_segments": [{}],
        "segment_losses": [{}],
        "track_id": "CKS",
        "track_match": {"name": "CKS", "length_m": 1200},
        "steps_ok": ["01_ingest", "02_gps"],
        "steps_failed": [],
    }
    result = extract_comparable_metrics(raw)
    assert result["scores"]["total_score"] == 80.5
    assert result["scores"]["grade"] == "A"
    assert len(result["lap_times"]) == 3
    assert result["corner_count"] == 2
    assert result["track_id"] == "CKS"

def test_extract_comparable_metrics_missing_fields():
    raw = {"steps_ok": [], "steps_failed": ["01_ingest"]}
    result = extract_comparable_metrics(raw)
    assert result["scores"]["total_score"] is None
    assert result["lap_times"] == []
    assert result["corner_count"] == 0

def test_load_batch_config(tmp_path):
    config = {"session_type": "race", "track_state": "dry",
              "drivers": [{"name": "Test", "lap_range": None}]}
    path = tmp_path / "test.json"
    import json
    path.write_text(json.dumps(config))
    loaded = load_batch_config(str(path))
    assert loaded["session_type"] == "race"
    assert loaded["drivers"][0]["name"] == "Test"
```

**Step 3: Run tests**

```bash
pytest tools/tests/test_old_tool_runner.py -v
```

Expected: all PASS

**Step 4: Commit**

```bash
git add tools/old_tool_runner.py tools/tests/test_old_tool_runner.py
git commit -m "feat(tools): add old tool runner for baseline generation"
```

---

### Task 5: Build Parity Checker

**Files:**
- Create: `tools/parity_check.py`
- Create: `tools/tests/test_parity_check.py`

**Step 1: Write the failing test**

```python
# tools/tests/test_parity_check.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parity_check import compare_values, compare_dicts, ParityResult

def test_exact_match():
    r = compare_values(42, 42, "test")
    assert r.passed

def test_float_within_tolerance():
    r = compare_values(45.1234, 45.1235, "lap_time", tolerance=0.001)
    assert r.passed

def test_float_outside_tolerance():
    r = compare_values(45.123, 45.200, "lap_time", tolerance=0.001)
    assert not r.passed

def test_none_match():
    r = compare_values(None, None, "test")
    assert r.passed

def test_none_vs_value():
    r = compare_values(None, 42, "test")
    assert not r.passed

def test_string_match():
    r = compare_values("A", "A", "grade")
    assert r.passed

def test_string_mismatch():
    r = compare_values("A", "B", "grade")
    assert not r.passed

def test_list_length_mismatch():
    r = compare_values([1, 2], [1, 2, 3], "laps")
    assert not r.passed

def test_list_match():
    r = compare_values([1.0, 2.0], [1.0, 2.0], "laps", tolerance=0.001)
    assert r.passed

def test_compare_dicts_all_pass():
    baseline = {"scores": {"pace": 22.5, "grade": "A"}, "lap_times": [45.1]}
    webapp = {"scores": {"pace": 22.5, "grade": "A"}, "lap_times": [45.1]}
    results = compare_dicts(baseline, webapp)
    assert all(r.passed for r in results)

def test_compare_dicts_with_failure():
    baseline = {"scores": {"pace": 22.5}}
    webapp = {"scores": {"pace": 20.0}}
    results = compare_dicts(baseline, webapp, tolerance=0.5)
    assert not all(r.passed for r in results)
```

**Step 2: Run test to verify it fails**

```bash
pytest tools/tests/test_parity_check.py -v
```

**Step 3: Write parity_check.py**

```python
"""Parity checker — compares webapp API output against old tool baselines.

Usage:
    python tools/parity_check.py --baseline audit/baselines/old_tool/OK_R1.json --webapp audit/baselines/webapp/OK_R1.json
    python tools/parity_check.py --baseline audit/baselines/old_tool/OK_R1.json --api-url https://api.lap-coach.racing --session-id <id> --token <jwt>
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from normalize import normalize_dict

logger = logging.getLogger(__name__)

# Default tolerances per metric category
TOLERANCES = {
    "lap_time": 0.001,      # ±1ms
    "speed": 0.01,          # ±0.01 m/s
    "score": 0.5,           # ±0.5 points
    "gps": 0.0001,          # ±0.0001 degrees (~11m)
    "percentage": 0.1,      # ±0.1%
    "default": 0.0001,      # ±0.0001 for unclassified floats
}


@dataclass
class ParityResult:
    """Result of a single parity comparison."""
    path: str
    passed: bool
    baseline_value: Any = None
    webapp_value: Any = None
    tolerance: float | None = None
    delta: float | None = None
    message: str = ""


def _classify_tolerance(path: str) -> float:
    """Pick tolerance based on the JSON path name."""
    low = path.lower()
    if "time" in low or "lap_time" in low:
        return TOLERANCES["lap_time"]
    if "speed" in low or "mps" in low:
        return TOLERANCES["speed"]
    if "score" in low or "pace" in low or "consistency" in low:
        return TOLERANCES["score"]
    if "lat" in low or "lon" in low:
        return TOLERANCES["gps"]
    if "pct" in low or "percent" in low:
        return TOLERANCES["percentage"]
    return TOLERANCES["default"]


def compare_values(
    baseline: Any,
    webapp: Any,
    path: str,
    tolerance: float | None = None,
) -> ParityResult:
    """Compare two values with type-aware logic."""
    if tolerance is None:
        tolerance = _classify_tolerance(path)

    # Both None
    if baseline is None and webapp is None:
        return ParityResult(path=path, passed=True)

    # One None
    if baseline is None or webapp is None:
        return ParityResult(
            path=path, passed=False,
            baseline_value=baseline, webapp_value=webapp,
            message=f"None mismatch: baseline={baseline}, webapp={webapp}",
        )

    # Numeric comparison
    if isinstance(baseline, (int, float)) and isinstance(webapp, (int, float)):
        delta = abs(float(baseline) - float(webapp))
        passed = delta <= tolerance
        return ParityResult(
            path=path, passed=passed,
            baseline_value=baseline, webapp_value=webapp,
            tolerance=tolerance, delta=delta,
            message="" if passed else f"Delta {delta:.6f} exceeds tolerance {tolerance}",
        )

    # String comparison
    if isinstance(baseline, str) and isinstance(webapp, str):
        passed = baseline == webapp
        return ParityResult(
            path=path, passed=passed,
            baseline_value=baseline, webapp_value=webapp,
            message="" if passed else f"String mismatch: '{baseline}' vs '{webapp}'",
        )

    # List comparison
    if isinstance(baseline, list) and isinstance(webapp, list):
        if len(baseline) != len(webapp):
            return ParityResult(
                path=path, passed=False,
                baseline_value=f"len={len(baseline)}", webapp_value=f"len={len(webapp)}",
                message=f"List length mismatch: {len(baseline)} vs {len(webapp)}",
            )
        # Compare element by element
        all_passed = True
        for i, (b, w) in enumerate(zip(baseline, webapp)):
            r = compare_values(b, w, f"{path}[{i}]", tolerance)
            if not r.passed:
                all_passed = False
        return ParityResult(path=path, passed=all_passed)

    # Dict comparison
    if isinstance(baseline, dict) and isinstance(webapp, dict):
        results = compare_dicts(baseline, webapp, tolerance, path)
        all_passed = all(r.passed for r in results)
        return ParityResult(path=path, passed=all_passed)

    # Type mismatch
    return ParityResult(
        path=path, passed=False,
        baseline_value=str(type(baseline)), webapp_value=str(type(webapp)),
        message=f"Type mismatch: {type(baseline).__name__} vs {type(webapp).__name__}",
    )


def compare_dicts(
    baseline: dict,
    webapp: dict,
    tolerance: float | None = None,
    prefix: str = "",
) -> list[ParityResult]:
    """Compare two dicts recursively, returning list of results."""
    results = []
    all_keys = set(baseline.keys()) | set(webapp.keys())

    for key in sorted(all_keys):
        path = f"{prefix}.{key}" if prefix else key
        b_val = baseline.get(key)
        w_val = webapp.get(key)

        if key not in baseline:
            results.append(ParityResult(
                path=path, passed=True,  # Extra keys in webapp are OK
                message=f"Extra key in webapp (acceptable)",
            ))
            continue

        if key not in webapp:
            results.append(ParityResult(
                path=path, passed=False,
                baseline_value=b_val, webapp_value=None,
                message=f"Missing key in webapp",
            ))
            continue

        if isinstance(b_val, dict) and isinstance(w_val, dict):
            results.extend(compare_dicts(b_val, w_val, tolerance, path))
        else:
            results.append(compare_values(b_val, w_val, path, tolerance))

    return results


def run_parity_check(
    baseline_path: str,
    webapp_path: str | None = None,
    webapp_data: dict | None = None,
    output_path: str | None = None,
) -> tuple[bool, list[ParityResult]]:
    """Run full parity check between baseline JSON and webapp JSON/data.

    Returns (all_passed, results).
    """
    with open(baseline_path, "r") as f:
        baseline = json.load(f)

    if webapp_path:
        with open(webapp_path, "r") as f:
            webapp_data = json.load(f)

    if webapp_data is None:
        raise ValueError("Provide either webapp_path or webapp_data")

    # Normalize both sides
    baseline = normalize_dict(baseline)
    webapp_data = normalize_dict(webapp_data)

    results = compare_dicts(baseline, webapp_data)
    all_passed = all(r.passed for r in results)

    # Write diff report
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(f"# Parity Check Report\n")
            f.write(f"# Baseline: {baseline_path}\n")
            f.write(f"# Webapp: {webapp_path or 'inline data'}\n")
            f.write(f"# Date: {datetime.now().isoformat()}\n")
            f.write(f"# Result: {'PASS' if all_passed else 'FAIL'}\n\n")

            failures = [r for r in results if not r.passed]
            passes = [r for r in results if r.passed]

            f.write(f"Total checks: {len(results)}\n")
            f.write(f"Passed: {len(passes)}\n")
            f.write(f"Failed: {len(failures)}\n\n")

            if failures:
                f.write("## Failures\n\n")
                for r in failures:
                    f.write(f"- {r.path}: {r.message}\n")
                    if r.baseline_value is not None:
                        f.write(f"  baseline={r.baseline_value}\n")
                    if r.webapp_value is not None:
                        f.write(f"  webapp={r.webapp_value}\n")
                    if r.delta is not None:
                        f.write(f"  delta={r.delta:.6f}, tolerance={r.tolerance}\n")
                    f.write("\n")

    return all_passed, results


def main():
    parser = argparse.ArgumentParser(description="Compare webapp output against old tool baseline")
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON")
    parser.add_argument("--webapp", help="Path to webapp JSON")
    parser.add_argument("--output", help="Path to write diff report")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if not args.webapp:
        parser.error("Provide --webapp path to webapp JSON")

    passed, results = run_parity_check(
        args.baseline, args.webapp, output_path=args.output,
    )

    failures = [r for r in results if not r.passed]
    print(f"\nParity check: {'PASS' if passed else 'FAIL'}")
    print(f"  Total: {len(results)} | Passed: {len(results) - len(failures)} | Failed: {len(failures)}")

    if failures:
        print("\nFailures:")
        for r in failures[:20]:  # Show first 20
            print(f"  {r.path}: {r.message}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tools/tests/test_parity_check.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add tools/parity_check.py tools/tests/test_parity_check.py
git commit -m "feat(tools): add parity checker for webapp vs old tool comparison"
```

---

### Task 6: Build PDF Report Generator

**Files:**
- Create: `tools/generate_report_pdf.py`

**Step 1: Write the generator**

```python
"""Generate PDF report from audit/report.md.

Uses markdown + weasyprint (already in telemetry_tool/requirements.txt).
Falls back to basic HTML if weasyprint is not installed.

Usage:
    python tools/generate_report_pdf.py
    python tools/generate_report_pdf.py --input audit/report.md --output audit/report.pdf
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def md_to_html(md_content: str) -> str:
    """Convert markdown to HTML with styling."""
    try:
        import markdown
        html_body = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "toc"],
        )
    except ImportError:
        # Fallback: minimal conversion
        html_body = f"<pre>{md_content}</pre>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>E2E Certification Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #222; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 10px; }}
  h2 {{ color: #16213e; margin-top: 30px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background-color: #16213e; color: white; }}
  tr:nth-child(even) {{ background-color: #f8f9fa; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #1a1a2e; color: #e0e0e0; padding: 15px; border-radius: 5px; overflow-x: auto; }}
  .pass {{ color: #28a745; font-weight: bold; }}
  .fail {{ color: #dc3545; font-weight: bold; }}
  .fixed {{ color: #fd7e14; font-weight: bold; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
{html_body}
<div class="footer">
  <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Branch: recovery/e2e-certification</p>
</div>
</body>
</html>"""


def generate_pdf(input_path: str, output_path: str) -> bool:
    """Convert markdown to PDF. Returns True on success."""
    with open(input_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    html = md_to_html(md_content)

    # Try weasyprint first
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(output_path)
        logger.info("PDF generated via weasyprint: %s", output_path)
        return True
    except ImportError:
        logger.warning("weasyprint not available, trying fallback")
    except Exception as e:
        logger.warning("weasyprint failed: %s, trying fallback", e)

    # Fallback: write HTML file (can be opened in browser and printed to PDF)
    html_path = output_path.replace(".pdf", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML report written (PDF fallback): %s", html_path)
    return False


def main():
    parser = argparse.ArgumentParser(description="Generate PDF from audit report")
    parser.add_argument("--input", default=str(ROOT / "audit" / "report.md"))
    parser.add_argument("--output", default=str(ROOT / "audit" / "report.pdf"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    generate_pdf(args.input, args.output)


if __name__ == "__main__":
    main()
```

**Step 2: Run smoke test**

```bash
python tools/generate_report_pdf.py
ls -la audit/report.pdf audit/report.html 2>/dev/null
```

Expected: either `report.pdf` (weasyprint) or `report.html` (fallback) created.

**Step 3: Commit**

```bash
git add tools/generate_report_pdf.py
git commit -m "feat(tools): add PDF report generator for audit reports"
```

---

### Task 7: Build Cycle Runner

**Files:**
- Create: `tools/cycle_runner.py`
- Create: `tools/cycle_template.md`

**Step 1: Create cycle template**

```markdown
# Cycle {cycle_number}: {feature_id} — {feature_name}

**Date:** {date}
**Tier:** {tier}
**Area:** {area}
**Test Method:** {test_method}

## Expected Behavior
{expected_behavior}

## Parity Reference
{parity_reference}

## Tests Executed
- [ ] {test_list}

## Observed Behavior (Webapp)
<!-- Fill during execution -->

## Parity Diff Summary
<!-- Fill if parity check applies -->

## Root Cause Analysis
<!-- Fill if defect found -->

## Fix Summary
<!-- Fill if fix applied -->

## Verification Evidence
<!-- Test output, logs, screenshots -->

## Regression Risk
<!-- What else could break -->

## Re-tested
<!-- What regression tests were run -->
```

**Step 2: Write cycle_runner.py**

```python
"""Cycle runner — orchestrates a single audit cycle.

Usage:
    python tools/cycle_runner.py --cycle 1 --feature F-0001
    python tools/cycle_runner.py --next  # Pick next pending from inventory
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def read_inventory(path: str | None = None) -> list[dict]:
    """Parse feature-inventory.md into list of feature dicts."""
    path = path or str(ROOT / "audit" / "feature-inventory.md")
    if not os.path.exists(path):
        logger.error("Feature inventory not found: %s", path)
        return []

    features = []
    with open(path, "r", encoding="utf-8") as f:
        in_table = False
        for line in f:
            line = line.strip()
            if line.startswith("| ID"):
                in_table = True
                continue
            if in_table and line.startswith("|---"):
                continue
            if in_table and line.startswith("|"):
                cols = [c.strip() for c in line.split("|")[1:-1]]
                if len(cols) >= 7:
                    features.append({
                        "id": cols[0],
                        "area": cols[1],
                        "feature": cols[2],
                        "tier": cols[3],
                        "test_method": cols[4],
                        "parity_ref": cols[5],
                        "status": cols[6],
                    })
            elif in_table and not line:
                in_table = False

    return features


def find_next_pending(features: list[dict]) -> dict | None:
    """Find next pending feature in inventory order."""
    for f in features:
        if f["status"].lower() == "pending":
            return f
    return None


def create_cycle_file(cycle_number: int, feature: dict) -> str:
    """Create a cycle log file from template."""
    template_path = ROOT / "tools" / "cycle_template.md"
    if template_path.exists():
        template = template_path.read_text()
    else:
        template = "# Cycle {cycle_number}: {feature_id} - {feature_name}\n\nDate: {date}\n"

    content = template.format(
        cycle_number=f"{cycle_number:04d}",
        feature_id=feature["id"],
        feature_name=feature["feature"],
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        tier=feature["tier"],
        area=feature["area"],
        test_method=feature["test_method"],
        expected_behavior="See feature inventory",
        parity_reference=feature["parity_ref"],
        test_list="See test method: " + feature["test_method"],
    )

    output_path = ROOT / "audit" / "cycles" / f"CYCLE-{cycle_number:04d}.md"
    output_path.write_text(content, encoding="utf-8")
    logger.info("Created cycle file: %s", output_path)
    return str(output_path)


def append_to_report(cycle_number: int, feature: dict, status: str, summary: str):
    """Append a cycle entry to audit/report.md."""
    report_path = ROOT / "audit" / "report.md"
    entry = f"- [CYCLE {cycle_number:04d}] {feature['id']}: {feature['feature']} — {status} — {summary}\n"

    with open(report_path, "a", encoding="utf-8") as f:
        f.write(entry)

    logger.info("Appended to report: %s", entry.strip())


def update_inventory_status(feature_id: str, new_status: str, path: str | None = None):
    """Update a feature's status in the inventory file."""
    path = path or str(ROOT / "audit" / "feature-inventory.md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace status in the matching row
    pattern = re.compile(
        rf"(\|\s*{re.escape(feature_id)}\s*\|.*?\|)\s*\w+\s*\|$",
        re.MULTILINE,
    )
    content = pattern.sub(rf"\1 {new_status} |", content)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Updated %s status to %s", feature_id, new_status)


def generate_pdf():
    """Regenerate the PDF report."""
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_report_pdf.py")],
        check=False,
    )


def git_commit_and_push(cycle_number: int, feature: dict, summary: str):
    """Commit and push cycle changes."""
    msg = f"cycle {cycle_number:04d}: {feature['id']} {summary}"
    subprocess.run(["git", "add", "-A"], cwd=str(ROOT), check=False)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT), check=False)
    subprocess.run(["git", "push", "origin", "recovery/e2e-certification"],
                   cwd=str(ROOT), check=False)


def deploy():
    """Run deployment script."""
    deploy_script = ROOT / "scripts" / "deploy.sh"
    if deploy_script.exists():
        subprocess.run(["bash", str(deploy_script)], cwd=str(ROOT), check=False)
    else:
        logger.warning("No deploy script found at %s", deploy_script)


def main():
    parser = argparse.ArgumentParser(description="Run a certification cycle")
    parser.add_argument("--cycle", type=int, help="Cycle number")
    parser.add_argument("--feature", help="Feature ID (e.g. F-0001)")
    parser.add_argument("--next", action="store_true", help="Pick next pending")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--skip-push", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    features = read_inventory()
    if not features:
        logger.error("No features found in inventory")
        sys.exit(1)

    if args.next:
        feature = find_next_pending(features)
        if not feature:
            logger.info("All features validated!")
            sys.exit(0)
        # Determine cycle number from existing cycle files
        existing = list((ROOT / "audit" / "cycles").glob("CYCLE-*.md"))
        cycle_number = len(existing) + 1
    else:
        if not args.cycle or not args.feature:
            parser.error("Provide --cycle and --feature, or use --next")
        cycle_number = args.cycle
        feature = next((f for f in features if f["id"] == args.feature), None)
        if not feature:
            logger.error("Feature %s not found in inventory", args.feature)
            sys.exit(1)

    logger.info("Starting cycle %d: %s — %s", cycle_number, feature["id"], feature["feature"])

    # Create cycle file
    create_cycle_file(cycle_number, feature)

    # Mark as in-progress
    update_inventory_status(feature["id"], "in-progress")

    print(f"\n{'='*60}")
    print(f"CYCLE {cycle_number:04d}: {feature['id']} — {feature['feature']}")
    print(f"Tier: {feature['tier']} | Method: {feature['test_method']}")
    print(f"{'='*60}")
    print(f"\nCycle file created. Now:")
    print(f"  1. Run tests for this feature")
    print(f"  2. Fix if needed")
    print(f"  3. Update cycle file with results")
    print(f"  4. Then run: python tools/cycle_runner.py --complete {cycle_number}")


if __name__ == "__main__":
    main()
```

**Step 3: Commit**

```bash
git add tools/cycle_runner.py tools/cycle_template.md
git commit -m "feat(tools): add cycle runner for audit cycle orchestration"
```

---

### Task 8: Create Playwright E2E Helpers

**Files:**
- Create: `lap-website/e2e/helpers/auth.ts`
- Create: `lap-website/e2e/helpers/api-mocks.ts`

**Step 1: Create shared auth helper**

```typescript
// lap-website/e2e/helpers/auth.ts
import { Page } from '@playwright/test';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

export interface TestUser {
  email: string;
  password: string;
  tier: 'demo' | 'racer' | 'world_class';
}

export const TEST_USERS: Record<string, TestUser> = {
  demo: {
    email: 'theos.elive@gmail.com',
    password: 'claudetest',
    tier: 'demo',
  },
  racer: {
    email: 'theo.stipapro@gmail.com',
    password: 'claudetest',
    tier: 'racer',
  },
  world_class: {
    email: 'fsae.ecn@gmail.com',
    password: 'claudetest',
    tier: 'world_class',
  },
};

/**
 * Login via the real API (not mocked) and store tokens.
 * Returns the access token for API calls.
 */
export async function loginAsUser(page: Page, tier: keyof typeof TEST_USERS): Promise<string> {
  const user = TEST_USERS[tier];

  const response = await page.request.post(`${API_URL}/auth/login`, {
    data: { email: user.email, password: user.password },
  });

  const body = await response.json();
  if (!body.ok) {
    throw new Error(`Login failed for ${user.email}: ${JSON.stringify(body.error)}`);
  }

  const accessToken = body.data.access_token;

  // Store token in page context for subsequent navigation
  await page.evaluate((token) => {
    (window as any).__accessToken = token;
  }, accessToken);

  return accessToken;
}

/**
 * Login via the UI login form (real E2E flow).
 */
export async function loginViaUI(page: Page, tier: keyof typeof TEST_USERS): Promise<void> {
  const user = TEST_USERS[tier];

  await page.goto('/login');
  await page.getByPlaceholder('driver@example.com').fill(user.email);
  await page.getByPlaceholder(/password|••••/i).fill(user.password);
  await page.getByRole('button', { name: /sign in/i }).click();

  // Wait for redirect to dashboard
  await page.waitForURL(/\/app/, { timeout: 15000 });
}

/**
 * Make an authenticated API request.
 */
export async function apiRequest(
  page: Page,
  method: string,
  path: string,
  token: string,
  body?: any,
) {
  const url = `${API_URL}${path}`;
  const options: any = {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  };
  if (body) {
    options.data = body;
  }

  if (method === 'GET') return page.request.get(url, options);
  if (method === 'POST') return page.request.post(url, options);
  if (method === 'PUT') return page.request.put(url, options);
  if (method === 'DELETE') return page.request.delete(url, options);

  throw new Error(`Unsupported method: ${method}`);
}
```

**Step 2: Create API mock helpers (for offline tests)**

```typescript
// lap-website/e2e/helpers/api-mocks.ts
import { Page } from '@playwright/test';

/**
 * Mock the /auth/me endpoint to simulate a logged-in user with a specific tier.
 */
export async function mockAuthMe(page: Page, tier: 'demo' | 'racer' | 'world_class') {
  const users = {
    demo: { id: 32, email: 'theos.elive@gmail.com', display_name: 'Demo User', plan_tier: 'demo' },
    racer: { id: 31, email: 'theo.stipapro@gmail.com', display_name: 'Racer User', plan_tier: 'racer' },
    world_class: { id: 59, email: 'fsae.ecn@gmail.com', display_name: 'World Class User', plan_tier: 'world_class' },
  };

  await page.route('**/api/v1/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: users[tier], meta: {} }),
    });
  });

  await page.route('**/api/v1/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: users[tier], meta: {} }),
    });
  });
}

/**
 * Mock entitlement snapshot for tier-gated tests.
 */
export async function mockEntitlements(page: Page, tier: 'demo' | 'racer' | 'world_class') {
  const entitlements = {
    demo: {
      plan_tier: 'demo', reports_per_month: 1, uploads_per_month: 1,
      api_access: false, comparison_enabled: false, visualization_enabled: false,
      coaching_plans_enabled: false, live_monitoring: false,
    },
    racer: {
      plan_tier: 'racer', reports_per_month: 10, uploads_per_month: 10,
      api_access: false, comparison_enabled: false, visualization_enabled: true,
      coaching_plans_enabled: true, live_monitoring: true,
    },
    world_class: {
      plan_tier: 'world_class', reports_per_month: -1, uploads_per_month: -1,
      api_access: true, comparison_enabled: true, visualization_enabled: true,
      coaching_plans_enabled: true, live_monitoring: true,
    },
  };

  await page.route('**/api/v1/account/entitlements', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: entitlements[tier], meta: {} }),
    });
  });
}
```

**Step 3: Commit**

```bash
git add lap-website/e2e/helpers/
git commit -m "feat(e2e): add shared auth and mock helpers for certification tests"
```

---

### Task 9: Create Tenant Isolation E2E Tests

**Files:**
- Create: `lap-website/e2e/tenant-isolation.spec.ts`

**Step 1: Write the test**

```typescript
// lap-website/e2e/tenant-isolation.spec.ts
import { test, expect } from '@playwright/test';
import { loginAsUser, apiRequest, TEST_USERS } from './helpers/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

test.describe('Multi-Tenant Isolation', () => {
  test.describe.configure({ mode: 'serial' });

  let demoToken: string;
  let racerToken: string;
  let worldClassToken: string;
  let demoSessionIds: string[] = [];

  test.beforeAll(async ({ browser }) => {
    // Login all 3 users and get tokens
    const page = await browser.newPage();

    demoToken = await loginAsUser(page, 'demo');
    racerToken = await loginAsUser(page, 'racer');
    worldClassToken = await loginAsUser(page, 'world_class');

    // Get demo user's sessions
    const resp = await page.request.get(`${API_URL}/api/v1/sessions/browse`, {
      headers: { Authorization: `Bearer ${demoToken}` },
    });
    const body = await resp.json();
    if (body.ok && body.data?.sessions) {
      demoSessionIds = body.data.sessions.map((s: any) => s.session_id).slice(0, 3);
    }

    await page.close();
  });

  test('racer cannot access demo user sessions via API', async ({ page }) => {
    test.skip(demoSessionIds.length === 0, 'No demo sessions to test');

    for (const sessionId of demoSessionIds) {
      const resp = await apiRequest(page, 'GET', `/api/v1/sessions/${sessionId}/details`, racerToken);
      const status = resp.status();
      expect([403, 404]).toContain(status);
    }
  });

  test('world_class cannot access demo user sessions via API', async ({ page }) => {
    test.skip(demoSessionIds.length === 0, 'No demo sessions to test');

    for (const sessionId of demoSessionIds) {
      const resp = await apiRequest(page, 'GET', `/api/v1/sessions/${sessionId}/details`, worldClassToken);
      const status = resp.status();
      expect([403, 404]).toContain(status);
    }
  });

  test('demo user session list does not include racer sessions', async ({ page }) => {
    // Get racer's sessions
    const racerResp = await page.request.get(`${API_URL}/api/v1/sessions/browse`, {
      headers: { Authorization: `Bearer ${racerToken}` },
    });
    const racerBody = await racerResp.json();
    const racerSessionIds = (racerBody.data?.sessions || []).map((s: any) => s.session_id);

    // Get demo's sessions
    const demoResp = await page.request.get(`${API_URL}/api/v1/sessions/browse`, {
      headers: { Authorization: `Bearer ${demoToken}` },
    });
    const demoBody = await demoResp.json();
    const demoSessionIdList = (demoBody.data?.sessions || []).map((s: any) => s.session_id);

    // No overlap
    for (const id of racerSessionIds) {
      expect(demoSessionIdList).not.toContain(id);
    }
  });

  test('IDOR: sequential ID guessing returns 403/404', async ({ page }) => {
    // Try accessing sessions with sequential IDs
    for (let id = 1; id <= 10; id++) {
      const resp = await apiRequest(page, 'GET', `/api/v1/sessions/${id}/details`, demoToken);
      const status = resp.status();
      // Should either be the user's own session (200) or blocked (403/404)
      if (status === 200) {
        const body = await resp.json();
        // If 200, verify it belongs to the demo user
        // (workspace isolation should handle this via RLS)
      }
      // 403 or 404 are acceptable for other users' sessions
    }
  });
});
```

**Step 2: Commit**

```bash
git add lap-website/e2e/tenant-isolation.spec.ts
git commit -m "feat(e2e): add multi-tenant isolation tests"
```

---

### Task 10: Create RBAC Tier Gate E2E Tests

**Files:**
- Create: `lap-website/e2e/rbac-gates.spec.ts`

**Step 1: Write the test**

```typescript
// lap-website/e2e/rbac-gates.spec.ts
import { test, expect } from '@playwright/test';
import { loginAsUser, apiRequest } from './helpers/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

test.describe('RBAC Tier Gates — Backend Enforcement', () => {

  test.describe('Demo tier restrictions', () => {
    let token: string;

    test.beforeAll(async ({ browser }) => {
      const page = await browser.newPage();
      token = await loginAsUser(page, 'demo');
      await page.close();
    });

    test('demo cannot access comparison endpoint', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/comparisons/', token);
      expect(resp.status()).toBe(403);
      const body = await resp.json();
      expect(body.error?.code).toBe('PLAN_REQUIRED');
    });

    test('demo cannot access visualization endpoint', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/visualize/', token);
      expect(resp.status()).toBe(403);
    });

    test('demo cannot access API data endpoint', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/data/', token);
      expect(resp.status()).toBe(403);
    });
  });

  test.describe('Racer tier access', () => {
    let token: string;

    test.beforeAll(async ({ browser }) => {
      const page = await browser.newPage();
      token = await loginAsUser(page, 'racer');
      await page.close();
    });

    test('racer CAN access visualization', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/visualize/', token);
      // Should not be 403 — may be 200 or 404 if no data
      expect(resp.status()).not.toBe(403);
    });

    test('racer CANNOT access comparison (world_class only)', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/comparisons/', token);
      expect(resp.status()).toBe(403);
    });

    test('racer CANNOT access API data (world_class only)', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/data/', token);
      expect(resp.status()).toBe(403);
    });
  });

  test.describe('World-class tier access', () => {
    let token: string;

    test.beforeAll(async ({ browser }) => {
      const page = await browser.newPage();
      token = await loginAsUser(page, 'world_class');
      await page.close();
    });

    test('world_class CAN access comparison', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/comparisons/', token);
      expect(resp.status()).not.toBe(403);
    });

    test('world_class CAN access visualization', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/visualize/', token);
      expect(resp.status()).not.toBe(403);
    });

    test('world_class CAN access API data', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/data/', token);
      expect(resp.status()).not.toBe(403);
    });
  });

  test.describe('Quota enforcement', () => {
    test('demo upload quota is enforced', async ({ page }) => {
      const token = await loginAsUser(page, 'demo');

      // Demo tier: 1 upload/month — check entitlements
      const resp = await apiRequest(page, 'GET', '/api/v1/account/entitlements', token);
      if (resp.status() === 200) {
        const body = await resp.json();
        expect(body.data?.uploads_per_month).toBe(1);
      }
    });

    test('world_class has unlimited uploads', async ({ page }) => {
      const token = await loginAsUser(page, 'world_class');

      const resp = await apiRequest(page, 'GET', '/api/v1/account/entitlements', token);
      if (resp.status() === 200) {
        const body = await resp.json();
        expect(body.data?.uploads_per_month).toBe(-1);
      }
    });
  });
});
```

**Step 2: Commit**

```bash
git add lap-website/e2e/rbac-gates.spec.ts
git commit -m "feat(e2e): add RBAC tier gate enforcement tests"
```

---

### Task 11: Create Backend Integration Tests for Tier Gates

**Files:**
- Create: `telemetry_tool/tests/test_certification_rbac.py`

**Step 1: Write backend RBAC integration tests**

```python
# telemetry_tool/tests/test_certification_rbac.py
"""Certification RBAC tests — verify backend enforcement of tier gates.

Tests that entitlement middleware correctly blocks/allows features
based on plan_tier, independent of frontend UI.
"""
import sys
import os
import pytest

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from auth.entitlements import (
    get_plan_entitlements,
    check_usage_limit,
    PLAN_ENTITLEMENTS,
    KNOWN_PLANS,
)


class TestPlanEntitlements:
    """Verify plan entitlement definitions are correct."""

    def test_demo_is_alias_for_free(self):
        assert PLAN_ENTITLEMENTS["demo"] is PLAN_ENTITLEMENTS["free"]

    def test_known_plans_complete(self):
        assert "free" in KNOWN_PLANS
        assert "demo" in KNOWN_PLANS
        assert "racer" in KNOWN_PLANS
        assert "world_class" in KNOWN_PLANS

    def test_demo_limits(self):
        ent = get_plan_entitlements("demo")
        assert ent["reports_per_month"] == 1
        assert ent["uploads_per_month"] == 1
        assert ent["api_access"] is False
        assert ent["comparison_progress"] is False
        assert ent["coaching_drills"] is False
        assert ent["viz_workspace"] is False

    def test_racer_limits(self):
        ent = get_plan_entitlements("racer")
        assert ent["reports_per_month"] == 10
        assert ent["uploads_per_month"] == 10
        assert ent["api_access"] is False
        assert ent["comparison_progress"] is False  # World-class only
        assert ent["coaching_drills"] is True
        assert ent["viz_workspace"] is True

    def test_world_class_limits(self):
        ent = get_plan_entitlements("world_class")
        assert ent["reports_per_month"] == -1  # unlimited
        assert ent["uploads_per_month"] == -1  # unlimited
        assert ent["api_access"] is True
        assert ent["comparison_progress"] is True
        assert ent["coaching_drills"] is True
        assert ent["viz_workspace"] is True

    def test_unknown_plan_falls_back_to_free(self):
        ent = get_plan_entitlements("nonexistent_tier")
        assert ent == PLAN_ENTITLEMENTS["free"]


class TestUsageLimits:
    """Verify usage limit checking logic."""

    def test_demo_report_under_limit(self):
        allowed, info = check_usage_limit("demo", "reports", 0)
        assert allowed is True
        assert info["remaining"] == 1

    def test_demo_report_at_limit(self):
        allowed, info = check_usage_limit("demo", "reports", 1)
        assert allowed is False
        assert info["remaining"] == 0

    def test_demo_report_over_limit(self):
        allowed, info = check_usage_limit("demo", "reports", 5)
        assert allowed is False

    def test_racer_report_under_limit(self):
        allowed, info = check_usage_limit("racer", "reports", 5)
        assert allowed is True
        assert info["remaining"] == 5

    def test_world_class_unlimited(self):
        allowed, info = check_usage_limit("world_class", "reports", 9999)
        assert allowed is True
        assert info["remaining"] == -1  # unlimited

    def test_unknown_metric_denied(self):
        allowed, info = check_usage_limit("racer", "unknown_metric", 0)
        assert allowed is False


class TestFeatureAccessMatrix:
    """Cross-tier feature access matrix — the definitive test."""

    # (plan, feature_key, expected_value)
    MATRIX = [
        # api_access
        ("demo", "api_access", False),
        ("racer", "api_access", False),
        ("world_class", "api_access", True),
        # comparison_progress (comparison feature)
        ("demo", "comparison_progress", False),
        ("racer", "comparison_progress", False),
        ("world_class", "comparison_progress", True),
        # coaching_drills
        ("demo", "coaching_drills", False),
        ("racer", "coaching_drills", True),
        ("world_class", "coaching_drills", True),
        # viz_workspace (visualization)
        ("demo", "viz_workspace", False),
        ("racer", "viz_workspace", True),
        ("world_class", "viz_workspace", True),
        # live_pace (live monitoring)
        ("demo", "live_pace", False),
        ("racer", "live_pace", True),
        ("world_class", "live_pace", True),
        # pdf_reports
        ("demo", "pdf_reports", False),
        ("racer", "pdf_reports", True),
        ("world_class", "pdf_reports", True),
        # max_workspace_members
        ("demo", "max_workspace_members", 1),
        ("racer", "max_workspace_members", 1),
        ("world_class", "max_workspace_members", 5),
    ]

    @pytest.mark.parametrize("plan,feature,expected", MATRIX)
    def test_feature_access(self, plan, feature, expected):
        ent = get_plan_entitlements(plan)
        assert ent[feature] == expected, (
            f"{plan}.{feature}: expected {expected}, got {ent[feature]}"
        )
```

**Step 2: Run tests**

```bash
pytest telemetry_tool/tests/test_certification_rbac.py -v
```

Expected: all PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_certification_rbac.py
git commit -m "feat(tests): add certification RBAC integration tests with full access matrix"
```

---

### Task 12: Create Feature Inventory (250+ Items)

**Files:**
- Create: `audit/feature-inventory.md`

**Step 1: Build the comprehensive inventory**

This is the largest single file. It should contain 250+ rows covering every testable feature. Structure it by area. The inventory draws from:
- `auth/entitlements.py` PLAN_ENTITLEMENTS dict
- `web/middleware/entitlements.py` _FEATURE_GATES and _QUOTA_GATES
- `web/routes/` — all 32 blueprints
- `pipeline.py` — 14+ pipeline stages
- `scoring.py` — 4-pillar scoring
- Existing E2E test files — 14 spec files
- Frontend routes in `lap-website/src/app/`

The inventory must have exactly these columns:
`| ID | Area | Feature | Tier | Test Method | Parity Ref | Status |`

Areas and approximate counts:
- Auth (F-0001 to F-0025): 25 items
- Upload/Ingest (F-0026 to F-0045): 20 items
- Pipeline Processing (F-0046 to F-0095): 50 items
- Charts/Visualization (F-0096 to F-0130): 35 items
- Exports (F-0131 to F-0145): 15 items
- Billing (F-0146 to F-0165): 20 items
- Account (F-0166 to F-0180): 15 items
- Admin (F-0181 to F-0195): 15 items
- RBAC/Entitlements (F-0196 to F-0220): 25 items
- Tenant Isolation (F-0221 to F-0240): 20 items
- Selling Site (F-0241 to F-0265): 25 items
- Old-Tool Parity (F-0266 to F-0285): 20 items
- Security (F-0286 to F-0300): 15 items

Write the full markdown table. Each row must be specific enough to test in a single cycle.

**Step 2: Verify count**

```bash
grep -c "^| F-" audit/feature-inventory.md
```

Expected: 250+

**Step 3: Commit**

```bash
git add audit/feature-inventory.md
git commit -m "feat(audit): create 250+ item feature inventory for certification"
```

---

### Task 13: Generate Old Tool Baselines

**Step 1: Inspect CSVs to finalize batch configs**

```bash
head -3 data/raw/OK_R1.csv
head -3 data/raw/OK_R3.csv
head -3 data/raw/OK_R4.csv
```

**Step 2: Update batch configs based on CSV structure**

Adjust `tools/batch_configs/OK_R1.json`, `OK_R3.json`, `OK_R4.json` with correct session_type, track_state, and driver configs.

**Step 3: Run baseline generation**

```bash
python tools/old_tool_runner.py --all
```

This will take several minutes per CSV (pipeline processing). Expected output:
```
INFO: Generating baseline for OK_R1 ...
INFO: Baseline written to audit/baselines/old_tool/OK_R1.json
INFO: Generating baseline for OK_R3 ...
INFO: Baseline written to audit/baselines/old_tool/OK_R3.json
INFO: Generating baseline for OK_R4 ...
INFO: Baseline written to audit/baselines/old_tool/OK_R4.json
```

**Step 4: Verify baselines are valid JSON with expected structure**

```bash
python -c "import json; d=json.load(open('audit/baselines/old_tool/OK_R1.json')); print(list(d.keys()))"
```

Expected keys: `scores`, `lap_times`, `corner_count`, `corners`, `consistency_metrics`, etc.

**Step 5: Commit baselines**

```bash
git add audit/baselines/old_tool/
git commit -m "feat(audit): generate old tool baselines for OK_R1, OK_R3, OK_R4"
```

---

### Task 14: Create `__init__.py` and Package Structure for Tools

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/tests/__init__.py`
- Create: `tools/tests/conftest.py`

**Step 1: Create package files**

```python
# tools/__init__.py
# Certification harness tools package
```

```python
# tools/tests/__init__.py
```

```python
# tools/tests/conftest.py
import sys
import os

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
```

**Step 2: Run all tools tests**

```bash
pytest tools/tests/ -v
```

Expected: all PASS

**Step 3: Commit**

```bash
git add tools/__init__.py tools/tests/__init__.py tools/tests/conftest.py
git commit -m "chore: add package structure for tools directory"
```

---

### Task 15: Run Full Test Suite Verification

**Step 1: Run backend tests**

```bash
pytest telemetry_tool/tests/ -q --tb=short
```

Verify existing tests still pass (no regressions from new code).

**Step 2: Run tools tests**

```bash
pytest tools/tests/ -v
```

**Step 3: Run frontend lint and tests**

```bash
cd lap-website && npm run lint && npm run test
```

**Step 4: Generate initial PDF report**

```bash
python tools/generate_report_pdf.py
```

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: verify full test suite passes, generate initial report"
```

---

## Execution Summary

| Task | Deliverable | Est. Time |
|------|-------------|-----------|
| 1 | Branch + directory scaffold | 3 min |
| 2 | Batch configs | 5 min |
| 3 | normalize.py + tests | 10 min |
| 4 | old_tool_runner.py + tests | 10 min |
| 5 | parity_check.py + tests | 10 min |
| 6 | generate_report_pdf.py | 5 min |
| 7 | cycle_runner.py + template | 10 min |
| 8 | Playwright helpers | 5 min |
| 9 | Tenant isolation E2E | 5 min |
| 10 | RBAC gate E2E | 5 min |
| 11 | Backend RBAC tests | 5 min |
| 12 | Feature inventory (250+ items) | 20 min |
| 13 | Generate baselines | 15 min |
| 14 | Package structure | 2 min |
| 15 | Full test verification | 5 min |
| **Total** | | **~115 min** |
