# LAP Website

Next.js marketing and conversion site for LAP telemetry analysis.

## Routes

- Core conversion: `/pricing`, `/demo`, `/book`, `/contact`, `/waitlist`
- Persona pages: `/drivers`, `/circuits`, `/teams`, `/endurance`
- Product and trust: `/product`, `/billing`, `/security`, `/status`
- Legal: `/privacy`, `/terms`, `/dpa`
- Proof and SEO: `/customers`, `/insights`

## Lead and Conversion APIs

- `POST /api/leads`: validates lead form payloads and forwards to CRM + email endpoints
- `POST /api/conversions`: server-side conversion forwarding
- Billing scaffolding:
  - `POST /api/billing/checkout`
  - `POST /api/billing/portal`
  - `POST /api/billing/switch`

## Environment Variables

- `CRM_WEBHOOK_URL`
- `EMAIL_WEBHOOK_URL`
- `LEAD_WEBHOOK_BEARER` (optional)
- `CONVERSION_WEBHOOK_URL` (optional)
- `CONVERSION_WEBHOOK_BEARER` (optional)
- `BILLING_CHECKOUT_WEBHOOK_URL` (optional)
- `BILLING_PORTAL_WEBHOOK_URL` (optional)
- `BILLING_SWITCH_WEBHOOK_URL` (optional)
- `BILLING_WEBHOOK_BEARER` (optional)
- `LEAD_ALERT_WEBHOOK_URL` (optional, for delivery failure alerts)
- `STRIPE_SECRET_KEY` (optional, enables direct Stripe checkout/portal/switch)
- `STRIPE_PRICE_PERFORMANCE_MONTHLY` (optional)
- `STRIPE_PRICE_PERFORMANCE_ANNUAL` (optional)
- `STRIPE_PRICE_PRO_RACER_MONTHLY` (optional)
- `STRIPE_PRICE_PRO_RACER_ANNUAL` (optional)
- `BILLING_ALLOW_GUEST` (optional, defaults to auth-required for portal/switch)
- `NEXT_PUBLIC_SITE_URL` (optional, used for live status fetch in SSR)

If endpoints are not configured, API routes return fallback responses so local development still works.

## Local Development

```bash
npm run dev
```

## Deploy to Cloudflare Workers

One-time setup:

```bash
npx wrangler login
```

Build and preview locally with the Cloudflare runtime:

```bash
npm run cf:preview
```

Deploy:

```bash
npm run cf:deploy
```

Notes:
1. Worker name is set to `lap-website` in `wrangler.jsonc`.
2. `WORKER_SELF_REFERENCE` is configured for ISR revalidation support.
3. Add runtime secrets in Cloudflare before deploy, for example `CRM_WEBHOOK_URL`, `EMAIL_WEBHOOK_URL`, and Stripe keys if used.

### Styling Reliability (Marketing Routes)

Use these scripts if marketing pages (`/`, `/pricing`, `/demo`, `/billing`, etc.) ever load as mostly unstyled HTML.

```bash
# Start from a clean local Next.js state
npm run dev:clean

# Check that marketing CSS/chunk assets resolve to HTTP 200
npm run health:assets

# One-command recovery: stop process on :3000, clear .next, start dev, run health check
npm run dev:reset
```

Recommended recovery flow:
1. Hard refresh the browser (`Ctrl+F5` / `Cmd+Shift+R`).
2. If still broken, run `npm run dev:reset`.
3. Reopen `http://localhost:3000` and verify theme/colors/spacing are back.

## Quality Gates

```bash
npm run lint
npm run test
npm run test:e2e
npm run qa:content
npm run ci
```

`npm run ci` runs lint, unit tests, build, and content QA checks.
