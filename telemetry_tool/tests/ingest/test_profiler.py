from pathlib import Path

import pytest

from telemetry_tool.ingest.profiler import Profiler, DataProfile
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


FIX = Path(__file__).parent / "fixtures"


def test_racechrono_csv_profiles_to_real_life():
    profile = Profiler().profile(FIX / "sample_racechrono.csv")
    assert isinstance(profile, DataProfile)
    assert profile.source is SourceLiteral.REAL_LIFE
    assert profile.parser == "racechrono"
    assert profile.confidence >= 0.9
    assert {ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G}.issubset(profile.channels_available)
    assert profile.suggested_engine == "real_life_pipeline"


def test_iracing_ibt_profiles_to_sim_optimizer():
    profile = Profiler().profile(FIX / "sample_iracing.ibt")
    assert profile.source is SourceLiteral.IRACING
    assert profile.parser == "iracing_ibt"
    assert profile.suggested_engine == "sim_optimizer"
    assert profile.confidence >= 0.9
    assert {ChannelTag.THROTTLE, ChannelTag.BRAKE, ChannelTag.STEER}.issubset(
        profile.channels_available,
    )


def test_ac_csv_profiles_to_ac_pipeline():
    profile = Profiler().profile(FIX / "sample_ac.csv")
    assert profile.source is SourceLiteral.AC
    assert profile.suggested_engine == "ac_pipeline"
    assert profile.confidence >= 0.9
    assert {ChannelTag.THROTTLE, ChannelTag.BRAKE}.issubset(profile.channels_available)


def test_unknown_extension_raises():
    tmp = FIX / "garbage.bin"
    tmp.write_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(ValueError):
        Profiler().profile(tmp)
    tmp.unlink()
