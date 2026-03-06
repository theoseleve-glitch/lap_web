#!/usr/bin/env node
/**
 * FAQ de-duplication linter.
 *
 * Ensures:
 *  1. FAQ questions in en.json match registry entries
 *  2. No near-duplicate questions across the registry
 *
 * Run: node scripts/lint-faq.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const EN_FILE = path.resolve(process.cwd(), 'src/i18n/en.json');
const REGISTRY_FILE = path.resolve(process.cwd(), 'src/content/faq-registry.ts');

const violations = [];

// 1. Check i18n FAQ keys match registry
const enData = JSON.parse(fs.readFileSync(EN_FILE, 'utf-8'));
const faqKeys = Object.entries(enData)
  .filter(([k]) => k.startsWith('faq.q'))
  .map(([k, v]) => ({ key: k, text: v }));

// Read registry source to find questions
const registrySrc = fs.readFileSync(REGISTRY_FILE, 'utf-8');
const registryQuestions = [];
const qRe = /question:\s*'([^']+)'/g;
let m;
while ((m = qRe.exec(registrySrc)) !== null) registryQuestions.push(m[1]);

for (const faq of faqKeys) {
  const normalized = faq.text.toLowerCase().trim().replace(/[?.!]/g, '');
  const found = registryQuestions.some(
    (rq) => rq.toLowerCase().trim().replace(/[?.!]/g, '') === normalized,
  );
  if (!found) {
    violations.push({
      rule: 'unregistered-faq',
      msg: `FAQ key "${faq.key}" ("${faq.text}") not in faq-registry.ts`,
    });
  }
}

// 2. Check for near-duplicate questions in registry
function trigrams(str) {
  const s = str.toLowerCase().replace(/[^a-z0-9 ]/g, '');
  const set = new Set();
  for (let i = 0; i <= s.length - 3; i++) set.add(s.substring(i, i + 3));
  return set;
}

function jaccard(a, b) {
  const intersection = new Set([...a].filter((x) => b.has(x)));
  const union = new Set([...a, ...b]);
  return union.size === 0 ? 0 : intersection.size / union.size;
}

const DUPLICATE_THRESHOLD = 0.75;

for (let i = 0; i < registryQuestions.length; i++) {
  const triA = trigrams(registryQuestions[i]);
  for (let j = i + 1; j < registryQuestions.length; j++) {
    const triB = trigrams(registryQuestions[j]);
    const sim = jaccard(triA, triB);
    if (sim >= DUPLICATE_THRESHOLD) {
      violations.push({
        rule: 'duplicate-faq',
        msg: `Near-duplicate (${(sim * 100).toFixed(0)}%): "${registryQuestions[i]}" / "${registryQuestions[j]}"`,
      });
    }
  }
}

if (violations.length === 0) {
  console.log(`lint-faq: ${registryQuestions.length} FAQs validated. No duplicates.`);
  process.exit(0);
} else {
  console.error(`lint-faq: ${violations.length} violation(s):\n`);
  for (const v of violations) {
    console.error(`  [${v.rule}] ${v.msg}`);
  }
  // Warnings for now
  console.error('\n  (faq warnings, not blocking CI yet)\n');
  process.exit(0);
}
