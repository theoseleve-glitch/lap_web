# Stripe Go-Live Checklist

## Current State

- Backend webhook handler: `telemetry_tool/web/routes/billing.py` (registered in app factory)
- Frontend checkout/portal/switch: `lap-website/src/app/api/billing/` (3 API routes)
- Frontend config: `lap-website/src/lib/stripe-billing.ts` (price ID mapping)
- Database: Migration 016 applied — `stripe_customer_id`, `stripe_subscription_id`, `billing_plan` columns on `users`
- Dependency: `stripe>=8.0` added to `requirements.txt`

## Steps to Go Live

### 1. Create Stripe Products & Prices

In the [Stripe Dashboard](https://dashboard.stripe.com/products):

| Product | Monthly Price | Annual Price | Notes |
|---------|--------------|--------------|-------|
| Performance | EUR 8.99/mo | EUR 69/yr | Self-serve B2C |
| Pro Racer | EUR 13.99/mo | EUR 109/yr | Self-serve B2C |

For each product, create two prices (monthly recurring + annual recurring).
Copy the `price_xxx` IDs for step 3.

### 2. Get Live API Keys

In [Stripe Dashboard > Developers > API Keys](https://dashboard.stripe.com/apikeys):

- Copy the **Secret key** (`sk_live_...`)
- Copy the **Publishable key** (`pk_live_...`)

### 3. Update Environment Variables

**Frontend** (`lap-website/.env.local` or Cloudflare Workers secrets):
```
STRIPE_SECRET_KEY=sk_live_...
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_PRICE_PERFORMANCE_MONTHLY=price_...
STRIPE_PRICE_PERFORMANCE_ANNUAL=price_...
STRIPE_PRICE_PRO_RACER_MONTHLY=price_...
STRIPE_PRICE_PRO_RACER_ANNUAL=price_...
```

**Backend** (`/opt/lap-api/.env.production`):
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### 4. Register Webhook Endpoint

In [Stripe Dashboard > Developers > Webhooks](https://dashboard.stripe.com/webhooks):

- **Endpoint URL**: `https://api.lap-coach.racing/api/v1/billing/webhook`
- **Events to listen for**:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_failed`
- Copy the **Signing secret** (`whsec_...`) to `.env.production`

### 5. Deploy Backend

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

### 6. Deploy Frontend

```bash
cd lap-website && rm -rf .open-next && npm run cf:deploy
```

### 7. Verify

```bash
# Test webhook is reachable (should return 400 "Invalid signature" — that's correct)
curl -X POST https://api.lap-coach.racing/api/v1/billing/webhook -d '{}' -H "Content-Type: application/json"

# Test checkout session creation (from browser)
# Navigate to /billing, click "Upgrade" on Performance plan
```

### 8. Test with Stripe CLI (optional)

```bash
stripe listen --forward-to https://api.lap-coach.racing/api/v1/billing/webhook
stripe trigger checkout.session.completed
```

## Architecture Notes

- B2B plans (Track Essential, Circuit Pro, Enterprise) route to `/contact` — no Stripe checkout
- STARTER plan routes to `/register` — no payment required
- Checkout fallback: if Stripe fails, users are redirected to `/book` with plan params
- Portal fallback: returns `/billing?portal=fallback`
- Webhook returns 200 even on processing errors to prevent Stripe retry storms
