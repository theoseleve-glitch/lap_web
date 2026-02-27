# Lap Coach — Duality Repositioning & Pricing Architecture Design

## Context

Lap Coach is a dual system: **Engineer Mode** (post-session telemetry analysis) and **Strategist Mode** (pre-event planning + live control + post-stint review). The current website treats the product as a single feature set, creating confusion. This redesign reframes the entire site, pricing, and app around the duality.

---

## A. Information Architecture

### Top Navigation
```
Product  |  Pricing  |  Demo  |  Contact  |  [Log In]  [Sign Up]
```
- **Product** `/product` — duality page: Engineer + Strategist explained side by side
- **Pricing** `/pricing` — 3 B2C tiers + 1 B2B card
- **Demo** `/demo` — free account creation for first report
- **Contact** `/contact` — sales + support
- Remove "Features" (`/drivers`) from top nav. Persona pages become secondary (linked from Product page).

### Product Page Structure
1. **ENGINEER MODE** — Upload, Scoring, Coaching, Comparison, Visualization
2. **STRATEGIST MODE** — Control Room, Live Monitoring, Pit Planning, Incidents
3. **How They Connect** — Data flows from Engineer analysis into Strategy planning

### App Sidebar (Authenticated)
```
ENGINEER
  Dashboard
  Sessions
  Analyze
  Compare
  Coaching Plans
  Visualization

STRATEGIST
  Race Strategy
  Leaderboard

OPERATIONS
  Tracks
  Drivers
  Karts
  Weekends
  Exports
  Data Health
```

### Homepage Adjustments
- S3 (FIND TIME): Reframe around duality — Engineer left, Strategist right
- S4 (WORKFLOW COVERAGE): Group modules into Engineer / Strategist / Operations
- Remove B2C/B2B toggle from S3 (belongs on pricing page only)

---

## B. Pricing Architecture

### B2C — 3 Tiers

| | **DEMO** (Free) | **RACER** (€8.99/mo · €5.75/mo yearly) | **WORLD-CLASS** (€13.99/mo · €9.08/mo yearly) |
|---|---|---|---|
| | | €69/yr — save 36% | €109/yr — save 35% |
| **ENGINEER** | | | |
| Analysis Reports | 1 full report | 10/month | Unlimited |
| 4-Pillar Scoring | Full | Full | Full |
| Corner Coaching | Full | Full | Full |
| Session Intelligence | Full | Full | Full |
| Comparison & Progress | — | — | Full |
| Coaching Plans | — | Full | Full |
| Visualization | — | Full | Full |
| **STRATEGIST** | | | |
| Race Strategy Dashboard | Limited (3h races) | Full | Full |
| Live Monitoring | — | Full | Full |
| Pit Stop Planning | — | Full | Full |
| Incident Queue | — | Full | Full |
| **DATA** | | | |
| Raw Telemetry Retention | 1 month | 3 months | 12 months |
| Report Retention | Indefinite | Indefinite | Indefinite |
| Exports | CSV | PDF + CSV | PDF + CSV + API |
| Seats | 1 | 1 | Up to 5 |
| **CTA** | Start Free | Upgrade | Go World-Class |

### B2B — Single Card

**FOR TEAMS & CIRCUITS**
- Hardware for data logging
- Live telemetry software
- Branded driver reports
- Custom retention & compliance
- Dedicated onboarding
- Raw telemetry: 1 month (standard), custom on request
- Standard reports: 2 years
- Endurance reports: 2 years

CTA: **Contact Sales** → `/contact?plan=b2b`

### Removed
- All add-on cards (timing integration, endurance module, white-label, SLA, webhook tiering)
- B2B multi-tier structure (Track Essential / Circuit Pro / Circuit Enterprise)

### Pricing Display Rules
- Monthly/Annual toggle, default Annual
- Annual price shown as per-month equivalent with savings percentage
- B2B card appears beside B2C tiers (not behind an audience toggle)

---

## C. Data Lifecycle Transparency Block

Visual block on pricing page (below tiers) and product page:

### RAW TELEMETRY (100MB–8GB per session)
- Demo: 1 month → auto-deleted
- Racer: 3 months → auto-deleted
- World-Class: 12 months → auto-deleted
- "Raw files are large. After expiry, they're automatically deleted. Export before expiry — it's always yours."

### PROCESSED REPORTS (1–5MB)
- All B2C tiers: Stored indefinitely
- B2B: 2 years
- "Reports are your permanent record. Lightweight. No extra cost."

### LIVE EVENT DATA
- High-frequency raw: temporary (flushed after event)
- Summaries + leaderboard: persist
- "Real-time data serves the moment. Summaries last."

### Messaging Principles
- Deletion is intentional engineering, not a limitation
- Reports = permanent value, raw = temporary input
- "Need raw data longer? Export before expiry."

---

## D. Feature Eligibility Matrix

Complete redo. Remove Team and Track columns. Three B2C tiers only, grouped by duality:

| Feature | Demo | Racer | World-Class |
|---|---|---|---|
| **ENGINEER** | | | |
| Upload & Analyze | 1 report | 10/mo | Unlimited |
| 4-Pillar Scoring | Full | Full | Full |
| Corner-by-Corner Coaching | Full | Full | Full |
| Session Intelligence Tabs | Full | Full | Full |
| Comparison & Progress | — | — | Full |
| Coaching Plans & Drills | — | Full | Full |
| Visualization Workspace | — | Full | Full |
| **STRATEGIST** | | | |
| Race Strategy Dashboard | 3h limit | Full | Full |
| Live Pace & Stint Monitoring | — | Full | Full |
| Pit Stop Planning | — | Full | Full |
| Incident & Alert Queue | — | Full | Full |
| **DATA & OPS** | | | |
| Track/Driver/Kart Management | Basic | Full | Full |
| PDF Reports | — | Full | Full |
| API Access | — | — | Full |
| Team Seats | 1 | 1 | Up to 5 |
| Raw Telemetry Retention | 1 month | 3 months | 12 months |
| Report Retention | Indefinite | Indefinite | Indefinite |

---

## E. Roadmap

**Keep:** Sim racing ingestion (waitlist)
**Add:** Multisource import
**Remove:** Webhook tiering

Waitlist page updated to reflect only these two items.

---

## F. Messaging

### Homepage
- Hero: "EVERY LAP HAS A SECRET" (unchanged)
- S3 reframe: Left = ENGINEER ("Post-session. Find where you lost time.") / Right = STRATEGIST ("Pre-event. Plan how you'll gain it back.")
- Pricing header: "CHOOSE YOUR DEPTH"

### Product Page
- Two clear halves: Engineer pillar and Strategist pillar
- Connecting narrative: data flows from analysis into strategy

### Tone
- Motorsport-native, technical, confident
- Premium positioning, not gimmicky
- Clear > clever

---

## G. Web App Alignment

The sidebar grouping (Engineer / Strategist / Operations) directly mirrors the marketing site structure:
- Users see the same language on the sales page and inside the app
- Future features slot into one of three groups (no ambiguity)
- Upgrade triggers are natural: Demo users see locked Strategist features, Racer users see locked Comparison

---

## H. Monetization Logic

- **Mid-tier dominance**: Racer is the obvious choice — 10 reports + full strategy for €9/mo
- **Upgrade drivers**: Demo→Racer: need more than 1 report or >3h strategy. Racer→World-Class: need comparison, API, team seats
- **Retention as lever**: Raw telemetry windows incentivize higher tiers (export friction = upgrade trigger)
- **B2C/B2B no cannibalization**: B2B is custom-priced, completely separate funnel via Contact Sales
- **LTV maximization**: Annual billing default with visible savings, indefinite report storage means users never lose value

---

## Files to Modify

### Data files
- `lap-website/src/data/pricing.ts` — new tiers, remove addons, new matrix
- `lap-website/src/data/navigation.ts` — remove Features link
- `lap-website/src/data/workflow-modules.ts` — add group labels (engineer/strategist/ops)
- `lap-website/src/data/claim-registry.ts` — remove webhook_tiering, update race_strategy to available_now
- `lap-website/src/data/copy.ts` — S3 reframe messaging
- `lap-website/src/data/personas.ts` — keep but deprioritize from nav

### Pages
- `lap-website/src/app/(marketing)/pricing/page.tsx` — full rewrite
- `lap-website/src/app/(marketing)/product/page.tsx` — duality restructure
- `lap-website/src/app/(marketing)/waitlist/page.tsx` — sim racing + multisource import only

### Components
- `lap-website/src/components/ui/PricingTable.tsx` — new tier layout with annual per-month display
- `lap-website/src/components/rooms/S3Product.tsx` — duality framing
- `lap-website/src/components/rooms/S4WorkflowCoverage.tsx` — grouped by pillar
- `lap-website/src/components/rooms/PitStop.tsx` — new pricing, remove addons, remove audience toggle
- `lap-website/src/app/app/layout.tsx` — sidebar grouped into Engineer/Strategist/Operations

### Backend
- `lap-website/src/lib/stripe-billing.ts` — rename plan IDs (RACER, WORLD_CLASS)
