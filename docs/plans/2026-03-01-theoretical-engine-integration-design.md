# Theoretical Engine Integration & Weekly Training — Design

## Goal

Wire the existing theoretical lap computation engine into the production web app so that every uploaded session automatically gets a theoretical best lap computed. Add weekly training to continuously improve the model from accumulated data before retention deletes raw telemetry.

## Problem

The kart_envelope QSS/CasADi solver, the theoretical adapter, and the Celery pipeline all exist in the codebase — but the upload route never triggers the pipeline chain. Sessions land in the DB without theoretical data, making the app a data viewer instead of an analysis tool.

## Architecture

### Upload Flow

```
CSV Upload → POST /api/v1/ingest/upload
  → Streaming ingest (chunked Parquet cache)
  → Session row created in sessions table
  → Celery chain dispatched:
      pipeline_ingest.s(job_id)
      | pipeline_analyze.s(job_id)
      | pipeline_finalize.s(job_id)
  → Stage 10 in pipeline_finalize:
      Priority 0: kart_envelope QSS (via theoretical_adapter.py)
      Priority 1: Hybrid physics simulation
      Priority 2: Adaptive percentile envelope
  → Results stored in theoretical_data table
  → Frontend renders on session detail page
```

### Weekly Training (Sundays 00:00 UTC)

Three-tier training wave, each tier independent:

**Tier 1 — Track-specific CapabilityEnvelopes (~30s per group)**
- Group sessions by (track_id, vehicle_type)
- Skip groups with <3 sessions
- Train envelope: speed bins, grip quantiles, PAVA smoothing, p-norm fit
- Save to /data/models/envelopes/{track_id}_{vehicle}.json

**Tier 2 — Global model bundle (~5-15 min)**
- build_training_dataset() from all sessions
- Teacher model (physics-based) → student distillation
- Package bundle_v2 to /data/models/bundle_v2/
- Counterfactual synthesis for data augmentation

**Tier 3 — Reprocess all sessions**
- For each non-expired session: re-run pipeline_finalize with new models
- Throttled: 2 concurrent, 30s pause between batches
- Update theoretical_data rows with improved predictions

### Scheduling

| Task | Schedule | Queue | Time Limit |
|------|----------|-------|------------|
| weekly_retrain_and_reprocess | Sunday 00:00 UTC | pipeline | 2 hours soft, 2.5 hours hard |
| enforce_telemetry_retention | Daily 2:15 AM UTC | default | 30 min |

Training completes before retention runs. Models persist as files (not in retention-scoped tables).

## Error Handling

- **Insufficient data**: _safe_step() catches, logs, stores None. Frontend shows "not yet computed" fallback.
- **Cold start (no models)**: Adapter cascades to percentile envelope. Still produces a theoretical lap.
- **Concurrent uploads during training**: Read-only data snapshots. No locking conflicts.
- **Training timeout**: Saves partial results, logs timeout. Retention runs independently.
- **Per-session reprocess failure**: Logged, doesn't abort batch.
- **Retention vs models**: Trained model files (/data/models/) are NOT subject to retention. Only raw telemetry rows are deleted.

## Implementation Scope

| Piece | File | Lines |
|-------|------|-------|
| Upload → pipeline trigger | web/routes/ingest.py | ~20 |
| Weekly training Celery task | tasks/training_tasks.py (new) | ~200 |
| Beat schedule entry | tasks/celery_app.py | ~5 |

Existing code (no changes): theoretical_adapter.py, pipeline.py stage 10, kart_envelope solver, offline training pipeline, frontend rendering.

## Verification Needed

- pipeline chain runs end-to-end in Docker (stages 1-14)
- theoretical_data table exists in production PG (confirmed)
- /data/models/ directory exists on Docker volume
- kart_envelope importable inside Docker container
- theoretical_adapter.py column mapping works with production CSV formats

## Success Criteria

1. Upload a CSV → session detail page shows theoretical lap time, speed profile, coaching
2. Weekly training improves envelope → subsequent uploads use trained model
3. Re-processed sessions show updated theoretical data
4. Frontend 409 fallback works for sessions that fail computation
5. No impact on upload latency (pipeline runs async via Celery)
