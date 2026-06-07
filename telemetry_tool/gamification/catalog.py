"""Gamification tuning catalog — every threshold/XP value in ONE place.

Recalibration is a deploy, not a migration (spec §7). Before each phase
ships, calibrate against production distributions targeting: median new
driver earns first bronze stars in session 1, first silver within 3
sessions, Rookie->Club within 2-4 weeks of weekly driving.
"""
from __future__ import annotations

CATALOG_VERSION = 1

# ── Corner score ──────────────────────────────────────────────
# corner_score = 100 * (1 - clamp(median_time_loss_ms / TIME_LOSS_FULL_PENALTY_MS, 0, 1))
# time_loss_ms comes straight from corner_metrics (loss vs theoretical).
TIME_LOSS_FULL_PENALTY_MS = 1500.0

# ── Star tiers (on corner_score 0-100) ────────────────────────
STAR_BRONZE_SCORE = 60.0
STAR_SILVER_SCORE = 75.0   # must be hit in TWO separate sessions
STAR_GOLD_SCORE = 85.0
SILVER_SESSIONS_REQUIRED = 2

# ── Star XP ───────────────────────────────────────────────────
XP_STAR = {"bronze": 25, "silver": 75, "gold": 150}

TIER_ORDER = ["none", "bronze", "silver", "gold"]


def tier_rank(tier: str) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else 0


# ── Pit Pass + comeback (Phase 2b) ────────────────────────────
PIT_PASS_EARN_WEEKS = 4     # +1 banked freeze each 4-week streak milestone
PIT_PASS_CAP = 3
COMEBACK_WEEKS = 3          # >= this many weeks away triggers a Shakedown
COMEBACK_XP_MULTIPLIER = 2
