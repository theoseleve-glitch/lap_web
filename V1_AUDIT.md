# Telemetry Analysis Platform — Comprehensive Audit & Launch Plan
### Version 1.0 | February 2026

---

# PROMPT 1 — One-Page System Map

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER ENTRY POINTS                            │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────────┐ │
│  │ Desktop .exe │  │ Flask Dashboard  │  │ CLI (main.py --serve)  │ │
│  │ (PyInstaller)│  │  localhost:5000   │  │ or main.py <csv>      │ │
│  └──────┬──────┘  └────────┬─────────┘  └───────────┬────────────┘ │
└─────────┼──────────────────┼────────────────────────┼──────────────┘
          │                  │                        │
          ▼                  ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FLASK APPLICATION LAYER                         │
│  web/app.py — create_app() factory, 17 blueprints, 120+ routes     │
│                                                                     │
│  Route Blueprints:                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │dashboard │ │sessions  │ │tracks    │ │analysis  │ │api_data  │ │
│  │  (home)  │ │(CRUD+    │ │(CRUD+    │ │(run pipe)│ │(90+ JSON │ │
│  │          │ │ upload)  │ │ detect)  │ │          │ │endpoints)│ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │weekends  │ │drivers   │ │compare   │ │leader-   │ │visualize │ │
│  │(groups)  │ │(profiles)│ │(multi-   │ │board     │ │(charts)  │ │
│  │          │ │          │ │session)  │ │          │ │          │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │data-     │ │analytics │ │predict-  │ │annota-   │ │dashboards│ │
│  │health    │ │(weather, │ │ions      │ │tions     │ │(custom)  │ │
│  │          │ │trends)   │ │(what-if) │ │          │ │          │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐                                         │
│  │dev_plans │ │exports   │                                         │
│  │(coaching)│ │(PDF/md)  │                                         │
│  └──────────┘ └──────────┘                                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────────┐
│  FRONTEND LAYER  │ │  ANALYSIS ENGINE │ │    PERSISTENCE LAYER     │
│                  │ │                  │ │                          │
│ 34 HTML templates│ │ 14-stage pipeline│ │  SQLite (telemetry.db)   │
│ 36 JS files      │ │ pipeline.py      │ │  Schema v11, 11 phases   │
│  (Canvas 2D,     │ │  (2,441 lines)   │ │  ~30 tables              │
│   Chart.js,      │ │                  │ │                          │
│   vanilla JS)    │ │ 50+ pure-function│ │  db/schema.py  (576 L)   │
│                  │ │ analysis modules │ │  db/migrate.py (138 L)   │
│ main.css (dark   │ │                  │ │  db/queries.py (886 L)   │
│ theme, 1 file)   │ │ Total: ~73k LoC  │ │                          │
│                  │ │                  │ │  File storage:           │
│ No framework     │ │ Key modules:     │ │  data/raw/*.csv          │
│ (pure HTML/JS/   │ │  scoring    2692L│ │  results/*.html          │
│  CSS)            │ │  theoretical1359L│ │  results/*.pdf           │
│                  │ │  corner_det 1199L│ │                          │
│ SPA-like via     │ │  corner_ana 1436L│ │  JSON blobs in TEXT cols │
│ fetch() + DOM    │ │  debrief    1080L│ │  (gps traces, scores,    │
│ manipulation     │ │  ml_engine  1523L│ │   style features, etc.)  │
│                  │ │  session_trim2006│ │                          │
└──────────────────┘ │  lap_sim    2099L│ └──────────────────────────┘
                     │  friction   1470L│
                     │  reporting  5091L│
                     └──────────────────┘
```

## Data Flow

```
CSV Upload → io_racechrono.read_racechrono_csv()
    │
    ▼
GPS Filtering → gps_filtering.filter_gps_quality()
    │
    ▼
Derived Channels → derived_channels.compute_*()
    │            (speed, accel, distance, curvature, yaw)
    ▼
Session Trimming → session_trimming.trim_session()
    │             (outlier removal, per-type strategies)
    ▼
Track Detection → track_detection.register_or_match_track()
    │            (bbox matching, auto-registration)
    ▼
Corner Detection → corner_detection.detect_corners()
    │             (curvature-based, Gaussian smoothing)
    ▼
Resampling → resampling.resample_all_laps()
    │        (uniform distance grid for comparison)
    ▼
Feature Extraction → features.compute_*()
    │               (per-lap metrics)
    ▼
Reference + Physics → reference_line, friction_model,
    │                  vehicle_model, data_quality
    ▼
Theoretical Lap → theoretical_engine + lap_simulation
    │            (physics sim → percentile fallback)
    ▼
ML + Anomaly → ml_engine, anomaly_detection, feature_builder
    │
    ▼
Scoring → scoring.score_session()
    │    (Pace 30 + Consistency 25 + Execution 25 + Robustness 20)
    ▼
Reports + Storage → reporting_html, reporting_pdf,
                     driver_profile, DB insert
```

## External Dependencies

| Layer | Dependencies |
|-------|-------------|
| **Runtime** | Python 3.13, Flask 3.x, NumPy, Pandas, SciPy, scikit-learn |
| **Reporting** | WeasyPrint → pdfkit → wkhtmltopdf (3-tier fallback) |
| **Packaging** | PyInstaller (single-dir .exe), NSIS (installer) |
| **Frontend** | Chart.js (CDN), zero npm/node |
| **Database** | SQLite 3 (stdlib, zero-config) |
| **Data Source** | RaceChrono Pro CSV export (single vendor) |

## Key Architectural Decisions

1. **Single-process monolith** — Flask + SQLite, no async, no workers
2. **Pure-function analysis modules** — deterministic, testable, no side effects
3. **Graceful degradation** — each pipeline stage wrapped in `_safe_step()`; failures logged and skipped
4. **Self-test pattern** — every module has `_run_tests()` at bottom for validation
5. **No framework on frontend** — vanilla JS + Canvas 2D, minimal bundle
6. **JSON-in-TEXT columns** — GPS traces, score breakdowns, style features stored as JSON blobs in SQLite TEXT columns

---

# PROMPT 2 — Feature Inventory

## Complete Feature Catalogue

### Tier 1: Core Analysis (Import → Score → Report)

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 1 | CSV Import (RaceChrono) | `io_racechrono.py` | 653 | ✅ Working | Production — encoding fallbacks, column auto-detection |
| 2 | GPS Filtering | `gps_filtering.py` | 753 | ✅ Working | Production — Kalman-like smoothing, spike removal |
| 3 | Derived Channels | `derived_channels.py` | 1,586 | ✅ Working | Production — speed, accel, curvature, yaw, distance |
| 4 | Session Trimming | `session_trimming.py` | 2,006 | ✅ Working | Production — outlier removal, per-session-type strategies |
| 5 | Track Detection | `track_detection.py` | 932 | ✅ Working | Production — bbox matching, auto-register new tracks |
| 6 | Corner Detection | `corner_detection.py` | 1,199 | ✅ Working | Production — curvature-based, Gaussian smoothing |
| 7 | Lap Resampling | `resampling.py` | 645 | ✅ Working | Production — uniform distance grid |
| 8 | Feature Extraction | `features.py` + `feature_builder.py` | 2,331 | ✅ Working | Production |
| 9 | Session Scoring | `scoring.py` | 2,692 | ✅ Working | Production — 4-category, session-type weights |
| 10 | HTML Report | `reporting_html.py` | 4,162 | ✅ Working | Production — self-contained single-file report |
| 11 | PDF Report | `reporting_pdf.py` | 929 | ✅ Working | Production — 3-backend fallback chain |

### Tier 2: Physics & Theory

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 12 | Theoretical Lap | `theoretical_engine.py` | 1,359 | ✅ Working | Production — 98th/99th percentile envelope |
| 13 | Lap Simulation | `lap_simulation.py` | 2,099 | ✅ Working | Production — point-mass physics + friction |
| 14 | Friction Model | `friction_model.py` | 1,470 | ✅ Working | Production — grip estimation from data |
| 15 | Vehicle Model | `vehicle_model.py` | 1,192 | ✅ Working | Production — kart classification |
| 16 | Reference Line | `reference_line.py` | 1,383 | ✅ Working | Production — optimal racing line computation |
| 17 | Wet Physics | `wet_physics.py` | 901 | ✅ Working | Production — wet/dry grip modelling |

### Tier 3: Driver Intelligence

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 18 | Driving Style Classification | `driving_style.py` | 926 | ✅ Working | Production — multi-feature style profiling |
| 19 | Driver Profile | `driver_profile.py` | 1,224 | ✅ Working | Production — progression tracking, skill radar |
| 20 | Debrief Engine | `debrief_engine.py` | 1,080 | ✅ Working | Production — 7 mistake types, coaching hints |
| 21 | Corner Analysis | `corner_analysis.py` | 1,436 | ✅ Working | Production — per-corner metrics, coaching |
| 22 | Cross-Session Comparison | `cross_session.py` | 517 | ✅ Working | Production — percentile ranking, trends |
| 23 | Session Comparison | `session_comparison.py` | 524 | ✅ Working | Production — head-to-head session diffs |
| 24 | Development Plans | `development_plan.py` | 2,611 | ✅ Working | Production — 5 templates, 60 drills, progress tracking |

### Tier 4: Advanced Analytics

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 25 | ML Engine | `ml_engine.py` | 1,523 | ✅ Working | Production — RandomForest, feature importance |
| 26 | Anomaly Detection | `anomaly_detection.py` | 1,672 | ✅ Working | Production — statistical outlier flagging |
| 27 | Trend Analysis | `trend_analysis.py` | 340 | ✅ Working | Beta — polynomial fit, plateau detection |
| 28 | Rival Comparison | `rival_comparison.py` | 338 | ✅ Working | Beta — multi-driver gap analysis |
| 29 | Weather Correlation | `weather_correlation.py` | ~300 | ✅ Working | Beta — temp/humidity vs pace |
| 30 | Condition Tracking | `condition_tracking.py` | 1,063 | ✅ Working | Production — track evolution, phase detection |
| 31 | Tyre Degradation | `tyre_degradation.py` | 1,030 | ✅ Working | Production — pace fade, cliff detection |
| 32 | Stint Analysis | `stint_analysis.py` | 780 | ✅ Working | Production — per-stint metrics |
| 33 | Fatigue Detection | `fatigue_detection.py` | 591 | ✅ Working | Production — late-stint performance decay |

### Tier 5: Telemetry Enrichment

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 34 | Speed Profile Analysis | `speed_profile.py` | 623 | ✅ Working | Production — speed vs distance curves |
| 35 | Lap Distribution | `lap_distribution.py` | 608 | ✅ Working | Production — lap time histograms |
| 36 | Energy Balance | `energy_balance.py` | 502 | ✅ Working | Production — kinetic/potential energy |
| 37 | Lap Progress Tracker | `lap_progress.py` | 530 | ✅ Working | Production — session-long improvement |
| 38 | Session Badges | `session_badges.py` | 582 | ✅ Working | Production — 8 types, gold/silver/bronze |
| 39 | Workload Estimator | `workload_estimator.py` | 499 | ✅ Working | Production — physical load modelling |
| 40 | Session Summary | `session_summary.py` | 646 | ✅ Working | Production — natural-language summary |
| 41 | Auto-Tagging | `auto_tagging.py` | 496 | ✅ Working | Production — rule-based session tags |
| 42 | Data Health | `data_health.py` | 470 | ✅ Working | Production — quality scoring dashboard |
| 43 | Performance Fingerprint | `performance_fingerprint.py` | 477 | ✅ Working | Production — driver DNA chart |

### Tier 6: Simulation & Prediction

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 44 | What-If Simulator | `what_if_simulator.py` | ~350 | ✅ Working | Beta — corner speed adjustment |
| 45 | Setup Tracker | `setup_tracker.py` | ~350 | ✅ Working | Beta — setup vs pace correlation |
| 46 | Fuel Calculator | `fuel_calculator.py` | ~300 | ✅ Working | Beta — fuel effect, pit strategy |
| 47 | Race Pace Predictor | `race_pace_predictor.py` | 633 | ✅ Working | Production — pace projection |
| 48 | Line Optimization | `line_optimization.py` | ~300 | ✅ Working | Beta — deviation from reference |
| 49 | Pit Window Calculator | `pit_window.py` | 669 | ✅ Working | Production — optimal pit timing |

### Tier 7: UX & Workflow

| # | Feature | Module(s) | Lines | Status | Maturity |
|---|---------|-----------|-------|--------|----------|
| 50 | Custom Dashboards | `dashboard_builder.py` | 683 | ✅ Working | Production — widget grid layout |
| 51 | Annotations | `annotations.py` | 380 | ✅ Working | Production — CRUD, tags, search |
| 52 | Weekend Grouping | `web/routes/weekends.py` | ~200 | ✅ Working | Production — multi-session weekends |
| 53 | Leaderboard | `web/routes/leaderboard.py` | ~150 | ✅ Working | Production — cross-driver ranking |
| 54 | Session Replay | `session_replay.py` | 587 | ✅ Working | Production — animated playback |
| 55 | Visualization Mode | `web/routes/visualize.py` | ~200 | ✅ Working | Production — interactive charts |

### Infrastructure

| # | Feature | Module(s) | Lines | Status |
|---|---------|-----------|-------|--------|
| 56 | Data Quality Checks | `data_quality.py` | 1,319 | ✅ Production |
| 57 | Sensor Offset Correction | `sensor_offset.py` | 1,074 | ✅ Production |
| 58 | Distance Validation | `distance_validation.py` | 1,025 | ✅ Production |
| 59 | Deltas (Time Loss) | `deltas.py` | 955 | ✅ Production |
| 60 | Sector Analysis | `sector_analysis.py` | 607 | ✅ Production |
| 61 | Corner Persistence | `corner_persistence.py` | 827 | ✅ Production |
| 62 | Corner Mastery | `corner_mastery.py` | 563 | ✅ Production |
| 63 | Parquet Manager | `parquet_manager.py` | 467 | ✅ Production |
| 64 | Model Registry | `model_registry.py` | 541 | ✅ Production |
| 65 | Path Manager | `path_manager.py` | ~200 | ✅ Production |
| 66 | Tyre Comparator | `tyre_comparator.py` | 567 | ✅ Production |
| 67 | Session Context | `session_context.py` | 658 | ✅ Production |
| 68 | Batch Analysis | `batch_analysis.py` | ~250 | ✅ Production |

**Total: 68 features across ~88,600 lines of code (Python + JS + HTML + CSS)**

### Web Layer Summary

| Component | Count | Lines |
|-----------|-------|-------|
| Python modules (analysis) | ~55 | ~62,000 |
| Route blueprints | 17 | ~5,500 |
| HTML templates | 34 | ~5,000 |
| JavaScript files | 36 | ~10,000 |
| CSS files | 1 (main.css) | ~1,200 |
| DB layer (schema+migrate+queries) | 3 | ~1,600 |
| Test files | 22+ | ~4,000 |

---

# PROMPT 3 — Data Pipeline Documentation

## Pipeline Stages (14 + sub-stages)

### Stage 1: Ingest
- **Module:** `io_racechrono.read_racechrono_csv()`
- **Input:** Raw CSV file from RaceChrono Pro
- **Process:** Read with encoding fallback chain (utf-8 → latin-1 → cp1252), auto-detect column names, parse timestamps, identify lap boundaries from "Lap #" column
- **Output:** `pd.DataFrame` with columns: `Time (s)`, `Lap #`, `Speed (m/s)`, `Distance (m)`, `Latitude`, `Longitude`, accelerations
- **Failure mode:** Returns None → pipeline aborts

### Stage 2: GPS Filter
- **Module:** `gps_filtering.filter_gps_quality()`
- **Input:** Raw DataFrame
- **Process:** Kalman-like smoothing, spike detection (threshold: 3σ), interpolation of missing points
- **Output:** Cleaned DataFrame with smoothed GPS traces
- **Failure mode:** Returns original data (passthrough)

### Stage 3: Derived Channels
- **Module:** `derived_channels.compute_*()`
- **Input:** Filtered DataFrame
- **Process:** Compute from raw signals:
  - Speed from GPS if missing
  - Longitudinal acceleration (derivative of speed)
  - Lateral acceleration (from GPS curvature × speed²)
  - Curvature (from GPS heading changes)
  - Yaw rate (heading derivative)
  - Cumulative distance
- **Output:** DataFrame enriched with 6+ derived columns
- **Failure mode:** Individual channels skip; others proceed

### Stage 4: Session Trimming
- **Module:** `session_trimming.trim_session()`
- **Input:** Enriched DataFrame
- **Process:**
  - Detect outlier laps via IQR method (k=1.5)
  - Per-session-type strategies: qualifying keeps only fast laps, race keeps all, endurance preserves pit laps
  - Remove in/out laps (ratio threshold vs median: 1.3–2.5× depending on type)
  - Minimum 3 valid laps required
- **Output:** List of valid lap DataFrames + metadata
- **Failure mode:** Too few valid laps → warnings, returns what's available

### Stage 5: Track Detection
- **Module:** `track_detection.register_or_match_track()`
- **Input:** GPS coordinates from valid laps
- **Process:** Compute bounding box, compare against known tracks in DB, auto-register if new
- **Output:** `track_id` (str), track metadata
- **Failure mode:** Returns "unknown" track, analysis continues

### Stage 6: Corner Detection
- **Module:** `corner_detection.detect_corners()`
- **Input:** GPS traces, curvature profile
- **Process:**
  - Gaussian smoothing (σ=5 samples) of curvature
  - Threshold: curvature > 0.01 1/m → corner zone
  - Merge adjacent zones within 10m
  - Label as left/right by sign of curvature
  - Extract entry/apex/exit points
- **Output:** List of corner dicts with positions and geometry
- **Failure mode:** Returns empty list → corner-based features unavailable

### Stage 7: Resample
- **Module:** `resampling.resample_all_laps()`
- **Input:** Trimmed lap DataFrames
- **Process:** Interpolate each lap onto a uniform distance grid (step ≈ 1m) for lap-to-lap comparison
- **Output:** Dict of resampled DataFrames keyed by lap number
- **Failure mode:** Returns original laps (comparison less accurate)

### Stage 8: Feature Extraction
- **Module:** `features.compute_*()`
- **Input:** Resampled laps
- **Process:** Compute per-lap metrics:
  - Lap time, speed stats (mean, max, min, std)
  - Braking stats (max decel, brake count, brake duration)
  - Acceleration stats (max accel, throttle application)
  - Lateral G stats (max, mean, utilization)
  - Line length, distance variation
- **Output:** DataFrame of features (rows=laps, cols=metrics)
- **Failure mode:** Missing channels → NaN columns

### Stage 9: Reference + Physics Sub-stages
- **9a Reference Line:** `reference_line.compute_reference_line()` — optimal racing line from best-lap GPS
- **9b Curvature Profile:** `reference_line.compute_curvature_profile()` — distance-indexed curvature
- **9c Friction Model:** `friction_model.build_friction_model()` — grip limit estimation from G-G diagram envelope
- **9d Vehicle Model:** `vehicle_model.classify_vehicle()` — kart classification (rental, sprint, shifter)
- **9e Data Quality:** `data_quality.score_data_quality()` — GPS/accel quality scores, channel completeness

### Stage 10: Theoretical Lap
- **Module:** `theoretical_engine.py` + `lap_simulation.py`
- **Input:** Resampled laps, friction model, reference line
- **Process:**
  1. **Primary:** Point-mass physics simulation using friction model + vehicle model
  2. **Fallback:** Adaptive percentile envelope (98th speed, 99th accel per distance point)
  3. Trapezoidal integration of speed profile → lap time
- **Output:** Theoretical best lap time, speed/distance profile, gap percentage
- **Failure mode:** Falls back to percentile method; if that fails too → theoretical=None, scoring uses simpler pace metric

### Stage 11: Feature Dataset
- **Module:** `feature_builder.build_feature_dataset()`
- **Input:** Per-lap features, theoretical data, corner metrics
- **Process:** Assemble ML-ready feature matrix with standardized column names
- **Output:** Feature DataFrame for ML training/prediction

### Stage 12: ML + Anomaly
- **Module:** `ml_engine.py` + `anomaly_detection.py`
- **Input:** Feature dataset
- **Process:**
  - Train/update RandomForest regressor for pace prediction
  - Detect statistical anomalies (Z-score based, IQR)
  - Feature importance extraction
- **Output:** Predictions, anomaly flags, model metadata

### Stage 13: Scoring
- **Module:** `scoring.score_session()`
- **Input:** Lap data, theoretical lap, resampled laps, corner metrics
- **Process:** Four independent scorers:
  1. **Pace (0–30):** Gap to theoretical, blended absolute + percentage
  2. **Consistency (0–25):** CV% of lap times + best-to-median gap
  3. **Execution (0–25):** Speed/accel/brake efficiency vs theoretical
  4. **Robustness (0–20):** Pace retention (early vs late) + stability
  - Session-type weight adjustments (10 types)
  - Grade assignment: S(≥92) A(≥80) B(≥65) C(≥50) D(≥35) F(<35)
  - Strength/weakness identification
- **Output:** Structured score dict with breakdown

### Stage 14: Report Generation
- **Module:** `reporting_html.py`, `reporting_pdf.py`, `driver_profile.py`
- **Input:** All pipeline artifacts
- **Process:**
  - Generate self-contained HTML report (single file, embedded charts)
  - Generate PDF via WeasyPrint → pdfkit → wkhtmltopdf fallback
  - Update driver profile with progression data
  - Store to DB and filesystem
- **Output:** HTML file, PDF file, DB records updated

### Post-Pipeline Steps (triggered by web routes, not pipeline)
- Debrief engine coaching
- Badge assignment
- Auto-tagging
- Session summary generation
- Data health scoring
- Cross-session ranking update

## Error Handling Philosophy

Every stage is wrapped in `_safe_step()`:
```python
def _safe_step(fn, *args, label="step", **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("Step '%s' failed: %s", label, exc)
        return None
```

This means:
- **No single failure crashes the pipeline**
- Downstream stages check for None inputs and adapt
- Reports include "N/A" for unavailable sections
- Self-test suite validates each stage independently

---

# PROMPT 4 — Performance Baseline

## Current Performance Profile

### Pipeline Execution Time (estimated from architecture)

| Stage | Estimated Time | Bottleneck |
|-------|---------------|------------|
| 1. CSV Ingest | 0.5–2s | I/O bound — file size dependent |
| 2. GPS Filter | 0.2–0.5s | NumPy vectorized ops |
| 3. Derived Channels | 0.3–0.8s | NumPy — 6 channel computations |
| 4. Session Trimming | 0.1–0.3s | Statistical filtering |
| 5. Track Detection | 0.1–0.2s | DB query + bbox match |
| 6. Corner Detection | 0.5–1.5s | Gaussian smoothing + curvature threshold |
| 7. Resampling | 0.3–1.0s | Per-lap interpolation (scipy) |
| 8. Feature Extraction | 0.2–0.5s | NumPy vectorized |
| 9. Reference + Physics | 1.0–3.0s | Friction model fitting |
| 10. Theoretical Lap | 2.0–8.0s | **Largest bottleneck** — physics sim |
| 11. Feature Dataset | 0.1–0.2s | DataFrame assembly |
| 12. ML + Anomaly | 0.5–2.0s | RandomForest train/predict |
| 13. Scoring | 0.1–0.3s | Pure math |
| 14. Report Generation | 1.0–3.0s | HTML template rendering |

**Total estimated: 7–22 seconds per session (15–30 lap typical karting session)**

### Web Dashboard Response Times

| Endpoint Type | Estimated Response | Notes |
|--------------|-------------------|-------|
| Dashboard home | <100ms | Simple DB query |
| Session list | 100–300ms | Paginated query |
| Session detail | 200–500ms | Multiple DB queries + JSON parsing |
| API /session/<id>/laps | 50–150ms | Single query |
| API /session/<id>/gps | 100–400ms | JSON blob deserialization |
| API /session/<id>/gg-diagram | 100–300ms | JSON blob + processing |
| Full pipeline run (via web) | 7–22s | Full analysis |
| Batch re-analysis (5 sessions) | 35–110s | Sequential processing |

### Memory Profile

| Operation | Estimated RAM | Notes |
|-----------|--------------|-------|
| Idle Flask app | ~50 MB | Python + Flask overhead |
| Single session analysis | 100–300 MB | DataFrame in memory |
| Large session (50+ laps) | 300–500 MB | GPS traces dominate |
| Peak (physics simulation) | 400–600 MB | Multiple arrays simultaneously |

### Known Performance Gaps

1. **No caching layer** — every API call hits SQLite directly; JSON blob deserialization repeated per request
2. **Sequential pipeline** — stages run serially; stages 6–10 could partially parallelize
3. **Full page reload on drill completion** — `window.location.reload()` after each checkbox toggle
4. **No pagination on GPS traces** — large sessions load all GPS data at once
5. **SQLite WAL mode not enforced** — potential write contention on concurrent analysis runs
6. **No connection pooling** — new SQLite connection per request via Flask `g`
7. **Report generation blocks request** — HTML/PDF generation is synchronous

### Benchmarks Needed (not yet measured)

- [ ] End-to-end pipeline time with real SWS data (25-lap session)
- [ ] API p95 response time under concurrent load (5 users)
- [ ] Memory peak during physics simulation
- [ ] SQLite query performance with 100+ sessions in DB
- [ ] Frontend paint time with 30+ corner charts

---

# PROMPT 5 — Storage Model

## SQLite Database: `telemetry.db`

### Schema Summary

| Phase | Tables | Purpose |
|-------|--------|---------|
| Phase 1 (core) | `schema_version`, `tracks`, `drivers`, `sessions`, `laps`, `gps_traces`, `score_details`, `condition_phases` | Core data model |
| Phase 2 (weekends) | `weekends`, `weekend_sessions`, `track_records`, `condition_markers` | Weekend grouping, records |
| Phase 3 (profiles) | `driver_profiles`, `driver_progression`, `driving_style_features` | Driver analytics |
| Phase 4 (physics) | `theoretical_data`, `reference_lines` | Physics simulation results |
| Phase 5 (sectors) | `session_sectors` | Track sector decomposition |
| Phase 6 (health) | `data_health`, `session_tags` | Quality + tagging |
| Phase 7 (coaching) | `corner_metrics`, `corner_best_practices` | Per-corner coaching data |
| Phase 8 (weather) | `session_weather` | Weather correlation |
| Phase 9 (simulation) | `vehicle_setups`, `what_if_scenarios` | Setup + what-if |
| Phase 10 (workflow) | `session_annotations`, `development_plans`, `custom_dashboards`, `export_templates` | UX features |
| Phase 11 (stints) | `stint_analysis` | Per-stint metrics |

**Total: ~30 tables, Schema Version 11**

### Storage Growth Model

Per session stored:

| Data | Estimated Size | Storage Location |
|------|---------------|-----------------|
| Raw CSV | 1–5 MB | `data/raw/` filesystem |
| Session row | ~500 bytes | `sessions` table |
| Laps (25 rows) | ~2.5 KB | `laps` table |
| GPS traces (25 laps × 500pts) | ~1.5 MB | `gps_traces` table (JSON blobs) |
| Score details | ~1 KB | `score_details` table |
| Corner metrics (25 laps × 10 corners) | ~25 KB | `corner_metrics` table |
| Theoretical data | ~100 KB | `theoretical_data` table (speed profile JSON) |
| Driving style features | ~500 bytes | `driving_style_features` table |
| Driver progression row | ~200 bytes | `driver_progression` table |
| HTML report | 200–500 KB | `results/` filesystem |
| PDF report | 100–300 KB | `results/` filesystem |

**Per session total: ~2–7 MB (DB) + 1–5 MB (CSV) + 0.3–0.8 MB (reports) ≈ 3–13 MB**

### Growth Projections (SWS Target Market)

| Scenario | Sessions | DB Size | Total Disk |
|----------|----------|---------|------------|
| Casual driver (1 session/week, 1 year) | 52 | ~260 MB | ~500 MB |
| Active racer (3 sessions/week, 1 year) | 156 | ~780 MB | ~1.5 GB |
| Club with 10 drivers (3 sessions/week each, 1 year) | 1,560 | ~7.8 GB | ~15 GB |
| Intensive (10 drivers, 2 years) | 3,120 | ~15.6 GB | ~30 GB |

### Storage Risks

1. **GPS JSON blobs dominate** — `gps_traces` table is 70–80% of DB size; ~60KB per lap stored as JSON text
2. **No compression** — JSON blobs stored as raw text; could 5x compress with gzip
3. **No archival strategy** — no mechanism to archive old sessions or prune GPS data
4. **SQLite 2GB practical limit** — at current growth, a 10-driver club hits this in ~3–6 months of heavy use
5. **No vacuum scheduling** — deleted sessions leave dead space in DB file
6. **File-based reports accumulate** — HTML/PDF files never cleaned up

### Recommendations

1. **Short-term:** Enable WAL mode, schedule periodic VACUUM
2. **Medium-term:** Compress GPS JSON blobs (gzip → base64 in TEXT column), or move to separate binary store
3. **Long-term:** Consider PostgreSQL for club/multi-driver scenarios, or tiered storage (hot: last 3 months, warm: older)

---

# PROMPT 6 — Compute Model

## Computational Profile

### CPU-Intensive Operations (ranked by cost)

| Rank | Operation | Module | Complexity | Notes |
|------|-----------|--------|------------|-------|
| 1 | Physics Simulation | `lap_simulation.py` | O(n_points × iterations) | Point-mass sim, ~1000 distance points, 3–10 convergence passes |
| 2 | Friction Model Fit | `friction_model.py` | O(n_samples²) | G-G envelope fitting, convex hull |
| 3 | ML Training | `ml_engine.py` | O(n_features × n_estimators × n_samples) | RandomForest with 100 trees |
| 4 | Corner Detection | `corner_detection.py` | O(n_points × σ_window) | Gaussian convolution per lap |
| 5 | Resampling | `resampling.py` | O(n_laps × n_points) | scipy.interpolate per lap |
| 6 | GPS Filtering | `gps_filtering.py` | O(n_points) | Vectorized NumPy |
| 7 | Scoring | `scoring.py` | O(n_laps) | Pure math, vectorized |
| 8 | Report Generation | `reporting_html.py` | O(n_laps × n_charts) | String building + Jinja |

### Parallelization Opportunities

| Operation | Current | Could Be | Effort | Impact |
|-----------|---------|----------|--------|--------|
| Multi-session batch | Sequential | concurrent.futures.ProcessPool | Low | 3–5× for batch |
| Lap-level resampling | Sequential loop | Per-lap parallel | Low | 2× on multi-core |
| Physics sim | Single-threaded | Numba JIT or Cython | Medium | 5–10× per session |
| ML training | Single-threaded | n_jobs=-1 in sklearn | Trivial | 2–4× |
| Corner analysis | Sequential per corner | NumPy vectorize across corners | Low | 2× |

### Scaling Limits

| Dimension | Current Limit | Bottleneck |
|-----------|--------------|------------|
| Sessions per day | ~50–100 (serial) | CPU — physics sim |
| Concurrent web users | 3–5 | SQLite write lock + single Flask thread |
| Laps per session | 100+ works | Memory — GPS arrays |
| Corners per track | 30+ works | O(corners × laps) in analysis |
| Tracks in DB | 100+ works | Bbox matching is O(n_tracks) |
| Historical sessions for ML | ~1000 | Feature matrix in RAM |

### Compute Cost Analysis

For SWS rental kart market:
- **Typical session:** 15–25 laps, ~10 corners, 8-minute session
- **Pipeline time:** ~10–15 seconds
- **RAM:** ~150–250 MB peak
- **Disk I/O:** ~5–10 MB read/write

This is well within a single laptop or desktop. No cloud compute needed for the target market of individual recreational kart drivers.

### Optimization Roadmap

1. **Quick wins (1–2 days):**
   - Enable `n_jobs=-1` on sklearn estimators
   - Add `functools.lru_cache` to frequently called pure functions (track lookup, corner lookup)
   - Enable SQLite WAL mode

2. **Medium effort (1 week):**
   - Batch pipeline with ProcessPoolExecutor
   - Pre-compute and cache theoretical laps per track
   - Add Redis/SQLite-based response cache for API endpoints

3. **Significant effort (2–4 weeks):**
   - Numba JIT for physics simulation inner loop
   - Move to PostgreSQL for concurrent write support
   - WebSocket for live pipeline progress (replace polling)

---

# PROMPT 7 — CSV Specification Extraction

## RaceChrono Pro CSV Format

### Expected Columns (from `io_racechrono.py` + `pipeline.py`)

| Column Name | Type | Unit | Source | Required |
|-------------|------|------|--------|----------|
| `Time (s)` | float | seconds | RaceChrono timestamp | **Yes** |
| `Lap #` | int | — | RaceChrono lap counter | **Yes** |
| `Speed (m/s)` | float | m/s | GPS-derived or OBD | Preferred |
| `Speed (m/s) *calc` | float | m/s | RaceChrono calculated | Fallback for Speed |
| `Distance (m)` | float | metres | Cumulative | Preferred |
| `Latitude` | float | degrees | GPS | Preferred (for corners, track map) |
| `Longitude` | float | degrees | GPS | Preferred (for corners, track map) |
| `Longitudinal acceleration (G) *calc` | float | G | Calculated from speed | Optional |
| `Longitudinal acceleration (m/s²)` | float | m/s² | Accelerometer | Optional |
| `Lateral acceleration (G) *calc` | float | G | Calculated from GPS | Optional |
| `Lateral acceleration (m/s²)` | float | m/s² | Accelerometer | Optional |

### Column Name Mapping (from `_RAW_TO_INTERNAL` in `pipeline.py`)

```
"Distance (m)"                         → distance_m
"Speed (m/s)"                          → speed_mps
"Speed (m/s) *calc"                    → speed_mps     (fallback)
"Longitudinal acceleration (G) *calc"  → accel_long_mps2
"Longitudinal acceleration (m/s²)"     → accel_long_mps2
"accel_long"                           → accel_long_mps2
"accel_long_g"                         → accel_long_mps2
"Lateral acceleration (G) *calc"       → accel_lat_mps2
"Lateral acceleration (m/s²)"         → accel_lat_mps2
"accel_lat"                            → accel_lat_mps2
"Time (s)"                             → time_s
"Lap #"                                → lap_number
```

### Minimum Viable CSV

The absolute minimum for a session to process:
1. `Time (s)` — required for lap timing
2. `Lap #` — required for lap separation
3. At least one of: `Speed (m/s)` or `Speed (m/s) *calc` — needed for pace analysis

Without GPS (`Latitude`, `Longitude`): corner detection, track maps, and racing line analysis are unavailable but scoring still works on speed/time data.

Without acceleration channels: derived channels compute them from GPS/speed data.

### Encoding Handling

```python
# Fallback chain in io_racechrono.py:
encodings = ['utf-8', 'latin-1', 'cp1252']
```

### Sample Rate

RaceChrono Pro typically exports at 10–25 Hz GPS rate. The pipeline handles any sample rate via time-based interpolation during resampling.

### Edge Cases Handled

- Duplicate column names → first occurrence wins
- Missing columns → derived_channels attempts to compute
- Non-numeric values → coerced to NaN, filtered
- Empty laps (0 data points) → removed in trimming
- Single lap → minimum 1 lap for basic analysis, 3+ for full statistics

---

# PROMPT 8 — Lap-Detection Correctness Analysis

## Current Implementation

### Primary Method: `Lap #` Column from RaceChrono

The pipeline does **not** detect laps from GPS data. It relies entirely on the `Lap #` column pre-computed by RaceChrono Pro using:
- Start/finish line GPS coordinates set by the user in the app
- Crossing detection at the phone/device level

### Lap Boundary Processing

```
1. io_racechrono reads CSV → groups by "Lap #" column
2. Each unique Lap # value = one lap
3. session_trimming filters:
   - Remove laps with fewer than N data points (configurable, default ~10)
   - Remove laps where lap_time exceeds median × outlap_ratio
   - Per-type ratios: qualifying=1.3×, race=2.0×, endurance=2.5×
   - Remove laps shorter than min_lap_time (e.g., 5s)
```

### Correctness Assessment

**Strengths:**
1. Relies on RaceChrono's built-in lap detection — mature, user-verified
2. No risk of GPS drift causing false lap boundaries
3. Works even without high-quality GPS (as long as RaceChrono detects crossings)

**Weaknesses / Risks:**
1. **Single point of failure:** If user misconfigures start/finish line in RaceChrono, ALL laps are wrong — the pipeline has no way to detect or correct this
2. **No validation against distance:** A "lap" of 50m (when track is 1km) is accepted if it passes the time filter — should validate `line_length_m ≈ track.lap_length_m`
3. **In/out lap detection is time-ratio only:** A slow exploratory lap that happens to be within the outlap_ratio threshold would be kept — could cross-check against distance
4. **No split-crossing detection:** If a driver crosses the start/finish line mid-corner (common at some kart tracks), RaceChrono may produce a "lap" that's actually a half-lap
5. **Lap numbering gaps:** If RaceChrono skips a lap number, the pipeline doesn't detect the gap

### Recommended Improvements

1. **Distance validation gate:** After track detection, verify each lap's distance is within ±15% of `track.lap_length_m`. Flag/remove laps outside this range.
2. **GPS-based fallback detection:** If `Lap #` column is missing or has only one value, attempt GPS-based crossing detection using track start/finish coordinates.
3. **Lap integrity score:** Combine time ratio + distance ratio + speed profile completeness into a confidence score per lap.
4. **User alert for anomalous laps:** Surface laps that pass filters but look suspicious (e.g., distance off by >10%).

---

# PROMPT 9 — Scoring System Correctness Audit

## Scoring Architecture

### Category Weights (sum = 100)

| Category | Max Points | Sub-weights | What It Measures |
|----------|-----------|-------------|-----------------|
| **Pace** | 30 | 70% percentage gap + 30% absolute gap | Best lap vs theoretical |
| **Consistency** | 25 | 60% CV% + 40% best-to-median gap | Lap-to-lap repeatability |
| **Execution** | 25 | 50% speed + 25% accel + 25% brake | Corner efficiency vs theoretical |
| **Robustness** | 20 | 60% pace fade + 40% stability | Late-stint performance retention |

### Pace Scoring Detail

**Physics simulation path (primary):**
```
pace_gap_pct = (driver_best - theoretical) / theoretical × 100
pace_gap_s   = driver_best - theoretical

score_pct = MAX_PACE × (1 - ((gap_pct - 2.0) / (12.0 - 2.0))^1.6)  [clamped 0–MAX_PACE]
score_abs = MAX_PACE × (1 - ((gap_s - 1.0) / (8.0 - 1.0))^1.6)     [clamped 0–MAX_PACE]

final_pace = 0.70 × score_pct + 0.30 × score_abs
```

**Thresholds:**
- Within 2% or 1.0s → full 30 points
- At 12% or 8.0s → 0 points
- Decay exponent 1.6 → moderately forgiving near peak

**Correctness check:** ✅ Sound. Percentage-based scoring normalizes across track lengths. The absolute component guards against very short tracks where 2% = 0.3s. The 1.6 exponent creates a curve that rewards being close to the limit without cliff effects.

### Consistency Scoring Detail

```
CV% = std(lap_times) / mean(lap_times) × 100
BTM = median(lap_times) - best_lap_time

score_cv  = 0.60 × MAX_CONSISTENCY × (1 - (CV% - 0.6) / (3.0 - 0.6))
score_btm = 0.40 × MAX_CONSISTENCY × (1 - (BTM - 0.6) / (5.0 - 0.6))
```

**Wet adjustment:** Wider thresholds (CV zero=5.0%, BTM zero=6.0s)

**Correctness check:** ✅ Sound. CV% is the standard metric for consistency in motorsport. The BTM component adds useful information about how tight the best-vs-typical gap is. Session-type adjustments (endurance allows wider CV) are implemented.

**Potential issue:** For very short sessions (3–4 laps), CV% has high variance — a single outlier lap dominates. Consider minimum lap count guard (already at 3, might want 5 for full consistency scoring).

### Execution Scoring Detail

```
speed_ratio = mean_driver_speed / theoretical_speed
accel_ratio = driver_max_accel / theoretical_max_accel
brake_ratio = driver_max_brake / theoretical_max_brake

score = 0.50 × f(speed_ratio) + 0.25 × f(accel_ratio) + 0.25 × f(brake_ratio)
```

Where `f(ratio)` is a linear map from [zero_ratio, full_ratio] → [0, MAX_EXECUTION]

**Correctness check:** ⚠️ Moderate concern. Speed efficiency ratio against the theoretical lap is valid, but the accel/brake ratios compare peaks rather than profiles. A driver with one spike of max braking would score the same as one who consistently brakes hard. **Recommendation:** Use percentile (75th) rather than max for more representative comparison.

### Robustness Scoring Detail

```
early_laps = first 33% of session
late_laps  = last 33% of session

pace_fade = (mean_late - mean_early) / mean_early
yaw_ratio = var_yaw_late / var_yaw_early

score_fade = 0.60 × MAX_ROBUSTNESS × (1 - (fade - 0.01) / (0.05 - 0.01))
score_stab = 0.40 × MAX_ROBUSTNESS × (1 - (yaw - 1.1) / (2.5 - 1.1))
```

**Correctness check:** ✅ Sound. Pace fade is the gold standard for endurance assessment. The yaw-rate stability component adds a unique physical-consistency dimension. The early/late split at 33% is reasonable for 15–25 lap sessions.

**Edge case:** In qualifying (5–8 fast laps), early/late split may only have 2 laps each — high variance. Session-type weighting addresses this (robustness weight drops to 0.60 in qualifying).

### Session-Type Weight Overrides

```python
_SESSION_WEIGHT_OVERRIDES = {
    "qualifying":      {"pace": 1.40, "consistency": 0.90, "execution": 1.10, "robustness": 0.60},
    "race":            {"pace": 0.90, "consistency": 1.10, "execution": 0.90, "robustness": 1.40},
    "sprint_race":     {"pace": 0.90, "consistency": 1.10, "execution": 0.90, "robustness": 1.40},
    "practice":        {"pace": 1.00, "consistency": 1.00, "execution": 1.20, "robustness": 0.80},
    "test":            {"pace": 0.80, "consistency": 1.10, "execution": 1.30, "robustness": 0.80},
    "warmup":          {"pace": 0.60, "consistency": 0.80, "execution": 1.30, "robustness": 0.60},
    "heat":            {"pace": 1.20, "consistency": 1.00, "execution": 1.00, "robustness": 0.80},
    "final":           {"pace": 1.10, "consistency": 1.00, "execution": 1.00, "robustness": 0.90},
    "feature_race":    {"pace": 0.90, "consistency": 1.10, "execution": 0.90, "robustness": 1.40},
    "endurance_stint": {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60},
    "endurance_race":  {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60},
}
```

**Correctness check:** ✅ Sound. Weight multipliers are normalized so total still = 100. The overrides correctly emphasize pace for qualifying, robustness for endurance, and execution for practice/test sessions.

### Grade Boundaries

| Grade | Threshold | Label |
|-------|-----------|-------|
| S | ≥92 | Exceptional |
| A | ≥80 | Excellent |
| B | ≥65 | Good |
| C | ≥50 | Average |
| D | ≥35 | Below Average |
| F | <35 | Needs Work |

**Correctness check:** ✅ Reasonable distribution. For SWS rental kart drivers, most sessions should land in B–C range (50–80), giving clear room for improvement visibility.

### Overall Scoring Verdict

**Score: 8/10 — Generally sound with minor improvements needed:**
1. Execution sub-score should use percentile rather than peak for accel/brake
2. Minimum lap count for full consistency scoring should be 5 (currently 3)
3. Consider adding a "data quality confidence" modifier — scores from sessions with poor GPS should be flagged as less reliable

---

# PROMPT 10 — Theoretical Optimal Lap

## Implementation Analysis

### Architecture

Two-tier approach:
1. **Primary: Physics simulation** (`lap_simulation.py`, 2,099 lines)
2. **Fallback: Percentile envelope** (`theoretical_engine.py`, 1,359 lines)

### Physics Simulation (Primary)

**Method:** Point-mass vehicle model with friction circle constraint

```
For each distance point along the reference line:
1. Compute available grip from friction model
2. Compute max cornering speed from curvature + grip
3. Forward pass: accelerate from corner exit, limited by grip + power
4. Backward pass: decelerate into corners, limited by grip + braking
5. Take minimum of forward/backward speed at each point
6. Integrate speed profile → lap time (trapezoidal rule)
```

**Inputs required:**
- Reference line (from best-lap GPS)
- Friction model (from G-G diagram envelope fitting)
- Vehicle model (kart classification → mass, power, CoG estimates)
- Track curvature profile

**When it fires:** Physics sim is attempted when friction model + reference line + vehicle model are all available.

### Percentile Envelope (Fallback)

**Method:** Build ideal speed profile from best segments across all laps

```
For each distance point:
  ideal_speed[d] = percentile(all_laps_speed_at_d, 98th)
  ideal_accel[d] = percentile(all_laps_accel_at_d, 99th)

Apply physical constraints:
  - Speed cannot exceed friction-limited cornering speed
  - Acceleration cannot exceed available grip
  - Deceleration limited by braking capacity

Integrate constrained speed profile → theoretical lap time
```

**Why 98th/99th (not 100th):** The maximum can contain GPS spikes or sensor noise. 98th/99th percentile is robust to outliers while still representing near-best performance.

### Correctness Assessment

**Strengths:**
1. Two-tier fallback ensures theoretical lap is almost always available
2. Physics sim accounts for grip, power, and weight — physically meaningful
3. Percentile method works even without detailed physics knowledge
4. Both methods produce a full speed-vs-distance profile (not just a time)

**Weaknesses / Concerns:**
1. **Physics sim relies on friction model accuracy:** Friction model is fitted from actual driver data, so it inherently reflects the driver's grip utilization (not true physical limit). This means the "theoretical" lap is "best this driver could achieve given their current technique" rather than "what a perfect driver would achieve."
   - **Impact:** Gap to theoretical may be overly optimistic — real limit could be further away
   - **Recommendation:** Weight friction model toward top 10% of G-G data points, not all data

2. **Percentile method ceiling effect:** With only 15–25 laps from a single session, the 98th percentile at each point is essentially "best seen at this distance." For a driver who is consistently slow in one corner, the theoretical will be close to their actual — hiding the improvement opportunity.
   - **Recommendation:** For tracks with reference data from faster drivers, blend in external reference

3. **Vehicle model is estimated:** The system classifies karts as rental/sprint/shifter and uses generic mass/power values. Real kart performance varies significantly (tire wear, engine tune, track temperature).
   - **Impact:** Physics sim accuracy is ±10–15% on lap time — sufficient for relative scoring but imprecise for absolute benchmarks

4. **No warm-up modeling:** The theoretical lap assumes cold start (no tire temp effect). In reality, tire temperature significantly affects grip in the first 2–3 laps.

### Verdict

**Score: 7/10 — Good approach, execution limitations acknowledged.** The two-tier system is architecturally sound. The main improvement would be incorporating external reference data (faster drivers, track records) to set a more aspirational theoretical target.

---

# PROMPT 11 — Debrief / Coaching Engine Audit

## Implementation: `debrief_engine.py` (1,080 lines)

### Mistake Classification (7 Types)

| # | Mistake Type | Detection Signal | Coaching Response |
|---|-------------|-----------------|-------------------|
| 1 | Late Braking | Brake point > reference + threshold | "Try braking X meters earlier at corner Y" |
| 2 | Early Braking | Brake point < reference - threshold | "You're leaving time on the table — brake later" |
| 3 | Slow Apex Speed | Apex speed < 90% of best apex speed | "Carry more speed through the apex" |
| 4 | Late Throttle Application | Throttle onset > reference + threshold | "Get on the throttle earlier at exit" |
| 5 | Inconsistent Line | Line variation index > threshold | "Your line is inconsistent — pick a reference point" |
| 6 | Over-Driving (Scrubbing) | High lateral G + low speed | "You're scrubbing speed — smoother inputs" |
| 7 | Pace Fade | Late stint pace > 103% of early stint | "Work on physical endurance and tire management" |

### Coaching Output

For each detected issue, the engine generates:
1. **What happened** — metric-backed description
2. **Why it matters** — time loss estimate
3. **How to fix it** — actionable drill recommendation
4. **Priority** — ranked by time loss magnitude

### Session Summary

`summarize_session()` produces a natural-language debrief:
- Top 3 strengths
- Top 3 areas for improvement
- Next-session focus recommendation
- Coaching tone adapts by session type (race → tactical, qualifying → performance, practice → technique)

### Development Plans Integration

The debrief engine feeds into `development_plan.py` which provides:
- 5 pre-built plan templates (beginner, intermediate, advanced, race-prep, consistency)
- 4 weeks × 3 drills per plan = 60 total drills
- Each drill has: detailed instructions, steps, tips, common mistakes, success criteria
- Progress tracking with completion percentage

### Correctness Assessment

**Strengths:**
1. Mistake types cover the most common recreational karting errors
2. Time-loss estimates provide concrete motivation for improvement
3. Coaching adapts to session type (not one-size-fits-all)
4. Development plans provide structured long-term progression

**Weaknesses:**
1. **Static coaching cues** — responses don't evolve based on the driver's history. A driver who has been told "brake earlier" for 10 sessions should get a different message.
2. **No video/visual reference** — coaching is text-only; no overlay on GPS trace or speed profile
3. **Binary mistake detection** — either you have the mistake or you don't; no severity gradation beyond time-loss magnitude
4. **Missing mistake types for rental karts:**
   - Defensive driving (lifting in traffic) — common in rental leagues
   - Weather adaptation delay — slow to adjust in changing conditions
   - Tire warm-up technique — first 2–3 laps

### Recommendations for SWS Market

1. Add "progress-aware coaching" — compare current issues vs last 3 sessions
2. Add GPS-trace overlay showing brake point drift (visual coaching)
3. Add "traffic management" mistake type for race sessions
4. Consider ChatGPT/Claude API integration for more natural coaching language (future)

---

# PROMPT 12 — Weekend Analysis

## Implementation

### Architecture

- **DB tables:** `weekends`, `weekend_sessions` (Phase 2 schema)
- **Web routes:** `web/routes/weekends.py`
- **Templates:** `weekend_list.html`, `weekend_form.html`, `weekend_detail.html` (412 lines)

### Features

1. **Weekend creation** — Group multiple sessions under a named weekend event
2. **Session ordering** — Manual ordering within a weekend (session_order column)
3. **Cross-session comparison** — View progression across practice → qualifying → race
4. **Weekend summary view** — Shows all sessions with scores, lap times, progression arc

### Current Capabilities

- Create/edit/delete weekends
- Add/remove sessions to weekends
- View session list with scores and timing
- Compare sessions within a weekend
- Track-level grouping (same track required)

### Gap Analysis for SWS Market

**What exists:** Basic weekend grouping with manual session assignment
**What's missing for SWS rental karting:**

1. **No automatic weekend detection** — User must manually group sessions; could auto-detect by date proximity + track
2. **No practice→qualifying→race flow visualization** — Weekend detail shows flat list, not a progression narrative
3. **No pace evolution chart** — Should show best lap per session as a line chart across the weekend
4. **No position tracking** — Race results (finishing position) not captured
5. **No rival comparison within weekend** — Can't compare against other drivers at the same event
6. **No "event report"** — No single-page PDF summarizing the entire weekend

### Recommendations

1. Auto-group sessions within 48 hours at same track as "weekend"
2. Add weekend progression chart (best lap per session, colored by session type)
3. Add simple position input for race sessions
4. Generate weekend PDF report with progression narrative

---

# PROMPT 13 — Endurance / Stint Mode

## Implementation

### Relevant Modules

| Module | Lines | Role |
|--------|-------|------|
| `stint_analysis.py` | 780 | Per-stint metrics, pace fade, tyre cliff |
| `tyre_degradation.py` | 1,030 | Pace degradation modelling |
| `fatigue_detection.py` | 591 | Late-stint performance decay |
| `pit_window.py` | 669 | Optimal pit timing |
| `fuel_calculator.py` | ~300 | Fuel effect modelling |
| `condition_tracking.py` | 1,063 | Track evolution, condition phases |

### Stint Analysis Features

1. **Stint detection** — Identifies stint boundaries from lap time gaps (>2× median = pit/break)
2. **Per-stint metrics:** best/mean/median/std lap time, CV%, pace fade%, tire cliff detection
3. **Pace fade modeling** — Linear regression of lap times within stint, slope = fade rate
4. **Tyre cliff detection** — Detects sudden pace drop-off (>3% slower than running average)
5. **Coaching hint generation** — Per-stint coaching based on pace pattern

### Tyre Degradation Model

- Exponential decay fit: `lap_time(n) = base + α × e^(β × n)`
- Estimates tyre life window (before cliff)
- Compares actual vs predicted degradation

### Fatigue Detection

- Compares consistency metrics (CV%, line variation) between first half and second half of stint
- Increased inconsistency + pace fade = fatigue signal
- Generates fatigue-specific coaching

### Pit Window Calculator

- Combines tyre degradation model + fuel load effect
- Estimates optimal pit stop lap for endurance races
- Considers track position loss from pit stop time

### Endurance Session Scoring

Via `_SESSION_WEIGHT_OVERRIDES`:
```python
"endurance_stint": {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60}
"endurance_race":  {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60}
```
Robustness gets 1.6× weight (highest of any type), pace drops to 0.8×. This correctly emphasizes consistency and stamina over raw speed.

### Trimming for Endurance

```python
"endurance_*": keep_all=True, preserve_pit_laps=True, outlap_ratio=2.5
```
All laps kept (including slow pit in/out), very lenient outlier threshold. This preserves the full session picture.

### Gap Analysis

**Comprehensive for a V1.** The main gaps for the SWS market are:

1. **No driver swap detection** — Endurance races with driver changes are common in rental karting leagues. System doesn't detect or handle multi-driver stints.
2. **No stint comparison across teams** — Can't compare your stint pace against rival teams' stints.
3. **No real-time stint monitoring** — Everything is post-hoc; no live timing integration.
4. **Fuel model is theoretical** — Rental karts typically have fixed fuel; model is more relevant for owned karts.

### Verdict

**Score: 8/10 — Strong endurance feature set for V1.** The stint analysis, tyre degradation, and fatigue detection form a coherent package. Main improvement for SWS: add driver swap detection for team endurance events.

---

# PROMPT 14 — UX Audit

## Current UX Assessment

### Navigation Structure

From `base.html` — Main nav dropdown with sections:
- Dashboard (home)
- Sessions (list, upload, detail)
- Tracks (list, detail)
- Drivers (list, profiles)
- Analysis (run pipeline)
- Comparisons
- Weekends
- Leaderboard
- Visualize
- Data Health
- Analytics (weather, trends)
- Predictions (what-if)
- Dev Plans
- Custom Dashboards
- Exports

**Issue:** 15+ top-level navigation items is overwhelming. Most users will use 3–5 features regularly.

### Design System

- **Dark theme** — single CSS file (`main.css`), dark background (#1a1a2e), light text
- **No design framework** — custom CSS only
- **Responsive:** Partially — some templates use flex/grid, others are fixed-width
- **Typography:** System fonts, no custom font loading
- **Color palette:** Blues (#36a2eb), greens (#4caf50), reds (#e74c3c), golds (#ffd700) — consistent but informal

### Page-by-Page Assessment

| Page | Quality | Issues |
|------|---------|--------|
| Dashboard | ⭐⭐⭐ | Good overview, but dense. No visual hierarchy for new users. |
| Session List | ⭐⭐⭐ | Functional table, lacks visual sessions cards |
| Session Detail | ⭐⭐⭐⭐ | Rich — many tabs, charts work well. Tab overload (15+ tabs). |
| Track Detail | ⭐⭐⭐ | Functional, track map renders well |
| Dev Plans | ⭐⭐⭐⭐ | Recently enriched, beautiful drill cards with expandable details |
| Leaderboard | ⭐⭐⭐ | Clean table, could use more visual comparison |
| Upload Flow | ⭐⭐ | Basic file picker → form. No progress indicator during analysis. |
| Weekend Detail | ⭐⭐⭐ | Functional but information-dense |

### Critical UX Issues

1. **No loading states** — Pipeline analysis takes 10–20s with no progress feedback
2. **Full page reload on actions** — Many actions use `window.location.reload()` instead of DOM updates
3. **No empty states** — New user sees blank pages with no guidance
4. **Tab overload on session detail** — 15+ tabs; should be grouped into 3–4 main sections
5. **No mobile optimization** — Site is desktop-focused; kart drivers often access from phone after sessions
6. **No dark/light toggle** — Forced dark theme (fine for most, but no option)
7. **Error messages are generic** — "Something went wrong" with no actionable guidance
8. **No keyboard shortcuts** — Power users can't navigate efficiently

### UX Recommendations for SWS Launch

**Must-fix (before launch):**
1. Add loading spinner during pipeline analysis
2. Add empty states with setup guidance for new users
3. Group session detail tabs into sections (Overview, Corners, Coaching, Advanced)
4. Make upload flow show progress steps

**Should-fix (within 2 weeks post-launch):**
1. Mobile-responsive session list and session detail
2. Guided first-session flow (upload → analyze → view results)
3. Simplify nav to 5–6 items (Dashboard, Sessions, Coaching, Analytics, Settings)
4. Add visual session cards instead of table rows

**Nice-to-have:**
1. Keyboard shortcuts (j/k navigation, / for search)
2. Dark/light theme toggle
3. Drag-and-drop CSV upload
4. Notification system for completed analyses

---

# PROMPT 15 — Onboarding Design

## Current State

**There is no onboarding flow.** New users land on the dashboard which shows:
- Empty session list
- Empty track list
- No guidance on what to do first

### Proposed Onboarding Flow

#### Step 1: Welcome Screen (first visit detection)

```
Welcome to Telemetry Analysis!

Let's get you set up in 3 steps:

1. 📱 Record a session with RaceChrono Pro
2. 📤 Upload your CSV file
3. 📊 View your analysis & coaching

[Upload Your First Session] →
[I'll explore first] →
```

#### Step 2: Upload Wizard

```
Step 1 of 3: Upload CSV
┌─────────────────────────────────┐
│  [Drag CSV here]                │
│  or [Browse Files]              │
│                                 │
│  Supports: RaceChrono Pro CSV   │
│  Need help? [Export Guide] →    │
└─────────────────────────────────┘

Step 2 of 3: Session Details
- Driver name: [Auto-detect or enter] ────
- Session type: [Practice ▼]
- Track condition: [Dry ▼]
- Notes: [Optional] ────────────

Step 3 of 3: Analyzing...
[████████████░░░░░░░░] 60%
Detecting corners... ✓
Computing scores...  ⟳
Generating report... ○
```

#### Step 3: First Results Guided Tour

```
🎉 Your first session is analyzed!

Your Score: 72/100 (Grade: B)

Let me show you what this means...
[Start Tour] → [Skip]

Tour stops:
1. "This is your overall score..."
2. "These are your strengths..."
3. "Here's where you can improve..."
4. "Check out your coaching plan..."
```

### RaceChrono Export Guide

A critical piece of onboarding — users need to know HOW to get data out of RaceChrono:

```
How to Export from RaceChrono Pro
─────────────────────────────────
1. Open RaceChrono Pro
2. Select your session
3. Tap ⋮ (menu) → Export
4. Choose "CSV" format
5. Select these channels:
   ✅ Speed
   ✅ Distance
   ✅ GPS Position
   ✅ Accelerations
   ✅ Lap number
6. Save/share the file
7. Upload here!
```

### Implementation Effort

| Component | Effort | Priority |
|-----------|--------|----------|
| Welcome screen | 2 hours | P0 — must have for launch |
| Upload wizard (3-step) | 4 hours | P0 — must have |
| Analysis progress bar | 3 hours | P0 — must have |
| Guided tour (first results) | 6 hours | P1 — first week post-launch |
| RaceChrono export guide page | 2 hours | P0 — must have |
| First-visit detection (cookie/localStorage) | 1 hour | P0 |

**Total: ~18 hours for complete onboarding**

---

# PROMPT 16 — PDF Export Assessment

## Current Implementation: `reporting_pdf.py` (929 lines)

### Backend Chain

```
WeasyPrint (preferred)
    ↓ if unavailable
pdfkit (wkhtmltopdf wrapper)
    ↓ if unavailable
wkhtmltopdf (direct subprocess)
    ↓ if all fail
HTML-only export (fallback)
```

### What's in the PDF Report

1. **Header:** Session name, date, driver, track, session type
2. **Score summary:** Total score, grade, 4 sub-scores with bar charts
3. **Lap times table:** All laps with timing, valid/invalid flags
4. **Speed profile chart:** Speed vs distance for best lap
5. **Consistency chart:** Lap times over session
6. **Strengths & weaknesses:** Bullet points from scoring
7. **Corner analysis summary:** Per-corner performance (if available)
8. **Coaching recommendations:** From debrief engine

### Quality Assessment

**Strengths:**
1. Three-tier fallback means PDF generation rarely fails completely
2. Self-contained HTML → PDF means consistent styling
3. Charts embedded as inline SVG/canvas (no external dependencies)

**Weaknesses:**
1. **Chart rendering in PDF is fragile** — Canvas-based charts don't render in WeasyPrint; requires Chart.js server-side rendering or static image generation
2. **No custom report builder** — One fixed format; users can't choose sections
3. **No batch PDF export** — Can't generate reports for an entire weekend or season
4. **No branding/customization** — Fixed layout; no team logos, custom colors
5. **File size can be large** — Embedded images + full HTML → 1–3MB per report
6. **No markdown export** — Code exists for it but it's basic

### PDF Export Recommendations

For SWS market:

1. **Fix chart rendering** — Use matplotlib or Plotly for PDF charts (server-side), reserve Chart.js/Canvas for web only
2. **Add selectable sections** — Checkbox UI: "Include corner analysis? Include coaching? Include GPS trace?"
3. **Add weekend summary PDF** — Single PDF covering all sessions in a weekend
4. **Add team branding** — Logo upload, custom header/footer
5. **Reduce file size** — Optimize images, compress embedded data

---

# PROMPT 17 — QA Plan

## Current Test Coverage

### Existing Test Files

| File | Tests | What It Covers |
|------|-------|----------------|
| `test_session_trimming.py` | 24 | Outlier removal, per-type strategies, edge cases |
| `test_pipeline_physics.py` | 18 | Physics simulation, theoretical lap |
| `test_reporting.py` | 44 | HTML/PDF generation, all report sections |
| `test_driving_style.py` | 7 | Style classification |
| `test_cross_session.py` | 5 | Cross-session comparison |
| `test_routes.py` | 15 | Flask route response codes |
| `test_integration.py` | ~10 | End-to-end pipeline |
| `test_session_context.py` | ~8 | Session context builder |
| `test_bug_fixes.py` | ~10 | Regression tests |
| `test_debrief_engine.py` | ~10 | Coaching generation |
| Various module self-tests | ~50+ | Per-module _run_tests() |

**Estimated total: ~200 tests across 22 test files + self-tests**

### Coverage Gaps

| Area | Coverage | Risk |
|------|----------|------|
| Scoring edge cases | Medium | Incorrect scores for unusual sessions |
| GPS filtering | Low | Corrupted data might pass through |
| Corner detection | Low | False positives/negatives on unusual tracks |
| ML engine | Low | Model drift, poor predictions |
| API endpoints | Medium | Missing validation, error handling |
| Frontend JS | None | No JS tests at all |
| PDF charts | Low | Chart rendering failures |
| Database migrations | Low | Schema upgrade failures |
| Concurrent access | None | Race conditions, data corruption |

### Recommended QA Plan for Launch

#### Phase 1: Critical Path Testing (Week 1)

1. **Upload → Analyze → View → Export** flow with 5 real SWS sessions
2. **Scoring validation:** Compare scores against manually assessed sessions
3. **PDF generation:** Verify on Windows 10/11 with each backend
4. **Empty state testing:** Fresh DB, no sessions, all pages load
5. **Error recovery:** Upload corrupt CSV, incomplete CSV, wrong format

#### Phase 2: Feature Testing (Week 2)

1. **All 90+ API endpoints** — automated test with Flask test client
2. **Development plan progress** — create, complete drills, verify percentage
3. **Weekend grouping** — create, add sessions, compare
4. **Cross-session comparison** — verify percentile calculations
5. **Batch re-analysis** — 1, 5, 10 sessions

#### Phase 3: Stress Testing (Week 3)

1. **Large session (100+ laps)** — verify memory + time
2. **Many sessions (500+)** — verify DB performance, listing speed
3. **Concurrent uploads (3 simultaneous)** — verify no DB corruption
4. **Long-running analysis** — verify timeout handling
5. **Disk full scenario** — verify graceful failure

#### Phase 4: User Acceptance (Week 3-4)

1. **5 beta testers** with real SWS sessions
2. **Feedback form** on each major feature
3. **Bug triage** — P0/P1/P2 classification
4. **Fix P0 bugs before launch**

### Automated Testing Infrastructure

```
pytest tests/ -v --tb=short
├── conftest.py          (shared fixtures)
├── test_scoring_*.py    (scoring edge cases)
├── test_pipeline_*.py   (end-to-end)
├── test_api_*.py        (all endpoints)
├── test_upload_*.py     (CSV parsing)
├── test_export_*.py     (PDF/HTML generation)
└── test_edge_cases.py   (corrupted data, empty data)
```

**Target: 300+ automated tests, >80% code coverage on critical paths**

---

# PROMPT 18 — Observability Strategy

## Current State

### Logging
- Python `logging` module used throughout
- Logger per module: `logger = logging.getLogger(__name__)`
- Pipeline stages log start/end/failure
- No structured logging (plain text format)
- No log aggregation or persistence beyond stdout

### Metrics
- **None.** No timing metrics, no counters, no gauges.

### Error Tracking
- `_safe_step()` wrapper logs errors but doesn't aggregate or alert
- Flask error handlers return generic 404/500 pages
- No error reporting service

### Health Checks
- `/_debug/template-info` endpoint exists (development-only)
- No formal health check endpoint

## Recommended Observability Stack (Appropriate for Solo/Small Team)

### Tier 1: Essential (Before Launch)

1. **Structured logging with file rotation:**
```python
import logging.handlers
handler = logging.handlers.RotatingFileHandler(
    'telemetry.log', maxBytes=10_000_000, backupCount=5
)
formatter = logging.Formatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s'
)
```

2. **Health check endpoint:**
```python
@app.route('/health')
def health():
    return {"status": "ok", "db_size_mb": ..., "session_count": ..., "uptime_s": ...}
```

3. **Pipeline timing:**
```python
# Already have _safe_step — add timing:
import time
start = time.perf_counter()
result = fn(*args, **kwargs)
elapsed = time.perf_counter() - start
logger.info("Step '%s' completed in %.2fs", label, elapsed)
```

4. **Error count dashboard:**
- Simple SQLite table: `error_log(timestamp, module, error_type, message)`
- API endpoint to query recent errors

### Tier 2: Post-Launch (Month 1)

1. **Simple analytics tracking:**
   - Sessions analyzed per day/week
   - Most used features (API hit counts)
   - Pipeline failure rate
   - Average analysis time

2. **User-facing status page:**
   - System health (green/yellow/red)
   - Last successful analysis timestamp
   - DB size and session count

### Tier 3: Scale Phase (Month 3+)

1. **If multi-user:** Sentry for error tracking, simple dashboard metrics
2. **If revenue growing:** Consider lightweight APM (no need for enterprise tools for a desktop app)

### Cost: $0 for Tier 1-2 (all local, no cloud services needed)

---

# PROMPT 19 — Security Review

## Threat Model for Desktop Telemetry App

### Attack Surface

| Vector | Risk Level | Notes |
|--------|-----------|-------|
| Local network access | Medium | Flask serves on localhost:5000 by default |
| CSV upload | Medium | Malicious CSV could cause memory exhaustion |
| SQLite injection | Low | Parameterized queries used throughout |
| File path traversal | Low | Path manager uses Path() for safety |
| XSS in templates | Medium | Jinja2 auto-escapes, but some `|safe` filters may exist |
| CSRF | Low | No authentication = no meaningful CSRF target |
| Dependency vulnerabilities | Medium | NumPy, Pandas, Flask — standard packages |

### Current Security Posture

**Authentication:** None. The app has no login, no users, no permissions. This is by design for a single-user desktop app.

**Input Validation:**
- CSV parsing has encoding fallbacks but no file size limit enforcement at parse level (MAX_CONTENT_LENGTH set in Flask config)
- Session type and track state are selected from dropdowns (not free text in most paths)
- API endpoints do basic type checking but no schema validation

**SQL Injection:**
- Parameterized queries used consistently in `db/queries.py`
- Some raw SQL in route handlers — should audit for string interpolation

**XSS:**
- Jinja2 auto-escaping enabled by default
- `session_detail.html` and other templates may use `|safe` filter for HTML content
- User-supplied notes fields rendered in templates

**File System:**
- Uploads restricted to `UPLOAD_DIR`
- Report files written to `RESULTS_DIR`
- Path manager handles PyInstaller frozen mode correctly

### Security Recommendations

**For desktop deployment (current model):**
1. Bind Flask to `127.0.0.1` only (already done) — not `0.0.0.0`
2. Add file size validation at upload endpoint (reject > 50MB)
3. Audit all `|safe` Jinja2 filters — remove or sanitize
4. Add rate limiting on analysis endpoint (prevent accidental rapid re-analysis)
5. Validate CSV structure before parsing (column count, expected headers)

**If moving to hosted/multi-user (future):**
1. Add authentication (OAuth2 or simple email/password)
2. Add per-user data isolation
3. Switch to HTTPS (Let's Encrypt)
4. Add CSRF tokens to all forms
5. Switch from SQLite to PostgreSQL
6. Add input validation middleware
7. Security headers (CSP, HSTS, X-Frame-Options)

### Dependency Audit

Run periodic `pip audit` to check for known vulnerabilities in:
- Flask, Werkzeug
- NumPy, Pandas, SciPy
- scikit-learn
- WeasyPrint/pdfkit

**Risk rating: LOW for desktop deployment, MEDIUM if exposed to network**

---

# PROMPT 20 — Distribution Model

## Current Distribution

### Desktop .exe (PyInstaller)

**Build process:**
```
pyinstaller telemetry_tool.spec --clean --noconfirm
→ dist/telemetry_tool/telemetry_tool.exe (single-directory bundle)
```

**Installer:**
- NSIS-based Windows installer (`installer/telemetry_installer.nsi`)
- Creates desktop shortcuts:
  - "Telemetry Analysis" → console/file-picker mode
  - "Telemetry Dashboard" → `--serve` flag, auto-opens browser
- Start menu group with both shortcuts + uninstaller
- Silent install support (`/S` flag)
- Uninstaller preserves user data (DB, CSVs, results)

**Distribution size:** ~150–200 MB (Python runtime + all dependencies bundled)

### Distribution Channels

| Channel | Effort | Reach | Cost |
|---------|--------|-------|------|
| Direct download (website) | Low | Medium | ~€10/mo hosting |
| GitHub Releases | Very Low | Low–Medium | Free |
| Discord/WhatsApp (SWS community) | Very Low | High for target market | Free |
| USB stick at track | Very Low | Very targeted | ~€5 per stick |
| Email to kart track mailing lists | Low | Medium | Free |

### Recommended Distribution Strategy

**Phase 1 (Launch):**
1. GitHub Releases page with .exe installer download
2. Simple landing page with download button
3. Direct outreach in SWS WhatsApp/Discord groups
4. Bring USB sticks to local SWS tracks

**Phase 2 (Growth):**
1. Simple website with download, docs, and support
2. YouTube video tutorial (setup + first analysis)
3. Partnership with 1–2 local SWS tracks for "official analysis tool" status

**Phase 3 (Scale):**
1. Consider web-hosted version (eliminates install friction)
2. Auto-update mechanism (check GitHub releases on startup)
3. App store listing (Windows Store is low-friction)

### Update Mechanism

**Current:** None. User must manually download new version.

**Recommended:** Add version check on startup:
```python
# On app start, check GitHub releases API
latest = requests.get('https://api.github.com/repos/.../releases/latest')
if latest['tag_name'] > current_version:
    show_update_notification()
```

---

# PROMPT 21 — Pricing & Packaging

## Target Market: SWS Rental Kart Drivers

### Market Characteristics

- **Customer profile:** Recreational kart racers at SWS (South West Simulator? / rental kart chain)
- **Price sensitivity:** HIGH — this is a hobby, not a business expense
- **Willingness to pay:** €5–15/month for analysis tools (based on comparable motorsport apps)
- **Market size:** Estimate 200–500 active SWS regulars who track with RaceChrono
- **Revenue target:** €1,000 in 2 months

### Pricing Models

#### Option A: Freemium + Premium (Recommended)

| Tier | Price | Features |
|------|-------|----------|
| **Free** | €0 | Upload + basic score + lap times + 5 sessions max |
| **Racer** | €9.99/mo | Unlimited sessions + coaching + development plans + PDF export |
| **Team** | €24.99/mo | Everything + 5 drivers + rival comparison + weekend analysis |

**Revenue math to hit €1k in 2 months:**
- Need ~50 Racer subscribers, or ~20 Team + 20 Racer
- With 200–500 target market, need 10–25% conversion → aggressive but achievable with strong product-market fit

#### Option B: One-Time Purchase

| Tier | Price | Features |
|------|-------|----------|
| **Starter** | €29 | Core analysis + scoring + basic coaching |
| **Pro** | €69 | Everything included, lifetime updates for 1 year |

**Revenue math:** Need ~15 Pro or ~35 Starter sales in 2 months. Lower barrier but no recurring revenue.

#### Option C: Pay-Per-Analysis

| Model | Price | Features |
|-------|-------|----------|
| **Single session** | €1.99 | Full analysis + report |
| **10-pack** | €14.99 | 10 sessions (€1.50 each) |
| **Unlimited monthly** | €9.99 | Unlimited for one month |

### Recommendation

**Go with Option A (Freemium + Premium)** because:
1. Free tier removes friction for trial
2. 5-session limit creates natural upgrade trigger (most SWS regulars do 2-4 sessions/week)
3. Monthly subscription creates recurring revenue
4. Team tier enables word-of-mouth within racing groups

### Implementation Requirements

For licensing/payment:
1. **Desktop app:** License key system (generate key → enter in app → unlock features)
2. **Payment:** Stripe Checkout for simple payment links (no complex integration)
3. **Feature gating:** Check license tier before premium features; graceful downgrade to free tier

**Estimated implementation: 2–3 days for basic license key system + Stripe checkout page**

---

# PROMPT 22 — Landing Page Content Specification

## Landing Page Structure

### Hero Section

```
HEADLINE: "Turn Your Lap Data Into Faster Laps"
SUBHEADLINE: "Professional telemetry analysis for rental kart racers.
             Upload your RaceChrono data, get instant coaching."

[CTA: Download Free →]  [CTA: See Demo →]

HERO IMAGE: Screenshot of session detail page with score + coaching panel
```

### Problem/Solution Section

```
"Every kart session generates data. Most of it goes to waste."

❌ You record sessions but never analyze them
❌ You know you're slow in some corners but don't know why
❌ You can't track your improvement over time
❌ Professional coaching is expensive

↓

✅ Automatic analysis of every session
✅ Corner-by-corner coaching with specific fix suggestions
✅ Progress tracking across weeks and months
✅ Development plans to guide your improvement
```

### Feature Highlights (3 columns)

```
📊 INSTANT ANALYSIS          🏎️ CORNER COACHING           📈 TRACK PROGRESS
Upload your CSV and get      See exactly where you're     Watch your scores improve
a full score breakdown       losing time and what to      session by session with
in under 30 seconds.         do about it.                 personalized development
                                                          plans.
```

### Social Proof Section

```
"Used by XX drivers at SWS tracks"

[Testimonial 1 — real user quote]
[Testimonial 2 — real user quote]
[Testimonial 3 — real user quote]
```

### Pricing Section

(From Prompt 21 — embedded pricing table)

### FAQ Section

```
Q: What data logger do I need?
A: RaceChrono Pro (Android/iOS). It uses your phone's GPS.

Q: Does it work for my track?
A: Yes! The system automatically detects any track from GPS data.

Q: Do I need to be connected to the internet?
A: No. The app runs entirely on your computer. Your data stays private.

Q: How accurate is the scoring?
A: Scoring uses physics-based models validated against professional
   karting data. It accounts for your specific track and conditions.
```

### CTA Footer

```
"Ready to go faster?"
[Download Free →]

Works on Windows 10/11. Mac support coming soon.
```

### Technical Requirements

- Single-page site (no framework needed — static HTML/CSS/JS)
- Hosting: GitHub Pages (free) or Netlify (free tier)
- Domain: ~€10/year for a .com
- Analytics: Simple Plausible or GoatCounter (privacy-friendly)
- Email capture: Simple form → Google Sheet or Mailchimp free tier

---

# PROMPT 23 — Launch Checklist

## Pre-Launch Checklist (3.5 weeks out)

### Week 1: Critical Fixes

- [ ] **Onboarding flow** — Welcome screen + upload wizard + progress bar
- [ ] **RaceChrono export guide** — Help page with step-by-step screenshots
- [ ] **Empty state pages** — Guidance when no data exists
- [ ] **Loading indicators** — Spinner during pipeline analysis
- [ ] **Error handling** — User-friendly error messages for common failures
- [ ] **Basic logging** — File-based log rotation + pipeline timing

### Week 2: Quality & Polish

- [ ] **Run full test suite** — All existing tests pass (200+)
- [ ] **Test with 5 real SWS sessions** — End-to-end validation
- [ ] **PDF export verification** — Test on Windows 10 and 11
- [ ] **Fix any P0 bugs** from testing
- [ ] **Navigation simplification** — Group nav into 5–6 items
- [ ] **Session detail tab grouping** — Reduce from 15+ to 4 sections
- [ ] **Build installer** — Clean Windows .exe with desktop shortcuts

### Week 3: Distribution & Marketing

- [ ] **Landing page** — Deploy to GitHub Pages / Netlify
- [ ] **GitHub Releases** — Upload installer with release notes
- [ ] **YouTube walkthrough video** — 5-minute setup + first analysis
- [ ] **RaceChrono export video** — 2-minute tutorial
- [ ] **SWS community outreach** — Post in WhatsApp/Discord groups
- [ ] **5 beta testers** — Real SWS drivers, collect feedback
- [ ] **License key system** — Basic free/premium feature gating
- [ ] **Stripe checkout** — Payment page for premium tier

### Week 3.5: Launch

- [ ] **Fix any P0 bugs from beta**
- [ ] **Update landing page with beta feedback/testimonials**
- [ ] **Announce in SWS communities**
- [ ] **Track: 3 USB sticks prepared for local track distribution**
- [ ] **Support channel** — Simple email or Discord server for bug reports

### Post-Launch (Week 1)

- [ ] Monitor error logs daily
- [ ] Respond to all support requests within 24 hours
- [ ] Track download count and conversion rate
- [ ] Collect and prioritize feature requests
- [ ] Push first bugfix release if needed

---

# PROMPT 24 — Post-Launch Roadmap

## 90-Day Roadmap

### Month 1: Stabilize & Convert (Weeks 1–4)

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| P0 | Bug fixes from launch feedback | Ongoing | Critical |
| P0 | Mobile-responsive session list + detail | 3 days | High — drivers check on phone at track |
| P1 | Auto-update check on startup | 1 day | Medium — reduces support burden |
| P1 | Guided first-session tour | 2 days | Medium — improves onboarding |
| P1 | Session comparison (head-to-head view) | 2 days | High — common user request |
| P2 | Weekend auto-detection | 1 day | Medium — removes manual grouping |

**Goal:** 50+ active users, 10+ paying subscribers, <5 P0 bugs open

### Month 2: Growth Features (Weeks 5–8)

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| P0 | Multi-driver comparison page | 3 days | High — competitive motivation |
| P1 | Season overview dashboard | 2 days | High — long-term engagement |
| P1 | Improved coaching (progress-aware) | 3 days | High — differentiator |
| P1 | Batch session upload (ZIP) | 1 day | Medium — convenience |
| P2 | Track records leaderboard (public) | 2 days | High — community feature |
| P2 | Simple team/group feature | 3 days | Medium — team endurance prep |

**Goal:** 100+ active users, 30+ paying subscribers, first testimonials

### Month 3: Scale & Differentiate (Weeks 9–12)

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| P1 | Cloud-hosted version (web app) | 2 weeks | High — eliminates install friction |
| P1 | RaceChrono direct integration (API) | 1 week | High — eliminates export step |
| P2 | Live timing display (websocket) | 1 week | Medium — event feature |
| P2 | Championship tracking | 3 days | Medium — league engagement |
| P2 | AI coaching (LLM integration) | 1 week | High — unique differentiator |

**Goal:** 200+ active users, 50+ paying subscribers, €1k+ monthly revenue

### Long-Term Vision (6–12 months)

1. **Multi-logger support** — AIM, MoTeC, OBD-II direct
2. **Real-time analysis** — Phone streams data, laptop shows live telemetry
3. **Marketplace** — Users can share track setups, coaching plans
4. **Pro team features** — Multi-driver comparison, team strategy tools
5. **Integration with kart rental booking** — Automatic session association

---

# PROMPT 25 — Risk Register

## Risk Register for Next 3.5 Weeks

| # | Risk | Probability | Impact | Severity | Mitigation |
|---|------|------------|--------|----------|------------|
| 1 | **RaceChrono CSV format changes** — New version breaks parser | Low | Critical | High | Pin to known RaceChrono version in docs; flexible column detection already handles most changes |
| 2 | **PyInstaller build fails on new Windows update** | Medium | High | High | Test build weekly; have fallback "run from Python" instructions |
| 3 | **Physics simulation gives unrealistic scores for SWS tracks** | Medium | High | High | Test with 5+ real SWS sessions before launch; add manual calibration option |
| 4 | **No users sign up in first week** | Medium | High | High | Have 5 beta testers pre-committed; prepare direct outreach to 20 SWS contacts |
| 5 | **PDF generation fails on user's Windows** | Medium | Medium | Medium | WeasyPrint fallback chain; add HTML-as-PDF fallback (print-to-PDF via browser) |
| 6 | **SQLite database corruption** | Low | Critical | Medium | Enable WAL mode; add automatic backup on startup; document manual recovery |
| 7 | **Memory exhaustion on large sessions** | Low | Medium | Low | Add session size warning; limit to 200 laps per session |
| 8 | **User uploads non-RaceChrono CSV** | High | Low | Medium | Add clear error message: "This doesn't look like a RaceChrono export" with format guide link |
| 9 | **Stripe payment integration issues** | Low | Medium | Medium | Test with real transactions; have manual license key backup |
| 10 | **Feature creep delays launch** | High | High | High | **Strict scope freeze after Week 1.** Only P0 bugs and the checklist items. Everything else goes to post-launch roadmap. |
| 11 | **SWS track corner detection inaccuracy** | Medium | Medium | Medium | Test corner detection on 3+ SWS track layouts; allow manual corner override |
| 12 | **Competitor launches similar product** | Low | Medium | Low | Focus on speed-to-market and community relationship; features are deep enough to differentiate |
| 13 | **User data loss (DB or CSV files)** | Low | Critical | Medium | Document backup strategy; installer preserves data on uninstall; add export-all feature |
| 14 | **Negative word-of-mouth from buggy beta** | Medium | High | High | Limit initial beta to 5 trusted users; fix all reported bugs before wider launch |
| 15 | **Developer burnout / time underestimate** | Medium | High | High | Focus on the critical path only; cut nice-to-haves ruthlessly; the product already has 68 features — it's enough for V1 |

## Top 5 Actions to Reduce Risk

1. **Test with real SWS data THIS WEEK** — Validate scoring, corners, and coaching on actual sessions (mitigates #3, #11)
2. **Recruit 5 beta testers NOW** — Reduces #4, #14; provides early feedback (mitigates #10)
3. **Scope freeze after Week 1** — Only critical path items; everything else is post-launch (mitigates #10, #15)
4. **Build and test installer on clean Windows VM** — Catches #2, #5 before they reach users
5. **Enable SQLite WAL + daily backup** — Prevents #6, reduces blast radius of #13

---

## Document Summary

| Prompt | Topic | Status | Key Finding |
|--------|-------|--------|-------------|
| 1 | System Map | ✅ | Monolith: Flask+SQLite, 17 blueprints, 14-stage pipeline |
| 2 | Feature Inventory | ✅ | 68 features across 88.6k lines — feature-complete for V1 |
| 3 | Data Pipeline | ✅ | 14 stages, graceful degradation, deterministic |
| 4 | Performance Baseline | ✅ | 7–22s per session, adequate for target market |
| 5 | Storage Model | ✅ | 3–13 MB per session, SQLite adequate for 1–2 years |
| 6 | Compute Model | ✅ | Single-threaded OK for desktop, parallelization available |
| 7 | CSV Spec | ✅ | RaceChrono Pro, 10 columns, encoding fallbacks |
| 8 | Lap Detection | ✅ | Relies on RaceChrono — add distance validation |
| 9 | Scoring | ✅ | 8/10 — sound architecture, minor improvements noted |
| 10 | Theoretical Lap | ✅ | 7/10 — two-tier approach, friction model accuracy risk |
| 11 | Coaching Engine | ✅ | 7 mistake types, static cues — add progress awareness |
| 12 | Weekend Analysis | ✅ | Basic grouping — add auto-detection, progression charts |
| 13 | Endurance Mode | ✅ | 8/10 — strong stint analysis, add driver swap detection |
| 14 | UX Audit | ✅ | Nav overload, no loading states, no mobile — fix for launch |
| 15 | Onboarding | ✅ | Missing entirely — ~18 hours to implement full flow |
| 16 | PDF Export | ✅ | 3-tier fallback works, chart rendering fragile |
| 17 | QA Plan | ✅ | ~200 tests exist, need 300+ and real-data validation |
| 18 | Observability | ✅ | None today — add structured logging + health endpoint |
| 19 | Security | ✅ | LOW risk for desktop; adequate for V1 launch |
| 20 | Distribution | ✅ | PyInstaller .exe + NSIS installer + GitHub Releases |
| 21 | Pricing | ✅ | Freemium recommended: Free/€9.99/€24.99 monthly |
| 22 | Landing Page | ✅ | Static site spec ready — GitHub Pages deployment |
| 23 | Launch Checklist | ✅ | 3.5-week plan with weekly milestones |
| 24 | Roadmap | ✅ | 90-day plan: Stabilize → Grow → Scale |
| 25 | Risk Register | ✅ | 15 risks identified, top 5 mitigations prioritized |

---

*Generated by comprehensive codebase analysis of 88,607 lines across ~100 modules.*
*Audit date: February 2026*
