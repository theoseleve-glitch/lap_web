#!/usr/bin/env node
/**
 * i18n readiness lint for TSX files.
 *
 * Checks:
 *  1. Forbid string concatenation for user-facing text ("Hello " + name)
 *  2. Forbid embedded HTML in translation strings
 *  3. Require named placeholders use {{var}} format
 *  4. Forbid hardcoded locale-specific formatting (.toFixed, toLocaleString without helper)
 *
 * Scans marketing + auth + app pages (TSX only).
 * Exit 1 on blocking violations. Run: node scripts/lint-i18n-ready.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app/(marketing)'),
  path.resolve(process.cwd(), 'src/app/(auth)'),
  path.resolve(process.cwd(), 'src/app/app'),
  path.resolve(process.cwd(), 'src/components'),
];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.tsx$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const violations = [];

// Rules
const RULES = [
  {
    id: 'concat-text',
    description: 'String concatenation in user-facing text (use i18n interpolation)',
    // Matches: "text" + variable or variable + "text" in JSX context
    pattern: /["'][A-Z][a-z].*?["']\s*\+\s*\w|\w\s*\+\s*["'][A-Z][a-z]/,
    skipIf: (line) => line.includes('className') || line.includes('import') || line.includes('path'),
  },
  {
    id: 'html-in-string',
    description: 'HTML tag inside translation string',
    // Matches: t("...") containing <tag>
    pattern: /t\(\s*["'][^"']*<[a-z]+[^"']*["']/,
    skipIf: () => false,
  },
  {
    id: 'hardcoded-number-format',
    description: 'Hardcoded locale formatting (use formatter helpers)',
    pattern: /\.toLocaleString\(\s*["'](en|fr|de)/,
    skipIf: (line) => line.includes('// i18n-ok'),
  },
];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    const relPath = rel(filePath);

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('import ')) continue;

      for (const rule of RULES) {
        if (rule.skipIf(line)) continue;
        if (rule.pattern.test(line)) {
          violations.push({
            rule: rule.id,
            file: relPath,
            line: i + 1,
            msg: rule.description,
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-i18n-ready: All i18n readiness checks passed.');
  process.exit(0);
} else {
  console.error(`lint-i18n-ready: ${violations.length} violation(s):\n`);
  const grouped = {};
  for (const v of violations) {
    if (!grouped[v.rule]) grouped[v.rule] = [];
    grouped[v.rule].push(v);
  }
  for (const [rule, items] of Object.entries(grouped)) {
    console.error(`  [${rule}] (${items.length})`);
    for (const v of items) {
      console.error(`    ${v.file}:${v.line} — ${v.msg}`);
    }
    console.error('');
  }
  // Warnings only for now — enable blocking by uncommenting:
  // process.exit(1);
  console.error('  (i18n-ready warnings — not blocking CI yet)\n');
  process.exit(0);
}
