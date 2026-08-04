# Driving Pattern Recognition — design

**Date:** 2026-08-04
**Branch:** `feat/driving-pattern-recognition` (worktree `C:/Users/Admin/lap_web-wt-patterns`), forked from `feat/adaptive-coaching` @ `476a889`
**Status:** design approved, plan pending
**Hard dependency:** the per-lap corner coordinate fix, split out as a standalone shippable change (see §10)

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
- Not the per-lap coordinate fix — that ships separately (§10).

## 4. Evidence base

Every number below was measured during design, on real customer-shaped data
(`telemetry_tool/data/raw/OK_R4.csv`, RaceChrono Pro kart export, 211,002 rows, 10 laps).
Probe: `scratchpad/probe_corner_slice.py`, read-only.

| Question | Measurement | Consequence for the design |
|---|---|---|
| Do per-lap corner slices return data? | **9 of 10 laps return ZERO corner samples.** Rebasing each lap to `d − d_min` returns ~273 samples on all 10. | Blocking prerequisite. §10. |
| Distance-grid resolution inside a corner | 1.204 m/sample; at apex speed (10.8–13.9 m/s) that is 86–111 ms/sample → **~3 samples per 0.3 s**, but **25–79 samples per corner**. | Phase segmentation, plateau, trough and envelope fill are all viable on the existing grid. Only sub-second ramp/oscillation primitives are grid-limited. The time grid is a late, narrow phase — not a foundation. |
| Is the lateral-g channel trustworthy? | Median `\|a_lat\| / (v²κ)` = **0.961**, per-lap range 0.951–0.975, n≈650/lap, measured only where `v²κ > 2 m/s²` (i.e. in corners). | **Tier-1 physics anchor is viable on real kart data.** |

### 4.1 A correction to the prior validation report

`docs/validation/attitude_correction_report.md` reports the lateral channel reading 15% low overall and **47% low on straights** (`cal_bias` 0.531), which had made a physics anchor look unusable.

That figure is a division artifact. On a straight `v²κ ≈ 0`, so the ratio is noise divided by noise. Restricted to samples that are actually in corners — the only place a grip anchor is used — agreement is **96%, stable to ±1.2% across all ten laps**. The channel is fit for this purpose.

### 4.2 Facts that constrain the architecture

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

    # location, in the canonical per-lap coordinate (§10)
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
| `physics` | `FrictionEnvelope` bin at the corner's speed | `median(sensor_quality.curvature_agreement)` within `[0.80, 1.25]` **and** the bin is not fabricated |
| `driver_best` | driver's own best execution of that corner, from `corner_metrics` | that corner has ≥1 prior clean execution |
| `refused` | none | always available; carries a machine-readable reason |

Ordered fail-safe downgrade, vocabulary constants and a single consumer guard, copied literally from `track_surface/honesty.py:13-75`.

**Fabricated-bin detection**, available today with no new code: a `FrictionBin` is synthetic when `confidence == 0.0`, `sample_count < 8`, or `accel_max_g == global * 0.6` (`friction_envelope.py:229`). Tier 1 must not quote a floored bin as a measurement.

Measured gate outcome on real kart data: **0.961 → PASS**.

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
| **0** | *Separate deliverable* — per-lap coordinate fix (§10) | Everything below aggregates per-lap corner data, which is currently empty on laps 2..N |
| **1** | Tiered anchor + trust gate, on the existing distance grid | Every downstream number is quoted against this, and it is the piece most likely to fail on real data — so it goes first |
| **2** | Per-lap phase segmentation, `DrivingEvent`, migration 085, detector registry, the ✓ detector set | The spine. None of it needs the time grid. |
| **3** | Mistake tape + exploitation map in the webapp | One visible surface proves the events mean something; draw primitives already exist |
| **4** | Time grid + `ramp` / `oscillation` primitives | Only change touching the Celery two-phase contract and the pipeline hash. Payoff is 12–16×, not unbounded. Native-rate **corner windows** persisted from phase A, not whole laps. |
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

## 9. Open questions

- Whether `envelope_use_pct` should be reported against the ellipse boundary along the *current* combined-g direction, or as area fill over the phase. (Leaning: both — instantaneous for the tape, area for the map.)
- Whether tier-2's "driver's own best" is scoped per track only, or per track *and* condition. Wet vs dry changes peak lateral from 1.42 g to 0.85 g on the same driver, so a shared reference would systematically mislabel wet sessions as under-driving.

## 10. Split-out prerequisite: per-lap corner coordinate fix

**Shipped separately, independently deployable.** Own branch, own plan.

Corners are detected on the first resampled lap only (`s07_resample.py:82-83`) and carry that lap's **absolute** distance span. RaceChrono's `Distance (m)` is cumulative session distance, and resampling preserves each lap's absolute range (`resampling.py:201-204`). The ubiquitous slicing idiom `(dist >= s_start) & (dist <= s_end)` — `corner_analysis.py:339`, `s10b_corners.py:427`, `s13_coaching_v3.py:265` — therefore returns an empty mask on every lap but the detection lap.

It fails silently: `_enrich_corner_telemetry` early-returns on `len(corner_idx) <= 2`, and the per-lap loop swallows exceptions with a bare `except ... continue` (`s10b_corners.py:380-382`).

Measured: **9 of 10 laps return zero corner samples; all 10 return ~273 after rebasing.**

A complication the fix must handle: `distance_integrity` rebuilds distance from zero via `cumsum` **only for laps that fail its monotonicity gate**, so within one session some laps can be 0-based and others cumulative. A single session-wide offset is therefore not valid; the fix must normalise per lap.

Fix option selection, exact change list, backward-compatibility and reprocessing are determined by a separate blast-radius analysis and written up in that deliverable's own plan.

**Also folded into that deliverable** (both are silent-failure fixes of the same character, both prerequisites for trustworthy aggregates):

- Pass `best_lap_number` into `run_handling_analysis_v2` (`orchestrator.py:1233-1236` vs `s10b_corners.py:759-760`).
- Count and report the swallowed per-lap corner exceptions rather than discarding them.
- Persist `DataQualityReport.to_dict()` (one-line `isinstance` fix).

**Explicitly NOT folded in:** the dropped return of `apply_kart_traction_floor` (`s09_physics.py:269`). Fixing it would silently raise the grip envelope on every kart session — a behaviour change that must not ride along inside a correctness fix.
