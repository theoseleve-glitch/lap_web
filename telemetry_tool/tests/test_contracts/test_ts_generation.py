from pathlib import Path

from telemetry_tool.web.schemas.contracts._scripts.generate_ts import (
    generate_ts_file,
    TS_OUTPUT_PATH,
)


def test_generator_writes_typescript(tmp_path: Path):
    out = tmp_path / "contracts.ts"
    generate_ts_file(out)
    text = out.read_text()

    # Presence of the three top-level interfaces
    for name in ("SessionContract", "CoachingContract", "OptimizerContract"):
        assert f"export interface {name}" in text, f"missing interface: {name}"

    # ChannelTag enum
    assert "export enum ChannelTag" in text or "export type ChannelTag" in text
    # SourceLiteral enum/union
    for v in ("real_life", "iracing", "ac"):
        assert v in text, f"source value missing: {v}"


def test_committed_ts_up_to_date():
    """CI gate: if this fails, regenerate with:
        python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts
    """
    from telemetry_tool.web.schemas.contracts._scripts.generate_ts import (
        generate_ts_string,
    )
    fresh = generate_ts_string()
    on_disk = TS_OUTPUT_PATH.read_text()
    assert fresh == on_disk, "contracts.ts drifted — regenerate"
