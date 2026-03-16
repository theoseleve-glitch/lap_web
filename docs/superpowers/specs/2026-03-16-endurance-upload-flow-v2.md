# Endurance Upload Flow V2 — Design Spec

**Date:** 2026-03-16
**Status:** Approved
**Replaces:** Original endurance report design (stint detection was post-upload)

---

## Problem

The current flow tries to process a 650MB endurance CSV through the full pipeline at once, causing OOM kills. The upload form doesn't adapt for endurance. Stint detection happens post-upload which is too late.

## Solution

A dedicated 2-step endurance upload flow that detects stints first (cheap), lets the user configure them, then processes each stint individually through the pipeline (small chunks, no OOM).

---

## Step 1: Endurance Upload Form

When `session_type = endurance` is selected, the form transforms:

**Hidden:** Single "Driver Name" field (top of form)

**Shown:**
- **Drivers section:** "Add Driver" with name input, tag chips (like V1)
- **Pit stop threshold:** number input, default 120s, label: "Pit stop duration (seconds)"
- **Kart:** shared across all drivers (same as now)
- **Date:** shared (same as now)
- **Track:** shared (same as now)
- **Upload button**

Upload sends: CSV file + drivers list + pit threshold + shared metadata.

---

## Step 2: Stint Detection & Configuration

After upload, the backend does a **quick first pass** — reads only the lap times column from the CSV (fast, low memory). No full pipeline.

### Detection Logic

```
median_valid = median(all lap times where lap_time < pit_threshold)
pit_candidates = laps where lap_time > median_valid + pit_threshold

Group consecutive non-pit laps into stints.
```

### User Configuration Screen

Shows a table of ALL laps with:
- Lap number
- Lap time
- Auto-detected status: "Valid" / "Pit Stop" / "Anomaly"
- User can override each lap:
  - **Valid + Stint N** — assign to a specific stint (manual override)
  - **Pit lap** — marks as pit stop (stint boundary)
  - **Ignore** — remove from analysis entirely

Below the table:
- **Stint summary:** Stint 1 (Laps 1–8), Stint 2 (Laps 10–17), etc.
- Per stint: **Driver dropdown** + **Condition dropdown** (dry/damp/wet/mixed)
- **"Process Stints" button**

If user manually entered pit laps with stint numbers → use as-is, skip auto-detection.

---

## Step 3: Per-Stint Pipeline Processing

After user confirms stint configuration:

1. **For each stint** (sequentially or 2 at a time):
   - Extract only that stint's rows from the CSV
   - Run the full pipeline on the subset (~50-100 laps, ~30MB instead of 650MB)
   - Store results (laps, GPS, scores, etc.) tagged with stint_number
   - **Frontend:** stint appears in a roll-menu as soon as processed — user can click into Tier 1 report immediately

2. **After all stints processed:**
   - Compute per-driver aggregation (Tier 2 reports)
   - Reveal driver reports in the roll-menu

3. **After driver reports:**
   - Compute team report (Tier 3)
   - Reveal full race report

### Frontend Progress UX

```
Processing stints...

[✓] Stint 1 — Théo — 8 laps — 52.1s best          [View Report →]
[✓] Stint 2 — William — 7 laps — 53.2s best        [View Report →]
[⟳] Stint 3 — Théo — processing...
[ ] Stint 4 — William — queued
[ ] Stint 5 — Théo — queued

── After all stints ──
[⟳] Driver reports — processing...
[ ] Race report — queued
```

Each completed stint is clickable → opens Tier 1 (stint report) inline or in the session detail Endurance tab.

---

## Backend Architecture

### Quick Lap Detection Endpoint

**`POST /api/v1/sessions/endurance-detect`**

Accepts the uploaded CSV + pit threshold. Does a fast read of just the lap times column (no full pipeline). Returns:

```json
{
  "job_id": "abc123",
  "laps": [
    { "lap_number": 1, "lap_time_s": 52.1, "status": "valid" },
    { "lap_number": 8, "lap_time_s": 185.2, "status": "pit" },
    ...
  ],
  "auto_stints": [
    { "stint_number": 1, "start_lap": 1, "end_lap": 7, "lap_count": 7 },
    { "stint_number": 2, "start_lap": 9, "end_lap": 15, "lap_count": 7 },
    ...
  ],
  "median_lap_time_s": 52.8,
  "pit_threshold_s": 120
}
```

This is a lightweight endpoint — only reads lap boundaries, no GPS processing.

### Per-Stint Pipeline Endpoint

**`POST /api/v1/sessions/endurance-process`**

Accepts: job_id, stint configuration (with driver assignments + conditions).

Dispatches Celery tasks: one per stint, chained with driver aggregation + team report.

```json
{
  "job_id": "abc123",
  "stints": [
    { "stint_number": 1, "driver_name": "Théo", "condition": "dry", "start_lap": 1, "end_lap": 7 },
    { "stint_number": 2, "driver_name": "William", "condition": "dry", "start_lap": 9, "end_lap": 15 }
  ]
}
```

Each stint is processed as a Celery task:
1. Read only that stint's rows from the cached CSV
2. Run pipeline stages 1–13 on the subset
3. Persist results tagged with session_id + stint_number
4. Update job status → frontend shows stint as complete

### SSE Progress Stream

**`GET /api/v1/jobs/{job_id}/stream`** (existing)

Events include stint-level progress:
```
data: {"status": "processing_stint", "stint_number": 1, "stage": "Computing Metrics", "pct": 45}
data: {"status": "stint_complete", "stint_number": 1, "best_lap_s": 52.1}
data: {"status": "processing_stint", "stint_number": 2, "stage": "GPS Filtering", "pct": 12}
data: {"status": "stint_complete", "stint_number": 2, "best_lap_s": 53.2}
data: {"status": "processing_drivers"}
data: {"status": "driver_complete", "driver_name": "Théo"}
data: {"status": "processing_team"}
data: {"status": "completed"}
```

---

## Memory Budget

| Scenario | Old (full CSV) | New (per-stint) |
|----------|---------------|----------------|
| 650MB CSV, 120 laps | ~2.5GB peak → OOM | ~150MB peak per stint |
| 10 stints × 12 laps | N/A | 10 × 150MB (sequential) = 150MB peak |

---

## Files to Create/Modify

### Backend
- `telemetry_tool/web/routes/endurance_upload.py` — New blueprint: detect + process endpoints
- `telemetry_tool/tasks/endurance_tasks.py` — Celery tasks: per-stint pipeline + aggregation
- `telemetry_tool/endurance_ingest.py` — Quick lap detection from CSV (no full pipeline)

### Frontend
- `lap-website/src/app/app/sessions/upload/page.tsx` — Endurance form mode + stint config step
- `lap-website/src/components/app/endurance/StintConfigFlow.tsx` — Lap table + stint assignment
- `lap-website/src/components/app/endurance/StintProcessingProgress.tsx` — Roll-menu progress

---

## Out of Scope

- Parallel stint processing (V2 — sequential is fine for V1)
- Live timing during race
- Automatic driver detection from telemetry signatures
