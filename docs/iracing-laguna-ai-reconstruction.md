# Laguna Seca Virtual-Track Reconstruction Audit

Date: 2026-03-30

## Objective

Goal: support an AI training / lap-time optimization project that builds a virtual representation of Laguna Seca with:

- track boundaries as accurately as possible
- local grip level as accurately as possible
- a defensible recap of how iRacing splits physics logic between compiled code and external data

## Local Data Fetched

### Installed Laguna Seca track package

Files found in the local iRacing installation:

- `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat`
- `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\school\school.dat`
- `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\version.txt`

`version.txt` content:

- `2026.02.26.04`

No other Laguna Seca geometry or metadata files were found in the install tree outside the packed `.dat` containers.

### `lagunaseca.dat`

File: `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat`

- size: `271,922,406` bytes
- first bytes: `03 00 41 64 B5 24 5D 25 8D BE 24 5C ...`
- `U16_LE@0 = 3`
- full-file entropy: `7.997886`
- sampled 64 KiB windows stay near maximum entropy
- no repeated 16-byte or 32-byte blocks in the first `64 KiB`
- no meaningful ASCII table or readable surface/material/grip strings
- longest printable runs look random, not structured metadata
- candidate `zlib/gzip` decompression probes did not yield a valid payload

Interpretation:

- this behaves like a packed opaque asset container
- the file almost certainly contains canonical track assets
- static carving did not recover a direct road-boundary mesh or per-surface grip table
- however, the container is not monolithic encryption: it contains typed chunks and decodable zstd-compressed assets

### `school.dat`

File: `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\school\school.dat`

- size: `78,421` bytes
- first bytes: `03 00 9D C6 B8 C0 08 8A 29 72 98 4C ...`
- `U16_LE@0 = 3`
- full-file entropy: `7.98449`
- same opaque-container behavior as the main track file

### Local non-`.dat` Laguna assets

These are not part of the install tree, but they are present locally and are the practical path for reconstruction:

- Laguna lap/reference files in `C:\Users\Admin\Documents\iRacing\lapfiles\lagunaseca`
- Laguna telemetry logs in `C:\Users\Admin\Documents\iRacing\telemetry`

Observed inventory:

- `11` Laguna lap/reference files: `.olap`, `.blap`, `.olapta`
- `7` Laguna telemetry logs: `.ibt`

Example lap/reference file:

- `C:\Users\Admin\Documents\iRacing\lapfiles\lagunaseca\605804_formulavee.olap`

Example telemetry file:

- `C:\Users\Admin\Documents\iRacing\telemetry\formulavee_lagunaseca 2025-05-02 11-18-19.ibt`

The `.olap` file is visibly structured:

- magic: `OLAP`
- track/session identifier visible near the header: `605804`
- embedded strings include `formulavee`, `lagunaseca`, and build tags such as `2024.10.09.01`
- float blocks appear after the header, which strongly suggests a usable sampled racing/reference line

That initial conclusion is now confirmed and pushed much further:

- the file is not just "structured", it is partially decoded
- the Laguna Formula Vee `.olap` can be split into a fixed header, a five-segment lap descriptor table, and a dense sampled payload
- the sampled payload is sufficient to reconstruct a metric centerline loop for Laguna Seca
- when that centerline is aligned against the DAT-derived 2D track-outline image, the fit is tight enough to use as a virtual-track scaffold

## Decoded `.olap` Structure

Decoded file:

- `C:\Users\Admin\Documents\iRacing\lapfiles\lagunaseca\605804_formulavee.olap`

Confirmed header fields:

- magic: `OLAP`
- file version: `3`
- track id: `605804`
- driver string: `ThO Stipa`
- car slug: `formulavee`
- track slug: `lagunaseca`
- build strings: `2024.10.09.01`, `2024.08.26.02`, `2024.08.22.02`
- lap time: `101.213 s`

Confirmed segment table:

- segment count: `5`
- cumulative end distances: `654.105`, `1345.206`, `2290.964`, `2865.662`, `3565.175` m
- sample counts: `327`, `346`, `473`, `287`, `350`
- implied step sizes: about `2.00 m`

Important check:

- the segment sample counts sum to `1783`
- the remaining payload size after the segment table is exactly `1783 * 28` bytes
- so the main payload is a fixed-size sampled record block, not arbitrary junk

## Reconstructed Centerline

The strongest new reverse-engineering result is that one payload field behaves like yaw / heading:

- it wraps cleanly at `+-pi`
- unwrapped total heading change across the lap is about `6.324 rad`, which is effectively one full loop
- integrating that heading with the decoded `~2 m` spacing reconstructs a metric centerline

Results from the Laguna Formula Vee `.olap`:

- interval count: `1778`
- lap length from the file: `3565.175 m`
- raw loop-closure error before correction: `12.66 m`
- after distributing that residual drift, a closed centerline loop is obtained

That is already enough for:

- a virtual centerline in local track coordinates
- an interval-by-interval speed profile from `distance / dt`
- a curvature-driven grip-demand proxy along the lap

Artifacts generated locally:

- `artifacts/iracing_olap_decode/605804_formulavee/summary.json`
- `artifacts/iracing_olap_decode/605804_formulavee/segments.csv`
- `artifacts/iracing_olap_decode/605804_formulavee/intervals.csv`
- `artifacts/iracing_olap_decode/605804_formulavee/centerline_local.csv`

## Alignment Against The DAT-Derived Outline

The reconstructed `.olap` centerline was aligned to the decoded DAT outline image:

- outline source: `artifacts/iracing_dat_extract/lagunaseca_pmts_1920x1080_type7.png`
- alignment RMS error: about `4.24 px`
- best transform used `flip_y = -1` with no axis swap

Interpretation:

- the `.olap` centerline and the DAT image are describing the same track shape
- this is strong cross-validation from two independent local sources

Generated overlay:

- `artifacts/iracing_olap_decode/605804_formulavee/outline_overlay.png`

Generated approximate corridor export:

- `artifacts/iracing_olap_decode/605804_formulavee/virtual_track.csv`

That CSV contains, for each centerline point:

- local centerline coordinates
- approximate left/right boundary hits derived from the outline image
- aligned pixel coordinates
- ribbon width in pixels

Important limitation:

- these left/right boundaries come from the DAT UI-style outline image, not a decoded road mesh
- so they are a good virtual-image scaffold, but they are not yet proven laser-survey-grade physical boundaries

## Grip / Physics Information Recoverable From `.olap`

What the decoded `.olap` gives you physically:

- segment-local timing
- sampled heading
- speed inferred from spacing and local time
- smoothed curvature
- a location-indexed grip-demand proxy based on `v^2 * curvature / g`

For the Formula Vee Laguna sample:

- inferred speed range: about `21.39` to `42.85 m/s`
- smoothed grip-demand proxy 95th percentile: about `1.64 g`
- smoothed grip-demand proxy max: about `2.21 g`

Interpretation:

- this is not the hidden surface `mu` table
- it is an empirical demand proxy from one recorded lap line
- it is still useful for AI training because it marks where the driven line is asking the most from the tire-track system
- the peaks are high enough that this proxy should be treated as a relative map, not as a literal calibrated friction coefficient

## New Repro Script

A reusable decoder for this path now exists:

- `scripts/decode_iracing_olap.py`

Example:

```powershell
python scripts/decode_iracing_olap.py "C:\Users\Admin\Documents\iRacing\lapfiles\lagunaseca\605804_formulavee.olap" --outline-image artifacts\iracing_dat_extract\lagunaseca_pmts_1920x1080_type7.png
```

Validation notes:

- the same decoder also worked on `605804_rt2000.olap`
- `605804_audir18.olap` exposed `format_version = 0`, which the script now rejects as an unsupported payload variant instead of returning misleading numbers

## What The `.dat` Files Can And Cannot Give You

### What they can give you now

From static local inspection, the `.dat` files give you:

- the canonical Laguna Seca asset package location
- track build/version association
- evidence that the assets are packed and not plain-text
- evidence that the source-of-truth geometry/material data is likely inside the container

### What they do not give you yet

From static local inspection alone, the `.dat` files do not yet give you:

- a decoded road mesh
- explicit left/right boundary polylines
- a readable lane graph
- a readable per-cell or per-surface `mu` table
- a directly usable asphalt/curb/grass polygon map

That means the accurate statement is:

- the data is probably in the `.dat` path somewhere
- it is not currently accessible by simple static extraction
- for deeper recovery you need either runtime memory extraction or a broader container decoder

## Runtime Probe With Laguna Loaded

While Laguna Seca was live in the simulator, a runtime probe confirmed several additional facts.

Process:

- running process: `iRacingSim64DX11.exe`
- executable path: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

Important runtime handle result:

- under elevated inspection, the live process had `C:\Program Files (x86)\iRacing\tracks\lagunaseca\lagunaseca.dat` open
- it also had `C:\Users\Admin\AppData\Local\iRacing\replay\_spool.tmp` open

Interpretation:

- the simulator is actively using the Laguna DAT asset package at runtime
- the current state was replay-oriented, which explains why some live surface channels were unavailable

Live session data from the SDK / shared-memory path:

- `TrackName`: `lagunaseca`
- `TrackDisplayName`: `WeatherTech Raceway Laguna Seca`
- `TrackLength`: `3.5652 km`
- `TrackVersion`: `2026.02.26.04`
- `TrackDynamicTrack`: `1`
- `SessionTrackRubberState`: `moderately high usage`
- `TrackWetness`: `1`
- `TrackSurfaceTempCrew`: about `34.44 C`
- `TrackAirTemp`: about `18.73 C`
- `TrackWeatherType`: `Realistic`
- `TrackSkies`: `Dynamic`

Important runtime caveat:

- `IsOnTrack = False`
- `IsOnTrackCar = False`
- `PlayerTrackSurface = -1`
- `PlayerTrackSurfaceMaterial = -1`
- all `CarIdxTrackSurface*` values were `-1`

Interpretation:

- the runtime surface/material channels do exist
- they were not populated in this probe because the sim was not currently in an active on-track driving state
- this is a session-state limitation, not evidence that the telemetry channels are missing

Artifacts generated from the runtime probe:

- `artifacts/iracing_runtime_probe.json`
- `artifacts/iracing_runtime_session_info.yaml`

Reusable script:

- `scripts/probe_iracing_runtime.py`

## Confirmed DAT Container Structure

This is the farthest confirmed static reverse-engineering result from the local Laguna Seca package.

### Chunk format

Multiple sections of `lagunaseca.dat` are organized as typed chunks with:

- `tag[4]`
- `zero[4]`
- `payload_len_le[4]`
- `payload`
- padding to 4-byte alignment using `0x20` bytes

Confirmed tags:

- `ATAD` = `DATA`
- `PAMB` = `BMAP`
- `DHMB` = `BMHD`
- `PMTS` = `STMP`-like parent chunk
- `DHTS` = `STHD`-like header chunk

### Confirmed bitmap header layout

For `DHMB` payloads with length `14`, the following layout is confirmed:

- byte `0`: type id
- bytes `1..4`: width
- bytes `5..8`: height
- bytes `9..12`: row stride in bytes
- byte `13`: format/flags id

Examples recovered from Laguna Seca:

- `0a 20 00 00 00 20 00 00 00 10 00 00 00 17` -> type `10`, `32x32`, stride `16`
- `07 e0 00 00 00 8a 00 00 00 80 03 00 00 17` -> type `7`, `224x138`, stride `896`
- `07 80 07 00 00 38 04 00 00 00 1e 00 00 17` -> type `7`, `1920x1080`, stride `7680`
- `06 00 0f 00 00 70 08 00 00 00 2d 00 00 17` -> type `6`, `3840x2160`, stride `11520`

### Confirmed DATA payload variants

`ATAD` payloads appear in two forms:

1. small inline/raw payloads
2. compressed payloads with a 16-byte prefix followed by one or more zstd frames

For zstd-backed `ATAD`, the first 16 payload bytes behave like:

- u32 `segment_count`
- u32 `segment_output_size` or tile output budget
- u32 `0`
- u32 first compressed-frame size hint

Confirmed examples:

- `[1, 131072, 0, 398]` -> one zstd frame, `512` bytes output
- `[1, 131072, 0, 6608]` -> one zstd frame, `123648` bytes output
- `[64, 131072, 0, 25]` -> sixty-four zstd frames, `8294400` bytes total output
- `[190, 131072, 0, 4426]` -> one hundred ninety zstd frames, `24883200` bytes total output

For the multi-frame cases, the number of detected zstd frame starts matched `segment_count` exactly.

## Assets Recovered

Using the confirmed chunk rules and zstd decoding, the following Laguna Seca assets were extracted directly from `lagunaseca.dat`:

- a `224x138` RGBA badge/logo image
- a `1920x1080` RGBA track-outline image
- a `3840x2160` RGB loading-screen / scene image

Extracted files:

- `artifacts/iracing_dat_extract/laguna_224x138_rgba.png`
- `artifacts/iracing_dat_extract/laguna_1920x1080_rgba.png`
- `artifacts/iracing_dat_extract/laguna_3840x2160_rgb.png`

What these prove:

- the DAT package definitely embeds decodable visual assets
- the container is at least partially understood
- some Laguna-specific 2D track imagery is recoverable statically

What they do not prove:

- these are UI / presentation assets, not the physical road mesh
- they do not contain per-cell grip coefficients by themselves
- they are not sufficient to recover exact 3D boundaries or the hidden surface-physics tables

### Texture-family observation

The most common decodable family in the DAT is a large number of `PAMB/BMHD/ATAD` bitmap groups.

One confirmed family uses:

- type `10`
- mip-chain dimensions `1x1` up to `1024x1024`
- zstd-backed payloads whose output sizes scale like packed GPU texture data rather than plain RGBA pixels

When rendered naively as grayscale, these decode into noise-like patterns, which is consistent with GPU-oriented packed texture formats rather than directly viewable source images.

Pushing that further, one `type 10` sample was successfully decoded as a BC1 / DXT1 texture and rendered into a recognizable tire-wall material. That confirms at least part of the large texture family is stored as GPU block-compressed image data rather than custom encryption.

Example decoded output:

- `artifacts/iracing_dat_extract/laguna_type10_1024x1024_bc1.png`

That matters because some track-physics-adjacent maps may live in these texture families, but identifying which ones correspond to physical surface fields still requires additional semantic decoding.

## Physics Model Recap

The local executable provides strong evidence that iRacing splits physics across compiled code and external parameter data.

### 1. Compiled executable side

File:

- `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

#### Tire model / tire analysis

Observed strings:

- `tire2Descriptor::v6params`
- `tire2Descriptor::v9params`
- `RunTireTestsOnStartup`
- `PerformTireAnalysis@TireAnalysisManager`
- `testLoad`
- `testSpeed`
- `testColdPressure`
- `testHotPressure`
- `testCamber`
- `testSurfaceTemperature`
- `testCarcassTemperature`
- `oppWheelGripModifier`

Interpretation:

- tire behavior is not a simple constant-friction model
- the sim uses a compiled tire model fed by descriptor/versioned parameter sets
- analysis and validation tooling for tires exists in the executable

#### Rigid-body / contact / integration side

Observed strings:

- `rePhysicsWorld_UpdateBodyTouchMeshFlags`
- `rePhysicsWorld_AddBodyForces`
- `rePhysicsWorld_UpdateCollideEvents`
- `rePhysicsWorld_EulerIntegrate`
- `rePhysicsWorld_TransformMeshContacts`
- `rePhysicsWorld_TransformPairContacts`
- `rePhysicsWorld_ImproveIntegrate`
- `rePhysicsWorld_CollideMesh`
- `rePhysicsWorld_CollidePairs`

Interpretation:

- contact generation, collision, and state integration are compiled systems
- this is where suspension, wheel loads, impacts, and contact resolution are handled

#### Track-surface parameter families

Observed strings:

- `track_mpd_`
- `track_tanphi_`
- `track_sqrtkrhoc_`
- `track_gripsealer_`
- `track_polish_min_mpd_`
- `track_polish_max_mpd_`
- `track_polish_min_tanphi_`
- `track_polish_max_tanphi_`
- `track_polish_min_sqrtkrhoc_`
- `track_polish_max_sqrtkrhoc_`

Interpretation:

- iRacing is not using one global grip coefficient for the whole track
- the surface model appears to use multiple parameters tied to polish/sealing/state
- the executable expects track-surface inputs that likely come from external data

#### Dynamic track state

Observed strings:

- `rubberlevel_practice`
- `rubberlevel_qualify`
- `rubberlevel_race`
- `rubberlevel_testing`
- `rubberlevel_warmup`
- `gripcompoundlevel_practice`
- `gripcompoundlevel_testing`
- `gripcompoundlevel_warmup`
- `gripcompoundlevel_qualify`
- `gripcompoundlevel_race`
- `dtdBaseRubber`
- `trackWetPolish`
- `trackMarbles`
- `trackWaterHeight`
- `trackDirtWater`

Interpretation:

- grip depends on session state, rubbering, contaminants, and wetness
- even if a base surface coefficient exists, the effective local grip is dynamic

#### Telemetry/runtime surface identifiers

Observed strings:

- `PlayerTrackSurfaceMaterial`
- `PlayerTrackSurface`
- `CarIdxTrackSurfaceMaterial`
- `CarIdxTrackSurface`
- `irsdk_TrkSurf`
- `irsdk_TrkLoc`

Interpretation:

- the runtime model exposes surface category/type information
- this is useful for labeling telemetry samples by surface class
- it still does not reveal the hidden base `mu` table directly

#### Suspension and aero examples

Observed suspension strings:

- `springDefl`
- `springForce`
- `shockVel`
- `shockForce`
- `arbOffset`
- `arbForce`

Observed aero strings:

- `AeroYaw`
- `AeroPitch`
- `carDragMod`
- `carDownforceMod`
- `dragArea`
- `dpWingRear`
- `dcWingRear`

Interpretation:

- suspension and aero are also compiled models with external parameter inputs
- that matches the usual architecture: code implements the equations, data sets the vehicle/track-specific values

### 2. External-data side

The reverse-engineering evidence supports this practical split:

- executable: tire model, suspension solver, aero model, contact/collision/integration logic
- external data: vehicle descriptors, tire descriptors, track-state inputs, and probably packed track/material assets

That is the correct high-level architecture to present in the project.

## Best Reconstruction Pipeline For AI Training

If the goal is a virtual Laguna Seca with accurate boundaries and local grip for lap-time optimization, the best local-data stack is:

### Boundary geometry

Use in this order:

1. decoded track assets from `lagunaseca.dat` if you can recover them at runtime
2. `.olap` / `.blap` files to recover a dense centerline or reference line
3. repeated `.ibt` laps to estimate lateral spread and infer practical lane boundaries

Why:

- the `.dat` file is probably the canonical source
- but right now it is still opaque on the physics side
- `.olap` is now partially decoded and already gives a usable metric centerline
- `.ibt` gives real driven trajectories across cars and conditions

### Grip map

Use in this order:

1. hidden track/material parameters if recovered from runtime memory
2. `.ibt` telemetry to estimate effective grip empirically

For empirical grip, combine:

- `Speed`
- `LapDist`
- `Lat`
- `Lon`
- `Alt`
- `YawRate`
- `LatAccel`
- `LongAccel`
- runtime surface labels when available, especially `PlayerTrackSurfaceMaterial` / `CarIdxTrackSurfaceMaterial`

Result:

- not the hidden base `mu` table
- but a very useful effective-grip map by location, car, condition, and line choice

For AI lap-time work, that effective-grip map is often more valuable than a raw static coefficient anyway.

## Project-Ready Conclusion

If you say:

"I want to do AI training and lap-time optimization from a virtual image of Laguna Seca, with the boundaries and grip level modeled as precisely as possible."

Then the technically correct answer from the local reverse-engineering work is:

- Laguna Seca's install package is stored in packed `.dat` containers
- those containers are probably the canonical source for mesh/material data
- static inspection did not recover a readable boundary mesh or per-surface grip table
- the Laguna `.olap` path is now decoded enough to recover a sampled centerline and an interval-by-interval speed/curvature map
- the DAT-derived outline and the `.olap`-derived centerline align closely, so they can be fused into a practical virtual-track scaffold
- the executable clearly contains the compiled tire, suspension, aero, and dynamic-track logic
- the executable also exposes the surface/state parameter families that drive grip at runtime
- the most practical high-accuracy reconstruction path is: `.dat` for canonical source, `.olap` for centerline structure, `.ibt` for empirical grip and boundary refinement

## Best Next Step

If you want the next reverse-engineering step after this, the most promising route is:

1. run the sim with Laguna Seca loaded
2. find where the loaded track block is materialized in memory
3. trace references near `track_gripsealer_`, `track_polish_*`, and the surface telemetry identifiers
4. dump the decoded track/material structures from memory instead of attacking the packed `.dat` blindly

That is the likeliest way to recover the hidden boundary/material data with high fidelity.

## Repro Script

A reusable partial extractor is available here:

- `scripts/extract_iracing_dat_assets.py`
- `scripts/decode_iracing_bc1_atad.py`

Example:

```powershell
python scripts/extract_iracing_dat_assets.py "C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat"
```
