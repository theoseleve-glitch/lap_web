"""onboarding -- Track Onboarding Loop (spec: docs/superpowers/specs/2026-07-06-track-onboarding-loop-design.md).

Modules are added task-by-task per the implementation plan
(docs/superpowers/plans/2026-07-06-track-onboarding-loop.md). This package
currently provides:

  repo.py   Data-access layer over ``track_onboarding_requests`` (migration
            081): atomic-upsert dedup + conditional state writes.
"""
