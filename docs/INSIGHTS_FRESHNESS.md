# /insights Freshness Plan

## Cadence

- 2 posts/month minimum
- 1 product update + 1 educational/case study alternating
- Quarterly batch: review all posts, archive stale ones, refresh top performers

## Topic Buckets

| Bucket | Examples | Target frequency |
|--------|----------|-----------------|
| Product updates | New feature launches, UI improvements, plan changes | 1/month |
| Telemetry science | Corner analysis methodology, scoring explained, GPS accuracy | 1/quarter |
| Case studies | Venue ROI stories, driver improvement journeys | 1/quarter |
| Venue ROI | Revenue impact, driver retention metrics, operational efficiency | 1/quarter |
| How-to guides | Upload flow, reading your report, comparing sessions | As needed |

## Internal Link Rules

Each post must include:
- 1 link to `/product` or `/pricing`
- 2 links to related posts (auto-suggested from tag overlap)
- 1 link to a relevant CTA page (`/demo`, `/book`, `/register`)

## Tags

Every post must have 1-3 tags from: `product`, `telemetry`, `case-study`, `venue`, `guide`, `update`.

## Freshness Audit (Quarterly)

- [ ] All posts < 6 months old or marked "evergreen"
- [ ] Posts with outdated pricing/plan names updated
- [ ] Dead internal links fixed
- [ ] Posts with < 50 views/quarter flagged for refresh or archive
- [ ] New related-post links added for recent content
- [ ] Feature names match `feature_names.json` canonical casing

## Insights Index

Maintain `src/data/insights-index.ts` with:
- `slug`, `title`, `date`, `tags[]`, `summary`, `relatedSlugs[]`
- Auto-generate related links from tag overlap (min 2 shared tags)
- Sort by date descending on `/insights` page
