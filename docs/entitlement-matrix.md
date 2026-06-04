# Entitlement Matrix — Single Source of Truth

> **Authority**: This document is the canonical reference for all plan entitlements.
> Frontend (`pricing.ts`), backend (`plan_definitions` DB), and Stripe products MUST match this matrix.
> Run `python scripts/verify_entitlement_consistency.py` to detect drift.

## Customer Pricing (June-8)

ONE membership. No free tier; no per-tier choice.

| Offer | Monthly | Notes |
|-------|---------|-------|
| **Founding-50** | €14.90/mo | First 50 paying members only, then closes |
| **Standard** | €19.90/mo | Everyone after the first 50 |

- **Free trial**: 30 days, full access, no card charged until it ends.
- **Billing**: monthly only (no annual).
- **Charge currency**: EUR (usd/gbp on the site are display-only).
- Every paying member receives the internal `world-class` entitlement below — the
  price paid (standard vs founding) does not change what they get.

## Internal Entitlement Tiers

`demo` / `racer` / `world-class` / `b2b` are INTERNAL entitlement tiers (the
`plan_definitions` DB + `entitlements.py` engine), **not** purchasable plans. The
single membership maps to `world-class`. They are kept for the engine and for
grandfathered accounts; the matrices below describe them.

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
Product: "Lap Coach Membership"
  ├── Price: standard_monthly  (€19.90/mo, recurring, interval=month)
  └── Price: founding_monthly  (€14.90/mo, recurring, interval=month)
```

Both prices belong to the same product and grant the same (`world-class`)
entitlement. The server-side Founding-50 cap selects `founding_monthly` for the
first 50 paying members and `standard_monthly` thereafter.

### Environment Variables (from Stripe Dashboard)

```
STRIPE_PRICE_STANDARD_MONTHLY=price_xxx
STRIPE_PRICE_FOUNDING_MONTHLY=price_xxx
```

## Stripe Customer Portal

- **Plan switching**: n/a — single membership (no upgrade/downgrade)
- **Payment methods**: update allowed
- **Cancellation**: `cancel_at_period_end = true` (NOT immediate)
- **Invoice history**: visible
- **Redirect URL**: `https://lap-coach.racing/app/account/billing`

## Entitlement Overrides

Overrides in `entitlement_overrides` table take precedence over plan defaults.
Used for: grandfathering (legacy pricing), support credits, promotional offers.

Override values are JSON: `{"value": 5}` for `reports_per_month`.

## Reconciliation

Four sources must stay in sync:
1. **This document** — canonical specification
2. **`pricing.ts`** — frontend display (the single membership)
3. **`plan_definitions` DB** — backend entitlement enforcement (internal tiers)
4. **Stripe products** — payment processing (the membership product + 2 prices)

Run `python scripts/verify_entitlement_consistency.py` in CI to catch drift.
