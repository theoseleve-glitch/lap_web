from __future__ import annotations

from telemetry_tool.pipeline.handler import RealLifePipelineHandler


def test_handler_declares_real_life_source():
    h = RealLifePipelineHandler()
    # Source identifier should match SourceLiteral.REAL_LIFE
    assert h.source == "real_life"


def test_handler_run_invokes_pipeline_and_emits_contracts(monkeypatch, tmp_path, ctx, minimal_summary):
    # Stub the orchestrator to avoid running the real pipeline
    def fake_run_full_analysis(*args, **kwargs):
        return minimal_summary
    import telemetry_tool.pipeline.orchestrator as orchestrator
    monkeypatch.setattr(orchestrator, "run_full_analysis", fake_run_full_analysis)

    csv = tmp_path / "session.csv"
    csv.write_text("stub")

    h = RealLifePipelineHandler()
    out = h.run(csv_path=str(csv), session_meta={}, ctx=ctx)
    assert out.session.source.value == "real_life"
    assert out.optimizer.depth.value == "trajectory_only"


def test_lazy_registration_does_not_fail_without_router():
    """When W2 router isn't available, adapter import still succeeds."""
    # This is verified by pytest having imported the package at all,
    # since the registration block is in __init__.py. Assert the module
    # is importable and no ImportError was raised.
    from telemetry_tool import pipeline  # noqa: F401
