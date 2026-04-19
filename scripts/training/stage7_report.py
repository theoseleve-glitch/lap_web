"""Stage 7: Generate full-scale training report."""
import sys, pathlib, json
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
MODEL_DIR = ROOT / "telemetry_tool" / "handling" / "ml" / "models"
DATA_DIR = ROOT / "data" / "external"


def main():
    # Load training results
    results_path = MODEL_DIR / "training_results.json"
    results = {}
    if results_path.exists():
        with open(results_path) as f:
            results = json.load(f)

    # Count feature files
    sources = {}
    for name in ["dtm_events", "tumftm_features", "f1_features", "motorsport_features", "kart_features"]:
        for ext in [".parquet", ".csv"]:
            p = DATA_DIR / f"{name}{ext}"
            if p.exists():
                try:
                    df = pd.read_parquet(p) if ext == ".parquet" else pd.read_csv(p)
                    sources[name] = len(df)
                except Exception:
                    sources[name] = 0
                break

    total_rows = sum(sources.values())

    # Generate report
    lines = [
        "# Full-Scale ML Training Report",
        "",
        "## Data Processed",
        "",
        f"| Source | Rows |",
        f"|--------|------|",
    ]
    for name, count in sources.items():
        lines.append(f"| {name} | {count:,} |")
    lines.append(f"| **Total** | **{total_rows:,}** |")

    lines.extend(["", "## Model Performance", ""])

    ds = results.get("data_summary", {})
    ld = ds.get("label_dist", {})
    lines.append(f"Training data: {ds.get('total_rows', '?')} rows, "
                 f"{ds.get('n_features', '?')} features")
    lines.append(f"Labels: OS={ld.get('os', '?')}, neutral={ld.get('neutral', '?')}, US={ld.get('us', '?')}")
    lines.append("")

    lines.append("| Model | Metric | Value |")
    lines.append("|-------|--------|-------|")

    nb = results.get("naive_bayes", {})
    lines.append(f"| Naive Bayes | Accuracy | {nb.get('accuracy', '?'):.1%} |" if isinstance(nb.get('accuracy'), (int, float)) else "| Naive Bayes | Accuracy | ? |")

    ridge = results.get("ridge", {})
    lines.append(f"| Ridge Regression | R² | {ridge.get('r2', '?')} |")
    lines.append(f"| Ridge Regression | MAE | {ridge.get('mae', '?')} deg |")

    rf = results.get("random_forest", {})
    lines.append(f"| Random Forest | Accuracy | {rf.get('accuracy', '?'):.1%} |" if isinstance(rf.get('accuracy'), (int, float)) else "| Random Forest | Accuracy | ? |")

    anom = results.get("anomaly", {})
    lines.append(f"| Anomaly Detector | Event detection rate | {anom.get('event_rate', '?')} |")

    gmm = results.get("gmm", {})
    lines.append(f"| GMM | Clusters | {gmm.get('n_clusters', '?')} |")

    lines.extend(["", "## Models Saved", ""])
    for p in sorted(MODEL_DIR.glob("*.json")):
        size = p.stat().st_size
        lines.append(f"- `{p.name}` ({size:,} bytes)")

    report_path = ARTIFACTS / "full_training_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
