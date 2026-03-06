#!/usr/bin/env node
/**
 * Build-time lint: enforces max 1 primary CTA per marketing page.
 *
 * Counts StampButton usage with variant="primary" (or no variant, since default is primary).
 * Allows multiple variant="secondary" buttons.
 *
 * Exit code 1 if any page has >1 primary CTA.
 *
 * Usage: node scripts/lint-cta-count.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/page\.(tsx|ts|jsx|js)$/.test(entry.name)) results.push(full);
  }
  return results;
}

const violations = [];
const pages = walk(MARKETING_DIR);

for (const pagePath of pages) {
  const source = fs.readFileSync(pagePath, 'utf-8');
  const relPath = path.relative(process.cwd(), pagePath).replace(/\\/g, '/');

  // Count StampButton without variant (defaults to primary) or with variant="primary"
  const stampRe = /<StampButton\b([^>]*)>/g;
  let primaryCount = 0;
  let m;
  while ((m = stampRe.exec(source)) !== null) {
    const attrs = m[1];
    if (/variant=["']secondary["']/.test(attrs)) continue;
    primaryCount++;
  }

  if (primaryCount > 1) {
    violations.push({ file: relPath, count: primaryCount });
  }
}

if (violations.length === 0) {
  console.log('lint-cta-count: All pages have <= 1 primary CTA.');
  process.exit(0);
} else {
  console.error(`lint-cta-count: ${violations.length} page(s) with >1 primary CTA:\n`);
  for (const v of violations) {
    console.error(`  ${v.file}: ${v.count} primary CTAs (max 1)`);
  }
  process.exit(1);
}
