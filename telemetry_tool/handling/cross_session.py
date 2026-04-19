"""Cross-session handling analysis: setup comparison, driver comparison,
track profiles, and handling-vs-laptime correlation.

All functions take runner result dicts (from run_handling_analysis()) and
return plain JSON-serializable dicts.  No database access; pure analysis.
"""
from __future__ import annotations

import numpy as np

# ── helpers ────────────────────────────────────────────────────────────────

def _corners(result: dict) -> list[dict]:
    return result.get("corners") or []

def _events(corner: dict) -> list[dict]:
    return corner.get("events") or []

def _dominant_dir(events: list[dict]) -> float:
    """Confidence-weighted mean direction across a corner's fused events."""
    if not events:
        return 0.0
    dirs = [e.get("direction", 0.0) for e in events]
    confs = [e.get("confidence", 0.0) for e in events]
    return sum(d * c for d, c in zip(dirs, confs)) / (sum(confs) or 1.0)

def _label(direction: float) -> str:
    if direction > 0.15:
        return "understeer"
    if direction < -0.15:
        return "oversteer"
    return "neutral"

# ── E1: Setup Change A/B Comparison ───────────────────────────────────────

def compare_setups(
    session_a: dict, session_b: dict,
    labels: tuple[str, str] = ("A", "B"),
) -> dict:
    """Compare handling results from the same track under different setups.
    Corners matched by index (same track assumed)."""
    ca, cb = _corners(session_a), _corners(session_b)
    n = min(len(ca), len(cb))
    deltas: list[dict] = []
    improved_ids: list[int] = []
    worsened_ids: list[int] = []

    for i in range(n):
        da = _dominant_dir(_events(ca[i]))
        db = _dominant_dir(_events(cb[i]))
        cid = ca[i].get("corner_id", i)
        is_better = abs(db) < abs(da)
        deltas.append({
            "corner_id": cid,
            "direction_a": round(da, 3), "direction_b": round(db, 3),
            "delta": round(db - da, 3),
            "tendency_a": _label(da), "tendency_b": _label(db),
            "improved": is_better,
        })
        if is_better:
            improved_ids.append(cid)
        elif abs(db) > abs(da):
            worsened_ids.append(cid)

    overall = float(np.mean([d["delta"] for d in deltas])) if deltas else 0.0

    parts: list[str] = []
    if improved_ids:
        s = "s" if len(improved_ids) > 1 else ""
        parts.append(f"Setup {labels[1]} reduced imbalance at corner{s} "
                     f"{', '.join(str(c) for c in improved_ids)}")
    if worsened_ids:
        s = "s" if len(worsened_ids) > 1 else ""
        parts.append(f"Setup {labels[1]} worsened balance at corner{s} "
                     f"{', '.join(str(c) for c in worsened_ids)}")

    return {
        "label_a": labels[0], "label_b": labels[1],
        "corner_deltas": deltas,
        "overall_delta": round(overall, 3),
        "improved_corners": len(improved_ids),
        "worsened_corners": len(worsened_ids),
        "recommendation": ". ".join(parts) or "No significant difference detected.",
    }

# ── E2: Driver Comparison ─────────────────────────────────────────────────

def compare_drivers(
    driver_a: dict, driver_b: dict,
    names: tuple[str, str] = ("Driver A", "Driver B"),
) -> dict:
    """Compare handling characteristics between two drivers on the same track."""
    ca, cb = _corners(driver_a), _corners(driver_b)
    n = min(len(ca), len(cb))
    details: list[dict] = []
    entry_us: dict[str, list[int]] = {names[0]: [], names[1]: []}
    exit_os: dict[str, list[int]] = {names[0]: [], names[1]: []}

    for i in range(n):
        ea, eb = _events(ca[i]), _events(cb[i])
        da, db = _dominant_dir(ea), _dominant_dir(eb)
        cid = ca[i].get("corner_id", i)
        details.append({
            "corner_id": cid,
            "direction_a": round(da, 3), "direction_b": round(db, 3),
            "tendency_a": _label(da), "tendency_b": _label(db),
        })
        for evts, name in [(ea, names[0]), (eb, names[1])]:
            for ev in evts:
                phase, d = ev.get("corner_phase", ""), ev.get("direction", 0.0)
                if phase == "entry" and d > 0.15:
                    entry_us[name].append(cid)
                elif phase == "exit" and d < -0.15:
                    exit_os[name].append(cid)

    diffs: list[str] = []
    for name in names:
        if entry_us[name]:
            ids = sorted(set(entry_us[name]))
            s = "s" if len(ids) > 1 else ""
            diffs.append(f"{name} has more entry understeer at corner{s} "
                         f"{', '.join(str(c) for c in ids)}")
        if exit_os[name]:
            ids = sorted(set(exit_os[name]))
            s = "s" if len(ids) > 1 else ""
            diffs.append(f"{name} manages exit oversteer at corner{s} "
                         f"{', '.join(str(c) for c in ids)}")
    if not diffs:
        diffs.append("Both drivers show similar handling characteristics.")

    return {
        "driver_a": names[0], "driver_b": names[1],
        "corners": details, "style_differences": diffs,
    }

# ── E3: Track Handling Profile ────────────────────────────────────────────

def build_track_profile(sessions: list[dict]) -> dict:
    """Build per-corner handling profile from multiple sessions on the same track."""
    if not sessions:
        return {"n_sessions": 0, "corners": [], "track_tendency": "unknown"}
    max_c = max((len(_corners(s)) for s in sessions), default=0)
    if max_c == 0:
        return {"n_sessions": len(sessions), "corners": [], "track_tendency": "neutral"}

    profiles: list[dict] = []
    for cid in range(max_c):
        dirs: list[float] = []
        confs: list[float] = []
        for sess in sessions:
            cs = _corners(sess)
            if cid >= len(cs):
                continue
            evts = _events(cs[cid])
            dirs.append(_dominant_dir(evts))
            cv = [e.get("confidence", 0.0) for e in evts]
            confs.append(float(np.mean(cv)) if cv else 0.0)
        if not dirs:
            continue
        labels = [_label(d) for d in dirs]
        counts: dict[str, int] = {}
        for lbl in labels:
            counts[lbl] = counts.get(lbl, 0) + 1
        dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
        freq = counts[dominant] / len(labels)
        profiles.append({
            "corner_id": cid,
            "dominant_tendency": dominant if freq > 0.6 else "variable",
            "frequency": round(freq, 2),
            "avg_confidence": round(float(np.mean(confs)), 3),
            "avg_direction": round(float(np.mean(dirs)), 3),
        })

    all_dirs = [p["avg_direction"] for p in profiles]
    return {
        "n_sessions": len(sessions),
        "corners": profiles,
        "track_tendency": _label(float(np.mean(all_dirs)) if all_dirs else 0.0),
    }

# ── E4: Handling vs Lap-Time Correlation ──────────────────────────────────

def handling_lap_time_correlation(
    session_result: dict, lap_times: dict[int, float],
) -> dict:
    """Correlate per-corner handling severity with lap time.

    Since the runner produces best-lap-only data, this ranks corners by
    severity * confidence and reports those most likely to cost time.
    """
    cs = _corners(session_result)
    if not cs:
        return {"correlation": 0.0, "p_significant": False,
                "interpretation": "No handling data available.",
                "worst_corners": []}

    scores: list[tuple[int, float]] = []
    for c in cs:
        evts = _events(c)
        sc = sum(abs(e.get("direction", 0.0)) * e.get("confidence", 0.0) for e in evts)
        scores.append((c.get("corner_id", 0), sc))
    total = sum(s for _, s in scores)

    # Attempt correlation with enough laps
    times = list(lap_times.values())
    corr, sig = 0.0, False
    if len(times) >= 5 and total > 0:
        with np.errstate(invalid="ignore"):
            r = np.corrcoef(np.full(len(times), total), times)[0, 1]
        corr = 0.0 if np.isnan(r) else float(r)
        sig = abs(corr) > 0.3

    scores.sort(key=lambda x: x[1], reverse=True)
    worst = [cid for cid, sc in scores[:3] if sc > 0]

    if total > 0.5:
        interp = f"Handling issues detected (total severity {total:.2f})"
        if worst:
            interp += f"; corners {', '.join(str(c) for c in worst)} most affected"
    else:
        interp = "Handling is clean; minimal time loss expected."

    return {
        "correlation": round(corr, 3), "p_significant": sig,
        "interpretation": interp, "worst_corners": worst,
    }
