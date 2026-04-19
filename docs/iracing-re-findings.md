# iRacing Reverse-Engineering Findings

Date: 2026-03-30

## Scope

This note documents a first-pass reverse-engineering sweep of:

- `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`
- `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat`
- `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\school\school.dat`

The goal was to test the claim that:

1. core vehicle/track physics logic lives in compiled code
2. track and tire inputs are loaded from external data containers

## Conclusion

The executable contains strong evidence of compiled physics systems and named parameter families:

- tire descriptors and tire-test controls
- world-physics update/collision/integration routines
- track parameter keys for grip/polish/surface state
- suspension and aero-related state/controls

The Laguna Seca `.dat` files behave like packed opaque containers:

- common `0x0003` version marker at the start
- very high entropy across the file
- no readable surface coefficient table in plain ASCII
- no successful decompression at candidate `zlib/gzip` offsets

This supports the architecture claim, but it does **not** yet recover a plain-text per-surface `mu` table from Laguna Seca.

## Executable Evidence

### Tire model / tire analysis

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

- `.rdata` `0x01DC1430`: `tire2Descriptor::v6params`
- `.rdata` `0x01DC1450`: `tire2Descriptor::v9params`
- `.rdata` `0x01DC1470`: `tire2Descriptor`
- `.rdata` `0x01EAE440`: `tire2Descriptor of compound %d is incorrect version. FIX THE CAR!`
- `.rdata` `0x01EAE488`: `wheel2Descriptor incorrect version. FIX THE CAR!`
- `.rdata` `0x01EAE4C0`: `RunTireTestsOnStartup`
- `.data` `0x0F56E580`: `PerformTireAnalysis@TireAnalysisManager`

Nearby strings also include:

- `testLoad`
- `testSpeed`
- `testColdPressure`
- `testHotPressure`
- `testCamber`
- `testSurfaceTemperature`
- `testCarcassTemperature`
- `oppWheelGripModifier`

### World physics / solver

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

Decorated symbols found in `.data` around `0x0F56DF40-0x0F56E580`:

- `rePhysicsWorld_UpdateBodyTouchMeshFlags`
- `rePhysicsWorld_AddBodyForces`
- `rePhysicsWorld_UpdateCollideEvents`
- `rePhysicsWorld_EulerIntegrate`
- `rePhysicsWorld_TransformMeshContacts`
- `rePhysicsWorld_TransformPairContacts`
- `rePhysicsWorld_ImproveIntegrate`
- `rePhysicsWorld_CollideMesh`
- `rePhysicsWorld_CollidePairs`

This is direct evidence that at least part of the rigid-body / contact / integration stack is compiled into the executable.

### Track grip / dynamic surface parameter keys

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

Strings in `.rdata` around `0x01DC0F40`:

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

These are not proof of a readable Laguna Seca coefficient table, but they are strong evidence that the simulation uses named track-surface parameter families for grip and polish behavior.

### Dynamic track / session grip controls

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

- `.rdata` `0x01E4CBF8`: `rubberlevel_practice`
- `.rdata` `0x01E4CF10`: `rubberlevel_qualify`
- `.rdata` `0x01E4CF28`: `rubberlevel_race`
- `.rdata` `0x01E4D780`: `rubberlevel_testing`
- `.rdata` `0x01E4D998`: `rubberlevel_warmup`
- `.rdata` `0x0238E180`: `gripcompoundlevel_practice`
- `.rdata` `0x0238E1A0`: `gripcompoundlevel_testing`
- `.rdata` `0x0238E1E8`: `dtdBaseRubber`

### Surface-state variables

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

Examples:

- `trackWetPolish`
- `trackMarbles`
- `trackWaterHeight`
- `trackDirtWater`
- `lfDynamicTireMarblesMin`
- `lfDynamicTireMarblesMax`
- `lfDynamicTireGravelMin`
- `lfDynamicTireGrassMin`
- equivalent `rf`, `lr`, `rr` tire-surface variables

### Suspension

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

Examples:

- `springDefl`
- `springForce`
- `shockVel`
- `shockForce`
- `arbOffset`
- `arbForce`
- `dcAntiRollFront`
- `dcAntiRollRear`
- `dcShockLeftRear`
- `dcShockRightRear`
- `dcShockLeftFront`
- `dcShockRightFront`

### Aero

File: `C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe`

Examples:

- `AeroYaw`
- `AeroPitch`
- `carDragMod`
- `carDownforceMod`
- `AI.LapTimeCalc.AeroDrag`
- `AI.LapTimeCalc.AeroLift`
- `dragAreaLowDf`
- `dragAreaHighDf`
- `dragArea`
- `dpWingRear`
- `dcWingRear`
- `dpWingFront`
- `WingFrontLevel`
- `WingRearLevel`

## Laguna Seca `.dat` Evidence

### Main track package

File: `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat`

- Size: `271,922,406` bytes
- First bytes: `03 00 41 64 B5 24 5D 25 ...`
- `U16_LE@0 = 3`
- Sample entropy:
  - head: `7.9919`
  - middle: `7.9791`
  - tail: `7.9828`
- No repeated 16-byte or 32-byte blocks in the first `64 KiB` sample
- No successful `zlib/gzip` decode at candidate offsets tested
- No readable keyword strings for grip/surface/material tables in a targeted scan

### School config package

File: `C:\Program Files (x86)\iRacing\Tracks\lagunaseca\school\school.dat`

- Size: `78,421` bytes
- First bytes: `03 00 9D C6 B8 C0 08 8A ...`
- `U16_LE@0 = 3`
- Entropy across samples: `~7.98`
- No readable keyword strings

### Cross-track comparison

Other iRacing track packages tested:

- `C:\Program Files (x86)\iRacing\Tracks\daytona\daytona.dat`
- `C:\Program Files (x86)\iRacing\Tracks\barcelona\barcelona.dat`

Observed:

- same `0x0003` start marker
- similarly high entropy
- similarly opaque headers

This is consistent with a common packed container format, and inconsistent with a plain-text or lightly structured coefficient table.

## Reproduction Commands

### EXE mapping

```powershell
python scripts/inspect_pe_strings.py "C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe" --pattern "PerformTireAnalysis|TireAnalysisManager|rePhysicsWorld_|RunTireTestsOnStartup|tire2Descriptor of compound|wheel2Descriptor incorrect version" --context 4
```

```powershell
python scripts/inspect_pe_strings.py "C:\Program Files (x86)\iRacing\iRacingSim64DX11.exe" --pattern "gripcompoundlevel_|rubberlevel_|dtdBaseRubber|track_polish_|track_gripsealer_|track_mpd_|track_tanphi_|track_sqrtkrhoc_" --context 4
```

### Track container probing

```powershell
python scripts/inspect_iracing_dat.py --no-strings "C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat"
```

```powershell
python scripts/probe_iracing_track_container.py "C:\Program Files (x86)\iRacing\Tracks\lagunaseca\lagunaseca.dat" "C:\Program Files (x86)\iRacing\Tracks\daytona\daytona.dat" "C:\Program Files (x86)\iRacing\Tracks\barcelona\barcelona.dat" --zlib-offset 29731 --zlib-offset 50841 --zlib-offset 128095 --zlib-offset 18991568 --zlib-attempts 4
```

## Best Next Step

If the goal is to actually recover Laguna Seca per-surface coefficients, the most promising follow-up is:

1. identify the track-loader code path in the executable
2. find where `track_gripsealer_` / `track_polish_*` strings are referenced
3. inspect the memory representation after the `.dat` is loaded, instead of trying to decode the packed file blind

Blind static carving of `lagunaseca.dat` alone is currently not enough to recover the values.
