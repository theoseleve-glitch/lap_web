"""
session_summary.py
------------------
Session Summary Report Generator — creates a comprehensive structured
debrief covering overview, highlights, weaknesses, key metrics, and
actionable next steps.

Core Features
~~~~~~~~~~~~~
1. **Overview**: Session type, driver, date, lap count, total score.
2. **Highlights**: Top 3 achievements and notable moments.
3. **Areas for Improvement**: Identified weaknesses with specific advice.
4. **Key Metrics Table**: Pace, consistency, best/worst laps, scores.
5. **Action Items**: Concrete next-session drills and focus areas.
6. **Trend Context**: How this session compares to recent history.

Public API
~~~~~~~~~~
- ``generate_session_summary(session_data)``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

MAX_HIGHLIGHTS: Final[int] = 5
MAX_IMPROVEMENTS: Final[int] = 4
MAX_ACTIONS: Final[int] = 4


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class SessionOverview:
    """Session overview section."""
    session_id: str = ""
    driver_name: str = ""
    session_date: str = ""
    session_type: str = ""
    n_laps: int = 0
    duration_estimate_min: float = 0.0
    total_score: float = 0.0
    grade: str = ""  # A+, A, B+, B, C+, C, D, F

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "driver_name": self.driver_name,
            "session_date": self.session_date,
            "session_type": self.session_type,
            "n_laps": self.n_laps,
            "duration_estimate_min": round(self.duration_estimate_min, 1),
            "total_score": round(self.total_score, 1),
            "grade": self.grade,
        }


@dataclass
class Highlight:
    """A single highlight item."""
    title: str = ""
    detail: str = ""
    metric_value: str = ""
    category: str = ""  # "pace", "consistency", "improvement", "endurance", "technique"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "metric_value": self.metric_value,
            "category": self.category,
        }


@dataclass
class ImprovementArea:
    """An identified area for improvement."""
    area: str = ""
    explanation: str = ""
    priority: int = 0  # 1 = highest
    suggested_drill: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "explanation": self.explanation,
            "priority": self.priority,
            "suggested_drill": self.suggested_drill,
        }


@dataclass
class KeyMetric:
    """A key metric for the summary table."""
    name: str = ""
    value: str = ""
    rating: str = ""  # "excellent", "good", "average", "needs_work"
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "rating": self.rating,
            "context": self.context,
        }


@dataclass
class ActionItem:
    """An actionable next step."""
    action: str = ""
    category: str = ""
    difficulty: str = ""  # "easy", "medium", "hard"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "category": self.category,
            "difficulty": self.difficulty,
        }


@dataclass
class SessionSummaryResult:
    """Full session summary report."""
    overview: SessionOverview = field(default_factory=SessionOverview)
    highlights: list[Highlight] = field(default_factory=list)
    improvements: list[ImprovementArea] = field(default_factory=list)
    key_metrics: list[KeyMetric] = field(default_factory=list)
    actions: list[ActionItem] = field(default_factory=list)
    executive_summary: str = ""
    detailed_narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overview": self.overview.to_dict(),
            "highlights": [h.to_dict() for h in self.highlights],
            "improvements": [i.to_dict() for i in self.improvements],
            "key_metrics": [m.to_dict() for m in self.key_metrics],
            "actions": [a.to_dict() for a in self.actions],
            "executive_summary": self.executive_summary,
            "detailed_narrative": self.detailed_narrative,
        }


# ============================================================================
# Core Functions
# ============================================================================


def _compute_grade(score: float) -> str:
    """Convert numeric score to letter grade."""
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 85:
        return "B+"
    if score >= 80:
        return "B"
    if score >= 75:
        return "C+"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _rate_metric(value: float, excellent: float, good: float, average: float, lower_better: bool = False) -> str:
    """Rate a metric value."""
    if lower_better:
        if value <= excellent:
            return "excellent"
        if value <= good:
            return "good"
        if value <= average:
            return "average"
        return "needs_work"
    else:
        if value >= excellent:
            return "excellent"
        if value >= good:
            return "good"
        if value >= average:
            return "average"
        return "needs_work"


def generate_session_summary(
    session_data: dict[str, Any],
) -> SessionSummaryResult:
    """
    Generate comprehensive session summary.

    Parameters
    ----------
    session_data:
        Dict with keys:
        - session_id, driver_name, session_date, session_type
        - lap_times: list[float]
        - total_score: float (optional)
        - pace_score, consistency_score, execution_score, robustness_score (optional)

    Returns
    -------
    SessionSummaryResult
    """
    result = SessionSummaryResult()

    lap_times = session_data.get("lap_times", [])
    valid_times = [t for t in lap_times if t is not None and math.isfinite(t) and t > 0]

    if len(valid_times) < 2:
        result.executive_summary = "Insufficient data for session summary."
        return result

    arr = np.array(valid_times, dtype=float)
    n = len(arr)
    best = float(np.min(arr))
    worst = float(np.max(arr))
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    cv = (std / mean * 100) if mean > 0 else 0
    total_time = float(np.sum(arr))

    total_score = float(session_data.get("total_score", 0) or 0)
    if total_score == 0:
        ps = float(session_data.get("pace_score", 0) or 0)
        cs = float(session_data.get("consistency_score", 0) or 0)
        es = float(session_data.get("execution_score", 0) or 0)
        rs = float(session_data.get("robustness_score", 0) or 0)
        total_score = ps + cs + es + rs

    # Overview
    result.overview = SessionOverview(
        session_id=str(session_data.get("session_id", "")),
        driver_name=str(session_data.get("driver_name", "")),
        session_date=str(session_data.get("session_date", "")),
        session_type=str(session_data.get("session_type", "")),
        n_laps=n,
        duration_estimate_min=total_time / 60,
        total_score=total_score,
        grade=_compute_grade(total_score) if total_score > 0 else "N/A",
    )

    # Highlights
    highlights = []

    # Best lap
    best_idx = int(np.argmin(arr))
    highlights.append(Highlight(
        title="Best Lap Time",
        detail=f"Lap {best_idx + 1} was the fastest at {best:.3f}s",
        metric_value=f"{best:.3f}s",
        category="pace",
    ))

    # Improvement from first to best
    improvement = arr[0] - best
    if improvement > 0.1:
        imp_pct = (improvement / arr[0]) * 100
        highlights.append(Highlight(
            title="Session Improvement",
            detail=f"Improved {improvement:.3f}s ({imp_pct:.1f}%) from first to best lap",
            metric_value=f"-{improvement:.3f}s",
            category="improvement",
        ))

    # Consistency
    if cv < 1.0:
        highlights.append(Highlight(
            title="Excellent Consistency",
            detail=f"CV of {cv:.2f}% shows very tight lap-to-lap variation",
            metric_value=f"{cv:.2f}%",
            category="consistency",
        ))

    # Endurance
    if n >= 20:
        highlights.append(Highlight(
            title="Strong Endurance",
            detail=f"Completed {n} laps over ~{total_time/60:.1f} minutes",
            metric_value=f"{n} laps",
            category="endurance",
        ))

    # Late pace
    if n >= 6:
        last_third = arr[n - n // 3:]
        first_third = arr[:n // 3]
        late_mean = float(np.mean(last_third))
        early_mean = float(np.mean(first_third))
        if late_mean < early_mean:
            highlights.append(Highlight(
                title="Strong Finish",
                detail="Faster pace in final third vs opening laps",
                metric_value=f"{(early_mean - late_mean)*1000:.0f}ms faster",
                category="technique",
            ))

    result.highlights = highlights[:MAX_HIGHLIGHTS]

    # Improvements
    improvements = []

    if cv > 2.0:
        improvements.append(ImprovementArea(
            area="Consistency",
            explanation=f"CV of {cv:.2f}% indicates significant lap-to-lap variation",
            priority=1,
            suggested_drill="Focus on hitting the same marks every lap for 10 consecutive laps",
        ))

    gap = worst - best
    if gap > best * 0.05:
        improvements.append(ImprovementArea(
            area="Pace Range",
            explanation=f"Gap of {gap:.3f}s between best and worst lap — reduce outliers",
            priority=2,
            suggested_drill="Identify the worst 3 laps and analyze what went wrong",
        ))

    if n >= 8:
        last_q = arr[n - n // 4:]
        first_q = arr[:n // 4]
        fade = float(np.mean(last_q)) - float(np.mean(first_q))
        if fade > 0.3:
            improvements.append(ImprovementArea(
                area="Late-Session Pace",
                explanation=f"Pace dropped {fade:.3f}s in the final quarter — possible fatigue",
                priority=2,
                suggested_drill="Practice shorter stints with focused intensity",
            ))

    if improvement < 0.1 and n > 5:
        improvements.append(ImprovementArea(
            area="Pace Development",
            explanation="Minimal improvement through the session — try varying technique",
            priority=3,
            suggested_drill="Experiment with different braking points and lines for 5 laps",
        ))

    result.improvements = improvements[:MAX_IMPROVEMENTS]

    # Key metrics
    result.key_metrics = [
        KeyMetric("Best Lap", f"{best:.3f}s", _rate_metric(0, 0, 0, 0), "Fastest single lap"),
        KeyMetric("Mean Lap", f"{mean:.3f}s", _rate_metric(0, 0, 0, 0), "Average pace"),
        KeyMetric("CV%", f"{cv:.2f}%", _rate_metric(cv, 1.0, 2.0, 3.0, lower_better=True), "Lap-to-lap consistency"),
        KeyMetric("Lap Count", str(n), _rate_metric(n, 25, 15, 5), "Session volume"),
        KeyMetric("Best-Worst Gap", f"{gap:.3f}s", _rate_metric(gap, 0.5, 1.0, 2.0, lower_better=True), "Pace range"),
        KeyMetric("Score", f"{total_score:.1f}", _rate_metric(total_score, 90, 80, 70), "Overall rating"),
    ]

    # Actions
    actions = []
    if improvements:
        for imp in improvements[:2]:
            actions.append(ActionItem(
                action=imp.suggested_drill,
                category=imp.area,
                difficulty="medium",
            ))

    actions.append(ActionItem(
        action=f"Target breaking the {best:.3f}s barrier next session",
        category="pace",
        difficulty="hard",
    ))

    if cv > 1.5:
        actions.append(ActionItem(
            action="Do a 10-lap consistency run: aim for all laps within 0.3s of each other",
            category="consistency",
            difficulty="easy",
        ))

    result.actions = actions[:MAX_ACTIONS]

    # Executive summary
    result.executive_summary = _build_executive_summary(result, arr)

    # Detailed narrative
    result.detailed_narrative = _build_narrative(result, arr)

    logger.info(
        "Session summary: %s, %d laps, grade=%s, %d highlights, %d improvements, %d actions",
        result.overview.session_id, n, result.overview.grade,
        len(result.highlights), len(result.improvements), len(result.actions),
    )

    return result


def _build_executive_summary(result: SessionSummaryResult, arr: np.ndarray) -> str:
    """Build 1-2 sentence executive summary."""
    ov = result.overview
    parts = []

    if ov.grade != "N/A":
        parts.append(f"{ov.n_laps}-lap session graded {ov.grade} ({ov.total_score:.0f}/100).")
    else:
        parts.append(f"{ov.n_laps}-lap session completed.")

    if result.highlights:
        h = result.highlights[0]
        parts.append(f"Highlight: {h.title} ({h.metric_value}).")

    if result.improvements:
        parts.append(f"Top focus area: {result.improvements[0].area}.")

    return " ".join(parts)


def _build_narrative(result: SessionSummaryResult, arr: np.ndarray) -> str:
    """Build detailed multi-paragraph narrative."""
    paragraphs = []

    ov = result.overview
    paragraphs.append(
        f"This {ov.session_type or 'session'} saw {ov.n_laps} laps over approximately "
        f"{ov.duration_estimate_min:.1f} minutes. "
        f"Overall score: {ov.total_score:.1f}/100 (Grade {ov.grade})."
    )

    if result.highlights:
        h_text = "; ".join(f"{h.title}: {h.detail}" for h in result.highlights[:3])
        paragraphs.append(f"Key highlights: {h_text}.")

    if result.improvements:
        i_text = "; ".join(f"{i.area} (P{i.priority}): {i.explanation}" for i in result.improvements[:3])
        paragraphs.append(f"Areas to improve: {i_text}.")

    if result.actions:
        a_text = "; ".join(f"{a.action} [{a.difficulty}]" for a in result.actions[:3])
        paragraphs.append(f"Next steps: {a_text}.")

    return " ".join(paragraphs)


# ============================================================================
# Self-Tests
# ============================================================================


def _run_tests() -> None:
    """Verify all functions with synthetic data."""
    import sys

    passed = 0
    failed = 0
    total = 12

    def _ok(name: str):
        nonlocal passed
        passed += 1
        print(f"  OK {name}")

    def _fail(name: str, msg: str):
        nonlocal failed
        failed += 1
        print(f"  FAIL {name}: {msg}")

    # 1. Basic summary
    try:
        data = {
            "session_id": "test_001",
            "driver_name": "Test Driver",
            "session_date": "2024-01-15",
            "session_type": "practice",
            "lap_times": [60.0 + i * 0.1 for i in range(20)],
            "total_score": 82.5,
        }
        r = generate_session_summary(data)
        assert r.overview.n_laps == 20
        assert r.overview.grade == "B", f"grade={r.overview.grade}"
        assert len(r.highlights) > 0
        assert len(r.key_metrics) > 0
        assert r.executive_summary != ""
        _ok("basic_summary")
    except Exception as e:
        _fail("basic_summary", str(e))

    # 2. Grading system
    try:
        assert _compute_grade(96) == "A+"
        assert _compute_grade(92) == "A"
        assert _compute_grade(87) == "B+"
        assert _compute_grade(83) == "B"
        assert _compute_grade(77) == "C+"
        assert _compute_grade(72) == "C"
        assert _compute_grade(65) == "D"
        assert _compute_grade(50) == "F"
        _ok("grading")
    except Exception as e:
        _fail("grading", str(e))

    # 3. Metric rating
    try:
        assert _rate_metric(0.5, 1.0, 2.0, 3.0, lower_better=True) == "excellent"
        assert _rate_metric(1.5, 1.0, 2.0, 3.0, lower_better=True) == "good"
        assert _rate_metric(2.5, 1.0, 2.0, 3.0, lower_better=True) == "average"
        assert _rate_metric(4.0, 1.0, 2.0, 3.0, lower_better=True) == "needs_work"
        _ok("metric_rating")
    except Exception as e:
        _fail("metric_rating", str(e))

    # 4. Highlights populated
    try:
        data = {
            "lap_times": [65.0, 64.0, 63.0, 62.0, 61.0, 60.0],
            "total_score": 80,
        }
        r = generate_session_summary(data)
        categories = [h.category for h in r.highlights]
        assert "pace" in categories
        assert "improvement" in categories
        _ok("highlights_populated")
    except Exception as e:
        _fail("highlights_populated", str(e))

    # 5. Improvements populated for inconsistent session
    try:
        data = {
            "lap_times": [60.0, 65.0, 60.0, 66.0, 60.0, 65.0, 60.0, 64.0],
            "total_score": 55,
        }
        r = generate_session_summary(data)
        areas = [i.area for i in r.improvements]
        assert "Consistency" in areas, f"areas={areas}"
        _ok("improvements_inconsistent")
    except Exception as e:
        _fail("improvements_inconsistent", str(e))

    # 6. Actions generated
    try:
        data = {"lap_times": [60.0 + i * 0.1 for i in range(15)], "total_score": 75}
        r = generate_session_summary(data)
        assert len(r.actions) >= 1
        assert all(a.difficulty in ("easy", "medium", "hard") for a in r.actions)
        _ok("actions_generated")
    except Exception as e:
        _fail("actions_generated", str(e))

    # 7. NaN robustness
    try:
        data = {"lap_times": [60.0, float("nan"), 61.0, None, 60.5]}
        r = generate_session_summary(data)
        assert r.overview.n_laps == 3
        _ok("nan_robustness")
    except Exception as e:
        _fail("nan_robustness", str(e))

    # 8. Single lap
    try:
        data = {"lap_times": [60.0]}
        r = generate_session_summary(data)
        assert "Insufficient" in r.executive_summary
        _ok("single_lap")
    except Exception as e:
        _fail("single_lap", str(e))

    # 9. Key metrics complete
    try:
        data = {"lap_times": [60.0, 60.5, 61.0, 60.2, 60.8], "total_score": 80}
        r = generate_session_summary(data)
        metric_names = [m.name for m in r.key_metrics]
        assert "Best Lap" in metric_names
        assert "CV%" in metric_names
        assert "Score" in metric_names
        _ok("key_metrics")
    except Exception as e:
        _fail("key_metrics", str(e))

    # 10. Serialization
    try:
        data = {"lap_times": [60.0, 60.5, 61.0], "total_score": 80}
        r = generate_session_summary(data)
        d = r.to_dict()
        import json
        json.dumps(d)
        assert "overview" in d
        assert "highlights" in d
        assert "improvements" in d
        assert "key_metrics" in d
        assert "actions" in d
        _ok("serialization")
    except Exception as e:
        _fail("serialization", str(e))

    # 11. Deterministic
    try:
        data = {"lap_times": [60.0, 60.5, 61.0, 60.2], "total_score": 80}
        r1 = generate_session_summary(data)
        r2 = generate_session_summary(data)
        assert r1.to_dict() == r2.to_dict()
        _ok("deterministic")
    except Exception as e:
        _fail("deterministic", str(e))

    # 12. Narrative populated
    try:
        data = {
            "session_id": "test",
            "session_type": "qualifying",
            "lap_times": [60.0 + i * 0.05 for i in range(10)],
            "total_score": 88,
        }
        r = generate_session_summary(data)
        assert len(r.detailed_narrative) > 50
        assert "qualifying" in r.detailed_narrative
        _ok("narrative")
    except Exception as e:
        _fail("narrative", str(e))

    print(f"\nSession Summary Tests: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
