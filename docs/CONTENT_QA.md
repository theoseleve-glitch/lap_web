# Content QA Checklist

Required before every marketing page deploy. Copy into PR description and check each item.

## Pre-Deploy Checklist

- [ ] **Spelling/grammar** — Manual pass on all new/changed copy
- [ ] **Link check** — `npm run lint:links` passes (no dead links, no orphans)
- [ ] **Uniqueness lint** — `npm run lint:copy` passes (no duplicate copy blocks)
- [ ] **CTA lint** — `npm run lint:cta` passes (max 1 primary CTA per page)
- [ ] **Copy standards** — `npm run lint:standards` passes (naming, punctuation, units)
- [ ] **Claim proof/hedge** — Every factual claim has an entry in `CLAIMS_REGISTRY.csv` with status `approved` or `needs_hedge`
- [ ] **Naming** — Product is "LAP", entity is "Lap Coach", plans are Demo/Racer/World-Class
- [ ] **Units/numbers** — Uses km/h (not kph), EUR with `€` prefix, ISO dates on legal pages
- [ ] **Legal dates** — All legal pages have `Effective: YYYY-MM-DD` and `Last updated: YYYY-MM-DD`
- [ ] **Benefits registry** — New benefit bullets added to `src/data/benefits.ts` with unique id and page scope
- [ ] **Glossary** — Telemetry terms match `GLOSSARY.md` canonical phrasing
- [ ] **Brand constants** — Hero, meta, OG, footer reference `brand.ts` — no hardcoded synonyms

## Automated (CI)

These run automatically on `npm run ci`:

| Check | Script | Blocks CI |
|-------|--------|-----------|
| Duplicate copy | `npm run lint:copy` | Yes |
| CTA count | `npm run lint:cta` | Yes |
| Copy standards | `npm run lint:standards` | Yes (except legal-date warnings) |
| Internal links | `npm run lint:links` | Yes |
| Content QA | `npm run qa:content` | Yes |

## How to Fix Common Failures

**Duplicate copy**: Rewrite one instance with unique framing. Same benefit for different audiences needs a different `benefit_id` in `benefits.ts`.

**CTA count**: Mark secondary CTAs with `variant="secondary"` on `StampButton`.

**Naming violation**: Replace forbidden product name with "LAP" (product) or "Lap Coach" (entity).

**Legal date**: Change "Last updated: February 2026" to "Last updated: 2026-02-01".
