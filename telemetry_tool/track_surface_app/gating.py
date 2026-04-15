"""OutputGate — enforces what each SupportTier is permitted to see.

The gate is consulted in two places:
  1. Artifact endpoints: filter the index + refuse forbidden kinds.
  2. Summary/planner/surface/uncertainty endpoints: refuse tier-inappropriate access.

Kept simple and data-driven so the contract is obvious from a table.
"""
from __future__ import annotations

from track_surface_app.domain import SupportTier

# All artifact kinds emitted by ArtifactWriter (see artifacts.py).
ALL_ARTIFACT_KINDS: tuple[str, ...] = (
    "summary",
    "surface_field",
    "confidence_heatmap",
    "planner_nominal",
    "planner_robust",
    "planner_exploitable",
    "racing_line_deltas",
    "diagnostics",
)

# Artifacts that every tier (even D) can see. Covers transparency: a user always
# sees at minimum "we tried, here's why it didn't work".
ALWAYS_PUBLIC_ARTIFACTS: frozenset[str] = frozenset({"summary", "diagnostics"})

# Additional artifacts allowed at tier C (beyond ALWAYS_PUBLIC).
_TIER_C_EXTRA: frozenset[str] = frozenset()

# Additional artifacts allowed at tier B (beyond tier C).
_TIER_B_EXTRA: frozenset[str] = frozenset({
    "surface_field",
    "confidence_heatmap",
    "planner_nominal",
    "planner_robust",
    "racing_line_deltas",
})

# Additional artifacts allowed at tier A (beyond tier B).
_TIER_A_EXTRA: frozenset[str] = frozenset({"planner_exploitable"})


# Endpoint gating (simpler, explicit table)
_ENDPOINT_TIER_ALLOWLIST: dict[str, set[SupportTier]] = {
    "summary":     {SupportTier.A, SupportTier.B, SupportTier.C, SupportTier.D},
    "surface":     {SupportTier.A, SupportTier.B, SupportTier.C},
    "planner":     {SupportTier.A, SupportTier.B},
    "uncertainty": {SupportTier.A, SupportTier.B, SupportTier.C},
    "artifacts":   {SupportTier.A, SupportTier.B, SupportTier.C, SupportTier.D},
}


def _allowed_artifacts(tier: SupportTier) -> frozenset[str]:
    if tier is SupportTier.A:
        return ALWAYS_PUBLIC_ARTIFACTS | _TIER_C_EXTRA | _TIER_B_EXTRA | _TIER_A_EXTRA
    if tier is SupportTier.B:
        return ALWAYS_PUBLIC_ARTIFACTS | _TIER_C_EXTRA | _TIER_B_EXTRA
    if tier is SupportTier.C:
        return ALWAYS_PUBLIC_ARTIFACTS | _TIER_C_EXTRA
    return ALWAYS_PUBLIC_ARTIFACTS   # tier D


class OutputGate:
    """Applies per-tier access rules to artifacts and endpoints."""

    def __init__(self, tier: SupportTier):
        self._tier = tier
        self._allowed_artifacts = _allowed_artifacts(tier)

    @property
    def tier(self) -> SupportTier:
        return self._tier

    def filter_artifact_kinds(self, kinds) -> list[str]:
        """Return only the artifact kinds this tier may see."""
        return [k for k in kinds if k in self._allowed_artifacts]

    def is_artifact_allowed(self, kind: str) -> bool:
        return kind in self._allowed_artifacts

    def is_endpoint_allowed(self, endpoint_name: str) -> bool:
        return self._tier in _ENDPOINT_TIER_ALLOWLIST.get(endpoint_name, set())
