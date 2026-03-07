#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [path.resolve(process.cwd(), 'src/app')];

function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (entry.name === 'page.tsx') results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    const source = fs.readFileSync(filePath, 'utf-8');
    const file = rel(filePath);

    const h1Matches = [...source.matchAll(/<h1[\s>]/g)];
    const pageIntroMatches = [...source.matchAll(/<PageIntro[\s/]/g)];
    const h1Count = h1Matches.length + pageIntroMatches.length;

    if (h1Count === 0) {
      violations.push({ file, line: 1, rule: 'heading:missing-h1', context: 'No <h1> or <PageIntro>' });
    } else if (h1Count > 1) {
      violations.push({ file, line: 1, rule: 'heading:multiple-h1', context: `Found ${h1Count} H1-level elements` });
    }

    const headings = [];
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineHRe = /<h([1-6])[\s>]/g;
      let match;
      while ((match = lineHRe.exec(line)) !== null) {
        headings.push({ level: parseInt(match[1], 10), line: i + 1 });
      }
      if (/<PageIntro[\s/]/.test(line)) {
        headings.push({ level: 1, line: i + 1 });
      }
    }

    for (let i = 1; i < headings.length; i++) {
      const gap = headings[i].level - headings[i - 1].level;
      if (gap > 1) {
        violations.push({
          file,
          line: headings[i].line,
          rule: 'heading:level-skip',
          context: `h${headings[i - 1].level} -> h${headings[i].level} (skipped ${gap - 1} level(s))`,
        });
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-heading-hierarchy: No violations. All clear.');
  process.exit(0);
}

const BUDGET = 10;
console.warn(`lint-heading-hierarchy: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.warn(`  ${v.file}:${v.line} -- ${v.rule} -- ${v.context}`);
}

if (violations.length > BUDGET) {
  console.error(`\n  FAIL: ${violations.length} exceeds budget of ${BUDGET}`);
  process.exit(1);
} else {
  console.warn(`\n  OK: within budget (${BUDGET - violations.length} remaining)`);
  process.exit(0);
}
