# Universal Telemetry Ingest — Design Spec

**Date**: 2026-03-19
**Status**: Approved (rev 2 — post-review fixes)
**Scope**: Extend the existing `telemetry_tool/adapters/` system with streaming support, new format parsers, and enhanced detection for all supported telemetry data sources.

---

## 1. Problem Statement

The system has an existing adapter registry (`telemetry_tool/adapters/`) with 5 registered adapters (RaceChrono CSV, iRacing CSV, ACC CSV, MoTeC CSV, GenericCSV). Stage 01 of the 14-stage pipeline already calls `adapters.parse_file()` as its primary ingest path, with `io_racechrono` as fallback.

However, several gaps remain:
- **No binary format support**: `.ibt` (iRacing native), `.ld`/`.ldx` (MoTeC native), `.xrk` (AiM) require dedicated binary parsers — the existing adapters only handle CSV exports from these tools
- **Missing real-world formats**: VBOX `.vbo`, RaceBox CSV, and Qstarz CSV have no adapters
- **No streaming**: All adapters load entire files into memory via `pd.read_csv()`, which fails on large files (endurance sessions, high-rate sim telemetry)
- **No content-based detection**: Detection relies solely on header-line parsing, missing binary formats entirely

## 2. Goals

- Add streaming capability to `BaseAdapter` so large files stay under <1 GB peak memory
- Add new adapters for VBOX, RaceBox CSV, Qstarz CSV, iRacing `.ibt` binary, MoTeC `.ld` binary
- Enhance format detection with two-pass (extension → content probe) for binary format support
- Maintain backward compatibility — `s01_ingest.py` canonical→RaceChrono reverse mapping stays untouched

## 3. Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Package location | Extend `telemetry_tool/adapters/` in-place | System already exists with 5 adapters, registry, and pipeline integration. Creating a new package would duplicate 60% of existing code. |
| Base class | Extend existing `BaseAdapter` ABC (not Protocol) | 5 concrete adapters already inherit `BaseAdapter`. Adding Protocol would create two incompatible registration mechanisms. |
| Binary format strategy | Hybrid — libraries where mature, custom where not | Ship fast for formats with good community tooling |
| Format detection | Two-pass (extension narrows → content probe via `detect()` on first 4KB) | Fast for unambiguous extensions, robust for `.csv`/`.vbo` |
| Streaming | Add optional `stream()` to `BaseAdapter` with default that wraps `parse()` | Existing adapters keep working. New adapters can implement native streaming. |
| Column contract | `distance_m` and `lap_number` are OPTIONAL at adapter output | Many formats (VBOX, RaceBox, Qstarz) lack native distance/lap data. Pipeline derives them. |

## 4. Existing Adapter Inventory

### Already Implemented (CSV-based)

| Adapter | FORMAT_NAME | Extensions | Detection Strategy |
|---------|-------------|-----------|-------------------|
| `RaceChronoAdapter` | `racechrono` | `.csv` | `"Time (s)"` / `"Speed (m/s)"` sentinels |
| `IRacingAdapter` | `iracing` | `.csv`, `.txt` | `Lap`, `Speed`, `Throttle`, `Brake`, `RPM`, `SteeringWheelAngle` (≥3 of 6) |
| `ACCAdapter` | `acc` | `.csv` | `speedKmh`, `gas`, `brake`, `steerAngle` |
| `MoTeCAdapter` | `motec` | `.csv` | `Beacon` column or `Engine RPM` + supporting columns |
| `GenericCSVAdapter` | `generic_csv` | `.csv` | Fuzzy keyword matching (catch-all, max confidence 0.7) |

### New Adapters to Add

| Adapter | FORMAT_NAME | Extensions | Type | Notes |
|---------|-------------|-----------|------|-------|
| `VboxAdapter` | `vbox` | `.vbo` | Text, custom | 9 core columns; velocity in knots → m/s, lat/long in minutes×10⁻⁵ → degrees |
| `RaceBoxCSVAdapter` | `racebox` | `.csv` | Text, custom | Variable headers, `"UTC Time"` / `"Speed(km/h)"` probe |
| `QstarzCSVAdapter` | `qstarz_csv` | `.csv` | Text, custom | `"INDEX"`, `"RCR"`, `"DATE"`, `"TIME"` probe |
| `IRacingBinaryAdapter` | `iracing_ibt` | `.ibt` | Binary, library | Uses `ibt` PyPI package. 52+ channels natively. |
| `MoTeCBinaryAdapter` | `motec_ld` | `.ld`, `.ldx` | Binary, library | Uses `ldparser` PyPI package. Also handles ACC native `.ld` exports. |
| `AiMAdapter` | `aim` | `.xrk`, `.xrz` | Binary, SDK | Requires AiM SDK DLL (`AIMXRK.dll`) — Windows only. Stub on other platforms. |
| `RaceChronoRCZAdapter` | `racechrono_rcz` | `.rcz` | Binary, stdlib | ZIP with `session.json` + binary channels. Experimental. |
| `QstarzBinaryStub` | `qstarz_binary` | `.rcnx`, `.rcn` | Stub | Raises `MissingDependency` with export-to-CSV hint. |

### Important Distinction: CSV Export vs Native Binary

| Tool | CSV Export (already supported) | Native Binary (new) |
|------|-------------------------------|-------------------|
| iRacing | `IRacingAdapter` — parses CSV with `Lap`, `Speed`, etc. | `IRacingBinaryAdapter` — parses `.ibt` via `ibt` library |
| MoTeC | `MoTeCAdapter` — parses CSV with `Beacon`, `Engine RPM`, etc. | `MoTeCBinaryAdapter` — parses `.ld`/`.ldx` via `ldparser` |
| ACC | `ACCAdapter` — parses CSV with `speedKmh`, `gas`, etc. | Covered by `MoTeCBinaryAdapter` (ACC exports MoTeC `.ld`) |

Existing CSV adapters are NOT replaced. Binary adapters are added alongside them.

### Implementation Priority

| Tier | Adapters | Rationale |
|------|----------|-----------|
| 1 — MVP | `VboxAdapter`, `RaceBoxCSVAdapter`, `QstarzCSVAdapter` | Text, no deps, covers most real-world users |
| 2 — Sim + Pro | `IRacingBinaryAdapter`, `MoTeCBinaryAdapter` | Library-backed, big user base |
| 3 — Niche | `AiMAdapter`, `RaceChronoRCZAdapter` | SDK dependency / experimental |
| 4 — Stub | `QstarzBinaryStub` | No docs, export fallback only |

## 5. BaseAdapter Changes

### Current Interface (unchanged)

```python
class BaseAdapter(abc.ABC):
    FORMAT_NAME: str = "unknown"

    @staticmethod
    @abc.abstractmethod
    def detect(file_path: str) -> float: ...

    @abc.abstractmethod
    def parse(self, file_path: str, progress_cb=None) -> pd.DataFrame: ...

    @abc.abstractmethod
    def metadata(self) -> dict: ...

    @abc.abstractmethod
    def available_channels(self) -> list[str]: ...

    def data_tier(self) -> int: ...  # concrete helper
```

### New Additions

```python
class BaseAdapter(abc.ABC):
    # ... existing interface above ...

    # ── New: extension + binary detection support ──
    EXTENSIONS: list[str] = []          # e.g. [".vbo"], [".ibt"]
    MAGIC_BYTES: bytes | None = None    # e.g. b'\x00\x01' for binary magic

    # ── New: streaming support (optional override) ──
    def stream(
        self,
        file_path: str,
        *,
        config: IngestionConfig | None = None,
        progress_cb: ProgressCallback | None = None,
    ) -> Iterator[pd.DataFrame]:
        """Yield bounded-memory DataFrame chunks in canonical column names.

        Default implementation: calls self.parse() and yields the full
        DataFrame as a single chunk. Adapters for large files should
        override this with chunked reading.
        """
        df = self.parse(file_path, progress_cb=progress_cb)
        yield df

    # ── New: declare whether streaming is natively supported ──
    @property
    def supports_streaming(self) -> bool:
        """True if stream() is overridden with native chunked reading."""
        return type(self).stream is not BaseAdapter.stream
```

### Backward Compatibility

- Existing adapters (RaceChrono, iRacing CSV, ACC, MoTeC CSV, GenericCSV) keep working — `stream()` falls back to `parse()` by default
- `s01_ingest.py` continues to call `parse_file()` which returns a single DataFrame
- The canonical→RaceChrono reverse mapping in `s01_ingest.py:24-35` stays untouched
- New code paths that want streaming call `adapter.stream()` directly

## 6. Registry Enhancements

### Current Registry (kept)

```python
# telemetry_tool/adapters/registry.py — existing
def register_adapter(cls: Type[BaseAdapter]) -> None: ...
def detect_format(file_path: str) -> tuple[Type[BaseAdapter] | None, float]: ...
def parse_file(file_path: str, progress_cb=None) -> tuple[pd.DataFrame, BaseAdapter]: ...
```

### New Functions Added

```python
def supported_extensions() -> set[str]:
    """Return all extensions from registered adapters' EXTENSIONS class var."""

def stream_file(
    file_path: str,
    *,
    config: IngestConfig | None = None,
    progress_cb: ProgressCallback | None = None,
) -> Iterator[pd.DataFrame]:
    """detect_format() → adapter.stream(). Streaming entry point."""

def detect_format_two_pass(file_path: str) -> tuple[Type[BaseAdapter] | None, float]:
    """Enhanced detection — replaces detect_format() as the default:
    1. Filter adapters by EXTENSIONS (if set) matching file extension
    2. If no EXTENSIONS match, include all adapters (backward compat with existing 5)
    3. Run detect() on candidates
    4. Return highest confidence above _MIN_CONFIDENCE
    parse_file() and stream_file() both call this instead of detect_format().
    detect_format() is kept as-is for any external callers.
    """
```

### Detection: `detect()` Contract Update

The existing `detect(file_path: str) -> float` signature stays the same. Adapters that need binary magic byte checks simply read the first bytes themselves within `detect()`. The registry opens the file once and passes it — no, wait. The current contract has `detect()` as a `@staticmethod` that receives only `file_path`. This stays. Binary adapters read 4KB themselves in `detect()`. This is consistent with how all 5 existing adapters work (each reads the file header in their own `detect()` method).

## 7. Canonical Column Contract

### Required Columns (minimum viable for pipeline)

| Column | Type | Unit | Required |
|--------|------|------|----------|
| `time_s` | float64 | seconds | **yes** |
| `speed_mps` | float64 | m/s | **yes** |

### Derivable Columns (pipeline provides if missing)

| Column | Type | Unit | Derived How |
|--------|------|------|------------|
| `distance_m` | float64 | meters | `cumtrapz(speed_mps, time_s)` — integrated in `s01_ingest.py` post-parse |
| `lap_number` | int/float | — | GPS track boundary crossing detection (pipeline stages 3-5) |

### Optional Channels

| Column | Type | Unit |
|--------|------|------|
| `lat_deg` | float64 | degrees |
| `lon_deg` | float64 | degrees |
| `accel_long_mps2` | float64 | m/s² |
| `accel_lat_mps2` | float64 | m/s² |
| `throttle_pct` | float64 | 0–100 |
| `brake_pct` | float64 | 0–100 |
| `rpm` | float64 | rev/min |
| `gear` | int | — |
| `steering_angle_deg` | float64 | degrees |
| `yaw_rate_dps` | float64 | deg/s |
| `heading_deg` | float64 | degrees |
| `altitude_m` | float64 | meters |

Extra source channels pass through with `raw_` prefix.

### Derivation Logic (added to `s01_ingest.py`)

```python
# After parse and reverse-mapping, derive missing required columns:

# distance_m: integrate speed over time
if "Distance (m)" not in raw_df.columns and "Speed (m/s)" in raw_df.columns:
    from scipy.integrate import cumulative_trapezoid
    speed = raw_df["Speed (m/s)"].fillna(0).values
    time = raw_df["Time (s)"].values
    dist = cumulative_trapezoid(speed, time, initial=0)
    raw_df["Distance (m)"] = dist

# lap_number: sentinel value 0 if not present (pipeline stages 3-5 derive real laps)
if "Lap #" not in raw_df.columns:
    raw_df["Lap #"] = 0
```

### Unit Normalization Contract

All adapters convert to SI on output: speed → m/s, acceleration → m/s², angles → degrees, time → seconds from session start.

## 8. New Adapter Specifications

### Text Formats

**VboxAdapter** (`.vbo`)
- Section-based text format: `[header]`, `[comments]`, `[column names]`, `[data]`
- 9 core columns: `sats / time / lat / long / velocity / heading / height / vertvel / event1`
- Unit conversions: velocity in knots → m/s (`× 0.514444`), lat/long in minutes×10⁻⁵ → degrees (`÷ 60000.0`)
- Streaming: parse header sections first (small), then stream `[data]` section line-by-line in chunks
- Lap detection: not natively available — `event1` channel transitions may indicate laps, otherwise pipeline derives
- Detection: `detect()` reads first 20 lines, looks for `[header]` or `[column names]` section marker

**RaceBoxCSVAdapter** (`.csv`)
- Variable headers, no single fixed schema
- Detection: look for `"UTC Time"` or `"Speed(km/h)"` or `"Latitude"` / `"Longitude"` patterns — confidence 0.75 if found (below RaceChrono's 0.9)
- Speed in km/h → ÷ 3.6 to m/s
- No native lap markers — pipeline derives from GPS
- No native distance — derived from speed integration

**QstarzCSVAdapter** (`.csv`)
- Detection: `"INDEX"`, `"RCR"`, `"DATE"`, `"TIME"` in first header row — confidence 0.8
- Speed in km/h, coordinates in decimal degrees
- No lap markers, no distance — both derived

### Binary Formats

**IRacingBinaryAdapter** (`.ibt`)
- Library: `ibt` (PyPI, MIT license)
- 52 default channels, up to ~300 with extended set
- Native lap numbers (`Lap`), speed (`Speed` in m/s), distance (`LapDist` in m)
- Streaming: `.ibt` has fixed header → variable data records. Read header for channel defs, stream data in chunks.
- Conversion: Throttle/Brake 0–1 → 0–100%, SteeringWheelAngle/YawRate rad → deg
- Detection: check first 4 bytes for iRacing version header magic

**MoTeCBinaryAdapter** (`.ld`, `.ldx`)
- Library: `ldparser` (PyPI, MIT license)
- Channel data stored per-channel contiguously. `.ldx` sidecar has metadata.
- Streaming: read channel directory, stream each channel's data block, interleave into row chunks
- Lap markers: beacon events in data stream
- Detection: check byte at offset 0 for MoTeC signature
- Also handles ACC native `.ld` exports (ACC writes MoTeC format)

**AiMAdapter** (`.xrk`, `.xrz`)
- `.xrk` is a **proprietary binary format** — NOT SQLite. Requires the AiM SDK DLL (`AIMXRK.dll`) which is Windows-only.
- `.xrz` is gzip-compressed `.xrk`
- Strategy: use the unofficial `aimsdk` Python wrapper if available, otherwise stub with `MissingDependency` error directing user to export to CSV from AiM RaceStudio
- Detection: check magic bytes in binary header
- **Platform limitation**: Windows-only due to DLL dependency. On Linux/macOS, acts as stub.

**RaceChronoRCZAdapter** (`.rcz`) — Experimental
- ZIP container with `session.json` metadata + binary channel data files
- Strategy: `zipfile.ZipFile` → parse `session.json` → stream channel binaries
- Channel data format varies by RaceChrono version (protobuf or flat binary)
- Low priority — most users export to CSV from RaceChrono

**QstarzBinaryStub** (`.rcnx`, `.rcn`) — Stub only
- `detect()` returns 0.3
- `parse()` raises `MissingDependency` with message: "Qstarz .rcnx/.rcn files require export to CSV via the QRacing app. Open QRacing, select the session, and export as CSV."

## 9. Files Changed

### Modified Files

| File | Change |
|------|--------|
| `telemetry_tool/adapters/base.py` | Add `EXTENSIONS`, `MAGIC_BYTES`, `stream()`, `supports_streaming` |
| `telemetry_tool/adapters/registry.py` | Add `supported_extensions()`, `stream_file()`, `detect_format_two_pass()` |
| `telemetry_tool/adapters/__init__.py` | Import + register new adapters |
| `telemetry_tool/pipeline/stages/s01_ingest.py` | Add `distance_m` / `lap_number` derivation for formats lacking them |
| `telemetry_tool/web/routes/sessions_v2.py` | Use `registry.supported_extensions()` for dynamic ALLOWED set |

### New Files

| File | Purpose |
|------|---------|
| `telemetry_tool/adapters/vbox_adapter.py` | VBOX `.vbo` text parser |
| `telemetry_tool/adapters/racebox_adapter.py` | RaceBox CSV parser |
| `telemetry_tool/adapters/qstarz_csv_adapter.py` | Qstarz CSV export parser |
| `telemetry_tool/adapters/iracing_binary_adapter.py` | iRacing `.ibt` binary parser |
| `telemetry_tool/adapters/motec_binary_adapter.py` | MoTeC `.ld`/`.ldx` binary parser |
| `telemetry_tool/adapters/aim_adapter.py` | AiM `.xrk`/`.xrz` (SDK-backed or stub) |
| `telemetry_tool/adapters/racechrono_rcz_adapter.py` | RaceChrono `.rcz` ZIP container |
| `telemetry_tool/adapters/qstarz_binary_stub.py` | Stub directing to CSV export |
| `telemetry_tool/adapters/streaming_utils.py` | Shared chunked-read utilities for text formats |

### Streaming Infrastructure

The existing streaming infrastructure in `telemetry_tool/ingest/` (streaming.py, cache.py, pool.py) stays in place. New adapters that need streaming for text formats reuse:
- `telemetry_tool/ingest/streaming.py` — chunked CSV reader, adaptive chunk sizing
- `telemetry_tool/ingest/cache.py` — Parquet chunk cache + PyArrow merge

Binary adapters implement their own streaming based on their library's API.

## 10. Error Handling

```python
# New errors added to telemetry_tool/adapters/errors.py

class ParseError(Exception):
    """Base. All adapter errors inherit from this."""
    format_name: str
    file_path: str

class UnrecognizedFormat(ParseError):
    """No adapter scored above _MIN_CONFIDENCE."""
    candidates: list[tuple[str, float]]  # top 3 (format_name, confidence)

class MissingColumns(ParseError):
    """Required canonical columns not found after mapping."""
    missing: list[str]
    available: list[str]

class CorruptedFile(ParseError):
    """File matched format but data is unreadable."""
    offset: int | None

class MissingDependency(ParseError):
    """Adapter library not installed."""
    package: str
    install_hint: str

class InsufficientData(ParseError):
    """File parsed but has < minimum rows for analysis."""
    row_count: int
    minimum: int  # typically 100
```

The existing `ValueError` from `parse_file()` when no adapter matches is enhanced to include top-3 candidates with scores:

```python
# Enhanced error in registry.py parse_file()
raise UnrecognizedFormat(
    f"No adapter matched file '{file_path}'.",
    candidates=[(a.FORMAT_NAME, score) for a, score in top_3],
)
```

API returns actionable feedback:
```json
{
  "ok": false,
  "error": "unrecognized_format",
  "detail": {
    "best_guesses": [{"format": "racebox", "confidence": 0.35}],
    "hint": "Try exporting with GPS columns enabled."
  }
}
```

## 11. Testing Strategy

### Test Location

```
telemetry_tool/tests/adapters/
├── conftest.py               # shared fixtures, sample generators
├── contract.py               # AdapterContractTests mixin
├── test_registry.py          # registration, detection, two-pass
├── fixtures/                 # one small sample file per format
│   ├── racechrono_sample.csv
│   ├── vbox_sample.vbo
│   ├── racebox_sample.csv
│   ├── iracing_sample.ibt
│   ├── motec_sample.ld
│   └── qstarz_sample.csv
├── test_vbox.py
├── test_racebox.py
├── test_qstarz_csv.py
├── test_iracing_binary.py
├── test_motec_binary.py
└── test_aim.py
```

### Universal Contract Tests

Every adapter must pass `AdapterContractTests`:

- `test_detect_returns_high_confidence_for_own_format`
- `test_detect_returns_low_confidence_for_wrong_format`
- `test_parse_returns_dataframe_with_canonical_columns`
- `test_required_columns_present` (at minimum: `time_s`, `speed_mps`)
- `test_units_are_si` (speed in m/s range, not km/h range)
- `test_time_monotonically_increasing`
- `test_metadata_returns_dict`
- `test_available_channels_returns_list`
- `test_stream_yields_dataframes` (default: yields single chunk)
- `test_empty_file_returns_zero_confidence`
- `test_corrupted_file_returns_zero_confidence`

Adapters that override `stream()` additionally pass:
- `test_streaming_memory_bounded` (peak RSS < config threshold)
- `test_stream_chunks_have_consistent_columns`
- `test_stream_total_rows_match_parse` (concat(stream chunks) == parse output)

### Fixtures Strategy

- Real files: one small (~50 rows) real file per format, GPS anonymized
- Synthetic generators: for streaming/memory tests, generate large files programmatically
- Cross-format confusion tests: feed VBOX to iRacing adapter → 0.0 confidence

## 12. Dependencies

| Package | PyPI | Required For | Tier | Added To |
|---------|------|-------------|------|----------|
| `ibt` | `ibt` | iRacing `.ibt` binary | 2 | `requirements.txt` (optional) |
| `ldparser` | `ldparser` | MoTeC `.ld`/`.ldx` binary | 2 | `requirements.txt` (optional) |
| `scipy` | existing | `cumulative_trapezoid` for distance derivation | 1 | already present |
| `pandas` | existing | all adapters | all | already present |
| `pyarrow` | existing | streaming merge | all | already present |

Tier 1 (text format) adapters require zero new dependencies.
Tier 2 binary libraries are optional — adapters degrade to `MissingDependency` error if not installed.

## 13. Streaming Threshold

The `concat_frames()` / stream-to-disk threshold reuses the existing constant from `telemetry_tool/ingest/config.py`:

```python
STREAMING_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB
```

- Files < 100 MB: `stream()` chunks accumulated in memory via `pd.concat()`
- Files ≥ 100 MB: chunks flushed to Parquet cache, merged via PyArrow streaming writer

This matches the existing INGEST_V2 behavior.

## 14. SessionMetadata Persistence Across Stream Chunks

When streaming with Parquet cache (files ≥ 100 MB):
- `SessionMetadata` is written to the cache manifest file on the first chunk flush
- On resume, manifest is read to restore metadata before resuming chunk iteration
- Every chunk from `stream()` carries the same metadata reference (parsers emit metadata on first chunk, subsequent chunks reference it)

## 15. INGEST_V2 Flag

The existing `TELEMETRY_INGEST_V2` flag stays as a rollback mechanism:
- When ON (default): `io_racechrono.py` routes through streaming infrastructure
- When OFF: legacy in-memory `read_racechrono_csv()` path
- New adapters (VBOX, RaceBox, etc.) always use the adapter registry regardless of this flag — the flag only controls the RaceChrono CSV code path
