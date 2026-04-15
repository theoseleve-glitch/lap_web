"""Phase 5: Generate combined validation report from all phases.

Reads results from:
  - artifacts/validation_ground_truth.json (Phase 2)
  - data/external/dtm_features.csv (Phase 3)
  - artifacts/validation_f1_cross_track.json (Phase 4)

Outputs:
  - artifacts/validation_report.md
  - artifacts/validation_report.png (4-panel summary figure)
"""
import sys, pathlib, json
import numpy as np
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"


def load_json(name: str) -> dict:
    path = ARTIFACTS / name
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def main():
    gt = load_json("validation_ground_truth.json")
    f1 = load_json("validation_f1_cross_track.json")

    # Try to load ML results
    ml_results = {}
    for name in ["naive_bayes_results.json", "gmm_results.json", "anomaly_results.json"]:
        r = load_json(name)
        if r:
            ml_results[name.replace("_results.json", "")] = r

    # Check if DTM features exist
    dtm_path = ROOT / "data" / "external" / "dtm_features.csv"
    dtm_exists = dtm_path.exists()
    dtm_rows = 0
    if dtm_exists:
        import pandas as pd
        dtm_rows = len(pd.read_csv(dtm_path))

    # Generate markdown report
    lines = [
        "# Handling Detection System - Validation Report",
        "",
        "## 1. Ground Truth Validation (TUMFTM Vehicle Dynamics)",
        "",
    ]

    if gt:
        acc = gt.get("overall_accuracy", 0)
        total = gt.get("total_corners", 0)
        correct = gt.get("total_correct", 0)
        lines.append(f"- **Accuracy**: {acc:.1%} ({correct}/{total} corners)")
        lines.append(f"- **Files processed**: {len(gt.get('files', []))}")

        # Per-file breakdown
        lines.append("")
        lines.append("| File | Corners | Correct | Accuracy |")
        lines.append("|------|---------|---------|----------|")
        for f in gt.get("files", []):
            if "error" in f and f["error"]:
                lines.append(f"| {f['file']} | ERROR | - | {f['error']} |")
            else:
                lines.append(f"| {f['file']} | {f.get('n_compared',0)} | {f.get('n_correct',0)} | {f.get('accuracy',0):.0%} |")
    else:
        lines.append("*Not run yet. Execute: `python scripts/validate_against_ground_truth.py`*")

    lines.extend(["", "## 2. ML Models (DTM Labeled Events)", ""])

    if dtm_exists:
        lines.append(f"- **Training corners**: {dtm_rows}")
        for name, r in ml_results.items():
            lines.append(f"- **{name}**: accuracy={r.get('accuracy', '?')}")
    else:
        lines.append("*Not run yet. Execute: `python scripts/ml/extract_features.py`*")

    lines.extend(["", "## 3. Cross-Track Generalization (F1 2022-2026)", ""])

    if f1:
        laps = f1.get("laps", [])
        n = len(laps)
        tracks = len(set(r["track"] for r in laps))
        drivers = len(set(r["driver"] for r in laps))
        seasons = len(set(r["year"] for r in laps))

        lines.append(f"- **Laps tested**: {n}")
        lines.append(f"- **Tracks**: {tracks}")
        lines.append(f"- **Drivers**: {drivers}")
        lines.append(f"- **Seasons**: {seasons}")

        # Per-driver
        lines.extend(["", "### Per-driver tendency", ""])
        lines.append("| Driver | Laps | US events | OS events | Avg direction | Tendency |")
        lines.append("|--------|------|-----------|-----------|---------------|----------|")
        for drv in sorted(set(r["driver"] for r in laps)):
            dr = [r for r in laps if r["driver"] == drv]
            avg_d = np.mean([r["overall_direction"] for r in dr])
            n_us = sum(r["n_understeer"] for r in dr)
            n_os = sum(r["n_oversteer"] for r in dr)
            tend = "US" if avg_d > 0.05 else ("OS" if avg_d < -0.05 else "BAL")
            lines.append(f"| {drv} | {len(dr)} | {n_us} | {n_os} | {avg_d:+.3f} | {tend} |")

        # Per-track
        lines.extend(["", "### Per-track profile", ""])
        lines.append("| Track | Type | Laps | Avg direction | Tendency |")
        lines.append("|-------|------|------|---------------|----------|")
        for track in sorted(set(r["track"] for r in laps)):
            tr = [r for r in laps if r["track"] == track]
            avg_d = np.mean([r["overall_direction"] for r in tr])
            ttype = tr[0].get("track_type", "?")
            tend = "US" if avg_d > 0.05 else ("OS" if avg_d < -0.05 else "BAL")
            lines.append(f"| {track} | {ttype} | {len(tr)} | {avg_d:+.3f} | {tend} |")
    else:
        lines.append("*Not run yet. Execute: `python scripts/validate_f1_cross_track.py`*")

    lines.extend([
        "",
        "## 4. System Summary",
        "",
        "| Component | Count |",
        "|-----------|-------|",
        "| Detectors | 16 |",
        "| Fusion | Bayesian (C1) + conflict (C3) + per-phase (C5) |",
        "| ML models | 3 (Naive Bayes, GMM, Anomaly) |",
        f"| Training data | {dtm_rows:,} corners (DTM) |",
        f"| Validation data | {gt.get('total_corners', 0)} corners (TUMFTM) |",
        f"| F1 cross-track | {f1.get('n_processed', 0)} laps |",
        "",
    ])

    # Write report
    report_path = ARTIFACTS / "validation_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Report saved to {report_path}")

    # Generate summary figure
    _plot_summary(gt, f1, ml_results, dtm_rows)


def _plot_summary(gt, f1, ml_results, dtm_rows):
    """Generate 4-panel summary figure."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.patch.set_facecolor("#0a0a0a")
    fig.suptitle("Handling Detection System - Validation Report", color="#F0EDE5", fontsize=14)

    for ax in axes.flat:
        ax.set_facecolor("#141414")
        ax.tick_params(colors="#949494")
        for sp in ax.spines.values():
            sp.set_color("#333")

    # Panel 1: Ground truth accuracy per file
    ax1 = axes[0, 0]
    if gt and gt.get("files"):
        files = [f for f in gt["files"] if "error" not in f or not f["error"]]
        names = [f["file"][:15] for f in files]
        accs = [f.get("accuracy", 0) for f in files]
        ax1.barh(names, accs, color="#C9A84C", alpha=0.8)
        ax1.set_xlim(0, 1)
        ax1.axvline(gt.get("overall_accuracy", 0), color="#FF2A2A", linestyle="--", label=f'Overall: {gt.get("overall_accuracy",0):.0%}')
        ax1.legend(facecolor="#1a1a1a", edgecolor="#333", labelcolor="#F0EDE5")
    ax1.set_title("Ground Truth Accuracy (TUMFTM)", color="#F0EDE5", fontsize=11)

    # Panel 2: F1 cross-track driver comparison
    ax2 = axes[0, 1]
    if f1 and f1.get("laps"):
        laps = f1["laps"]
        drivers = sorted(set(r["driver"] for r in laps))
        x = np.arange(len(drivers))
        dirs = [np.mean([r["overall_direction"] for r in laps if r["driver"] == d]) for d in drivers]
        colors = ["#FF2A2A" if d < -0.05 else ("#22C55E" if d > 0.05 else "#949494") for d in dirs]
        ax2.bar(x, dirs, color=colors, alpha=0.8)
        ax2.set_xticks(x)
        ax2.set_xticklabels(drivers, color="#F0EDE5")
        ax2.axhline(0, color="#949494", linewidth=0.5)
    ax2.set_title("F1 Driver Handling Tendencies", color="#F0EDE5", fontsize=11)
    ax2.set_ylabel("Direction (+US / -OS)", color="#F0EDE5")

    # Panel 3: F1 per-track tendency
    ax3 = axes[1, 0]
    if f1 and f1.get("laps"):
        laps = f1["laps"]
        tracks = sorted(set(r["track"] for r in laps))
        x = np.arange(len(tracks))
        dirs = [np.mean([r["overall_direction"] for r in laps if r["track"] == t]) for t in tracks]
        colors = ["#FF2A2A" if d < -0.05 else ("#22C55E" if d > 0.05 else "#949494") for d in dirs]
        ax3.barh(x, dirs, color=colors, alpha=0.8)
        ax3.set_yticks(x)
        ax3.set_yticklabels([t[:20] for t in tracks], color="#F0EDE5", fontsize=8)
        ax3.axvline(0, color="#949494", linewidth=0.5)
    ax3.set_title("F1 Track Handling Profiles", color="#F0EDE5", fontsize=11)

    # Panel 4: Summary stats
    ax4 = axes[1, 1]
    ax4.axis("off")
    stats = [
        f"Detectors: 16",
        f"Fusion: Bayesian + conflict + per-phase",
        f"",
        f"Ground Truth (TUMFTM):",
        f"  Accuracy: {gt.get('overall_accuracy', 0):.0%}" if gt else "  Not run",
        f"  Corners: {gt.get('total_corners', 0)}" if gt else "",
        f"",
        f"ML Training (DTM):",
        f"  Corners: {dtm_rows:,}" if dtm_rows else "  Not run",
        f"",
        f"Cross-Track (F1):",
        f"  Laps: {f1.get('n_processed', 0)}" if f1 else "  Not run",
    ]
    ax4.text(0.05, 0.95, "\n".join(stats), transform=ax4.transAxes, fontsize=10,
             color="#F0EDE5", verticalalignment="top", fontfamily="monospace")

    plt.tight_layout()
    out = ROOT / "artifacts" / "validation_report.png"
    plt.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    print(f"Figure saved to {out}")


if __name__ == "__main__":
    main()
