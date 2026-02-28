# E2E Certification Harness — Design Document

**Date**: 2026-02-28
**Branch**: `recovery/e2e-certification`
**Status**: Approved

## Problem

The production SaaS (selling website + webapp) needs rigorous end-to-end certification across:
- Feature parity with the legacy CLI tool (same pipeline code, different execution context)
- Tier-based access control (demo / racer / world_class) enforced backend-side
- Multi-tenant isolation (RLS + API-level IDOR prevention)
- Telemetry processing correctness and determinism
- Auth/session hardening
- Security posture

The certification must produce a PDF audit report with 250+ granular cycle entries.

## Architecture

### Parity Model

The "old tool" (CLI: `python telemetry_tool/main.py <csv>`) and the webapp (Flask + Celery + PG + Next.js) share the same pipeline code (`telemetry_tool/pipeline.py`). Parity means verifying that the web execution path (async, streaming INGEST_V2, PostgreSQL storage) produces identical numerical results to the CLI path (synchronous, direct file I/O, SQLite storage).

### Directory Layout

```
audit/                           # Top-level audit artifacts
├── cycles/                      # CYCLE-0001.md … CYCLE-0250+.md
├── baselines/
│   └── old_tool/               # CLI baseline outputs
│       ├── OK_R1.json          # Normalized session_summary
│       ├── OK_R3.json
│       └── OK_R4.json
├── screenshots/                 # Playwright failure screenshots
├── logs/
│   ├── parity-diffs/           # Per-run parity diff files
│   └── test-runs/              # Test execution logs
├── feature-inventory.md         # 250+ feature inventory
├── report.md                    # Running cycle log
├── report.pdf                   # Auto-generated PDF
├── security-findings.md         # Security audit findings
├── fixes-applied.md             # Applied fixes log
└── risks.md                     # Documented divergences + risks

tools/
├── old_tool_runner.py           # Runs CLI pipeline, captures outputs
├── parity_check.py              # Compares webapp vs CLI outputs
├── normalize.py                 # Normalization rules for comparison
├── cycle_runner.py              # Orchestrates cycle workflow
├── generate_report_pdf.py       # MD → PDF converter
├── batch_configs/
│   ├── OK_R1.json              # Deterministic batch config
│   ├── OK_R3.json
│   └── OK_R4.json
└── README.md
```

### Test Accounts

| Email | Tier | Purpose |
|-------|------|---------|
| theos.elive@gmail.com | demo | Verify free-tier limits + gate enforcement |
| theo.stipapro@gmail.com | racer | Verify mid-tier feature access |
| fsae.ecn@gmail.com | world_class | Verify full access + comparison features |

### Baseline Generation

1. Run CLI pipeline on OK_R1, OK_R3, OK_R4 with fixed batch configs
2. Capture `session_summary.json`, `corner_table.csv`, `delta_map.csv`
3. Normalize outputs (4 decimal float rounding, sorted keys, NaN→null)
4. Store in `audit/baselines/old_tool/`

### Normalization Rules

| Type | Rule |
|------|------|
| Floats | Round to 4 decimal places |
| Timestamps | Strip to second precision |
| NaN/Inf | Convert to `null` |
| Dict keys | Sort alphabetically |
| Lists | Preserve order |
| Channel names | Map via canonical name table |

### Parity Tolerances

| Metric | Tolerance |
|--------|-----------|
| Lap times | ±0.001s |
| Speeds | ±0.01 m/s |
| Scores | ±0.5 points |
| GPS coordinates | ±0.0001° |
| Percentages | ±0.1% |

### Test Layers

**Layer A — Unit tests** (pytest): Pure functions — CSV parsing, derived channels, scoring math. Extend existing 134 test files.

**Layer B — Integration tests** (pytest): API auth flows, upload pipeline, RBAC gates, tier enforcement, tenant isolation via API.

**Layer C — E2E tests** (Playwright): Selling site flows, webapp workflows, tier gating UI, cross-tenant URL access.

### Multi-Tenant Isolation Test

1. Login as user A, upload CSV, note session/resource IDs
2. Login as user B, attempt access to A's resources via:
   - Direct URL navigation
   - Direct API calls with guessed IDs
   - List endpoints (verify absence)
3. Assert 403/404 for all cross-tenant attempts

### Feature Inventory

250+ entries across areas:
- Auth (20): registration, login, OAuth, refresh, logout, email verify
- Upload/Ingest (15): CSV upload, streaming, progress, resume, validation
- Processing/Pipeline (40): each pipeline stage, derived channels, scoring
- Charts/Visualization (30): speed traces, G-G diagrams, delta heatmaps
- Exports (10): CSV, PDF, JSON exports
- Billing (15): plans, checkout, webhooks, tier changes
- Account (10): profile, security settings, data privacy
- Admin (10): admin panel, audit logs, user management
- RBAC (20): per-tier feature gates, API enforcement
- Isolation (15): cross-tenant IDOR, RLS, storage access
- Selling Site (25): pages, CTAs, pricing, signup flow
- Old-Tool Parity (30): per-stage pipeline output comparison
- Security (10): headers, CORS, CSRF, rate limiting

### Cycle Workflow

Each cycle:
1. Pick next pending feature from inventory
2. Create `audit/cycles/CYCLE-NNNN.md`
3. Run relevant tests
4. Fix if needed (root cause only)
5. Update inventory status
6. Append to report.md
7. Generate report.pdf
8. Commit + push
9. Deploy to production
10. Post-deploy smoke test

### PDF Generation

Python `markdown` + `weasyprint` (already available) to convert `audit/report.md` → `audit/report.pdf`.

## Deployment Model

Every cycle: commit → push → `scripts/deploy.sh` → post-deploy smoke → next cycle.

## Completion Criteria

- 250+ cycles logged
- 100% feature inventory validated
- E2E suite passes reliably
- RBAC enforced backend-side for all gated features
- No cross-tenant leakage verified by tests
- Telemetry parity achieved for key outputs
- report.pdf generated with full cycle log and sign-off checklist
