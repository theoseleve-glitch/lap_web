# Datalogger iRacing Full-Capture Prompt

Modify the repo at `C:\Users\Admin\Documents\Telemetry\datalogger`.

## Goal

Extend the iRacing logger so it preserves the current normalized cross-sim output, but also records the full recoverable iRacing observable set, and samples at the actual IRSDK shared-memory update cadence instead of the current manual sleep-limited rate.

## Important technical constraint

Do **not** hardcode `960 Hz`. On the current live system, IRSDK reports `header.tick_rate = 60`. The implementation must follow the SDK's actual tick cadence by reading the live header / buffer ticks, not by assuming the physics engine rate.

If the SDK tick rate changes in another session or build, the logger should adapt automatically.

## Current relevant files

- `src/lap_coach_logger/adapters/iracing_adapter.py`
- `src/lap_coach_logger/core/schema.py`
- `src/lap_coach_logger/normalization/mapper.py`
- `src/lap_coach_logger/core/session_coordinator.py`
- `src/lap_coach_logger/writers/finalizer.py`
- `src/lap_coach_logger/writers/channels.py`
- `src/lap_coach_logger/config/models.py`
- `src/lap_coach_logger/ui/settings_window.py`
- `src/lap_coach_logger/ui/desktop/service.py`

## External recovered inventories to use as source of truth

- `C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\artifacts\iracing_live_var_schema.json`
  All 332 public IRSDK live vars
- `C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\artifacts\iracing_session_leaf_paths.json`
  615 flattened session metadata leaf paths
- `C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\artifacts\iracing_localserver_track_fields.json`
  156 hidden local-server track/config field names
- `C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\artifacts\iracing_localserver_arq_messages.json`
  103 internal local-server message names
- `C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\artifacts\iracing_sim_param_names.json`
  571 executable/runtime parameter names

## Required design

1. Keep the existing normalized `TelemetrySample` output and current session bundle format backward compatible.
2. Add a second iRacing-specific raw telemetry stream that records every public IRSDK variable, not just the hand-picked subset currently read in `iracing_adapter.py`.
3. Add a session metadata snapshot output for the flattened IRSDK session/YAML tree.
4. Add the recovered static catalogs from the local-server binary and sim executable into the session bundle as reference metadata catalogs, not as fake live values.
5. Make the iRacing sampling loop event/tick-driven so it records once per new IRSDK buffer tick at the SDK's real publish rate.
6. Keep ACC behavior unchanged.

## Implementation requirements

1. In `iracing_adapter.py`, add a raw iRacing capture path that iterates all IRSDK var headers dynamically.
2. Handle scalar and array vars correctly.
3. For array vars, flatten deterministically into suffixed columns like `irsdk__CarIdxLapDistPct__0`, `irsdk__CarIdxLapDistPct__1`, etc.
4. Add raw runtime metadata fields like:
   - `irsdk__header_tick_rate_hz`
   - `irsdk__header_num_buf`
   - `irsdk__var_buffer_tick`
   - `irsdk__session_info_update`
   - `irsdk__sample_timestamp_utc`
5. Do not replace the normalized schema. Add new outputs alongside it.

## Sampling behavior

1. Replace the current sleep-limited iRacing recording path with SDK-driven capture.
2. Use the IRSDK data-valid event and/or buffer tick change to wait for fresh data.
3. Only append a new raw/normalized sample when the buffer tick changes.
4. Expose both configured mode and observed rate in metadata:
   - `sample_mode`
   - `sdk_tick_rate_hz`
   - `observed_sample_rate_hz`
5. For iRacing, default to `sample_mode = auto_sdk`.
6. Optional manual override may exist, but auto-SDK mode should be the default and preferred path.
7. Update validation and UI so it no longer caps the sample rate at 100 Hz for iRacing if auto-SDK mode is used.

## Output changes

1. Keep existing:
   - `telemetry.csv` or `telemetry.parquet`
   - `channels.json`
   - `session.json`
2. Add:
   - `telemetry_iracing_raw.parquet` or `telemetry_iracing_raw.csv`
   - `channels_iracing_raw.json`
   - `session_info_iracing.json`
   - `iracing_catalogs.json`
3. `session_info_iracing.json` should contain the full flattened session metadata tree from the live session.
4. `iracing_catalogs.json` should include:
   - `localserver_track_fields`
   - `localserver_arq_messages`
   - `sim_param_names`
   - source file paths
   - counts
5. `session.json` should include references to these new files in `source_metadata`.

## Flattening rules

1. Session metadata paths should be flattened consistently, for example:
   - `WeekendInfo.TrackName` -> `session__WeekendInfo__TrackName`
   - `SessionInfo.Sessions[0].SessionTrackRubberState` -> `session__SessionInfo__Sessions__0__SessionTrackRubberState`
2. Preserve original types where possible.
3. If a value is not scalar, serialize it in a deterministic way.
4. Avoid characters in column names that are awkward for Parquet or CSV consumers.

## Do not do this

- Do not invent per-tile grip or `mu` values.
- Do not pretend the 156 local-server field names or 571 sim parameter names are live sampled values unless they are actually sourced at runtime.
- Do not break ACC.
- Do not remove the existing normalized telemetry bundle.

## Acceptance criteria

1. Existing normalized telemetry still writes successfully.
2. iRacing raw output contains all public IRSDK vars from the 332-var schema.
3. Session metadata snapshot contains all recoverable flattened session leaf paths.
4. The bundle contains the recovered catalog files.
5. The logger records at the actual SDK update cadence in auto mode.
6. The saved metadata reports the detected SDK tick rate and observed sample rate.
7. Tests cover:
   - raw var flattening
   - array var handling
   - session metadata flattening
   - auto-SDK sample mode
   - backward compatibility of the existing normalized output

## Deliverables requested from the implementer

Please implement the code changes directly, update tests, and summarize:

- files changed
- new bundle outputs
- how the effective iRacing sample rate is determined
- any remaining limits of the IRSDK shared-memory API
