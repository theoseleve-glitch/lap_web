"""Release gate — turns the validated research stack into a release-decision system.

The classifier (``classifier.py``) emits informational warnings. The
release gate is the binding decision layer:

  - PASS : no warning above the configurable per-class thresholds, no
           planner invariant violated
  - WARN : at least one quality metric exceeds its WARN band, no FAIL conditions
  - FAIL : any planner invariant violated OR any quality metric exceeds
           its FAIL band

The gate is config-driven. Track-class × vehicle-class threshold
differences live in JSON (``data/release_thresholds.json``), not in
code. The "Spa 60.2 vs 60.0" issue is fixed by configuring a different
fallback threshold for ``flat × TouringCar``, not by loosening the
global default.

Resolution rule for thresholds (most-specific wins):

  1. ``by_track_x_vehicle["{track_class},{vehicle_class}"]``
  2. ``by_vehicle_class[vehicle_class]``
  3. ``by_track_class[track_class]``
  4. ``default``

Each level can override individual keys; missing keys inherit from
the next level.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from track_surface.validation.metrics import SessionMetrics

logger = logging.getLogger(__name__)


# ── Threshold profile ────────────────────────────────────────


@dataclass(frozen=True)
class ThresholdProfile:
    """All quality thresholds for a single (track_class, vehicle_class) bucket.

    All values have explicit semantics. ``warn`` thresholds trip a WARN
    on the corresponding check; ``fail`` thresholds trip a FAIL.
    """
    # ── Lambda quality ───────────────────────────────────────
    lambda_band: tuple[float, float] = (0.6, 1.6)
    lambda_in_band_pct_warn: float = 50.0   # below this → WARN

    # ── Field / observability ───────────────────────────────
    min_field_coverage_pct_warn: float = 5.0
    min_accept_pct_warn: float = 30.0
    min_accept_pct_fail: float = 10.0

    # ── Bucket fallback ─────────────────────────────────────
    max_fallback_depth_2_pct_warn: float = 30.0
    max_fallback_depth_2_pct_fail: float = 60.0

    # ── Transition contamination (NEW gate output) ─────────
    max_transition_pct_warn: float = 20.0
    max_transition_pct_fail: float = 40.0

    # ── Structure / racing line ─────────────────────────────
    racing_line_lift_min_warn: float = -0.05  # below → WARN
    racing_line_lift_min_fail: float = -0.10  # below → FAIL (clearly inverted)

    # ── Stability ───────────────────────────────────────────
    max_lap_to_lap_std_warn: float = 0.20

    # ── Tire model ──────────────────────────────────────────
    max_fy_residual_std_n_warn: float = 3000.0

    # ── Bucket health ───────────────────────────────────────
    min_bucket_active_warn: int = 2
    min_bucket_active_fail: int = 1

    # ── Provenance ──────────────────────────────────────────
    description: str = ""

    def overlay(self, partial: dict[str, Any]) -> "ThresholdProfile":
        """Return a new profile with `partial`'s keys overriding this one's.

        Used by the resolution path: start from ``default``, layer
        ``by_track_class`` over it, then ``by_vehicle_class``, then
        ``by_track_x_vehicle``.
        """
        if not partial:
            return self
        # Special-case lambda_band → tuple
        d = dict(partial)
        if "lambda_band" in d and isinstance(d["lambda_band"], list):
            d["lambda_band"] = tuple(d["lambda_band"])
        valid_keys = {f for f in self.__dataclass_fields__.keys()}
        unknown = set(d.keys()) - valid_keys
        if unknown:
            raise ValueError(
                f"Unknown threshold keys in overlay: {sorted(unknown)}"
            )
        return replace(self, **d)


# ── Threshold registry (loaded from JSON) ────────────────────


@dataclass
class ReleaseThresholds:
    """Collection of threshold profiles with class-based overrides."""
    default: ThresholdProfile = field(default_factory=ThresholdProfile)
    by_track_class: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_vehicle_class: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_track_x_vehicle: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolve(
        self,
        *,
        track_class: str,
        vehicle_class: str,
    ) -> ThresholdProfile:
        """Resolve a (track_class, vehicle_class) combo to a single profile.

        Layered most-specific-wins: ``default → by_track_class →
        by_vehicle_class → by_track_x_vehicle``. Each layer's keys
        override the previous layer's. Missing keys inherit.
        """
        profile = self.default
        # Layer 1: track class
        track_partial = self.by_track_class.get(track_class, {})
        profile = profile.overlay(track_partial)
        # Layer 2: vehicle class
        vehicle_partial = self.by_vehicle_class.get(vehicle_class, {})
        profile = profile.overlay(vehicle_partial)
        # Layer 3: most specific
        cross_key = f"{track_class},{vehicle_class}"
        cross_partial = self.by_track_x_vehicle.get(cross_key, {})
        profile = profile.overlay(cross_partial)
        return profile

    @classmethod
    def from_json(cls, path: str | Path) -> "ReleaseThresholds":
        """Load thresholds from a JSON file. Missing file → defaults."""
        p = Path(path)
        if not p.is_file():
            logger.warning("Release thresholds file not found at %s — using defaults", p)
            return cls()
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("Release thresholds root must be a JSON object")
        version = raw.get("version", 1)
        if version != 1:
            raise ValueError(f"Unsupported release thresholds version: {version}")

        default_partial = raw.get("default", {})
        default = ThresholdProfile().overlay(default_partial)
        return cls(
            default=default,
            by_track_class=dict(raw.get("by_track_class", {})),
            by_vehicle_class=dict(raw.get("by_vehicle_class", {})),
            by_track_x_vehicle=dict(raw.get("by_track_x_vehicle", {})),
        )


# ── Release decision model ───────────────────────────────────


class ReleaseDecision(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

    def is_at_least(self, other: "ReleaseDecision") -> bool:
        order = {ReleaseDecision.PASS: 0, ReleaseDecision.WARN: 1, ReleaseDecision.FAIL: 2}
        return order[self] >= order[other]


@dataclass(frozen=True)
class ReleaseCheck:
    """One evaluated check on one session."""
    name: str                  # e.g. "lambda_in_band"
    subsystem: str             # e.g. "tire_model" | "field" | "planner" | ...
    decision: ReleaseDecision
    metric: str
    value: float
    threshold: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


@dataclass
class ReleaseSessionResult:
    """All checks for one session, with overall verdict."""
    dataset_id: str
    track_class: str
    vehicle_class: str
    profile_description: str
    decision: ReleaseDecision
    checks: list[ReleaseCheck]
    n_pass: int
    n_warn: int
    n_fail: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "track_class": self.track_class,
            "vehicle_class": self.vehicle_class,
            "profile_description": self.profile_description,
            "decision": self.decision.value,
            "n_pass": self.n_pass,
            "n_warn": self.n_warn,
            "n_fail": self.n_fail,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class ReleaseReport:
    """Aggregate release report across all sessions."""
    decision: ReleaseDecision
    n_sessions: int
    n_pass: int
    n_warn: int
    n_fail: int
    sessions: list[ReleaseSessionResult]
    generated_at: str
    smoke_mode: bool = False
    top_failures: list[str] = field(default_factory=list)
    top_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "decision": self.decision.value,
            "n_sessions": self.n_sessions,
            "n_pass": self.n_pass,
            "n_warn": self.n_warn,
            "n_fail": self.n_fail,
            "smoke_mode": self.smoke_mode,
            "top_failures": list(self.top_failures),
            "top_warnings": list(self.top_warnings),
            "sessions": [s.to_dict() for s in self.sessions],
        }

    @property
    def exit_code(self) -> int:
        """Suitable for ``sys.exit()`` — 0 = PASS, 1 = WARN, 2 = FAIL."""
        return {
            ReleaseDecision.PASS: 0,
            ReleaseDecision.WARN: 1,
            ReleaseDecision.FAIL: 2,
        }[self.decision]


# ── Per-session evaluation ───────────────────────────────────


def _aggregate_decision(checks: list[ReleaseCheck]) -> ReleaseDecision:
    if any(c.decision == ReleaseDecision.FAIL for c in checks):
        return ReleaseDecision.FAIL
    if any(c.decision == ReleaseDecision.WARN for c in checks):
        return ReleaseDecision.WARN
    return ReleaseDecision.PASS


def _check(
    *, name: str, subsystem: str, value: float, threshold: float,
    decision: ReleaseDecision, message: str,
) -> ReleaseCheck:
    return ReleaseCheck(
        name=name, subsystem=subsystem, decision=decision,
        metric=name, value=float(value), threshold=float(threshold),
        message=message,
    )


def evaluate_session(
    metrics: SessionMetrics,
    profile: ThresholdProfile,
    *,
    track_class: str | None = None,
    vehicle_class: str | None = None,
) -> ReleaseSessionResult:
    """Run all release checks for one session and return the verdict.

    Hard FAILs (no threshold can override them):
      - planner invariant: robust mean μ > nominal mean μ
      - planner invariant: exploitable mean μ > nominal mean μ
      - pipeline exception (catastrophic)

    Threshold-driven checks: see ThresholdProfile fields.

    track_class / vehicle_class are recorded in the result for
    traceability. If omitted, falls back to attribute-based detection
    (handy for tests that synthesize SessionMetrics directly).
    """
    checks: list[ReleaseCheck] = []
    track_cls = track_class or _track_class_for(metrics)
    vehicle_cls = vehicle_class or _vehicle_class_for(metrics)

    # ── Pipeline succeeded at all ────────────────────────────
    if not metrics.pipeline_succeeded:
        checks.append(_check(
            name="pipeline_succeeded", subsystem="harness",
            value=0.0, threshold=1.0,
            decision=ReleaseDecision.FAIL,
            message=f"Pipeline did not produce a result: {metrics.exception or 'no lambda recovered'}",
        ))
        return ReleaseSessionResult(
            dataset_id=metrics.dataset_id,
            track_class=track_cls,
            vehicle_class=vehicle_cls,
            profile_description=profile.description,
            decision=ReleaseDecision.FAIL,
            checks=checks,
            n_pass=0, n_warn=0, n_fail=1,
        )

    # ── Planner invariants — HARD FAIL, not configurable ────
    if metrics.planner_robust_mean > metrics.planner_nominal_mean + 1e-6:
        checks.append(_check(
            name="planner_robust_le_nominal", subsystem="planner",
            value=metrics.planner_robust_mean - metrics.planner_nominal_mean,
            threshold=0.0,
            decision=ReleaseDecision.FAIL,
            message="INVARIANT VIOLATED: robust mean μ exceeds nominal mean μ",
        ))
    else:
        checks.append(_check(
            name="planner_robust_le_nominal", subsystem="planner",
            value=metrics.planner_robust_mean - metrics.planner_nominal_mean,
            threshold=0.0,
            decision=ReleaseDecision.PASS,
            message="OK",
        ))

    if metrics.planner_exploitable_mean > metrics.planner_nominal_mean + 1e-6:
        checks.append(_check(
            name="planner_exploitable_le_nominal", subsystem="planner",
            value=metrics.planner_exploitable_mean - metrics.planner_nominal_mean,
            threshold=0.0,
            decision=ReleaseDecision.FAIL,
            message="INVARIANT VIOLATED: exploitable mean μ exceeds nominal mean μ",
        ))
    else:
        checks.append(_check(
            name="planner_exploitable_le_nominal", subsystem="planner",
            value=metrics.planner_exploitable_mean - metrics.planner_nominal_mean,
            threshold=0.0,
            decision=ReleaseDecision.PASS,
            message="OK",
        ))

    # ── Lambda band ──────────────────────────────────────────
    band_lo, band_hi = profile.lambda_band
    if metrics.lambda_median < band_lo or metrics.lambda_median > band_hi:
        checks.append(_check(
            name="lambda_in_band", subsystem="tire_model",
            value=metrics.lambda_median,
            threshold=band_lo if metrics.lambda_median < band_lo else band_hi,
            decision=ReleaseDecision.FAIL,
            message=f"λ median {metrics.lambda_median:.3f} outside band [{band_lo:.2f}, {band_hi:.2f}]",
        ))
    elif metrics.lambda_in_band_pct < profile.lambda_in_band_pct_warn:
        checks.append(_check(
            name="lambda_in_band", subsystem="tire_model",
            value=metrics.lambda_in_band_pct,
            threshold=profile.lambda_in_band_pct_warn,
            decision=ReleaseDecision.WARN,
            message=f"Only {metrics.lambda_in_band_pct:.1f}% of λ inside band",
        ))
    else:
        checks.append(_check(
            name="lambda_in_band", subsystem="tire_model",
            value=metrics.lambda_in_band_pct, threshold=profile.lambda_in_band_pct_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Coverage floor ───────────────────────────────────────
    if metrics.coverage_pct < profile.min_field_coverage_pct_warn:
        checks.append(_check(
            name="coverage_floor", subsystem="field",
            value=metrics.coverage_pct,
            threshold=profile.min_field_coverage_pct_warn,
            decision=ReleaseDecision.WARN,
            message=f"Coverage {metrics.coverage_pct:.1f}% below floor {profile.min_field_coverage_pct_warn:.1f}%",
        ))
    else:
        checks.append(_check(
            name="coverage_floor", subsystem="field",
            value=metrics.coverage_pct, threshold=profile.min_field_coverage_pct_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Accept rate ──────────────────────────────────────────
    if metrics.accept_pct < profile.min_accept_pct_fail:
        checks.append(_check(
            name="accept_pct_floor", subsystem="inverse_solver",
            value=metrics.accept_pct, threshold=profile.min_accept_pct_fail,
            decision=ReleaseDecision.FAIL,
            message=f"Accept rate {metrics.accept_pct:.1f}% below FAIL floor {profile.min_accept_pct_fail:.1f}%",
        ))
    elif metrics.accept_pct < profile.min_accept_pct_warn:
        checks.append(_check(
            name="accept_pct_floor", subsystem="inverse_solver",
            value=metrics.accept_pct, threshold=profile.min_accept_pct_warn,
            decision=ReleaseDecision.WARN,
            message=f"Accept rate {metrics.accept_pct:.1f}% below WARN floor",
        ))
    else:
        checks.append(_check(
            name="accept_pct_floor", subsystem="inverse_solver",
            value=metrics.accept_pct, threshold=profile.min_accept_pct_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Bucket fallback ──────────────────────────────────────
    fb_pct = metrics.fallback_depth_2_pct
    if fb_pct >= profile.max_fallback_depth_2_pct_fail:
        checks.append(_check(
            name="fallback_pct_ceiling", subsystem="bucket",
            value=fb_pct, threshold=profile.max_fallback_depth_2_pct_fail,
            decision=ReleaseDecision.FAIL,
            message=f"{fb_pct:.1f}% of grid uses global prior (FAIL ≥ {profile.max_fallback_depth_2_pct_fail:.1f}%)",
        ))
    elif fb_pct >= profile.max_fallback_depth_2_pct_warn:
        checks.append(_check(
            name="fallback_pct_ceiling", subsystem="bucket",
            value=fb_pct, threshold=profile.max_fallback_depth_2_pct_warn,
            decision=ReleaseDecision.WARN,
            message=f"{fb_pct:.1f}% of grid uses global prior (WARN ≥ {profile.max_fallback_depth_2_pct_warn:.1f}%)",
        ))
    else:
        checks.append(_check(
            name="fallback_pct_ceiling", subsystem="bucket",
            value=fb_pct, threshold=profile.max_fallback_depth_2_pct_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Transition contamination ─────────────────────────────
    tx = metrics.transition_quarantine_pct
    if tx >= profile.max_transition_pct_fail:
        checks.append(_check(
            name="transition_ceiling", subsystem="transition_gate",
            value=tx, threshold=profile.max_transition_pct_fail,
            decision=ReleaseDecision.FAIL,
            message=f"{tx:.1f}% transition quarantine (FAIL ≥ {profile.max_transition_pct_fail:.1f}%)",
        ))
    elif tx >= profile.max_transition_pct_warn:
        checks.append(_check(
            name="transition_ceiling", subsystem="transition_gate",
            value=tx, threshold=profile.max_transition_pct_warn,
            decision=ReleaseDecision.WARN,
            message=f"{tx:.1f}% transition quarantine (WARN ≥ {profile.max_transition_pct_warn:.1f}%)",
        ))
    else:
        checks.append(_check(
            name="transition_ceiling", subsystem="transition_gate",
            value=tx, threshold=profile.max_transition_pct_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Racing line lift ─────────────────────────────────────
    rl = metrics.racing_line_lift
    if rl < profile.racing_line_lift_min_fail:
        checks.append(_check(
            name="racing_line_lift_floor", subsystem="field",
            value=rl, threshold=profile.racing_line_lift_min_fail,
            decision=ReleaseDecision.FAIL,
            message=f"Racing line lift {rl:+.3f} below FAIL floor {profile.racing_line_lift_min_fail:+.3f}",
        ))
    elif rl < profile.racing_line_lift_min_warn:
        checks.append(_check(
            name="racing_line_lift_floor", subsystem="field",
            value=rl, threshold=profile.racing_line_lift_min_warn,
            decision=ReleaseDecision.WARN,
            message=f"Racing line lift {rl:+.3f} below WARN floor {profile.racing_line_lift_min_warn:+.3f}",
        ))
    else:
        checks.append(_check(
            name="racing_line_lift_floor", subsystem="field",
            value=rl, threshold=profile.racing_line_lift_min_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Lap-to-lap stability ─────────────────────────────────
    if metrics.lap_to_lap_std > profile.max_lap_to_lap_std_warn:
        checks.append(_check(
            name="lap_to_lap_std_ceiling", subsystem="stability",
            value=metrics.lap_to_lap_std,
            threshold=profile.max_lap_to_lap_std_warn,
            decision=ReleaseDecision.WARN,
            message=f"Per-lap λ std {metrics.lap_to_lap_std:.3f} exceeds {profile.max_lap_to_lap_std_warn:.3f}",
        ))
    else:
        checks.append(_check(
            name="lap_to_lap_std_ceiling", subsystem="stability",
            value=metrics.lap_to_lap_std, threshold=profile.max_lap_to_lap_std_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Tire model residual ──────────────────────────────────
    if metrics.fy_residual_std > profile.max_fy_residual_std_n_warn:
        checks.append(_check(
            name="fy_residual_ceiling", subsystem="tire_model",
            value=metrics.fy_residual_std,
            threshold=profile.max_fy_residual_std_n_warn,
            decision=ReleaseDecision.WARN,
            message=f"Fy residual std {metrics.fy_residual_std:.0f} N exceeds {profile.max_fy_residual_std_n_warn:.0f} N",
        ))
    else:
        checks.append(_check(
            name="fy_residual_ceiling", subsystem="tire_model",
            value=metrics.fy_residual_std, threshold=profile.max_fy_residual_std_n_warn,
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Bucket actives ───────────────────────────────────────
    if metrics.bucket_active_count <= profile.min_bucket_active_fail:
        checks.append(_check(
            name="bucket_actives_floor", subsystem="bucket",
            value=float(metrics.bucket_active_count),
            threshold=float(profile.min_bucket_active_fail),
            decision=ReleaseDecision.FAIL,
            message=f"Only {metrics.bucket_active_count} active bucket(s)",
        ))
    elif metrics.bucket_active_count <= profile.min_bucket_active_warn:
        checks.append(_check(
            name="bucket_actives_floor", subsystem="bucket",
            value=float(metrics.bucket_active_count),
            threshold=float(profile.min_bucket_active_warn),
            decision=ReleaseDecision.WARN,
            message=f"Bucket activity thin: {metrics.bucket_active_count} active",
        ))
    else:
        checks.append(_check(
            name="bucket_actives_floor", subsystem="bucket",
            value=float(metrics.bucket_active_count),
            threshold=float(profile.min_bucket_active_warn),
            decision=ReleaseDecision.PASS, message="OK",
        ))

    # ── Aggregate ────────────────────────────────────────────
    decision = _aggregate_decision(checks)
    return ReleaseSessionResult(
        dataset_id=metrics.dataset_id,
        track_class=track_cls,
        vehicle_class=vehicle_cls,
        profile_description=profile.description,
        decision=decision,
        checks=checks,
        n_pass=sum(1 for c in checks if c.decision == ReleaseDecision.PASS),
        n_warn=sum(1 for c in checks if c.decision == ReleaseDecision.WARN),
        n_fail=sum(1 for c in checks if c.decision == ReleaseDecision.FAIL),
    )


# ── Suite-level evaluation ───────────────────────────────────


def evaluate_suite(
    *,
    suite_session_metrics: list[SessionMetrics],
    track_classes: dict[str, str],          # dataset_id → track_class
    vehicle_classes: dict[str, str],        # dataset_id → vehicle_class
    thresholds: ReleaseThresholds,
    smoke_mode: bool = False,
) -> ReleaseReport:
    """Evaluate every session metric and aggregate into one ReleaseReport.

    Parameters
    ----------
    suite_session_metrics : list of SessionMetrics
    track_classes : map dataset_id → "banked" | "flat" | "mixed"
    vehicle_classes : map dataset_id → "GT4" | "TouringCar" | "TCR" | "F3" | ...
    thresholds : ReleaseThresholds (typically loaded via from_json)
    smoke_mode : bookkeeping only — flagged in the report
    """
    sessions: list[ReleaseSessionResult] = []
    for m in suite_session_metrics:
        track_cls = track_classes.get(m.dataset_id, "flat")
        vehicle_cls = vehicle_classes.get(m.dataset_id, "unknown")
        profile = thresholds.resolve(
            track_class=track_cls, vehicle_class=vehicle_cls,
        )
        sr = evaluate_session(
            m, profile,
            track_class=track_cls, vehicle_class=vehicle_cls,
        )
        sessions.append(sr)

    n_pass = sum(1 for s in sessions if s.decision == ReleaseDecision.PASS)
    n_warn = sum(1 for s in sessions if s.decision == ReleaseDecision.WARN)
    n_fail = sum(1 for s in sessions if s.decision == ReleaseDecision.FAIL)

    if n_fail > 0:
        overall = ReleaseDecision.FAIL
    elif n_warn > 0:
        overall = ReleaseDecision.WARN
    else:
        overall = ReleaseDecision.PASS

    # Top failure / warning causes
    fail_causes: dict[str, int] = {}
    warn_causes: dict[str, int] = {}
    for s in sessions:
        for c in s.checks:
            if c.decision == ReleaseDecision.FAIL:
                fail_causes[c.name] = fail_causes.get(c.name, 0) + 1
            elif c.decision == ReleaseDecision.WARN:
                warn_causes[c.name] = warn_causes.get(c.name, 0) + 1
    top_failures = [
        f"{cause} ({count})"
        for cause, count in sorted(fail_causes.items(), key=lambda kv: -kv[1])
    ]
    top_warnings = [
        f"{cause} ({count})"
        for cause, count in sorted(warn_causes.items(), key=lambda kv: -kv[1])
    ]

    return ReleaseReport(
        decision=overall,
        n_sessions=len(sessions),
        n_pass=n_pass, n_warn=n_warn, n_fail=n_fail,
        sessions=sessions,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        smoke_mode=smoke_mode,
        top_failures=top_failures,
        top_warnings=top_warnings,
    )


# ── Markdown rendering ───────────────────────────────────────


def render_markdown(report: ReleaseReport) -> str:
    """Human-readable markdown summary."""
    lines: list[str] = []
    decision_emoji = {
        ReleaseDecision.PASS: "✅ PASS",
        ReleaseDecision.WARN: "⚠️  WARN",
        ReleaseDecision.FAIL: "❌ FAIL",
    }[report.decision]

    lines.append(f"# Release Gate Report — {decision_emoji}")
    lines.append("")
    lines.append(f"Generated: {report.generated_at}")
    lines.append(f"Smoke mode: {report.smoke_mode}")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- **Decision: {report.decision.value.upper()}**")
    lines.append(f"- Sessions evaluated: {report.n_sessions}")
    lines.append(f"- PASS: {report.n_pass}")
    lines.append(f"- WARN: {report.n_warn}")
    lines.append(f"- FAIL: {report.n_fail}")
    lines.append("")

    if report.top_failures:
        lines.append("## Top failure causes")
        lines.append("")
        for f in report.top_failures:
            lines.append(f"- {f}")
        lines.append("")
    if report.top_warnings:
        lines.append("## Top warning causes")
        lines.append("")
        for w in report.top_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Per-session verdicts")
    lines.append("")
    lines.append("| Decision | Dataset | Track class | Vehicle class | Pass | Warn | Fail |")
    lines.append("|----------|---------|-------------|---------------|------|------|------|")
    for s in report.sessions:
        d = {ReleaseDecision.PASS: "PASS", ReleaseDecision.WARN: "WARN", ReleaseDecision.FAIL: "FAIL"}[s.decision]
        lines.append(
            f"| {d} | `{s.dataset_id}` | {s.track_class} | {s.vehicle_class} | "
            f"{s.n_pass} | {s.n_warn} | {s.n_fail} |"
        )
    lines.append("")

    # Per-session detail (only WARN/FAIL checks)
    interesting = [s for s in report.sessions if s.decision != ReleaseDecision.PASS]
    if interesting:
        lines.append("## Per-session WARN/FAIL detail")
        lines.append("")
        for s in interesting:
            lines.append(f"### `{s.dataset_id}` ({s.track_class} / {s.vehicle_class}) — {s.decision.value.upper()}")
            lines.append(f"Profile: {s.profile_description or '(default)'}")
            lines.append("")
            for c in s.checks:
                if c.decision == ReleaseDecision.PASS:
                    continue
                lines.append(
                    f"- **{c.decision.value.upper()}** — `{c.name}` ({c.subsystem}) — "
                    f"{c.message}  (`value={c.value:.3f}` vs `threshold={c.threshold:.3f}`)"
                )
            lines.append("")

    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────


def _track_class_for(metrics: SessionMetrics) -> str:
    """Best-effort track class from the metrics record.

    SessionMetrics doesn't carry the manifest's track regime directly;
    callers using evaluate_suite should pass a per-dataset map. When
    used standalone (e.g. tests), we fall back based on observed
    bucket diagnostics or 'flat'.
    """
    return getattr(metrics, "_track_class_override", None) or "flat"


def _vehicle_class_for(metrics: SessionMetrics) -> str:
    return getattr(metrics, "_vehicle_class_override", None) or "unknown"
