#!/usr/bin/env node
/**
 * Combined copy standards linter.
 *
 * Checks:
 *  1. Product naming (forbidden variants)
 *  2. Punctuation normalization (em dash, ellipsis)
 *  3. Units/numbers format (km/h not kph, EUR format)
 *  4. Legal page dates (ISO format required)
 *
 * Exit 1 on blocking violations. Run: node scripts/lint-copy-standards.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');
const violations = [];

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

function pageName(filePath) {
  const r = path.relative(MARKETING_DIR, filePath).replace(/\\/g, '/');
  return r.replace(/\/page\.(tsx|ts)$/, '').replace(/^page\.(tsx|ts)$/, 'home');
}

// ── Forbidden product name variants ──
const FORBIDDEN_NAMES = [
  'Lap Racing', 'LAP Racing', 'Lap Technologies', 'LAP Technologies',
  'LapCoach', 'lap-coach',
];

// ── Punctuation checks ──
const PUNCTUATION_RULES = [
  { pattern: /--/g, name: 'double-hyphen (use em dash \u2014)' },
  { pattern: /\.{3}(?!\.)/g, name: 'triple-dot (use ellipsis \u2026)' },
];

// ── Units checks ──
const UNITS_RULES = [
  { pattern: /\bkph\b/gi, name: 'kph (use km/h)' },
  { pattern: /\bkmh\b/gi, name: 'kmh (use km/h)' },
  { pattern: /\bKPH\b/g, name: 'KPH (use km/h)' },
];

// ── Legal page date check ──
const LEGAL_PAGES = ['privacy', 'terms', 'dpa', 'subprocessors', 'security'];
const VAGUE_DATE_RE = /(?:Last updated|Effective)[^.]*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}/i;

// ── Process files ──
const files = walk(MARKETING_DIR);

for (const filePath of files) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const relPath = rel(filePath);
  const page = pageName(filePath);
  const lines = source.split('\n');

  // 1. Forbidden product names
  for (const name of FORBIDDEN_NAMES) {
    let searchFrom = 0;
    while (true) {
      const idx = source.indexOf(name, searchFrom);
      if (idx < 0) break;
      searchFrom = idx + name.length;
      const lineNum = source.substring(0, idx).split('\n').length;
      const line = lines[lineNum - 1] || '';
      if (line.trim().startsWith('//') || line.trim().startsWith('*') || line.includes('import')) continue;
      // Skip email addresses and URLs containing the domain name
      if (/[@/]lap-coach\./i.test(line) || /href=/.test(line)) continue;
      violations.push({
        rule: 'naming',
        file: relPath,
        line: lineNum,
        msg: `Forbidden product name "${name}" \u2014 use "LAP" or "Lap Coach"`,
      });
    }
  }

  // 2. Punctuation
  for (const rule of PUNCTUATION_RULES) {
    rule.pattern.lastIndex = 0;
    let m;
    while ((m = rule.pattern.exec(source)) !== null) {
      const lineNum = source.substring(0, m.index).split('\n').length;
      const line = lines[lineNum - 1] || '';
      if (line.trim().startsWith('//') || line.trim().startsWith('*') || line.includes('import')) continue;
      if (line.includes('className') || line.includes('style=') || line.includes('border-') || line.includes('var(--')) continue;
      violations.push({ rule: 'punctuation', file: relPath, line: lineNum, msg: rule.name });
    }
  }

  // 3. Units
  for (const rule of UNITS_RULES) {
    rule.pattern.lastIndex = 0;
    let m;
    while ((m = rule.pattern.exec(source)) !== null) {
      const lineNum = source.substring(0, m.index).split('\n').length;
      violations.push({ rule: 'units', file: relPath, line: lineNum, msg: rule.name });
    }
  }

  // 4. Legal date checks
  if (LEGAL_PAGES.includes(page)) {
    const vague = VAGUE_DATE_RE.exec(source);
    if (vague) {
      const lineNum = source.substring(0, vague.index).split('\n').length;
      violations.push({
        rule: 'legal-date',
        file: relPath,
        line: lineNum,
        msg: `Vague date "${vague[0]}" \u2014 use ISO format YYYY-MM-DD`,
      });
    }
  }
}

// ── Report ──
if (violations.length === 0) {
  console.log('lint-copy-standards: All checks passed.');
  process.exit(0);
} else {
  console.error(`lint-copy-standards: ${violations.length} violation(s):\n`);
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
  const blocking = violations.filter(v => v.rule !== 'legal-date');
  if (blocking.length > 0) {
    process.exit(1);
  } else {
    console.error('  (legal-date warnings only \u2014 not blocking CI)\n');
    process.exit(0);
  }
}
