#!/usr/bin/env node
/**
 * Plan naming cross-mix linter.
 *
 * Enforces that B2C pages do not mention B2B plan tokens and vice versa,
 * unless the page is in the allowed cross-reference list (brand.ts).
 *
 * Exit 1 on cross-mix violations. Run: node scripts/lint-plan-names.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');
const BRAND_FILE = path.resolve(process.cwd(), 'src/data/brand.ts');

const brandSrc = fs.readFileSync(BRAND_FILE, 'utf-8');

function parseArray(name) {
  const match = brandSrc.match(new RegExp(`${name}\\s*=\\s*\\[([\\s\\S]*?)\\]\\s*as\\s*const`));
  if (!match) return [];
  return [...match[1].matchAll(/'([^']+)'/g)].map(m => m[1]);
}

const B2C_PLANS = parseArray('B2C_PLANS');
const B2B_PLANS = parseArray('B2B_PLANS');
const B2B_ALLOWED = parseArray('B2B_ALLOWED_PAGES');
const B2C_ALLOWED = parseArray('B2C_ALLOWED_PAGES');

// Legal/compliance pages may reference any plan name in context
const EXEMPT_PAGES = new Set([
  'terms', 'privacy', 'dpa', 'subprocessors', 'security', 'status',
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

function pageName(filePath) {
  const r = path.relative(MARKETING_DIR, filePath).replace(/\\/g, '/');
  return r.replace(/\/page\.(tsx|ts)$/, '').replace(/^page\.(tsx|ts)$/, 'home');
}

const violations = [];
const files = walk(MARKETING_DIR);

for (const filePath of files) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const page = pageName(filePath);
  const relPath = rel(filePath);
  const lines = source.split('\n');

  if (!B2B_ALLOWED.includes(page) && !EXEMPT_PAGES.has(page)) {
    for (const plan of B2B_PLANS) {
      const re = new RegExp(`\\b${plan.replace(/\s+/g, '\\s+')}\\b`, 'gi');
      let m;
      while ((m = re.exec(source)) !== null) {
        const lineNum = source.substring(0, m.index).split('\n').length;
        const line = lines[lineNum - 1] || '';
        if (line.trim().startsWith('//') || line.trim().startsWith('*') || line.includes('import')) continue;
        violations.push({
          rule: 'b2b-on-b2c',
          file: relPath, line: lineNum,
          msg: `B2B plan "${plan}" on page "${page}" \u2014 only allowed on [${B2B_ALLOWED.join(', ')}]`,
        });
      }
    }
  }

  if (!B2C_ALLOWED.includes(page) && !EXEMPT_PAGES.has(page)) {
    for (const plan of B2C_PLANS.filter(p => p === 'World-Class')) {
      const re = new RegExp(`\\b${plan}\\b`, 'gi');
      let m;
      while ((m = re.exec(source)) !== null) {
        const lineNum = source.substring(0, m.index).split('\n').length;
        const line = lines[lineNum - 1] || '';
        if (line.trim().startsWith('//') || line.trim().startsWith('*') || line.includes('import')) continue;
        if (/Go World-Class/.test(line)) continue;
        violations.push({
          rule: 'b2c-on-b2b',
          file: relPath, line: lineNum,
          msg: `B2C plan "${plan}" on page "${page}" \u2014 only allowed on [${B2C_ALLOWED.join(', ')}]`,
        });
      }
    }
  }
}

if (violations.length === 0) {
  console.log(`lint-plan-names: No plan name cross-mixing (B2C: ${B2C_PLANS.join('/')}, B2B: ${B2B_PLANS.join('/')}).`);
  process.exit(0);
} else {
  console.error(`lint-plan-names: ${violations.length} cross-mix violation(s):\n`);
  for (const v of violations) {
    console.error(`  [${v.rule}] ${v.file}:${v.line} \u2014 ${v.msg}`);
  }
  process.exit(1);
}
