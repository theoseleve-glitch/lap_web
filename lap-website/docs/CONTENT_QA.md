# Content QA Checklist

Required before deploying any marketing page change. Enforced via PR template checkbox.

## Pre-Deploy Checks

- [ ] **Spelling/grammar pass** -- Run `npm run lint:spelling` (cspell). Fix all flagged words or add to dictionary.
- [ ] **Link check** -- Run `npm run lint:links`. Zero dead links and zero orphan pages.
- [ ] **Uniqueness lint pass** -- Run `npm run lint:copy`. No duplicate copy blocks across pages (Jaccard > 85%).
- [ ] **Benefit registry check** -- Run `npm run lint:benefits`. All benefit ids respect `allowedPages` scoping.
- [ ] **CTA lint pass** -- Run `npm run lint:cta-text`. All button/link CTAs use CTA_DICTIONARY labels.
- [ ] **CTA count pass** -- Run `npm run lint:cta`. Max 1 primary CTA per page.
- [ ] **Claim proof/hedge check** -- Run `npm run qa:content`. All claims in claim-registry.ts have valid status.
- [ ] **Naming lint pass** -- Run `npm run lint:standards`. No forbidden product name variants.
- [ ] **Plan naming check** -- Run `npm run lint:plan-names`. No B2C/B2B plan cross-mixing.
- [ ] **Units/numbers policy pass** -- Run `npm run lint:standards`. km/h not kph, max 2 decimals, no raw "milliseconds".
- [ ] **Legal dates present** -- All legal pages have `Effective date: YYYY-MM-DD` and `Last updated: YYYY-MM-DD`.
- [ ] **Feature case check** -- Run `npm run lint:feature-case`. Canonical feature name casing used.
- [ ] **Placeholder check** -- Run `npm run lint:placeholders`. No TODO/TBD/lorem/FIXME in production copy.

## Quick All-In-One

```bash
npm run ci
```

This runs: lint, test, build, qa:content, lint:copy, lint:cta, lint:standards, lint:links, lint:placeholders, plus the new linters.

## Automated via CI

The GitHub Actions `ci.yml` workflow runs `npm run ci` on every push and PR. Failures block merge.

## Adding New Benefits

1. Add entry to `src/data/benefits.ts` with unique `BEN-*` id
2. Set `allowedPages` to the pages where this benefit text may appear
3. If the same concept appears on multiple pages with different framing, use `framingOverride: true` and create a separate id

## Adding New CTAs

1. Add the exact label string to `CTA_DICTIONARY` in `src/data/brand.ts`
2. Use the label in `<StampButton>` or `cta=` props exactly as written
