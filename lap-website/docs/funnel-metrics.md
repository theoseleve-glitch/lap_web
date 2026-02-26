# Funnel Metrics and Experimentation

## Funnel Definition

1. `visit`: page view on landing pages.
2. `cta_click`: user clicks route-based CTA.
3. `form_submit_start`: validated form submission begins.
4. `lead_submit_success`: lead API accepts and forwards submission.
5. `meeting_booked`: booking workflow reaches thank-you page.
6. `signup`: first authenticated product session (tracked in product app).

## Tracking Architecture

- Client-side event dispatch: `src/lib/analytics.ts` via Plausible.
- Server-side conversion forwarding: `POST /api/conversions`.
- Lead capture conversion forwarding: `POST /api/leads`.

## Attribution Persistence

- Middleware stores:
  - `lap_session_id` (180 days)
  - `lap_attribution` UTM/GCLID/FBCLID payload (90 days)
- Form submissions attach cookie attribution into lead payload.

## A/B Harness

- Experiments:
  - `hero`: `control` vs `performance_focus`
  - `pricing`: `standard_table` vs `comparison_first`
  - `cta`: `demo_first` vs `book_first`
- Assignment is cookie-based in middleware.
- Variant usage is consumed in route components.
