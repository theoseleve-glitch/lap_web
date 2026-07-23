---
title: Adaptive Coaching & Drill Detection — Repair, Real Detection, Cross-Session Adaptivity
date: 2026-07-23
status: draft (awaiting owner review)
owner: product
scope: Backend (telemetry_tool) + minimal frontend payload wiring
anchors:
  - docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md (north-star platform; this is compatible with, not a replacement for)
  - ground-truth audit workflow wf_07b49c60-45d (2026-07-23, ran the pipeline on real SLK_FP2 kart data)
---

# Adaptive Coaching & Drill Detection

## 1. Context & motivation

LAP **already** contains a deep coaching subsystem — a 26-root-cause taxonomy
(`coaching/taxonomy/causes.json`), a 156-entry cause×severity×vehicle-class tip
matrix (`CORNER_TIPS`), a 60-text drill library (`DRILL_LIBRARY`), a causal-chain
under/oversteer root-cause **classifier** (`coaching/corner_diagnosis.py`, logic
verified: 43/43 unit tests, correct on a controlled hot-entry lap), and a
per-driver **prescriptive engine** (`track_surface/prescriptive/`). The design
depth is real and is the strongest asset.

The problem is **delivery, not features.** The 2026-07-23 ground-truth audit ran
the real pipeline on the SLK kart session and found that almost none of that
depth reaches a customer intact. On real data today a paying user gets:
- **Every corner → "Unknown cause" + one generic consistency drill** — a single
  vocabulary bug: `_resolve_cause` (`corner_composer.py:186`) emits cause id
  `low_apex_speed`, absent from BOTH the taxonomy (real id `mid_corner_speed_loss`)
  AND `DRILL_LIBRARY`.
- **Raw template placeholders shipped verbatim** — `{primary_strength}`,
  `{primary_weakness}`, and "brake pressure is **0.0%** below optimal"
  (`_pick_narrative` never `.format`s, `session_composer.py:306`;
  `_build_placeholders` hardcodes magnitudes to 0.0, `corner_composer.py:189-222`).
- On the CLI entrypoint the advanced stage **crashes on an import-prefix typo**
  (`s13_coaching_v3.py:32/173` imports `from telemetry_tool.coaching…`; siblings
  use bare `from coaching…`) and silently degrades to a near-empty coaching_v2
  copy **stored under the coaching_v3 key** — and the pytest suite's different
  sys.path masks it (green tests, broken prod).
- The deepest components are computed-then-dropped: `corner_diagnosis` runs only
  for operator-drawn PG corners and writes `summary['corner_labels']`, which
  **nothing reads**; the prescriptive engine has **zero callers**; cross-session
  adaptivity params (`driver_history`, `previous_goals`, `trend`) are threaded
  through three layers but **never read**.

This program makes the existing coaching **correct + delivered** (Phase 1),
promotes the verified classifier to genuine **root-cause → drill detection**
(Phase 2), and adds **cross-session adaptive progression** via a maintained
per-driver-per-track profile (Phase 3). It reuses the existing taxonomy/drill
assets and stays compatible with the 2026-04-19 unified-architecture north star.

## 2. Goals / non-goals

**Goals**
- The deep coaching becomes correct and reaches customers (no "Unknown cause",
  no raw placeholders, no silent v2-under-v3 mislabeling).
- Real **drill detection**: a driver's actual diagnosed mistake (root cause +
  measured severity) selects and shapes the drill, not a category→template lookup.
- **Adaptive progression**: drills adapt to how the driver has improved across
  sessions at a track (a maintained per-driver-per-track profile).
- An **honesty / data-sufficiency contract**: degenerate or low-confidence data
  (e.g. a kart with a corrupt yaw channel) yields softened language or "insufficient
  data", never a fabricated number or an over-confident oversteer call.

**Non-goals (explicitly out of scope for this program)**
- The full multi-source unified platform (sim/iRacing/AC ingestion, the three
  Contracts, per-game coaches, frontend unification) — that is the separate
  2026-04-19 program. This work stays *compatible* with it but does not build it.
- UI redesign. We fix the *payload* flowing to the existing coaching surfaces;
  panels/components are reused as-is.
- The scoring system, auth/billing, track-surface analysis, endurance — unchanged.

## 3. Target architecture — one canonical coaching spine

Collapse the 8 tangled paths into a single spine; everything off it is deleted or
folded in:

```
telemetry
  → corner detection (s10b)
  → corner_diagnosis  (root cause, EVERY session, confidence-gated)   ── Phase 2 promotes this
  → drill detection   (root cause + measured severity → drill from the 60-drill library)
  → adaptive layer    (per-driver-per-track profile shapes emphasis + drill progression)  ── Phase 3
  → ONE coaching payload  (single canonical shape on coaching/models.py)
  → existing endpoints: GET /sessions/<id>/coaching, /reveal, /corner-coaching-v4
  → webapp (existing components)
```

**Deleted / folded in** (audit-confirmed dead or duplicative):
- `debrief_engine` phantom stage (step `13b_coaching_guide`) — module never existed;
  remove the dead reference and the wasted step.
- `GET /sessions/<id>/practice-plan` — `practice_plan` is never persisted → permanent
  404; either persist it into the payload or remove the endpoint (decision in Phase 1).
- Orchestrator step `13g2 persist_coaching_v3` — no-op (called with an always-empty
  blob + `conn=None`); remove or make real.
- The duplicate `coaching_engine.py` `FocusArea/Drill/SessionCoaching` dataclasses —
  unify on `coaching/models.py`; keep a thin fallback only if a guaranteed-non-empty
  degenerate-data payload is still needed.

**Compatibility with the unified north star:** the drill-detection step is written
as a self-contained function of (diagnosed causes + magnitudes + capabilities), so
it can later be wrapped as a capability-tagged detector without a rewrite; the
taxonomy/drill library are reused verbatim (they are exactly what the unified W6
registry consumes); we do NOT move packages into `shared/` (that is unified-W5's job).

## 4. Phase 1 — Repair & Unify

**Purpose:** make the deep coaching that already exists correct and delivered.
This is mostly pinpointed bug-fixes on a live, customer-facing, currently-broken
feature.

**Components touched:** `pipeline/stages/s13_coaching_v3.py`,
`coaching/composers/corner_composer.py`, `coaching/composers/session_composer.py`,
`pipeline/orchestrator.py`, `coaching_engine.py`, `coaching/models.py`.

**Design:**
1. **Import correctness + a test that can catch it.** Fix the `from telemetry_tool.…`
   prefix so the stage runs on every entrypoint. Add an integration test that
   exercises the stage in **script-mode sys.path** (the way `main.py` sets it up),
   not only under pytest — the current suite's path masks the crash.
2. **Vocabulary integrity.** Fix `low_apex_speed → mid_corner_speed_loss`, and add a
   **startup / import-time assertion** that every cause id `_resolve_cause` can emit
   is present in BOTH the taxonomy and `DRILL_LIBRARY`. Vocabulary drift must fail
   loudly at boot, never silently collapse every corner to "Unknown cause".
3. **No placeholders leak.** `_pick_narrative` must `.format_map` the chosen variant;
   `_build_placeholders` must be fed the real analyzer magnitudes (the analyzers
   already compute them) instead of hardcoded 0.0. A payload-level guard test asserts
   no `{token}` and no literal "0.0%" reaches the customer payload.
4. **Honest fallback.** When the enhanced path genuinely can't run, return an explicit
   `None`/degraded marker — never a v2 payload stored under the v3 key. Consumers must
   be able to tell which engine produced the content.
5. **Type unification.** One `FocusArea/Drill/SessionCoaching` definition
   (`coaching/models.py`); retire the colliding `coaching_engine.py` duplicates.

**Data flow:** unchanged pipes (coaching payload → `analysis_json` → the 3 endpoints);
only the payload content is corrected.

**Done when:** running `main.py` on the real SLK session produces named causes +
real drills + filled narrative (or an explicit insufficient-data marker), the
script-mode integration test passes, and the no-placeholder guard passes.

## 5. Phase 2 — Real drill detection

**Purpose:** genuine root-cause → drill, from the verified classifier.

**Components:** `coaching/corner_diagnosis.py`, `pipeline/orchestrator.py`
(the `classify_all_corners` call site ~1264-1281), `coaching/composers/corner_composer.py`,
`coaching/analyzers/symptom_detector.py` (retired as the driver of tip selection),
the persistence blob builders (`pipeline_tasks.py:_build_analysis_blob`,
`sessions_v2.py`).

**Design:**
1. **Promote the classifier to canonical.** Decouple `classify_all_corners` from the
   `if user_corner_rows:` gate so it runs on **every auto-detected session**, not just
   operator-drawn PG corners. Persist its output into `analysis_json` (not a dead
   `summary['corner_labels']`).
2. **Route drill selection through the diagnosis.** `corner_composer` selects the
   drill from the diagnosed **root cause + severity magnitude** (via the existing
   `CORNER_TIPS`/`DRILL_LIBRARY` matrices), replacing the shallow `symptom_detector`
   heuristic that currently drives tip selection. "Detection" = the diagnosed cause
   (e.g. `exit_understeer ← early_throttle`) at a measured severity picks and shapes
   the drill and its difficulty.
3. **Confidence / honesty gate (critical for karts).** `corner_diagnosis`'s
   yaw-residual labels are low-confidence when there is no curvature profile or the
   yaw channel fails calibration (as on the real SLK data). The classifier must emit
   a per-label **confidence**, and the composer must down-rank / soften / withhold
   low-confidence oversteer calls rather than assert them. This reuses/extends the
   existing honesty-layer philosophy.

**Done when:** on a session with usable data, corners carry named root causes with
confidence, and the selected drill demonstrably changes with the diagnosed cause
(verified on a controlled synthetic input with a known mistake, plus the real SLK
run where oversteer is correctly withheld as low-confidence, not fabricated).

## 6. Phase 3 — Adaptive / cross-session progression

**Purpose:** drills that adapt to the driver's improvement over time.

**History model (owner decision, resolved 2026-07-23): a maintained
per-driver-per-track profile.** Not on-the-fly recomputation.

**Design:**
1. **Profile data model + migration.** A new table (working name
   `driver_corner_profile`) keyed by (workspace_id / user, track/canonical_id,
   corner, vehicle_class), storing rolling aggregates: recent per-corner mistake
   magnitudes, dominant root cause, a short trend (improving / flat / regressing),
   sessions_analyzed, streaks, and last-updated. Alembic migration on the chain-a
   lineage (its head is `084_merge_chain_ab`; this adds the next revision, RLS-scoped
   like other per-tenant tables — see §7 honesty/security). SQLite-schema parallel
   for the CLI path.
2. **Post-session upkeep.** After a session's coaching is computed, update the
   profile (idempotent, RLS/workspace-scoped, best-effort so it never breaks the
   pipeline). This is the missing "writer" for adaptivity.
3. **Read the adaptivity that's already plumbed.** Actually consume the
   `driver_history` / `previous_goals` / `trend` params the composers already accept
   but ignore; make `progressive_coach.py`'s improving/regressing branches reachable.
   Extend `corner_mastery` from session-scoped to cross-session (feed it the profile).
4. **Feed the prescriptive engine.** Wire a caller that assembles the profile +
   session evidence into the `track_surface/prescriptive` engine's inputs (it already
   computes real per-driver magnitudes/trends/confidence — it just has no callers) and
   folds its output into the coaching payload.
5. **Drill progression.** Drill difficulty/variant advances as a corner's mistake
   magnitude falls across sessions (e.g. "T3 exit-understeer down 40% over 3 sessions →
   progress to the harder variant"), and de-emphasizes corners the driver has mastered.

**Done when:** a second session at the same track produces coaching that references
prior sessions (trend/progression), the profile row updates correctly and idempotently,
and drill difficulty demonstrably advances as magnitudes fall — all verified on a
multi-session fixture.

## 7. Cross-cutting concerns

- **Honesty / data-sufficiency contract.** A single guard: degenerate input (e.g.
  SLK's identical entry=apex=exit speed targets, empty symptom evidence, null
  traction/trail-brake, or a failed-calibration yaw channel) must produce an explicit
  "insufficient data for this corner/label" state — never a fabricated magnitude or an
  over-confident call. This is a first-class output field, surfaced to the customer as
  honest language, not hidden.
- **Delivery.** Fix the payload to the *existing* 3 endpoints and their webapp
  components (`useCornerData.ts`, `reveal/page.tsx`, `CornerCoachingV4.tsx`); confirm
  the payload shape they expect and keep it (or extend additively). No UI redesign.
- **Entitlement gating.** Coaching is currently JWT-only (no plan gating). Whether
  coaching depth becomes a paid feature is a product decision flagged here, not
  decided in this spec; the payload should carry the fields regardless, gated at the
  read layer if the owner later wants tiering.
- **Testing strategy.** (a) real-data regression: run on SLK + at least one good-yaw
  session; (b) the script-mode integration test (catches the sys.path class of bug);
  (c) a payload guard: no `{placeholder}` / no "Unknown cause" / no literal "0.0%"
  ever reaches the payload; (d) controlled synthetic-mistake tests for the classifier
  → drill mapping; (e) profile-upkeep idempotency + cross-session progression tests.

## 8. Global Constraints

- **Branch-only, deploy-gated.** Work on `feat/adaptive-coaching` (off
  `feat/chain-a-consolidated`, the intended-prod lineage). No deploy without explicit
  confirmation. Never `git add -A` in lap_web (AV quarantines deletions — stage files
  by explicit path).
- **Reuse, don't re-author, the coaching assets.** The 26-cause taxonomy, 156-tip
  matrix, and 60-drill library are the strongest asset — build on them; do not rewrite
  the vocabulary.
- **No fabrication.** Every customer-facing number must trace to real telemetry or be
  explicitly marked insufficient/low-confidence. (Same principle as the launch-readiness
  audit's data-correctness findings.)
- **Kart-first, car-safe.** Real validation data is the SLK kart; keep the existing
  vehicle-class thresholds (kart vs car) intact and correct.
- **Stack.** Backend Python (Flask + alembic), system Python 3.14; PostgreSQL for the
  profile with RLS/workspace scoping like sibling per-tenant tables; SQLite parallel
  for the CLI/desktop path. Migration adds the next revision after `084_merge_chain_ab`.
- **Unified-north-star compatibility.** Do not move packages to `shared/` or build the
  contract/registry here; keep the drill-detection step a pure function so it can later
  become a capability-tagged detector.

## 9. Phasing & acceptance

| Phase | Deliverable | Acceptance |
|---|---|---|
| 1 — Repair | Correct + delivered coaching | SLK run yields named causes + real drills + filled narrative or explicit insufficient-data; script-mode integration test + no-placeholder guard pass |
| 2 — Detection | Root-cause → drill from the promoted classifier | Drill changes with diagnosed cause (synthetic); real SLK withholds low-confidence oversteer, not fabricates; classifier output persisted + consumed |
| 3 — Adaptive | Per-driver-per-track profile + progression | 2nd session references prior; profile updates idempotently; drill difficulty advances as magnitudes fall (multi-session fixture) |

Phases are sequential (1 is prerequisite for 2; 2 for 3) and each gets its own
implementation plan (`docs/superpowers/plans/…`) referencing this spec.

## 10. Open questions carried into planning

- Exact `driver_corner_profile` column set + the canonical track key (reuse
  `canonical_id`); RLS policy mirrors which existing table.
- Whether `practice_plan` is persisted-and-surfaced or removed (Phase 1 decision).
- Whether coaching depth becomes plan-tier gated (product decision; payload-ready either way).
- Confidence thresholds for the yaw-residual honesty gate (kart vs car).
