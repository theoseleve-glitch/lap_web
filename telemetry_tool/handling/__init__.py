"""Handling balance detection: over/understeer from GPS + accelerometer data.

Package structure:
  handling/
    types.py          — CornerWindow, SessionContext, DetectorVote, FusedEvent
    calibration.py    — Per-session calibration (yaw ratio, G threshold, etc.)
    detectors/        — Individual detector implementations (registry pattern)
    fusion.py         — Bayesian fusion of detector votes
    runner.py         — Top-level entry point for pipeline integration
    cross_session.py  — Cross-session analysis (setup/driver comparison, track profile)
    ml/               — ML models (Naive Bayes, GMM, anomaly detection)
"""
