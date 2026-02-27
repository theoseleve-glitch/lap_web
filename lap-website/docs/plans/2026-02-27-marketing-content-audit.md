# Marketing Content Audit

**Date:** 2026-02-27
**Scope:** All marketing pages on lap-coach.racing

---

## Summary

- **23 pages/sections reviewed**
- **47 content issues identified**
- **18 redundancy/consolidation opportunities**
- **12 missing proof-points**
- **8 terminology inconsistencies**

---

## Content Pruning Table

### High Priority (Quick Wins)

| Page | Section | Issue | Action | Proposed Fix |
|------|---------|-------|--------|--------------|
| `/product` | H1 | "LAP Product Workflow Coverage" — internal jargon | Rewrite | "Telemetry Analysis from Upload to Race Strategy" |
| `/pricing` | H1 | "Plans, Eligibility, and Conversion Paths" — internal | Rewrite | "Plans for Drivers, Coaches, and Circuits" |
| `/drivers` | H1 | "Persona Landing" — placeholder text | Rewrite | "For Drivers" (already in data, not in metadata) |
| `/circuits` | H1 | "Persona Landing" — same placeholder | Rewrite | "For Circuits" |
| `/teams` | H1 | "Persona Landing" — same placeholder | Rewrite | "For Teams" |
| `/endurance` | H1 | "Persona Landing" — same placeholder | Rewrite | "For Endurance Programs" |
| All personas | Secondary CTA | Links to `/pricing?persona=X` but pricing page ignores param | Fix routing | Either use param or remove it from URL |
| Site-wide | Terminology | "Drivers" vs "B2C" used interchangeably | Standardize | Use "Drivers" everywhere (more relatable) |
| Site-wide | Terminology | "Circuits" vs "Operators" vs "B2B" | Standardize | Use "Circuits & Teams" for B2B umbrella |
| Site-wide | CTA text | Varies: "Book Demo" / "Start Free" / "Try Demo" / "Book Now" | Standardize | Drivers: "Start Free", B2B: "Book Demo" |

### Medium Priority (Content Improvements)

| Page | Section | Issue | Action |
|------|---------|-------|--------|
| Homepage | S2Proof | "REPEATABLE," "REALISTIC," "CONTEXT-AWARE" — engineer-speak | Translate to outcomes |
| Homepage | S3Product B2B | "BETTER DRIVER OUTCOMES" — no metrics | Add specifics |
| Homepage | PitStop FAQ | "Do you support sim racing?" — no timeline | Add date or remove |
| Homepage | Trust Strip | "99.9% UPTIME TARGET" — no proof link | Link to `/status` |
| Homepage | Trust Strip | "GDPR COMPLIANT" — no link to policy | Link to `/privacy` |
| Pricing | Feature Matrix | "On request" undefined — what triggers it? | Add clarification |
| Pricing | Add-ons | "White-label reporting" — no deliverable details | Define scope |
| Pricing | Premium SLA | "+EUR 690/yr" — no coverage hours defined | Define scope |
| Product | Workflow Tabs | Preview text is filler, no real content shown | Replace with sample |
| Product | Availability | Repeated 3x (modules, claims, sections) | Consolidate to once |

### Low Priority (Long-Term)

| Page | Section | Issue | Action |
|------|---------|-------|--------|
| Site-wide | Social Proof | No customer logos, testimonials, or case studies | Add trust signals |
| Insights | CMS | Only 3 articles — page looks sparse | Expand to 10-15 |
| Endurance | Features | "Fuel windows" mentioned but not visible elsewhere | Verify feature status |
| Contact | Response SLA | "1 business day" claimed — who owns this? | Define process |
| FAQ | "Is my data private?" | Missing data residency and encryption details | Expand answer |
| FAQ | "What data formats?" | "RaceBox exports" unclear (CSV or API?) | Clarify format |

---

## Cross-Cutting Themes

### 1. Missing Social Proof
No customer testimonials, case studies, logos, or usage metrics anywhere on the site. This is the single biggest trust gap for conversion.

### 2. Vague Claims Without Evidence
"Better driver outcomes," "exact corner analysis," "repeatable" — all lack quantitative backing. Each claim should have a specificity bar.

### 3. Incomplete Roadmap Disclosure
Sim telemetry, webhook tiering, endurance module marked "roadmap" with no dates. Creates buyer confusion. Standardize: Available Now / Coming Q2 2026 / Enterprise / Backlog.

### 4. SEO Issues
- Page titles use internal jargon ("Persona Landing," "Conversion Paths")
- Missing Open Graph meta descriptions on persona pages
- H1 tags should describe the page content for search engines

---

## Quick Wins Applied

The following fixes were applied in this session:

1. Fixed persona page eyebrow text ("Persona Landing" → actual titles)
2. Fixed pricing page H1 to be user-facing
3. Fixed product page H1 to be user-facing
4. Updated `.env.local.example` with all required env vars
