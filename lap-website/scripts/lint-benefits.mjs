#!/usr/bin/env node
/**
 * Benefits registry linter.
 *
 * Validates that benefit bullet ids used in marketing pages match
 * the benefits registry (src/data/benefits.ts) and respect page scoping.
 *
 * Checks:
 *  1. Duplicate benefit ids in the registry
 *  2. Benefit text reused across pages without framingOverride
 *  3. Benefit id used on a page not in its allowedPages list
 *
 * Exit 1 on violations. Run: node scripts/lint-benefits.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');
const BENEFITS_FILE = path.resolve(process.cwd(), 'src/data/benefits.ts');

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

// ── Parse benefits registry ──
const benefitsSrc = fs.readFileSync(BENEFITS_FILE, 'utf-8');

// Extract benefit entries
const benefitIdRe = /id:\s*'([^']+)'/g;
const benefitTextRe = /text:\s*'([^']+)'/g;
const allowedPagesRe = /allowedPages:\s*\[([^\]]*)\]/g;
const framingRe = /framingOverride:\s*true/g;

const ids = [...benefitsSrc.matchAll(benefitIdRe)].map(m => m[1]);
const texts = [...benefitsSrc.matchAll(benefitTextRe)].map(m => m[1]);
const pageGroups = [...benefitsSrc.matchAll(allowedPagesRe)].map(m =>
  [...m[1].matchAll(/'([^']+)'/g)].map(pm => pm[1])
);

// Count framingOverride entries by scanning the block structure
const blocks = benefitsSrc.split(/\{[\s\n]+id:/);
blocks.shift(); // remove preamble
const hasFraming = blocks.map(b => /framingOverride:\s*true/.test(b));

const violations = [];

// 1. Check for duplicate ids in registry
const idCounts = new Map();
for (const id of ids) {
  idCounts.set(id, (idCounts.get(id) || 0) + 1);
}
for (const [id, count] of idCounts) {
  if (count > 1) {
    violations.push({
      rule: 'duplicate-id',
      msg: `Duplicate benefit id "${id}" appears ${count} times in registry`,
    });
  }
}

// 2. Check for duplicate texts without framingOverride
const textToEntries = new Map();
for (let i = 0; i < texts.length; i++) {
  const norm = texts[i].toLowerCase().trim();
  if (!textToEntries.has(norm)) textToEntries.set(norm, []);
  textToEntries.get(norm).push({ id: ids[i], pages: pageGroups[i] || [], framing: hasFraming[i] });
}

for (const [text, entries] of textToEntries) {
  if (entries.length > 1) {
    const withoutFraming = entries.filter(e => !e.framing);
    if (withoutFraming.length > 1) {
      violations.push({
        rule: 'duplicate-text',
        msg: `Benefit text "${text.slice(0, 60)}..." shared by ids ${entries.map(e => e.id).join(', ')} without framingOverride`,
      });
    }
  }
}

// 3. Scan marketing pages for benefit text used outside allowedPages
const benefitMap = new Map();
for (let i = 0; i < ids.length; i++) {
  benefitMap.set(ids[i], {
    text: texts[i],
    allowedPages: pageGroups[i] || [],
    framing: hasFraming[i],
  });
}

const files = walk(MARKETING_DIR);

for (const filePath of files) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const page = pageName(filePath);
  const relPath = rel(filePath);

  for (const [id, benefit] of benefitMap) {
    // Check if this benefit text appears on this page
    if (source.includes(benefit.text)) {
      if (!benefit.allowedPages.includes(page)) {
        violations.push({
          rule: 'page-scope',
          msg: `Benefit "${id}" used on page "${page}" but only allowed on [${benefit.allowedPages.join(', ')}] — ${relPath}`,
        });
      }
    }
  }
}

// ── Report ──
if (violations.length === 0) {
  console.log(`lint-benefits: All ${ids.length} benefits pass registry checks.`);
  process.exit(0);
} else {
  console.error(`lint-benefits: ${violations.length} violation(s):\n`);
  for (const v of violations) {
    console.error(`  [${v.rule}] ${v.msg}`);
  }
  process.exit(1);
}
