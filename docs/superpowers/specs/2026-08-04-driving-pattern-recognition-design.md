# Driving Pattern Recognition — design

**Date:** 2026-08-04
**Branch:** `feat/driving-pattern-recognition` (worktree `C:/Users/Admin/lap_web-wt-patterns`), originally forked from `feat/adaptive-coaching` @ `476a889` — **must be rebased onto `fix/per-lap-distance-frame` before Phase 1 implementation** (see §11)
**Status:** design approved, plan pending
**Hard dependency:** the per-lap corner coordinate fix, split out as a standalone shippable change (see §11)

---

## 1. Problem

LAP renders telemetry graphics — g-g diagram, speed trace, GPS trace, racing line — and computes a large volume of derived data behind them. Nothing reads the **shape** of those signals.

Every detector in the codebase today is a scalar threshold or a sustained-run count:

- Throttle application is a single threshold crossing (`a_long > +0.5 m/s²` held 5 m, `corner_analysis.py:1839-1876`). There is no application slope, no linearity, no progressive-vs-stab classification.
- The speed trace's own curvature is never computed. Curvature exists only for the *track path* (`corner_detection._compute_curvature`).
- The g-g diagram is a viewer. `gg_explorer.js` offers all/single/compare modes, density colouring and lap animation, and extracts nothing.
- No mistake is ever assigned a time cost, and no detection is persisted in queryable form.

Three detection stacks exist with three vocabularies (`corner_diagnosis` 23 labels, `handling/` 17 fused detectors, `coaching/` 26-cause taxonomy). None measures trace shape or envelope exploitation.

**Consequence:** the product can draw the picture in which a mistake is visible, but cannot name it, locate it, price it, or notice that it happened again last week.

## 2. Goals

1. **Mistake tape** — located, typed, quantified, costed events, on *every lap*.
2. **Limit-exploitation map** — per corner-phase envelope use, expressing both under-use and over-use, against an honestly-labelled anchor.
3. **Driving signature** — cross-session recurrence of a fault, and whether it is improving.
4. **Annotated graphics** — events and phase segmentation projected onto the existing charts.

These are four **views of one record**, not four features. Building them separately would create a fourth unreconciled vocabulary.

## 3. Non-goals

- Not a new coaching taxonomy. New event types map onto the existing 26-cause `causes.json` vocabulary so tips and drills keep working.
- Not computer vision over rendered chart images. "Pattern recognition in the graphics" means reading the signals the graphics are drawn from.
- Not a replacement for the OCP solver or racing-line work.
- Not a fix for the theoretical lap's known under-estimation (it currently serves optimal laps *slower* than the driver's actual best — 71 s vs 61.7 s on real kart data). This design routes around it rather than depending on it.
- Not the per-lap coordinate fix — that ships separately (§11).

## 4. Evidence base

Every number below was measured during design, on real customer-shaped data
(`telemetry_tool/data/raw/OK_R4.csv`, RaceChrono Pro kart export, 211,002 rows, 10 laps).
Probe: `scratchpad/probe_corner_slice.py`, read-only.

| Question | Measurement | Consequence for the design |
|---|---|---|
| Do per-lap corner slices return data? | **9 of 10 laps return ZERO corner samples.** Rebasing each lap to `d − d_min` returns ~273 samples on all 10. | Blocking prerequisite. §11. |
| Distance-grid resolution inside a corner | 1.204 m/sample; at apex speed (10.8–13.9 m/s) that is 86–111 ms/sample → **~3 samples per 0.3 s**, but **25–79 samples per corner**. | Phase segmentation, plateau, trough and envelope fill are all viable on the existing grid. Only sub-second ramp/oscillation primitives are grid-limited. The time grid is a late, narrow phase — not a foundation. |
| Is the lateral-g channel trustworthy? | Median `\|a_lat\| / (v²κ)` = **0.961**, per-lap range 0.951–0.975, n≈650/lap, measured only where `v²κ > 2 m/s²` (i.e. in corners). | **Tier-1 physics anchor is viable on real kart data.** |
| What is the *true* native rate? | Row rate 250 Hz (median `dt` 4.0 ms) but `Device update rate (Hz)` is a flat **25.0** — the row grid is mostly interpolation. Raw IMU (`*acc`, `*gyro`) changes on ~223 k of 211 k rows → genuinely ~100 Hz. | Anything GPS-derived, **including `Speed (m/s)`**, is limited to 40 ms regardless of grid. Only the IMU carries sub-40 ms information. Restructures Phase 4 — see §4.2. |

### 4.1 A correction to the prior validation report

`docs/validation/attitude_correction_report.md` reports the lateral channel reading 15% low overall and **47% low on straights** (`cal_bias` 0.531), which had made a physics anchor look unusable.

That figure is a division artifact. On a straight `v²κ ≈ 0`, so the ratio is noise divided by noise. Restricted to samples that are actually in corners — the only place a grip anchor is used — agreement is **96%, stable to ±1.2% across all ten laps**. The channel is fit for this purpose.

### 4.2 A ~100 Hz IMU is being dropped at ingest

Every RaceChrono export carries six high-rate channels — `X/Y/Z acceleration (G) *acc` and `X/Y/Z rate of rotation (deg/s) *gyro`, both ~100 Hz. **LAP discards all six on every upload.**

The discovery patterns are `Accel.*X` and `Gyro.*X` (`column_discovery.py:116-121`); the actual headers put the axis letter *first* (`X acceleration`, `X rate of rotation`), so the regexes can never match and the columns fall through as "custom". The `racechrono_adapter._COLUMN_MAP` maps only the GPS-derived `*calc` lateral/longitudinal channels (`racechrono_adapter.py:70-76`).

Two consequences:

1. **The only sub-40 ms information in the file is in these channels.** `Speed (m/s)` is GPS-derived at a hard 25 Hz, so no regridding can recover finer speed-trace detail than 40 ms. A 0.3 s brake release is ~7.5 independent GPS samples versus ~3 on the current distance grid — a 2.5× gain, not the order of magnitude a naive reading of the 250 Hz row rate suggests. Accel-derived shape, by contrast, would go to ~30 samples.
2. **This explains the dead attitude-correction chain.** `sensor_quality._run_attitude_corrections` is gated on `accel_x_mps2`, which the earlier audit found "no module produces". Nothing produces it *because the ingest mapping never matches*. A single column-mapping fix would light up both the high-rate IMU and the orphaned `phone_mount_estimator → road_attitude_estimator → attitude_correction` chain.

**This is a candidate, not a promise.** Raw phone IMU is in the handset frame, contains gravity, and has failed calibration on real data before (the SLK kart gyro fails a yaw-ratio gate outright). It must be validated before any detector depends on it, and it must never silently replace the `*calc` channels that measure at 0.961 agreement today.

Phase 4 is therefore restructured (§6): the cheap, high-value half is **ingesting the IMU**; the expensive half is the time grid, which is only worth doing for channels that carry sub-40 ms information.

### 4.3 Facts that constrain the architecture

- **Production runs the pipeline as two separate Celery calls.** In the resume phase `raw_df = None` (`orchestrator.py:341`), `lap_dict` is never assigned, and `trimmed_df` is a concatenation of the *resampled* laps (`orchestrator.py:349-353`). All corner and coaching stages run in that phase. **No native-rate data exists in production when detection runs.**
- `handling/` is session-level, string-keyed (`runner.py:225-240`), best-lap-only (`runner.py:123-127`), and its corner ids are 0-based from its own `|a_lat| > 0.25 G` detector, unrelated to `corner_detection`'s 1-based ids. Its consumers look it up by int section id against string keys (`coaching_basic.py:403`, `coaching_advanced.py:235`) and have never matched.
- `corner_diagnosis`'s six yaw-derived labels are unreachable: `_COL_HEADING = "Heading (rad)"` (`corner_diagnosis.py:212`) has no producer anywhere in the repo. Additionally `curvature_1pm` is stored `abs()`-ed (`reference_line.py:701,753`), so `_compute_kappa_sign` returns +1 for every corner.
- `FrictionCircle` is never persisted (`orchestrator.py:898`). `FrictionEnvelope` and `GripMap` do reach the DB.
- `DataQualityReport` is stored as a dataclass (`orchestrator.py:926`) while both persistence paths gate on `isinstance(dq, dict)` — so `analysis_json.data_quality_summary` is never written.
- `sensor_quality.curvature_agreement` **is** computed and **is** persisted (`sensor_quality.py:436`), as a per-bin list of `cal_bias`.

## 5. Architecture

### 5.1 The spine — `DrivingEvent`

One record type. All four views are queries over it.

```python
@dataclass(frozen=True)
class DrivingEvent:
    # identity
    event_type: str            # controlled vocabulary, §5.4
    lap_number: int
    corner_id: int | None      # None for straight-line events
    corner_phase: str | None   # "entry" | "mid" | "exit"

    # location, in the canonical per-lap coordinate (§11)
    s_start_m: float           # 0-based per-lap metres
    s_end_m: float
    s_norm_start: float        # 0..1, lap-length invariant
    s_norm_end: float

    # magnitude, in the event type's own unit — never a bare number
    magnitude: float
    magnitude_unit: str        # "g" | "kph" | "m" | "s" | "deg" | "pct"

    # what limit this was measured against
    anchor_tier: str           # "physics" | "driver_best" | "refused"
    anchor_reason: str | None  # machine-readable, required when refused
    envelope_available: float | None
    envelope_use_pct: float | None   # NOT clamped at 100

    # cost
    time_cost_s: float | None
    time_cost_basis: str       # "driver_best_corner" | "unavailable"

    # trust
    confidence: float          # 0..1
    detector: str
    evidence: dict             # the numbers backing the claim, auditable
```

Three deliberate decisions:

- **`envelope_use_pct` is not clamped.** Today `corner_analysis.py:665` does `min(100.0, ...)`, `is_feasible` grants 5–10% slack, and `lap_simulation` clamps against the envelope. Over-driving is silently truncated everywhere, which is *why* it is currently inexpressible. Exceedance must be a first-class number.
- **`anchor_tier` is mandatory on every event.** No number is quoted without saying what it was measured against.
- **`evidence` is mandatory.** Any claim shown to a customer must be reconstructible from stored numbers.

Field names reuse `handling/types.py:132-151`'s `FusedEvent.to_dict()` vocabulary (`event_type`, `severity`, `corner_phase`, `confidence`) rather than coining a fourth set.

### 5.2 Capability-tagged detector registry

The 2026-04-19 north-star spec specified this and it was never built; all three current stacks hard-code their channel assumptions.

```python
class Detector(Protocol):
    name: str
    requires: frozenset[str]        # canonical channel names
    min_samples_per_corner: int     # grid-resolution requirement
    def detect(self, w: CornerWindow) -> list[DrivingEvent]: ...
```

The registry admits a detector only when the session provides every required channel **and** the corner window meets `min_samples_per_corner`. A detector that cannot run produces an explicit *not-measurable* record, never silence — mirroring `track_surface/prescriptive/_internal.py:118-151`'s `NotTriggered` / `Insufficient` / `Unregistered` distinction, which is the one place in the repo that models this correctly.

This is what makes "works on GPS-only kart data" a property of the system rather than a hope.

### 5.3 Tiered grip anchor

```python
def decide_anchor(corner, lap, session) -> Anchor
```

| Tier | Source | Gate |
|---|---|---|
| `physics_ellipse_fitted` | in-scope `FrictionCircle`, fitted exponent | bin provenance passes **and** inline channel-trust ratio in band **and** the exponent was genuinely fitted |
| `physics_ellipse_default_p2` | same, but the exponent fell back to the hint | as above, exponent not fitted — a true ellipse claim would be false |
| `driver_best_session` | that driver's best execution of that corner **in this session** | ≥2 laps produced a usable window for that corner |
| `refused` | none | always available; carries a machine-readable reason |

Ordered fail-safe downgrade, vocabulary constants and a single consumer guard, copied literally from `track_surface/honesty.py:13-75`.

Five corrections from verification, each of which invalidated an earlier draft of this section:

**The gate is NOT `sensor_quality.curvature_agreement`.** That signal is wrong on three axes at once: its bins are ~0.5 m *distance* bins along the centerline (`builder.py:270`, `frenet.py:126-127`) while the envelope is *speed*-binned; it admits samples down to `0.05 G ≈ 0.49 m/s²` (`sensor_quality.py:243`), the near-straight regime the committed report measures at `cal_bias` **0.531** — so the 0.961 figure in §4 is not a number that signal ever sees; and it is produced at step `10e_sensor_quality` (`orchestrator.py:1349-1355`), *after* the hook, so an anchor would read `None` and fail-safe to refused on every session. It is also all-zeros on any session with ≤3 usable laps, with `0.0` doubling as the "not measured" sentinel (`sensor_quality.py:266`, `:279`). **Instead:** compute the trust ratio inline over our own corner mask, restricted to `v²κ > 2 m/s²` — the condition under which 0.961 was actually measured. ~15 lines over arrays already in hand.

**Tier 1 uses the in-scope `FrictionCircle`, not the persisted `FrictionEnvelope`.** `FrictionCircle` holds the fitted ellipse exponent and is never persisted — but it is already passed into the hook stage as `friction_model=summary.get("friction_model")` (`orchestrator.py:1178`). So the fitted ellipse is free and the "persist the ellipse" workstream disappears. The persisted `FrictionEnvelope` hardcodes p=2 (`friction_envelope.py:98-108`); quoting it under a `physics` label would be a false provenance claim.

**Units.** `FrictionCircle` is m/s²; `FrictionBin`/`GripMap` μ are G. The existing path is already unit-correct — `_resolve_accel_lat` (`corner_analysis.py:316-324`) converts to m/s² and compares against `FrictionCircle.lateral_max`, also m/s². The 9.8× hazard is *created* the moment a baseline is read from the envelope. Keep the arithmetic in m/s², convert at one named boundary, and name the persisted column `grip_anchor_baseline_g` so a reviewer catches an unconverted value.

**Fabricated-bin detection** reduces to one exact test: `confidence == 0.0` ⟺ `sample_count < 8` (`friction_envelope.py:221-234`, `:248`). Drop the `accel_max_g == global * 0.6` proxy — `round(g*0.6, 4)` vs `round(g, 4)*0.6` (`:229` vs `:268`) makes it fail most of the time.

**Never cap at 100%.** The legacy `grip_utilisation_pct` does (`corner_analysis.py:665`). The lateral envelope is a *percentile*, not a maximum (`friction_model.py:465`, `:549-568`), so exceeding it is expected — and exceedance is the single most diagnostic value available, both for over-driving and for detecting that the envelope or the channel is wrong. Capping destroys it.

`is_feasible` is not used: it tests a circle with 5–10% slack (`friction_envelope.py:69-83`), deliberate solver headroom for `lap_simulation`, which would inflate every percentage by 5–10 points.

### 5.4 Shape primitives

A pure library. No I/O, no pipeline knowledge, unit-testable in isolation.

| Primitive | Output | Grid-limited? |
|---|---|---|
| `segment_phases` | entry/mid/exit index spans | no — lift `handling/calibration.segment_corner_phases:226` |
| `plateau` | width, level, span | no |
| `trough` | depth, roundness, width at fraction | no |
| `envelope_fill` | fill fraction, max exceedance, exceedance area, per phase | no |
| `coast_gap` | duration, distance | no |
| `ramp` | slope, R², duration | **yes** — needs the time grid |
| `oscillation` | sign changes, RMS | **yes** |

Only the last two require Phase 4. This is the measured basis for deferring the time grid.

### 5.5 Initial detector set

✓ = runs on GPS-only tier-2 data, i.e. what LAP's actual customers upload.

| Detector | Basis | ✓ |
|---|---|---|
| `over_braking` | peak decel vs envelope brake axis, plus resulting min-speed deficit | ✓ |
| `over_slowing` | min speed below driver's best at that corner, causally linked to the preceding brake event | ✓ |
| `coast_gap` | neither accel nor decel beyond a band, between brake release and throttle | ✓ |
| `late_throttle` | throttle-on point vs driver best, magnitude in metres | ✓ |
| `envelope_under_use` | per-phase fill fraction below threshold vs anchor | ✓ |
| `envelope_exceedance` | samples outside the fitted ellipse, with magnitude | ✓ |
| `corner_rounding` | combined-g trace shape through the brake→turn transition ("square vs round") | ✓ |
| `re_braking` | second decel event after the apex | ✓ |
| `understeer` / `oversteer` | **from `handling/`, spatially joined** — not re-implemented | ✓ |
| `lockup`, `wheelspin` | require brake pressure / wheel speed | ✗ dark on tier 2 |

`handling/` is consumed as a **detector source**, spatially joined on `s_start`/`s_end` overlap. It is not promoted to a canonical label store: it is session-level, best-lap-only, string-keyed, and uses a different corner numbering. Joining is correct; promoting is not.

`corner_diagnosis`'s yaw labels are **not** retired until Phase 2 events are landing and coverage is proven equal. They are currently the only per-lap-per-corner label that persists anywhere; retiring first would replace something with nothing.

### 5.6 Time cost

Anchored to **the driver's own best execution of that corner**, never the theoretical lap.

No existing time-loss field is reusable: every one is anchored to the theoretical lap and clamped `≥ 0` (`corner_analysis.py:711-722`, `s10b_corners.py:366-367`), and the theoretical lap is in a different coordinate frame (rebased to zero) *and* is known to be slower than the driver's real best.

If a lap is better than the reference, the event does not fire. No silent negative-clamping.

### 5.7 Persistence

Migration `085_driving_events` off single head `084_merge_chain_ab`, workspace-scoped and RLS-enabled, copying `081_feeling_competition.py:43-82`.

**Plus the `db/schema.py` mirror, `ALL_TABLES`, and a `SCHEMA_VERSION` bump.** Omitting this is precisely why `store_corner_progression` was written, never wired, and never testable — the standard pytest fixture builds from `db/schema.py`, so a table that exists only in alembic cannot be unit-tested.

Note an existing asymmetry to resolve: `get_driver_corner_trends` **is** live (`s13_coaching_v3.py:160,164`, pipeline step 13f) while its writer has zero callers. There is a dead read path in production; this design adopts it or retires it explicitly.

### 5.8 Delivery

- `GET /sessions/{id}/events` — the tape.
- `/gg-data` extended with per-sample `corner_id` + `phase`, and a real envelope boundary (today the dashed circle is `0.95 × max observed` — derived from the same points it is drawn over, so it can never diagnose anything).
- Charts reuse existing draw primitives: the distance-range band (`SpeedTraceChart.tsx:505-517`) is the corner shade; the per-segment bottom strip (`:519-538`) is the tape; the metre-keyed hover store carries event markers with no store changes.
- Overlays become parameters of the pure-draw functions. `ChartAnnotations` is not reused — it paints externally and the next `clearRect` erases it.

## 6. Phases

| Phase | Content | Rationale |
|---|---|---|
| **0** | *Separate deliverable* — per-lap coordinate fix (§11) | Everything below aggregates per-lap corner data, which is currently empty on laps 2..N |
| **1** | Tiered anchor + trust gate, on the existing distance grid | Every downstream number is quoted against this, and it is the piece most likely to fail on real data — so it goes first |
| **2** | Per-lap phase segmentation, `DrivingEvent`, migration 085, detector registry, the ✓ detector set | The spine. None of it needs the time grid. |
| **3** | Mistake tape + exploitation map in the webapp | One visible surface proves the events mean something; draw primitives already exist |
| **4a** | **Ingest the dropped IMU** (§4.2): fix the column patterns, validate the six channels against the trusted `*calc` ones, and gate them behind a calibration check. Additive — never replaces `*calc`. | Cheap (a mapping fix), high value (the only sub-40 ms information in the file), and it also unblocks the orphaned attitude-correction chain. Must precede 4b: regridding channels that carry no sub-40 ms information buys ~2.5×. |
| **4b** | Time grid + `ramp` / `oscillation` primitives, **only for channels proven to carry sub-40 ms information** | Only change touching the Celery two-phase contract and the pipeline hash. Native-rate **corner windows** persisted from phase A, not whole laps. Scope is decided by 4a's outcome. |
| **5** | Cross-session signature | Gated on wiring `corner_persistence.resolve_corners`; corner identity across sessions is an independent risk and must not block the per-session product |

## 7. Validation

No human-labelled corner exists anywhere in the repo, so precision/recall is unmeasurable and every threshold in all three existing stacks is unvalidated. Substitutes:

1. **Synthetic-mistake injection** — inject a fault of known type, location and magnitude into a clean lap; assert the detector finds it at the right place with the right magnitude and a sane time cost. Injection happens at **native rate**, not into resampled laps — injecting into the coarse grid would fail to test the thing Phase 4 exists for.
2. **Label-distribution stability harness** over the real corpus — a detector whose label mix swings wildly between similar sessions is miscalibrated.
3. **Honesty tests** — assert tier-3 refusal fires when the trust gate fails, and that no `envelope_use_pct` is emitted without an `anchor_tier`.
4. **Bite-check every test** — deliberately break the code each new test guards and confirm it goes red before accepting it.

## 8. Risks

| Risk | Mitigation |
|---|---|
| **Persisting a `confidence` we cannot defend.** `handling/fusion.py:117-121` was retuned to lift mean confidence ~20%→~50% with no ground-truth calibration, and three detectors that anti-correlate with TUMFTM truth still vote at full weight. | Do not inherit that number under the name "confidence". Either calibrate it or emit an ordinal. Decide in Phase 2. |
| **Unit boundary.** `FrictionCircle` is m/s²; `FrictionBin` and `GripMap` μ are G. A 9.8× error is one assignment away. | Units in every field name or a typed quantity. Test asserts magnitude ranges. |
| **Ellipse vs circle.** `is_feasible` tests a *circle* with 5–10% slack, not the fitted ellipse; fill computed two ways disagrees by construction. | Spec fixes the fitted ellipse as canonical. Single implementation. |
| **Cross-session corner identity.** `corner_id` is positional from a single first-lap detection with an adaptive p85 curvature threshold, so a wet and a dry session can renumber everything. | Phase 5 gate. Does not block Phases 1–4. |
| **Envelope provenance.** No flag distinguishes measured bins from floored ones. | Use the three proxies in §5.3 now; add a real flag in Phase 1. |
| Adding a genuinely new cause requires a `causes.json` entry, 6 `CORNER_TIPS` entries and a drill, or the composer degrades to a generic string. | Map new event types onto existing causes first; add causes only with the full set. |

## 9. Resolved ambiguities

These were open during design and are now decided, so implementation has no discretion.

**Envelope use is two distinct numbers, both stored.** `envelope_use_pct` is *instantaneous*: the sample's combined-g magnitude as a fraction of the fitted-ellipse boundary **along that sample's own combined-g direction**. The exploitation map instead aggregates `envelope_fill_area` — the fraction of the reachable ellipse sector swept during the phase. A single number cannot serve both: instantaneous use answers "did you exceed the limit at this instant", area fill answers "did you use the whole envelope through this corner". A driver can score 100% instantaneous and 40% area by touching the limit once and coasting the rest.

**Tier 2 is session-scoped in Phase 1, and named `driver_best_session` to say so.** Cross-session "your best at this corner" is not buildable yet and must not be attempted: `corner_id` is a positional index over curvature regions found in *one lap of one session* (`corner_detection.py:709-717`), an adaptive retry can renumber every corner after it (`:721-734`), and `corner_persistence.match_corners`/`resolve_corners` — written to solve exactly this — has zero production callers. Corner 4 in session A and corner 4 in session B are not guaranteed to be the same piece of tarmac.

Condition cannot carry the partition either: `sessions.track_state` is `NOT NULL DEFAULT 'dry'` (`db/schema.py:63`), the upload UI never sends it, and the weather classifier overwrites it — so `dry` frequently means "nobody said". Pooling under that is the same class of error the anchor exists to prevent.

The Phase 1 value is still real and honest: *"you used 84% of your own best through here today."* Naming the tier `driver_best_session` now means cross-session becomes a **new** tier value (`driver_best_track`) in Phase 2 rather than a silent redefinition — the discipline `honesty.py`'s `TIERS` frozenset enforces. Reserve `condition_unknown` and `corner_identity_unstable` in the reason taxonomy now, so whoever attempts the cross-session lookup must handle both deliberately.

**Spatial join tolerance for `handling/` events is 50% span overlap**, computed in the canonical per-lap coordinate. Below that the handling event is attached to the *lap* rather than to a corner, rather than being force-fitted to the nearest corner.

**`min_samples_per_corner` defaults to 20**, grounded in the measurement that real corners carry 25–79 samples on the distance grid (§4). `ramp` and `oscillation` override it upward and are consequently dark until Phase 4.

## 10. Scope note

Each phase gets its own implementation plan. This spec is the shared contract between them — principally the `DrivingEvent` shape (§5.1), the detector protocol (§5.2) and the anchor tiers (§5.3). Phases 1–3 are one coherent deliverable; 4 and 5 are independently schedulable and neither blocks customer-visible value.

## 11. Split-out prerequisite: per-lap corner coordinate fix

**Shipped separately, independently deployable.** Own branch, own plan.

Corners are detected on the first resampled lap only (`s07_resample.py:82-83`) and carry that lap's **absolute** distance span. RaceChrono's `Distance (m)` is cumulative session distance, and resampling preserves each lap's absolute range (`resampling.py:201-204`). The ubiquitous slicing idiom `(dist >= s_start) & (dist <= s_end)` — `corner_analysis.py:339`, `s10b_corners.py:427`, `s13_coaching_v3.py:265` — therefore returns an empty mask on every lap but the detection lap.

It fails silently: `_enrich_corner_telemetry` early-returns on `len(corner_idx) <= 2`, and the per-lap loop swallows exceptions with a bare `except ... continue` (`s10b_corners.py:380-382`).

Measured: **9 of 10 laps return zero corner samples; all 10 return ~273 after rebasing.**

A complication the fix must handle: `distance_integrity` rebuilds distance from zero via `cumsum` **only for laps that fail its monotonicity gate**, so within one session some laps can be 0-based and others cumulative. A single session-wide offset is therefore not valid; the fix must normalise per lap.

**STATUS: BUILT.** Branch `fix/per-lap-distance-frame` (worktree `C:/Users/Admin/lap_web-wt-distframe`), 26 commits, plan `docs/superpowers/plans/2026-08-04-per-lap-distance-frame-fix.md`, runbook `docs/runbooks/per-lap-distance-frame-deploy.md`. Whole-branch review clean after one fix wave. Not deployed — deploy-gated.

The blast-radius analysis found **five** mutually incompatible coordinate frames in production, not one. The fix rebases `Distance (m)` in place at `resampling.py`, which collapses all five at once because resampling runs unconditionally and sits downstream of every producer of frame heterogeneity.

**This is a hard dependency for Phase 1, not merely a prerequisite in principle.** Phase 1's verification named "per-lap corner windows may be empty on real customer data" as its single biggest risk — and that is precisely this bug: every gate Phase 1 builds would pass, and the anchor would confidently label a number computed over one lap as `physics`. That is the honesty layer delivering the exact failure it exists to prevent.

So `feat/driving-pattern-recognition` must be rebased onto `fix/per-lap-distance-frame` before any Phase 1 code is written. Building Phase 1 on the `476a889` base would produce a tier-1 anchor that is confidently wrong on 9 of 10 laps.

**Also folded into that deliverable** (both are silent-failure fixes of the same character, both prerequisites for trustworthy aggregates):

- Pass `best_lap_number` into `run_handling_analysis_v2` (`orchestrator.py:1233-1236` vs `s10b_corners.py:759-760`).
- Count and report the swallowed per-lap corner exceptions rather than discarding them.
- Persist `DataQualityReport.to_dict()` (one-line `isinstance` fix).

**Explicitly NOT folded in:** the dropped return of `apply_kart_traction_floor` (`s09_physics.py:269`). Fixing it would silently raise the grip envelope on every kart session — a behaviour change that must not ride along inside a correctness fix.
