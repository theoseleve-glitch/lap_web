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

If endpoints are not configured, API routes return fallback responses so local development still works.

## Local Development

```bash
npm run dev
```

## Quality Gates

```bash
npm run lint
npm run test
npm run test:e2e
npm run qa:content
npm run ci
```

`npm run ci` runs lint, unit tests, build, and content QA checks.
