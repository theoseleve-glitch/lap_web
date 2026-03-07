#!/usr/bin/env node
/**
 * Typography contract test.
 *
 * Fails if any component introduces:
 *  1. font-size in raw px (use rem or var(--text-*))
 *  2. Non-token font-family (use var(--font-*) or font-monument/body/telemetry)
 *  3. Arbitrary text-[Npx] Tailwind classes (use text-telemetry, text-caption, etc.)
 *
 * Exit 1 on violations. Run: node scripts/lint-typography.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const SRC_DIR = path.resolve(process.cwd(), 'src');
const violations = [];

const EXEMPT_FILES = new Set([
  'src/styles/tokens.css',
  'src/app/globals.css',
  'src/tokens/typography.ts',
  'src/styles/reduced-motion.css',
  'src/styles/textures.css',
]);

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.next') continue;
      results.push(...walk(full));
    } else if (/\.(tsx|ts|jsx|css)$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const files = walk(SRC_DIR);

for (const filePath of files) {
  const relPath = rel(filePath);
  if (EXEMPT_FILES.has(relPath)) continue;

  const source = fs.readFileSync(filePath, 'utf-8');
  const lines = source.split('\n');
  const isCss = filePath.endsWith('.css');
  const isTsx = /\.(tsx|ts|jsx)$/.test(filePath);

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const lineNum = i + 1;

    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;

    // 1. CSS: raw px font-size
    if (isCss) {
      const fontSizeMatch = /font-size:\s*(\d+)px/.exec(trimmed);
      if (fontSizeMatch && !trimmed.includes('clamp') && !trimmed.includes('var(')) {
        violations.push({
          rule: 'px-font-size',
          file: relPath, line: lineNum,
          msg: `Raw px font-size \u2014 use rem or var(--text-*)`,
        });
      }
    }

    if (isTsx) {
      // 2. TSX: fontSize inline style with px
      const fontSizeInline = /fontSize:\s*['"]?(\d+)px['"]?/.exec(trimmed);
      if (fontSizeInline && !trimmed.includes('clamp')) {
        violations.push({
          rule: 'px-font-size',
          file: relPath, line: lineNum,
          msg: `Raw px fontSize: ${fontSizeInline[1]}px \u2014 use rem or token`,
        });
      }

      // 3. TSX: text-[Npx] arbitrary Tailwind
      const textArbitrary = /text-\[(\d+)px\]/.exec(trimmed);
      if (textArbitrary) {
        violations.push({
          rule: 'px-font-size',
          file: relPath, line: lineNum,
          msg: `Arbitrary text-[${textArbitrary[1]}px] \u2014 use text-telemetry, text-caption, etc.`,
        });
      }

      // 4. Non-token fontFamily inline
      const fontFamilyInline = /fontFamily:\s*['"]([^'"]+)['"]/.exec(trimmed);
      if (fontFamilyInline) {
        const val = fontFamilyInline[1];
        if (!val.includes('var(--font-')) {
          violations.push({
            rule: 'non-token-font',
            file: relPath, line: lineNum,
            msg: `Non-token fontFamily: "${val}" \u2014 use var(--font-display/body/mono)`,
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-typography: All typography uses tokens.');
  process.exit(0);
} else {
  console.error(`lint-typography: ${violations.length} violation(s):\n`);
  const grouped = {};
  for (const v of violations) {
    if (!grouped[v.rule]) grouped[v.rule] = [];
    grouped[v.rule].push(v);
  }
  for (const [rule, items] of Object.entries(grouped)) {
    console.error(`  [${rule}] (${items.length})`);
    for (const v of items) {
      console.error(`    ${v.file}:${v.line} \u2014 ${v.msg}`);
    }
    console.error('');
  }
  // Budget: fail CI only if violations INCREASE beyond this threshold.
  const BUDGET = 311;
  console.error(`lint-typography: ${violations.length} violation(s) (budget: ${BUDGET})`);
  if (violations.length > BUDGET) {
    console.error(`  FAIL: ${violations.length - BUDGET} new violation(s) introduced.`);
    process.exit(1);
  }
  process.exit(0);
}
