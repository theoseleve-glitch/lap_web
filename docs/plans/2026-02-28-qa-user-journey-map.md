# QA User Journey & Feature Parity Map

**Agent C — QA Strike Team**
**Date**: 2026-02-28
**Scope**: Feature parity audit between old Jinja2 tool and new Next.js SaaS frontend

---

## Section 1: Feature Parity Matrix (Old vs New)

### 1.1 Session Analysis Features

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Session overview with metadata | `templates/session_detail.html` — meta-grid with date, driver, track, type, condition, kart, grade | `app/sessions/[id]/page.tsx` — StatCard grid with same fields | **PARITY** | Both show driver, track, date, type, condition, kart, grade, score |
| Inline session editing (date, driver, track, type, condition, notes) | `session_editor.js` — debounced auto-save on blur via AJAX POST to `/sessions/<id>/edit` | `app/sessions/[id]/page.tsx` — no inline editing visible | **MISSING** | Old tool had 8 inline-editable fields with auto-save; new tool is read-only |
| Session delete | `session_list.html` — context menu + batch delete via `DELETE /api/session/<id>` | Not found in session detail or session list | **MISSING** | Old tool had single delete, batch delete, and right-click context menu |
| Score breakdown (Pace/Consistency/Execution/Robustness) | `session_detail.html` — score bars with color coding per subcategory | `app/sessions/[id]/page.tsx` — `ScoreBar` component with same 4 categories | **PARITY** | Both show /25 sub-scores with progress bars |
| Letter grade display | `session_detail.html` — colored grade badge (S/A/B/C/D) | `app/sessions/[id]/page.tsx` — `gradeColor()` helper with colored badge | **PARITY** | |
| Speed trace (speed vs distance) | `chart_sync.js` — Canvas chart with color gradient, theoretical envelope overlay | `SpeedTrace.tsx` component imported in session detail | **PARITY** | Both have speed-distance chart; need to verify theoretical overlay in new |
| Lap times bar chart | `chart_sync.js` — bar chart with best lap highlight, mean line, invalid lap cross-hatch, hover tooltip with delta-vs-best | `LapProgress.tsx` component | **PARITY** | Both show lap time bars |
| G-G diagram | `gg_diagram.js` — density-colored scatter, friction circle envelope, zoom/pan, keyboard navigation, quadrant labels | `GGDiagram.tsx` component | **PARITY** | Old had zoom/pan/keyboard; verify new tool matches interaction depth |
| Track map with speed coloring | `track_map.js` — Canvas-based, multi-lap overlay, corner labels, speed legend, S/F marker | `TrackMap.tsx` component | **PARITY** | Both render track with speed-colored lines |
| Bidirectional chart-map hover sync | `chart_sync.js` + `track_map.js` — chart hover updates map marker, map hover updates chart crosshair | Need to verify in `SpeedTrace.tsx` + `TrackMap.tsx` | **UNKNOWN** | Old tool had tight bidirectional sync; critical UX feature to verify |
| Corner coaching table | `session_detail.html` — per-corner entry/apex/exit speeds, time loss, coaching hints, best-practice reference | `app/sessions/[id]/page.tsx` — CornerCoachingEntry interface + coaching tab | **PARITY** | Both show corner-by-corner coaching data |
| Corner detail page | Not a separate page; coaching was inline | `app/sessions/[id]/corners/[cornerId]/page.tsx` — dedicated corner detail | **ENHANCED** | New tool adds a dedicated corner detail page (improvement) |
| Corner replay (animated playback) | `corner_replay.js` + `corner_replay_map.js` + `corner_replay_cockpit.js` + `corner_replay_controls.js` — review/split/top3 modes, playback speed control, cockpit gauges | `CornerReplay.tsx` + `CornerReplayMap.tsx` + `CornerReplayCockpit.tsx` + `CornerReplayControls.tsx` | **PARITY** | Both have animated corner replay with cockpit view |
| Speed trace zoom (drag-to-select) | `speed_trace_zoom.js` — drag selection on overview, zoomed detail canvas, multi-lap comparison, corner-click auto-zoom | Need to verify in `SpeedTrace.tsx` | **UNKNOWN** | Old tool had premium drag-to-zoom with lap comparison |
| Lap selector (dropdown + "show all" toggle) | `session_detail.html` — `#lap-select` dropdown + `#toggle-all-laps` checkbox | `app/sessions/[id]/page.tsx` — lap selector state management | **PARITY** | |
| Driving style radar chart | `progression.js` — radar chart with 9 axes (trail braking, brake consistency, etc.) | `DrivingStyle.tsx` component | **PARITY** | |
| Session badges & tags | `session_badges.js` — badges earned during session + auto-generated tags | `app/sessions/[id]/page.tsx` — `BadgesData` interface with badges + tags | **PARITY** | |
| Focus mode (split pane) | `focus_mode.js` + `focus_tools.js` + `split_pane.js` — immersive analysis with tool dock | `FocusMode.tsx` + `SplitPane.tsx` + `ToolDock.tsx` | **PARITY** | |
| Brake scatter plot | `brake_scatter.js` — scatter of brake points per corner | `BrakeScatter.tsx` | **PARITY** | |
| Consistency heatmap | `consistency_heatmap.js` — lap-to-lap consistency visualization | `ConsistencyHeatmap.tsx` | **PARITY** | |
| Throttle heatmap | `throttle_heatmap.js` — throttle application visualization | `ThrottleHeatmap.tsx` | **PARITY** | |
| Sector chart | `sector_chart.js` | `SectorChart.tsx` | **PARITY** | |
| Lap distribution | `lap_distribution.js` | `LapDistribution.tsx` | **PARITY** | |
| Lap overlay | `lap_overlay.js` | `LapOverlay.tsx` | **PARITY** | |
| Fingerprint chart | `fingerprint_chart.js` | `Fingerprint.tsx` | **PARITY** | |
| Energy balance | `energy_balance.js` | `EnergyBalance.tsx` | **PARITY** | |
| Fatigue chart | `fatigue_chart.js` | `FatigueChart.tsx` | **PARITY** | |
| Speed profile | `speed_profile.js` | `SpeedProfile.tsx` | **PARITY** | |
| Workload chart | `workload_chart.js` | `WorkloadChart.tsx` | **PARITY** | |
| Tyre chart | `tyre_chart.js` | `TyreChart.tsx` | **PARITY** | |
| Weather chart | `weather_chart.js` | `WeatherChart.tsx` | **PARITY** | |
| Stint chart | `stint_chart.js` | `StintChart.tsx` | **PARITY** | |
| Trend chart | `trend_chart.js` | `TrendChart.tsx` | **PARITY** | |
| Rival chart | `rival_chart.js` | `RivalChart.tsx` | **PARITY** | |
| Pit window chart | `pit_window_chart.js` | `PitWindowChart.tsx` | **PARITY** | |
| Comparison matrix | `comparison_matrix.js` | `ComparisonMatrix.tsx` | **PARITY** | |
| Condition phase detection display | Not present | `app/sessions/[id]/page.tsx` — `ConditionPhase` interface | **ENHANCED** | New feature in Next.js |
| Data health display (per-session) | `data_health_detail.html` — GPS quality, accel quality, channels, gaps | `app/sessions/[id]/page.tsx` — `data_health` object in session detail | **PARITY** | |
| Theoretical lap comparison | `chart_sync.js` — dashed gold line on speed trace | `app/sessions/[id]/page.tsx` — `TheoreticalData` interface | **PARITY** | |
| HTML report link | `session_detail.html` — "View Full Report" button linking to generated HTML | Not found in new tool | **MISSING** | Old tool generated standalone HTML reports; this link is gone |

### 1.2 Upload & Analysis

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| 3-step analysis wizard | `analyze.html` — wizard steps (Select Data > Configure > Analyze) | `app/analyze/page.tsx` — identical 3-step wizard | **PARITY** | |
| File browser (list server files) | `analyze.html` — `/api/files/list` populates file list | `app/analyze/page.tsx` — `api.get('/files')` query | **PARITY** | |
| CSV upload with drag-drop | `analyze.html` — `#file-drop` div + `#csv-upload` input | `app/analyze/page.tsx` — `onDragOver/onDrop` + file input | **PARITY** | |
| Upload progress bar | `analyze.html` — `#upload-progress-fill` | `app/analyze/page.tsx` — progress bar div | **PARITY** | |
| Session type selection | `analyze.html` — 7 types (practice/qualifying/race/warmup/sprint/endurance/test) | `app/analyze/page.tsx` — 4 types (Practice/Qualifying/Race/Test) | **PARTIAL** | Missing: warmup, sprint, endurance session types |
| Track conditions (dry/wet/damp/mixed/etc.) | `analyze.html` — 10 condition pills | `app/analyze/page.tsx` — not present | **MISSING** | Old tool had rich condition tagging; new tool omits it |
| Driver selection with "New Driver" | `analyze.html` — dropdown + "+ New Driver" option + name input | `app/analyze/page.tsx` — dropdown only (no create-new inline) | **PARTIAL** | Can select existing but cannot create new driver inline |
| Track selection with predefined tracks | `analyze.html` — dropdown + "+ New Track" + predefined track search | `app/analyze/page.tsx` — dropdown only | **PARTIAL** | No predefined track database or inline create |
| Kart model selection | `analyze.html` — dropdown with specs display | `app/analyze/page.tsx` — dropdown only | **PARTIAL** | No specs preview in new tool |
| Endurance stints configuration | `analyze.html` — `#endurance-stints-group` with per-stint driver/laps/conditions | `app/analyze/page.tsx` — not present | **MISSING** | Endurance mode removed entirely |
| Lap range filter | `analyze.html` — start/end lap inputs | `app/analyze/page.tsx` — not present | **MISSING** | |
| Joker lap detection toggle | `analyze.html` — `#enable-joker` checkbox | `app/analyze/page.tsx` — not present | **MISSING** | |
| Corner picker (interactive) | `analyze.html` + `corner_picker_map.js` — canvas-based corner point selection | `app/analyze/page.tsx` — not present | **MISSING** | Interactive corner selection for new tracks is gone |
| Joker lap confirmation dialog | `analyze.html` — `#joker-confirm-panel` with lap comparison table | `app/analyze/page.tsx` — not present | **MISSING** | |
| Pipeline stage progress (8 named stages) | `analyze.html` — stage dots with labels (Loading CSV, Detecting laps, etc.) | `app/analyze/page.tsx` — single progress bar + message | **PARTIAL** | Old showed 8 distinct stages; new shows generic progress |
| Elapsed time counter | `analyze.html` — `#analysis-elapsed` | `app/analyze/page.tsx` — not present | **MISSING** | |
| Session type report hint | `analyze.html` — `#session-type-hint` explaining report focus per type | `app/analyze/page.tsx` — not present | **MISSING** | |

### 1.3 Dashboard

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Stats cards (sessions, drivers, tracks, laps, best/avg score) | `dashboard.html` — 6 stat cards with animated tick-up | `app/dashboard/page.tsx` — 7 StatCards | **PARITY** | New adds Personal Best card |
| Empty state onboarding | `dashboard.html` — welcome hero + how-it-works steps + feature hints | `app/dashboard/page.tsx` — similar welcome hero + how-it-works + feature cards | **PARITY** | |
| Score trend sparkline | `dashboard.html` — Canvas chart via `dashboard_charts.js` | `app/dashboard/page.tsx` — `Sparkline` component | **PARITY** | |
| Best lap times trend | `dashboard.html` — Canvas chart | `app/dashboard/page.tsx` — `Sparkline` component | **PARITY** | |
| Recent sessions table | `dashboard.html` — clickable rows with date/driver/track/type/laps/best/score/grade | `app/dashboard/page.tsx` — `DataTable` with same columns | **PARITY** | |
| Custom dashboard builder | `custom_dashboard.html` — user-configurable dashboard layouts | Not present in new tool | **MISSING** | Entire feature removed |

### 1.4 Session List

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Session table with sorting | `session_list.html` — sortable columns (date, driver, track, type, condition, laps, best, mean, score, grade) | `app/sessions/page.tsx` — need to verify | **UNKNOWN** | Old had client-side column sorting |
| Batch select-all checkbox | `session_list.html` — `#select-all-sessions` | Not found | **MISSING** | |
| Batch re-analyze | `session_list.html` — `#batch-reanalyze-btn` → POST `/api/batch-reanalyze` | Not found | **MISSING** | |
| Batch delete | `session_list.html` — `#batch-delete-btn` | Not found | **MISSING** | |
| Right-click context menu | `context_menu.js` — Open Session, Open in Visualize, Copy Session ID, Delete Session | Not found | **MISSING** | Premium UX pattern lost |
| Pagination | `session_list.html` — page-based pagination | `app/sessions/page.tsx` — need to verify | **UNKNOWN** | |
| Mean lap time column | `session_list.html` — shown in table | Need to verify | **UNKNOWN** | |
| Track condition column | `session_list.html` — condition badge | Need to verify | **UNKNOWN** | |

### 1.5 Comparison

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Compare hub (session + driver) | `compare.html` — two side-by-side forms | `app/compare/page.tsx` — two card links | **PARITY** | |
| Session comparison detail | `compare_sessions.html` — side-by-side metadata, score bars, driving style, delta box, speed overlay, lap times chart | `app/compare/sessions/page.tsx` | **PARITY** | Both have session selection and comparison |
| Driver head-to-head | `compare_drivers.html` — scoreboard header (wins tally), h2h scorecard rows, verdict, score progression overlay | `app/compare/drivers/page.tsx` | **PARITY** | |
| Speed overlay (best laps) | `compare_sessions.html` + `comparison.js` — speed-vs-distance overlay with A/B coloring | Need to verify in compare sessions page | **UNKNOWN** | |
| Best lap delta calculation | `compare_sessions.html` — delta box with trophy icon, mean delta | Need to verify | **UNKNOWN** | |
| Score delta calculation | `compare_sessions.html` — score delta box | Need to verify | **UNKNOWN** | |
| Entitlement gating | Not present (all features free) | `app/compare/page.tsx` — `useEntitlements` + `UpgradeBanner` | **ENHANCED** | New tool gates comparison behind World-Class plan |

### 1.6 Driver Management

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Driver list | `driver_list.html` | `app/drivers/page.tsx` | **PARITY** | |
| Driver profile with stats | `driver_profile.html` — total sessions, laps, peak performance, pace delta, consistency rating, aggression index | `app/drivers/[id]/page.tsx` | **PARITY** | |
| Editable driver fields (weight, kart class, experience, email, phone, ID code, goals, notes) | `driver_profile.html` + `driver_editor.js` — 8 editable fields with debounced auto-save | Need to verify in driver detail | **UNKNOWN** | Old had rich profile editor |
| Earned badges display | `driver_profile.html` — badges grid with medal icons | Need to verify | **UNKNOWN** | |
| Track records held | `driver_profile.html` — list of records | Need to verify | **UNKNOWN** | |
| Driving style radar | `driver_profile.html` + `progression.js` — 9-axis radar | Need to verify | **UNKNOWN** | |
| Strengths & weaknesses | `driver_profile.html` — insight boxes | Need to verify | **UNKNOWN** | |
| Progression charts (lap time + score) | `driver_profile.html` + `progression.js` — two Canvas charts | `app/drivers/[id]/progression/page.tsx` — dedicated page | **PARITY** | Moved to sub-route |
| Session history table | `driver_profile.html` — full session table | Need to verify | **UNKNOWN** | |
| Delete driver | `driver_profile.html` — danger zone with confirmation | Need to verify | **MISSING** | |

### 1.7 Track Management

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Track list | `track_list.html` | `app/tracks/page.tsx` | **PARITY** | |
| Track detail with metadata | `track_detail.html` — lap length, known laps, S/F coordinates | `app/tracks/[id]/page.tsx` | **PARITY** | |
| Rename track | `track_detail.html` — inline rename form | Need to verify | **UNKNOWN** | |
| Reference lines (dry/wet) | `track_detail.html` — reference session links | Need to verify | **UNKNOWN** | |
| Joker lap settings | `track_detail.html` — toggle + distance/time delta inputs | Not present | **MISSING** | |
| Interactive Leaflet map with draggable S/F marker | `track_detail.html` — Leaflet map, drag S/F, save position | Need to verify | **UNKNOWN** | Old used Leaflet; new likely uses Canvas |
| Sector management (add/remove via map click) | `track_detail.html` — click map to add sector, delete button per sector | Need to verify | **UNKNOWN** | |
| Track records podium | `track_detail.html` — top-3 podium display, full records table, add/remove records | Need to verify | **UNKNOWN** | |
| Lap time evolution chart | `track_detail.html` + `track_evolution.js` | `app/tracks/[id]/evolution/page.tsx` — dedicated page | **PARITY** | |
| Delete track | `track_detail.html` — danger zone with confirmation | Need to verify | **MISSING** | |

### 1.8 Analytics & Predictions

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Analytics index | `analytics_index.html` | `app/analytics/page.tsx` | **PARITY** | |
| Pace trend analysis | `trend_analysis.html` — driver/track filter, improvement rates, plateau detection | `app/analytics/trends/page.tsx` | **PARITY** | |
| Pace predictor | (via analytics routes) | `app/analytics/pace-predictor/page.tsx` | **PARITY** | |
| Weight simulator | `weight_simulator.html` — baseline params, phase breakdown, multi-scenario comparison, coaching hint | `app/analytics/weight-simulator/page.tsx` | **PARITY** | |
| What-if simulator | `what_if.html` — per-corner speed adjustment sliders, simulation API | Not present as separate page | **MISSING** | Linked from session detail in old tool |
| Meteo dashboard | `meteo_dashboard.html` | `app/analytics/meteo/page.tsx` | **PARITY** | |
| Weather analysis | `weather_analysis.html` | `app/analytics/weather/page.tsx` | **PARITY** | |
| Rival comparison | `rival_comparison.html` — multi-driver corner-by-corner comparison | Not a separate page | **MISSING** | Was a distinct analytics tool in old |
| Cross-session analysis | `cross_session.js` | Not present | **MISSING** | |
| Setup tracker (correlation) | `setup_tracker.html` — driver/track filter, setup-performance correlations | `app/setup-tracker/page.tsx` | **PARITY** | |

### 1.9 Visualization & Export

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Visualization mode (full screen) | `visualize.html` — sidebar with lap list, sector times, stats; main with GPS map, speed chart, G-G diagram | `app/visualize/[id]/page.tsx` | **PARITY** | |
| Visualize session list | Not present | `app/visualize/page.tsx` | **ENHANCED** | New adds a list view |
| Export builder (section select + format) | `export_builder.html` — checkbox sections, Markdown format, preview + copy | `app/exports/page.tsx` | **PARITY** | |
| Annotation system | `annotations.html` — add note/insight/issue/todo per lap, tag support, delete | `app/annotations/page.tsx` | **PARITY** | |
| Annotation search | `annotation_search.html` | Not found as separate page | **MISSING** | |

### 1.10 Development Plans

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Dev plan list with templates | `dev_plan.html` — driver select, template cards, active plans with progress | `app/dev-plans/page.tsx` | **PARITY** | |
| Dev plan detail | `dev_plan_detail.html` — weekly drills, completion tracking | `app/dev-plans/[id]/page.tsx` | **PARITY** | |
| Driver progress tracking | `dev_plan.html` — progress stats, best lap trend chart, score trend chart, session history, PB markers | Need to verify | **UNKNOWN** | Old had rich embedded progress charts |
| Session drill suggestions | `dev_plan.html` — priority-colored drill cards based on latest session | Need to verify | **UNKNOWN** | |

### 1.11 Race Strategy

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Race list with status | `race_strategy/index.html` — table with LIVE hero, saved races, duplicate/delete | `app/race-strategy/page.tsx` — card grid with status badges, search/filter | **ENHANCED** | New tool has better UI with card layout |
| New race creation | `race_strategy/config.html` | `app/race-strategy/new/page.tsx` | **PARITY** | |
| Race detail/edit | `race_strategy/detail.html` | `app/race-strategy/[id]/page.tsx` + `[id]/edit/page.tsx` | **PARITY** | |
| Live race control | `race_strategy/live.html` + `race_strategy_live.js` | `app/race-strategy/[id]/live/page.tsx` | **PARITY** | |
| Race summary | `race_strategy/summary.html` | `app/race-strategy/[id]/summary/page.tsx` | **PARITY** | |
| Import/export JSON | `race_strategy/index.html` — file upload form | Need to verify | **UNKNOWN** | |
| Duplicate race | `race_strategy/index.html` — inline form button | Need to verify | **UNKNOWN** | |

### 1.12 Kart Catalog

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Kart list | `kart_list.html` | `app/karts/page.tsx` | **PARITY** | |
| Kart detail with specs | `kart_detail.html` — manufacturer, model, engine, power, weight, notes | `app/karts/[id]/page.tsx` | **PARITY** | |
| Kart create/edit form | `kart_form.html` | `app/karts/new/page.tsx` | **PARITY** | |

### 1.13 Weekends

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Weekend list | `weekend_list.html` | `app/weekends/page.tsx` | **PARITY** | |
| Weekend detail | `weekend_detail.html` — track, dates, summary stats, linked sessions | `app/weekends/[id]/page.tsx` | **PARITY** | |
| Weekend create/edit | `weekend_form.html` | `app/weekends/new/page.tsx` | **PARITY** | |
| Weekend delete | `weekend_detail.html` — delete button | Need to verify | **UNKNOWN** | |

### 1.14 Leaderboard

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Leaderboard with ranking | `leaderboard.html` — podium medals, full table with rank/driver/best/avg score/best score/sessions/laps/style/trend | `app/leaderboard/page.tsx` | **PARITY** | |
| Track filter | `leaderboard.html` — dropdown auto-submit | Need to verify | **UNKNOWN** | |
| Sort options (best time, avg score, sessions) | `leaderboard.html` — dropdown auto-submit | Need to verify | **UNKNOWN** | |
| Driving style labels | `leaderboard.html` — styled badges (smooth/aggressive/conservative/adaptive) | Need to verify | **UNKNOWN** | |

### 1.15 Data Health

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Data health dashboard | `data_health.html` — summary cards + quality distribution chart + sessions table | `app/data-health/page.tsx` | **PARITY** | |
| Data health detail (per-session) | `data_health_detail.html` | `app/data-health/[id]/page.tsx` | **PARITY** | |

### 1.16 Account & Billing (New-only)

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| User profile | Not present (no auth) | `app/account/profile/page.tsx` — display name, avatar, email, language, timezone, units, notifications | **NEW** | SaaS-only feature |
| Security settings | Not present | `app/account/security/page.tsx` | **NEW** | Password change, 2FA |
| Billing & subscription | Not present | `app/account/billing/page.tsx` — plan tier, invoices, payment method | **NEW** | Stripe integration |
| Billing upgrade | Not present | `app/account/billing/upgrade/page.tsx` | **NEW** | |
| Usage tracking | Not present | `app/account/usage/page.tsx` | **NEW** | |
| Data management | Not present | `app/account/data/page.tsx` | **NEW** | GDPR export/erasure |
| Support | Not present | `app/account/support/page.tsx` | **NEW** | |

### 1.17 Admin / Race Control (New-only)

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| Health overview | Not present | `app/race-control/page.tsx` — services status, jobs/billing/security metrics | **NEW** | |
| User management | Not present | `app/race-control/users/page.tsx` + `[id]/page.tsx` | **NEW** | |
| Job monitoring | Not present | `app/race-control/jobs/page.tsx` + `[id]/page.tsx` | **NEW** | |
| Billing reconciliation | Not present | `app/race-control/billing/page.tsx` + reconciliation + webhooks | **NEW** | |
| Security/audit log | Not present | `app/race-control/security/page.tsx` + audit-log | **NEW** | |
| Infrastructure | Not present | `app/race-control/infra/page.tsx` | **NEW** | |
| Incidents | Not present | `app/race-control/incidents/page.tsx` + `[id]/page.tsx` | **NEW** | |
| Email management | Not present | `app/race-control/email/page.tsx` | **NEW** | |
| Entitlements | Not present | `app/race-control/entitlements/page.tsx` | **NEW** | |

### 1.18 Error & System Pages

| Feature | Old Tool (Jinja2) | New Tool (Next.js) | Status | Notes |
|---------|-------------------|-------------------|--------|-------|
| 404 page | `404.html` | Next.js built-in `not-found.tsx` | **PARITY** | |
| 500 page | `500.html` | Next.js built-in `error.tsx` | **PARITY** | |
| Toast notifications | `toast.js` — success/error/info toasts | Need to verify | **UNKNOWN** | |
| Dark theme | `theme.js` — CSS variables based dark theme | Tailwind dark theme via CSS | **PARITY** | |
| Responsive tables | `resize_observer.js` — auto-resize canvas charts | Need to verify | **UNKNOWN** | |

---

## Section 2: Synchronized Interaction Map

### Old Tool Interaction System

The old Jinja2 tool had a sophisticated synchronized interaction system built on vanilla JavaScript module registration (`ModuleManager`) and lifecycle management (`LifecycleHelpers`). Key patterns:

| Interaction | Old Tool | New Tool | Status |
|-------------|----------|----------|--------|
| Hover on speed trace -> highlight on track map | **YES** — `chart_sync.js` calls `TrackMap.updateMarkerByDistance(distM)` on mousemove | Depends on `SpeedTrace.tsx` + `TrackMap.tsx` implementation | **UNKNOWN** — needs verification |
| Hover on track map -> crosshair on speed trace | **YES** — `track_map.js` calls `ChartSync.updateCrosshair(distance)` on hover | Depends on shared state in session page | **UNKNOWN** — needs verification |
| Touch support for chart sync | **YES** — `chart_sync.js` handles `touchstart` and `touchmove` events | Likely via React events | **UNKNOWN** |
| Lap selector -> update all charts | **YES** — `#lap-select` change triggers `ChartSync.loadSpeedData(lapNum)` + `TrackMap` redraw | Likely via React state | **PARITY** (different mechanism) |
| G-G diagram zoom/pan | **YES** — mouse wheel zoom with focus point, drag pan, double-click reset, keyboard (+/-/arrows/0) | Depends on `GGDiagram.tsx` | **UNKNOWN** |
| Speed trace drag-to-zoom | **YES** — `speed_trace_zoom.js` — drag selection opens zoomed detail canvas below with multi-lap overlay | Depends on `SpeedTrace.tsx` | **UNKNOWN** |
| Corner marker click -> auto-zoom speed trace | **YES** — `speed_trace_zoom.js` — clicking corner marker on overview auto-zooms to brake-to-throttle window | Depends on implementation | **UNKNOWN** |
| Lap bar click -> load that lap's data | **YES** — clicking lap in bar chart loads that lap's GPS data into track map + speed trace | Depends on implementation | **UNKNOWN** |
| Tab switching -> lazy chart rendering | **YES** — G-G diagram waits for `tab:activate` event before rendering (avoids rendering hidden canvases with zero width) | React state via tab management | **PARITY** (different mechanism) |
| ResizeObserver -> redraw all canvases | **YES** — `resize_observer.js` calls `canvas.__redraw()` on all registered canvases | React resize handling | **UNKNOWN** |
| Corner replay playback -> synchronized map + cockpit | **YES** — `corner_replay.js` orchestrates `CornerReplayMap` + `CornerReplayCockpit` with rAF animation loop | `CornerReplay.tsx` system | **PARITY** |

### Critical Sync Gaps to Verify

1. **Chart-map bidirectional hover** — this was the most premium interaction in the old tool. Both `chart_sync.js` and `track_map.js` explicitly call each other's public APIs. The new tool must replicate this via shared React state or context.

2. **G-G diagram interactivity** — the old tool had full zoom (wheel with focus-point tracking), pan (drag), reset (double-click), and keyboard navigation. This is a data-dense chart and these interactions are critical for professional use.

3. **Speed trace drag-to-zoom** — the old tool let users drag-select a distance range on the overview speed chart, then rendered a zoomed detail canvas below with multi-lap comparison. This was a differentiating feature.

---

## Section 3: CRUD Capabilities Comparison

| CRUD Operation | Old Tool | New Tool | Status |
|----------------|----------|----------|--------|
| **Rename session** (date, driver, track, type, condition, kart, notes) | `session_editor.js` — inline editable fields, debounced auto-save via POST `/sessions/<id>/edit` | Not found | **MISSING** |
| **Delete single session** | `session_list.html` — context menu "Delete Session" via DELETE `/api/session/<id>` | Not found | **MISSING** |
| **Batch delete sessions** | `session_list.html` — `#batch-delete-btn` with multi-select checkboxes | Not found | **MISSING** |
| **Batch re-analyze sessions** | `session_list.html` — `#batch-reanalyze-btn` via POST `/api/batch-reanalyze` | Not found | **MISSING** |
| **Edit driver profile** (weight, class, experience, email, phone, ID, goals, notes) | `driver_editor.js` — inline edit with debounced save via POST `/api/driver/<id>/profile` | Not found | **MISSING** |
| **Delete driver** (cascade) | `driver_profile.html` — danger zone form POST `/drivers/<id>/delete` | Not found | **MISSING** |
| **Rename track** | `track_detail.html` — inline rename form POST `/tracks/<id>/rename` | Not found | **MISSING** |
| **Delete track** (cascade) | `track_detail.html` — danger zone form POST `/tracks/<id>/delete` | Not found | **MISSING** |
| **Update S/F position** (drag marker) | `track_detail.html` — Leaflet drag + POST `/tracks/<id>/update-sf` | Not found | **MISSING** |
| **Add track sector** (click map) | `track_detail.html` — map click POST `/tracks/<id>/sectors/add` | Not found | **MISSING** |
| **Remove track sector** | `track_detail.html` — delete button POST `/tracks/<id>/sectors/<sid>/remove` | Not found | **MISSING** |
| **Add track record** | `track_detail.html` — form POST `/tracks/<id>/records/add` | Not found | **MISSING** |
| **Remove track record** | `track_detail.html` — delete button POST `/tracks/<id>/records/<rid>/remove` | Not found | **MISSING** |
| **Update joker lap settings** | `track_detail.html` — form POST `/tracks/<id>/joker` | Not found | **MISSING** |
| **Invalidate/flag lap** | `session_detail.html` — lap validity shown but editing not confirmed | Not found | **MISSING** |
| **Create annotation** | `annotations.html` — POST `/api/annotations/<session_id>` | `app/annotations/page.tsx` | **PARITY** |
| **Delete annotation** | `annotations.html` — DELETE `/api/annotations/item/<id>` | `app/annotations/page.tsx` | **PARITY** |
| **Create dev plan** | `dev_plan.html` — POST `/api/dev-plans/<driver_id>` | `app/dev-plans/page.tsx` | **PARITY** |
| **Delete dev plan** | `dev_plan.html` — DELETE `/api/dev-plans/plan/<id>` | `app/dev-plans/page.tsx` | **PARITY** |
| **Create race strategy** | `race_strategy/config.html` — POST | `app/race-strategy/new/page.tsx` | **PARITY** |
| **Edit race strategy** | `race_strategy/detail.html` | `app/race-strategy/[id]/edit/page.tsx` | **PARITY** |
| **Delete race strategy** | `race_strategy/index.html` — inline form | Need to verify | **UNKNOWN** |
| **Duplicate race strategy** | `race_strategy/index.html` — inline form | Need to verify | **UNKNOWN** |
| **Import race (JSON)** | `race_strategy/index.html` — file upload | Need to verify | **UNKNOWN** |
| **Create/edit kart** | `kart_form.html` | `app/karts/new/page.tsx` | **PARITY** |
| **Create/edit/delete weekend** | `weekend_form.html` / `weekend_detail.html` | `app/weekends/new/page.tsx` / `app/weekends/[id]/page.tsx` | **PARITY** |
| **Edit user profile** | Not present | `app/account/profile/page.tsx` | **NEW** |
| **Change password** | Not present | `app/account/security/page.tsx` | **NEW** |
| **Manage subscription** | Not present | `app/account/billing/page.tsx` | **NEW** |
| **Export/session data** | `export_builder.html` — POST `/api/export/session/<id>` | `app/exports/page.tsx` | **PARITY** |

### Summary of CRUD Losses

The new Next.js frontend is missing **15 critical CRUD operations** that were available in the old tool. The most impactful losses are:

1. **Session editing** (inline metadata editing with auto-save)
2. **Session deletion** (single + batch)
3. **Driver profile editing** (8 editable fields)
4. **Track management** (rename, S/F drag, sector management, records, joker settings)
5. **Batch operations** (re-analyze, bulk delete)

---

## Section 4: Six Critical User Journeys

### Journey 1: Upload -> Analyze

```
Step 1: Navigate to /app/analyze
  Frontend: app/analyze/page.tsx
  Query: GET /api/v1/files (TanStack query for file list, enabled when step=1)
  Display: File browser with server-side file list + drag-drop upload zone

Step 2: Upload CSV (optional — can also select existing file)
  Frontend: handleUpload() in app/analyze/page.tsx
  Action: Drag-drop or click "Upload CSV" button
  API: POST /api/v1/files/upload (FormData with Bearer token)
  Response: { data: { filename: string } }
  Risk: No upload progress via XHR (no XMLHttpRequest.upload.onprogress)

Step 3: Select file and click "Next: Configure"
  Frontend: setSelectedFile(name), setStep(2)
  Validation: Button disabled until file selected

Step 4: Configure session metadata
  Frontend: Step 2 panel in app/analyze/page.tsx
  Queries: GET /api/v1/drivers, GET /api/v1/tracks, GET /api/v1/karts (all enabled when step=2)
  Inputs: Session type (4 options), Driver (dropdown), Track (dropdown), Kart (dropdown)
  Auto-defaults: First complete driver/track/kart auto-selected
  GAPS vs old tool:
    - Missing: Track conditions (10 options), endurance stints, lap range, joker detection
    - Missing: "New Driver" inline creation, "New Track" with predefined search
    - Missing: Session type hint explaining report focus

Step 5: Start Analysis
  Frontend: handleSubmit() -> setStep(3)
  API: POST /api/v1/ingest/start (FormData: csv_file, driver_id, track_id, kart_id, session_type)
  Response: { job_id: string }
  Risk: If API down, user sees "Failed to start analysis" with retry

Step 6: Monitor progress
  Frontend: TanStack query polling every 2s: GET /api/v1/ingest/status/{job_id}
  Response: { job_id, status, progress, message, session_id? }
  States: pending -> processing -> complete | failed
  Display: Spinner + progress bar + message text
  GAPS vs old tool:
    - Missing: Named pipeline stages (8 stages with labels)
    - Missing: Elapsed time counter
    - Missing: Corner picker interaction (pauses pipeline for user input)
    - Missing: Joker lap confirmation dialog (pauses for user decision)

Step 7: View results
  Frontend: "View Session" button -> router.push(/app/sessions/{session_id})
  API: GET /api/v1/sessions/{id}
  Risk: session_id may be null if pipeline didn't return it
```

### Journey 2: View Session (5 Tabs)

```
Step 1: Navigate to /app/sessions/{id}
  Frontend: app/sessions/[id]/page.tsx
  API: GET /api/v1/sessions/{id}
  Response: SessionDetail object (id, date, track, driver, scores, grade, condition, etc.)
  Display: PageHeader + StatCards (best time, mean time, score, grade, laps, consistency)

Step 2: Tab — Overview
  Frontend: Default tab with stat cards + score breakdown
  Components: ScoreBar (4 bars), grade badge, condition phases, data health, weather
  Data: All from initial session query + computed stats from laps
  Sub-queries:
    - GET /api/v1/sessions/{id}/laps -> lap table
    - GET /api/v1/sessions/{id}/badges -> badges + tags

Step 3: Tab — Corners & Coaching
  Components: CornerMastery, BrakeScatter, ThrottleHeatmap, corner coaching table
  Sub-queries:
    - GET /api/v1/sessions/{id}/corner-coaching -> CornerCoachingEntry[]
    - GET /api/v1/sessions/{id}/corner-metrics/summary
  Features: CornerReplay (animated playback)

Step 4: Tab — Performance
  Components: SpeedTrace, TrackMap, GGDiagram, LapProgress, SectorChart
  Sub-queries:
    - GET /api/v1/sessions/{id}/gps/{lap_number} -> GPS trace data
    - GET /api/v1/sessions/{id}/gg_data -> acceleration data
    - GET /api/v1/sessions/{id}/theoretical -> theoretical speed envelope
    - GET /api/v1/sessions/{id}/lap_times -> lap time bars
  Critical: Chart-map hover sync must work (see Section 2)

Step 5: Tab — Analytics
  Components: DrivingStyle, Fingerprint, ConsistencyHeatmap, FatigueChart,
              EnergyBalance, WorkloadChart, SpeedProfile, TyreChart, WeatherChart
  Sub-queries: Various analytics endpoints
  Risk: Many charts depend on optional data (tyre, weather may not exist)

Step 6: Tab — Lap Data
  Components: DataTable with full lap details, LapDistribution, LapOverlay
  Data: Lap rows with time, avg speed, max speed, braking, accel, line length, validity
  Features: Sort by column, click to select lap

GAPS vs old tool:
  - Missing: Inline session editing (date, driver, track, type, condition, kart, notes)
  - Missing: What-if simulator link
  - Missing: Export builder link
  - Missing: Annotations link
  - Missing: HTML report link
```

### Journey 3: Compare Sessions/Drivers

```
Step 1: Navigate to /app/compare
  Frontend: app/compare/page.tsx
  Gating: useEntitlements() -> canUse('comparison')
  If not entitled: UpgradeBanner blocks access
  Risk: Free-tier users see dead-end page with no way forward

Step 2a: Session Comparison
  Navigate: /app/compare/sessions
  Frontend: app/compare/sessions/page.tsx
  API: GET /api/v1/sessions (for session picker)
  Action: Select Session A and Session B
  API: GET /api/v1/comparisons/sessions?a={id}&b={id}
  Display: Side-by-side metadata, score bars, delta calculation, speed overlay chart

Step 2b: Driver Comparison
  Navigate: /app/compare/drivers
  Frontend: app/compare/drivers/page.tsx
  API: GET /api/v1/drivers (for driver picker)
  Action: Select Driver A and Driver B
  API: GET /api/v1/comparisons/drivers?a={id}&b={id}
  Display: H2H scoreboard, scorecard rows, verdict, progression overlay

GAPS vs old tool:
  - Old tool had no entitlement gating (all features free)
  - Need to verify: speed overlay, lap time comparison charts in new tool
  - Need to verify: score progression overlay for driver comparison
```

### Journey 4: Race Strategy

```
Step 1: Navigate to /app/race-strategy
  Frontend: app/race-strategy/page.tsx
  API: GET /api/v1/race-strategy/
  Display: Stat cards (total races, live, completed, race hours) + filterable card grid

Step 2: Create new race
  Navigate: /app/race-strategy/new
  Frontend: app/race-strategy/new/page.tsx
  API: POST /api/v1/race-strategy/
  Inputs: Race name, track, team, duration, desired stints, drivers

Step 3: Configure stints
  Navigate: /app/race-strategy/{id}/edit
  Frontend: app/race-strategy/[id]/edit/page.tsx
  API: PUT /api/v1/race-strategy/{id}
  Features: Stint optimizer, driver rotation, fuel/tyre strategy

Step 4: Go live
  Navigate: /app/race-strategy/{id}/live
  Frontend: app/race-strategy/[id]/live/page.tsx
  API: Various real-time endpoints for live timing
  Features: Live lap timing, stint tracking, strategy adjustments, pit window optimization

Step 5: View summary
  Navigate: /app/race-strategy/{id}/summary
  Frontend: app/race-strategy/[id]/summary/page.tsx
  API: GET /api/v1/race-strategy/{id}/summary

GAPS vs old tool:
  - New tool has better UI (card layout vs table)
  - Need to verify: Import/export JSON, duplicate race
```

### Journey 5: Account & Billing

```
Step 1: Navigate to /app/account
  Frontend: app/account/page.tsx -> redirects to /app/account/profile
  Layout: app/account/layout.tsx -> sidebar with Profile/Security/Billing/Data/Support links

Step 2: Edit profile
  Navigate: /app/account/profile
  Frontend: app/account/profile/page.tsx
  API: GET /api/v1/account/profile -> UserProfile
  API: PUT /api/v1/account/profile -> update display_name, preferences
  Features: Language (7 options), timezone, units (metric/imperial), notification prefs

Step 3: Security
  Navigate: /app/account/security
  Frontend: app/account/security/page.tsx
  API: POST /api/v1/auth/change-password
  Features: Password change, OAuth connections display

Step 4: Billing
  Navigate: /app/account/billing
  Frontend: app/account/billing/page.tsx
  API: GET /api/v1/billing/subscription -> plan tier, status, payment method
  API: GET /api/v1/billing/invoices -> invoice history
  Features: Plan display, usage dashboard, invoice PDF links

Step 5: Upgrade
  Navigate: /app/account/billing/upgrade
  Frontend: app/account/billing/upgrade/page.tsx
  API: POST /api/v1/billing/checkout -> Stripe checkout session
  Features: Plan comparison, pricing cards

Step 6: Data management
  Navigate: /app/account/data
  Frontend: app/account/data/page.tsx
  API: POST /api/v1/account/export -> GDPR data export
  API: POST /api/v1/account/erase -> GDPR erasure
  Features: Data export request, account deletion

NOTE: This entire journey is NEW — the old tool had no auth, billing, or account management.
```

### Journey 6: Admin / Race Control

```
Step 1: Navigate to /app/race-control
  Frontend: app/race-control/page.tsx
  Layout: app/race-control/layout.tsx -> sidebar with Overview/Users/Jobs/Billing/Security/Infra/Email/Incidents
  API: GET /api/v1/admin/health -> services status, job metrics, billing metrics, security metrics
  Gating: Presumably admin-only (RBAC)

Step 2: User management
  Navigate: /app/race-control/users
  Frontend: app/race-control/users/page.tsx
  API: GET /api/v1/admin/users -> user list
  Features: Search, filter by role/status
  Detail: /app/race-control/users/[id]/page.tsx -> user detail, role management

Step 3: Job monitoring
  Navigate: /app/race-control/jobs
  Frontend: app/race-control/jobs/page.tsx
  API: GET /api/v1/admin/jobs -> job list with status/duration
  Detail: /app/race-control/jobs/[id]/page.tsx -> job detail, logs, retry

Step 4: Billing reconciliation
  Navigate: /app/race-control/billing
  Frontend: app/race-control/billing/page.tsx
  Sub-pages: reconciliation, webhooks
  API: GET /api/v1/admin/billing/reconciliation
  Features: Revenue metrics, subscription tracking, webhook logs

Step 5: Security & audit
  Navigate: /app/race-control/security
  Frontend: app/race-control/security/page.tsx
  Sub-page: audit-log
  API: GET /api/v1/admin/security/audit-log
  Features: Login failures, rate limits, security events

Step 6: Incidents
  Navigate: /app/race-control/incidents
  Frontend: app/race-control/incidents/page.tsx
  Detail: /app/race-control/incidents/[id]/page.tsx
  API: Various admin endpoints
  Features: Incident creation, tracking, resolution

NOTE: This entire journey is NEW — the old tool had no admin panel.
```

---

## Section 5: UX Regression Catalog

| UX Pattern | Old Tool Quality | New Tool Quality | Impact |
|------------|-----------------|-----------------|--------|
| **Page load time** | Fast — SSR Jinja2, single HTML render, JS lazy-loads chart data | Good — Next.js RSC + client components, TanStack Query for data fetching | **Neutral** — SPA navigation offsets initial load |
| **Chart interactivity** | Excellent — custom Canvas charts with zoom/pan/keyboard, hover sync | Good — React chart components exist but interaction depth unknown | **Medium** — need to verify zoom/pan/keyboard parity |
| **Data table sorting** | Client-side column sorting on all tables (`session_list.html`) | `DataTable` component with `sortable: true` columns | **Parity** |
| **Dark theme consistency** | Consistent — CSS variables, `Theme.colors` object shared by all JS | Consistent — Tailwind custom theme with design tokens | **Parity** |
| **Mobile responsiveness** | Moderate — responsive meta tag, some chart touch support, but primarily desktop | Good — Tailwind responsive classes, mobile-first design | **Improved** |
| **Error messages clarity** | Good — `Toast.show()` for success/error, inline `.form-error` spans, confirmation dialogs | Good — `QueryError` component, inline error states | **Parity** |
| **Loading states** | Good — skeleton loaders (`.skeleton` class), "Loading..." placeholders | Excellent — `SkeletonStatCards`, `SkeletonTableRows`, `SkeletonBox`, spinner | **Improved** |
| **Empty states** | Excellent — themed empty-hero components with icon, title, description, CTA button | Excellent — similar empty states with descriptive text and CTA | **Parity** |
| **Keyboard navigation** | Good — `tabindex` on rows, `role="link"`, G-G diagram arrow keys | Unknown — standard React accessibility | **Unknown** |
| **Print/export formatting** | Good — export builder with section selection, Markdown output, copy to clipboard | Unknown — export page exists | **Unknown** |
| **Right-click context menu** | Premium — `context_menu.js` with session-specific actions (open, visualize, copy ID, delete) | **Missing** — no context menu | **High** — loss of power-user workflow |
| **Inline editing** | Premium — session fields, driver profile, all with debounced auto-save | **Missing** — all pages appear read-only | **Critical** — data management impossible |
| **Batch operations** | Present — select-all, batch re-analyze, batch delete | **Missing** | **High** — fleet/team management impossible |
| **Wizard step detail** | Rich — 8 named pipeline stages, elapsed timer, corner picker, joker confirmation | Basic — generic progress bar with percentage | **Medium** — less informative progress |
| **Animated stat counters** | Present — `Motion.tickUp()` animates numbers on load | Not present — static numbers | **Low** — cosmetic |
| **Drag-to-zoom on charts** | Present — speed trace zoom with multi-lap comparison | Unknown | **High** — critical analysis workflow |
| **Session type specificity** | 7 types with report focus hints | 4 types without hints | **Medium** — less nuanced analysis |
| **Track condition tagging** | 10 condition pills (dry/wet/damp/mixed/drying/greasy/flooded/dusty/cold/hot) | Not present | **Medium** — affects data quality |

---

## Section 6: Implementation Priority

| Priority | Feature/Fix | Impact | Effort Estimate |
|----------|-------------|--------|-----------------|
| **P0** | **Session editing** — add inline editing for session metadata (date, driver, track, type, condition, kart, notes) | Users cannot correct misattributed sessions | 2-3 days |
| **P0** | **Session deletion** — add delete button to session detail + session list | Users cannot clean up bad/test data | 1 day |
| **P0** | **Verify chart-map hover sync** — confirm bidirectional hover between SpeedTrace and TrackMap works | Core professional workflow; chart analysis without sync is crippled | 1-2 days (verify + fix if needed) |
| **P1** | **Track condition tagging** in analysis wizard — add condition pills to step 2 | Conditions affect scoring and comparison accuracy | 1 day |
| **P1** | **Batch operations** — batch select + batch delete + batch re-analyze on session list | Team/fleet users need bulk operations | 2-3 days |
| **P1** | **Driver profile editing** — add inline editing for weight, class, experience, goals, etc. | Driver profiles are empty shells without editable fields | 1-2 days |
| **P1** | **Track management CRUD** — rename track, S/F position, sector management, records, joker settings | Track configuration is frozen after first analysis | 3-4 days |
| **P1** | **Pipeline stage feedback** — show 8 named stages instead of generic progress bar | Users don't know what's happening during analysis | 0.5 days |
| **P2** | **Session type expansion** — add warmup, sprint, endurance types with report hints | Professional users need these types | 0.5 days |
| **P2** | **Drag-to-zoom on speed trace** — implement drag selection + zoomed detail view | Power analysis feature for lap comparison | 2-3 days |
| **P2** | **G-G diagram zoom/pan/keyboard** — verify and match old tool's interaction depth | Professional UX for acceleration analysis | 1-2 days |
| **P2** | **What-if simulator** — restore per-corner speed adjustment simulation tool | Unique coaching feature for improvement planning | 2 days |
| **P2** | **Right-click context menu** on session list — open, visualize, copy ID, delete | Power-user workflow acceleration | 1-2 days |
| **P2** | **Driver delete** — add delete with cascade confirmation | Data management completeness | 0.5 days |
| **P2** | **Track delete** — add delete with cascade confirmation | Data management completeness | 0.5 days |
| **P3** | **Endurance stints configuration** in analysis wizard | Needed for endurance race analysis | 2 days |
| **P3** | **Corner picker** in analysis wizard for new tracks | Needed when analyzing at new venues | 2 days |
| **P3** | **Joker lap detection** toggle + confirmation dialog | Niche feature for circuits with joker sections | 1-2 days |
| **P3** | **Lap range filter** in analysis wizard | Useful for partial session analysis | 0.5 days |
| **P3** | **Annotation search** — cross-session annotation search | Was a separate page in old tool | 1 day |
| **P3** | **Custom dashboard** — user-configurable dashboard layouts | Was available in old tool as separate page | 3-5 days |
| **P3** | **Cross-session analysis** — restore analytics tool | Multi-session pattern detection | 2-3 days |
| **P3** | **Rival comparison** — restore multi-driver corner-by-corner analysis | Competitive benchmarking tool | 2-3 days |
| **P3** | **HTML report link** — restore link to generated standalone report | Some users prefer static reports | 1 day |
| **P3** | **Animated stat counters** — `tickUp()` effect on dashboard | Cosmetic polish | 0.5 days |

### Summary

**Total features in old tool**: ~85 distinct features across 45 templates and 60+ JS modules
**Features at PARITY or ENHANCED in new tool**: ~60 (71%)
**Features MISSING in new tool**: ~15 (18%)
**Features PARTIALLY implemented**: ~10 (12%)
**NEW features in Next.js**: ~20 (account, billing, admin, entitlements, race control)

The new Next.js frontend has achieved strong chart-component parity (25+ chart types ported to React components) and added significant SaaS infrastructure (auth, billing, admin). However, it has lost nearly all **CRUD operations for data management** (session editing, deletion, driver editing, track management) and several **premium interaction patterns** (chart-map hover sync verification needed, drag-to-zoom, context menus, batch operations). The P0 items represent data management capabilities that prevent users from maintaining their own data, which is the most critical gap.
