"""Full-scale ML training pipeline orchestrator.

Runs all 7 stages in order, skipping stages whose outputs already exist.
Stages 1-5 extract features, Stage 6 trains models, Stage 7 generates report.

Usage:
    python scripts/training/full_training_pipeline.py           # run all
    python scripts/training/full_training_pipeline.py --stage 6  # run specific stage
    python scripts/training/full_training_pipeline.py --force    # re-run even if outputs exist
"""
import sys, pathlib, argparse, time, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "external"

STAGES = [
    ("Stage 1: DTM Events",       "scripts/training/stage1_dtm_events.py",   DATA_DIR / "dtm_events.parquet"),
    ("Stage 2: TUMFTM Features",  "scripts/training/stage2_tumftm.py",       DATA_DIR / "tumftm_features.parquet"),
    ("Stage 3: F1 Features",      "scripts/training/stage3_f1.py",           DATA_DIR / "f1_features.parquet"),
    ("Stage 4: Motorsport",       "scripts/training/stage4_motorsport.py",   DATA_DIR / "motorsport_features.parquet"),
    ("Stage 5: Kart Features",    "scripts/training/stage5_kart.py",         DATA_DIR / "kart_features.parquet"),
    ("Stage 6: Train Models",     "scripts/training/stage6_train.py",        ROOT / "telemetry_tool/handling/ml/models/training_results.json"),
    ("Stage 7: Report",           "scripts/training/stage7_report.py",       ROOT / "artifacts/full_training_report.md"),
]


def run_stage(name, script, output, force=False):
    """Run a stage if its output doesn't exist (or force=True)."""
    # Check for CSV fallback if parquet missing
    csv_fallback = output.with_suffix(".csv") if output.suffix == ".parquet" else None

    if not force and (output.exists() or (csv_fallback and csv_fallback.exists())):
        print(f"  SKIP {name} (output exists)")
        return True

    print(f"\n{'='*60}")
    print(f"  RUNNING: {name}")
    print(f"{'='*60}")

    script_path = ROOT / script
    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(ROOT),
            timeout=7200,  # 2 hour max per stage
            capture_output=False,
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            print(f"  {name}: DONE in {elapsed:.0f}s")
            return True
        else:
            print(f"  {name}: FAILED (exit code {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print(f"  {name}: TIMEOUT (>2 hours)")
        return False
    except Exception as e:
        print(f"  {name}: ERROR ({e})")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, help="Run specific stage (1-7)")
    parser.add_argument("--force", action="store_true", help="Re-run even if outputs exist")
    args = parser.parse_args()

    print("Full-Scale ML Training Pipeline")
    print(f"Data directory: {DATA_DIR}")
    print(f"{'='*60}\n")

    total_start = time.time()

    if args.stage:
        idx = args.stage - 1
        if 0 <= idx < len(STAGES):
            name, script, output = STAGES[idx]
            run_stage(name, script, output, force=True)
        else:
            print(f"Invalid stage: {args.stage} (1-7)")
    else:
        for name, script, output in STAGES:
            success = run_stage(name, script, output, force=args.force)
            if not success and "Stage 6" in name:
                print("Stage 6 failed — skipping Stage 7")
                break

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"Pipeline complete in {total_elapsed/60:.1f} minutes")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
