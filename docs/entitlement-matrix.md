# Entitlement Matrix — Single Source of Truth

> **Authority**: This document is the canonical reference for all plan entitlements.
> Frontend (`pricing.ts`), backend (`plan_definitions` DB), and Stripe products MUST match this matrix.
> Run `python scripts/verify_entitlement_consistency.py` to detect drift.

## Plan Tiers

| Tier | Slug | Monthly | Annual | Annual/mo |
|------|------|---------|--------|-----------|
| Demo | `demo` | Free | Free | — |
| Racer | `racer` | €8.99 | €69 | €5.75 |
| World-Class | `world-class` | €13.99 | €109 | €9.08 |
| B2B | `b2b` | Custom | Custom | Custom |

## Feature Entitlements

| Feature | Code Key | Demo | Racer | World-Class | B2B |
|---------|----------|------|-------|-------------|-----|
| Analysis Reports / month | `reports_per_month` | 1 | 10 | Unlimited (`NULL`) | Unlimited (`NULL`) |
| 4-Pillar Scoring | `scoring` | Full | Full | Full | Full |
| Corner Coaching | `corner_coaching` | Full | Full | Full | Full |
| Session Intelligence | `session_intelligence` | Full | Full | Full | Full |
| Comparison & Progress | `comparison` | No | No | Yes | Yes |
| Coaching Plans | `coaching_plans` | No | Yes | Yes | Yes |
| Visualization | `visualization` | No | Yes | Yes | Yes |
| Race Strategy | `race_strategy` | `limited_3h` | `full` | `full` | `full` |
| Live Monitoring | `live_monitoring` | No | Yes | Yes | Yes |
| Pit Stop Planning | `pit_planning` | No | Yes | Yes | Yes |
| Incident Queue | `incident_queue` | No | Yes | Yes | Yes |
| PDF Reports | `export_pdf` | No | Yes | Yes | Yes |
| CSV Export | `export_csv` | Yes | Yes | Yes | Yes |
| API Access | `api_access` | No | No | Yes | Yes |
| Branded Reports | `branded_reports` | No | No | No | Yes |

## Resource Limits

| Resource | Code Key | Demo | Racer | World-Class | B2B |
|----------|----------|------|-------|-------------|-----|
| Raw Telemetry Retention | `telemetry_retention_days` | 30 | 90 | 365 | Custom (`NULL`) |
| Max Upload Size | `max_upload_size_mb` | 500 | 2000 | 5000 | 10000 |
| Max Concurrent Jobs | `max_concurrent_jobs` | 1 | 2 | 5 | 10 |
| Rate Limit Multiplier | `rate_multiplier` | 1.0 | 2.0 | 5.0 | 10.0 |

## Export Formats by Tier

| Tier | Formats |
|------|---------|
| Demo | `["csv"]` |
| Racer | `["pdf","csv"]` |
| World-Class | `["pdf","csv","api"]` |
| B2B | `["pdf","csv","api","branded"]` |

## Data Lifecycle

| Data Category | Demo | Racer | World-Class | B2B |
|---------------|------|-------|-------------|-----|
| Raw Telemetry | 1 month → auto-deleted | 3 months → auto-deleted | 12 months → auto-deleted | Custom |
| Processed Reports | Indefinite | Indefinite | Indefinite | 2 years |
| Live Event Data | Temporary (flushed) | Temporary (flushed) | Temporary (flushed) | Temporary (flushed) |

## Stripe Product Configuration

```
Product: "Lap Coach Racer"
  ├── Price: racer_monthly   (€8.99/mo, recurring, interval=month)
  └── Price: racer_annual    (€69/yr, recurring, interval=year)

Product: "Lap Coach World-Class"
  ├── Price: worldclass_monthly  (€13.99/mo, recurring, interval=month)
  └── Price: worldclass_annual   (€109/yr, recurring, interval=year)

Product: "Lap Coach B2B"
  └── Price: b2b_custom  (custom pricing, not self-serve)
```

### Environment Variables (from Stripe Dashboard)

```
STRIPE_PRICE_RACER_MONTHLY=price_xxx
STRIPE_PRICE_RACER_ANNUAL=price_xxx
STRIPE_PRICE_WORLDCLASS_MONTHLY=price_xxx
STRIPE_PRICE_WORLDCLASS_ANNUAL=price_xxx
```

## Stripe Customer Portal

- **Plan switching**: upgrade/downgrade allowed
- **Payment methods**: update allowed
- **Cancellation**: `cancel_at_period_end = true` (NOT immediate)
- **Invoice history**: visible
- **Redirect URL**: `https://lap-coach.racing/app/account/billing`

## Entitlement Overrides

Overrides in `entitlement_overrides` table take precedence over plan defaults.
Used for: grandfathering (legacy pricing), support credits, promotional offers.

Override values are JSON: `{"value": 5}` for `reports_per_month`.

## Reconciliation

Three sources must stay in sync:
1. **This document** — canonical specification
2. **`pricing.ts`** — frontend display
3. **`plan_definitions` DB** — backend enforcement
4. **Stripe products** — payment processing

Run `python scripts/verify_entitlement_consistency.py` in CI to catch drift.
