## Summary

<!-- Brief description of changes -->

## Content QA Checklist

> Required for any PR that touches marketing pages, copy, or content data files.

- [ ] `npm run lint:spelling` -- no spelling errors
- [ ] `npm run lint:links` -- no dead links or orphans
- [ ] `npm run lint:copy` -- no duplicate copy blocks
- [ ] `npm run lint:benefits` -- benefits respect page scoping
- [ ] `npm run lint:cta-text` -- CTAs match CTA_DICTIONARY
- [ ] `npm run lint:cta` -- max 1 primary CTA per page
- [ ] `npm run qa:content` -- claims registry consistent
- [ ] `npm run lint:standards` -- naming, punctuation, units, numbers, legal dates
- [ ] `npm run lint:plan-names` -- no B2C/B2B plan cross-mixing
- [ ] `npm run lint:placeholders` -- no placeholder text

Or run all at once: `npm run ci`

## Test Plan

<!-- How to verify these changes -->
