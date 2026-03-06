# LAP Copy Style Guide

## Tone

Direct, technical, confident but never arrogant. Write like a race engineer debriefing a driver — short sentences, concrete outcomes, no fluff.

## Positioning

**Statement**: LAP turns raw telemetry into actionable coaching reports in under a minute, giving every kart and car driver access to professional-grade analysis without data science skills or expensive engineers.

**One-liner** (8–12 words): Upload your session. Get professional coaching in minutes.

**Tagline**: Find Time.

All three live in `src/data/brand.ts`. Reference them — never rewrite them.

## Banned Words

| Banned | Use Instead |
|--------|-------------|
| revolutionary | — (delete the sentence) |
| cutting-edge | proven / validated |
| AI-powered | automated / data-driven |
| game-changing | measurable / concrete |
| seamless | straightforward / simple |
| unlock | access / enable |
| empower | help / give |
| synergy | — (delete) |
| leverage (verb) | use |
| best-in-class | — (delete or prove with data) |
| world-class (adjective outside plan name) | professional-grade |
| next-generation | — (delete) |
| disrupt | — (delete) |
| innovative | — (show, don't tell) |

## Claims Policy

1. Every factual claim must have an entry in `CLAIMS_REGISTRY.csv`.
2. **Provable claims** use present tense: "The pipeline produces deterministic output."
3. **Unprovable / aspirational claims** must be hedged with `may`, `can help`, `is designed to`, or `targets`.
4. **Metrics** must include methodology: sample size, measurement period, baseline.
5. **Testimonials** must be real and attributed (role + context, name optional).

## Hedging Policy

| Confidence Level | Phrasing |
|-----------------|----------|
| Proven (internal test, deterministic) | "produces", "delivers", "scores" |
| Observed (case study, limited sample) | "has helped teams", "in our testing" |
| Designed for (not yet measured) | "is designed to", "aims to" |
| Target (SLA, uptime) | "targets 99.9% uptime" |

## Punctuation

- **Headlines**: Title Case. No period unless a full sentence.
- **Subheads**: Sentence case. No period.
- **Body copy**: Full sentences with periods.
- **CTAs**: UPPERCASE, no period. Max 3 words.
- **Stamps/badges**: UPPERCASE.
- **Lists**: No terminal period unless items are full sentences.

## Casing

| Element | Style |
|---------|-------|
| Product name | LAP (always caps) |
| Plan names | DEMO, RACER, WORLD-CLASS (always caps) |
| Feature names in UI | Title Case |
| Body copy | Sentence case |
| Navigation links | Title Case |
| Footer links | Title Case |

## Numbers

- Spell out one through nine in body copy.
- Use digits for 10+, measurements, and prices.
- Always include units: `25 Hz`, `100 MB`, `€8.99 / mo`.
- Use `–` (en dash) for ranges: `100–500 MB`.
- Prices: `€X.XX` with euro sign prefix, no space.

## Units

| Quantity | Format |
|----------|--------|
| Frequency | `25 Hz` |
| File size | `100 MB`, `8 GB` |
| Time | `under a minute`, `8 minutes`, `3 months` |
| Currency | `€69 / yr`, `€8.99 / mo` |
| Percentage | `36%` |

## Link Style

- Internal links: descriptive text, never "click here".
- External links: open in new tab, add `rel="noopener noreferrer"`.
- CTA buttons: use `StampButton` with explicit `variant="primary"` or `variant="secondary"`.
- Max 1 primary CTA per page. Enforced by `lint-cta-count.mjs`.
