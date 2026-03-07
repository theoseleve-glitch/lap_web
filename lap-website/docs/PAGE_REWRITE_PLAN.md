# Page JTBD Rewrite Plan

Each marketing page must have a unique Job-To-Be-Done. No two pages share the same JTBD sentence. Cross-reference with `src/data/personas.ts` for persona targeting.

| Page | Unique JTBD | Unique example / proof | Primary CTA |
|------|------------|----------------------|-------------|
| `/` (home) | Discover that professional telemetry analysis is now accessible to every driver | Hero animation showing CSV → coaching report in under 60 seconds | Start free |
| `/product` | Understand what LAP analyses and how corner-by-corner coaching works | Interactive corner breakdown: entry speed, apex, exit — with before/after delta | See pricing |
| `/pricing` | Compare plans and choose the right tier for my usage level | Side-by-side plan cards with session limits, feature matrix, and annual savings | Start free |
| `/demo` | Experience the analysis on my own data before committing | Upload form with instant free report (limited to 1 session) | Start free |
| `/customers` | See proof that drivers like me have improved with LAP | Coach testimonial: "5-minute debriefs instead of 45" + junior team case study | Request demo |
| `/contact` | Reach the team for enterprise, venue, or custom needs | Contact form with plan selector (B2B/enterprise pre-selected) | Send message |
| `/book` | Schedule a live walkthrough with a product specialist | Calendar embed or booking link with availability | Book session |
| `/waitlist` | Register interest for sim racing or upcoming features | Email capture with feature interest checkboxes | Join waitlist |
| `/insights` | Learn telemetry analysis techniques to get more from my data | Article index with categories: corner technique, data interpretation, race prep | (none — content hub) |
| `/insights/[slug]` | Apply a specific telemetry technique to improve a measurable skill | Step-by-step guide with annotated chart screenshots | Start free |
| `/privacy` | Understand what data LAP collects and how it is protected | Cookie table, retention periods, data subject rights summary | (none — legal) |
| `/terms` | Review the legal terms governing use of the LAP service | Plain-language terms with highlighted key clauses | (none — legal) |
| `/security` | Verify that LAP meets my organisation's security requirements | Encryption specs, RLS isolation, incident response SLAs | Contact sales |
| `/dpa` | Obtain a Data Processing Addendum for my organisation's compliance needs | 11-section DPA with "Request signed DPA" CTA | Request demo |
| `/subprocessors` | Review which third parties process data on LAP's behalf | Table of sub-processors with data location and purpose | (none — legal) |
| `/billing` | Manage my subscription, view invoices, or change plan | (app-gated — redirects to authenticated billing page) | Open app |
| `/status` | Check current system availability and incident history | Status indicators for API, frontend, database, workers | (none — status) |
