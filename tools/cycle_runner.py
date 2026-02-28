"""Cycle runner for E2E certification audit.

Orchestrates the test-fix-verify cycle for each feature in the inventory.
Reads the feature inventory, creates cycle files, updates statuses,
generates reports, and optionally commits/pushes/deploys.

Usage:
    python tools/cycle_runner.py --cycle 1 --feature F-0001
    python tools/cycle_runner.py --next          # Pick next pending from inventory
    python tools/cycle_runner.py --next --skip-deploy --skip-push
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


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------

def read_inventory(path: str | None = None) -> list[dict]:
    """Parse audit/feature-inventory.md markdown table into list of feature dicts.

    Each dict has keys: id, area, feature, tier, test_method, parity_ref, status.
    """
    if path is None:
        path = str(ROOT / "audit" / "feature-inventory.md")

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    features: list[dict] = []
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Detect table header row
        if stripped.startswith("| ID "):
            in_table = True
            continue

        # Skip separator row (e.g. |----|------|...)
        if in_table and re.match(r"^\|[\s\-|]+\|$", stripped):
            continue

        # Parse data rows
        if in_table and stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")]
            # split on | gives empty strings at start and end
            cells = [c for c in cells if c != "" or c == ""]
            # Filter out empty strings from leading/trailing pipes
            cells = stripped.split("|")
            cells = [c.strip() for c in cells[1:-1]]  # drop first empty and last empty

            if len(cells) >= 7:
                features.append({
                    "id": cells[0],
                    "area": cells[1],
                    "feature": cells[2],
                    "tier": cells[3],
                    "test_method": cells[4],
                    "parity_ref": cells[5],
                    "status": cells[6],
                })
        elif in_table and not stripped.startswith("|"):
            # End of table
            break

    return features


def find_next_pending(features: list[dict]) -> dict | None:
    """Find first feature with status 'pending'."""
    for f in features:
        if f["status"].lower() == "pending":
            return f
    return None


# ---------------------------------------------------------------------------
# Cycle file creation
# ---------------------------------------------------------------------------

def create_cycle_file(cycle_number: int, feature: dict) -> str:
    """Read cycle_template.md, format with feature data, write to audit/cycles/CYCLE-{nnnn}.md.

    Returns the path to the created file.
    """
    template_path = ROOT / "tools" / "cycle_template.md"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    content = template.format(
        cycle_number=cycle_number,
        feature_id=feature["id"],
        feature_name=feature["feature"],
        date=datetime.now().strftime("%Y-%m-%d"),
        tier=feature["tier"],
        area=feature["area"],
        test_method=feature["test_method"],
        expected_behavior=feature["feature"],
        parity_reference=feature.get("parity_ref", "\u2014"),
        test_list=f'{feature["test_method"]} test for {feature["feature"]}',
    )

    cycles_dir = ROOT / "audit" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)

    filename = f"CYCLE-{cycle_number:04d}.md"
    output_path = cycles_dir / filename
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Created cycle file: %s", output_path)
    return str(output_path)


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

def append_to_report(cycle_number: int, feature: dict, status: str, summary: str) -> None:
    """Append cycle entry line to audit/report.md."""
    report_path = ROOT / "audit" / "report.md"

    entry = (
        f"| {cycle_number:04d} | {feature['id']} | {feature['feature'][:50]} "
        f"| {status} | {summary} |\n"
    )

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Append after the marker comment
    marker = "<!-- Append cycle entries below this line -->"
    if marker in content:
        content = content.replace(marker, marker + "\n" + entry)
    else:
        # Fallback: just append at end
        content += "\n" + entry

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Appended cycle %04d to report", cycle_number)


# ---------------------------------------------------------------------------
# Inventory status update
# ---------------------------------------------------------------------------

def update_inventory_status(feature_id: str, new_status: str, path: str | None = None) -> None:
    """Regex replace status in the matching inventory row."""
    if path is None:
        path = str(ROOT / "audit" / "feature-inventory.md")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Match the row for this feature_id and replace the status column (last column)
    # Pattern: | F-0001 | ... | old_status |
    pattern = re.compile(
        r"^(\|\s*" + re.escape(feature_id) + r"\s*\|.*\|)\s*\S+\s*\|\s*$",
        re.MULTILINE,
    )

    match = pattern.search(content)
    if not match:
        raise ValueError(f"Feature {feature_id} not found in inventory at {path}")

    # Replace the last column value
    row = match.group(0)
    # Split on | and rebuild with new status
    parts = row.split("|")
    # parts: ['', ' F-0001 ', ' area ', ..., ' old_status ', '']
    # The status is the second-to-last non-empty part
    parts[-2] = f" {new_status} "
    new_row = "|".join(parts)

    content = content[:match.start()] + new_row + content[match.end():]

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Updated %s status to '%s'", feature_id, new_status)


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def generate_pdf() -> None:
    """Call python tools/generate_report_pdf.py via subprocess."""
    script = ROOT / "tools" / "generate_report_pdf.py"
    if not script.exists():
        logger.warning("generate_report_pdf.py not found at %s", script)
        return

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("PDF generation failed: %s", result.stderr)
    else:
        logger.info("PDF generation complete")
        if result.stdout:
            logger.info(result.stdout.strip())


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_commit_and_push(cycle_number: int, feature: dict, summary: str) -> None:
    """Stage only audit/ and tools/ files, commit, push."""
    msg = f"audit(cycle-{cycle_number:04d}): {feature['id']} {summary}"

    # Stage only harness-related directories — never git add -A
    subprocess.run(["git", "add", "audit/", "tools/"], cwd=str(ROOT), check=True)
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(ROOT),
        check=True,
    )
    subprocess.run(
        ["git", "push", "origin", "recovery/e2e-certification"],
        cwd=str(ROOT),
        check=True,
    )
    logger.info("Committed and pushed cycle %04d", cycle_number)


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

def deploy() -> None:
    """Run scripts/deploy.sh if it exists, else warn."""
    deploy_script = ROOT / "scripts" / "deploy.sh"
    if not deploy_script.exists():
        logger.warning("Deploy script not found: %s", deploy_script)
        return

    result = subprocess.run(
        ["bash", str(deploy_script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Deploy failed (exit %d): %s", result.returncode, result.stderr)
    else:
        logger.info("Deploy complete")
        if result.stdout:
            logger.info(result.stdout.strip())


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cycle runner for E2E certification audit",
    )
    parser.add_argument(
        "--cycle", type=int, default=None,
        help="Cycle number to assign",
    )
    parser.add_argument(
        "--feature", type=str, default=None,
        help="Feature ID (e.g. F-0001) to test",
    )
    parser.add_argument(
        "--next", action="store_true", dest="pick_next",
        help="Automatically pick the next pending feature",
    )
    parser.add_argument(
        "--skip-deploy", action="store_true",
        help="Skip deploy step",
    )
    parser.add_argument(
        "--skip-push", action="store_true",
        help="Skip git push (still commits locally)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load inventory
    features = read_inventory()

    # Determine which feature to run
    feature = None
    if args.pick_next:
        feature = find_next_pending(features)
        if feature is None:
            logger.info("All features have been processed. Nothing pending.")
            return
    elif args.feature:
        for f in features:
            if f["id"] == args.feature:
                feature = f
                break
        if feature is None:
            logger.error("Feature %s not found in inventory", args.feature)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    # Determine cycle number
    if args.cycle is not None:
        cycle_number = args.cycle
    else:
        # Auto-assign: count existing cycle files + 1
        cycles_dir = ROOT / "audit" / "cycles"
        existing = list(cycles_dir.glob("CYCLE-*.md")) if cycles_dir.exists() else []
        cycle_number = len(existing) + 1

    logger.info(
        "Starting cycle %04d for %s: %s",
        cycle_number, feature["id"], feature["feature"],
    )

    # 1. Create cycle file
    cycle_path = create_cycle_file(cycle_number, feature)
    logger.info("Cycle file: %s", cycle_path)

    # 2. Update inventory to 'in_progress'
    update_inventory_status(feature["id"], "in_progress")

    # 3. Append to report (initial entry)
    append_to_report(cycle_number, feature, "in_progress", "Cycle started")

    # 4. Generate PDF
    generate_pdf()

    # 5. Deploy (unless skipped)
    if not args.skip_deploy:
        deploy()
    else:
        logger.info("Deploy skipped (--skip-deploy)")

    # 6. Git commit and push (unless push skipped)
    if not args.skip_push:
        git_commit_and_push(cycle_number, feature, feature["feature"][:60])
    else:
        logger.info("Push skipped (--skip-push)")

    logger.info("Cycle %04d ready for manual testing.", cycle_number)


if __name__ == "__main__":
    main()
