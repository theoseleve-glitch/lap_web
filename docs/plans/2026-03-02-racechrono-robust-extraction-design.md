# Robust RaceChrono & RaceBox CSV Extraction — Design

**Date**: 2026-03-02
**Status**: Approved
**Approach**: Dynamic Column Discovery (B) with RaceBox format support

## Problem

The current CSV ingestion (`io_racechrono.py`, `ingest/streaming.py`) has:

1. **Hard-coded mapping of only 11 column variants** (`_RAW_TO_INTERNAL`) — everything else passes through unnamed and gets ignored by downstream pipeline steps.
2. **Missing raw acceleration fallback**: `"Longitudinal acceleration (G)"` (without `*calc`) is unmapped. Pipeline falls back to slow dv/dt derivation instead of using available sensor data.
3. **No Latitude/Longitude/Bearing/Altitude in the mapping** — survive only because `derived_channels.py` hard-codes raw names separately.
4. **No OBD channel support**: RPM, Throttle, Coolant Temp, etc. are silently dropped.
5. **No gyro beyond yaw**: Pitch rate, Roll rate discarded.
6. **No unit conversion**: `Speed (km/h)`, `Speed (mph)` not handled.
7. **RaceBox CSV fails**: Header sentinel only checks for `"Time (s)"` as first cell.
8. **Unknown/custom channels dropped**: No persistence path for user-added sensors.

## Design: Dynamic Column Discovery Engine

### Architecture

```
CSV file
  ↓
io_racechrono.py / streaming.py   (encoding, header, delimiter — unchanged)
  ↓
column_discovery.py (NEW)          parse headers → classify → convert units → *calc preference
  ↓
pipeline.py                        consumes internal names (same as before)
  ↓
models.py                          persists channel inventory as JSON
```

### Module: `telemetry_tool/column_discovery.py`

Single new file. Two public functions:

```python
def discover_columns(df: pd.DataFrame) -> DiscoveryResult:
    """Parse all column headers, classify, convert units, apply *calc preference."""

def apply_discovery(df: pd.DataFrame, result: DiscoveryResult) -> pd.DataFrame:
    """Rename columns to internal names, apply unit conversions in-place."""
```

#### `DiscoveryResult` dataclass:

```python
@dataclass
class DiscoveredChannel:
    raw_name: str           # Original column header from CSV
    internal_name: str      # Canonical internal name (or raw_name if unknown)
    category: str           # time, position, speed, acceleration, gyro, heading, altitude,
                            # gps_quality, engine, pedal, steering, biometric, custom
    unit_raw: str | None    # Unit from header (e.g. "G", "km/h", "deg/s")
    unit_internal: str | None  # Canonical unit after conversion
    is_calc: bool           # True if "*calc" variant
    conversion_factor: float | None  # Multiply raw values by this (e.g. 9.80665 for G→m/s²)
    n_valid: int            # Count of non-NaN values

@dataclass
class DiscoveryResult:
    format: str             # "racechrono" | "racebox" | "unknown"
    channels: list[DiscoveredChannel]
    rename_map: dict[str, str]     # raw_name → internal_name (for df.rename)
    conversions: dict[str, float]  # internal_name → multiplication factor
    calc_overrides: dict[str, str] # internal_name → preferred raw_name (*calc wins)
    custom_channels: list[str]     # Columns that couldn't be classified
```

### Header Parsing

Each column header is parsed with this regex:

```python
HEADER_RE = re.compile(
    r"^(?P<name>.+?)"           # Channel name
    r"(?:\s*\((?P<unit>[^)]+)\))?"  # Optional unit in parens
    r"(?:\s*\*(?P<flag>\w+))?"   # Optional *calc / *raw flag
    r"\s*$"
)
```

Examples:
- `"Speed (m/s) *calc"` → name=`Speed`, unit=`m/s`, flag=`calc`
- `"Lateral acceleration (G)"` → name=`Lateral acceleration`, unit=`G`, flag=`None`
- `"Lap #"` → name=`Lap #`, unit=`None`, flag=`None`
- `"Tire temp FL (°C)"` → name=`Tire temp FL`, unit=`°C`, flag=`None`

### Classification Rules

Priority-ordered pattern matching on the parsed channel name:

| Priority | Pattern (case-insensitive) | Category | Internal Name |
|---|---|---|---|
| 1 | `name == "Time"` | time | `time_s` |
| 2 | `name matches "Lap"` | lap | `lap_number` |
| 3 | `name matches "Distance"` | distance | `distance_m` |
| 4 | `name matches "Speed"` | speed | `speed_mps` |
| 5 | `name matches "Lat(itude)?"` | position | `latitude_deg` |
| 6 | `name matches "Lon(gitude)?"` | position | `longitude_deg` |
| 7 | `name == "X"` | position | `x_m` |
| 8 | `name == "Y"` | position | `y_m` |
| 9 | `name matches "Longitud.*accel"` | acceleration | `accel_long_mps2` |
| 10 | `name matches "Lateral.*accel"` | acceleration | `accel_lat_mps2` |
| 11 | `name matches "Accel.*X"` | acceleration | `accel_long_mps2` |
| 12 | `name matches "Accel.*Y"` | acceleration | `accel_lat_mps2` |
| 13 | `name matches "Accel.*Z"` | acceleration | `accel_vert_mps2` |
| 14 | `name matches "Yaw"` | gyro | `yaw_rate_dps` |
| 15 | `name matches "Pitch"` | gyro | `pitch_rate_dps` |
| 16 | `name matches "Roll"` | gyro | `roll_rate_dps` |
| 17 | `name matches "Gyro.*X"` | gyro | `roll_rate_dps` |
| 18 | `name matches "Gyro.*Y"` | gyro | `pitch_rate_dps` |
| 19 | `name matches "Gyro.*Z"` | gyro | `yaw_rate_dps` |
| 20 | `name matches "Bear(ing)\|Head(ing)"` | heading | `heading_deg` |
| 21 | `name matches "Alt(itude)?"` | altitude | `altitude_m` |
| 22 | `name matches "Satellite"` | gps_quality | `satellites` |
| 23 | `name matches "Accuracy\|HDOP"` | gps_quality | `accuracy_m` |
| 24 | `name matches "RPM"` | engine | `engine_rpm` |
| 25 | `name matches "Throttle\|TPS"` | engine | `throttle_pct` |
| 26 | `name matches "Coolant"` | engine | `coolant_temp_c` |
| 27 | `name matches "Oil.*temp"` | engine | `oil_temp_c` |
| 28 | `name matches "Intake.*temp"` | engine | `intake_temp_c` |
| 29 | `name matches "Battery\|Volt"` | engine | `battery_v` |
| 30 | `name matches "Boost\|MAP"` | engine | `boost_kpa` |
| 31 | `name matches "Brake"` | pedal | `brake_pct` |
| 32 | `name matches "Steer"` | steering | `steering_angle_deg` |
| 33 | `name matches "Heart.*rate\|HR\|BPM"` | biometric | `heart_rate_bpm` |
| 34 | *anything else* | custom | raw_name preserved |

### Unit Conversion Table

| Unit (from header) | Canonical | Factor |
|---|---|---|
| `G` | m/s² | × 9.80665 |
| `km/h` | m/s | × (1/3.6) |
| `mph` | m/s | × 0.44704 |
| `kn` / `knots` | m/s | × 0.514444 |
| `ft` | m | × 0.3048 |
| `ft/s` | m/s | × 0.3048 |
| `rad/s` | deg/s | × (180/π) |
| `°F` | °C | (v - 32) × 5/9 |
| `kPa` | bar | × 0.01 |
| `psi` | bar | × 0.0689476 |

Conversions are applied in-place on the DataFrame columns (no copy).

### `*calc` Preference Logic

When multiple columns map to the same internal name:
1. `*calc` variant wins over non-calc
2. Among same-flag columns, first match wins
3. Losing columns are preserved in `custom_channels` with original data

### Format Detection

Before column discovery, detect the source format from metadata rows:

```python
def detect_format(metadata: dict[str, str]) -> str:
    text = " ".join(metadata.values()).lower()
    if "racebox" in text:
        return "racebox"
    if "racechrono" in text:
        return "racechrono"
    return "unknown"
```

Format affects:
- **RaceChrono**: Standard header parsing, `*calc` preference
- **RaceBox**: Axis-based accel/gyro mapping (X=long, Y=lat, Z=vert), potential km/h default, ISO timestamp parsing

### Header Sentinel Expansion

`_find_header_row_from_lines()` currently only checks first cell == `"Time (s)"`.

Change to check first cell against a set of sentinels:

```python
_HEADER_SENTINELS = {"Time (s)", "Time", "UTC Time", "Timestamp", "time_s"}
```

Fallback: if no sentinel matches as first cell, scan for any row where ≥3 cells match known column patterns (fuzzy header detection).

### DB Persistence

New Alembic migration adds to `sessions` table:

```sql
ALTER TABLE sessions ADD COLUMN channel_inventory JSONB;
```

The `channel_inventory` column stores the `DiscoveryResult` summary:

```json
{
  "format": "racechrono",
  "channels": [
    {"raw": "Speed (m/s) *calc", "internal": "speed_mps", "category": "speed", "unit": "m/s", "is_calc": true, "n_valid": 14200},
    {"raw": "Engine RPM (rpm)", "internal": "engine_rpm", "category": "engine", "unit": "rpm", "n_valid": 14100}
  ],
  "custom": ["Tire temp FL (°C)", "Tire temp FR (°C)"]
}
```

### New API Endpoints

```
GET /api/v1/sessions/<id>/channels
```
Returns the channel inventory for a session.

```
GET /api/v1/sessions/<id>/channel-data?channel=engine_rpm&lap=2
```
Returns time-series data for any discovered channel (reads from stored per-lap Parquet or recalculates).

### Pipeline Integration

In `pipeline.py`, replace:
```python
df = _map_to_internal_names(df)
```
with:
```python
from telemetry_tool.column_discovery import discover_columns, apply_discovery
discovery = discover_columns(df)
df = apply_discovery(df, discovery)
summary["channel_discovery"] = discovery.to_dict()
```

All downstream steps continue consuming internal names (`speed_mps`, `accel_long_mps2`, etc.) unchanged.

### Files Changed

| File | Change Type | Description |
|---|---|---|
| `telemetry_tool/column_discovery.py` | **NEW** | Discovery engine — parse, classify, convert, preference |
| `telemetry_tool/pipeline.py` | MODIFY | Replace `_RAW_TO_INTERNAL` + `_map_to_internal_names` with discovery calls |
| `telemetry_tool/io_racechrono.py` | MODIFY | Expand header sentinels from single to set |
| `telemetry_tool/ingest/streaming.py` | MODIFY | Same sentinel expansion for streaming path |
| `telemetry_tool/web/models.py` | MODIFY | Add `insert_channel_inventory()`, update `upsert_session()` |
| `telemetry_tool/db/schema.py` | MODIFY | Add `channel_inventory TEXT` to sessions table (SQLite path) |
| `alembic/versions/017_channel_inventory.py` | **NEW** | Migration adding `channel_inventory JSONB` column |
| `telemetry_tool/web/routes/data_v2.py` | MODIFY | Add channels + channel-data endpoints |
| `telemetry_tool/tests/test_column_discovery.py` | **NEW** | Unit tests for discovery engine |

### Backward Compatibility

- Existing CSV files that work today continue to work unchanged
- `_map_to_internal_names` is replaced, not augmented — the discovery engine is a complete replacement
- All internal column names (`speed_mps`, `accel_long_mps2`, etc.) remain identical
- DB sessions without `channel_inventory` return `null` from the API (graceful)
- The `derived_channels.py` module continues as-is — it runs after discovery and fills gaps

### Testing Strategy

1. **Unit tests for discovery engine**: Parse known RaceChrono headers, RaceBox headers, European locale, missing columns
2. **Integration tests**: Full pipeline with synthetic CSVs containing OBD/custom channels → verify `channel_inventory` in DB
3. **Regression tests**: Existing test CSVs must produce identical pipeline output
4. **Edge cases**: Empty columns, duplicate names, all-NaN columns, mixed units
