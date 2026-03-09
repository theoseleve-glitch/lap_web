"""
Stage 14 — Reports
~~~~~~~~~~~~~~~~~~~~
Steps 14a–14c: driver profile generation, driving style analysis,
HTML report generation, and PDF conversion.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


# ── Step 14a: Driver profile ──────────────────────────────────────────


def run_driver_profile(
    meta: dict[str, Any],
    consistency: Optional[dict[str, Any]],
    robustness: Optional[dict[str, Any]],
    theo_metrics: dict[str, Any],
    resampled_laps: dict[int, pd.DataFrame],
    score_result: Optional[dict[str, Any]],
    lap_metrics: Optional[list[dict[str, Any]]],
    *,
    context: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    lap_to_phase: Optional[dict[int, int]] = None,
) -> dict[str, Any]:
    """Generate driver profile.

    Returns
    -------
    dict
        Driver profile data (strengths, weaknesses, recommendations).

    Raises
    ------
    ImportError
        If the ``driver_profile`` module is unavailable.
    """
    dp_mod = lazy_import("driver_profile")
    if dp_mod is None:
        raise ImportError("driver_profile unavailable")

    sess_data: dict[str, Any] = {
        "metrics": {**(consistency or {}), **(robustness or {})},
        "theoretical_metrics": theo_metrics,
        "resampled_laps": list(resampled_laps.values()),
        "score_result": score_result or {},
        "session_id": meta.get("session_id"),
        "session_date": meta.get("date"),
    }
    if lap_metrics:
        sess_data["metrics"].update(lap_metrics[0])

    return dp_mod.generate_driver_profile(
        meta.get("driver_name", "Unknown"),
        [sess_data],
        context=context,
        phases_df=phases_df,
        lap_to_phase=lap_to_phase,
        lap_metrics=lap_metrics,
    )


# ── Step 14a2: Driving style ──────────────────────────────────────────


def run_driving_style(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    lap_metrics: Optional[list[dict[str, Any]]] = None,
    corners: Optional[list[dict[str, Any]]] = None,
    corner_performances: Optional[list[dict[str, Any]]] = None,
    theo_metrics: Optional[dict[str, Any]] = None,
    per_lap_corner_metrics: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """Compute driving style features.

    Returns a dict with style_label, features, and fingerprint,
    or ``None`` if the module is unavailable or there are no laps.
    """
    ds_mod = lazy_import("driving_style")
    if ds_mod is None:
        return None
    if not resampled_laps:
        return None

    return ds_mod.compute_driving_style(
        resampled_laps,
        lap_metrics=lap_metrics,
        corners=corners,
        corner_performances=corner_performances,
        theoretical_metrics=theo_metrics,
        per_lap_corner_metrics=per_lap_corner_metrics,
    )


# ── Step 14b: HTML report ─────────────────────────────────────────────


def run_html_report(
    score_result: Optional[dict[str, Any]],
    theoretical_lap: Optional[pd.DataFrame],
    best_lap_df: Optional[pd.DataFrame],
    delta_segments: Optional[list[dict[str, Any]]],
    lap_times: Optional[list[float]],
    segment_losses: Any,
    driver_profile: Optional[dict[str, Any]],
    meta: dict[str, Any],
    out_dir: Path,
    summary: dict[str, Any],
    *,
    driver_tag: str = "",
    context: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    resampled_laps: Optional[dict[int, pd.DataFrame]] = None,
    friction_circle: Any = None,
    corner_performances: Optional[list[dict[str, Any]]] = None,
    grip_evolution: Any = None,
    data_quality: Any = None,
    theoretical_result: Any = None,
    weather_timeline: Optional[pd.DataFrame] = None,
    coaching_guide: Optional[dict[str, Any]] = None,
    corners: Optional[list[dict[str, Any]]] = None,
) -> Path:
    """Generate HTML report.

    Parameters
    ----------
    out_dir : Path
        Output directory for the HTML file.
    summary : dict
        Full pipeline summary (used to pull distance_quality, traffic,
        lap_inclusion, theoretical_metrics, grip_map, driver_style,
        coaching_v2, practice_plan, endurance, track_boundaries,
        raceline_optimization).

    Returns
    -------
    Path
        Path to the generated HTML file.

    Raises
    ------
    ImportError
        If the ``reporting_html`` module is unavailable.
    """
    rpt_html = lazy_import("reporting_html")
    if rpt_html is None:
        raise ImportError("reporting_html unavailable")

    dtag_suffix = f"_{driver_tag}" if driver_tag else ""

    # Enrich corner_performances with advanced intelligence data
    enriched_corner_perfs = _enrich_corner_perfs_for_report(
        corner_performances, corners, summary,
    )

    return rpt_html.generate_report(
        score_result=score_result,
        theoretical_lap=theoretical_lap,
        best_lap=best_lap_df,
        delta_segments=delta_segments[:20] if delta_segments else None,
        lap_times=lap_times,
        segment_losses=segment_losses,
        driver_profiles=[driver_profile] if driver_profile else None,
        session_meta=meta,
        context=context,
        phases_df=phases_df,
        output_path=out_dir / f"index{dtag_suffix}.html",
        coaching_guide=coaching_guide,
        resampled_laps=resampled_laps,
        friction_circle=friction_circle,
        corner_performances=enriched_corner_perfs,
        grip_evolution=grip_evolution,
        data_quality=data_quality,
        theoretical_result=theoretical_result,
        weather_timeline=weather_timeline,
        distance_quality=summary.get("distance_quality"),
        traffic=summary.get("traffic"),
        lap_inclusion=summary.get("lap_inclusion"),
        theoretical_metrics=summary.get("theoretical_metrics"),
        grip_map=summary.get("grip_map"),
        driver_style=summary.get("driver_style"),
        coaching_v2=summary.get("coaching_v2"),
        practice_plan=summary.get("practice_plan"),
        endurance=summary.get("endurance"),
        track_boundaries=summary.get("track_boundaries"),
        raceline_optimization=summary.get("raceline_optimization"),
    )


def _enrich_corner_perfs_for_report(
    corner_performances: Optional[list[dict[str, Any]]],
    corners: Optional[list[dict[str, Any]]],
    summary: dict[str, Any],
) -> Optional[list[dict[str, Any]]]:
    """Merge advanced intelligence data into corner performances for HTML."""
    if not corner_performances or not corners:
        return corner_performances

    try:
        aci = summary.get("advanced_corner_intelligence", {})
        risk_scores = aci.get("corner_risk_scores", [])
        risk_map = {r.get("corner_id"): r.get("risk_index", 0) for r in risk_scores}
        tl_data = summary.get("corner_timelines", [])
        tl_map = {
            (t.get("corner_id") if isinstance(t, dict) else getattr(t, "corner_id", None)): t
            for t in tl_data
        }
        corner_type_map = {
            c.get("corner_id", i): c.get("corner_type", "") for i, c in enumerate(corners)
        }
        compound_map = {
            c.get("corner_id", i): c.get("compound_id") for i, c in enumerate(corners)
        }
        setup_map = {
            c.get("corner_id", i): c.get("is_setup_corner", False) for i, c in enumerate(corners)
        }
        br_data = aci.get("brake_release_metrics", [])
        br_map = {b.get("corner_id"): b for b in br_data} if br_data else {}

        enriched = []
        for p in corner_performances:
            d = (
                p.to_dict()
                if hasattr(p, "to_dict")
                else dict(p) if isinstance(p, dict) else {"corner_id": 0}
            )
            cid = d.get("corner_id", 0)
            d["corner_type"] = corner_type_map.get(cid, "")
            d["risk_index"] = risk_map.get(cid, 0.0)
            d["compound_id"] = compound_map.get(cid)
            d["is_setup_corner"] = setup_map.get(cid, False)
            d["brake_release"] = br_map.get(cid, {})
            tl = tl_map.get(cid)
            if tl:
                d["timeline"] = (
                    tl
                    if isinstance(tl, dict)
                    else (tl.to_dict() if hasattr(tl, "to_dict") else {})
                )
            enriched.append(d)
        return enriched
    except Exception:
        logger.debug("Corner perf enrichment failed, using raw data", exc_info=True)
        return corner_performances


# ── Step 14c: PDF report ──────────────────────────────────────────────


def run_pdf_report(
    html_path: Optional[Path],
    out_dir: Path,
    *,
    driver_tag: str = "",
) -> Optional[Path]:
    """Generate PDF from HTML.

    Returns the PDF path, or ``None`` if the module is unavailable
    or no HTML path was provided.
    """
    rpt_pdf = lazy_import("reporting_pdf")
    if rpt_pdf is None or html_path is None:
        return None

    dtag_suffix = f"_{driver_tag}" if driver_tag else ""
    return rpt_pdf.generate_pdf_from_html(
        html_path,
        out_dir / f"session_report{dtag_suffix}.pdf",
    )
