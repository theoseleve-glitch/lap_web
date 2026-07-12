"""Data-profile detector (W2.T2.1/T2.2).

Composes on top of :mod:`telemetry_tool.adapters.registry` — the profiler
decides *which engine* should process the file, not *how to parse* it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from telemetry_tool.adapters.registry import detect_format_two_pass
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


# Adapter FORMAT_NAME → SourceLiteral + suggested engine.
# Unknown FORMAT_NAMEs fall back to (REAL_LIFE, real_life_pipeline).
_PARSER_ROUTING: Final[dict[str, tuple[SourceLiteral, str]]] = {
    "racechrono": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "racechrono_rcz": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "racebox_csv": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "vbox": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "qstarz_csv": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "qstarz_binary": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "generic_csv": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "iracing_ibt": (SourceLiteral.IRACING, "sim_optimizer"),
    "iracing": (SourceLiteral.IRACING, "sim_optimizer"),
    "acc": (SourceLiteral.AC, "ac_pipeline"),
    "lmu": (SourceLiteral.AC, "ac_pipeline"),
    "f1_game": (SourceLiteral.AC, "ac_pipeline"),
    "motec": (SourceLiteral.AC, "ac_pipeline"),
    "motec_ld": (SourceLiteral.AC, "ac_pipeline"),
    "aim_xrk": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
}


def _assert_routing_keys_valid() -> None:
    """Guard against drift between the registry and this routing table.

    Called at import time — fails loudly if a key in _PARSER_ROUTING
    is not a registered adapter FORMAT_NAME.
    """
    # Lazy-import to avoid a circular dependency at module load.
    from telemetry_tool.adapters.registry import _ADAPTERS
    known = {cls.FORMAT_NAME for cls in _ADAPTERS}
    # If the registry is empty (adapters not yet imported), skip — the
    # check will run again on the next import.
    if not known:
        return
    unknown = set(_PARSER_ROUTING) - known
    if unknown:
        raise AssertionError(
            f"_PARSER_ROUTING contains FORMAT_NAMEs not in adapter registry: "
            f"{sorted(unknown)}. Known: {sorted(known)}."
        )


_assert_routing_keys_valid()

# Column-name → ChannelTag mapping. Case-insensitive substring match.
# Order matters — specific substrings (e.g. "lateral", "lat_g") should come
# before generic ones (e.g. "lat"), but since we accumulate all matching
# tags into a set, a column may legitimately produce multiple tags (e.g.
# "Lateral acceleration" → LAT_G *and* GPS via the "lat" substring).
_COL_TAGS: Final[list[tuple[str, ChannelTag]]] = [
    # Lateral acceleration variants
    ("lat_g", ChannelTag.LAT_G),
    ("latacc", ChannelTag.LAT_G),
    ("accel_lat", ChannelTag.LAT_G),
    ("lateral", ChannelTag.LAT_G),
    # Longitudinal acceleration variants
    ("lon_g", ChannelTag.LON_G),
    ("longacc", ChannelTag.LON_G),
    ("lonacc", ChannelTag.LON_G),
    ("accel_long", ChannelTag.LON_G),
    ("longitudinal", ChannelTag.LON_G),
    # Motion / dynamics
    ("yaw", ChannelTag.YAW_RATE),
    # Driver inputs — throttle (ACC uses "gas")
    ("throttle", ChannelTag.THROTTLE),
    ("gas", ChannelTag.THROTTLE),
    ("brake", ChannelTag.BRAKE),
    ("steer", ChannelTag.STEER),
    # Per-wheel (sim-only) — check these before the broader "lat"/"lon" GPS
    # sentinels so a wheel-speed column doesn't also trigger a GPS tag.
    ("wheel_spd", ChannelTag.WHEEL_SPD),
    ("wheelspeed", ChannelTag.WHEEL_SPD),
    ("shock", ChannelTag.SHOCK_DEFL),
    # GPS — intentionally last; broad "lat"/"lon" substrings that also
    # appear in acceleration columns are fine because we collect tags in
    # a set, so the same column may contribute to both GPS and LAT_G/LON_G.
    ("lat", ChannelTag.GPS),
    ("lon", ChannelTag.GPS),
]

_HEADER_SAMPLE_ROWS = 5


class DataProfile(BaseModel):
    """Declarative summary of an uploaded telemetry file.

    Populated by :class:`Profiler`.  Handlers downstream inspect
    ``suggested_engine`` to pick the right pipeline, and
    ``channels_available`` to filter detectors.
    """
    model_config = ConfigDict(frozen=True)
    source: SourceLiteral
    parser: str
    channels_available: frozenset[ChannelTag]
    suggested_engine: str
    confidence: float = Field(ge=0.0, le=1.0)
    sample_hz: float | None = None
    total_channels_detected: int | None = None


class UnknownFormatError(ValueError):
    """Raised when no adapter matches and no fallback is configured."""


class Profiler:
    """Classify an uploaded file and declare its channel set."""

    def profile(self, file_path: str | Path) -> DataProfile:
        file_path = Path(file_path)
        adapter_cls, confidence = detect_format_two_pass(str(file_path))
        if adapter_cls is None:
            raise UnknownFormatError(
                f"No adapter matched {file_path.name}. "
                "Check the supported-formats list in telemetry_tool.adapters.registry."
            )
        parser = adapter_cls.FORMAT_NAME
        source, engine = _PARSER_ROUTING.get(
            parser, (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
        )
        channels, total = self._channels_from_header(file_path, adapter_cls)
        return DataProfile(
            source=source,
            parser=parser,
            channels_available=channels,
            suggested_engine=engine,
            confidence=confidence,
            total_channels_detected=total,
        )

    def _channels_from_header(
        self, file_path: Path, adapter_cls,
    ) -> tuple[frozenset[ChannelTag], int | None]:
        """Read the first few rows to enumerate columns, then tag them.

        Falls back to ``{GPS}`` for files we can't cheaply sample.
        """
        suffix = file_path.suffix.lower()
        if suffix in {".csv", ".txt"}:
            try:
                header = pd.read_csv(
                    file_path, nrows=_HEADER_SAMPLE_ROWS, engine="python",
                    on_bad_lines="skip", skip_blank_lines=True,
                )
            except Exception:
                return frozenset({ChannelTag.GPS}), None
            columns = [str(c).lower() for c in header.columns]
            tags: set[ChannelTag] = set()
            for name in columns:
                for needle, tag in _COL_TAGS:
                    if needle in name:
                        tags.add(tag)
            if not tags:
                tags.add(ChannelTag.GPS)
            return frozenset(tags), len(columns)
        # TODO(T2.3 handoff review): this is the maximum-possible iRacing
        # channel set, not file-verified. Downstream detectors that gate on
        # channels_available may run on channels that are actually absent
        # from the .ibt and crash at parse time. Tighten by enumerating the
        # adapter's var_headers during a header-only probe before shipping.
        if suffix == ".ibt":
            return frozenset({
                ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
                ChannelTag.YAW_RATE, ChannelTag.THROTTLE, ChannelTag.BRAKE,
                ChannelTag.STEER, ChannelTag.WHEEL_SPD,
            }), None
        return frozenset({ChannelTag.GPS}), None
