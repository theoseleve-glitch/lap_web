# Desktop-to-Cloud Session Sync — v1 Design

**Date**: 2026-04-16
**Status**: Design — ready to implement

---

## A. Recommended v1 Architecture

### One sentence

**Build the bundle eagerly at session finalize, enqueue it to a local SQLite
sync queue, drain the queue in a background thread with exponential backoff,
POST to the existing `/api/v1/bundles` endpoint.**

### Diagram

```
Session End (desktop)
  │
  ▼
Pipeline finalize (existing)
  │ returns summary dict
  ▼
BundleBuilder.build(capture_dir) ──────────► session.zip (on disk, immutable)
  │                                           ManifestV2 compliant
  ▼
SyncQueue.enqueue(bundle_path, checksum)
  │
  │  ┌──────────────── Policy check ────────────────┐
  │  │ World Class (auto_upload=true):               │
  │  │   status = "pending"  → picked up immediately │
  │  │ Racer (auto_upload=false):                    │
  │  │   status = "skipped"  → waits for user click  │
  │  └──────────────────────────────────────────────┘
  │
  ▼ (background thread)
SyncWorker.drain()
  │ for each "pending" row:
  │   POST /api/v1/bundles (multipart, with checksum header)
  │   ├── 201/202  → mark "uploaded"
  │   ├── 409 dup  → mark "uploaded" (already there, not an error)
  │   ├── 4xx      → mark "failed" + error_message
  │   └── network  → increment attempt, backoff, retry later
  │
  ▼
Existing webapp bundle intake (no changes)
```

### Key decision: eager bundle generation

The ManifestV2 zip is built **immediately after pipeline finalize**, not lazily at
upload time.

Why:
- The immutable artifact exists before any network I/O
- No "build failed during upload" state
- Checksums computed once
- Bundle is the same whether uploaded 10 seconds or 10 days later
- Local session folder stays as-is for desktop debug/history — the bundle is an
  additional output, not a replacement

### What lives where

| Component | Location | Why there |
|-----------|----------|-----------|
| BundleBuilder | `telemetry_tool/desktop_sync/bundle_builder.py` | importable from main.py + build_bundle.py CLI |
| SyncQueue | `telemetry_tool/desktop_sync/queue.py` | SQLite table in existing `telemetry.db` |
| SyncWorker | `telemetry_tool/desktop_sync/worker.py` | background thread, drains queue |
| UserConfig | `telemetry_tool/desktop_sync/config.py` | reads/writes `~/.lap/config.json` |
| DB migration | `telemetry_tool/db/schema.py` | new `sync_queue` table in Phase 16 |

---

## B. Rejected Alternatives (and why)

| Alternative | Why rejected |
|---|---|
| **Lazy bundle generation at upload time** | Introduces transient state ("folder exists, bundle doesn't"). Requires the capture_meta.json + IBT to still be on disk at upload time — fragile if user moves/deletes files. Eager = simpler invariant. |
| **Separate process / service** | PyInstaller exe can't reliably spawn daemons. A background thread in the same process is simpler and exits when the app exits. |
| **Cloud-first with local fallback** | Violates "finalize locally first." If cloud is down, user can't use their session at all. Local-first is non-negotiable. |
| **Different upload format per tier** | More complexity, more test surface, more bugs. One format, one path, policy is just a boolean. |
| **Celery/Redis on desktop** | Absurd for a desktop exe. SQLite + threading.Thread is the right tool. |
| **Sync as a separate desktop app** | Doubles the install surface. Users expect one app. |

---

## C. Modules / Files

### New files (4 + 1 test file)

```
telemetry_tool/desktop_sync/
├── __init__.py
├── config.py              # UserConfig — reads ~/.lap/config.json
├── bundle_builder.py      # build_session_bundle(capture_dir) → Path
├── queue.py               # SyncQueue — SQLite CRUD for sync_queue table
└── worker.py              # SyncWorker — background thread, HTTP upload, retry

telemetry_tool/tests/test_desktop_sync/
├── __init__.py
├── conftest.py
├── test_config.py
├── test_queue.py
├── test_worker.py
└── test_bundle_builder.py
```

### Modified files

| File | Change |
|------|--------|
| `telemetry_tool/db/schema.py` | Add `sync_queue` table (Phase 16) |
| `telemetry_tool/main.py` | After `run()` returns: call `build_session_bundle()` + `SyncQueue.enqueue()` + start `SyncWorker` |
| `telemetry_tool/telemetry_tool.spec` | Add `desktop_sync` + `requests` to hidden imports |
| `scripts/batch_replay_capture.py` | After capture: call `build_session_bundle()` + `SyncQueue.enqueue()` |

---

## D. Bundle Generation Point

```
main.py::run(csv_path, ...) → summary dict
  │
  │ if summary["pipeline"]["status"] != "failed":
  │   bundle_path = build_session_bundle(
  │     output_dir=summary["output_dir"],
  │     track_name=summary.get("track_name"),
  │     car_name=summary.get("car_name"),
  │     session_type=summary.get("session_type", "practice"),
  │   )
  │   queue.enqueue(bundle_path, auto_upload=config.auto_upload)
  │
  ▼
_wait_for_keypress()  ← worker thread is draining in background
```

The bundle builder lives in `desktop_sync/bundle_builder.py` and is a thin
wrapper around the same logic as `scripts/build_bundle.py` (one function,
importable, no CLI overhead).

For `batch_replay_capture.py` the hook is similar — after IBT copy + capture_meta
write, call `build_session_bundle()` + `enqueue()`.

---

## E. Sync State Machine

### States

```
┌──────────┐     enqueue(auto=true)    ┌─────────┐
│  (none)  │ ─────────────────────────►│ pending │
└──────────┘                           └────┬────┘
     │                                      │  worker picks up
     │  enqueue(auto=false)                 ▼
     │                             ┌────────────────┐
     └────────────────────────────►│   skipped      │
                                   └───────┬────────┘
                                           │ user clicks "Upload"
                                           ▼
                                   ┌────────────────┐
                                   │   pending      │
                                   └───────┬────────┘
                                           │
                                           ▼
                                   ┌────────────────┐
                                   │  uploading     │
                                   └──┬──────────┬──┘
                                      │          │
                             success/dup     failure
                                      │          │
                                      ▼          ▼
                              ┌───────────┐  ┌─────────┐
                              │ uploaded   │  │ failed  │
                              └───────────┘  └────┬────┘
                                                  │ retry (attempt < max)
                                                  ▼
                                            ┌──────────┐
                                            │ pending  │ (with backoff)
                                            └──────────┘
```

### Table schema (`sync_queue`)

```sql
CREATE TABLE IF NOT EXISTS sync_queue (
    queue_id        TEXT PRIMARY KEY,       -- uuid4 hex
    bundle_path     TEXT NOT NULL,          -- absolute path to .zip on disk
    checksum_sha256 TEXT NOT NULL,          -- outer archive checksum
    status          TEXT NOT NULL DEFAULT 'pending',
                    -- pending | skipped | uploading | uploaded | failed
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    last_attempt_at TEXT,
    next_retry_at   TEXT,                   -- NULL = immediately eligible
    error_message   TEXT,
    cloud_bundle_id TEXT,                   -- populated on 201/202/409 response
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    uploaded_at     TEXT
);
```

### Retry rules

| Attempt | Backoff | Max age before giving up |
|---------|---------|--------------------------|
| 1 | immediate | — |
| 2 | 5 seconds | — |
| 3 | 30 seconds | — |
| 4 | 5 minutes | — |
| 5 | 30 minutes | — |
| >5 | stop, mark `failed` | user must click "Retry" manually |

Backoff formula: `min(30 * 60, 5 ** attempt)` seconds.

### Duplicate handling

Backend returns `409 BUNDLE_DUPLICATE` with `existing_bundle_id` in details.
Worker marks `status=uploaded`, `cloud_bundle_id=<existing_id>`. **Not an error.**

---

## F. Desktop UX States

### World Class (auto_upload=true)

| Session state | What user sees | Where |
|---|---|---|
| Pipeline running | "Analyzing..." | Progress in main window |
| Pipeline done, bundle built | "Analysis complete. Syncing to cloud..." | Console + status bar |
| Upload in progress | "Uploading session..." | Console |
| Upload succeeded | "Session synced to cloud." | Console + green indicator |
| Upload failed (retrying) | "Sync will retry automatically." | Console + yellow indicator |
| Upload failed (exhausted) | "Sync failed. Check your connection." | Console + red indicator |
| Offline (no network) | "Session saved locally. Will sync when online." | Console |

### Racer (auto_upload=false)

| Session state | What user sees | Where |
|---|---|---|
| Pipeline done, bundle built | "Analysis complete. Bundle saved locally." | Console |
| User wants to upload | (Future: button in desktop UI. v1: CLI command.) | CLI |
| After manual upload | "Session synced to cloud." | Console |

### v1 UX scope

The desktop app is currently **console-only** (no GUI beyond the Tkinter file picker).
v1 sync UX is **console log lines** — no new GUI elements. The status information
is persisted in `sync_queue` so a future desktop GUI can read it.

```
# World Class auto-upload:
[SYNC] Bundle built: daytona_road_course_mclaren_570s_gt4.zip (18.2 MB)
[SYNC] Uploading to cloud... done (bundle_id: 4b9d1f8c)
[SYNC] Session synced to cloud.

# Racer local-only:
[SYNC] Bundle built: daytona_road_course_mclaren_570s_gt4.zip (18.2 MB)
[SYNC] Auto-upload disabled. Use 'python -m desktop_sync upload' to sync.

# Failure:
[SYNC] Upload failed: connection refused. Will retry in 30s.
[SYNC] Upload failed after 5 attempts. Run 'python -m desktop_sync retry' to try again.
```

### Manual upload CLI (Racer tier)

```bash
# Upload all pending/skipped bundles
python -m telemetry_tool.desktop_sync upload

# Upload one specific session
python -m telemetry_tool.desktop_sync upload --queue-id <id>

# Show sync status
python -m telemetry_tool.desktop_sync status

# Retry failed uploads
python -m telemetry_tool.desktop_sync retry
```

---

## G. E2E Validation Plan

### Test 1: Happy path (World Class auto-upload)

```
1. Set auto_upload=true in config
2. Process a test session (pipeline finalize)
3. Verify: bundle .zip exists on disk
4. Verify: sync_queue row inserted with status=pending
5. Worker runs → POST /api/v1/bundles → 201
6. Verify: sync_queue status=uploaded, cloud_bundle_id populated
7. Verify: webapp shows the bundle in GET /bundles
```

### Test 2: Racer manual upload

```
1. Set auto_upload=false
2. Process a test session
3. Verify: sync_queue row inserted with status=skipped
4. Run 'upload' CLI command
5. Verify: status changes pending → uploading → uploaded
```

### Test 3: Duplicate upload

```
1. Upload a bundle (status=uploaded)
2. Re-run 'upload' command on the same session
3. Verify: backend returns 409
4. Verify: sync_queue marks uploaded (not failed)
```

### Test 4: Network failure + retry

```
1. Set auto_upload=true
2. Process a session with backend unreachable
3. Verify: attempt_count increments, status stays pending
4. Verify: next_retry_at is set to backoff time
5. Make backend reachable
6. Verify: next drain cycle succeeds
```

### Test 5: Offline → online transition

```
1. Process a session while offline
2. Verify: bundle built, sync_queue row created, upload fails gracefully
3. Come online
4. Verify: worker retries and succeeds
```

### Test 6: Pipeline failure → no bundle

```
1. Process a session that fails at pipeline stage
2. Verify: no bundle built, no sync_queue row
3. Verify: user sees "Analysis failed" (existing behavior unchanged)
```

---

## H. Go / No-Go Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | `build_session_bundle()` produces a valid ManifestV2 zip from a real pipeline output | Unit test + integration |
| 2 | World Class: auto-upload works end-to-end (session → bundle → queue → upload → webapp shows it) | Staging with real iRacing IBT |
| 3 | Racer: manual upload CLI works | Staging |
| 4 | Duplicate upload returns 409 and is treated as success | Automated test |
| 5 | Network failure → graceful retry with backoff, no crash | Automated test |
| 6 | Offline → no user-visible error, bundle persists locally | Automated test |
| 7 | Pipeline failure → no bundle attempted, no sync error | Automated test |
| 8 | sync_queue table persists across app restarts | Manual verification |
| 9 | `config.json` toggle works: `auto_upload=true/false` | Unit test |
| 10 | PyInstaller build succeeds with new modules | Build test |
| 11 | No changes to research core (`track_surface/`) | `git diff` |
| 12 | No changes to webapp bundle intake contract | `git diff` on `bundle_intake/` |

**Not required for v1 ship:**
- Desktop GUI integration (console-only is fine)
- Upload progress bar (background thread, no UI)
- Cross-device session dedup (backend handles via checksum)
- Bandwidth throttling
- Partial/resumable uploads
