"""Thin application layer over telemetry_tool.track_surface validated core.

This package owns:
  - HTTP-facing DTO translation (via web/schemas/track_surface.py)
  - Support-tier gating (SupportTierResolver, OutputGate)
  - Persistence (AnalysisRunRepository, analysis_runs table)
  - Orchestration (AnalysisOrchestrator + Celery task)

It does NOT contain physics. All numerics stay in track_surface/.
"""
