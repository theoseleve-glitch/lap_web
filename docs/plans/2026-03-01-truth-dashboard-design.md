# Audit Truth Dashboard — Design

> **For Claude:** This is a single self-contained HTML file. Implementation is straightforward.

**Goal:** Standalone HTML dashboard that live-probes the SaaS API to verify whether 6 audit conflict points from Report 1 are resolved.

**Architecture:** Single `docs/audit-truth-dashboard.html` file with inline JS + CSS. Opens in any browser. Hits SaaS endpoints via fetch(). No build step, no dependencies.

**Location:** `docs/audit-truth-dashboard.html` (dev-only, not deployed)

---

## Conflict Points & Probes

| # | Conflict | API Probe | Pass Condition |
|---|----------|-----------|----------------|
| 1 | Session identity wrong | `GET /sessions/{id}` | `csv_filename` ≠ full path, `driver_name` present, `track_name` ≠ "Unknown Track", `session_date` present |
| 2 | Visualize renders blank | `GET /sessions/{id}/speed-trace?lap=1` + `GET /sessions/{id}/gps-trace?lap=1` | Both `available: true` with non-empty data |
| 3 | Timeline tab missing | `GET /sessions/{id}/lap-progress` + `GET /sessions/{id}/stint-analysis` | Both return 200 with data |
| 4 | Analytics tab missing | `GET /sessions/{id}/sectors` + `GET /sessions/{id}/gg-data?lap=1` + `GET /sessions/{id}/scores` | All return `available: true` |
| 5 | Corners/coaching missing | `GET /sessions/{id}/corners` | `available: true`, non-empty array, at least one has `coaching` text |
| 6 | CSP violations | Inspect `connect-src` in CSP header | Contains necessary domains for Leaflet/OSM tiles |

## Card States

- **PASS** (green) — Probe confirms conflict is resolved
- **FAIL** (red) — Conflict still exists, evidence shown
- **SKIP** (yellow) — Couldn't run (no session, network error)

## UI

- Dark theme (asphalt/steel/acid-green matching app)
- Top form: API URL + Session ID + JWT (optional) + Run button
- Summary bar: X/6 PASS, Y/6 FAIL, Z/6 SKIP
- 6 expandable cards with probe evidence
- Each card: conflict description, reproduction steps, success condition, probe result
