#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIR = path.resolve(process.cwd(), 'src');
const EXEMPT_FILES = new Set([
  'src/lib/site-url.ts',
  'src/__tests__/billing-checkout-origin.test.ts',
  'src/__tests__/seo.test.ts',
  'src/__tests__/site-url-config.test.ts',
]);

const DOMAIN_RE = /https?:\/\/(?:www\.)?lap-coach\.racing|https?:\/\/lap\.racing/g;

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.next') continue;
      results.push(...walk(full));
    } else if (/\.(ts|tsx|js|mjs)$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

const violations = [];

for (const filePath of walk(SCAN_DIR)) {
  const relative = path.relative(process.cwd(), filePath).replace(/\\/g, '/');
  if (EXEMPT_FILES.has(relative)) continue;

  const source = fs.readFileSync(filePath, 'utf-8');
  const lines = source.split('\n');

  for (let i = 0; i < lines.length; i++) {
    const matches = lines[i].match(DOMAIN_RE);
    if (matches) {
      for (const m of matches) {
        violations.push({ file: relative, line: i + 1, match: m });
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-canonical: No hardcoded domain references outside site-url.ts. All clear.');
  process.exit(0);
}

console.error(`lint-canonical: ${violations.length} hardcoded domain reference(s):\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line} -- ${v.match}`);
}
console.error('\n  Use getSiteUrl() from @/lib/site-url instead.');
process.exit(1);
