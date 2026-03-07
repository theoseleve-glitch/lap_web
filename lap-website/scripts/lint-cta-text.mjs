#!/usr/bin/env node
/**
 * CTA text linter.
 *
 * Enforces that button/link text with CTA role uses one of the canonical
 * labels from CTA_DICTIONARY (src/data/brand.ts).
 *
 * Scans for: StampButton, Button with text content, cta props.
 *
 * Exit 1 on non-conforming CTAs. Run: node scripts/lint-cta-text.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const BRAND_FILE = path.resolve(process.cwd(), 'src/data/brand.ts');
const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app/(marketing)'),
  path.resolve(process.cwd(), 'src/app/(auth)'),
  path.resolve(process.cwd(), 'src/app/(free-report)'),
  path.resolve(process.cwd(), 'src/components'),
];

// ── Parse CTA dictionary from brand.ts ──
const brandSrc = fs.readFileSync(BRAND_FILE, 'utf-8');
const ctaMatch = brandSrc.match(/CTA_DICTIONARY\s*=\s*\[([\s\S]*?)\]\s*as\s*const/);
if (!ctaMatch) {
  console.error('lint-cta-text: Cannot parse CTA_DICTIONARY from brand.ts');
  process.exit(1);
}
const ctaLabels = [...ctaMatch[1].matchAll(/'([^']+)'/g)].map(m => m[1]);
const ctaLabelSet = new Set(ctaLabels);

// Allowlist: CTAs that are acceptable but not in the dictionary
const ALLOWLIST = new Set([
  'Submit', 'Cancel', 'Close', 'Back', 'Next', 'Save', 'Delete',
  'Learn more', 'Read more', 'View details', 'Download',
  'TRY DEMO', 'TALK',
  'START FREE // NO CARD REQUIRED // FIRST OUTCOME IN MINUTES',
  '<- RESTART LAP',
  // App-internal billing CTAs (not marketing-facing)
  'Update Payment', 'Resolve Payment', 'Resubscribe', 'Resume Subscription',
  'BOOK A DEMO',
]);

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const violations = [];

const CTA_PATTERNS = [
  // Single-line JSX children only (avoids multi-line false positives)
  /<(?:StampButton|Button)[^>]*>([^<\n]{2,})<\/(?:StampButton|Button)>/g,
  /cta[=:]\s*["']([^"']+)["']/g,
];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    const source = fs.readFileSync(filePath, 'utf-8');
    const relPath = rel(filePath);
    const lines = source.split('\n');

    for (const pattern of CTA_PATTERNS) {
      pattern.lastIndex = 0;
      let m;
      while ((m = pattern.exec(source)) !== null) {
        const ctaText = m[1].trim();
        if (!ctaText) continue;
        if (ctaLabelSet.has(ctaText)) continue;
        if (ALLOWLIST.has(ctaText)) continue;
        if (ctaText.startsWith('{') || ctaText.includes('{')) continue;

        const lineNum = source.substring(0, m.index).split('\n').length;
        const line = lines[lineNum - 1] || '';
        if (line.trim().startsWith('//') || line.trim().startsWith('*')) continue;
        if (line.includes('import ')) continue;

        const ciMatch = ctaLabels.find(l => l.toLowerCase() === ctaText.toLowerCase());
        if (ciMatch) {
          violations.push({
            file: relPath, line: lineNum,
            msg: `CTA "${ctaText}" has wrong casing \u2014 use "${ciMatch}"`,
            severity: 'casing',
          });
        } else {
          violations.push({
            file: relPath, line: lineNum,
            msg: `CTA "${ctaText}" is not in CTA_DICTIONARY \u2014 allowed: ${ctaLabels.join(', ')}`,
            severity: 'unknown',
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log(`lint-cta-text: All CTAs match dictionary (${ctaLabels.length} canonical labels).`);
  process.exit(0);
} else {
  const casing = violations.filter(v => v.severity === 'casing');
  const unknown = violations.filter(v => v.severity === 'unknown');

  console.error(`lint-cta-text: ${violations.length} non-conforming CTA(s):\n`);
  if (unknown.length > 0) {
    console.error(`  [unknown] (${unknown.length})`);
    for (const v of unknown) console.error(`    ${v.file}:${v.line} \u2014 ${v.msg}`);
    console.error('');
  }
  if (casing.length > 0) {
    console.error(`  [casing] (${casing.length})`);
    for (const v of casing) console.error(`    ${v.file}:${v.line} \u2014 ${v.msg}`);
    console.error('');
  }

  if (unknown.length > 0) {
    process.exit(1);
  } else {
    console.error('  (casing warnings only \u2014 not blocking CI)\n');
    process.exit(0);
  }
}
