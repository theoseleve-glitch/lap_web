# Copy Style Guide

Compact reference for all LAP marketing and product copy. Enforced by linters in `scripts/`.

## Tone

- Professional-technical. Confident but not aggressive.
- Second person ("your lap time") preferred over third person.
- Active voice. Short sentences. No filler.
- Never salesy or hyperbolic. Let results speak.

## Product naming

- Product: **LAP** (always uppercase in UI)
- Entity: **Lap Coach** (legal/entity contexts only)
- Forbidden: "Lap Racing", "LAP Racing", "Lap Technologies", "LapCoach", "lap-coach"
- Enforced by `lint-copy-standards.mjs`

## Claims policy

- Every claim must have an entry in `src/data/claim-registry.ts`
- Status `available_now`: state as fact
- Status `enterprise_on_request`: hedge with "available for enterprise" or "on request"
- Status `roadmap`: hedge with "coming soon" or "planned" — never imply current availability
- Enforced by claim_id reference in copy

## Hedging

- Use "helps", "designed to", "can" instead of absolutes ("guarantees", "always", "ensures")
- Exception: factual capabilities (encryption, data isolation) may be stated directly

## Banned words

| Banned | Use instead |
|--------|-------------|
| revolutionize | improve |
| game-changing | effective |
| cutting-edge | modern |
| world-class (as adjective for LAP) | professional-grade |
| synergy | (remove) |
| leverage (as verb) | use |
| utilize | use |
| best-in-class | (remove or cite proof) |
| seamless | smooth / integrated |
| empower | help / enable |

## Punctuation

- Em dash (—) not double hyphen (--)
- Ellipsis (…) not triple dots (...)
- Oxford comma required
- No trailing periods on headings or CTA labels
- Enforced by `lint-copy-standards.mjs`

## Numbers and units

- Speed: km/h (not kph, kmh, KPH)
- Time: 1:32.456 format for lap times
- Percentages: 15% (no space)
- Currency: EUR with symbol (€49/mo)
- Dates: ISO 8601 (2026-03-07) on legal pages

## Casing

- H1: Title Case
- H2/H3: Sentence case
- CTA labels: Sentence case ("Start free", not "START FREE")
- Navigation: Sentence case

## CTAs

- Max 1 primary CTA per page (enforced by `lint-cta-count.mjs`)
- Multiple secondary links allowed
- Labels must come from `CTA_DICTIONARY` in `src/data/brand.ts`
- Primary CTA must match the persona's recommended CTA from `src/data/personas.ts`

## Links

- Internal links: relative paths (`/pricing`, not full URLs)
- External links: open in new tab with `rel="noopener"`
- Email addresses: display as text, not mailto (anti-scrape)
