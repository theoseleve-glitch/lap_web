# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Motorsport telemetry analysis platform — Python 3.x with Flask web dashboard, PyInstaller-bundled .exe, SQLite persistence, and Parquet for ML features. Ingests RaceChrono/RaceBox CSV files from kart and car sessions.

## Commands

```bash
# Run all telemetry_tool tests
pytest telemetry_tool/tests/

# Run a single test file
pytest telemetry_tool/tests/test_streaming_ingest.py

# Run a single test by name
pytest telemetry_tool/tests/test_streaming_ingest.py -k "test_chunk_cache_flush"

# Run kart_envelope tests
pytest kart_envelope/tests/

# Launch Flask web dashboard (localhost:5000)
python telemetry_tool/main.py --serve

# Process a single CSV via CLI
python telemetry_tool/main.py data/raw/SESSION.csv

# Run kart envelope analysis
python -m kart_envelope analyze <csv> --metadata <meta.json>

# Build .exe with PyInstaller
pyinstaller telemetry_tool.spec --clean --noconfirm

# Run ingest benchmark
python benchmarks/bench_ingest.py
```

No linter configuration exists. No `pyproject.toml` or `Makefile`. Dependencies: `pip install -r requirements.txt`.

## Architecture

### Two Parallel Pipelines

**Pipeline A: `telemetry_tool/pipeline.py`** — 14-stage orchestrator (2,400+ lines)
```
CSV → GPS Filter → Derived Channels → Session Trim → Track Detection
→ Corner Detection → Resampling → Features → Reference Line
→ Physics Models → Theoretical Lap → ML/Anomaly → Scoring → Reports
```

**Pipeline B: `kart_envelope/pipeline.py`** — 18-step orchestrator
```
CSV → Normalize → Clean → Track Detection → Lap Split → Outlier Filter
→ Resample → Envelope Training → Min-Time Solve → Record Calibrate
→ Delta Map → Corner Coaching → Cause Ranking → Output
```

Both use a `_safe_step()` wrapper pattern: each step that fails is logged and skipped so downstream steps receive the best partial result.

### Entry Points

| Mode | Command | Code |
|------|---------|------|
| Desktop .exe | double-click | `telemetry_tool/main.py` → Tkinter file picker |
| CLI | `python telemetry_tool/main.py <csv>` | same file, argparse |
| Web dashboard | `--serve` flag | `telemetry_tool/web/app.py` `create_app()` factory |
| Kart envelope | `python -m kart_envelope analyze` | `kart_envelope/cli.py` |

### Flask App Structure

- `web/app.py` — Factory with 17 blueprints, resolves template/static paths for both dev and PyInstaller
- `web/routes/` — 17 blueprints: `dashboard`, `sessions`, `tracks`, `analysis`, `api_data`, `drivers`, `comparisons`, `leaderboard`, `visualize`, `data_health`, `weekends`, `analytics`, `annotations_routes`, `dashboards`, `dev_plans`, `exports`, `predictions`
- `web/templates/` — 34+ Jinja2 templates
- `web/static/` — Vanilla JS + CSS (no npm/node). Chart.js via CDN. Canvas 2D rendering. Single dark-theme `main.css`

### Persistence

- **SQLite** (`telemetry.db`) — v15 schema (`db/schema.py`), ~30 tables across 11 phases. Migrations via `db/migrate.py` `ensure_schema()` (idempotent `CREATE TABLE IF NOT EXISTS`)
- **Parquet** — ML feature datasets managed by `parquet_manager.py` with file locking and dedup
- **JSON blobs** — GPS traces, scores, style features stored in SQLite TEXT columns

### INGEST_V2 Streaming Pipeline

The streaming ingest system in `telemetry_tool/ingest/` handles 10GB+ files with <1GB peak memory:

- **Feature flag**: `TELEMETRY_INGEST_V2` env var, default ON. Set `=0` for legacy `io_racechrono` path
- **Modules**: `config.py` (flag + IngestionConfig), `streaming.py` (chunked reader), `cache.py` (Parquet chunk cache + resume + merge via PyArrow), `pool.py` (bounded WriteQueue), `checksum.py` (SHA-256), `progress.py` (callbacks)
- **Routing**: `io_racechrono.py` checks the flag at the top of `read_racechrono_csv()` and routes accordingly
- **Web integration**: `web/routes/ingest.py` — SSE + polling with `JobStore` (dual-write: in-memory + SQLite)
- **Key invariant**: `flush_chunk()` is idempotent (index-based), `merge_chunks()` uses PyArrow streaming writer (O(1 chunk) memory, not `pd.concat`)

### Scoring System

`scoring.py` (2,700 lines) computes session scores across four dimensions: Pace, Consistency, Execution, Robustness. Each scored out of 25 for a 100-point total with letter grades.

## Key Conventions

- **Column names**: RaceChrono headers like `"Lap #"`, `"Time (s)"`, `"Speed (m/s)"` preserved through pipeline; snake_case mapping happens at theoretical engine / feature schema boundary
- **Import paths**: Both `telemetry_tool/tests/conftest.py` and `kart_envelope/tests/conftest.py` add the project root to `sys.path` — no package install required
- **PyInstaller awareness**: `web/app.py` and `web/config.py` handle `sys._MEIPASS` for frozen builds; `path_manager.py` resolves base directory differently when frozen
- **Graceful degradation**: Pipeline steps never crash the pipeline. `_safe_step()` catches exceptions, logs them, and returns `None`
- **In-place coercion**: Streaming pipeline does numeric coercion in-place (no `.copy()`) to stay within memory budget

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEMETRY_INGEST_V2` | `"1"` (ON) | Streaming ingest feature flag |
| `TELEMETRY_DB_PATH` | `telemetry.db` | SQLite database location |
| `TELEMETRY_SECRET_KEY` | `"telemetry-local-dev-key"` | Flask secret key |
| `TELEMETRY_HOST` | `"127.0.0.1"` | Flask bind address |
| `TELEMETRY_PORT` | `"5000"` | Flask port |
| `TELEMETRY_DEBUG` | `"0"` | Flask debug mode |

## Test Fixtures

- `test_db` — In-memory SQLite with full schema via `ensure_schema()`
- `seeded_db` — Adds sample driver, track, two sessions with laps and score details
- `synthetic_oval_laps` (kart_envelope) — Physics-realistic 500m oval with 3 laps, curvature, speed, accel
- `known_envelope` / `oval_geometry` — Pre-built capability envelope and track geometry for solver tests
