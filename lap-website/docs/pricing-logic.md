# Pricing Logic and Eligibility Matrix

## Plan Families

- B2C: `STARTER`, `PERFORMANCE`, `PRO RACER`
- B2B: `TRACK ESSENTIAL`, `CIRCUIT PRO`, `CIRCUIT ENTERPRISE`

## Availability Tiers

- `available_now`: generally available in self-serve plans.
- `enterprise_on_request`: available through commercial and technical review.
- `roadmap`: not yet available; routed to waitlist.

## Eligibility Rules

1. Any CTA from a pricing card must route to a real conversion page (`/book`, `/demo`, `/contact`).
2. Roadmap-only capabilities cannot be listed as enabled in plan feature entitlements.
3. Enterprise-only capabilities must include an explicit `on request` or `enterprise` label.
4. VAT and currency calculations are delegated to the billing provider endpoint.
5. Plan switch requests are accepted only for existing subscription IDs.

## Billing Lifecycle

1. Checkout is initiated via `POST /api/billing/checkout`.
2. Portal access is initiated via `POST /api/billing/portal`.
3. Plan changes are initiated via `POST /api/billing/switch`.
4. Invoice generation and tax lines are finalized by the configured billing provider.

## Claim Mapping Requirement

Any pricing claim must map to an entry in `src/data/claim-registry.ts` and carry a status classification.
